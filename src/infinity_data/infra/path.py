"""跨平台路径通行：语言内 POSIX 路径 ↔ 当前平台原生路径。

语言约定（见 neo_desg.md 3.2）：
- 语言内**只允许** POSIX 风格路径（``/`` 分割），Windows 盘符写作 ``/c/...``（小写单字母）
- 访问文件系统时按当前平台**自动映射**，同一份 .infd 在 linux/windows/mac 均可用

函数：
- :func:`posix_to_native`：语言内 POSIX 路径 → 原生 :class:`Path`（Windows 上盘符映射）
- :func:`native_to_posix`：原生路径 → 语言内 POSIX 形式（glob 白名单匹配用）
"""

from __future__ import annotations

import sys
from pathlib import Path, PurePosixPath, PureWindowsPath

__all__ = ['posix_to_native', 'native_to_posix']


def posix_to_native(path: str, *, platform: str | None = None) -> Path:
    """语言内 POSIX 路径 → 当前平台原生 Path。

    - POSIX（linux/mac）：原样使用
    - Windows：``/c/foo/bar`` → ``C:/foo/bar``（盘符转大写）；相对路径由 pathlib 转换分隔符
    - ``platform`` 可注入（默认 ``sys.platform``），便于跨平台单测
    """
    if (platform or sys.platform).lower().startswith('win'):
        pure = PurePosixPath(path)
        if pure.is_absolute() and len(pure.parts) >= 2 and len(pure.parts[1]) == 1 and pure.parts[1].isalpha():
            drive = pure.parts[1].upper() + ':'
            rest = PurePosixPath(*pure.parts[2:]).as_posix()
            return Path(f'{drive}/{rest}')
    return Path(path)


def native_to_posix(path: Path) -> str:
    """原生路径 → 语言内 POSIX 形式（``/`` 分割；Windows 盘符转 ``/c/`` 小写）。

    glob 白名单按语言内 POSIX 形式匹配，保证跨平台一致。
    """
    win = PureWindowsPath(path)
    if win.drive:
        drive_letter = win.drive[0].lower()
        rest = PurePosixPath(*win.parts[1:]).as_posix()
        return f'/{drive_letter}/{rest}'
    return path.as_posix()
