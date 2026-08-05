"""递归下降语法分析器，将 Token 流转换为 RawAst。
"""

from __future__ import annotations

from typing import TypeVar

from infinity_data.parser.errors import (
    EmptyTokenListError,
    InvalidImportKeywordError,
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
    DictValue,
    Document,
    DollarValue,
    EnvImportStmt,
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
    TypeAnnotation,
    Value,
)
from infinity_data.tokenizer.models.raw_tokens import RawTokenType, SourceInfo, SourceRange
from infinity_data.tokenizer.models.tokens import (
    AsToken,
    BoolToken,
    ColonToken,
    CommaToken,
    DollarToken,
    DotToken,
    EnvToken,
    EofToken,
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
    NewlineToken,
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
        tokens: list[Token],
        error_collector: ParseErrorCollector | None = None,
    ) -> None:
        self._tokens: list[Token] = tokens
        self._pos = 0
        self._errors: ParseErrorCollector = error_collector or ParseErrorCollector()

    @property
    def error_collector(self) -> ParseErrorCollector:
        return self._errors

    # ═══════════════════════════════════════════════════════
    # 公开入口
    # ═══════════════════════════════════════════════════════

    def parse(self) -> Document:
        if not self._tokens:
            dummy = SourceRange(
                start=SourceInfo(file_path="", line=0, col=0, index=0),
                end=SourceInfo(file_path="", line=0, col=0, index=0),
            )
            self._errors.add(EmptyTokenListError(source=dummy))
            return Document(source=dummy)
        doc = Document(source=SourceRange(start=self._tokens[0].raw.source.start, end=self._tokens[-1].raw.source.end))
        while not self._is_done():
            stmt = self._parse_statement()
            if stmt is not None:
                doc.statements.append(stmt)
        return doc

    # ═══════════════════════════════════════════════════════
    # 顶层
    # ═══════════════════════════════════════════════════════

    def _parse_statement(self) -> Statement | None:
        """解析一条顶层语句。"""
        self._skip_newlines()

        if self._check(RawTokenType.EOF):
            return None

        match self._peek():
            case ExclamationToken():
                return self._parse_any_import()
            case TildeToken():
                return self._parse_template_def()
            case IdentifierToken():
                return self._parse_field()
            case _:
                self._advance()  # skip unexpected
                return None

    # ═══════════════════════════════════════════════════════
    # 导入语句
    # ═══════════════════════════════════════════════════════

    def _parse_any_import(self) -> Statement:
        """解析 !env / !file / !from 导入语句。"""
        excl_tok = self._expect_type(ExclamationToken)

        match self._peek():
            case EnvToken():
                return self._parse_env_import(excl_tok)
            case FileToken():
                return self._parse_file_import(excl_tok)
            case FromToken():
                return self._parse_template_import(excl_tok)
            case tok:
                self._advance()
                self._errors.add(InvalidImportKeywordError(
                    source=self._single_span(tok),
                    actual=tok.raw.type.name,
                ))
                self._skip_newlines()
                # 错误恢复：返回一个空字段作为占位
                return Field(
                    source=self._single_span(excl_tok),
                    name="<import-error>",
                )

    def _parse_env_import(self, excl_tok: ExclamationToken) -> EnvImportStmt:
        """!env import NAME [as NEW_NAME]"""
        self._expect_type(EnvToken)
        self._expect_type(ImportToken)
        name_tok = self._expect_type(IdentifierToken)

        alias = None
        if isinstance(self._peek(), AsToken):
            self._advance()
            alias = self._expect_type(IdentifierToken).name

        self._skip_newlines()
        return EnvImportStmt(
            source=self._span_from(excl_tok),
            name=name_tok.name,
            alias=alias,
        )

    def _parse_file_import(self, excl_tok: ExclamationToken) -> FileImportStmt:
        """!file "path" [as <format>] import .path.to.key [as alias], ..."""
        self._expect_type(FileToken)
        path_tok = self._expect_type(StringToken)

        # 可选 as <format>
        fmt = None
        if isinstance(self._peek(), AsToken):
            self._advance()
            fmt = self._expect_type(IdentifierToken).name

        self._expect_type(ImportToken)

        # 导入项列表
        items: list[FileImportItem] = []
        items.append(self._parse_file_import_item())

        while isinstance(self._peek(), CommaToken):
            self._advance()
            items.append(self._parse_file_import_item())

        self._skip_newlines()
        return FileImportStmt(
            source=self._span_from(excl_tok),
            file_path=path_tok.value,
            format=fmt,
            imports=items,
        )

    def _parse_file_import_item(self) -> FileImportItem:
        """解析单个 .path.to.key [as alias]。

        路径语法: "." ( "." identifier | "[" integer "]" | "." string )*
        """
        first = self._peek()
        json_path = self._parse_json_path()

        alias = None
        if isinstance(self._peek(), AsToken):
            self._advance()
            alias = self._expect_type(IdentifierToken).name

        self._skip_newlines()
        return FileImportItem(
            source=self._span_from(first),
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
        tok = self._peek()
        if not isinstance(tok, DotToken):
            return []
        self._advance()

        # 第一个段：必须是标识符（首 key 名）
        tok = self._peek()
        if isinstance(tok, IdentifierToken):
            segments.append(JsonPathKey(source=self._single_span(tok), key=tok.name))
            self._advance()
        else:
            # 只有 . → 导入整个文件
            return []

        # 后续段：".key" 或 "[index]"
        while not self._is_done():
            match self._peek():
                case DotToken():
                    self._advance()
                    match self._peek():
                        case IdentifierToken(name=name) as id_tok:
                            segments.append(JsonPathKey(source=self._single_span(id_tok), key=name))
                            self._advance()
                        case StringToken(value=value) as str_tok:
                            segments.append(JsonPathKey(source=self._single_span(str_tok), key=value))
                            self._advance()
                        case _:
                            break

                case LbracketToken():
                    lbracket = self._advance()
                    match self._peek():
                        case IntegerToken(value=value):
                            self._advance()
                            if isinstance(self._peek(), RbracketToken):
                                self._advance()
                            segments.append(JsonPathIndex(source=self._span_from(lbracket), index=value))
                        case _:
                            break

                case _:
                    break

        return segments

    def _parse_template_import(self, excl_tok: ExclamationToken) -> TemplateImportStmt:
        """!from "path" import Name1, Name2, ..."""
        self._expect_type(FromToken)
        path_tok = self._expect_type(StringToken)
        self._expect_type(ImportToken)

        names: list[str] = []
        names.append(self._expect_type(IdentifierToken).name)
        while isinstance(self._peek(), CommaToken):
            self._advance()
            names.append(self._expect_type(IdentifierToken).name)

        self._skip_newlines()
        return TemplateImportStmt(
            source=self._span_from(excl_tok),
            from_path=path_tok.value,
            names=names,
        )

    # ═══════════════════════════════════════════════════════
    # 模板定义
    # ═══════════════════════════════════════════════════════

    def _parse_template_def(self) -> TemplateDef:
        """~Name { template_fields... }"""
        first = self._peek()
        self._expect_type(TildeToken)
        name_tok = self._expect_type(IdentifierToken)
        self._expect_type(LbraceToken)
        self._skip_newlines()

        fields: list[TemplateField] = []
        while not self._check(RawTokenType.RBRACE) and not self._is_done():
            fields.append(self._parse_template_field())
            self._skip_newlines()

        self._expect_type(RbraceToken)
        self._skip_newlines()

        return TemplateDef(
            source=self._span_from(first),
            name=name_tok.name,
            fields=fields,
        )

    def _parse_template_field(self) -> TemplateField:
        """解析模板内部字段：必须有类型标注，默认值可选。"""
        first = self._peek()
        name_tok = self._expect_type(IdentifierToken)

        # 类型标注（模板字段必须）
        self._expect_type(ColonToken)
        type_annotation = self._parse_type_annotation()

        # 默认值（可选，省略 = 必填）
        default_value: Value | None = None
        if isinstance(self._peek(), EqualsToken):
            self._advance()
            default_value = self._parse_value()
        elif self._starts_value(self._peek()):
            default_value = self._parse_value()

        self._skip_newlines()
        return TemplateField(
            source=self._span_from(first),
            name=name_tok.name,
            type_annotation=type_annotation,
            default_value=default_value,
        )

    # ═══════════════════════════════════════════════════════
    # 字段
    # ═══════════════════════════════════════════════════════

    def _parse_field(self) -> Field:
        """解析普通字段：name[: type] [= value]

        支持省略等号：name { ... }, name [ ... ], name Template(...)
        """
        first = self._peek()
        name_tok = self._expect_type(IdentifierToken)

        # 类型标注 name: <...> 或 name: type 或 name: type?
        type_annotation: TypeAnnotation | None = None
        if isinstance(self._peek(), ColonToken):
            self._advance()
            type_annotation = self._parse_type_annotation()

        # 值：有 = 时直接解析；无 = 时识别复合值、模板调用或 $ 引用
        value: Value | None = None
        tok = self._peek()
        if isinstance(tok, EqualsToken):
            self._advance()
            value = self._parse_value()
        elif self._starts_value(tok):
            value = self._parse_value()

        self._skip_newlines()
        return Field(
            source=self._span_from(first),
            name=name_tok.name,
            type_annotation=type_annotation,
            value=value,
        )

    @staticmethod
    def _starts_value(tok: Token) -> bool:
        """判断 token 是否可以起始一个值。"""
        # FloatToken 覆盖所有浮点值（含 NaN / ±Inf）
        return isinstance(tok, (
            StringToken,
            IntegerToken, FloatToken,
            BoolToken, NullToken, NoexistToken,
            LbraceToken, LbracketToken,
            IdentifierToken, DollarToken,
        ))

    # ═══════════════════════════════════════════════════════
    # 类型标注
    # ═══════════════════════════════════════════════════════

    def _parse_type_annotation(self) -> TypeAnnotation:
        """解析类型标注。

        支持:
        - int, str, bool, float, list, dict, ?, object
        - type? → one(type, ?)
        - <constraint, constraint, ...> → all(constraint, ...)
        - <any(...)>, <one(...)>, <not(...)>, <all(...)>
        """
        first = self._peek()

        match first:
            case LangleToken():
                self._advance()
                constraints: list[Constraint] = []
                while not self._check(RawTokenType.RANGLE) and not self._is_done():
                    constraints.append(self._parse_constraint())
                    if isinstance(self._peek(), CommaToken):
                        self._advance()
                self._expect_type(RangleToken)
                return TypeAnnotation(source=self._span_from(first), constraints=constraints)

            case IdentifierToken(name=name):
                self._advance()
                nullable = False
                if isinstance(self._peek(), QuestionToken):
                    self._advance()
                    nullable = True
                return TypeAnnotation(
                    source=self._span_from(first),
                    constraints=[ConstraintIdent(source=self._single_span(first), name=name)],
                    nullable=nullable,
                )

            case QuestionToken():
                self._advance()
                return TypeAnnotation(
                    source=self._span_from(first),
                    constraints=[ConstraintIdent(source=self._single_span(first), name="?")],
                )

            case _:
                self._advance()
                return TypeAnnotation(source=self._span_from(first))

    def _parse_constraint(self) -> Constraint:
        """解析单个约束：标识符、函数调用或字面量。"""
        tok = self._peek()

        match tok:
            case IdentifierToken() as name_tok:
                self._advance()
                if isinstance(self._peek(), LparenToken):
                    return self._parse_constraint_call(name_tok)
                return ConstraintIdent(source=self._single_span(name_tok), name=name_tok.name)

            case QuestionToken():
                self._advance()
                return ConstraintIdent(source=self._single_span(tok), name="?")

            case StringToken() | IntegerToken() | FloatToken() | BoolToken() | NullToken():
                return self._parse_constraint_literal()

            case _:
                self._advance()
                return ConstraintIdent(source=self._single_span(tok), name="?")

    def _parse_constraint_call(self, name_tok: IdentifierToken) -> ConstraintCall:
        """解析约束函数调用: name(arg, arg, ...)。"""
        self._expect_type(LparenToken)
        args: list[Constraint] = []
        while not self._check(RawTokenType.RPAREN) and not self._is_done():
            args.append(self._parse_constraint())
            if isinstance(self._peek(), CommaToken):
                self._advance()
        self._expect_type(RparenToken)
        return ConstraintCall(
            source=self._span_from(name_tok),
            name=name_tok.name,
            arguments=args,
        )

    def _parse_constraint_literal(self) -> ConstraintLiteral:
        """解析约束中的字面量参数，包装为 ConstraintLiteral。"""
        tok = self._peek()
        self._advance()
        lit = self._wrap_literal(tok)
        return ConstraintLiteral(source=lit.source, value=lit)

    # ═══════════════════════════════════════════════════════
    # 值
    # ═══════════════════════════════════════════════════════

    def _parse_value(self) -> Value:
        """解析任意值。"""
        match self._peek():
            # ── $ 导入空间引用 ──
            case DollarToken():
                return self._parse_dollar_value()

            # ── 字面量（FloatToken 覆盖所有浮点值，含 NaN / ±Inf）──
            case StringToken() | IntegerToken() | FloatToken() | BoolToken() | NullToken() | NoexistToken() as tok:
                self._advance()
                return self._wrap_literal(tok)

            # ── 复合值 ──
            case LbraceToken():
                return self._parse_object()
            case LbracketToken():
                return self._parse_array()

            # ── 标识符 → 模板调用 ──
            case IdentifierToken():
                ident = self._expect_type(IdentifierToken)
                return self._parse_template_call(ident)

            case tok:
                self._advance()
                # 错误回退：返回 null 占位
                return LiteralValue(source=self._single_span(tok), value=NullToken(raw=tok.raw))

    def _wrap_literal(self, tok: Token) -> LiteralValue:
        """将字面量 Token 包装为 LiteralValue。"""
        return LiteralValue(source=self._single_span(tok), value=tok)  # type: ignore[arg-type]

    def _parse_dollar_value(self) -> DollarValue:
        """$name [as type] 导入空间引用。"""
        dollar_tok = self._expect_type(DollarToken)
        name_tok = self._expect_type(IdentifierToken)

        type_cast = None
        if isinstance(self._peek(), AsToken):
            self._advance()
            cast_tok = self._peek()
            if isinstance(cast_tok, IdentifierToken):
                name = cast_tok.name
                if name in ("int", "float", "bool", "str"):
                    type_cast = name
                self._advance()

        return DollarValue(
            source=self._span_from(dollar_tok),
            name=name_tok.name,
            type_cast=type_cast,
        )

    def _parse_object(self) -> DictValue:
        """{ field, ... }"""
        lbrace_tok = self._expect_type(LbraceToken)
        self._skip_newlines()

        fields: list[Field] = []
        while not self._check(RawTokenType.RBRACE) and not self._is_done():
            fields.append(self._parse_field())
            self._skip_newlines()

        self._expect_type(RbraceToken)
        return DictValue(source=self._span_from(lbrace_tok), fields=fields)

    def _parse_array(self) -> ArrayValue:
        """[ value, ... ] 换行等价于逗号。"""
        lbracket_tok = self._expect_type(LbracketToken)
        self._skip_newlines()

        elements: list[Value] = []
        while not self._check(RawTokenType.RBRACKET) and not self._is_done():
            val = self._parse_value()
            elements.append(val)
            self._skip_separators()

        self._expect_type(RbracketToken)
        return ArrayValue(source=self._span_from(lbracket_tok), elements=elements)

    def _parse_template_call(self, name_tok: IdentifierToken) -> TemplateCallValue:
        """Name(pos_args..., named_arg=value, ...)"""
        self._expect_type(LparenToken)
        self._skip_newlines()

        positional: list[Value] = []
        named: dict[str, Value] = {}
        saw_named = False

        while not self._check(RawTokenType.RPAREN) and not self._is_done():
            self._skip_newlines()
            if self._check(RawTokenType.RPAREN) or self._is_done():
                break

            # 命名参数检测: name=value
            if isinstance(self._peek(), IdentifierToken):
                saved = self._pos
                ident = self._expect_type(IdentifierToken)
                if isinstance(self._peek(), EqualsToken):
                    self._advance()
                    named[ident.name] = self._parse_value()
                    saw_named = True
                    self._skip_separators()
                    continue
                # 回退：位置参数
                self._pos = saved

            if saw_named:
                self._errors.add(TemplateArgOrderError(source=self._single_span(name_tok)))
                # 错误恢复：仍消费该值作为位置参数（宽松模式）

            positional.append(self._parse_value())
            self._skip_separators()

        self._expect_type(RparenToken)
        return TemplateCallValue(
            source=self._span_from(name_tok),
            template_name=name_tok.name,
            positional_args=positional,
            named_args=named,
        )

    # ═══════════════════════════════════════════════════════
    # 辅助方法
    # ═══════════════════════════════════════════════════════

    def _span_from(self, first: Token) -> SourceRange:
        """计算从 first 到当前已消费的最后一个 token 的 SourceRange。"""
        last = self._tokens[self._pos - 1] if self._pos > 0 else first
        return SourceRange(start=first.raw.source.start, end=last.raw.source.end)

    @staticmethod
    def _single_span(tok: Token) -> SourceRange:
        """单个 token 的 SourceRange。"""
        return tok.raw.source

    def _peek(self) -> Token:
        return self._tokens[min(self._pos, len(self._tokens) - 1)]

    def _advance(self) -> Token:
        tok = self._peek()
        self._pos += 1
        return tok

    def _check(self, token_type: RawTokenType) -> bool:
        if self._pos >= len(self._tokens):
            return token_type is RawTokenType.EOF
        return self._tokens[self._pos].raw.type is token_type

    def _is_done(self) -> bool:
        return self._pos >= len(self._tokens) or isinstance(self._tokens[self._pos], EofToken)

    def _skip_newlines(self) -> None:
        while not self._is_done() and isinstance(self._peek(), NewlineToken):
            self._advance()

    def _skip_separators(self) -> None:
        """跳过逗号和换行（它们是等价的）。"""
        while isinstance(self._peek(), (CommaToken, NewlineToken)):
            self._advance()

    def _expect_type(self, token_cls: type[_TToken]) -> _TToken:
        tok = self._peek()
        if not isinstance(tok, token_cls):
            self._errors.add(UnexpectedTokenError(
                source=self._single_span(tok),
                expected=token_cls.__name__,
                actual=tok.raw.type.name,
            ))
            # 错误恢复：跳过意外 token，尝试继续
            self._advance()
            if self._is_done():
                # 到达末尾：返回最后消费的 token（类型不匹配但至少不崩溃）
                return tok  # type: ignore[return-value]
            return self._peek()  # type: ignore[return-value]
        self._pos += 1
        return tok
