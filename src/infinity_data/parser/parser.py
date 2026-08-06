"""递归下降语法分析器，将 Token 流转换为 RawAst"""

from collections.abc import AsyncIterable
from typing import TypeVar

from infinity_data.parser.errors import (
    EmptyTokenListError,
    InvalidImportKeywordError,
    ParseErrorCollector,
    TemplateArgOrderError,
)
from infinity_data.parser.models import (
    ArrayValue,
    Constraint,
    ConstraintCall,
    ConstraintIdent,
    ConstraintLiteral,
    Constraints,
    DictValue,
    Document,
    DollarValue,
    EnvImportStmt,
    ErrorConstraint,
    ErrorStatement,
    ErrorValue,
    Field,
    FileImportItem,
    FileImportStmt,
    JsonPathIndex,
    JsonPathKey,
    JsonPathSegment,
    LiteralValue,
    Statement,
    TemplateCallValue,
    TemplateDef,
    TemplateField,
    TemplateImportStmt,
    Value,
)
from infinity_data.parser.token_stream import TokenStream
from infinity_data.tokenizer.models.raw_tokens import RawTokenType, SourceInfo, SourceRange
from infinity_data.tokenizer.models.tokens import (
    AsToken,
    BoolToken,
    ColonToken,
    CommaToken,
    DollarToken,
    DotToken,
    EnvToken,
    EqualsToken,
    ExclamationToken,
    FileToken,
    FloatToken,
    FromToken,
    IdentifierToken,
    ImportToken,
    IntegerToken,
    LangleToken,
    LbraceToken,
    LbracketToken,
    LparenToken,
    NoexistToken,
    NullToken,
    QuestionToken,
    RangleToken,
    RbraceToken,
    RbracketToken,
    RparenToken,
    StringToken,
    TildeToken,
    Token,
)

_TToken = TypeVar("_TToken", bound=Token)

