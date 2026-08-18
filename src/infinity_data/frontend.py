"""前端流水线：源码 File → RawAst Document + 前端诊断（容错收集）。

供 :mod:`pipeline`（主文件）与 :mod:`semantic.builder`（外部模板文件）共用，
消除两处重复的 RawTokenizer → FinalTokenizer → Parser 组装。
"""

from __future__ import annotations

from infinity_data.infra.diagnostics import Diagnostic, DiagnosticCollector
from infinity_data.infra.file import File
from infinity_data.parser.models import Document
from infinity_data.parser.parser import Parser
from infinity_data.tokenizer.finalizer import FinalTokenizer
from infinity_data.tokenizer.tokenizer import RawTokenizer

__all__ = ['parse_source']


def parse_source(file: File) -> tuple[Document, list[Diagnostic]]:
    """词法 + 语法分析，返回 RawAst Document 与前端诊断。

    容错：词法/语法错误经 DiagnosticCollector 收集而非抛出，调用方决定如何处置
    （主文件 → 汇入最终诊断；外部模板 → 并入当前分析器诊断）。
    """
    tokenize_collector = DiagnosticCollector()
    parse_collector = DiagnosticCollector()

    raw_tokens = RawTokenizer(file=file, error_collector=tokenize_collector)
    tokens = FinalTokenizer(raw_tokens)
    parser = Parser(tokens, error_collector=parse_collector)
    doc = parser.parse()

    # 词法/语法错误统一为 Diagnostic（纯数据，直接聚合）
    return doc, [*tokenize_collector, *parse_collector]
