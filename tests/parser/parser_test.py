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
    parser = Parser(FinalTokenizer(RawTokenizer(file=file, error_collector=col)), collector=col)
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


def test_env_import_requires_newline() -> None:
    """!env 无导入项列表：尾部必须换行/EOF，同一行逗号后接语句必须报错。

    若不检查，同一行逗号会被顶层 skip_separators 吞掉（`!env import A as a, x = 1`
    被误认为合法），与 !from / !file 的「尾部必须换行」行为不一致。
    """
    # 换行结尾 → 合法
    _, diags = _parse('!env import A as a\n')
    assert not diags
    # 同一行逗号接语句 → 报错（逗号仍由顶层吞掉，x = 1 容错继续解析）
    _, diags = _parse('!env import A as a, x = 1\n')
    assert any(d.code == 'parse.import_requires_newline' for d in diags)
    # 尾随逗号（逗号后 EOF）→ 报错
    _, diags = _parse('!env import A as a,')
    assert any(d.code == 'parse.import_requires_newline' for d in diags)


def test_omitted_equals_requires_composite() -> None:
    _, diags = _parse('x 123\n')
    assert any(d.code == 'parse.field_requires_equals' for d in diags)


def test_template_field_requires_constraint() -> None:
    _, diags = _parse('~X {\n    a\n}\n')
    assert any(d.code == 'parse.template_field_no_constraint' for d in diags)


def test_malformed_template_config_no_crash() -> None:
    """错误模板 config 不应 IndexError 或死循环（LSP 输入中途场景）。

    回归：值缺失（~X(a=）、缺 =（~X(a, b=1)）、括号未闭合（~X(a=1）等。
    """
    for src in ['~X(a=\n', '~X(a=', '~X(a, b=1)\n', '~X(description=\n', '~X(allow_extra=\n', '~X(a=1\n']:
        doc, _ = _parse(src)
        assert doc is not None


def test_unterminated_value_no_crash() -> None:
    """未闭合数组/对象/约束不应崩溃（EOF 在值中间）。"""
    for src in ['x = [1,\n', 'x = [1', 'x = {a = ', 'a: ', '~X { a: ']:
        doc, _ = _parse(src)
        assert doc is not None
