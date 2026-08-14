"""M3 安全模型：沙盒配置（SandboxConfig）、顶层 Schema 约束与安全异常。

设计要点（extra_desg.md §2-3）：

- 零信任默认：库默认 ``deny_all()``，所有导入能力关闭，调用者显式开放
- 授权矩阵：``env``（环境变量注入）、``allow_files``（!file 白名单）、
  ``allow_templates``（!from 白名单）
- ``strict`` 模式控制违规行为：True 抛 :class:`SandboxError`，False 仅警告
- 白名单值为 glob 模式（``None`` = 全部允许），相对模式以导入基准目录解析
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Literal, cast

from infinity_data.infra.errors import InfinityDataError
from infinity_data.infra.location import SourceRange

__all__ = ['SandboxConfig', 'SandboxError', 'SchemaError', 'Schema']


def _match_globs(target: Path, patterns: list[str] | None, base: Path) -> bool:
    """目标路径是否命中任一 glob 白名单模式。

    - ``patterns is None`` → 全部允许（full_access）
    - 绝对模式（``/`` 起始）直接对绝对路径匹配
    - 相对模式以 ``base`` 为基准，``*`` 不跨目录分隔符，``**`` 跨
    """
    if patterns is None:
        return True
    target_abs = target.resolve()
    base_abs = base.resolve()
    for pattern in patterns:
        p = pattern.strip()
        if not p:
            continue
        if p.startswith('./'):
            p = p[2:]
        if p.startswith('/'):
            if PurePosixPath(target_abs.as_posix()).match(p):
                return True
            continue
        try:
            rel = target_abs.relative_to(base_abs)
        except ValueError:
            continue  # 目标在 base 之外：仅能由绝对模式命中
        if PurePosixPath(rel.as_posix()).match(p):
            return True
    return False


@dataclass
class SandboxConfig:
    """控制 .infd 文件的导入权限。默认零信任。"""

    # ── 环境变量注入：key → value。未列出的变量 !env import 时受限 ──
    env: dict[str, str] = field(default_factory=lambda: {})

    # ── 文件导入白名单（glob 模式；None = 全部允许）──
    allow_files: list[str] | None = field(default_factory=lambda: [])

    # ── 模板导入白名单（glob 模式；None = 全部允许）──
    allow_templates: list[str] | None = field(default_factory=lambda: [])

    # ── 严格模式：True 白名单外导入抛 SandboxError；False 仅警告 ──
    strict: bool = True

    # ── 工厂方法 ──────────────────────────────────────

    @staticmethod
    def deny_all() -> SandboxConfig:
        """零信任：所有导入关闭。库默认。"""
        return SandboxConfig()

    @staticmethod
    def full_access() -> SandboxConfig:
        """全权限：继承当前进程的所有能力。CLI 默认。"""
        return SandboxConfig(
            env=dict(os.environ),
            allow_files=None,
            allow_templates=None,
        )

    @staticmethod
    def development() -> SandboxConfig:
        """开发模式：当前目录全权限 + 完整环境变量。

        注意：``**/*`` 不匹配根级文件，需同时提供 ``*``。
        """
        return SandboxConfig(
            env=dict(os.environ),
            allow_files=['*', '**/*'],
            allow_templates=['*', '**/*'],
        )

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SandboxConfig:
        """从 safe_load 的结果构造 SandboxConfig（自举场景）。"""
        raw_env = cast(dict[Any, Any] | None, d.get('env'))
        raw_files = cast(list[Any] | None, d.get('allow_files'))
        raw_templates = cast(list[Any] | None, d.get('allow_templates'))
        env = {str(k): str(v) for k, v in raw_env.items()} if raw_env is not None else {}
        allow_files = [str(x) for x in raw_files] if raw_files is not None else None
        allow_templates = [str(x) for x in raw_templates] if raw_templates is not None else None
        return cls(
            env=env,
            allow_files=allow_files,
            allow_templates=allow_templates,
            strict=bool(d.get('strict', True)),
        )

    # ── 授权检查 ──────────────────────────────────────

    def authorize_file(self, target: Path, base: Path) -> bool:
        """!file 导入目标是否授权。"""
        return _match_globs(target, self.allow_files, base)

    def authorize_template(self, target: Path, base: Path) -> bool:
        """!from 导入目标是否授权。"""
        return _match_globs(target, self.allow_templates, base)


class SandboxError(InfinityDataError):
    """导入超出沙盒授权（strict 模式抛出）。"""

    _msg: str

    def __init__(self, message: str, source: SourceRange | None = None) -> None:
        super().__init__(source=source)
        self._msg = message

    def _format_message(self) -> str:
        return self._msg


class SchemaError(InfinityDataError):
    """编译产物不符合顶层 schema 约束（无具体源码位置时 source 为 None）。"""

    _msg: str

    def __init__(self, message: str, source: SourceRange | None = None) -> None:
        super().__init__(source=source)
        self._msg = message

    def _format_message(self) -> str:
        return self._msg


@dataclass
class Schema:
    """顶层模板约束：强制编译产物符合指定模板的结构。"""

    template: str  # 模板名
    from_file: str | None = None  # 模板所在文件；None = 与配置同文件（或已导入）
    mode: Literal['strict', 'lenient', 'strip'] = 'strict'

    # strict:  额外字段 → 报错（SchemaError）。必填字段缺失 → 报错
    # lenient: 额外字段 → 警告。必填字段缺失 → 报错
    # strip:   额外字段 → 静默丢弃。必填字段缺失 → 报错
