"""输出转换配置（emit 层）：控制 std/python → 输出格式的有损投影语义。"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ['EmitConfig']


@dataclass(frozen=True)
class EmitConfig:
    """emit 层输出转换配置。

    转换语义：
    - ``full_float``：``float`` 值（:class:`decimal.Decimal`）以自描述标记
      ``{"__type__": "decimal", "num": "<十进制字符串>"}`` 编码（无损）；False 时
      有限值转普通 JSON 数字，NaN / ±Infinity 无法用 JSON 数字表达 → 仍以标记编码
    - ``full_path``：路径值（:class:`PurePosixPath`）以自描述标记
      ``{"__type__": "path", "path": "<POSIX 字符串>"}`` 编码（可辨识「这是路径」）；
      False 时投影为普通 POSIX 字符串
    - ``keep_noexist``：``noexist`` 字段保留为 ``{"__type__": "noexist"}`` 标记
      （依赖 :data:`~infinity_data.semantic.std.NOEXIST` 哨兵保留三态）；默认丢弃
      （键不出现，§1.6）

    序列化选项：
    - ``indent`` / ``sort_keys`` / ``ensure_ascii``：JSON 缩进 / 排序 / ASCII 转义
    """

    # ── 转换语义 ──────────────────────────────────────
    full_float: bool = False
    full_path: bool = False
    keep_noexist: bool = False

    # ── 序列化选项 ────────────────────────────────────
    indent: int | None = 2
    sort_keys: bool = False
    ensure_ascii: bool = False
