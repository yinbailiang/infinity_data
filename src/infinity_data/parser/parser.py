"""递归下降语法分析器，将 Token 流转换为 RawAst"""

from collections.abc import Iterable
from typing import TypeVar

from infinity_data.infra.ll1_stream import NoNextType
from infinity_data.parser.errors import (
    EmptyTokenListError,
    ParseErrorCollector,
    TemplateArgOrderError,
    UnexpectedTokenError,
)
from infinity_data.parser.models import (
    ArrayValue,
    Constraint,
    ConstraintCall,
    ConstraintIdent,
    ConstraintLiteral,
    Constraints,
    ConstraintStmt,
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
    TemplateImportItem,
    TemplateImportStmt,
    Value,
)
from infinity_data.parser.token_stream import TokenStream
from infinity_data.tokenizer.models.raw_tokens import RawTokenType, SourceRange
from infinity_data.tokenizer.models.tokens import (
    BoolToken,
    ColonToken,
    CommaToken,
    DollarToken,
    DotToken,
    EnvImportToken,
    EqualsToken,
    FileImportToken,
    FloatToken,
    FromImportToken,
    IdentifierToken,
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

_TToken = TypeVar('_TToken', bound=Token)


class Parser:
    """递归下降解析器。"""

    def __init__(
        self,
        source: Iterable[Token],
        error_collector: ParseErrorCollector | None = None,
    ) -> None:
        self._errors = error_collector if error_collector is not None else ParseErrorCollector()
        self._stream: TokenStream = TokenStream(source, self._errors)

    @property
    def error_collector(self) -> ParseErrorCollector:
        return self._errors

    # ═══════════════════════════════════════════════════════
    # 公开入口
    # ═══════════════════════════════════════════════════════

    def parse(self) -> Document:
        # 懒初始化：预读第一个 token
        first_tok = self._stream.peek()
        if isinstance(first_tok, NoNextType) or self._stream.eof():
            self._errors.add(EmptyTokenListError(source=SourceRange.empty()))
            return Document(source=SourceRange.empty())
        doc = Document(source=first_tok.raw.source)
        while True:
            stmt = self._parse_statement()
            if stmt is None:
                break
            doc.statements.append(stmt)
        return doc

    # ═══════════════════════════════════════════════════════
    # 顶层
    # ═══════════════════════════════════════════════════════

    def _parse_statement(self) -> Statement | None:
        """解析一条顶层语句。"""
        self._stream.skip_newlines()

        # 流真正耗尽（无 EOF token）或到达 EOF token 均视为结束
        if self._stream.eof():
            return None
        if self._stream.check(RawTokenType.EOF):
            return None

        match self._stream.peek():
            case EnvImportToken() | FileImportToken() | FromImportToken():
                return self._parse_import_statement()
            case TildeToken():
                return self._parse_template_def()
            case IdentifierToken():
                return self._parse_field()
            case ColonToken():
                return self._parse_constraint_stmt()
            case _:
                bad_tok = self._stream.advance()
                return ErrorStatement(
                    source=bad_tok.raw.source,
                    message=f'无法识别的顶层 token: {bad_tok.raw.type.name}',
                )

    # ═══════════════════════════════════════════════════════
    # 导入语句
    # ═══════════════════════════════════════════════════════

    def _parse_import_statement(self) -> Statement:
        """分发 !env / !file / !from 导入语句"""
        match self._stream.peek():
            case EnvImportToken() as tok:
                self._stream.advance()
                return self._parse_env_import(tok)
            case FileImportToken() as tok:
                self._stream.advance()
                return self._parse_file_import(tok)
            case FromImportToken() as tok:
                self._stream.advance()
                return self._parse_template_import(tok)
            case _:
                first = self._stream.peek()
                return ErrorStatement(source=self._stream.span_from(first), message='无法识别的导入语句')

    def _peek_keyword(self, name: str) -> bool:
        """当前 token 是否为名为 ``name`` 的标识符（import/as 已降级为标识符）。"""
        tok = self._stream.peek()
        return isinstance(tok, IdentifierToken) and tok.name == name

    def _expect_keyword(self, name: str) -> None:
        """期望语法位置上的关键字名（import/as），含错误恢复。"""
        if self._peek_keyword(name):
            self._stream.advance()
            return
        tok = self._stream.peek()
        if isinstance(tok, NoNextType):
            self._errors.add(
                UnexpectedTokenError(
                    source=self._stream.span_from(None),
                    expected=f'关键字 {name!r}',
                    actual='EOF',
                )
            )
            return
        self._errors.add(
            UnexpectedTokenError(
                source=tok.raw.source,
                expected=f'关键字 {name!r}',
                actual=tok.raw.type.name,
            )
        )
        self._stream.advance()

    def _parse_env_import(self, kw_tok: EnvImportToken) -> EnvImportStmt:
        """!env import NAME [as NEW_NAME]"""
        self._expect_keyword('import')
        name_tok = self._stream.expect(IdentifierToken)

        alias = None
        if self._peek_keyword('as'):
            self._stream.advance()
            alias = self._stream.expect(IdentifierToken).name

        self._stream.skip_newlines()
        return EnvImportStmt(
            source=self._stream.span_from(kw_tok),
            name=name_tok.name,
            alias=alias,
        )

    def _parse_file_import(self, kw_tok: FileImportToken) -> FileImportStmt:
        """!file "path" [as <format>] import .path.to.key as alias, ..."""
        path_tok = self._stream.expect(StringToken)

        # 可选 as <format>
        fmt = None
        if self._peek_keyword('as'):
            self._stream.advance()
            fmt = self._stream.expect(IdentifierToken).name

        self._expect_keyword('import')

        # 导入项列表
        items: list[FileImportItem] = []
        items.append(self._parse_file_import_item())

        while isinstance(self._stream.peek(), CommaToken):
            self._stream.advance()
            items.append(self._parse_file_import_item())

        self._stream.skip_newlines()
        return FileImportStmt(
            source=self._stream.span_from(kw_tok),
            file_path=path_tok.value,
            format=fmt,
            imports=items,
        )

    def _parse_file_import_item(self) -> FileImportItem:
        """解析单个 .path.to.key as alias。

        alias 必须提供——import 的值需要通过 $alias 引用。
        """
        first = self._stream.peek()
        json_path = self._parse_json_path()

        self._expect_keyword('as')
        alias = self._stream.expect(IdentifierToken).name

        self._stream.skip_newlines()
        return FileImportItem(
            source=self._stream.span_from(first),
            json_path=json_path,
            alias=alias,
        )

    def _parse_json_path(self) -> list[JsonPathSegment]:
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
        self._stream.advance()

        # 第一个段：必须是标识符（首 key 名）
        tok = self._stream.peek()
        if isinstance(tok, IdentifierToken):
            segments.append(JsonPathKey(source=tok.raw.source, key=tok.name))
            self._stream.advance()
        else:
            # 只有 . → 导入整个文件
            return []

        # 后续段：".key" 或 "[index]"
        while not self._stream.eof():
            match self._stream.peek():
                case DotToken():
                    self._stream.advance()
                    match self._stream.peek():
                        case IdentifierToken(name=name) as id_tok:
                            segments.append(JsonPathKey(source=self._stream.single_span(id_tok), key=name))
                            self._stream.advance()
                        case StringToken(value=value) as str_tok:
                            segments.append(JsonPathKey(source=self._stream.single_span(str_tok), key=value))
                            self._stream.advance()
                        case _:
                            break

                case LbracketToken():
                    lbracket = self._stream.advance()
                    match self._stream.peek():
                        case IntegerToken(value=value):
                            self._stream.advance()
                            if isinstance(self._stream.peek(), RbracketToken):
                                self._stream.advance()
                            segments.append(JsonPathIndex(source=self._stream.span_from(lbracket), index=value))
                        case _:
                            break

                case _:
                    break

        return segments

    def _parse_template_import(self, kw_tok: FromImportToken) -> TemplateImportStmt:
        """!from "path" import Name1 [as Alias1], Name2, ..."""
        path_tok = self._stream.expect(StringToken)
        self._expect_keyword('import')

        items: list[TemplateImportItem] = []
        items.append(self._parse_template_import_item())
        while isinstance(self._stream.peek(), CommaToken):
            self._stream.advance()
            items.append(self._parse_template_import_item())

        self._stream.skip_newlines()
        return TemplateImportStmt(
            source=self._stream.span_from(kw_tok),
            from_path=path_tok.value,
            items=items,
        )

    def _parse_template_import_item(self) -> TemplateImportItem:
        """解析单个导入项: Name [as Alias]。"""
        first = self._stream.peek()
        name_tok = self._stream.expect(IdentifierToken)

        alias = None
        if self._peek_keyword('as'):
            self._stream.advance()
            alias = self._stream.expect(IdentifierToken).name

        return TemplateImportItem(
            source=self._stream.span_from(first),
            name=name_tok.name,
            alias=alias,
        )

    # ═══════════════════════════════════════════════════════
    # 结构级约束语句（顶层）
    # ═══════════════════════════════════════════════════════

    def _parse_constraint_stmt(self) -> ConstraintStmt:
        """顶层结构级约束: ``: <constraint, ...>`` 或 ``: constraint``。

        顶层是隐式 dict，``:`` 起始的语句约束编译产物 root 的整体。
        """
        first = self._stream.peek()
        self._stream.advance()  # 消费 ':'
        parsed = self._parse_constraints()
        self._stream.skip_separators()
        return ConstraintStmt(
            source=self._stream.span_from(first),
            constraints=parsed.constraints,
        )

    # ═══════════════════════════════════════════════════════
    # 模板定义
    # ═══════════════════════════════════════════════════════

    def _parse_template_def(self) -> TemplateDef:
        """~Name [(config...)] { template_fields... }"""
        first = self._stream.peek()
        self._stream.expect(TildeToken)
        name_tok = self._stream.expect(IdentifierToken)

        # 可选模板配置参数: ~Name(allow_extra=true, ...)
        config: dict[str, Value] = {}
        if isinstance(self._stream.peek(), LparenToken):
            self._stream.advance()
            self._stream.skip_newlines()
            while not self._stream.check(RawTokenType.RPAREN) and not self._stream.eof():
                key_tok = self._stream.expect(IdentifierToken)
                self._stream.expect(EqualsToken)
                config[key_tok.name] = self._parse_value()
                self._stream.skip_separators()
            self._stream.expect(RparenToken)

        self._stream.expect(LbraceToken)
        self._stream.skip_newlines()

        fields: list[TemplateField] = []
        constraints: list[Constraint] = []
        while not self._stream.check(RawTokenType.RBRACE) and not self._stream.eof():
            # 结构级约束: : <...>
            if isinstance(self._stream.peek(), ColonToken):
                self._stream.advance()
                parsed = self._parse_constraints()
                constraints.extend(parsed.constraints)
            else:
                fields.append(self._parse_template_field())
            self._stream.skip_separators()

        self._stream.expect(RbraceToken)
        self._stream.skip_newlines()

        return TemplateDef(
            source=self._stream.span_from(first),
            name=name_tok.name,
            fields=fields,
            config=config,
            constraints=constraints,
        )

    def _parse_template_field(self) -> TemplateField:
        """解析模板内部字段：必须有类型标注，默认值可选。"""
        first = self._stream.peek()
        name_tok = self._stream.expect(IdentifierToken)

        # 类型标注（模板字段必须）
        self._stream.expect(ColonToken)
        constraints = self._parse_constraints()

        # 默认值（可选，省略 = 必填）
        default_value: Value | None = None
        if isinstance(self._stream.peek(), EqualsToken):
            self._stream.advance()
            default_value = self._parse_value()
        elif self._starts_value(self._stream.peek()):
            default_value = self._parse_value()

        self._stream.skip_newlines()
        return TemplateField(
            source=self._stream.span_from(first),
            name=name_tok.name,
            constraints=constraints,
            default_value=default_value,
        )

    # ═══════════════════════════════════════════════════════
    # 字段
    # ═══════════════════════════════════════════════════════

    def _parse_field(self) -> Field:
        """解析普通字段：name[: type] [= value]

        支持省略等号：name { ... }, name [ ... ], name Template(...)
        """
        first = self._stream.peek()
        name_tok = self._stream.expect(IdentifierToken)

        # 类型标注 name: <...> 或 name: type 或 name: type?
        constraints: Constraints | None = None
        if isinstance(self._stream.peek(), ColonToken):
            self._stream.advance()
            constraints = self._parse_constraints()

        # 值：有 = 时直接解析；无 = 时识别复合值、模板调用或 $ 引用
        value: Value | None = None
        tok = self._stream.peek()
        if isinstance(tok, EqualsToken):
            self._stream.advance()
            value = self._parse_value()
        elif self._starts_value(tok):
            value = self._parse_value()

        self._stream.skip_separators()
        return Field(
            source=self._stream.span_from(first),
            name=name_tok.name,
            constraints=constraints,
            value=value,
        )

    @staticmethod
    def _starts_value(tok: Token | NoNextType | None) -> bool:
        """判断 token 是否可以起始一个值。"""
        if isinstance(tok, NoNextType) or tok is None:
            return False
        return isinstance(
            tok,
            (
                StringToken,
                IntegerToken,
                FloatToken,
                BoolToken,
                NullToken,
                NoexistToken,
                LbraceToken,
                LbracketToken,
                IdentifierToken,
                DollarToken,
            ),
        )

    # ═══════════════════════════════════════════════════════
    # 约束列表
    # ═══════════════════════════════════════════════════════

    def _parse_constraints(self) -> Constraints:
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
                self._stream.advance()
                constraints: list[Constraint] = []
                while not self._stream.check(RawTokenType.RANGLE) and not self._stream.eof():
                    constraints.append(self._parse_constraint())
                    if isinstance(self._stream.peek(), CommaToken):
                        self._stream.advance()
                self._stream.expect(RangleToken)
                return Constraints(source=self._stream.span_from(first), constraints=constraints)

            case IdentifierToken(name=name):
                self._stream.advance()
                ident = ConstraintIdent(source=self._stream.single_span(first), name=name)

                if isinstance(self._stream.peek(), QuestionToken):
                    self._stream.advance()
                    # 直接展开: type? → one(type, ?)
                    return Constraints(
                        source=self._stream.span_from(first),
                        constraints=[
                            ConstraintCall(
                                source=self._stream.span_from(first),
                                name='one',
                                arguments=[
                                    ident,
                                    ConstraintIdent(source=self._stream.single_span(first), name='?'),
                                ],
                            )
                        ],
                    )

                # 单约束函数调用可省略尖括号: field: regex("re") = ...
                if isinstance(self._stream.peek(), LparenToken):
                    call = self._parse_constraint_call(first)
                    return Constraints(
                        source=self._stream.span_from(first),
                        constraints=[call],
                    )

                return Constraints(
                    source=self._stream.span_from(first),
                    constraints=[ident],
                )

            case QuestionToken():
                self._stream.advance()
                return Constraints(
                    source=self._stream.span_from(first),
                    constraints=[ConstraintIdent(source=self._stream.single_span(first), name='?')],
                )

            case _:
                self._stream.advance()
                return Constraints(source=self._stream.span_from(first))

    def _parse_constraint(self) -> Constraint:
        """解析单个约束：标识符、函数调用或字面量。"""
        tok = self._stream.peek()

        match tok:
            case IdentifierToken() as name_tok:
                self._stream.advance()
                if isinstance(self._stream.peek(), LparenToken):
                    return self._parse_constraint_call(name_tok)
                return ConstraintIdent(source=self._stream.single_span(name_tok), name=name_tok.name)

            case QuestionToken():
                self._stream.advance()
                return ConstraintIdent(source=tok.raw.source, name='?')

            case StringToken() | IntegerToken() | FloatToken() | BoolToken() | NullToken():
                return self._parse_constraint_literal()

            case _:
                bad_tok = self._stream.advance()
                return ErrorConstraint(
                    source=self._stream.single_span(bad_tok),
                    message=f'无法解析的约束: {bad_tok.raw.type.name}',
                )

    def _parse_constraint_call(self, name_tok: IdentifierToken) -> ConstraintCall:
        """解析约束函数调用: name(arg, arg, ...)。"""
        self._stream.expect(LparenToken)
        args: list[Constraint] = []
        while not self._stream.check(RawTokenType.RPAREN) and not self._stream.eof():
            args.append(self._parse_constraint())
            if isinstance(self._stream.peek(), CommaToken):
                self._stream.advance()
        self._stream.expect(RparenToken)
        return ConstraintCall(
            source=self._stream.span_from(name_tok),
            name=name_tok.name,
            arguments=args,
        )

    def _parse_constraint_literal(self) -> ConstraintLiteral:
        """解析约束中的字面量参数，包装为 ConstraintLiteral。"""
        tok = self._stream.peek()
        self._stream.advance()
        lit = self._wrap_literal(tok)
        return ConstraintLiteral(source=lit.source, value=lit)

    # ═══════════════════════════════════════════════════════
    # 值
    # ═══════════════════════════════════════════════════════

    def _parse_value(self) -> Value:
        """解析任意值。"""
        match self._stream.peek():
            # ── $ 导入空间引用 ──
            case DollarToken():
                return self._parse_dollar_value()

            # ── 字面量（FloatToken 覆盖所有浮点值，含 NaN / ±Inf）──
            case StringToken() | IntegerToken() | FloatToken() | BoolToken() | NullToken() | NoexistToken() as tok:
                self._stream.advance()
                return self._wrap_literal(tok)

            # ── 复合值 ──
            case LbraceToken():
                return self._parse_object()
            case LbracketToken():
                return self._parse_array()

            # ── 标识符 → 模板调用 ──
            case IdentifierToken():
                ident = self._stream.expect(IdentifierToken)
                return self._parse_template_call(ident)

            case tok:
                self._stream.advance()
                if isinstance(tok, NoNextType):
                    return ErrorValue(
                        source=SourceRange.empty(),
                        message='无法解析的值: EOF',
                    )
                return ErrorValue(
                    source=tok.raw.source,
                    message=f'无法解析的值: {tok.raw.type.name}',
                )

    def _wrap_literal(self, tok: Token | NoNextType | None) -> LiteralValue:
        """将字面量 Token 包装为 LiteralValue。"""
        assert not isinstance(tok, NoNextType) and tok is not None
        return LiteralValue(source=tok.raw.source, value=tok)  # type: ignore[arg-type]

    def _parse_dollar_value(self) -> DollarValue:
        """$name [as type] 导入空间引用。"""
        dollar_tok = self._stream.expect(DollarToken)
        name_tok = self._stream.expect(IdentifierToken)

        type_cast = None
        if self._peek_keyword('as'):
            self._stream.advance()
            cast_tok = self._stream.peek()
            if isinstance(cast_tok, IdentifierToken):
                name = cast_tok.name
                if name in ('int', 'float', 'bool', 'str'):
                    type_cast = name
                self._stream.advance()

        return DollarValue(
            source=self._stream.span_from(dollar_tok),
            name=name_tok.name,
            type_cast=type_cast,
        )

    def _parse_object(self) -> DictValue:
        """{ field, ... }

        dict 结构级约束: ``: <constraint, ...>`` 作用于该字面量 dict 的整体。
        """
        lbrace_tok = self._stream.expect(LbraceToken)
        self._stream.skip_separators()

        fields: list[Field] = []
        constraints: list[Constraint] = []
        while not self._stream.check(RawTokenType.RBRACE) and not self._stream.eof():
            # 结构级约束: : <...>
            if isinstance(self._stream.peek(), ColonToken):
                self._stream.advance()
                parsed = self._parse_constraints()
                constraints.extend(parsed.constraints)
            else:
                fields.append(self._parse_field())
            self._stream.skip_separators()

        self._stream.expect(RbraceToken)
        return DictValue(source=self._stream.span_from(lbrace_tok), fields=fields, constraints=constraints)

    def _parse_array(self) -> ArrayValue:
        """[ value, ... ] 换行等价于逗号。"""
        lbracket_tok = self._stream.expect(LbracketToken)
        self._stream.skip_newlines()

        elements: list[Value] = []
        while not self._stream.check(RawTokenType.RBRACKET) and not self._stream.eof():
            val = self._parse_value()
            elements.append(val)
            self._stream.skip_separators()

        self._stream.expect(RbracketToken)
        return ArrayValue(source=self._stream.span_from(lbracket_tok), elements=elements)

    def _parse_template_call(self, name_tok: IdentifierToken) -> TemplateCallValue:
        """Name(pos_args..., named_arg=value, ...)"""
        self._stream.expect(LparenToken)
        self._stream.skip_newlines()

        positional: list[Value] = []
        named: dict[str, Value] = {}
        saw_named = False

        while not self._stream.check(RawTokenType.RPAREN) and not self._stream.eof():
            self._stream.skip_newlines()
            if self._stream.check(RawTokenType.RPAREN) or self._stream.eof():
                break

            tok = self._stream.peek()

            # 分支 1：标识符 → 可能是命名参数或模板调用（位置参数）
            if isinstance(tok, IdentifierToken):
                ident: IdentifierToken = self._stream.expect(IdentifierToken)  # 消费到缓冲区
                nxt = self._stream.peek()  # 下一个 token

                if isinstance(nxt, EqualsToken):
                    self._stream.advance()  # 消费 =
                    named[ident.name] = self._parse_value()
                    saw_named = True
                    self._stream.skip_separators()
                    continue

                # 不是 = → 模板调用（位置参数），复用已消费的 ident
                positional.append(self._parse_template_call(ident))
                self._stream.skip_separators()
                continue

            # 分支 2：其他 token → 一定是位置参数
            if saw_named:
                self._errors.add(TemplateArgOrderError(source=self._stream.single_span(name_tok)))

            positional.append(self._parse_value())
            self._stream.skip_separators()

        self._stream.expect(RparenToken)
        return TemplateCallValue(
            source=self._stream.span_from(name_tok),
            template_name=name_tok.name,
            positional_args=positional,
            named_args=named,
        )