class Parser:
    """递归下降解析器。"""

    def __init__(
        self,
        source: AsyncIterable[Token],
        error_collector: ParseErrorCollector | None = None,
    ) -> None:
        self._errors: ParseErrorCollector = error_collector or ParseErrorCollector()
        self._stream: TokenStream = TokenStream(source, self._errors)

    @property
    def error_collector(self) -> ParseErrorCollector:
        return self._errors

    # ═══════════════════════════════════════════════════════
    # 公开入口
    # ═══════════════════════════════════════════════════════

    async def parse(self) -> Document:
        # 懒初始化：预读第一个 token
        first_tok = await self._stream.current()
        if first_tok is None or self._stream.is_done():
            dummy = SourceRange(
                start=SourceInfo(file_path="", line=0, col=0, index=0),
                end=SourceInfo(file_path="", line=0, col=0, index=0),
            )
            self._errors.add(EmptyTokenListError(source=dummy))
            return Document(source=dummy)
        doc = Document(source=self._stream.single_span(first_tok))
        while not self._stream.is_done():
            stmt = await self._parse_statement()
            if stmt is not None:
                doc.statements.append(stmt)
        return doc

    # ═══════════════════════════════════════════════════════
    # 顶层
    # ═══════════════════════════════════════════════════════

    async def _parse_statement(self) -> Statement | None:
        """解析一条顶层语句。"""
        await self._stream.skip_newlines()

        if self._stream.check(RawTokenType.EOF):
            return None

        match self._stream.peek():
            case ExclamationToken():
                return await self._parse_any_import()
            case TildeToken():
                return await self._parse_template_def()
            case IdentifierToken():
                return await self._parse_field()
            case _:
                bad_tok = await self._stream.advance()  # skip unexpected
                return ErrorStatement(
                    source=self._stream.single_span(bad_tok),
                    message=f"无法识别的顶层 token: {bad_tok.raw.type.name}",
                )

    # ═══════════════════════════════════════════════════════
    # 导入语句
    # ═══════════════════════════════════════════════════════

    async def _parse_any_import(self) -> Statement:
        """解析 !env / !file / !from 导入语句。"""
        excl_tok = await self._stream.expect(ExclamationToken)

        match self._stream.peek():
            case EnvToken():
                return await self._parse_env_import(excl_tok)
            case FileToken():
                return await self._parse_file_import(excl_tok)
            case FromToken():
                return await self._parse_template_import(excl_tok)
            case tok:
                await self._stream.advance()
                self._errors.add(InvalidImportKeywordError(
                    source=self._stream.single_span(tok),
                    actual=tok.raw.type.name,
                ))
                await self._stream.skip_newlines()
                return ErrorStatement(
                    source=self._stream.span_from(excl_tok),
                    message=f"! 后期望 env/file/from，实际为 {tok.raw.type.name}",
                )

    async def _parse_env_import(self, excl_tok: ExclamationToken) -> EnvImportStmt:
        """!env import NAME [as NEW_NAME]"""
        await self._stream.expect(EnvToken)
        await self._stream.expect(ImportToken)
        name_tok = await self._stream.expect(IdentifierToken)

        alias = None
        if isinstance(self._stream.peek(), AsToken):
            await self._stream.advance()
            alias = (await self._stream.expect(IdentifierToken)).name

        await self._stream.skip_newlines()
        return EnvImportStmt(
            source=self._stream.span_from(excl_tok),
            name=name_tok.name,
            alias=alias,
        )

    async def _parse_file_import(self, excl_tok: ExclamationToken) -> FileImportStmt:
        """!file "path" [as <format>] import .path.to.key as alias, ..."""
        await self._stream.expect(FileToken)
        path_tok = await self._stream.expect(StringToken)

        # 可选 as <format>
        fmt = None
        if isinstance(self._stream.peek(), AsToken):
            await self._stream.advance()
            fmt = (await self._stream.expect(IdentifierToken)).name

        await self._stream.expect(ImportToken)

        # 导入项列表
        items: list[FileImportItem] = []
        items.append(await self._parse_file_import_item())

        while isinstance(self._stream.peek(), CommaToken):
            await self._stream.advance()
            items.append(await self._parse_file_import_item())

        await self._stream.skip_newlines()
        return FileImportStmt(
            source=self._stream.span_from(excl_tok),
            file_path=path_tok.value,
            format=fmt,
            imports=items,
        )

    async def _parse_file_import_item(self) -> FileImportItem:
        """解析单个 .path.to.key as alias。

        alias 必须提供——import 的值需要通过 $alias 引用。
        """
        first = self._stream.peek()
        json_path = await self._parse_json_path()

        await self._stream.expect(AsToken)
        alias = (await self._stream.expect(IdentifierToken)).name

        await self._stream.skip_newlines()
        return FileImportItem(
            source=self._stream.span_from(first),
            json_path=json_path,
            alias=alias,
        )

    async def _parse_json_path(self) -> list[JsonPathSegment]:
        """解析 JSON 路径为结构化段列表。

        Token 序列示例:
            .server.host  →  [DOT] [server] [DOT] [host]
            .a.b[0]."c"   →  [DOT] [a] [DOT] [b] [[] [0] []] [DOT] ["c"]
            .              →  [DOT]

        语法: "." identifier ( "." identifier | "[" integer "]" | "." string )*
        返回: 路径段列表；空列表表示导入整个文件（仅 .）
        """
        segments: list[JsonPathSegment] = []

        # 路径必须以 . 起始
        tok = self._stream.peek()
        if not isinstance(tok, DotToken):
            return []
        await self._stream.advance()

        # 第一个段：必须是标识符（首 key 名）
        tok = self._stream.peek()
        if isinstance(tok, IdentifierToken):
            segments.append(JsonPathKey(source=self._stream.single_span(tok), key=tok.name))
            await self._stream.advance()
        else:
            # 只有 . → 导入整个文件
            return []

        # 后续段：".key" 或 "[index]"
        while not self._stream.is_done():
            match self._stream.peek():
                case DotToken():
                    await self._stream.advance()
                    match self._stream.peek():
                        case IdentifierToken(name=name) as id_tok:
                            segments.append(JsonPathKey(source=self._stream.single_span(id_tok), key=name))
                            await self._stream.advance()
                        case StringToken(value=value) as str_tok:
                            segments.append(JsonPathKey(source=self._stream.single_span(str_tok), key=value))
                            await self._stream.advance()
                        case _:
                            break

                case LbracketToken():
                    lbracket = await self._stream.advance()
                    match self._stream.peek():
                        case IntegerToken(value=value):
                            await self._stream.advance()
                            if isinstance(self._stream.peek(), RbracketToken):
                                await self._stream.advance()
                            segments.append(JsonPathIndex(source=self._stream.span_from(lbracket), index=value))
                        case _:
                            break

                case _:
                    break

        return segments

    async def _parse_template_import(self, excl_tok: ExclamationToken) -> TemplateImportStmt:
        """!from "path" import Name1, Name2, ..."""
        await self._stream.expect(FromToken)
        path_tok = await self._stream.expect(StringToken)
        await self._stream.expect(ImportToken)

        names: list[str] = []
        names.append((await self._stream.expect(IdentifierToken)).name)
        while isinstance(self._stream.peek(), CommaToken):
            await self._stream.advance()
            names.append((await self._stream.expect(IdentifierToken)).name)

        await self._stream.skip_newlines()
        return TemplateImportStmt(
            source=self._stream.span_from(excl_tok),
            from_path=path_tok.value,
            names=names,
        )

    # ═══════════════════════════════════════════════════════
    # 模板定义
    # ═══════════════════════════════════════════════════════

    async def _parse_template_def(self) -> TemplateDef:
        """~Name [(config...)] { template_fields... }"""
        first = self._stream.peek()
        await self._stream.expect(TildeToken)
        name_tok = await self._stream.expect(IdentifierToken)

        # 可选模板配置参数: ~Name(allow_extra=true, ...)
        config: dict[str, Value] = {}
        if isinstance(self._stream.peek(), LparenToken):
            await self._stream.advance()
            await self._stream.skip_newlines()
            while not self._stream.check(RawTokenType.RPAREN) and not self._stream.is_done():
                key_tok = await self._stream.expect(IdentifierToken)
                await self._stream.expect(EqualsToken)
                config[key_tok.name] = await self._parse_value()
                await self._stream.skip_separators()
            await self._stream.expect(RparenToken)

        await self._stream.expect(LbraceToken)
        await self._stream.skip_newlines()

        fields: list[TemplateField] = []
        constraints: list[Constraint] = []
        while not self._stream.check(RawTokenType.RBRACE) and not self._stream.is_done():
            # 模板级约束: : <...>
            if isinstance(self._stream.peek(), ColonToken):
                await self._stream.advance()
                parsed = await self._parse_constraints()
                constraints.extend(parsed.constraints)
            else:
                fields.append(await self._parse_template_field())
            await self._stream.skip_newlines()

        await self._stream.expect(RbraceToken)
        await self._stream.skip_newlines()

        return TemplateDef(
            source=self._stream.span_from(first),
            name=name_tok.name,
            fields=fields,
            config=config,
            constraints=constraints,
        )

    async def _parse_template_field(self) -> TemplateField:
        """解析模板内部字段：必须有类型标注，默认值可选。"""
        first = self._stream.peek()
        name_tok = await self._stream.expect(IdentifierToken)

        # 类型标注（模板字段必须）
        await self._stream.expect(ColonToken)
        constraints = await self._parse_constraints()

        # 默认值（可选，省略 = 必填）
        default_value: Value | None = None
        if isinstance(self._stream.peek(), EqualsToken):
            await self._stream.advance()
            default_value = await self._parse_value()
        elif self._starts_value(self._stream.peek()):
            default_value = await self._parse_value()

        await self._stream.skip_newlines()
        return TemplateField(
            source=self._stream.span_from(first),
            name=name_tok.name,
            constraints=constraints,
            default_value=default_value,
        )

    # ═══════════════════════════════════════════════════════
    # 字段
    # ═══════════════════════════════════════════════════════

    async def _parse_field(self) -> Field:
        """解析普通字段：name[: type] [= value]

        支持省略等号：name { ... }, name [ ... ], name Template(...)
        """
        first = self._stream.peek()
        name_tok = await self._stream.expect(IdentifierToken)

        # 类型标注 name: <...> 或 name: type 或 name: type?
        constraints: Constraints | None = None
        if isinstance(self._stream.peek(), ColonToken):
            await self._stream.advance()
            constraints = await self._parse_constraints()

        # 值：有 = 时直接解析；无 = 时识别复合值、模板调用或 $ 引用
        value: Value | None = None
        tok = self._stream.peek()
        if isinstance(tok, EqualsToken):
            await self._stream.advance()
            value = await self._parse_value()
        elif self._starts_value(tok):
            value = await self._parse_value()

        await self._stream.skip_newlines()
        return Field(
            source=self._stream.span_from(first),
            name=name_tok.name,
            constraints=constraints,
            value=value,
        )

    @staticmethod
    def _starts_value(tok: Token) -> bool:
        """判断 token 是否可以起始一个值。"""
        return isinstance(tok, (
            StringToken,
            IntegerToken, FloatToken,
            BoolToken, NullToken, NoexistToken,
            LbraceToken, LbracketToken,
            IdentifierToken, DollarToken,
        ))

    # ═══════════════════════════════════════════════════════
    # 约束列表
    # ═══════════════════════════════════════════════════════

    async def _parse_constraints(self) -> Constraints:
        """解析约束。

        支持:
        - int, str, bool, float, list, dict, ?, object
        - type? → one(type, ?)
        - <constraint, constraint, ...> → all(constraint, ...)
        - <any(...)>, <one(...)>, <not(...)>, <all(...)>
        """
        first = self._stream.peek()

        match first:
            case LangleToken():
                await self._stream.advance()
                constraints: list[Constraint] = []
                while not self._stream.check(RawTokenType.RANGLE) and not self._stream.is_done():
                    constraints.append(await self._parse_constraint())
                    if isinstance(self._stream.peek(), CommaToken):
                        await self._stream.advance()
                await self._stream.expect(RangleToken)
                return Constraints(source=self._stream.span_from(first), constraints=constraints)

            case IdentifierToken(name=name):
                await self._stream.advance()
                ident = ConstraintIdent(source=self._stream.single_span(first), name=name)

                if isinstance(self._stream.peek(), QuestionToken):
                    await self._stream.advance()
                    # 直接展开: type? → one(type, ?)
                    return Constraints(
                        source=self._stream.span_from(first),
                        constraints=[
                            ConstraintCall(
                                source=self._stream.span_from(first),
                                name="one",
                                arguments=[
                                    ident,
                                    ConstraintIdent(source=self._stream.single_span(first), name="?"),
                                ],
                            )
                        ],
                    )

                return Constraints(
                    source=self._stream.span_from(first),
                    constraints=[ident],
                )

            case QuestionToken():
                await self._stream.advance()
                return Constraints(
                    source=self._stream.span_from(first),
                    constraints=[ConstraintIdent(source=self._stream.single_span(first), name="?")],
                )

            case _:
                await self._stream.advance()
                return Constraints(source=self._stream.span_from(first))

    async def _parse_constraint(self) -> Constraint:
        """解析单个约束：标识符、函数调用或字面量。"""
        tok = self._stream.peek()

        match tok:
            case IdentifierToken() as name_tok:
                await self._stream.advance()
                if isinstance(self._stream.peek(), LparenToken):
                    return await self._parse_constraint_call(name_tok)
                return ConstraintIdent(source=self._stream.single_span(name_tok), name=name_tok.name)

            case QuestionToken():
                await self._stream.advance()
                return ConstraintIdent(source=self._stream.single_span(tok), name="?")

            case StringToken() | IntegerToken() | FloatToken() | BoolToken() | NullToken():
                return await self._parse_constraint_literal()

            case _:
                bad_tok = await self._stream.advance()
                return ErrorConstraint(
                    source=self._stream.single_span(bad_tok),
                    message=f"无法解析的约束: {bad_tok.raw.type.name}",
                )

    async def _parse_constraint_call(self, name_tok: IdentifierToken) -> ConstraintCall:
        """解析约束函数调用: name(arg, arg, ...)。"""
        await self._stream.expect(LparenToken)
        args: list[Constraint] = []
        while not self._stream.check(RawTokenType.RPAREN) and not self._stream.is_done():
            args.append(await self._parse_constraint())
            if isinstance(self._stream.peek(), CommaToken):
                await self._stream.advance()
        await self._stream.expect(RparenToken)
        return ConstraintCall(
            source=self._stream.span_from(name_tok),
            name=name_tok.name,
            arguments=args,
        )

    async def _parse_constraint_literal(self) -> ConstraintLiteral:
        """解析约束中的字面量参数，包装为 ConstraintLiteral。"""
        tok = self._stream.peek()
        await self._stream.advance()
        lit = self._wrap_literal(tok)
        return ConstraintLiteral(source=lit.source, value=lit)

    # ═══════════════════════════════════════════════════════
    # 值
    # ═══════════════════════════════════════════════════════

    async def _parse_value(self) -> Value:
        """解析任意值。"""
        match self._stream.peek():
            # ── $ 导入空间引用 ──
            case DollarToken():
                return await self._parse_dollar_value()

            # ── 字面量（FloatToken 覆盖所有浮点值，含 NaN / ±Inf）──
            case StringToken() | IntegerToken() | FloatToken() | BoolToken() | NullToken() | NoexistToken() as tok:
                await self._stream.advance()
                return self._wrap_literal(tok)

            # ── 复合值 ──
            case LbraceToken():
                return await self._parse_object()
            case LbracketToken():
                return await self._parse_array()

            # ── 标识符 → 模板调用 ──
            case IdentifierToken():
                ident = await self._stream.expect(IdentifierToken)
                return await self._parse_template_call(ident)

            case tok:
                await self._stream.advance()
                return ErrorValue(
                    source=self._stream.single_span(tok),
                    message=f"无法解析的值: {tok.raw.type.name}",
                )

    def _wrap_literal(self, tok: Token) -> LiteralValue:
        """将字面量 Token 包装为 LiteralValue。"""
        return LiteralValue(source=self._stream.single_span(tok), value=tok)  # type: ignore[arg-type]

    async def _parse_dollar_value(self) -> DollarValue:
        """$name [as type] 导入空间引用。"""
        dollar_tok = await self._stream.expect(DollarToken)
        name_tok = await self._stream.expect(IdentifierToken)

        type_cast = None
        if isinstance(self._stream.peek(), AsToken):
            await self._stream.advance()
            cast_tok = self._stream.peek()
            if isinstance(cast_tok, IdentifierToken):
                name = cast_tok.name
                if name in ("int", "float", "bool", "str"):
                    type_cast = name
                await self._stream.advance()

        return DollarValue(
            source=self._stream.span_from(dollar_tok),
            name=name_tok.name,
            type_cast=type_cast,
        )

    async def _parse_object(self) -> DictValue:
        """{ field, ... }"""
        lbrace_tok = await self._stream.expect(LbraceToken)
        await self._stream.skip_newlines()

        fields: list[Field] = []
        while not self._stream.check(RawTokenType.RBRACE) and not self._stream.is_done():
            fields.append(await self._parse_field())
            await self._stream.skip_newlines()

        await self._stream.expect(RbraceToken)
        return DictValue(source=self._stream.span_from(lbrace_tok), fields=fields)

    async def _parse_array(self) -> ArrayValue:
        """[ value, ... ] 换行等价于逗号。"""
        lbracket_tok = await self._stream.expect(LbracketToken)
        await self._stream.skip_newlines()

        elements: list[Value] = []
        while not self._stream.check(RawTokenType.RBRACKET) and not self._stream.is_done():
            val = await self._parse_value()
            elements.append(val)
            await self._stream.skip_separators()

        await self._stream.expect(RbracketToken)
        return ArrayValue(source=self._stream.span_from(lbracket_tok), elements=elements)

    async def _parse_template_call(self, name_tok: IdentifierToken) -> TemplateCallValue:
        """Name(pos_args..., named_arg=value, ...)"""
        await self._stream.expect(LparenToken)
        await self._stream.skip_newlines()

        positional: list[Value] = []
        named: dict[str, Value] = {}
        saw_named = False

        while not self._stream.check(RawTokenType.RPAREN) and not self._stream.is_done():
            await self._stream.skip_newlines()
            if self._stream.check(RawTokenType.RPAREN) or self._stream.is_done():
                break

            tok = self._stream.peek()

            # 分支 1：标识符 → 可能是命名参数或模板调用（位置参数）
            if isinstance(tok, IdentifierToken):
                ident: IdentifierToken = await self._stream.expect(IdentifierToken)  # 消费到缓冲区
                nxt = self._stream.peek()       # 下一个 token

                if isinstance(nxt, EqualsToken):
                    await self._stream.advance()  # 消费 =
                    named[ident.name] = await self._parse_value()
                    saw_named = True
                    await self._stream.skip_separators()
                    continue

                # 不是 = → 模板调用（位置参数），复用已消费的 ident
                positional.append(await self._parse_template_call(ident))
                await self._stream.skip_separators()
                continue

            # 分支 2：其他 token → 一定是位置参数
            if saw_named:
                self._errors.add(TemplateArgOrderError(source=self._stream.single_span(name_tok)))

            positional.append(await self._parse_value())
            await self._stream.skip_separators()

        await self._stream.expect(RparenToken)
        return TemplateCallValue(
            source=self._stream.span_from(name_tok),
            template_name=name_tok.name,
            positional_args=positional,
            named_args=named,
        )
