"""位置编码工具：编译器码点位置 ↔ LSP UTF-16 单元位置。

编译器 ``SourceInfo.line/col`` 为 **1-based 码点**列号；LSP 默认
``positionEncoding`` 为 **utf-16**（中文 BMP 内占 1 单元，emoji 等非 BMP
占 2 单元）。直接映射在含非 ASCII 的文档里会错位，统一在本层转换：

- 码点位置 → UTF-16 单元位置（``_utf16_prefix``）
- LSP 位置（0-based UTF-16）→ 码点 index（``_pos_index``，与
  ``SourceInfo.index`` 对齐，供语义定位用）
"""

from __future__ import annotations

from typing import Any

from infinity_data.infra.location import SourceRange

__all__ = ['utf16_len', 'utf16_prefix', 'to_lsp_range', 'pos_index', 'utf16_to_cp']


def utf16_len(s: str) -> int:
    """字符串的 UTF-16 单元长度（LSP 位置/length 用）。"""
    return len(s.encode('utf-16-le')) // 2


def utf16_prefix(line: str, codepoint_count: int) -> int:
    """该行前 codepoint_count 个码点的 UTF-16 单元数（= 0-based UTF-16 character）。"""
    if codepoint_count <= 0:
        return 0
    return utf16_len(line[:codepoint_count])


def utf16_to_cp(line: str, u16_count: int) -> int:
    """该行前 u16_count 个 UTF-16 单元对应的码点数。"""
    count = 0
    for cp in line:
        u = 1 if ord(cp) < 0x10000 else 2
        if count + u > u16_count:
            break
        count += u
    return count


def pos_index(text: str, position: dict[str, Any]) -> int:
    """LSP 位置（0-based, UTF-16）→ 码点 index（与 tokenizer SourceInfo.index 对齐）。"""
    lines = text.split('\n')
    line_no = int(position.get('line', 0))
    char = int(position.get('character', 0))
    index = 0
    for i, ln in enumerate(lines):
        if i == line_no:
            index += utf16_to_cp(ln, char)
            break
        index += len(ln) + 1  # +1 = 换行符
    return index


def to_lsp_range(source: SourceRange | None, lines: list[str]) -> dict[str, Any] | None:
    """SourceRange → LSP range（0-based + UTF-16 单元 + 开区间 end）。

    编译器位置为 1-based 码点：``start`` 是首字符位置、``end`` 是消费后的位置。
    LSP：start = (line-1, 前 start.col-1 个码点的 UTF-16 数)；
         end   = (line-1, 前 end.col-1 个码点的 UTF-16 数)（开区间）。
    """
    if source is None:
        return None
    start = source.start
    end = source.end
    start_line = max(start.line - 1, 0)
    end_line = max(end.line - 1, 0)
    line_s = lines[start_line] if start_line < len(lines) else ''
    line_e = lines[end_line] if end_line < len(lines) else line_s
    start_char = utf16_prefix(line_s, start.col - 1)
    end_char = utf16_prefix(line_e, end.col - 1)
    start_pos = {'line': start_line, 'character': start_char}
    if start_line == end_line and start_char == end_char:
        return {'start': start_pos, 'end': dict(start_pos)}
    return {'start': start_pos, 'end': {'line': end_line, 'character': end_char}}
