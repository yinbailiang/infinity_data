"""测试：加载 test.infd 并展示 token 流与 AST。"""

import asyncio
from collections.abc import AsyncIterable

from infinity_data.tokenizer.models import (
    Token,
)
from infinity_data.tokenizer.tokenizer import FinalTokenizer, RawTokenizer
from infinity_data.parser.parser import Parser
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


async def _chars_from_file(path: str) -> AsyncIterable[str]:
    """按字符异步产出文件内容。"""
    with open(path, encoding="utf-8") as f:
        content = f.read()
    for ch in content:
        yield ch


async def _collect_tokens(file_path: str) -> list[Token]:
    """收集所有 token，返回列表。"""
    tokens: list[Token] = []
    raw = RawTokenizer(_chars_from_file(file_path), file_path=file_path)
    final = FinalTokenizer(raw)
    async for tok in final:
        tokens.append(tok)
    return tokens


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
            lines = [f"{prefix}@Template {n} {{"]
            for s in b:
                lines.append(_format_stmt(s, indent + 1))
            lines.append(f"{prefix}}}")
            return "\n".join(lines)
        case Field() as f:
            return f"{prefix}{_format_field(f, indent)}"

    return f"{prefix}?"


def _print_ast(doc: Document) -> None:
    """打印 AST。"""
    print("\n=== AST ===")
    for stmt in doc.statements:
        print(_format_stmt(stmt))


async def main() -> None:
    file_path = "test.infd"

    tokens = await _collect_tokens(file_path)

    print(f"=== 文件: {file_path} ===\n")
    print(f"共 {len(tokens)} 个 token\n")

    parser = Parser(tokens)
    doc = parser.parse()
    _print_ast(doc)


if __name__ == "__main__":
    asyncio.run(main())
