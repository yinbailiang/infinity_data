"""tokenizer/diagnostics.py 单元测试：tokenize.* 词汇表注册（导入即注册）。"""

from infinity_data.infra.diagnostics import render_message


def test_vocab_registered() -> None:
    assert '未知字符' in render_message('tokenize.unknown_char', {'char': '@'}, location='x:1:1')
    assert '括号未闭合' in render_message('tokenize.unterminated_bracket', {'bracket': '['}, location='x:1:1')
    assert '不匹配' in render_message('tokenize.mismatched_bracket', {'open': '[', 'close': ')'}, location='x:1:1')
    assert '多余' in render_message('tokenize.unexpected_close_bracket', {'bracket': ')'}, location='x:1:1')
    assert '纠正' in render_message(
        'tokenize.bang_corrected', {'actual': 'envv', 'suggestion': 'env'}, location='x:1:1'
    )
    assert '带符号' in render_message('tokenize.signed_nan', {'raw': '+nan'}, location='x:1:1')
    assert 'BOM' in render_message('tokenize.bom', {}, location='x:1:1')
    assert '未闭合' in render_message('tokenize.unterminated_string', {}, location='x:1:1')
    assert '多行字符串未闭合' in render_message(
        'tokenize.unterminated_multiline_string', {'flag': '``'}, location='x:1:1'
    )
