"""递归下降语法分析器，将 Token 流转换为 RawAst"""

from collections.abc import Iterable
from typing import Any, TypeVar

from infinity_data.infra.diagnostics import DiagnosticCollector
from infinity_data.infra.ll1_stream import NoNextType
from infinity_data.parser.diagnostics import diag
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
    TemplateConfig,
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
    NewlineToken,
    NoexistToken,
    NullToken,
    QuestionToken,
    RangleToken,
    RbraceToken,
    RbracketToken,
    RparenToken,
    SinglelineStringToken,
    StringToken,
    TildeToken,
    Token,
)

_TToken = TypeVar('_TToken', bound=Token)

# 模板配置项白名单（dataclass 字段即白名单，此处按类型分组）
_CONFIG_BOOL_KEYS = frozenset({'allow_extra', 'positional'})
_CONFIG_STR_KEYS = frozenset({'description'})
_TEMPLATE_CONFIG_VALID = 'allow_extra, positional, description'


def _py_describe(v: Any) -> str:
    """config 值类型的人类可读描述（诊断用）。"""
    if isinstance(v, bool):
        return 'bool'
    if isinstance(v, str):
        return 'string'
    if isinstance(v, int):
        return 'integer'
    if isinstance(v, float):
        return 'float'
    return type(v).__name__


