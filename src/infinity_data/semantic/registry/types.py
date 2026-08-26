"""内置类型约束：object / ? / int / str / bool / float / list / dict / path。"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path, PurePath
from typing import Any

from infinity_data.infra.diagnostics import Severity
from infinity_data.infra.path import is_valid_posix_path
from infinity_data.semantic.builder.models import StdArray, StdLiteral, StdObject, StdValue
from infinity_data.semantic.registry._core import (
    ConstraintResult,
    Executor,
    describe,
    fail_result,
    ok_result,
)
from infinity_data.tokenizer.models.raw_tokens import SourceRange

__all__ = [
    '_check_object',
    '_check_nullable',
    '_check_int',
    '_check_float',
    '_check_str',
    '_check_bool',
    '_check_list',
    '_check_dict',
    '_check_path',
    '_check_exist',
    '_check_dir',
    '_check_file',
    '_check_link',
]


def _check_object(
    val: StdValue | None,
    source: SourceRange | None,
    path: str,
    args: list[Any],
    executor: Executor,
) -> ConstraintResult:
    if val is None:
        return fail_result('constraint.expect_value', {'expected': 'object'}, source, path)
    return ok_result()


def _check_nullable(
    val: StdValue | None,
    source: SourceRange | None,
    path: str,
    args: list[Any],
    executor: Executor,
) -> ConstraintResult:
    if isinstance(val, StdLiteral) and val.kind in ('null', 'noexist'):
        return ok_result()
    return fail_result(
        'constraint.type_mismatch', {'expected': 'noexist 或 null', 'actual': describe(val)}, source, path
    )


def _check_int(
    val: StdValue | None,
    source: SourceRange | None,
    path: str,
    args: list[Any],
    executor: Executor,
) -> ConstraintResult:
    if val is None:
        return fail_result('constraint.expect_value', {'expected': 'int'}, source, path)
    if isinstance(val, StdLiteral) and val.kind == 'int':
        return ok_result()
    return fail_result('constraint.type_mismatch', {'expected': 'int', 'actual': describe(val)}, source, path)


def _check_float(
    val: StdValue | None,
    source: SourceRange | None,
    path: str,
    args: list[Any],
    executor: Executor,
) -> ConstraintResult:
    if val is None:
        return fail_result('constraint.expect_value', {'expected': 'float'}, source, path)
    if isinstance(val, StdLiteral) and val.kind == 'float':
        return ok_result()  # 含 NaN / ±Infinity
    return fail_result('constraint.type_mismatch', {'expected': 'float', 'actual': describe(val)}, source, path)


def _check_str(
    val: StdValue | None,
    source: SourceRange | None,
    path: str,
    args: list[Any],
    executor: Executor,
) -> ConstraintResult:
    if val is None:
        return fail_result('constraint.expect_value', {'expected': 'str'}, source, path)
    # path 是 str 的特化（§1.5）：字符串约束接受 path 值
    if isinstance(val, StdLiteral) and val.kind in ('str', 'path'):
        return ok_result()
    return fail_result('constraint.type_mismatch', {'expected': 'str', 'actual': describe(val)}, source, path)


def _check_bool(
    val: StdValue | None,
    source: SourceRange | None,
    path: str,
    args: list[Any],
    executor: Executor,
) -> ConstraintResult:
    if val is None:
        return fail_result('constraint.expect_value', {'expected': 'bool'}, source, path)
    if isinstance(val, StdLiteral) and val.kind == 'bool':
        return ok_result()
    return fail_result('constraint.type_mismatch', {'expected': 'bool', 'actual': describe(val)}, source, path)


def _check_list(
    val: StdValue | None,
    source: SourceRange | None,
    path: str,
    args: list[Any],
    executor: Executor,
) -> ConstraintResult:
    if val is None:
        return fail_result('constraint.expect_value', {'expected': 'list'}, source, path)
    if isinstance(val, StdArray):
        return ok_result()
    return fail_result('constraint.type_mismatch', {'expected': 'list', 'actual': describe(val)}, source, path)


def _check_dict(
    val: StdValue | None,
    source: SourceRange | None,
    path: str,
    args: list[Any],
    executor: Executor,
) -> ConstraintResult:
    if val is None:
        return fail_result('constraint.expect_value', {'expected': 'dict'}, source, path)
    if isinstance(val, StdObject):
        return ok_result()
    return fail_result('constraint.type_mismatch', {'expected': 'dict', 'actual': describe(val)}, source, path)


# ── path 约束族 ────────────────────────────────────────
#
# - ``path``：纯语法校验（非空、无 NUL、可解析），无文件系统访问
# - ``exist`` / ``dir`` / ``file`` / ``link``：**构建期文件系统校验**（与导入同属
#   当前机器状态），经 :class:`Executor` 暴露的沙盒授权探测（deny_all → 拒绝）


def _path_str(val: StdValue | None) -> str | None:
    """从 str / path 字面量提取语言内 POSIX 字符串。"""
    if not isinstance(val, StdLiteral):
        return None
    if val.kind == 'str' and isinstance(val.value, str):
        return val.value
    if val.kind == 'path' and isinstance(val.value, PurePath):
        return val.value.as_posix()
    return None


def _check_path(
    val: StdValue | None,
    source: SourceRange | None,
    path: str,
    args: list[Any],
    executor: Executor,
) -> ConstraintResult:
    """path：值须是合法 POSIX 路径（str / path 均可，纯语法校验）。"""
    s = _path_str(val)
    if s is None:
        return fail_result('constraint.type_mismatch', {'expected': 'path', 'actual': describe(val)}, source, path)
    if not is_valid_posix_path(s):
        return fail_result('constraint.invalid_path', {'value': s}, source, path)
    return ok_result()


def _check_exist(
    val: StdValue | None,
    source: SourceRange | None,
    path: str,
    args: list[Any],
    executor: Executor,
) -> ConstraintResult:
    """exist：路径存在（lstat 成功，file/dir/link 任一）。"""
    return _fs_check(val, source, path, executor, 'exist', lambda p: p.exists())


def _check_dir(
    val: StdValue | None,
    source: SourceRange | None,
    path: str,
    args: list[Any],
    executor: Executor,
) -> ConstraintResult:
    """dir：路径是目录（跟随符号链接，stat）。"""
    return _fs_check(val, source, path, executor, 'dir', lambda p: p.is_dir())


def _check_file(
    val: StdValue | None,
    source: SourceRange | None,
    path: str,
    args: list[Any],
    executor: Executor,
) -> ConstraintResult:
    """file：路径是普通文件（跟随符号链接，stat）。"""
    return _fs_check(val, source, path, executor, 'file', lambda p: p.is_file())


def _check_link(
    val: StdValue | None,
    source: SourceRange | None,
    path: str,
    args: list[Any],
    executor: Executor,
) -> ConstraintResult:
    """link：路径是符号链接（判定链接本身，lstat）。"""
    return _fs_check(val, source, path, executor, 'link', lambda p: p.is_symlink())


def _fs_check(
    val: StdValue | None,
    source: SourceRange | None,
    path: str,
    executor: Executor,
    constraint: str,
    pred: Callable[[Path], bool],
) -> ConstraintResult:
    """文件系统约束公共路径：类型 → 沙盒授权探测 → 谓词判定。

    未授权（跃出沙盒，allow_files 白名单外）→ ``constraint.path_denied``
    **警告 + 失败**（ok=False、WARNING）：约束不满足，但属配置/授权问题而非数据错误。
    """
    s = _path_str(val)
    if s is None:
        return fail_result('constraint.type_mismatch', {'expected': 'path', 'actual': describe(val)}, source, path)
    native = executor.sandbox.probe_path(s)
    if native is None:
        return fail_result(
            'constraint.path_denied',
            {'constraint': constraint, 'path': s},
            source,
            path,
            severity=Severity.WARNING,
        )
    if not pred(native):
        return fail_result(f'constraint.path_not_{constraint}', {'path': s}, source, path)
    return ok_result()
