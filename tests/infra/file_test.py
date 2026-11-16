"""infra/file.py 单元测试：File / DiskFile / MemFile。"""

from pathlib import Path

from infinity_data.infra.file import DiskFile, MemFile
from infinity_data.sandbox import Sandbox, SandboxConfig


def test_mem_read_and_chars() -> None:
    mem = MemFile(name='a.infd', root_path=Path('.'), content='a = 1\n')
    assert mem.read() == 'a = 1\n'
    assert list(mem.chars()) == list('a = 1\n')


def test_mem_identity_content_addressed() -> None:
    mem = MemFile(name='a.infd', root_path=Path('.'), content='x')
    assert 'mem:' in mem.identity
    assert mem.identity.endswith(mem.content_hash())


def test_content_hash_stable_and_machine_agnostic() -> None:
    m1 = MemFile(name='a', root_path=Path('.'), content='hello')
    m2 = MemFile(name='b', root_path=Path('.'), content='hello')
    assert m1.content_hash() == m2.content_hash()
    assert len(m1.content_hash()) == 12  # sha256 前缀


def test_disk_read_and_identity(tmp_path: Path) -> None:
    p = tmp_path / 'x.infd'
    p.write_text('v = 1\n', encoding='utf-8')
    df = DiskFile.from_fullpath(p)
    assert df.read() == 'v = 1\n'
    assert df.identity == str(p.resolve())
    assert df.path == p


def test_disk_root_path_derived() -> None:
    df = DiskFile.from_fullpath('/a/b/c.infd')
    # name 是原生 Path 字符串（Windows 上为反斜杠）→ as_posix 归一化比较
    assert Path(df.name).as_posix() == '/a/b/c.infd'
    assert df.root_path == Path('/a/b')


def test_disk_read_is_cached_per_instance(tmp_path: Path) -> None:
    """同一 DiskFile 只读一次；需要新内容时重新构造。"""
    p = tmp_path / 'x.infd'
    p.write_text('a = 1\n', encoding='utf-8')
    df = DiskFile.from_fullpath(p)
    assert df.read() == 'a = 1\n'
    p.write_text('b = 2\n', encoding='utf-8')
    assert df.read() == 'a = 1\n'
    assert DiskFile.from_fullpath(p).read() == 'b = 2\n'


def test_sandbox_reuses_disk_file_instance(tmp_path: Path) -> None:
    """同一次编译的 Sandbox 内，同一目标路径返回同一 DiskFile（读取缓存生效）。"""
    p = tmp_path / 'x.infd'
    p.write_text('a = 1\n', encoding='utf-8')
    sandbox = Sandbox(config=SandboxConfig.full_access(), base_dir=tmp_path)
    f1 = sandbox.open_file(str(p))
    f2 = sandbox.open_file(str(p))
    assert f1 is not None and f2 is not None
    assert f1 is f2
    assert f1.read() == 'a = 1\n'
    p.write_text('b = 2\n', encoding='utf-8')
    assert f2.read() == 'a = 1\n'
