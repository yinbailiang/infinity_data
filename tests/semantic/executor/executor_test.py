"""约束执行器（ConstraintExecutor）独立测试：工作在已完成 StdAst 上。

与构建（AstBuilder）无关——直接构造带约束的 Std 节点，验证遍历执行、
只校验不转换、短路语义、模板即约束与 schema 模式。
"""

from __future__ import annotations

import pytest

from infinity_data.infra.diagnostics import DiagnosticCollector
from infinity_data.infra.location import SourceRange
from infinity_data.parser import ConstraintIdent, Constraints, TemplateConfig, TemplateDef, TemplateField
from infinity_data.sandbox import Schema, SchemaError
from infinity_data.semantic.builder import ResolvedConstraint, StdField, StdLiteral, StdObject
from infinity_data.semantic.executor import ConstraintExecutor
from infinity_data.semantic.registry import ConstraintRegistry
from infinity_data.semantic.resolver import Scope, TemplateKey

_SRC = SourceRange.empty()


def _executor(templates: dict[TemplateKey, TemplateDef] | None = None) -> ConstraintExecutor:
    return ConstraintExecutor(
        registry=ConstraintRegistry(),
        templates=templates or {},
        template_scopes={key: Scope() for key in (templates or {})},
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
    collector = DiagnosticCollector()
    _executor().validate(StdObject(fields=[field]), collector)
    assert [d.code for d in collector] == ['constraint.type_mismatch']


def test_diagnostic_source_is_checked_value_not_constraint() -> None:
    """约束失败诊断指向被检查的值（value.source），而非约束表达式自身（spec.source）。"""
    value_src = SourceRange.empty()
    constraint_src = SourceRange.empty()
    field = StdField(
        name='x',
        value=StdLiteral(kind='int', value=3, source=value_src),
        constraints=[ResolvedConstraint(name='str', source=constraint_src)],
    )
    collector = DiagnosticCollector()
    _executor().validate(StdObject(fields=[field]), collector)
    d = next(d for d in collector)
    assert d.code == 'constraint.type_mismatch'
    assert d.source is value_src
    assert d.source is not constraint_src


def test_template_constraint_falls_back_to_outer_source() -> None:
    """被检查 dict 整棵无来源（如外部导入数据）时，诊断回退到引用它的外层字段位置。"""
    tpl = TemplateDef(
        name='Srv',
        fields=[
            TemplateField(
                name='host',
                constraints=Constraints(constraints=[ConstraintIdent(name='str', source=_SRC)], source=_SRC),
                default_value=None,
                source=_SRC,
            ),
        ],
        constraints=[],
        config=TemplateConfig(),
        source=_SRC,
    )
    key = TemplateKey(identity='abc', name='Srv')
    executor = _executor({key: tpl})
    outer = SourceRange.empty()
    # 被检查 dict 与内部字段/值均无来源（模拟 !file/!env 导入数据）
    bad = StdObject(fields=[StdField(name='host', value=StdLiteral(kind='int', value=123))])
    field = StdField(
        name='hand',
        value=bad,
        constraints=[ResolvedConstraint(name=str(key))],
        source=outer,
    )
    collector = DiagnosticCollector()
    executor.validate(StdObject(fields=[field]), collector)
    codes = [d.code for d in collector]
    assert codes == ['constraint.type_mismatch']
    assert all(d.source is outer for d in collector)


def test_validate_only_checks_does_not_coerce() -> None:
    """只校验不转换：float 拒绝 int，失败后值保持原样。"""
    value = StdLiteral(kind='int', value=3)
    field = StdField(name='x', value=value, constraints=[ResolvedConstraint(name='float')])
    collector = DiagnosticCollector()
    _executor().validate(StdObject(fields=[field]), collector)
    assert list(collector)
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
    collector = DiagnosticCollector()
    _executor().validate(StdObject(fields=[field]), collector)
    assert [d.code for d in collector] == ['constraint.type_mismatch']  # range 未执行


def test_object_structure_constraints_all_executed() -> None:
    """结构级约束全部执行（不短路）：两个 size 约束都产出诊断。"""
    obj = StdObject(
        fields=[],
        constraints=[
            ResolvedConstraint(name='size', args=[1, 10]),
            ResolvedConstraint(name='size', args=[2, 10]),
        ],
    )
    collector = DiagnosticCollector()
    _executor().validate(obj, collector)
    assert [d.code for d in collector] == ['constraint.size_out', 'constraint.size_out']


def test_validate_recurses_into_nested_object() -> None:
    """递归遍历：嵌套 dict 内的结构约束也执行。"""
    inner = StdObject(
        fields=[],
        constraints=[ResolvedConstraint(name='size', args=[1, 10])],
    )
    outer = StdObject(fields=[StdField(name='child', value=inner)])
    collector = DiagnosticCollector()
    _executor().validate(outer, collector)
    assert [d.code for d in collector] == ['constraint.size_out']


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
    collector = DiagnosticCollector()
    executor.validate(
        StdObject(fields=[StdField(name='hand', value=ok, constraints=[ResolvedConstraint(name=str(key))])]),
        collector,
    )
    assert not list(collector)

    bad = StdObject(fields=[StdField(name='host', value=StdLiteral(kind='str', value='h'))])
    collector2 = DiagnosticCollector()
    executor.validate(
        StdObject(fields=[StdField(name='hand', value=bad, constraints=[ResolvedConstraint(name=str(key))])]),
        collector2,
    )
    assert [d.code for d in collector2] == ['template.missing_field']


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
    collector = DiagnosticCollector()
    executor.validate(
        StdObject(fields=[StdField(name='hand', value=obj, constraints=[ResolvedConstraint(name=str(key))])]),
        collector,
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
    collector = DiagnosticCollector()
    new_root = executor.apply_schema(root, Schema(template='Cfg', mode=mode), tpl, {}, collector)  # type: ignore[arg-type]
    return new_root, [d.code for d in collector]


def test_schema_strict_extra_field_raises() -> None:
    tpl = TemplateDef(name='Cfg', fields=[], constraints=[], config=TemplateConfig(), source=_SRC)
    key = TemplateKey(identity='abc', name='Cfg')
    executor = _executor({key: tpl})
    root = StdObject(fields=[StdField(name='extra', value=StdLiteral(kind='int', value=1))])
    with pytest.raises(SchemaError):
        executor.apply_schema(root, Schema(template='Cfg', mode='strict'), tpl, Scope(), DiagnosticCollector())


def test_schema_lenient_extra_field_warns() -> None:
    new_root, codes = _apply_schema('lenient')
    assert codes == ['schema.extra_fields_lenient']
    assert len(new_root.fields) == 1  # 未移除


def test_schema_strip_extra_field_removed() -> None:
    new_root, codes = _apply_schema('strip')
    assert codes == []
    assert new_root.fields == []
