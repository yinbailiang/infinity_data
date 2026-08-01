"""测试：加载 test.infd 并展示完整流水线。

流水线：
  文件 → Token 流 → RawAst → StandardAst → dict
"""

import asyncio
import json
from collections.abc import AsyncIterable

from infinity_data.analyzer.analyzer import SemanticAnalyzer
from infinity_data.analyzer.converter import reduce_to_dict
from infinity_data.analyzer.models import StdArray, StdDocument, StdLiteral, StdObject, StdValue
from infinity_data.parser.models import (
    ArrayValue,
    Constraint,
    ConstraintCall,
    ConstraintIdent,
    ConstraintLiteral,
    Document,
    Field,
    ImportStmt,
    LiteralValue,
    ObjectValue,
    Statement,
    TemplateCallValue,
    TemplateDef,
    Value,
)
from infinity_data.parser.parser import Parser
from infinity_data.tokenizer.models import (
    TokenizeErrorCollector,
    RawToken,
    Token,
    TokenizeError,
)
from infinity_data.tokenizer.tokenizer import FinalTokenizer, RawTokenizer


async def _chars_from_file(path: str) -> AsyncIterable[str]:
    """按字符异步产出文件内容。"""
    with open(path, encoding="utf-8") as f:
        content = f.read()
    for ch in content:
        yield ch


async def _collect_tokens(
    file_path: str,
) -> tuple[list[Token], list[TokenizeError]]:
    """词法分析：两阶段 tokenize，支持跨阶段快速失败。

    Returns:
        (tokens, errors): tokens 列表和错误列表。
        如果有错误，tokens 可能为空或不完整。
    """
    errors = TokenizeErrorCollector()

    # ── 阶段 1: RawTokenizer（容错：收集尽可能多错误）──
    raw = RawTokenizer(
        _chars_from_file(file_path),
        file_path=file_path,
        error_collector=errors,
    )
    raw_tokens: list[RawToken] = []
    async for rt in raw:
        raw_tokens.append(rt)

    if errors.has_errors:
        # 阶段 1 有错误 → 快速失败，跳过阶段 2
        return [], list(errors.errors)

    # ── 阶段 2: FinalTokenizer（阶段 1 无错误时才执行）──
    tokens: list[Token] = []
    final = FinalTokenizer(_async_iter_from_list(raw_tokens))
    async for tok in final:
        tokens.append(tok)

    return tokens, []


async def _async_iter_from_list(items: list[RawToken]) -> AsyncIterable[RawToken]:
    """将列表包装为异步可迭代对象。"""
    for item in items:
        yield item


def _format_value(val: Value, indent: int = 0) -> str:
    """格式化值。"""
    prefix = "  " * indent

    match val:
        case LiteralValue(kind=k, raw=r):
            return f"{k}({r!r})"
        case ObjectValue(fields=fs):
            lines = ["{"]
            for f in fs:
                lines.append(f"  {prefix}{_format_field(f, indent + 1)}")
            lines.append(f"{prefix}}}")
            return "\n".join(lines)
        case ArrayValue(elements=els):
            items = ", ".join(_format_value(e) for e in els)
            return f"[{items}]"
        case TemplateCallValue(template_name=n, positional_args=pa, named_args=na):
            parts = [_format_value(a) for a in pa]
            parts.extend(f"{k}={_format_value(v)}" for k, v in na.items())
            return f"{n}({', '.join(parts)})"

    return "?"


def _format_constraint(c: Constraint) -> str:
    """格式化单个约束。"""
    match c:
        case ConstraintIdent(name=n):
            return n
        case ConstraintCall(name=n, arguments=args):
            arg_str = ", ".join(_format_constraint(a) for a in args)
            return f"{n}({arg_str})"
        case ConstraintLiteral(kind=k, raw=r):
            return f"{k}({r!r})"
    return "?"


def _format_field(field: Field, indent: int = 0) -> str:
    """格式化字段定义。"""
    parts = [field.name]

    if field.type_annotation:
        ta = field.type_annotation
        if ta.constraints:
            cs = ", ".join(_format_constraint(c) for c in ta.constraints)
            parts.append(f": <{cs}>")
        if ta.nullable:
            if not ta.constraints:
                parts.append(": <null>")
            parts[-1] += "?"

    if field.value:
        parts.append(f"= {_format_value(field.value, indent)}")
    else:
        parts.append("(exist)")

    return " ".join(parts)


def _format_stmt(stmt: Statement, indent: int = 0) -> str:
    """格式化语句。"""
    prefix = "  " * indent

    match stmt:
        case ImportStmt(from_path=p, names=n):
            return f"{prefix}!from {p} import {', '.join(n)}"
        case TemplateDef(name=n, body=b):
            lines = [f"{prefix}~Template {n} {{"]
            for s in b:
                lines.append(_format_stmt(s, indent + 1))
            lines.append(f"{prefix}}}")
            return "\n".join(lines)
        case Field() as f:
            return f"{prefix}{_format_field(f, indent)}"

    return f"{prefix}?"


def _print_ast(doc: Document) -> None:
    """打印 RawAst。"""
    print("\n=== RawAst ===")
    for stmt in doc.statements:
        print(_format_stmt(stmt))


def _format_std_value(val: StdValue, indent: int = 0) -> str:
    """格式化 StdValue。"""
    prefix = "  " * indent
    match val:
        case StdLiteral(kind=k, value=v):
            return f"{k}({v!r})"
        case StdObject(fields=fs):
            lines = ["{"]
            for f in fs:
                val_str = _format_std_value(f.value, indent + 1) if f.value else "(none)"
                lines.append(f"  {prefix}{f.name} = {val_str}")
            lines.append(f"{prefix}}}")
            return "\n".join(lines)
        case StdArray(elements=els):
            items = ", ".join(_format_std_value(e) for e in els)
            return f"[{items}]"
    return "?"


def _print_standard_ast(doc: StdDocument) -> None:
    """打印 StandardAst。"""
    print("\n=== StandardAst ===")
    for field in doc.root.fields:
        val_str = _format_std_value(field.value, 1) if field.value else "(none)"
        print(f"{field.name} = {val_str}")

    if doc.diagnostics:
        print("\n--- 诊断信息 ---")
        for d in doc.diagnostics:
            loc = f"{d.source.file}:{d.source.line}" if d.source else "?:?"
            print(f"  [{d.level.upper()}] {loc} {d.path}: {d.message}")


async def main() -> None:
    file_path = "test.infd"

    # ── 阶段 1-2: 词法分析（跨阶段快速失败）──
    tokens, token_errors = await _collect_tokens(file_path)
    print(f"=== 文件: {file_path} ===\n")

    if token_errors:
        print(f"❌ 词法分析阶段发现 {len(token_errors)} 个错误:\n")
        for err in token_errors:
            loc = f"{err.source.file}:{err.source.line}:{err.source.col}"
            print(f"  [{loc}] {err.message}")
        print("\n由于词法错误，流水线终止。")
        return

    print(f"共 {len(tokens)} 个 token\n")

    # ── 阶段 2: 语法分析 (RawAst) ──
    parser = Parser(tokens)
    raw_doc = parser.parse()
    _print_ast(raw_doc)

    # ── 阶段 3: 语义分析 (StandardAst) ──
    print("\n" + "=" * 60)
    analyzer = SemanticAnalyzer()
    std_doc = analyzer.analyze(raw_doc)
    _print_standard_ast(std_doc)

    # ── 阶段 4: 降维 → dict ──
    print("\n" + "=" * 60)
    print("=== 降维 → dict ===")
    result = reduce_to_dict(std_doc.root)
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    asyncio.run(main())
