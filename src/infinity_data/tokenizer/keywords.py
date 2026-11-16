"""词法关键字元数据：Bang 指令与上下文关键字。

本模块是**关键字知识的单一事实源**：tokenizer 的 `!` 组合识别、拼写纠正、
LSP 补全与语义高亮都从这里派生，避免同一关键字在多个映射表中重复维护。

注意：解析逻辑仍留在 parser——这里只描述词法标签与展示信息，不持有 parser
回调，避免词法层反向依赖语法层。
"""

from dataclasses import dataclass
from enum import StrEnum

__all__ = [
    'BANG_BY_NAME',
    'BANG_KEYWORDS',
    'CONTEXTUAL_KEYWORDS',
    'CONTEXTUAL_NAMES',
    'BangKeyword',
    'BangKeywordSpec',
    'ContextualKeywordSpec',
]


class BangKeyword(StrEnum):
    """``!`` 组合关键字（词法层识别为单个 token）。"""

    ENV = 'env'
    FILE = 'file'
    FROM = 'from'
    VAR = 'var'
    ASSERT = 'assert'


@dataclass(frozen=True)
class BangKeywordSpec:
    """Bang 关键字元数据：名称、典型语法形态与补全说明。"""

    keyword: BangKeyword
    usage: str
    summary: str

    @property
    def label(self) -> str:
        """完整词法标签（如 ``!assert``）。"""
        return f'!{self.keyword.value}'


BANG_KEYWORDS: tuple[BangKeywordSpec, ...] = (
    BangKeywordSpec(BangKeyword.ENV, '!env import NAME [as ALIAS]', '环境变量导入'),
    BangKeywordSpec(BangKeyword.FILE, '!file p"path" as fmt import ...', '现有配置导入'),
    BangKeywordSpec(BangKeyword.FROM, '!from p"path" import Name [as Alias]', '模板导入'),
    BangKeywordSpec(BangKeyword.VAR, '!var <值> import [path] as NAME', '本地注入'),
    BangKeywordSpec(BangKeyword.ASSERT, '!assert <值> is <约束>', '编译期断言'),
)

BANG_BY_NAME: dict[str, BangKeywordSpec] = {spec.keyword.value: spec for spec in BANG_KEYWORDS}
"""关键字名（不含 ``!``）→ 元数据。"""


@dataclass(frozen=True)
class ContextualKeywordSpec:
    """上下文关键字：词法层是普通标识符，仅在特定语法位置生效。"""

    name: str
    usage: str
    summary: str


CONTEXTUAL_KEYWORDS: tuple[ContextualKeywordSpec, ...] = (
    ContextualKeywordSpec('import', '!env import NAME', '导入语句关键字'),
    ContextualKeywordSpec('as', 'import NAME as ALIAS', '别名关键字（$name as int）'),
    ContextualKeywordSpec('is', '!assert <值> is <约束>', '断言关键字'),
)

CONTEXTUAL_NAMES: frozenset[str] = frozenset(spec.name for spec in CONTEXTUAL_KEYWORDS)
"""上下文关键字名集合（LSP 语义高亮用）。"""
