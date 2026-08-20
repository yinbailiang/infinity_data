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
    file = MemFile(name='t.infd', root_path=Path('.'), content='')
    _, diags = parse_source(file)
    assert diags and any(d.code == 'parse.empty_token_list' for d in diags)
