"""semantic/registry/logic.py 单元测试：逻辑约束注册。"""

from infinity_data.semantic.registry import ConstraintRegistry


def test_logic_constraints_registered() -> None:
    names = ConstraintRegistry().names
    for n in ('not', 'any', 'one', 'all', 'when'):
        assert n in names, f'逻辑约束 {n} 未注册'
