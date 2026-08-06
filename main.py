"""测试：加载 test.infd 并展示完整流水线。

基于 neo_desg.md 重新设计。
流水线：
  文件 → Token 流 → RawAst → StandardAst → dict
"""

import asyncio
import json
from collections.abc import AsyncIterable

from infinity_data.analyzer.analyzer import SemanticAnalyzer
from infinity_data.analyzer.converter import reduce_to_dict
from infinity_data.analyzer.models import (
    StdArray,
    StdDocument,
    StdLiteral,
    StdObject,
    StdValue,
)
from infinity_data.parser.models import (
    ArrayValue,
    Constraint,
    ConstraintCall,
    ConstraintIdent,
    ConstraintLiteral,
    Document,
    DollarValue,
    EnvImportStmt,
    Field,
    FileImportStmt,
    LiteralValue,
    DictValue,
    Statement,
    TemplateCallValue,
    TemplateDef,
    TemplateField,
    TemplateImportStmt,
    Value,
)
from infinity_data.parser.parser import Parser
from infinity_data.tokenizer.models.raw_tokens import (
    RawToken,
)
from infinity_data.tokenizer.models.tokens import (
    Token,
)
from infinity_data.tokenizer.errors import (
    TokenizeError,
    TokenizeErrorCollector,
)
from infinity_data.tokenizer.tokenizer import RawTokenizer
from infinity_data.tokenizer.finalizer import FinalTokenizer


async def _chars_from_file(path: str) -> AsyncIterable[str]:
    """按字符异步产出文件内容。"""
    with open(path, encoding="utf-8") as f:
        content = f.read()
    for ch in content:
        yield ch


async def _collect_tokens(
    file_path: str,
) -> tuple[list[Token], list[TokenizeError]]:
    """词法分析：两阶段 tokenize，支持跨阶段快速失败。"""
    errors = TokenizeErrorCollector()

    # ── 阶段 1: RawTokenizer ──
    raw = RawTokenizer(
        _chars_from_file(file_path),
        file_path=file_path,
        error_collector=errors,
    )
    raw_tokens: list[RawToken] = []
    async for rt in raw:
        raw_tokens.append(rt)

    if errors.has_errors:
        return [], list(errors.errors)

    # ── 阶段 2: FinalTokenizer ──
    tokens: list[Token] = []
    final = FinalTokenizer(_async_iter_from_list(raw_tokens))
    async for tok in final:
        tokens.append(tok)

    return tokens, []


async def _async_iter_from_list(items: list[RawToken]) -> AsyncIterable[RawToken]:
    """将列表包装为异步可迭代对象。"""
    for item in items:
        yield item


# ═══════════════════════════════════════════════════════════
# 格式化输出
# ═══════════════════════════════════════════════════════════

def _format_value(val: Value, indent: int = 0) -> str:
    """格式化值。"""
    prefix = "  " * indent

    match val:
        case LiteralValue(kind=k, raw=r):
            return f"{k}({r!r})"
        case DollarValue(name=n, type_cast=tc):
            cast = f" as {tc}" if tc else ""
            return f"${n}{cast}"
        case DictValue(fields=fs):
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


def _format_field(field: Field | TemplateField, indent: int = 0) -> str:
    """格式化字段定义。"""
    parts = [field.name]

    if field.constraints:
        ta = field.constraints
        cs = ", ".join(_format_constraint(c) for c in ta.constraints)
        if cs:
            parts.append(f": <{cs}>")
    elif isinstance(field, TemplateField):
        # 模板字段必须有类型标注
        parts.append(": <?>")

    if isinstance(field, TemplateField):
        if field.default_value is not None:
            parts.append(f"= {_format_value(field.default_value, indent)}")
        else:
            parts.append("(必填)")
    elif field.value is not None:
        parts.append(f"= {_format_value(field.value, indent)}")
    else:
        parts.append("(exist)")

    return " ".join(parts)


def _format_stmt(stmt: Statement, indent: int = 0) -> str:
    """格式化语句。"""
    prefix = "  " * indent

    match stmt:
        case TemplateImportStmt(from_path=p, names=n):
            return f'{prefix}!from "{p}" import {", ".join(n)}'
        case EnvImportStmt(name=n, alias=a):
            alias = f" as {a}" if a else ""
            return f"{prefix}!env import {n}{alias}"
        case FileImportStmt(file_path=p, format=f, imports=imps):
            fmt = f" as {f}" if f else ""
            imp_strs = []
            for item in imps:
                s = item.json_path
                if item.alias:
                    s += f" as {item.alias}"
                imp_strs.append(s)
            return f'{prefix}!file "{p}"{fmt} import {", ".join(imp_strs)}'
        case TemplateDef(name=n, fields=fs):
            lines = [f"{prefix}~{n} {{"]
            for tf in fs:
                lines.append(f"  {prefix}{_format_field(tf, indent + 1)}")
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
            if k in ("nan", "+inf", "-inf"):
                return k
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


# ═══════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════

async def main() -> None:
    file_path = "test.infd"

    # ── 阶段 1-2: 词法分析 ──
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

    # 打印 token 列表
    print("--- Token 列表 ---")
    for tok in tokens:
        loc = f"{tok.source.file}:{tok.source.line}:{tok.source.col}"
        extra = ""
        if hasattr(tok, "value"):
            extra = f" = {tok.value!r}"  # type: ignore[union-attr]
        elif hasattr(tok, "name"):
            extra = f" = {tok.name!r}"  # type: ignore[union-attr]
        print(f"  {tok.type.name:20} [{loc}] {extra}")
    print()

    # ── 阶段 3: 语法分析 (RawAst) ──
    print("=" * 60)
    parser = Parser(tokens)
    raw_doc = parser.parse()
    _print_ast(raw_doc)

    # ── 阶段 4: 语义分析 (StandardAst) ──
    print("\n" + "=" * 60)
    analyzer = SemanticAnalyzer()
    std_doc = analyzer.analyze(raw_doc)
    _print_standard_ast(std_doc)

    # ── 阶段 5: 降维 → dict ──
    print("\n" + "=" * 60)
    print("=== 降维 → dict ===")
    result = reduce_to_dict(std_doc.root)
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    asyncio.run(main())

