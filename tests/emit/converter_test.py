"""emit/converter.py 单元测试：StdAst 降维（三态可空、嵌套）。"""

from decimal import Decimal

from infinity_data.emit.converter import reduce_array, reduce_object, reduce_value
from infinity_data.semantic.models import StdArray, StdField, StdLiteral, StdObject


def _obj(*fields: StdField) -> StdObject:
    return StdObject(fields=list(fields))


def test_three_state_fields() -> None:
    obj = _obj(
        StdField(name='a', value=StdLiteral(kind='noexist', value=None)),
        StdField(name='b', value=StdLiteral(kind='null', value=None)),
        StdField(name='c', value=StdLiteral(kind='int', value=1)),
    )
    assert reduce_object(obj) == {'b': None, 'c': 1}


def test_null_dropped_when_keep_null_false() -> None:
    obj = _obj(
        StdField(name='b', value=StdLiteral(kind='null', value=None)),
        StdField(name='c', value=StdLiteral(kind='int', value=2)),
    )
    assert reduce_object(obj, keep_null=False) == {'c': 2}


def test_nested_object() -> None:
    inner = _obj(StdField(name='x', value=StdLiteral(kind='int', value=5)))
    obj = _obj(StdField(name='s', value=inner))
    assert reduce_object(obj) == {'s': {'x': 5}}


def test_array_reduction() -> None:
    arr = StdArray(
        elements=[
            StdLiteral(kind='int', value=1),
            StdLiteral(kind='str', value='a'),
            StdLiteral(kind='float', value=Decimal('1.5')),
        ]
    )
    assert reduce_array(arr) == [1, 'a', Decimal('1.5')]


def test_reduce_value_dispatch() -> None:
    assert reduce_value(StdLiteral(kind='bool', value=True)) is True
    obj = _obj(StdField(name='a', value=StdLiteral(kind='int', value=1)))
    assert reduce_value(obj) == {'a': 1}
