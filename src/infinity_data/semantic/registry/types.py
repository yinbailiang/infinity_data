"""内置类型约束：object / ? / int / str / bool / float / list / dict / path。"""

from __future__ import annotations

import posixpath
from collections.abc import Callable
from pathlib import Path, PurePath, PurePosixPath
from typing import Any

from infinity_data.infra.diagnostics import Severity
from infinity_data.semantic.builder.models import StdArray, StdLiteral, StdObject, StdValue
from infinity_data.semantic.registry._core import (
    ConstraintResult,
    Executor,
    describe,
    fail_result,
    ok_result,
)
from infinity_data.semantic.registry._core import (
    path_str as _path_str,
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
    '_check_same_target',
    '_check_same_name',
    '_check_extension',
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
    # path 与 str 是独立基础类型（§1.4）：字符串约束只认 str
    if isinstance(val, StdLiteral) and val.kind == 'str':
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
# - ``path``：值必须是 path 类型（str 与 path 独立，§1.4）
# - ``exist`` / ``dir`` / ``file`` / ``link``：**构建期文件系统校验**（与导入同属
#   当前机器状态），经 :class:`Executor` 暴露的沙盒授权探测（deny_all → 拒绝）
# - ``same_target`` / ``same_name`` / ``extension``：**纯语法**路径约束（无 FS 访问）


def _check_path(
    val: StdValue | None,
    source: SourceRange | None,
    path: str,
    args: list[Any],
    executor: Executor,
) -> ConstraintResult:
    """path：值必须是 path 类型（``p"..."`` / ``as path`` 产生）。

    str 与 path 是**相互独立的基础类型**——字符串不满足 path（下游无二义）；
    str 值须经 ``as path`` 显式转换（§1.8）才能作为路径使用。
    """
    if isinstance(val, StdLiteral) and val.kind == 'path':
        return ok_result()
    return fail_result('constraint.type_mismatch', {'expected': 'path', 'actual': describe(val)}, source, path)


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


# ── 路径语法约束（纯语法，无文件系统访问） ────────────


def _check_same_target(
    val: StdValue | None,
    source: SourceRange | None,
    path: str,
    args: list[Any],
    executor: Executor,
) -> ConstraintResult:
    """same_target(path)：当前 path 与参数 path **词法解析后**指向同一目标。

    用 :func:`posixpath.normpath` 折叠 ``.`` / ``..`` 后字符串相等——
    纯字符串操作、不触碰文件系统、不解引用符号链接：纯语法、可复现（§1.2.1）。
    """
    s = _path_str(val)
    if s is None:
        return fail_result('constraint.type_mismatch', {'expected': 'path', 'actual': describe(val)}, source, path)
    other = args[0]
    if not isinstance(other, PurePath):
        return fail_result('constraint.same_target_arg', {'expected': 'path 字面量'}, source, path)
    a = posixpath.normpath(s)
    b = posixpath.normpath(other.as_posix())
    if a != b:
        return fail_result('constraint.same_target_mismatch', {'value': s, 'expected': other.as_posix()}, source, path)
    return ok_result()


def _check_same_name(
    val: StdValue | None,
    source: SourceRange | None,
    path: str,
    args: list[Any],
    executor: Executor,
) -> ConstraintResult:
    """same_name(str)：路径的 basename（最后一段）等于指定字符串。"""
    s = _path_str(val)
    if s is None:
        return fail_result('constraint.type_mismatch', {'expected': 'path', 'actual': describe(val)}, source, path)
    expected = args[0]
    if not isinstance(expected, str):
        return fail_result('constraint.same_name_arg', {'expected': '字符串'}, source, path)
    name = PurePosixPath(s).name
    if name != expected:
        return fail_result('constraint.same_name_mismatch', {'name': name, 'expected': expected}, source, path)
    return ok_result()


def _check_extension(
    val: StdValue | None,
    source: SourceRange | None,
    path: str,
    args: list[Any],
    executor: Executor,
) -> ConstraintResult:
    """extension(ext, ...)：路径扩展名匹配任一给定扩展名（不带前导点，如 ``"json"``）。"""
    s = _path_str(val)
    if s is None:
        return fail_result('constraint.type_mismatch', {'expected': 'path', 'actual': describe(val)}, source, path)
    exts = [a if a.startswith('.') else '.' + a for a in args if isinstance(a, str)]
    if not exts:
        return fail_result('constraint.extension_arg', {'expected': '扩展名字符串'}, source, path)
    suffix = PurePosixPath(s).suffix  # '.json' 或 ''（无扩展名）
    if suffix not in exts:
        return fail_result(
            'constraint.extension_mismatch', {'suffix': suffix or '(无)', 'expected': args}, source, path
        )
    return ok_result()
