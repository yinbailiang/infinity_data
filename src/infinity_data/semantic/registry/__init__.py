"""约束注册表：内置约束 + 用户自定义（模板即约束）。

- 表驱动：每个约束登记 ``(name, fn, min_args, max_args, description)``
- 内置约束按类别拆分子模块：types / general / dict_constraints / logic，
  注册表在此组装（单注册表 = 唯一执行入口）
- ``executor`` 回调支持嵌套约束：``each`` / ``not`` / ``any`` / ``one`` /
  ``all`` / ``when`` / ``field`` / 模板约束
- M5 将在 :class:`ConstraintEntry` 上追加 json_schema 生成回调，
  实现「模板即约束 → JSON Schema」的单注册表复用
"""

from __future__ import annotations

from infinity_data.semantic.models import ResolvedConstraint, StdValue
from infinity_data.semantic.registry._core import (
    ConstraintEntry,
    ConstraintFn,
    ConstraintResult,
    Executor,
    describe,
    fail_result,
    ok_result,
)
from infinity_data.semantic.registry.dict_constraints import _check_field, _check_has
from infinity_data.semantic.registry.general import (
    _check_each,
    _check_email,
    _check_eq,
    _check_hostname,
    _check_in,
    _check_ip,
    _check_ip4,
    _check_ip6,
    _check_negative,
    _check_nonnegative,
    _check_positive,
    _check_range,
    _check_regex,
    _check_size,
    _check_unique,
    _check_url,
    _check_uuid,
)
from infinity_data.semantic.registry.logic import (
    _check_all,
    _check_any,
    _check_not,
    _check_one,
    _check_when,
)
from infinity_data.semantic.registry.types import (
    _check_bool,
    _check_dict,
    _check_float,
    _check_int,
    _check_list,
    _check_nullable,
    _check_object,
    _check_str,
)
from infinity_data.tokenizer.models.raw_tokens import SourceRange

__all__ = [
    'ConstraintRegistry',
    'ConstraintResult',
    'ConstraintEntry',
    'ConstraintFn',
    'Executor',
    'ok_result',
    'fail_result',
    'describe',
]


class ConstraintRegistry:
    """约束注册表：内置约束 + 用户自定义（模板即约束）。"""

    def __init__(self) -> None:
        self._entries: dict[str, ConstraintEntry] = {}
        self._register_builtins()

    def register(
        self,
        name: str,
        fn: ConstraintFn,
        *,
        min_args: int = 0,
        max_args: int | None = None,
        description: str = '',
    ) -> None:
        self._entries[name] = ConstraintEntry(
            name=name,
            fn=fn,
            min_args=min_args,
            max_args=max_args,
            description=description,
        )

    def lookup(self, name: str) -> ConstraintEntry | None:
        return self._entries.get(name)

    @property
    def names(self) -> list[str]:
        return list(self._entries)

    def apply(
        self,
        constraint: ResolvedConstraint,
        value: StdValue | None,
        source: SourceRange | None,
        path: str,
        executor: Executor,
    ) -> ConstraintResult:
        """按名称执行约束（含参数个数校验）。"""
        entry = self._entries.get(constraint.name)
        if entry is None:
            return fail_result('constraint.unknown', {'name': constraint.name}, source, path)
        n = len(constraint.args)
        if n < entry.min_args or (entry.max_args is not None and n > entry.max_args):
            expected = str(entry.min_args) if entry.max_args is None else f'{entry.min_args}~{entry.max_args}'
            return fail_result(
                'constraint.arg_count', {'name': constraint.name, 'expected': expected, 'given': n}, source, path
            )
        return entry.fn(value, source, path, constraint.args, executor)

    def _register_builtins(self) -> None:
        """注册 neo_desg.md §1.2 全部内置约束。"""
        # ── 类型约束 ──────────────────────────────
        self.register('object', _check_object, description='通用超类型，总是通过')
        self.register('?', _check_nullable, description='纯可空类型：noexist 或 null')
        self.register('int', _check_int, description='有符号整数')
        self.register('float', _check_float, description='十进制浮点（只接受 float，不含 int 提升）')
        self.register('str', _check_str, description='utf-8 字符串')
        self.register('bool', _check_bool, description='布尔值')
        self.register('list', _check_list, description='数组')
        self.register('dict', _check_dict, description='字典')

        # ── 一般约束 ──────────────────────────────
        self.register('range', _check_range, min_args=1, max_args=2, description='数值范围 range(ge[, le])，可省略一端')
        self.register('size', _check_size, min_args=1, max_args=2, description='集合大小或字符串长度 size(ge[, le])')
        self.register('each', _check_each, min_args=1, max_args=1, description='每个元素均满足 each(constraint)')
        self.register('in', _check_in, min_args=1, description='值在给定选项中 in(choice, ...)')
        self.register('ip', _check_ip, description='IPv4 或 IPv6 地址')
        self.register('ip4', _check_ip4, description='IPv4 地址')
        self.register('ip6', _check_ip6, description='IPv6 地址')
        self.register('regex', _check_regex, min_args=1, max_args=1, description='正则全匹配 regex("re")')
        self.register('email', _check_email, description='邮箱格式')
        self.register('url', _check_url, description='URL 格式')
        self.register('uuid', _check_uuid, description='UUID 格式')
        self.register('hostname', _check_hostname, description='主机名格式')
        self.register('positive', _check_positive, description='正数 (> 0)')
        self.register('negative', _check_negative, description='负数 (< 0)')
        self.register('nonnegative', _check_nonnegative, description='非负数 (>= 0)')
        self.register('eq', _check_eq, min_args=1, max_args=1, description='等于指定值 eq(value)')
        self.register('unique', _check_unique, description='集合元素不重复')

        # ── 字典约束 ──────────────────────────────
        self.register('has', _check_has, min_args=1, max_args=1, description='包含指定键 has(key)')
        self.register('field', _check_field, min_args=2, max_args=2, description='字段约束 field(name, constraint)')

        # ── 逻辑约束 ──────────────────────────────
        self.register('not', _check_not, min_args=1, max_args=1, description='内部约束不满足则满足')
        self.register('any', _check_any, min_args=1, description='任意子约束满足')
        self.register('one', _check_one, min_args=1, description='恰好一个子约束满足')
        self.register('all', _check_all, min_args=1, description='全部子约束满足')
        self.register(
            'when', _check_when, min_args=2, max_args=2, description='条件满足时要求另一约束满足 when(cond, req)'
        )
