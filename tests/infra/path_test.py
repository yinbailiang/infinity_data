"""infra/path.py 单元测试：POSIX ↔ 原生路径映射（platform 注入 + PureWindowsPath 跨平台）。"""

from pathlib import Path, PureWindowsPath

from infinity_data.infra.path import native_to_posix, posix_to_native


def test_posix_on_linux_unchanged() -> None:
    assert posix_to_native('/c/foo/bar', platform='linux') == Path('/c/foo/bar')


def test_drive_mapped_on_windows() -> None:
    # 按 Windows 语义断言（as_posix 归一化分隔符）：真实 Windows 上 Path.str() 为反斜杠
    assert PureWindowsPath(posix_to_native('/c/foo/bar', platform='win32')).as_posix() == 'C:/foo/bar'
    assert PureWindowsPath(posix_to_native('/d/etc', platform='win32')).as_posix() == 'D:/etc'


def test_non_drive_absolute_unchanged_on_windows() -> None:
    # /usr/local 无盘符 → 原样（根于当前盘）
    p = PureWindowsPath(posix_to_native('/usr/local', platform='win32'))
    assert p.as_posix() == '/usr/local'
    assert p.drive == ''


def test_relative_path_unchanged() -> None:
    assert PureWindowsPath(posix_to_native('./foo/bar', platform='win32')).as_posix() == 'foo/bar'  # pathlib 归一化 ./
    assert posix_to_native('foo/bar', platform='linux') == Path('foo/bar')


def test_native_to_posix_drive_lowercase() -> None:
    assert native_to_posix(Path('C:/foo/bar')) == '/c/foo/bar'


def test_native_to_posix_without_drive() -> None:
    assert native_to_posix(Path('/usr/local')) == '/usr/local'


# ═══════════════════════════════════════════════════════
# Windows 语义验证（PureWindowsPath 在 Linux 上即给出真 Windows 语义）
# ═══════════════════════════════════════════════════════


def test_mapping_output_has_windows_drive_semantics() -> None:
    """posix_to_native(win32) 产物按 WindowsPath 解释应具备正确的盘符/绝对语义。"""
    p = PureWindowsPath(str(posix_to_native('/c/foo/bar', platform='win32')))
    assert p.drive == 'C:'
    assert p.is_absolute()
    assert p.parts == ('C:\\', 'foo', 'bar')


def test_absolute_join_wins_on_windows() -> None:
    """_open 的 base/绝对路径拼接：Windows 上绝对路径覆盖 base，相对路径基于 base。"""
    base = PureWindowsPath('C:/app')
    target = PureWindowsPath(str(posix_to_native('/d/templates/x.inft', platform='win32')))
    resolved = target if target.is_absolute() else base / target
    assert str(resolved) == 'D:\\templates\\x.inft'

    rel = PureWindowsPath(str(posix_to_native('templates/x.inft', platform='win32')))
    assert str(base / rel) == 'C:\\app\\templates\\x.inft'
