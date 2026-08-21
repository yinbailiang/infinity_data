"""frontend.py 单元测试：parse_source 词法+语法入口。"""

from pathlib import Path

from infinity_data.frontend import parse_source
from infinity_data.infra.file import MemFile


def test_parse_source_clean() -> None:
    file = MemFile(name='t.infd', root_path=Path('.'), content='a = 1\n')
    doc, col = parse_source(file)
    assert len(doc.statements) == 1
    assert list(col) == []


def test_parse_source_collects_errors() -> None:
    file = MemFile(name='t.infd', root_path=Path('.'), content='x = [1 2]\n')
    doc, diags = parse_source(file)
    assert any(d.code == 'parse.missing_separator' for d in diags)
    assert doc is not None  # 容错：错误不阻断解析


def test_parse_source_empty() -> None:
    # 空源码 → 空配置（非错误），见 neo_desg.md §4.1
    file = MemFile(name='t.infd', root_path=Path('.'), content='')
    doc, diags = parse_source(file)
    assert not diags
    assert doc.statements == []


def test_parse_source_only_comments() -> None:
    # 仅注释 → 同样空配置（非错误）
    file = MemFile(name='t.infd', root_path=Path('.'), content='# 注释\n#+ 多行 #-\n')
    doc, diags = parse_source(file)
    assert not diags
    assert doc.statements == []
