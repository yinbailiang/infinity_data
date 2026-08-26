"""产物发射层：Python / std → 输出格式（JSON / YAML / TOML）。

职责边界（与 semantic 层严格分离）：

- **内部表示**（忠实双向，语义最小丢失）：:func:`~infinity_data.semantic.std.python_to_std`
  与 :func:`~infinity_data.semantic.std.std_to_python`——path 保持
  :class:`PurePosixPath`、float 保持 :class:`decimal.Decimal`、noexist 经
  :data:`~infinity_data.semantic.std.NOEXIST` 哨兵保留三态。
  流水线内部（如 :class:`~infinity_data.pipeline.CompilationResult.value`）一律走该层。
- **本层（emit）**：做**有损投影**供输出格式消费，无需担心完整性——
  path → POSIX 字符串；Decimal 的 NaN / ±Infinity 等特殊编码由本层按
  :class:`EmitConfig` 决定（``full_float`` 标记编码）。

入口：
- :func:`to_json` / :func:`to_yaml` / :func:`to_toml`：输出文本（接受 std 或 Python 值）
- :func:`project_output`：纯 Python 值的轻量有损投影（path → 字符串）
"""

from __future__ import annotations

import importlib
import json
from decimal import Decimal, InvalidOperation
from pathlib import PurePath, PurePosixPath
from typing import Any, cast

from infinity_data.emit.config import EmitConfig
from infinity_data.semantic.std import NOEXIST, StdPythonValue, is_std_value, std_to_python

__all__ = [
    'dump_to_json',
    'load_from_json',
    'project_output',
    'restore_python',
    'to_json',
    'to_yaml',
    'to_toml',
]

# ── 自描述标记（输出格式无法原生表达的值的编码） ──────


def _decimal_marker(dec: Any) -> dict[str, str]:
    """Decimal 自描述标记：``{"__type__": "decimal", "num": "<十进制字符串>"}``。"""
    return {'__type__': 'decimal', 'num': str(dec)}


def _path_marker(s: str) -> dict[str, str]:
    """路径自描述标记：``{"__type__": "path", "path": "<POSIX 字符串>"}``。"""
    return {'__type__': 'path', 'path': s}


def _noexist_marker() -> dict[str, str]:
    """noexist 自描述标记：``{"__type__": "noexist"}``。"""
    return {'__type__': 'noexist'}


# ── 标记还原（反向：加载的原始 dict → StdPythonValue） ────


def _restore_marker(value: dict[Any, Any]) -> Any | None:
    """若 dict 是 emit 自描述标记则还原为 Python 值，否则 None（非标记）。

    仅识别 emit 层产出的**精确标记形状**；结构不符（额外键 / 负载非字符串 /
    数值无法解析）一律视为普通 dict（返回 None，尽力而为）。
    """
    typ = value.get('__type__')
    if typ == 'decimal':
        if set(value) == {'__type__', 'num'} and isinstance(value.get('num'), str):
            try:
                return Decimal(value['num'])
            except (InvalidOperation, ValueError, TypeError):
                return None
        return None
    if typ == 'path':
        if set(value) == {'__type__', 'path'} and isinstance(value.get('path'), str):
            return PurePosixPath(value['path'])
        return None
    if typ == 'noexist':
        if set(value) == {'__type__'}:
            return NOEXIST
        return None
    return None


def restore_python(value: Any) -> StdPythonValue:
    """从加载的原始 dict（含可选 emit 自描述标记）**尝试**还原为 StdPythonValue。

    - ``{"__type__": "decimal", "num": "..."}`` → :class:`decimal.Decimal`
    - ``{"__type__": "path", "path": "..."}`` → :class:`PurePosixPath`
    - ``{"__type__": "noexist"}`` → :data:`NOEXIST`
    - 普通 ``float`` → :class:`decimal.Decimal`（忠实形式，与
      :func:`~infinity_data.semantic.std.python_to_std` 规范一致）
    - int / bool / str / None 原样；dict / list 递归
    - 识别不了的形状（含疑似标记但结构不符）按普通 dict / list 保留（尽力而为）

    配合 :func:`to_json` 等 + ``EmitConfig(full_float=True, full_path=True,
    keep_noexist=True)`` 可实现「std → 输出文本 → 加载 → StdPythonValue」
    无损闭环（再经 :func:`~infinity_data.semantic.std.python_to_std` 回 std）。
    """
    if isinstance(value, dict):
        obj = cast(dict[Any, Any], value)
        marker = _restore_marker(obj)
        if marker is not None:
            return marker
        return {str(k): restore_python(v) for k, v in obj.items()}
    if isinstance(value, list):
        arr = cast(list[Any], value)
        return [restore_python(v) for v in arr]
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return Decimal(str(value))
    return value


# ── 序列化核心 ──────────────────────────────────────


def _to_serializable(value: Any, config: EmitConfig) -> Any:
    """std 或 Python 值 → 可序列化结构（按 config 做有损投影）。"""
    if is_std_value(value):
        # std 输入：忠实转 Python（noexist 按需保留为 NOEXIST 哨兵），再投影
        py = std_to_python(value, keep_noexist=config.keep_noexist)
        return _serializable(py, config)
    # Python 输入（如 CompilationResult.value）：直接投影
    return _serializable(value, config)


