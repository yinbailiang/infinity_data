"""前端流水线：源码 File → RawAst Document + 前端诊断（容错收集）。

供 :mod:`pipeline`（主文件）与 :mod:`semantic.resolver`（外部模板文件）共用，
消除两处重复的 RawTokenizer → FinalTokenizer → Parser 组装。
"""

from infinity_data.infra.diagnostics import DiagnosticCollector
from infinity_data.infra.file import File
from infinity_data.parser import Document
from infinity_data.parser.parser import Parser
from infinity_data.tokenizer.finalizer import FinalTokenizer
from infinity_data.tokenizer.tokenizer import RawTokenizer

__all__ = ['parse_source']


def parse_source(
    file: File,
    collector: DiagnosticCollector | None = None,
) -> tuple[Document, DiagnosticCollector]:
    """词法 + 语法分析，返回 RawAst Document 与生效收集器。

    容错：词法/语法错误经 :class:`DiagnosticCollector` 收集而非抛出。
    传入 ``collector`` 时三阶段（RawTokenizer / FinalTokenizer / Parser）全程
    复用同一收集器并**原样返回**（非副本）；缺省时内部新建并返回。
    返回值第二元素为生效收集器，可直接查询 errors / warnings / has_errors。
    """
    if collector is None:
        collector = DiagnosticCollector()

    raw_tokens = RawTokenizer(file=file, error_collector=collector)
    tokens = FinalTokenizer(raw_tokens, error_collector=collector)
    parser = Parser(tokens, collector=collector)
    doc = parser.parse()

    # 词法/语法错误统一为 Diagnostic（纯数据，直接聚合）
    return doc, collector
