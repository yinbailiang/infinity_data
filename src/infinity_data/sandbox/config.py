"""沙盒配置：授权数据（env / allow_files / allow_templates / strict）与工厂方法。

纯数据零行为：授权匹配与访问行为见 :mod:`infinity_data.sandbox.mediator`。
自举场景可直接 ``SandboxConfig(**safe_load(...).value)`` 构造。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

__all__ = ['SandboxConfig']


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
        """零信任"""
        return SandboxConfig()

    @staticmethod
    def full_access() -> SandboxConfig:
        """全权限"""
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