def _serializable(value: Any, config: EmitConfig) -> Any:
    """Python 值 → 可序列化结构（递归有损投影）。

    - :data:`NOEXIST` 哨兵 → ``{"__type__": "noexist"}``
    - :class:`PurePath` → POSIX 字符串
    - :class:`decimal.Decimal` → 按 ``full_float`` 编码（有限值默认 JSON 数字）
    - dict / list 递归；其余（int / bool / str / None 等）原样
    """
    if value is NOEXIST:
        return _noexist_marker()
    if isinstance(value, PurePath):
        s = value.as_posix()
        return _path_marker(s) if config.full_path else s
    if isinstance(value, dict):
        obj = cast(dict[Any, Any], value)
        return {k: _serializable(v, config) for k, v in obj.items()}
    if isinstance(value, list):
        arr = cast(list[Any], value)
        return [_serializable(v, config) for v in arr]
    if isinstance(value, Decimal):
        return _decimal_serializable(value, config)
    return value


def _decimal_serializable(dec: Any, config: EmitConfig) -> Any:
    """Decimal → 可序列化形式。

    - ``full_float`` → 自描述标记（无损）
    - 否则：有限值 → JSON 数字（整值转 int，避免 ``1.0``；溢出回退标记）；
      NaN / ±Infinity 无法用 JSON 数字表达 → 自描述标记
    """
    if config.full_float:
        return _decimal_marker(dec)
    if dec.is_nan() or dec.is_infinite():
        return _decimal_marker(dec)
    try:
        if dec == dec.to_integral_value():
            return int(dec)
        return float(dec)
    except (OverflowError, ValueError):
        return _decimal_marker(dec)


# ── 输出入口 ────────────────────────────────────────


def to_json(value: Any, *, config: EmitConfig | None = None) -> str:
    """std 或 Python 值 → JSON 文本。

    ``value`` 可为 :class:`~infinity_data.semantic.std.StdValue`（如
    ``CompilationResult.document.root``，支持完整选项）或 Python 值
    （如 ``CompilationResult.value``，noexist 信息已在转换时丢失）。
    """
    cfg = config or EmitConfig()
    data = _to_serializable(value, cfg)
    return json.dumps(data, indent=cfg.indent, sort_keys=cfg.sort_keys, ensure_ascii=cfg.ensure_ascii)


def to_yaml(value: Any, *, config: EmitConfig | None = None) -> str:
    """std 或 Python 值 → YAML 文本（需安装 PyYAML）。"""
    cfg = config or EmitConfig()
    data = _to_serializable(value, cfg)
    try:
        yaml = importlib.import_module('yaml')
    except ImportError as exc:  # pragma: no cover - 依赖缺失路径
        raise ImportError('to_yaml 需要 PyYAML（pip install pyyaml）') from exc
    return yaml.safe_dump(data, allow_unicode=not cfg.ensure_ascii, sort_keys=cfg.sort_keys)


def to_toml(value: Any, *, config: EmitConfig | None = None) -> str:
    """std 或 Python 值 → TOML 文本（需安装 tomli-w）。"""
    cfg = config or EmitConfig()
    data = _to_serializable(value, cfg)
    try:
        tomli_w = importlib.import_module('tomli_w')
    except ImportError as exc:  # pragma: no cover - 依赖缺失路径
        raise NotImplementedError('to_toml 需要 tomli-w（pip install tomli-w）；当前未安装') from exc
    return tomli_w.dumps(data)


# ── 便捷自由函数（默认尝试保留一切语义） ────────────


def dump_to_json(value: Any, *, config: EmitConfig | None = None) -> str:
    """std / Python 值 → JSON 文本（便捷入口，**默认保留一切语义**）。

    默认等价 ``EmitConfig(full_float=True, full_path=True, keep_noexist=True)``——
    Decimal / PurePosixPath / noexist 以 ``{"__type__": ...}`` 标记编码；
    传入 ``config`` 可覆盖（关闭标记、改缩进等，见 :class:`EmitConfig`）。

    与 :func:`load_from_json` 配对可实现「std → JSON → StdPythonValue」无损闭环。
    """
    cfg = config or EmitConfig(full_float=True, full_path=True, keep_noexist=True)
    return to_json(value, config=cfg)


def load_from_json(text: str) -> StdPythonValue:
    """JSON 文本 → StdPythonValue（便捷入口，**默认尝试还原全部语义**）。

    解析后经 :func:`restore_python`：``{"__type__": ...}`` 标记还原为
    Decimal / PurePosixPath / NOEXIST，普通 float 归一到 Decimal；
    识别不了的形状原样保留（尽力而为）。
    """
    return restore_python(json.loads(text))


# ── 轻量有损投影（纯 Python 值） ─────────────────────


def project_output(value: Any) -> Any:
    """Python 值 → 输出友好投影（递归，有损，无配置）。

    - :class:`PurePath`（含 :class:`PurePosixPath`）→ POSIX 字符串
    - dict / list 递归投影；其余（int / Decimal / bool / str / None 等）原样保留

    完整选项（Decimal 编码 / noexist 标记）请用 :func:`to_json` 等带
    :class:`EmitConfig` 的入口。
    """
    if isinstance(value, PurePath):
        return value.as_posix()
    if isinstance(value, dict):
        obj = cast(dict[Any, Any], value)
        return {k: project_output(v) for k, v in obj.items()}
    if isinstance(value, list):
        arr = cast(list[Any], value)
        return [project_output(v) for v in arr]
    return value
