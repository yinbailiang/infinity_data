"""顶层 Schema 约束。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

__all__ = ['Schema']


@dataclass
class Schema:
    """顶层模板约束：强制编译产物符合指定模板的结构。"""

    template: str  # 模板名
    from_file: str | None = None  # 模板所在文件；None = 与配置同文件（或已导入）
    mode: Literal['strict', 'lenient', 'strip'] = 'strict'

    # 校验器要求完整形状：字段缺失（含可选字段）一律报错（默认值不参与给定值校验）
    # strict:  额外字段 → 报错（SchemaError）
    # lenient: 额外字段 → 警告
    # strip:   额外字段 → 静默丢弃
