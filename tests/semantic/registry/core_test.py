"""semantic/registry/core.py 单元测试：结果类型 / 登记项 / 共享辅助。"""

from decimal import Decimal
from pathlib import PurePosixPath
from typing import Any

from infinity_data.infra.diagnostics import Severity
from infinity_data.semantic.registry.core import (
    ConstraintEntry,
    ConstraintResult,
    as_decimal_arg,
    as_number,
    as_spec,
    as_std_value,
    as_str,
    describe,
    fail_result,
    ok_result,
    path_str,
    safe_equal,
    spec_name,
    std_equal,
)
from infinity_data.semantic.std import (
    ResolvedConstraint,
    StdArray,
    StdField,
    StdLiteral,
    StdObject,
)

# ═══════════════════════════════════════════════════════════
# 结果类型
# ═══════════════════════════════════════════════════════════


def test_constraint_result_default_diagnostics_are_isolated() -> None:
    """默认 diagnostics 列表不共享（避免可变默认值跨实例泄漏）。"""
    a = ConstraintResult(ok=True)
    b = ConstraintResult(ok=True)
    assert a.diagnostics == []
    assert a.diagnostics is not b.diagnostics


def test_ok_result_is_success_without_diagnostics() -> None:
    result = ok_result()
    assert result.ok is True
    assert result.diagnostics == []


def test_fail_result_uses_declaration_and_location() -> None:
    from infinity_data.semantic.diagnostics import ConstraintTypeMismatch

    declaration = ConstraintTypeMismatch(expected='int', actual='str')
    result = fail_result(declaration, None, 'a.b')

    assert result.ok is False
    assert len(result.diagnostics) == 1
    diagnostic = result.diagnostics[0]
    assert diagnostic.declaration is declaration
    assert diagnostic.code == 'constraint.type_mismatch'
    assert diagnostic.path == 'a.b'
    assert diagnostic.source is None
    assert diagnostic.severity is None
    assert diagnostic.effective_severity is Severity.ERROR


def test_fail_result_severity_override() -> None:
    from infinity_data.semantic.diagnostics import ConstraintPathDenied

    declaration = ConstraintPathDenied(constraint='exist', path='./x')
    result = fail_result(declaration, None, '', severity=Severity.WARNING)

    assert result.ok is False
    assert result.diagnostics[0].effective_severity is Severity.WARNING


# ═══════════════════════════════════════════════════════════
# 登记项
# ═══════════════════════════════════════════════════════════


def _entry(min_args: int, max_args: int | None) -> ConstraintEntry:
    def fn(*args: Any) -> ConstraintResult:
        return ok_result()

    return ConstraintEntry(name='test', fn=fn, min_args=min_args, max_args=max_args)


def test_arity_error_unbounded() -> None:
    entry = _entry(1, None)
    assert entry.arity_error(0) == '1'
    assert entry.arity_error(1) is None
    assert entry.arity_error(99) is None


def test_arity_error_bounded_range() -> None:
    entry = _entry(1, 3)
    assert entry.arity_error(0) == '1~3'
    assert entry.arity_error(1) is None
    assert entry.arity_error(3) is None
    assert entry.arity_error(4) == '1~3'


def test_arity_error_exact() -> None:
    entry = _entry(2, 2)
    assert entry.arity_error(1) == '2~2'
    assert entry.arity_error(2) is None
    assert entry.arity_error(3) == '2~2'


def test_arity_error_zero_unbounded() -> None:
    entry = _entry(0, None)
    assert entry.arity_error(0) is None
    assert entry.arity_error(100) is None


# ═══════════════════════════════════════════════════════════
# describe / 提取辅助
# ═══════════════════════════════════════════════════════════


def test_describe_none_and_literals() -> None:
    assert describe(None) == '无值'
    assert describe(StdLiteral(kind='str', value='x')) == "str('x')"
    assert describe(StdLiteral(kind='int', value=1)) == 'int(1)'
    assert describe(StdLiteral(kind='bool', value=True)) == 'bool(True)'
    assert describe(StdLiteral(kind='null', value=None)) == 'null(None)'


def test_describe_containers() -> None:
    assert describe(StdArray(elements=[StdLiteral(kind='int', value=1)])) == 'list[1]'
    assert describe(StdObject(fields=[StdField(name='a', value=StdLiteral(kind='int', value=1))])) == 'dict[1]'


def test_as_number() -> None:
    assert as_number(StdLiteral(kind='int', value=42)) == Decimal(42)
    assert as_number(StdLiteral(kind='float', value=Decimal('1.5'))) == Decimal('1.5')
    assert as_number(StdLiteral(kind='str', value='1')) is None
    assert as_number(StdLiteral(kind='bool', value=True)) is None
    assert as_number(None) is None


def test_as_str_is_strict_about_path() -> None:
    assert as_str(StdLiteral(kind='str', value='x')) == 'x'
    assert as_str(StdLiteral(kind='path', value=PurePosixPath('/x'))) is None
    assert as_str(StdLiteral(kind='int', value=1)) is None
    assert as_str(None) is None


def test_path_str_is_strict_about_str() -> None:
    assert path_str(StdLiteral(kind='path', value=PurePosixPath('/a/b'))) == '/a/b'
    assert path_str(StdLiteral(kind='str', value='/a/b')) is None
    # kind 为 path 但值不是 PurePath（防御路径）：不视为路径
    assert path_str(StdLiteral(kind='path', value='/a/b')) is None
    assert path_str(None) is None


