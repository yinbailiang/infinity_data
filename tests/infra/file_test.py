"""infra/file.py 单元测试：File / DiskFile / MemFile。"""

from pathlib import Path

from infinity_data.infra.file import DiskFile, MemFile


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
    assert df.name == '/a/b/c.infd'
    assert df.root_path == Path('/a/b')
