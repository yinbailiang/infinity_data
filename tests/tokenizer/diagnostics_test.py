"""tokenizer/diagnostics.py 单元测试：tokenize.* 词汇表注册（导入即注册）。"""

from infinity_data.infra.diagnostics import render_message


def test_vocab_registered() -> None:
    assert '未知字符' in render_message('tokenize.unknown_char', {'char': '@'}, location='x:1:1')
    assert '括号未闭合' in render_message('tokenize.unterminated_bracket', {'bracket': '['}, location='x:1:1')
    assert 'BOM' in render_message('tokenize.bom', {}, location='x:1:1')
    assert '未闭合' in render_message('tokenize.unterminated_string', {'str_type': '字符串'}, location='x:1:1')
