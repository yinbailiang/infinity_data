"""约束执行器（ConstraintExecutor）独立测试：工作在已完成 StdAst 上。

与构建（AstBuilder）无关——直接构造带约束的 Std 节点，验证遍历执行、
只校验不转换、短路语义、模板即约束与 schema 模式。
"""

from __future__ import annotations

import pytest

from infinity_data.infra.location import SourceRange
from infinity_data.parser.models import Constraints, TemplateConfig, TemplateDef, TemplateField
from infinity_data.sandbox import Schema, SchemaError
from infinity_data.semantic.executor import ConstraintExecutor
from infinity_data.semantic.models import (
    ResolvedConstraint,
    StdField,
    StdLiteral,
    StdObject,
    TemplateKey,
)
from infinity_data.semantic.registry import ConstraintRegistry

_SRC = SourceRange.empty()


def _executor(templates: dict[TemplateKey, TemplateDef] | None = None) -> ConstraintExecutor:
    return ConstraintExecutor(
        registry=ConstraintRegistry(),
        templates=templates or {},
        template_scopes={key: {} for key in (templates or {})},
    )


# ═══════════════════════════════════════════════════════════
# 遍历执行
# ═══════════════════════════════════════════════════════════


def test_validate_field_constraint_failure() -> None:
    field = StdField(
        name='x',
        value=StdLiteral(kind='int', value=3),
        constraints=[ResolvedConstraint(name='str')],
    )
    diags = _executor().validate(StdObject(fields=[field]))
    assert [d.code for d in diags] == ['constraint.type_mismatch']


def test_validate_only_checks_does_not_coerce() -> None:
    """只校验不转换：float 拒绝 int，失败后值保持原样。"""
    value = StdLiteral(kind='int', value=3)
    field = StdField(name='x', value=value, constraints=[ResolvedConstraint(name='float')])
    diags = _executor().validate(StdObject(fields=[field]))
    assert diags
    assert field.value is value  # 未转换


def test_field_constraint_chain_short_circuit() -> None:
    """字段注解约束链短路：第一个失败即停，剩余约束不执行。"""
    field = StdField(
        name='x',
        value=StdLiteral(kind='int', value=3),
        constraints=[
            ResolvedConstraint(name='str'),
            ResolvedConstraint(name='range', args=[0, 10]),
        ],
    )
    diags = _executor().validate(StdObject(fields=[field]))
    assert [d.code for d in diags] == ['constraint.type_mismatch']  # range 未执行


def test_object_structure_constraints_all_executed() -> None:
    """结构级约束全部执行（不短路）：两个 size 约束都产出诊断。"""
    obj = StdObject(
        fields=[],
        constraints=[
            ResolvedConstraint(name='size', args=[1, 10]),
            ResolvedConstraint(name='size', args=[2, 10]),
        ],
    )
    diags = _executor().validate(obj)
    assert [d.code for d in diags] == ['constraint.size_out', 'constraint.size_out']


def test_validate_recurses_into_nested_object() -> None:
    """递归遍历：嵌套 dict 内的结构约束也执行。"""
    inner = StdObject(
        fields=[],
        constraints=[ResolvedConstraint(name='size', args=[1, 10])],
    )
    outer = StdObject(fields=[StdField(name='child', value=inner)])
    diags = _executor().validate(outer)
    assert [d.code for d in diags] == ['constraint.size_out']


# ═══════════════════════════════════════════════════════════
# 模板即约束
# ═══════════════════════════════════════════════════════════


def _server_template() -> tuple[TemplateDef, TemplateKey]:
    tpl = TemplateDef(
        name='Server',
        fields=[
            TemplateField(
                name='host',
                constraints=Constraints(constraints=[], source=_SRC),
                default_value=None,
                source=_SRC,
            ),
            TemplateField(
                name='port',
                constraints=Constraints(constraints=[], source=_SRC),
                default_value=None,
                source=_SRC,
            ),
        ],
        constraints=[],
        config=TemplateConfig(),
        source=_SRC,
    )
    return tpl, TemplateKey(identity='abc', name='Server')


def test_template_as_constraint_validates_handwritten_dict() -> None:
    """模板即约束：手写 dict 命中模板真名 → 结构校验（缺必填字段报错）。"""
    tpl, key = _server_template()
    executor = _executor({key: tpl})

    ok = StdObject(
        fields=[
            StdField(name='host', value=StdLiteral(kind='str', value='h')),
            StdField(name='port', value=StdLiteral(kind='int', value=80)),
        ]
    )
    assert (
        executor.validate(
            StdObject(fields=[StdField(name='hand', value=ok, constraints=[ResolvedConstraint(name=str(key))])])
        )
        == []
    )

    bad = StdObject(fields=[StdField(name='host', value=StdLiteral(kind='str', value='h'))])
    diags = executor.validate(
        StdObject(fields=[StdField(name='hand', value=bad, constraints=[ResolvedConstraint(name=str(key))])])
    )
    assert [d.code for d in diags] == ['template.missing_field']


def test_template_as_constraint_marks_source_template() -> None:
    """校验通过的手写 dict 被标记来源模板（变异，供下游引用）。"""
    tpl, key = _server_template()
    executor = _executor({key: tpl})
    obj = StdObject(
        fields=[
            StdField(name='host', value=StdLiteral(kind='str', value='h')),
            StdField(name='port', value=StdLiteral(kind='int', value=80)),
        ]
    )
    executor.validate(
        StdObject(fields=[StdField(name='hand', value=obj, constraints=[ResolvedConstraint(name=str(key))])])
    )
    assert obj.template == key


# ═══════════════════════════════════════════════════════════
# schema 校验（strict/lenient/strip）
# ═══════════════════════════════════════════════════════════


def _apply_schema(mode: str) -> tuple[StdObject, list[str]]:
    tpl = TemplateDef(name='Cfg', fields=[], constraints=[], config=TemplateConfig(), source=_SRC)
    key = TemplateKey(identity='abc', name='Cfg')
    executor = _executor({key: tpl})
    root = StdObject(fields=[StdField(name='extra', value=StdLiteral(kind='int', value=1))])
    new_root, diags = executor.apply_schema(root, Schema(template='Cfg', mode=mode), tpl, {})  # type: ignore[arg-type]
    return new_root, [d.code for d in diags]


def test_schema_strict_extra_field_raises() -> None:
    tpl = TemplateDef(name='Cfg', fields=[], constraints=[], config=TemplateConfig(), source=_SRC)
    key = TemplateKey(identity='abc', name='Cfg')
    executor = _executor({key: tpl})
    root = StdObject(fields=[StdField(name='extra', value=StdLiteral(kind='int', value=1))])
    with pytest.raises(SchemaError):
        executor.apply_schema(root, Schema(template='Cfg', mode='strict'), tpl, {})


def test_schema_lenient_extra_field_warns() -> None:
    new_root, codes = _apply_schema('lenient')
    assert codes == ['schema.extra_fields_lenient']
    assert len(new_root.fields) == 1  # 未移除


def test_schema_strip_extra_field_removed() -> None:
    new_root, codes = _apply_schema('strip')
    assert codes == []
    assert new_root.fields == []
