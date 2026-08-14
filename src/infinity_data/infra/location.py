"""源码位置类型（所有阶段共用）。"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ['SourceInfo', 'SourceRange']


@dataclass
class SourceInfo:
    """源码位置信息（单点）。"""

    file_path: str
    line: int
    col: int
    index: int


@dataclass
class SourceRange:
    """源码位置范围（区间）。词法阶段使用零宽 range（start == end）。"""

    start: SourceInfo
    end: SourceInfo