def test_as_decimal_arg() -> None:
    assert as_decimal_arg(True) is None  # bool 不参与数值约束
    assert as_decimal_arg(3) == Decimal(3)
    assert as_decimal_arg(Decimal('1.5')) == Decimal('1.5')
    assert as_decimal_arg(Decimal('NaN')) is None
    assert as_decimal_arg('3') is None
    assert as_decimal_arg(None) is None


# ═══════════════════════════════════════════════════════════
# 相等比较
# ═══════════════════════════════════════════════════════════


def test_safe_equal_nan_does_not_raise() -> None:
    assert safe_equal(Decimal('NaN'), Decimal('NaN')) is False
    assert safe_equal(Decimal('1.0'), Decimal('1')) is True


def test_std_equal_none_and_literals() -> None:
    one = StdLiteral(kind='int', value=1)
    assert std_equal(None, None) is True
    assert std_equal(None, one) is False
    assert std_equal(one, StdLiteral(kind='int', value=1)) is True
    assert std_equal(one, StdLiteral(kind='int', value=2)) is False


def test_std_equal_int_float_cross_kind() -> None:
    assert std_equal(StdLiteral(kind='int', value=42), StdLiteral(kind='float', value=Decimal('42'))) is True
    assert std_equal(StdLiteral(kind='int', value=1), StdLiteral(kind='float', value=Decimal('1.5'))) is False


def test_std_equal_bool_and_int_are_distinct() -> None:
    assert std_equal(StdLiteral(kind='bool', value=True), StdLiteral(kind='int', value=1)) is False


def test_std_equal_nan_is_not_equal_to_itself() -> None:
    nan = StdLiteral(kind='float', value=Decimal('NaN'))
    assert std_equal(nan, StdLiteral(kind='float', value=Decimal('NaN'))) is False


def test_std_equal_str_and_path_are_distinct() -> None:
    assert std_equal(StdLiteral(kind='str', value='/x'), StdLiteral(kind='path', value=PurePosixPath('/x'))) is False


def test_std_equal_arrays() -> None:
    a = StdArray(elements=[StdLiteral(kind='int', value=1), StdLiteral(kind='int', value=2)])
    b = StdArray(elements=[StdLiteral(kind='int', value=1), StdLiteral(kind='int', value=2)])
    c = StdArray(elements=[StdLiteral(kind='int', value=2), StdLiteral(kind='int', value=1)])
    d = StdArray(elements=[StdLiteral(kind='int', value=1)])
    assert std_equal(a, b) is True
    assert std_equal(a, c) is False
    assert std_equal(a, d) is False


def test_std_equal_objects_ignore_field_order() -> None:
    a = StdObject(
        fields=[
            StdField(name='a', value=StdLiteral(kind='int', value=1)),
            StdField(name='b', value=StdLiteral(kind='int', value=2)),
        ]
    )
    b = StdObject(
        fields=[
            StdField(name='b', value=StdLiteral(kind='int', value=2)),
            StdField(name='a', value=StdLiteral(kind='int', value=1)),
        ]
    )
    missing = StdObject(fields=[StdField(name='a', value=StdLiteral(kind='int', value=1))])
    assert std_equal(a, b) is True
    assert std_equal(a, missing) is False


def test_std_equal_different_node_types() -> None:
    assert std_equal(StdLiteral(kind='int', value=1), StdArray(elements=[])) is False


# ═══════════════════════════════════════════════════════════
# Python 值 → StdValue
# ═══════════════════════════════════════════════════════════


def test_as_std_value_scalars() -> None:
    assert as_std_value(None) == StdLiteral(kind='null', value=None)
    assert as_std_value(True) == StdLiteral(kind='bool', value=True)  # bool 先于 int
    assert as_std_value(3) == StdLiteral(kind='int', value=3)
    assert as_std_value(Decimal('1.5')) == StdLiteral(kind='float', value=Decimal('1.5'))
    assert as_std_value('x') == StdLiteral(kind='str', value='x')


def test_as_std_value_path_normalizes_posix() -> None:
    value = as_std_value(PurePosixPath('/a/../b'))
    assert isinstance(value, StdLiteral)
    assert value.kind == 'path'
    assert value.value == PurePosixPath('/a/../b')


def test_as_std_value_sequence_and_mapping() -> None:
    array = as_std_value([1, 'x'])
    assert isinstance(array, StdArray)
    assert [e for e in array.elements] == [
        StdLiteral(kind='int', value=1),
        StdLiteral(kind='str', value='x'),
    ]

    obj = as_std_value({'a': 1})
    assert isinstance(obj, StdObject)
    assert obj.fields == [StdField(name='a', value=StdLiteral(kind='int', value=1))]


def test_as_std_value_unknown_type_falls_back_to_str() -> None:
    class Thing:
        def __str__(self) -> str:
            return 'thing'

    value = as_std_value(Thing())
    assert value == StdLiteral(kind='str', value='thing')


# ═══════════════════════════════════════════════════════════
# 嵌套参数 / 名称
# ═══════════════════════════════════════════════════════════


def test_as_spec_accepts_constraint_and_bare_name() -> None:
    spec = ResolvedConstraint(name='int')
    assert as_spec(spec) is spec

    from_name = as_spec('range')
    assert from_name is not None
    assert from_name.name == 'range'
    assert from_name.args == []
    assert from_name.source is None

    assert as_spec(42) is None
    assert as_spec(None) is None


def test_spec_name() -> None:
    assert spec_name(ResolvedConstraint(name='int')) == 'int'
    assert spec_name('range') == 'range'
    assert spec_name(42) == '42'
