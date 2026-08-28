"""格式渲染与点分路径提取（infd-cov 的数据转换层）。

与 :mod:`infinity_data.tools.cov.cli`（流程层）分离：本模块只负责
「已编译的 Python 值 → 目标格式文本」与路径投影，不接触编译/CLI。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from infinity_data.emit import EmitConfig, plain_yaml, to_json, to_toml

__all__ = ['FORMATS', 'DEFAULT_FORMAT', 'extract_path', 'render']

FORMATS = ('yaml', 'json', 'toml')
DEFAULT_FORMAT = 'yaml'


def extract_path(obj: Any, path: str) -> Any:
    """按点分路径提取（如 ``web.spec.selector``）；空路径返回原值。

    Raises:
        ValueError: 路径段不存在（非 Mapping 或键缺失）。
    """
    if not path:
        return obj
    cur: Any = obj
    for seg in path.split('.'):
        if not isinstance(cur, Mapping) or seg not in cur:
            raise ValueError(f'提取路径 {path!r} 不存在（段 {seg!r}）')
        cur = cast(Mapping[str, Any], cur)[seg]
    return cur


def render(format: str, data: Any, *, compact: bool) -> str:
    """按格式渲染数据为文本。

    - ``yaml``：零依赖 emitter（:mod:`infinity_data.emit.plain_yaml`）
    - ``json``：stdlib（Decimal → 数字、路径 → 字符串的有损投影）
    - ``toml``：需要 tomli-w（未安装 → ``NotImplementedError``，由调用方转提示）
    """
    if format == 'yaml':
        return plain_yaml.yaml_dump(data)
    if format == 'json':
        return to_json(data, config=EmitConfig(indent=None if compact else 2))
    return to_toml(data)
