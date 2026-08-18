"""沙盒中介：库的系统访问唯一通道。

库不直接接触文件系统/环境变量——文件来源（:class:`File`）与变量值
一律由沙盒产出；授权匹配与授权谓词也在此实现（config 纯数据零行为）。
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from infinity_data.infra.file import DiskFile, File
from infinity_data.infra.location import SourceRange
from infinity_data.sandbox.config import SandboxConfig
from infinity_data.sandbox.errors import SandboxError

__all__ = ['Sandbox']


def match_globs(target: Path, patterns: list[str] | None, base: Path) -> bool:
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


class Sandbox:
    """系统访问中介：从 :class:`SandboxConfig` 构造。

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

    # ── 授权谓词（公开，无副作用）────────────────────

    def authorize_file(self, target: Path, base: Path | None = None) -> bool:
        """!file 导入目标是否授权。"""
        return match_globs(target, self._config.allow_files, base or self._base_dir)

    def authorize_template(self, target: Path, base: Path | None = None) -> bool:
        """!from 导入目标是否授权。"""
        return match_globs(target, self._config.allow_templates, base or self._base_dir)

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

        if not match_globs(path, patterns, self._base_dir):
            if self._config.strict:
                raise SandboxError(f'{label}超出沙盒授权: {from_path}', source)
            return None
        return DiskFile.from_fullpath(path)
