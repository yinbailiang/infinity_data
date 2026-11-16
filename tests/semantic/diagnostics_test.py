"""semantic/diagnostics.py 单元测试：semantic.* 声明注册与渲染（导入即注册）。"""

from infinity_data.infra.diagnostics import Diagnostic
from infinity_data.semantic.diagnostics import (
    ConstraintAllFail,
    DollarUndefined,
    TemplateUndefined,
    ValueNestingDepth,
)


def test_template_vocab_registered() -> None:
    msg = Diagnostic(TemplateUndefined(template='X'), lang='zh-CN').render(include_location=False)
    assert '未定义' in msg


def test_constraint_vocab_registered() -> None:
    msg = Diagnostic(ConstraintAllFail(), lang='zh-CN').render(include_location=False)
    assert '约束失败' in msg


def test_dollar_vocab_registered() -> None:
    msg = Diagnostic(DollarUndefined(name='A'), lang='zh-CN').render(include_location=False)
    assert '未找到导入变量' in msg


def test_value_vocab_registered() -> None:
    msg = Diagnostic(ValueNestingDepth(max=200), lang='zh-CN').render(include_location=False)
    assert '嵌套层级' in msg
