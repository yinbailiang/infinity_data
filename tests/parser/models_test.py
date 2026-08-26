"""parser/models.py 单元测试：RawAst 节点构造与默认值。"""

from infinity_data.infra.location import SourceRange
from infinity_data.parser import (
    ConstraintCall,
    ConstraintIdent,
    Constraints,
    ErrorConstraint,
    ErrorStatement,
    ErrorValue,
    Field,
    TemplateConfig,
    TemplateDef,
    TemplateField,
)


def test_template_config_defaults() -> None:
    c = TemplateConfig()
    assert c.allow_extra is False
    assert c.positional is True
    assert c.description is None


def test_constraint_nodes() -> None:
    ident = ConstraintIdent(source=SourceRange.empty(), name='int')
    call = ConstraintCall(source=SourceRange.empty(), name='range', arguments=[ident])
    assert call.arguments[0] is ident
    cs = Constraints(source=SourceRange.empty(), constraints=[ident, call])
    assert len(cs.constraints) == 2


def test_template_field_required_by_default() -> None:
    tf = TemplateField(
        source=SourceRange.empty(),
        name='a',
        constraints=Constraints(source=SourceRange.empty()),
        default_value=None,
    )
    assert tf.default_value is None  # 无默认值 = 必填字段


def test_field_optional_value() -> None:
    f = Field(source=SourceRange.empty(), name='x', constraints=None, value=None)
    assert f.value is None


def test_template_def_config_default() -> None:
    tpl = TemplateDef(source=SourceRange.empty(), name='X', fields=[])
    assert tpl.config.positional is True


def test_error_node_canonical_placeholder() -> None:
    """错误节点 canonical 容错输出 error("message") 占位符（不抛异常）。"""
    assert ErrorStatement(source=SourceRange.empty(), message='坏语句').canonical() == 'error("坏语句")'
    assert ErrorValue(source=SourceRange.empty(), message='坏值').canonical() == 'error("坏值")'
    assert ErrorConstraint(source=SourceRange.empty(), message='坏约束').canonical() == 'error("坏约束")'


def test_error_node_canonical_escapes_message() -> None:
    """消息中的引号/反斜杠经 JSON 转义（与 _canonical_str 一致）。"""
    import json

    msg = '含 "引号" 与 \\ 反斜杠'
    v = ErrorValue(source=SourceRange.empty(), message=msg)
    assert v.canonical() == f'error({json.dumps(msg, ensure_ascii=False)})'
