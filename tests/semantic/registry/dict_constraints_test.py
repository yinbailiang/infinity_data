"""semantic/registry/dict_constraints.py 单元测试：字典约束注册。"""

from infinity_data.semantic.registry import ConstraintRegistry


def test_dict_constraints_registered() -> None:
    names = ConstraintRegistry().names
    for n in ('has', 'field'):
        assert n in names, f'字典约束 {n} 未注册'
