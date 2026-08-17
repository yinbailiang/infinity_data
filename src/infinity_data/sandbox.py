"""M3 安全模型：沙盒配置、沙盒中介、顶层 Schema 约束与安全异常。

设计要点（extra_desg.md §2-3）：

- 零信任默认：库默认 ``deny_all()``，所有导入能力关闭，调用者显式开放
- 授权矩阵：``env``（环境变量注入）、``allow_files``（!file 白名单）、
  ``allow_templates``（!from 白名单）
- ``strict`` 模式控制违规行为：True 抛 :class:`SandboxError`，False 仅警告
- 白名单值为 glob 模式（``None`` = 全部允许），相对模式以编译入口目录解析
- :class:`Sandbox` 是系统访问中介：库不直接接触文件系统/环境变量，
  文件来源（:class:`File`）一律由沙盒产出
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Literal, cast

from infinity_data.infra.errors import InfinityDataError
from infinity_data.infra.file import DiskFile, File
from infinity_data.infra.location import SourceRange

__all__ = ['Sandbox', 'SandboxConfig', 'SandboxError', 'SchemaError', 'Schema']


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
        """!file 导入目标是否授权（公开谓词）。"""
        return _match_globs(target, self.allow_files, base)

    def authorize_template(self, target: Path, base: Path) -> bool:
        """!from 导入目标是否授权（公开谓词）。"""
        return _match_globs(target, self.allow_templates, base)


class Sandbox:
    """系统访问中介：从 :class:`SandboxConfig` 构造。

    库不直接接触文件系统/环境变量——文件来源（:class:`File`）与变量值
    一律由沙盒产出：

    - :meth:`open_file` / :meth:`open_template`：路径解析 + glob 授权 → File
    - :meth:`getenv`：env 授权查询
    - strict 违规 → 抛 :class:`SandboxError`；非 strict → None（调用方警告）
    """

    def __init__(self, config: SandboxConfig, base_dir: Path) -> None:
        self._config = config
        self._base_dir = base_dir

    @property
    def config(self) -> SandboxConfig:
        return self._config

    @property
    def base_dir(self) -> Path:
        """编译入口目录（glob 授权基准）。"""
        return self._base_dir

    # ── 环境变量 ──────────────────────────────────────

    def getenv(self, name: str, *, source: SourceRange | None = None) -> str | None:
        """env 授权查询：未授权 strict 抛 :class:`SandboxError`，否则 None。"""
        if name in self._config.env:
            return self._config.env[name]
        if self._config.strict:
            raise SandboxError(f'环境变量 {name!r} 未在沙盒授权（!env import）', source)
        return None

    # ── 文件来源 ──────────────────────────────────────

    def open_file(
        self,
        from_path: str,
        *,
        base_dir: Path | None = None,
        source: SourceRange | None = None,
    ) -> File | None:
        """!file 目标：路径解析 + allow_files 授权 → File。"""
        return self._open(from_path, self._config.allow_files, '文件导入', base_dir, source)

    def open_template(
        self,
        from_path: str,
        *,
        base_dir: Path | None = None,
        source: SourceRange | None = None,
    ) -> File | None:
        """!from 目标：路径解析 + allow_templates 授权 → File。"""
        return self._open(from_path, self._config.allow_templates, '模板导入', base_dir, source)

    def _open(
        self,
        from_path: str,
        patterns: list[str] | None,
        label: str,
        base_dir: Path | None,
        source: SourceRange | None,
    ) -> File | None:
        """公共路径解析 + 授权（相对路径以 base_dir 解析，glob 以入口目录匹配）。"""
        base = base_dir if base_dir is not None else self._base_dir
        path = Path(from_path)
        if not path.is_absolute():
            path = base / path

        if not _match_globs(path, patterns, self._base_dir):
            if self._config.strict:
                raise SandboxError(f'{label}超出沙盒授权: {from_path}', source)
            return None
        return DiskFile.from_fullpath(path)


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
