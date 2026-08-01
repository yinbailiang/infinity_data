"""递归下降语法分析器，将 Token 流转换为 RawAst。"""

from __future__ import annotations

from typing import TypeVar

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
    TypeAnnotation,
    Value,
)
from infinity_data.tokenizer.models import (
    ColonToken,
    CommaToken,
    EofToken,
    EqualsToken,
    ExistToken,
    FalseToken,
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
    NullToken,
    QuestionToken,
    RangleToken,
    RbraceToken,
    RbracketToken,
    RparenToken,
    StringToken,
    TildeToken,
    Token,
    TokenType,
    TrueToken,
)

_TToken = TypeVar("_TToken", bound=Token)


class Parser:
    """递归下降解析器。"""

    def __init__(self, tokens: list[Token]) -> None:
        self._tokens = tokens
        self._pos = 0

    def parse(self) -> Document:
        doc = Document()
        while not self._is_done():
            stmt = self._parse_statement()
            if stmt is not None:
                doc.statements.append(stmt)
        return doc

    # ── 顶层 ─────────────────────────────────────────────

    def _parse_statement(self) -> Statement | None:
        """解析一条顶层语句。"""
        self._skip_newlines()

        if self._check(TokenType.EOF):
            return None

        tok = self._peek()

        if isinstance(tok, TildeToken):
            return self._parse_template_def()
        if isinstance(tok, FromToken):
            return self._parse_import()
        if isinstance(tok, IdentifierToken):
            return self._parse_field()

        self._advance()  # skip unexpected
        return None

    # ── 导入 ─────────────────────────────────────────────

    def _parse_import(self) -> ImportStmt:
        self._expect_type(FromToken)  # from
        from_tok = self._expect_type(IdentifierToken)
        self._expect_type(ImportToken)  # import
        names: list[str] = []
        names.append(self._expect_type(IdentifierToken).name)
        while isinstance(self._peek(), CommaToken):
            self._advance()
            names.append(self._expect_type(IdentifierToken).name)
        self._skip_newlines()
        return ImportStmt(
            from_path=from_tok.name,
            names=names,
            source=from_tok.source,
        )

    # ── 模板定义 ─────────────────────────────────────────

    def _parse_template_def(self) -> TemplateDef:
        self._expect_type(TildeToken)  # ~
        name_tok = self._expect_type(IdentifierToken)
        self._expect_type(LbraceToken)  # {
        self._skip_newlines()

        body: list[Statement] = []
        while not self._check(TokenType.RBRACE) and not self._is_done():
            body.append(self._parse_field())
            self._skip_newlines()

        self._expect_type(RbraceToken)  # }
        self._skip_newlines()

        return TemplateDef(
            name=name_tok.name,
            body=body,
            source=name_tok.source,
        )

    # ── 字段 ─────────────────────────────────────────────

    def _parse_field(self) -> Field:
        name_tok = self._expect_type(IdentifierToken)

        # 类型标注 name: <...> 或 name: type 或 name: type?
        type_annotation: TypeAnnotation | None = None
        if isinstance(self._peek(), ColonToken):
            self._advance()
            type_annotation = self._parse_type_annotation()

        # 默认值 name = value
        value: Value | None = None
        if isinstance(self._peek(), EqualsToken):
            self._advance()
            value = self._parse_value()
        elif isinstance(self._peek(), LbraceToken):
            # 省略等号的对象值 name { ... }
            value = self._parse_object()
        elif isinstance(self._peek(), LbracketToken):
            # 省略等号的数组值 name [ ... ]
            value = self._parse_array()
        elif isinstance(self._peek(), IdentifierToken):
            # 可能是模板调用 name Template(args...) 或裸 exist 标记
            # 先按模板调用解析
            next_tok = self._peek()
            if isinstance(next_tok, IdentifierToken):
                # 这里需要判断下一个 token 后有没有 (
                # 实际上裸标识符是 exist 标记
                value = self._parse_value_maybe_template()
            else:
                # 裸标识符 → exist 标记
                pass  # value stays None

        self._skip_newlines()
        return Field(
            name=name_tok.name,
            type_annotation=type_annotation,
            value=value,
            source=name_tok.source,
        )

    def _parse_value_maybe_template(self) -> Value:
        """解析可能是模板调用的值。"""
        name_tok = self._peek()
        if isinstance(name_tok, IdentifierToken):
            # peek ahead
            saved = self._pos
            self._advance()
            if isinstance(self._peek(), LparenToken):
                # Template call: Name(args...)
                return self._parse_template_call(name_tok)
            # 回退：不是模板调用
            self._pos = saved

        return self._parse_value()

    # ── 类型标注 ─────────────────────────────────────────

    def _parse_type_annotation(self) -> TypeAnnotation:
        """解析类型标注，如 int, str?, <int, range(1,10)>"""
        constraints: list[Constraint] = []
        nullable = False

        tok = self._peek()

        if isinstance(tok, LangleToken):
            # <constraint, constraint, ...>
            self._advance()
            while not self._check(TokenType.RANGLE) and not self._is_done():
                constraints.append(self._parse_constraint())
                if isinstance(self._peek(), CommaToken):
                    self._advance()
            self._expect_type(RangleToken)
        elif isinstance(tok, IdentifierToken):
            self._advance()
            name = tok.name
            if isinstance(self._peek(), QuestionToken):
                self._advance()
                nullable = True
            constraints.append(ConstraintIdent(name=name))
        elif isinstance(tok, QuestionToken):
            self._advance()
            constraints.append(ConstraintIdent(name="?"))

        return TypeAnnotation(constraints=constraints, nullable=nullable)

    def _parse_constraint(self) -> Constraint:
        """解析单个约束，可能是标识符或函数调用。"""
        tok = self._peek()

        if isinstance(tok, IdentifierToken):
            name_tok = self._expect_type(IdentifierToken)
            if isinstance(self._peek(), LparenToken):
                return self._parse_constraint_call(name_tok.name)
            return ConstraintIdent(name=name_tok.name)

        if isinstance(tok, QuestionToken):
            self._advance()
            return ConstraintIdent(name="?")

        # 字面量参数
        if isinstance(tok, (StringToken, IntegerToken, FloatToken,
                            TrueToken, FalseToken, NullToken)):
            return self._parse_constraint_literal()

        self._advance()
        return ConstraintIdent(name="?")

    def _parse_constraint_call(self, name: str) -> ConstraintCall:
        """解析约束函数调用，如 each(str)、range(1, 10)。"""
        self._expect_type(LparenToken)
        args: list[Constraint] = []
        while not self._check(TokenType.RPAREN) and not self._is_done():
            args.append(self._parse_constraint())
            if isinstance(self._peek(), CommaToken):
                self._advance()
        self._expect_type(RparenToken)
        return ConstraintCall(name=name, arguments=args)

    def _parse_constraint_literal(self) -> ConstraintLiteral:
        """解析约束中的字面量参数。"""
        tok = self._peek()
        self._advance()

        if isinstance(tok, StringToken):
            return ConstraintLiteral(kind="str", raw=tok.value)
        if isinstance(tok, IntegerToken):
            return ConstraintLiteral(kind="int", raw=str(tok.value))
        if isinstance(tok, FloatToken):
            return ConstraintLiteral(kind="float", raw=str(tok.value))
        if isinstance(tok, TrueToken):
            return ConstraintLiteral(kind="true", raw="true")
        if isinstance(tok, FalseToken):
            return ConstraintLiteral(kind="false", raw="false")
        if isinstance(tok, NullToken):
            return ConstraintLiteral(kind="null", raw="null")

        return ConstraintLiteral(kind="?", raw="?")

    # ── 值 ───────────────────────────────────────────────

    def _parse_value(self) -> Value:
        tok = self._peek()

        if isinstance(tok, StringToken):
            self._advance()
            return LiteralValue(kind="str", raw=tok.value)
        if isinstance(tok, IntegerToken):
            self._advance()
            return LiteralValue(kind="int", raw=str(tok.value))
        if isinstance(tok, FloatToken):
            self._advance()
            return LiteralValue(kind="float", raw=str(tok.value))
        if isinstance(tok, TrueToken):
            self._advance()
            return LiteralValue(kind="true", raw="true")
        if isinstance(tok, FalseToken):
            self._advance()
            return LiteralValue(kind="false", raw="false")
        if isinstance(tok, NullToken):
            self._advance()
            return LiteralValue(kind="null", raw="null")
        if isinstance(tok, ExistToken):
            self._advance()
            return LiteralValue(kind="exist", raw="exist")
        if isinstance(tok, LbraceToken):
            return self._parse_object()
        if isinstance(tok, LbracketToken):
            return self._parse_array()

        self._advance()
        return LiteralValue(kind="error", raw="")

    def _parse_object(self) -> ObjectValue:
        self._expect_type(LbraceToken)
        self._skip_newlines()

        obj = ObjectValue()
        while not self._check(TokenType.RBRACE) and not self._is_done():
            obj.fields.append(self._parse_field())
            self._skip_newlines()

        self._expect_type(RbraceToken)
        return obj

    def _parse_array(self) -> ArrayValue:
        self._expect_type(LbracketToken)
        self._skip_newlines()

        arr = ArrayValue()
        while not self._check(TokenType.RBRACKET) and not self._is_done():
            val = self._parse_value()
            arr.elements.append(val)
            # 跳过逗号、换行
            self._skip_separators()

        self._expect_type(RbracketToken)
        return arr

    def _parse_template_call(self, name_tok: IdentifierToken) -> TemplateCallValue:
        """解析 Name(args...) 形式的模板调用。"""
        self._expect_type(LparenToken)
        self._skip_newlines()

        positional: list[Value] = []
        named: dict[str, Value] = {}

        while not self._check(TokenType.RPAREN) and not self._is_done():
            self._skip_newlines()

            if self._check(TokenType.RPAREN) or self._is_done():
                break

            # 先解析一个值
            if isinstance(self._peek(), IdentifierToken):
                saved = self._pos
                ident = self._expect_type(IdentifierToken)
                if isinstance(self._peek(), EqualsToken):
                    # 命名参数 name=value
                    self._advance()
                    named[ident.name] = self._parse_value()
                else:
                    # 回退：位置参数
                    self._pos = saved
                    positional.append(self._parse_value())
            else:
                positional.append(self._parse_value())

            # 跳过逗号和换行
            self._skip_separators()

        self._expect_type(RparenToken)
        return TemplateCallValue(
            template_name=name_tok.name,
            positional_args=positional,
            named_args=named,
            source=name_tok.source,
        )

    # ── 辅助方法 ─────────────────────────────────────────

    def _peek(self) -> Token:
        if self._pos >= len(self._tokens):
            return EofToken()
        return self._tokens[self._pos]

    def _advance(self) -> Token:
        tok = self._peek()
        self._pos += 1
        return tok

    def _check(self, token_type: TokenType) -> bool:
        if self._pos >= len(self._tokens):
            return token_type is TokenType.EOF
        return self._tokens[self._pos].type is token_type

    def _is_done(self) -> bool:
        return self._pos >= len(self._tokens) or isinstance(
            self._tokens[self._pos], EofToken
        )

    def _skip_newlines(self) -> None:
        while not self._is_done() and isinstance(self._peek(), NewlineToken):
            self._advance()

    def _skip_separators(self) -> None:
        """跳过逗号和换行。"""
        while isinstance(self._peek(), (CommaToken, NewlineToken)):
            self._advance()

    def _expect_type(self, token_cls: type[_TToken]) -> _TToken:
        tok = self._peek()
        if not isinstance(tok, token_cls):
            raise SyntaxError(
                f"期望 {token_cls.__name__}，实际为 {tok.type.name} "
                f"({tok.source.file}:{tok.source.line}:{tok.source.col})"
            )
        self._pos += 1
        return tok