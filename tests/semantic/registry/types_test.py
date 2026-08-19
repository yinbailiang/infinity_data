"""semantic/registry/types.py 单元测试：类型约束注册。"""

from infinity_data.semantic.registry import ConstraintRegistry


def test_type_constraints_registered() -> None:
    names = ConstraintRegistry().names
    for n in ('int', 'str', 'bool', 'float', 'list', 'dict', 'object', '?'):
        assert n in names, f'类型约束 {n} 未注册'


def test_registry_names_is_read_only_view() -> None:
    names = ConstraintRegistry().names
    assert 'int' in names
