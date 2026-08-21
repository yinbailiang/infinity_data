"""parser/parser.py 静态方法直接单测。

方法已纯化为 @staticmethod，测试直接构造 TokenStream + DiagnosticCollector，
无需经过 Parser 实例，零 mock 框架。
"""

# pyright: reportPrivateUsage=false
# 白盒单测：有意直接访问受保护静态方法，故关闭该文件的私有成员使用检查。

from pathlib import Path

from infinity_data.infra.diagnostics import DiagnosticCollector
from infinity_data.infra.file import MemFile
from infinity_data.infra.ll1_stream import NoNextType
from infinity_data.parser.models import (
    ArrayValue,
    ConstraintCall,
    ConstraintIdent,
    DictValue,
    Field,
    FileImportItem,
    JsonPathIndex,
    JsonPathKey,
    LiteralValue,
    TemplateCallValue,
    TemplateConfig,
    TemplateField,
    TemplateImportItem,
)
from infinity_data.parser.parser import Parser
from infinity_data.parser.token_stream import TokenStream
from infinity_data.tokenizer.finalizer import FinalTokenizer
from infinity_data.tokenizer.models.raw_tokens import RawTokenType
from infinity_data.tokenizer.models.tokens import IdentifierToken, IntegerToken
from infinity_data.tokenizer.tokenizer import RawTokenizer


def _stream(src: str, col: DiagnosticCollector) -> TokenStream:
    file = MemFile(name='t.infd', root_path=Path('.'), content=src)
    tokens = list(FinalTokenizer(RawTokenizer(file=file, error_collector=col), error_collector=col))
    return TokenStream(tokens, col)


# ── 纯静态辅助 ────────────────────────────────────────


def test_starts_value() -> None:
    col = DiagnosticCollector()
    assert Parser._starts_value(_stream('1', col).peek())
    assert Parser._starts_value(_stream('{', col).peek())
    assert Parser._starts_value(_stream('"x"', col).peek())
    assert Parser._starts_value(_stream('$x', col).peek())
    assert Parser._starts_value(_stream('X()', col).peek())
    assert not Parser._starts_value(_stream('=', col).peek())
    assert not Parser._starts_value(NoNextType())
    assert not Parser._starts_value(None)


def test_starts_constraint() -> None:
    col = DiagnosticCollector()
    assert Parser._starts_constraint(_stream('int', col).peek())
    assert Parser._starts_constraint(_stream('?', col).peek())
    assert Parser._starts_constraint(_stream('"re"', col).peek())
    assert not Parser._starts_constraint(_stream('{', col).peek())


def test_literal_config_value() -> None:
    col = DiagnosticCollector()
    lit = Parser._wrap_literal(_stream('true', col).peek())
    assert Parser._literal_config_value(lit) is True


# ── 关键字 ────────────────────────────────────────────


def test_peek_and_expect_keyword() -> None:
    col = DiagnosticCollector()
    s = _stream('import X', col)
    assert Parser._peek_keyword(s, 'import')
    Parser._expect_keyword(s, col, 'import')
    assert isinstance(s.peek(), IdentifierToken)
    assert not col.has_errors


def test_expect_keyword_missing_reports() -> None:
    col = DiagnosticCollector()
    s = _stream('env X', col)
    Parser._expect_keyword(s, col, 'import')
    assert any(d.code == 'parse.unexpected_token' for d in col)


# ── JSON path ─────────────────────────────────────────


def test_parse_json_path() -> None:
    col = DiagnosticCollector()
    s = _stream('.a.b[0]."c"', col)
    segs: list[JsonPathKey | JsonPathIndex] = Parser._parse_json_path(s, col)
    assert isinstance(segs[0], JsonPathKey) and segs[0].key == 'a'
    assert isinstance(segs[1], JsonPathKey) and segs[1].key == 'b'
    assert isinstance(segs[2], JsonPathIndex) and segs[2].index == 0
    assert isinstance(segs[3], JsonPathKey) and segs[3].key == 'c'
    assert not col.has_errors


def test_parse_json_path_empty_imports_whole_file() -> None:
    col = DiagnosticCollector()
    s = _stream('.', col)
    assert Parser._parse_json_path(s, col) == []


def test_parse_json_path_invalid_index_reports() -> None:
    col = DiagnosticCollector()
    s = _stream('.a[x]', col)
    segs = Parser._parse_json_path(s, col)
    assert len(segs) == 1
    assert any(d.code == 'parse.invalid_json_path' for d in col)


# ── 约束 ─────────────────────────────────────────────


def test_parse_constraints_single() -> None:
    col = DiagnosticCollector()
    s = _stream('int', col)
    cons = Parser._parse_constraints(s, col)
    assert len(cons.constraints) == 1
    assert isinstance(cons.constraints[0], ConstraintIdent)
    assert cons.constraints[0].name == 'int'


def test_parse_constraints_angle_list() -> None:
    col = DiagnosticCollector()
    s = _stream('<int, str>', col)
    cons = Parser._parse_constraints(s, col)
    names = [c.name for c in cons.constraints if isinstance(c, (ConstraintIdent, ConstraintCall))]
    assert names == ['int', 'str']


def test_parse_constraints_nullable_wraps_one() -> None:
    col = DiagnosticCollector()
    s = _stream('int?', col)
    cons = Parser._parse_constraints(s, col)
    call = cons.constraints[0]
    assert isinstance(call, ConstraintCall)
    assert call.name == 'one'
    assert isinstance(call.arguments[1], ConstraintIdent) and call.arguments[1].name == '?'


