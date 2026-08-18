"""源码位置类型（所有阶段共用）。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from infinity_data.infra.file import File

__all__ = ['SourceInfo', 'SourceRange', 'format_location']


def format_location(source: SourceRange | None) -> str:
    """格式化源码位置 ``file:line:col``（无位置时为 ``<unknown>``）。

    :class:`Diagnostic` 与沙盒异常共用，消除重复的格式化逻辑。
    """
    if source is None:
        return '<unknown>'
    s = source.start
    return f'{source.file.name}:{s.line}:{s.col}'


class _UnknownFile(File):
    """无源码来源的占位（仅 :meth:`SourceRange.empty` 使用，位置域私有概念）。"""

    def read(self) -> str:
        return ''

    @property
    def identity(self) -> str:
        return '<unknown>'

    def content_hash(self) -> str:
        return '<unknown>'


_UNKNOWN_FILE = _UnknownFile(name='<unknown>', root_path=Path())


@dataclass
class SourceInfo:
    """源码位置信息（纯位置，不含来源）。"""

    line: int
    col: int
    index: int


@dataclass
class SourceRange:
    """源码位置范围（区间）：来源文件 + 起止位置。

    词法阶段使用零宽 range（start == end）。
    """

    file: File
    start: SourceInfo
    end: SourceInfo

    @classmethod
    def empty(cls) -> SourceRange:
        """无来源占位（错误恢复、合成 token）。"""
        return cls(
            file=_UNKNOWN_FILE,
            start=SourceInfo(line=0, col=0, index=0),
            end=SourceInfo(line=0, col=0, index=0),
        )

    @classmethod
    def at(cls, file: File, pos: SourceInfo) -> SourceRange:
        """单点位置 → 零宽 range（词法阶段错误定位用）。"""
        return cls(file=file, start=pos, end=pos)
