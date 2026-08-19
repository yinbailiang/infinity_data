"""semantic/diagnostics.py 单元测试：semantic.* 词汇表注册（导入即注册）。"""

from infinity_data.infra.diagnostics import render_message


def test_template_vocab_registered() -> None:
    assert '未定义' in render_message('template.undefined', {'template': 'X'}, location='x:1:1')


def test_constraint_vocab_registered() -> None:
    assert '约束失败' in render_message('constraint.all_fail', {}, location='x:1:1')


def test_dollar_vocab_registered() -> None:
    assert '未找到导入变量' in render_message('dollar.undefined', {'name': 'A'}, location='x:1:1')


def test_value_vocab_registered() -> None:
    assert '嵌套层级' in render_message('value.nesting_depth', {'max': 200}, location='x:1:1')
