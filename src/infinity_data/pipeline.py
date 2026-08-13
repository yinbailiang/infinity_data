"""编译流水线：源码字符串 → StdDocument / Python dict。

全链路流式：chars → RawTokenizer → FinalTokenizer → Parser → SemanticAnalyzer → Converter。

公共 API 为同步接口；内部 async 阶段通过 :func:`asyncio.run` 编排。
（词法/语法阶段的 async 是流式设计产物，性能敏感场景的同步化重构见后续里程碑。）
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from infinity_data.parser.errors import ParseErrorCollector
from infinity_data.parser.models import Document
from infinity_data.parser.parser import Parser
from infinity_data.semantic.analyzer import SemanticAnalyzer
from infinity_data.semantic.converter import reduce_object
from infinity_data.semantic.imports import ImportResolver
from infinity_data.semantic.models import Diagnostic, Severity, StdDocument, StdObject
from infinity_data.semantic.registry import ConstraintRegistry
from infinity_data.tokenizer.errors import TokenizeErrorCollector
from infinity_data.tokenizer.finalizer import FinalTokenizer
from infinity_data.tokenizer.tokenizer import RawTokenizer


@dataclass
class CompilationResult:
    """一次编译的完整产物。"""

    document: StdDocument | None
    root: StdObject
    value: dict[str, Any]  # 降维后的纯 Python dict（尽力而为，即使有错误）
    diagnostics: list[Diagnostic] = field(default_factory=lambda: [])

    @property
    def has_errors(self) -> bool:
        return any(d.severity is Severity.ERROR for d in self.diagnostics)

    @property
    def warnings(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity is Severity.WARNING]


async def _char_source(text: str) -> AsyncIterator[str]:
    """逐字符产出（CharStream 按单字符消费）。"""
    for ch in text:
        yield ch


async def _tokenize_and_parse(source: str, file_path: str) -> tuple[Document, list[Diagnostic]]:
    """异步阶段：词法 + 语法分析。"""
    tokenize_collector = TokenizeErrorCollector()
    parse_collector = ParseErrorCollector()

    raw_tokens = RawTokenizer(
        _char_source(source),
        file_path=file_path,
        error_collector=tokenize_collector,
    )
    tokens = FinalTokenizer(raw_tokens)
    parser = Parser(tokens, error_collector=parse_collector)
    doc = await parser.parse()

    diagnostics: list[Diagnostic] = []
    for err in tokenize_collector:
        diagnostics.append(Diagnostic.from_error(err))
    for err in parse_collector:
        diagnostics.append(Diagnostic.from_error(err))
    return doc, diagnostics


def compile_source(
    source: str,
    *,
    file_path: str = 'unknown',
    env: Mapping[str, str] | None = None,
    registry: ConstraintRegistry | None = None,
) -> CompilationResult:
    """编译源码字符串，返回 CompilationResult。

    Args:
        source: infd 源码文本
        file_path: 源码路径（诊断定位与相对导入基准）
        env: 环境变量映射（None = 继承进程环境）
        registry: 自定义约束注册表（None = 内置）
    """
    # 空源码 → 空配置
    if not source.strip():
        return CompilationResult(
            document=None,
            root=StdObject(),
            value={},
            diagnostics=[],
        )

    doc, front_diagnostics = asyncio.run(_tokenize_and_parse(source, file_path))

    resolver = ImportResolver(env=env, base_dir=Path(file_path).parent)
    analyzer = SemanticAnalyzer(registry=registry, import_resolver=resolver)
    document = analyzer.analyze(doc)

    diagnostics = sorted(
        [*front_diagnostics, *document.diagnostics],
        key=lambda d: d.sort_key(),
    )
    return CompilationResult(
        document=document,
        root=document.root,
        value=reduce_object(document.root),
        diagnostics=diagnostics,
    )


def load(
    path: str | Path,
    *,
    env: Mapping[str, str] | None = None,
    registry: ConstraintRegistry | None = None,
) -> CompilationResult:
    """加载 .infd/.inft 文件并编译。

    Args:
        path: 文件路径（相对导入以此为基准）
        env: 环境变量映射（None = 继承进程环境）
        registry: 自定义约束注册表（None = 内置）
    """
    p = Path(path)
    text = p.read_text(encoding='utf-8')
    result = compile_source(text, file_path=str(p), env=env, registry=registry)

    # 规范要求 utf-8 NO BOM
    if text.startswith('\ufeff'):
        result.diagnostics.append(
            Diagnostic(
                severity=Severity.WARNING,
                message='文件包含 BOM，规范要求 UTF-8 NO BOM 编码',
            )
        )
        result.diagnostics.sort(key=lambda d: d.sort_key())
    return result
