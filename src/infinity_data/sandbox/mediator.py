"""沙盒中介：库的系统访问唯一通道。

库不直接接触文件系统/环境变量——文件来源（:class:`File`）与变量值
一律由沙盒产出；授权匹配与授权谓词也在此实现（config 纯数据零行为）。
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path, PurePosixPath

from infinity_data.infra.file import DiskFile, File
from infinity_data.infra.location import SourceRange
from infinity_data.infra.path import native_to_posix, posix_to_native
from infinity_data.sandbox.config import SandboxConfig
from infinity_data.sandbox.errors import AccessDeniedError, EnvNotAuthorizedError, EnvNotSetError

__all__ = ['Sandbox']


@lru_cache(maxsize=128)
def _translate_segment(segment: str) -> re.Pattern[str] | None:
    """单个路径段 glob → 编译正则（``**`` 段返回 None = 匹配任意多段）。

    语义（与常见 glob 一致）：
    - ``*`` 匹配段内任意字符（不跨 ``/``）
    - ``?`` 匹配段内单个字符
    - ``[...]`` 字符类（``!`` / ``^`` 取反）
    """
    if segment == '**':
        return None
    i, n = 0, len(segment)
    out: list[str] = []
    while i < n:
        c = segment[i]
        if c == '*':
            out.append('[^/]*')
        elif c == '?':
            out.append('[^/]')
        elif c == '[':
            j = i + 1
            if j < n and segment[j] in ('!', '^'):
                j += 1
            if j < n and segment[j] == ']':
                j += 1
            while j < n and segment[j] != ']':
                j += 1
            if j >= n:  # 未闭合的 '[' → 当作字面量
                out.append(r'\[')
            else:
                cls = segment[i : j + 1]
                if cls.startswith('[!'):
                    cls = '[^' + cls[2:]
                out.append(cls)
                i = j
        else:
            out.append(re.escape(c))
        i += 1
    return re.compile(''.join(out))


def _match_pattern(pattern: str, segments: tuple[str, ...]) -> bool:
    """单条 glob 模式与目标路径段序列匹配。

    段级 DP：``**`` 匹配零或多段（含零段，故 ``**/*.json`` 能命中根级文件），
    其余段按正则逐段匹配。与 ``Path.match`` 不同，语义不依赖 Python 版本。
    """
    pattern_segments = tuple(PurePosixPath(pattern).parts)
    if not pattern_segments:
        return not segments
    compiled = [_translate_segment(s) for s in pattern_segments]
    m, n = len(compiled), len(segments)
    dp = [[False] * (n + 1) for _ in range(m + 1)]
    dp[m][n] = True
    for i in range(m - 1, -1, -1):
        seg_re = compiled[i]
        if seg_re is None:  # ** 段：匹配零或多段
            for j in range(n, -1, -1):
                dp[i][j] = dp[i + 1][j] or (j < n and dp[i][j + 1])
        else:
            for j in range(n, -1, -1):
                if j < n and seg_re.fullmatch(segments[j]):
                    dp[i][j] = dp[i + 1][j + 1]
    return dp[0][0]


def match_globs(target: Path, patterns: list[str] | None, base: Path) -> bool:
    """目标路径是否命中任一 glob 白名单模式。

    - ``patterns is None`` → 全部允许（full_access）
    - 绝对模式（``/`` 起始）直接对绝对路径匹配
    - 相对模式以 ``base`` 为基准；``*`` 不跨目录分隔符，``**`` 跨任意段（含零段）
    """
    if patterns is None:
        return True
    target_abs = target.resolve()
    base_abs = base.resolve()
    target_segments = tuple(PurePosixPath(native_to_posix(target_abs)).parts)
    try:
        rel = target_abs.relative_to(base_abs)
        rel_segments: tuple[str, ...] | None = tuple(PurePosixPath(rel.as_posix()).parts)
    except ValueError:
        rel_segments = None  # 目标在 base 之外：仅能由绝对模式命中
    for pattern in patterns:
        p = pattern.strip()
        if not p:
            continue
        if p.startswith('./'):
            p = p[2:]
        if p.startswith('/'):
            if _match_pattern(p, target_segments):
                return True
            continue
        if rel_segments is not None and _match_pattern(p, rel_segments):
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

    def getenv(self, name: str, *, source: SourceRange | None = None) -> str:
        """env 授权查询。

        解析顺序：
        1. 注入值（``SandboxConfig.env``）命中 → 返回（注入优先）
        2. ``allow_env`` 白名单 / 全量授权（None）→ 从真实 OS 环境实时读取
        3. 其余一律抛 :class:`SandboxError`（无 strict 例外）

        已授权但进程未设置同样失败——绝不退化为空字符串注入
        （``DB_PASSWORD`` 变 ``''`` 会悄悄吞掉关键配置）。
        """
        if name in self._config.env:
            return self._config.env[name]
        if self._config.allow_env is None or name in self._config.allow_env:
            value = os.environ.get(name)
            if value is None:
                raise EnvNotSetError(name, source)
            return value
        raise EnvNotAuthorizedError(name, source)

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
        path = posix_to_native(from_path)  # 语言内 POSIX → 当前平台原生（/c/... → C:\...）
        if not path.is_absolute():
            path = base / path

        if not match_globs(path, patterns, self._base_dir):
            if self._config.strict:
                raise AccessDeniedError(label, from_path, source)
            return None
        return DiskFile.from_fullpath(path)
