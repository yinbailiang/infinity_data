"""补全场景测试：模拟 VS Code 客户端规则，验证「补全 → 接受 → 文本合法」。

真实 VS Code 行为不是直接插入返回项，而是：

1. 用 ``editor.wordSeparators`` 取光标词（单引号 / 连字符 / 括号都是分隔符）
2. 用 ``filterText``（缺省 label）对光标词做模糊匹配，过滤掉不匹配的项
3. 应用 ``textEdit``（缺省在光标处插入 ``insertText`` / label）

纯单元测试只断言返回字段，无法发现「项被客户端过滤掉」「插入后多一个引号」这类
问题；这里把客户端规则显式实现一遍，再编译应用后的文本确认语法有效。
"""

from __future__ import annotations

from typing import Any

import pytest

from infinity_data import compile_source
from infinity_data.tools.lsp import language

# 4 行模板定义；调用文本追加在第 5 行（line=4）
BASE = "~T {\n    'test-1': object\n    name: str\n}\n"
CALL_LINE = 4

_FORBIDDEN = {
    'parse.string_identifier_misplaced',
    'tokenize.unterminated_identifier',
    'tokenize.empty_identifier',
}


def _typed_word(text: str, line: int, char: int) -> str:
    """模拟 VS Code 的光标词：连续字母/数字/下划线（引号、连字符等是分隔符）。"""
    line_text = text.split('\n')[line]
    start = char
    while start > 0 and (line_text[start - 1].isalnum() or line_text[start - 1] == '_'):
        start -= 1
    return line_text[start:char]


def _fuzzy(needle: str, haystack: str) -> bool:
    """VS Code 风格的子序列模糊匹配（不区分大小写）。"""
    it = iter(haystack.lower())
    return all(ch in it for ch in needle.lower())


def _offset(text: str, line: int, char: int) -> int:
    lines = text.split('\n')
    return sum(len(part) + 1 for part in lines[:line]) + char


def _apply_edit(text: str, edit: dict[str, Any]) -> str:
    rng = edit['range']
    start = _offset(text, rng['start']['line'], rng['start']['character'])
    end = _offset(text, rng['end']['line'], rng['end']['character'])
    return text[:start] + edit['newText'] + text[end:]


def _accept(text: str, line: int, char: int, *, label: str) -> str:
    """按客户端规则选择并应用补全项，返回应用后的完整文本。"""
    items = language.completion_items(text, 'app.infd', {'line': line, 'character': char})
    typed = _typed_word(text, line, char)
    candidates = [it for it in items if _fuzzy(typed, it.get('filterText') or it['label'])]
    assert candidates, f'客户端会过滤掉全部补全项（typed={typed!r}）: {[i.get("label") for i in items]}'

    chosen = next((it for it in candidates if it['label'] == label), None)
    assert chosen is not None, f'缺少补全项 {label!r}: {[i["label"] for i in candidates]}'

    edit = chosen.get('textEdit')
    if edit is not None:
        return _apply_edit(text, edit)
    # 无 textEdit：在光标处插入 insertText（此处场景均带 textEdit）
    start = _offset(text, line, char) - len(typed)
    insert = chosen.get('insertText') or chosen['label']
    return text[:start] + insert + text[_offset(text, line, char) :]


def _assert_valid(new_text: str) -> None:
    codes = {d.code for d in compile_source(new_text).diagnostics}
    assert not (codes & _FORBIDDEN), f'{sorted(codes & _FORBIDDEN)} in:\n{new_text}'


# ═══════════════════════════════════════════════════════════
# 场景矩阵
# ═══════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    ('call_text', 'char', 'expected'),
    [
        # 刚打开括号，输入为空
        ('t = T(', 6, "t = T('test-1' = "),
        # 裸前缀（客户端用 filterText 匹配）
        ('t = T(te', 8, "t = T('test-1' = "),
        # 未闭合引号 + 尾括号：括号必须保留
        ("t = T(')", 7, "t = T('test-1' = )"),
        ("t = T('te)", 9, "t = T('test-1' = )"),
        # 引号内输入、光标在闭引号前
        ("t = T('te')", 9, "t = T('test-1' = )"),
        # 空引号对：光标在中间 / 在闭引号后
        ("t = T('')", 7, "t = T('test-1' = )"),
        ("t = T('')", 8, "t = T('test-1' = )"),
    ],
)
def test_quoted_field_completion_scenarios(call_text: str, char: int, expected: str) -> None:
    text = BASE + call_text + '\n'
    new_text = _accept(text, CALL_LINE, char, label="'test-1'")
    assert new_text == BASE + expected + '\n'
    _assert_valid(new_text)


def test_bare_field_completion_scenario() -> None:
    text = BASE + 't = T(na\n'
    new_text = _accept(text, CALL_LINE, 8, label='name')
    assert new_text == BASE + 't = T(name = \n'
    _assert_valid(new_text)


def test_used_field_not_suggested() -> None:
    text = BASE + "t = T('test-1' = 1, \n"
    items = language.completion_items(text, 'app.infd', {'line': CALL_LINE, 'character': 19})
    labels = {it['label'] for it in items}
    assert "'test-1'" not in labels
    assert 'name' in labels