class Parser:
    """递归下降解析器。"""

    def __init__(
        self,
        source: Iterable[Token],
        error_collector: DiagnosticCollector | None = None,
    ) -> None:
        self._errors = error_collector if error_collector is not None else DiagnosticCollector()
        self._stream: TokenStream = TokenStream(source, self._errors)

    @property
    def error_collector(self) -> DiagnosticCollector:
        return self._errors

    # ═══════════════════════════════════════════════════════
    # 公开入口
    # ═══════════════════════════════════════════════════════

    def parse(self) -> Document:
        # 懒初始化：预读第一个 token
        first_tok = self._stream.peek()
        if isinstance(first_tok, NoNextType) or self._stream.eof():
            self._errors.add(diag('parse.empty_token_list', {}, SourceRange.empty()))
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

        # EofToken 或物理耗尽均视为流结束
        if self._stream.eof():
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
                self._errors.add(
                    diag('parse.unrecognized_statement', {'name': bad_tok.raw.type.name}, bad_tok.raw.source)
                )
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
                diag(
                    'parse.unexpected_token',
                    {'expected': f'关键字 {name!r}', 'actual': 'EOF'},
                    self._stream.span_from(None),
                )
            )
            return
        self._errors.add(
            diag(
                'parse.unexpected_token', {'expected': f'关键字 {name!r}', 'actual': tok.raw.type.name}, tok.raw.source
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
        path_tok = self._stream.expect(SinglelineStringToken)

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

        # 第一个段：标识符（非 as）或字符串；`.` 后是 as（别名关键字）→ 整文件导入
        tok = self._stream.peek()
        if isinstance(tok, IdentifierToken) and tok.name != 'as':
            segments.append(JsonPathKey(source=tok.raw.source, key=tok.name))
            self._stream.advance()
        elif isinstance(tok, SinglelineStringToken):
            segments.append(JsonPathKey(source=tok.raw.source, key=tok.value))
            self._stream.advance()
        else:
            # 只有 .（或 . as alias）→ 导入整个文件
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
                        case SinglelineStringToken(value=value) as str_tok:
                            segments.append(JsonPathKey(source=self._stream.single_span(str_tok), key=value))
                            self._stream.advance()
                        case _:
                            self._report_invalid_json_path('：. 后缺少段名')
                            break

                case LbracketToken():
                    lbracket = self._stream.advance()
                    match self._stream.peek():
                        case IntegerToken(value=value):
                            self._stream.advance()
                            if isinstance(self._stream.peek(), RbracketToken):
                                self._stream.advance()
                            else:
                                self._report_invalid_json_path('：[ 下标后缺少 ]')
                            segments.append(JsonPathIndex(source=self._stream.span_from(lbracket), index=value))
                        case _:
                            self._report_invalid_json_path('：[ 后须为整数下标')
                            break

                case _:
                    break

        return segments

    def _report_invalid_json_path(self, detail: str) -> None:
        """JSON path 段无效 → 报 parse.invalid_json_path（指向当前 token）。"""
        tok = self._stream.peek()
        if isinstance(tok, NoNextType):
            return
        self._errors.add(diag('parse.invalid_json_path', {'detail': detail}, tok.raw.source))

    def _parse_template_import(self, kw_tok: FromImportToken) -> TemplateImportStmt:
        """!from "path" import Name1 [as Alias1], Name2, ..."""
        path_tok = self._stream.expect(SinglelineStringToken)
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
        # 语法层解析为类型化 TemplateConfig（未知键 / 类型错 / 非字面量 → 诊断）
        config = TemplateConfig()
        if isinstance(self._stream.peek(), LparenToken):
            self._stream.advance()
            self._stream.skip_newlines()
            missing_sep_reported = [False]
            while not self._stream.check(RawTokenType.RPAREN) and not self._stream.check(RawTokenType.EOF):
                key_tok = self._stream.expect(IdentifierToken)
                self._stream.expect(EqualsToken)
                value = self._parse_value()
                self._apply_template_config(config, key_tok, value)
                had_sep = self._stream.skip_separators()
                self._missing_separator(
                    had_sep,
                    isinstance(self._stream.peek(), IdentifierToken),
                    RawTokenType.RPAREN,
                    missing_sep_reported,
                )
            self._stream.expect(RparenToken)

        self._stream.expect(LbraceToken)
        self._stream.skip_newlines()

        fields: list[TemplateField] = []
        constraints: list[Constraint] = []
        missing_sep_reported = [False]
        while not self._stream.check(RawTokenType.RBRACE) and not self._stream.check(RawTokenType.EOF):
            # 结构级约束: : <...>
            if isinstance(self._stream.peek(), ColonToken):
                self._stream.advance()
                parsed = self._parse_constraints()
                constraints.extend(parsed.constraints)
            else:
                fields.append(self._parse_template_field())
            had_sep = self._stream.skip_separators()
            self._missing_separator(
                had_sep,
                isinstance(self._stream.peek(), (IdentifierToken, ColonToken)),
                RawTokenType.RBRACE,
                missing_sep_reported,
            )

        self._stream.expect(RbraceToken)
        self._stream.skip_newlines()

        return TemplateDef(
            source=self._stream.span_from(first),
            name=name_tok.name,
            fields=fields,
            config=config,
            constraints=constraints,
        )

    def _apply_template_config(
        self,
        config: TemplateConfig,
        key_tok: IdentifierToken,
        value: Value,
    ) -> None:
        """模板头部配置项 → 类型化字段；未知键 / 类型错 / 非字面量 → 语法诊断。

        config 值是纯字面量（布尔 / 字符串 / 整数），不支持 ``$`` 引用等复杂值。
        """
        key = key_tok.name
        if not isinstance(value, LiteralValue):
            self._errors.add(diag('parse.template_config_value', {'key': key}, value.source))
            return
        py = self._literal_config_value(value)
        if key in _CONFIG_BOOL_KEYS:
            if isinstance(py, bool):
                setattr(config, key, py)
            else:
                self._errors.add(
                    diag(
                        'parse.template_config_type',
                        {'key': key, 'expected': 'bool', 'actual': _py_describe(py)},
                        key_tok.raw.source,
                    )
                )
        elif key in _CONFIG_STR_KEYS:
            if isinstance(py, str):
                setattr(config, key, py)
            else:
                self._errors.add(
                    diag(
                        'parse.template_config_type',
                        {'key': key, 'expected': 'str', 'actual': _py_describe(py)},
                        key_tok.raw.source,
                    )
                )
        else:
            self._errors.add(
                diag(
                    'parse.template_config_unknown',
                    {'key': key, 'valid': _TEMPLATE_CONFIG_VALID},
                    key_tok.raw.source,
                )
            )

    @staticmethod
    def _literal_config_value(lit: LiteralValue) -> Any:
        """LiteralValue → Python 值（config 值限定为字面量）。"""
        match lit.value:
            case BoolToken(value=b):
                return b
            case StringToken(value=v):
                return v
            case IntegerToken(value=v):
                return v
            case FloatToken(value=v):
                return v
            case _:
                return None

    def _parse_template_field(self) -> TemplateField:
        """解析模板内部字段：必须有类型标注，默认值可选。"""
        first = self._stream.peek()
        name_tok = self._stream.expect(IdentifierToken)

        # 类型标注（模板字段必须）：缺失或为空 → 报错并跳过该字段
        if isinstance(self._stream.peek(), ColonToken):
            self._stream.advance()
            constraints = self._parse_constraints()
            if not constraints.constraints:
                self._errors.add(
                    diag(
                        'parse.template_field_no_constraint',
                        {'field': name_tok.name},
                        self._stream.single_span(name_tok),
                    )
                )
        else:
            self._errors.add(
                diag(
                    'parse.template_field_no_constraint',
                    {'field': name_tok.name},
                    self._stream.single_span(name_tok),
                )
            )
            self._skip_to_field_boundary()
            return TemplateField(
                source=self._stream.single_span(name_tok),
                name=name_tok.name,
                constraints=Constraints(source=self._stream.single_span(name_tok)),
                default_value=None,
            )

        # 默认值（可选，省略 = 必填）
        default_value: Value | None = None
        if isinstance(self._stream.peek(), EqualsToken):
            self._stream.advance()
            default_value = self._parse_value()
        elif self._starts_value(self._stream.peek()):
            default_value = self._parse_value()

        return TemplateField(
            source=self._stream.span_from(first),
            name=name_tok.name,
            constraints=constraints,
            default_value=default_value,
        )

    def _skip_to_field_boundary(self) -> None:
        """跳过当前模板字段的残余 token，直到分隔符或模板闭合符（错误恢复）。"""
        while not self._stream.eof() and not isinstance(
            self._stream.peek(), (CommaToken, NewlineToken, RbraceToken)
        ):
            self._stream.advance()

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

        # 值：有 = 时直接解析；省略等号仅限复合值（dict/array）与模板调用
        value: Value | None = None
        tok = self._stream.peek()
        if isinstance(tok, EqualsToken):
            self._stream.advance()
            value = self._parse_value()
        elif isinstance(tok, (LbraceToken, LbracketToken, IdentifierToken)):
            value = self._parse_value()
        elif self._starts_value(tok):
            # 字面量 / $ 引用省略等号 → 报错但仍解析（lint 式，尽力恢复）
            self._errors.add(
                diag('parse.field_requires_equals', {'name': name_tok.name}, self._stream.single_span(name_tok))
            )
            value = self._parse_value()

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

    @staticmethod
    def _starts_constraint(tok: Token | NoNextType | None) -> bool:
        """判断 token 是否可以起始一个约束（标识符 / ? / 字面量）。"""
        if isinstance(tok, NoNextType) or tok is None:
            return False
        return isinstance(
            tok,
            (IdentifierToken, QuestionToken, StringToken, IntegerToken, FloatToken, BoolToken, NullToken),
        )

    # ═══════════════════════════════════════════════════════
    # 分隔符检测（元素间必须显式分隔）
    # ═══════════════════════════════════════════════════════

    def _missing_separator(
        self,
        had_separator: bool,
        starts_next: bool,
        closing_type: RawTokenType,
        reported: list[bool],
    ) -> None:
        """元素之间缺少显式分隔符（逗号/换行）→ 报 parse.missing_separator。

        - ``had_separator``：刚消费过逗号/换行（有分隔则无事）
        - ``starts_next``：当前 token 是否起始下一个元素（避免与其他恢复错误叠加）
        - 每容器只报一次（``reported`` 标志），其余缺口静默恢复
        """
        if had_separator or not starts_next or reported[0]:
            return
        if self._stream.check(closing_type) or self._stream.check(RawTokenType.EOF):
            return
        tok = self._stream.peek()
        if not isinstance(tok, NoNextType):
            self._errors.add(diag('parse.missing_separator', {}, tok.raw.source))
        reported[0] = True

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
                self._stream.skip_newlines()
                constraints: list[Constraint] = []
                missing_sep_reported = [False]
                while not self._stream.check(RawTokenType.RANGLE) and not self._stream.check(RawTokenType.EOF):
                    constraints.append(self._parse_constraint())
                    had_sep = self._stream.skip_separators()
                    self._missing_separator(
                        had_sep,
                        self._starts_constraint(self._stream.peek()),
                        RawTokenType.RANGLE,
                        missing_sep_reported,
                    )
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
                        constraints=[self._nullable(ident)],
                    )

                # 单约束函数调用可省略尖括号: field: regex("re") = ...
                if isinstance(self._stream.peek(), LparenToken):
                    call = self._parse_constraint_call(first)
                    # 调用后也可空: regex("re")? → one(regex("re"), ?)
                    if isinstance(self._stream.peek(), QuestionToken):
                        self._stream.advance()
                        call = self._nullable(call)
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
                # 无效约束起始：报错；不消费容器闭合符（避免吞掉 }/>/）破坏外层解析）
                if not isinstance(self._stream.peek(), (RangleToken, RbraceToken, RparenToken)):
                    bad_tok = self._stream.advance()
                    self._errors.add(
                        diag('parse.unrecognized_constraint', {'name': bad_tok.raw.type.name}, bad_tok.raw.source)
                    )
                return Constraints(source=self._stream.span_from(first))

    @staticmethod
    def _nullable(c: Constraint) -> ConstraintCall:
        """可空包装：constraint? → one(constraint, ?)。"""
        return ConstraintCall(
            source=c.source,
            name='one',
            arguments=[c, ConstraintIdent(source=c.source, name='?')],
        )

    def _parse_constraint(self) -> Constraint:
        """解析单个约束：标识符、函数调用或字面量（支持可空后缀 ?）。"""
        tok = self._stream.peek()
        base: Constraint

        match tok:
            case IdentifierToken() as name_tok:
                self._stream.advance()
                if isinstance(self._stream.peek(), LparenToken):
                    base = self._parse_constraint_call(name_tok)
                else:
                    base = ConstraintIdent(source=self._stream.single_span(name_tok), name=name_tok.name)

            case QuestionToken():
                self._stream.advance()
                return ConstraintIdent(source=tok.raw.source, name='?')

            case StringToken() | IntegerToken() | FloatToken() | BoolToken() | NullToken():
                base = self._parse_constraint_literal()

            case _:
                bad_tok = self._stream.advance()
                return ErrorConstraint(
                    source=self._stream.single_span(bad_tok),
                    message=f'无法解析的约束: {bad_tok.raw.type.name}',
                )

        # 可空后缀: constraint? → one(constraint, ?)
        if isinstance(self._stream.peek(), QuestionToken):
            self._stream.advance()
            return self._nullable(base)
        return base

    def _parse_constraint_call(self, name_tok: IdentifierToken) -> ConstraintCall:
        """解析约束函数调用: name(arg, arg, ...)。"""
        self._stream.expect(LparenToken)
        self._stream.skip_newlines()
        args: list[Constraint] = []
        missing_sep_reported = [False]
        while not self._stream.check(RawTokenType.RPAREN) and not self._stream.check(RawTokenType.EOF):
            args.append(self._parse_constraint())
            had_sep = self._stream.skip_separators()
            self._missing_separator(
                had_sep,
                self._starts_constraint(self._stream.peek()),
                RawTokenType.RPAREN,
                missing_sep_reported,
            )
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
                # 标识符后接 = / : → 不是模板调用而是新语句的字段定义：
                # 说明外层数组/对象未闭合。报 parse.value_field 并停止，
                # 避免把后续行误解析为模板调用（消除 template.undefined 级联）。
                nxt = self._stream.peek()
                if isinstance(nxt, (EqualsToken, ColonToken)):
                    self._errors.add(diag('parse.value_field', {'name': ident.name}, self._stream.single_span(ident)))
                    return ErrorValue(source=self._stream.single_span(ident), message=f'值位置出现字段定义: {ident.name}')
                return self._parse_template_call(ident)

            case tok:
                self._stream.advance()
                name = 'EOF' if isinstance(tok, NoNextType) else tok.raw.type.name
                source = SourceRange.empty() if isinstance(tok, NoNextType) else tok.raw.source
                self._errors.add(diag('parse.unrecognized_value', {'name': name}, source))
                return ErrorValue(source=source, message=f'无法解析的值: {name}')

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
                else:
                    self._errors.add(diag('parse.invalid_cast', {'type': name}, cast_tok.raw.source))
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
        missing_sep_reported = [False]
        while not self._stream.check(RawTokenType.RBRACE) and not self._stream.check(RawTokenType.EOF):
            # 结构级约束: : <...>
            if isinstance(self._stream.peek(), ColonToken):
                self._stream.advance()
                parsed = self._parse_constraints()
                constraints.extend(parsed.constraints)
            else:
                fields.append(self._parse_field())
            had_sep = self._stream.skip_separators()
            self._missing_separator(
                had_sep,
                isinstance(self._stream.peek(), (IdentifierToken, ColonToken)),
                RawTokenType.RBRACE,
                missing_sep_reported,
            )

        self._stream.expect(RbraceToken)
        return DictValue(source=self._stream.span_from(lbrace_tok), fields=fields, constraints=constraints)

    def _parse_array(self) -> ArrayValue:
        """[ value, ... ] 逗号或换行分隔，元素间必须显式分隔。"""
        lbracket_tok = self._stream.expect(LbracketToken)
        self._stream.skip_newlines()

        elements: list[Value] = []
        missing_sep_reported = [False]
        while not self._stream.check(RawTokenType.RBRACKET) and not self._stream.check(RawTokenType.EOF):
            val = self._parse_value()
            elements.append(val)
            had_sep = self._stream.skip_separators()
            self._missing_separator(
                had_sep,
                self._starts_value(self._stream.peek()),
                RawTokenType.RBRACKET,
                missing_sep_reported,
            )

        self._stream.expect(RbracketToken)
        return ArrayValue(source=self._stream.span_from(lbracket_tok), elements=elements)

    def _parse_template_call(self, name_tok: IdentifierToken) -> TemplateCallValue:
        """Name(pos_args..., named_arg=value, ...)"""
        self._stream.expect(LparenToken)
        self._stream.skip_newlines()

        positional: list[Value] = []
        named: dict[str, Value] = {}
        saw_named = False
        missing_sep_reported = [False]

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
                else:
                    # 不是 = → 模板调用（位置参数），复用已消费的 ident
                    positional.append(self._parse_template_call(ident))
            else:
                # 分支 2：其他 token → 一定是位置参数
                if saw_named:
                    self._errors.add(diag('parse.template_arg_order', {}, self._stream.single_span(name_tok)))
                positional.append(self._parse_value())

            had_sep = self._stream.skip_separators()
            self._missing_separator(
                had_sep,
                self._starts_value(self._stream.peek()),
                RawTokenType.RPAREN,
                missing_sep_reported,
            )

        self._stream.expect(RparenToken)
        return TemplateCallValue(
            source=self._stream.span_from(name_tok),
            template_name=name_tok.name,
            positional_args=positional,
            named_args=named,
        )
