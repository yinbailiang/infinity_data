"""tokenizer/keywords.py 单元测试：Bang 关键字单一事实源。"""

from pathlib import Path

import pytest

from infinity_data.infra.diagnostics import DiagnosticCollector
from infinity_data.infra.file import MemFile
from infinity_data.tokenizer.keywords import (
    BANG_BY_NAME,
    BANG_KEYWORDS,
    CONTEXTUAL_KEYWORDS,
    CONTEXTUAL_NAMES,
    BangKeywordSpec,
)
from infinity_data.tokenizer.models.raw_tokens import RawTokenType
from infinity_data.tokenizer.tokenizer import RawTokenizer


@pytest.mark.parametrize('spec', BANG_KEYWORDS, ids=lambda spec: spec.label)
def test_bang_keyword_tokenizes_as_single_token(spec: BangKeywordSpec) -> None:
    file = MemFile(name='t.infd', root_path=Path('.'), content=f'{spec.label}\n')
    tokens = list(RawTokenizer(file=file, error_collector=DiagnosticCollector()))
    bangs = [tok for tok in tokens if tok.type is RawTokenType.BANG_KEYWORD]
    assert [tok.raw for tok in bangs] == [spec.label]
    assert BANG_BY_NAME[spec.keyword.value] is spec


def test_bang_keyword_names_are_unique() -> None:
    assert len(BANG_BY_NAME) == len(BANG_KEYWORDS)


def test_contextual_keyword_names_are_unique() -> None:
    assert len(CONTEXTUAL_NAMES) == len(CONTEXTUAL_KEYWORDS)
