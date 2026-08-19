"""semantic/registry/general.py 单元测试：一般约束注册。"""

from infinity_data.semantic.registry import ConstraintRegistry


def test_general_constraints_registered() -> None:
    names = ConstraintRegistry().names
    for n in ('range', 'size', 'each', 'regex', 'email', 'url', 'uuid', 'hostname', 'positive', 'eq', 'unique'):
        assert n in names, f'一般约束 {n} 未注册'
