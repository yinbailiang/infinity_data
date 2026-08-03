"""递归下降语法分析器，将 Token 流转换为 RawAst。

基于 neo_desg.md 重新设计，支持：
- !env import NAME [as ALIAS]
- !file "path" as <format> import .path [as alias], ...
- !from "path" import Name, ...
- $name [as type] 导入空间引用
- 模板必填字段 vs 可选字段
- 多行字符串、特殊浮点字面量
"""

from __future__ import annotations

from typing import TypeVar

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
    FileImportItem,
    FileImportStmt,
    LiteralValue,
    ObjectValue,
    Statement,
    TemplateCallValue,
    TemplateDef,
    TemplateField,
    TemplateImportStmt,
    TypeAnnotation,
    Value,
)
from infinity_data.tokenizer.models import (
    AsToken,
    ColonToken,
    CommaToken,
    DollarToken,
    EnvToken,
    EofToken,
    EqualsToken,
    ExclamationToken,
    FalseToken,
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
    MultilineStringToken,
    NanToken,
    NegInfToken,
    NewlineToken,
    NoexistToken,
    NullToken,
    PosInfToken,
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

    # ═══════════════════════════════════════════════════════
    # 顶层
    # ═══════════════════════════════════════════════════════

    def _parse_statement(self) -> Statement | None:
        """解析一条顶层语句。"""
        self._skip_newlines()

        if self._check(TokenType.EOF):
            return None

        tok = self._peek()

        # ── 导入语句 ──
        if isinstance(tok, ExclamationToken):
            return self._parse_any_import()

        # ── 模板定义 ──
        if isinstance(tok, TildeToken):
            return self._parse_template_def()

        # ── 字段定义 ──
        if isinstance(tok, IdentifierToken):
            return self._parse_field()

        self._advance()  # skip unexpected
        return None

    # ═══════════════════════════════════════════════════════
    # 导入语句
    # ═══════════════════════════════════════════════════════

    def _parse_any_import(self) -> Statement:
        """解析 !env / !file / !from 导入语句。"""
        self._expect_type(ExclamationToken)  # !

        tok = self._peek()

        if isinstance(tok, EnvToken):
            return self._parse_env_import()
        if isinstance(tok, FileToken):
            return self._parse_file_import()
        if isinstance(tok, FromToken):
            return self._parse_template_import()

        # 错误回退
        self._advance()
        raise SyntaxError(f"! 后期望 env/file/from")

    def _parse_env_import(self) -> EnvImportStmt:
        """!env import NAME [as NEW_NAME]"""
        env_tok = self._expect_type(EnvToken)
        self._expect_type(ImportToken)
        name_tok = self._expect_type(IdentifierToken)

        alias = None
        if isinstance(self._peek(), AsToken):
            self._advance()
            alias = self._expect_type(IdentifierToken).name

        self._skip_newlines()
        return EnvImportStmt(name=name_tok.name, alias=alias, source=env_tok.source)

    def _parse_file_import(self) -> FileImportStmt:
        """!file "path" [as <format>] import .path.to.key [as alias], ..."""
        file_tok = self._expect_type(FileToken)
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
            file_path=path_tok.value,
            format=fmt,
            imports=items,
            source=file_tok.source,
        )

    def _parse_file_import_item(self) -> FileImportItem:
        """解析单个 .path.to.key [as alias]。

        路径语法: "." ( "." identifier | "[" integer "]" | "." string )*
        """
        source: SourceInfo | None = None
        tok = self._peek()
        if isinstance(tok, Token):
            source = tok.source

        json_path = self._parse_json_path()

        alias = None
        if isinstance(self._peek(), AsToken):
            self._advance()
            alias_tok = self._expect_type(IdentifierToken)
            alias = alias_tok.name
            source = alias_tok.source

        return FileImportItem(json_path=json_path, alias=alias, source=source)

    def _parse_json_path(self) -> str:
        """解析 JSON 路径。

        Token 序列示例（. 是 IDENTIFIER(".")）:
            .server.host  →  [.] [server] [.] [host]
            .a.b[0]."c"   →  [.] [a] [.] [b] [[] [0] []] [.] ["c"]
            .              →  [.]

        语法: "." identifier ( "." identifier | "[" integer "]" | "." string )*
        """
        parts: list[str] = []

        # 路径必须以 . 起始
        tok = self._peek()
        if not (isinstance(tok, IdentifierToken) and tok.name == "."):
            return "."
        parts.append(".")
        self._advance()

        # 第一个段：必须是标识符（首 key 名）
        tok = self._peek()
        if isinstance(tok, IdentifierToken) and tok.name != ".":
            parts.append(tok.name)
            self._advance()
        else:
            # 只有 . → 导入整个文件
            return "."

        # 后续段：".key" 或 "[index]"
        while not self._is_done():
            tok = self._peek()

            if isinstance(tok, IdentifierToken) and tok.name == ".":
                # .identifier 或 ."string"
                self._advance()
                next_tok = self._peek()
                if isinstance(next_tok, IdentifierToken) and next_tok.name != ".":
                    parts.append(".")
                    parts.append(next_tok.name)
                    self._advance()
                elif isinstance(next_tok, StringToken):
                    parts.append(".")
                    parts.append(f'"{next_tok.value}"')
                    self._advance()
                else:
                    break

            elif isinstance(tok, LbracketToken):
                # [integer]
                self._advance()
                idx_tok = self._peek()
                if isinstance(idx_tok, IntegerToken):
                    parts.append(f"[{idx_tok.value}]")
                    self._advance()
                    if isinstance(self._peek(), RbracketToken):
                        self._advance()
                else:
                    break

            else:
                # 非路径 token（as / , / newline）→ 结束
                break

        return "".join(parts)

    def _parse_template_import(self) -> TemplateImportStmt:
        """!from "path" import Name1, Name2, ..."""
        from_tok = self._expect_type(FromToken)

        # 路径必须是字符串（引号包裹）
        path_tok = self._expect_type(StringToken)

        self._expect_type(ImportToken)

        names: list[str] = []
        names.append(self._expect_type(IdentifierToken).name)
        while isinstance(self._peek(), CommaToken):
            self._advance()
            names.append(self._expect_type(IdentifierToken).name)

        self._skip_newlines()
        return TemplateImportStmt(
            from_path=path_tok.value,
            names=names,
            source=from_tok.source,
        )

    # ═══════════════════════════════════════════════════════
    # 模板定义
    # ═══════════════════════════════════════════════════════

    def _parse_template_def(self) -> TemplateDef:
        """~Name { template_fields... }"""
        self._expect_type(TildeToken)  # ~
        name_tok = self._expect_type(IdentifierToken)
        self._expect_type(LbraceToken)
        self._skip_newlines()

        fields: list[TemplateField] = []
        while not self._check(TokenType.RBRACE) and not self._is_done():
            fields.append(self._parse_template_field())
            self._skip_newlines()

        self._expect_type(RbraceToken)
        self._skip_newlines()

        return TemplateDef(name=name_tok.name, fields=fields, source=name_tok.source)

    def _parse_template_field(self) -> TemplateField:
        """解析模板内部字段：必须有类型标注，默认值可选。"""
        name_tok = self._expect_type(IdentifierToken)

        # 类型标注（模板字段必须）
        self._expect_type(ColonToken)
        type_annotation = self._parse_type_annotation()

        # 默认值（可选，省略 = 必填）
        default_value: Value | None = None
        if isinstance(self._peek(), EqualsToken):
            self._advance()
            default_value = self._parse_value()
        elif isinstance(self._peek(), LbraceToken):
            default_value = self._parse_object()
        elif isinstance(self._peek(), LbracketToken):
            default_value = self._parse_array()

        self._skip_newlines()
        return TemplateField(
            name=name_tok.name,
            source=name_tok.source,
            type_annotation=type_annotation,
            default_value=default_value,
        )

    # ═══════════════════════════════════════════════════════
    # 字段
    # ═══════════════════════════════════════════════════════

    def _parse_field(self) -> Field:
        """解析普通字段：name[: type] [= value]

        支持省略等号的情况：name { ... }, name [ ... ], name Template(...)
        也支持 $name 直接作为值。
        """
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
        elif isinstance(tok, IdentifierToken):
            # 标识符在值位置 → 必定是省略等号的模板调用（无回溯）
            # 因为不存在"标识符字面量"这个概念，所以 id id 不可能是下一个字段
            ident = self._expect_type(IdentifierToken)
            value = self._parse_template_call(ident)
        elif self._starts_value(tok):
            value = self._parse_value()

        self._skip_newlines()
        return Field(
            name=name_tok.name,
            type_annotation=type_annotation,
            value=value,
            source=name_tok.source,
        )

    @staticmethod
    def _starts_value(tok: Token) -> bool:
        """判断 token 是否可以起始一个值。"""
        return isinstance(tok, (
            StringToken, MultilineStringToken,
            IntegerToken, FloatToken,
            TrueToken, FalseToken, NullToken, NoexistToken,
            NanToken, PosInfToken, NegInfToken,
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
            # 检查 ? 后缀
            if isinstance(self._peek(), QuestionToken):
                self._advance()
                nullable = True
            constraints.append(ConstraintIdent(name=name))
        elif isinstance(tok, QuestionToken):
            self._advance()
            constraints.append(ConstraintIdent(name="?"))

        return TypeAnnotation(constraints=constraints, nullable=nullable)

    def _parse_constraint(self) -> Constraint:
        """解析单个约束：标识符、函数调用或字面量。"""
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
        """解析约束函数调用: name(arg, arg, ...)。"""
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

    # ═══════════════════════════════════════════════════════
    # 值
    # ═══════════════════════════════════════════════════════

    def _parse_value(self) -> Value:
        """解析任意值。"""
        tok = self._peek()

        # ── $ 导入空间引用 ──
        if isinstance(tok, DollarToken):
            return self._parse_dollar_value()

        # ── 字面量 ──
        if isinstance(tok, StringToken):
            self._advance()
            return LiteralValue(kind="str", raw=tok.value)
        if isinstance(tok, MultilineStringToken):
            self._advance()
            return LiteralValue(kind="mlstr", raw=tok.value)
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
        if isinstance(tok, NoexistToken):
            self._advance()
            return LiteralValue(kind="noexist", raw="noexist")
        if isinstance(tok, NanToken):
            self._advance()
            return LiteralValue(kind="nan", raw="nan")
        if isinstance(tok, PosInfToken):
            self._advance()
            return LiteralValue(kind="+inf", raw="+inf")
        if isinstance(tok, NegInfToken):
            self._advance()
            return LiteralValue(kind="-inf", raw="-inf")

        # ── 复合值 ──
        if isinstance(tok, LbraceToken):
            return self._parse_object()
        if isinstance(tok, LbracketToken):
            return self._parse_array()

        # ── 标识符 → 模板调用 ──
        # 严格 LL(1): 不存在"标识符字面量"值类型，id 在值位置必定是模板调用
        if isinstance(tok, IdentifierToken):
            ident = self._expect_type(IdentifierToken)
            return self._parse_template_call(ident)

        self._advance()
        return LiteralValue(kind="error", raw="")

    def _parse_dollar_value(self) -> DollarValue:
        """$name [as type] 导入空间引用。"""
        dollar_tok = self._expect_type(DollarToken)
        name_tok = self._expect_type(IdentifierToken)

        type_cast = None
        if isinstance(self._peek(), AsToken):
            self._advance()
            cast_tok = self._peek()
            if isinstance(cast_tok, IdentifierToken):
                type_cast = cast_tok.name
                self._advance()

        return DollarValue(
            name=name_tok.name,
            source=dollar_tok.source,
            type_cast=type_cast,
        )

    def _parse_object(self) -> ObjectValue:
        """{ field, ... }"""
        self._expect_type(LbraceToken)
        self._skip_newlines()

        obj = ObjectValue()
        while not self._check(TokenType.RBRACE) and not self._is_done():
            obj.fields.append(self._parse_field())
            self._skip_newlines()

        self._expect_type(RbraceToken)
        return obj

    def _parse_array(self) -> ArrayValue:
        """[ value, ... ] 换行等价于逗号。"""
        self._expect_type(LbracketToken)
        self._skip_newlines()

        arr = ArrayValue()
        while not self._check(TokenType.RBRACKET) and not self._is_done():
            val = self._parse_value()
            arr.elements.append(val)
            self._skip_separators()

        self._expect_type(RbracketToken)
        return arr

    def _parse_template_call(self, name_tok: IdentifierToken) -> TemplateCallValue:
        """Name(pos_args..., named_arg=value, ...)"""
        self._expect_type(LparenToken)
        self._skip_newlines()

        positional: list[Value] = []
        named: dict[str, Value] = {}
        saw_named = False

        while not self._check(TokenType.RPAREN) and not self._is_done():
            self._skip_newlines()
            if self._check(TokenType.RPAREN) or self._is_done():
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
                # 位置参数不能出现在命名参数之后
                raise SyntaxError(f"位置参数不能出现在命名参数之后 ({name_tok.source.file}:{name_tok.source.line})")

            positional.append(self._parse_value())
            self._skip_separators()

        self._expect_type(RparenToken)
        return TemplateCallValue(
            template_name=name_tok.name,
            positional_args=positional,
            named_args=named,
            source=name_tok.source,
        )

    # ═══════════════════════════════════════════════════════
    # 辅助方法
    # ═══════════════════════════════════════════════════════

    def _peek(self) -> Token:
        if self._pos >= len(self._tokens):
            return EofToken(
                source=self._tokens[-1].source if self._tokens
                else SourceInfo(file="", line=0, col=0, start=0, end=0),
                type=TokenType.EOF,
            )
        return self._tokens[self._pos]

    def _advance(self) -> Token:
        tok = self._peek()
        self._pos += 1
        return tok

    def _check(self, token_type: TokenType) -> bool:
        if self._pos >= len(self._tokens):
            return token_type is TokenType.EOF
        return self._tokens[self._pos].type is token_type  # type: ignore[union-attr]

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
            raise SyntaxError(
                f"期望 {token_cls.__name__}，实际为 {tok.type.name} "
                f"({tok.source.file}:{tok.source.line}:{tok.source.col})"
            )
        self._pos += 1
        return tok
