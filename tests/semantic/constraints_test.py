"""semantic/constraints.py 单元测试：约束解析（resolve_constraint_list）。"""

from infinity_data.infra.location import SourceRange
from infinity_data.parser.models import Constraint, ConstraintIdent
from infinity_data.semantic.constraints import resolve_constraint_list


def _cs(*names: str) -> list[Constraint]:
    return [ConstraintIdent(source=SourceRange.empty(), name=n) for n in names]


def test_resolve_simple_ident() -> None:
    specs, diags = resolve_constraint_list(_cs('int'), {})
    assert not diags
    assert [s.name for s in specs] == ['int']


def test_resolve_question_mark() -> None:
    specs, diags = resolve_constraint_list(_cs('?'), {})
    assert not diags
    assert specs[0].name == '?'


def test_resolve_unknown_name_parses_without_diag() -> None:
    """未知约束名在解析期不报错（执行期 registry 报 constraint.unknown）。"""
    specs, diags = resolve_constraint_list(_cs('nosuch'), {})
    assert not diags
    assert specs[0].name == 'nosuch'


def test_resolve_multiple_idents() -> None:
    specs, diags = resolve_constraint_list(_cs('int', 'str'), {})
    assert not diags
    assert [s.name for s in specs] == ['int', 'str']
