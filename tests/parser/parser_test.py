"""parser/parser.py 单元测试：Parser 语法规则（输入为 token 链，测试解析行为）。"""

from pathlib import Path

from infinity_data.infra.diagnostics import DiagnosticCollector
from infinity_data.infra.file import MemFile
from infinity_data.parser import DictValue, Field, TemplateDef, TemplateField
from infinity_data.parser.parser import Parser
from infinity_data.tokenizer.finalizer import FinalTokenizer
from infinity_data.tokenizer.tokenizer import RawTokenizer


def _parse(src: str):
    file = MemFile(name='t.infd', root_path=Path('.'), content=src)
    col = DiagnosticCollector()
    parser = Parser(FinalTokenizer(RawTokenizer(file=file, error_collector=col)), error_collector=col)
    doc = parser.parse()
    return doc, list(col)


def test_field_statement() -> None:
    doc, diags = _parse('a = 1\n')
    assert not diags
    stmt = doc.statements[0]
    assert isinstance(stmt, Field)
    assert stmt.name == 'a'


def test_template_def_and_field() -> None:
    doc, diags = _parse('~X {\n    a: int = 1\n}\n')
    assert not diags
    tpl = doc.statements[0]
    assert isinstance(tpl, TemplateDef)
    assert isinstance(tpl.fields[0], TemplateField)
    assert tpl.fields[0].name == 'a'


def test_dict_value() -> None:
    doc, _ = _parse('y = {a = 1, b = 2}\n')
    field = doc.statements[0]
    assert isinstance(field, Field)
    assert isinstance(field.value, DictValue)


def test_missing_separator_reported() -> None:
    _, diags = _parse('x = [1 2]\n')
    assert any(d.code == 'parse.missing_separator' for d in diags)


def test_unrecognized_statement_reported() -> None:
    _, diags = _parse(')\n')
    assert any(d.code == 'parse.unrecognized_statement' for d in diags)


def test_omitted_equals_requires_composite() -> None:
    _, diags = _parse('x 123\n')
    assert any(d.code == 'parse.field_requires_equals' for d in diags)


def test_template_field_requires_constraint() -> None:
    _, diags = _parse('~X {\n    a\n}\n')
    assert any(d.code == 'parse.template_field_no_constraint' for d in diags)