def test_parse_constraint_call() -> None:
    col = DiagnosticCollector()
    s = _stream('regex("re")', col)
    name_tok = s.expect(IdentifierToken)
    call = Parser._parse_constraint_call(s, col, name_tok)
    assert call.name == 'regex'
    assert len(call.arguments) == 1


# ── 字段 ──────────────────────────────────────────────


def test_parse_field_with_value() -> None:
    col = DiagnosticCollector()
    s = _stream('a = 1', col)
    f = Parser._parse_field(s, col)
    assert isinstance(f, Field)
    assert f.name == 'a'
    assert isinstance(f.value, LiteralValue)
    assert isinstance(f.value.value, IntegerToken)
    assert not col.has_errors


def test_parse_field_with_type() -> None:
    col = DiagnosticCollector()
    s = _stream('b: int', col)
    f = Parser._parse_field(s, col)
    assert f.name == 'b'
    assert f.constraints is not None
    first = f.constraints.constraints[0]
    assert isinstance(first, (ConstraintIdent, ConstraintCall)) and first.name == 'int'


# ── 值 / 容器 ─────────────────────────────────────────


def test_parse_value_array() -> None:
    col = DiagnosticCollector()
    s = _stream('[1, 2]', col)
    v = Parser._parse_value(s, col)
    assert isinstance(v, ArrayValue)
    assert len(v.elements) == 2


def test_parse_value_object() -> None:
    col = DiagnosticCollector()
    s = _stream('{a = 1}', col)
    v = Parser._parse_value(s, col)
    assert isinstance(v, DictValue)
    assert len(v.fields) == 1


def test_parse_array() -> None:
    col = DiagnosticCollector()
    s = _stream('[1, 2]', col)
    arr = Parser._parse_array(s, col)
    assert isinstance(arr, ArrayValue)
    assert len(arr.elements) == 2


def test_parse_object() -> None:
    col = DiagnosticCollector()
    s = _stream('{a = 1, b = 2}', col)
    obj = Parser._parse_object(s, col)
    assert isinstance(obj, DictValue)
    assert [f.name for f in obj.fields] == ['a', 'b']


# ── 模板 ──────────────────────────────────────────────


def test_parse_template_call() -> None:
    col = DiagnosticCollector()
    s = _stream('X(a=1, 2)', col)
    name_tok = s.expect(IdentifierToken)
    call = Parser._parse_template_call(s, col, name_tok)
    assert isinstance(call, TemplateCallValue)
    assert call.template_name == 'X'
    assert list(call.named_args) == ['a']
    assert len(call.positional_args) == 1


def test_parse_template_field() -> None:
    col = DiagnosticCollector()
    s = _stream('a: int = 1', col)
    tf = Parser._parse_template_field(s, col)
    assert isinstance(tf, TemplateField)
    assert tf.name == 'a'
    assert tf.default_value is not None


def test_apply_template_config() -> None:
    col = DiagnosticCollector()
    config = TemplateConfig()
    key_tok = _stream('allow_extra', col).expect(IdentifierToken)
    value = Parser._wrap_literal(_stream('true', col).peek())
    Parser._apply_template_config(col, config, key_tok, value)
    assert config.allow_extra is True
    assert not col.has_errors


def test_apply_template_config_unknown_key_reports() -> None:
    col = DiagnosticCollector()
    config = TemplateConfig()
    key_tok = _stream('bogus', col).expect(IdentifierToken)
    value = Parser._wrap_literal(_stream('true', col).peek())
    Parser._apply_template_config(col, config, key_tok, value)
    assert any(d.code == 'parse.template_config_unknown' for d in col)


# ── 导入项 ────────────────────────────────────────────


def test_parse_template_import_item() -> None:
    col = DiagnosticCollector()
    s = _stream('Name as Alias', col)
    item = Parser._parse_template_import_item(s, col)
    assert isinstance(item, TemplateImportItem)
    assert item.name == 'Name'
    assert item.alias == 'Alias'


def test_parse_file_import_item() -> None:
    col = DiagnosticCollector()
    s = _stream('.a.b as x', col)
    item = Parser._parse_file_import_item(s, col)
    assert isinstance(item, FileImportItem)
    assert item.alias == 'x'
    assert len(item.json_path) == 2


# ── $ 引用 ────────────────────────────────────────────


def test_parse_dollar_value() -> None:
    col = DiagnosticCollector()
    s = _stream('$x as int', col)
    dv = Parser._parse_dollar_value(s, col)
    assert dv.name == 'x'
    assert dv.type_cast == 'int'


def test_parse_dollar_value_invalid_cast_reports() -> None:
    col = DiagnosticCollector()
    s = _stream('$x as nope', col)
    dv = Parser._parse_dollar_value(s, col)
    assert dv.type_cast is None
    assert any(d.code == 'parse.invalid_cast' for d in col)


# ── 分隔符 ────────────────────────────────────────────


def test_missing_separator_reports() -> None:
    col = DiagnosticCollector()
    s = _stream('1 2', col)
    reported = [False]
    Parser._missing_separator(s, col, False, True, RawTokenType.RBRACKET, reported)
    assert any(d.code == 'parse.missing_separator' for d in col)
    assert reported[0]


def test_missing_separator_silent_when_had_separator() -> None:
    col = DiagnosticCollector()
    s = _stream('1 2', col)
    Parser._missing_separator(s, col, True, True, RawTokenType.RBRACKET, [False])
    assert not col.has_errors


def test_missing_separator_silent_at_closing() -> None:
    col = DiagnosticCollector()
    s = _stream(']', col)
    Parser._missing_separator(s, col, False, True, RawTokenType.RBRACKET, [False])
    # 单独 ] 会触发 tokenizer 的 unexpected_close_bracket，但不应报 parse.missing_separator
    assert not any(d.code == 'parse.missing_separator' for d in col)
