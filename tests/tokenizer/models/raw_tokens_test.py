"""tokenizer/models/raw_tokens.py 单元测试：RawToken 与类型枚举。"""

from infinity_data.infra.location import SourceRange
from infinity_data.tokenizer.models.raw_tokens import RawToken, RawTokenType


def test_raw_token_type_values() -> None:
    assert RawTokenType.EQUALS.value == '='
    assert RawTokenType.IDENTIFIER.value == 'identifier'
    assert RawTokenType.EOF.value == 'eof'


def test_raw_token_fields() -> None:
    tok = RawToken(type=RawTokenType.INTEGER, raw='5', source=SourceRange.empty())
    assert tok.type is RawTokenType.INTEGER
    assert tok.raw == '5'
    assert tok.source == SourceRange.empty()


def test_import_keyword_types() -> None:
    assert RawTokenType.ENV_IMPORT.value == '!env'
    assert RawTokenType.FILE_IMPORT.value == '!file'
    assert RawTokenType.FROM_IMPORT.value == '!from'
