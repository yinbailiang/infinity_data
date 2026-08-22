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
    UnpackValue,
    Value,
    VarStmt,
)
from infinity_data.parser.token_stream import TokenStream
from infinity_data.tokenizer.models.raw_tokens import RawTokenType, SourceRange
from infinity_data.tokenizer.models.tokens import (
    BoolToken,
    ColonToken,
    CommaToken,
    DollarToken,
    DotToken,
    DoubleStarToken,
    EllipsisToken,
    EnvImportToken,
    EofToken,
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
    StarToken,
    StringToken,
    TildeToken,
    Token,
    VarImportToken,
)

_TToken = TypeVar('_TToken', bound=Token)

# 模板配置项白名单（dataclass 字段即白名单，此处按类型分组）
_CONFIG_BOOL_KEYS = frozenset({'allow_extra', 'positional'})
_CONFIG_STR_KEYS = frozenset({'description', 'extra_positional_vars', 'extra_named_vars'})
_TEMPLATE_CONFIG_VALID = 'allow_extra, positional, description, extra_positional_vars, extra_named_vars'

# 嵌套深度上限：递归下降在超深容器/约束上以诊断 + 错误节点恢复，而非 RecursionError 崩溃
_MAX_NESTING = 100


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
        collector: DiagnosticCollector | None = None,
    ) -> None:
        """构造解析器：source token 流 + 诊断收集器（默认新建）。"""
        self._collector = collector if collector is not None else DiagnosticCollector()
        self._stream: TokenStream = TokenStream(source, self._collector)

    @property
    def diagnostic_collector(self) -> DiagnosticCollector:
        """共享诊断收集器（容错收集用）。"""
        return self._collector

    # ═══════════════════════════════════════════════════════
    # 公开入口
    # ═══════════════════════════════════════════════════════

    def parse(self) -> Document:
        """解析全部顶层语句为 Document（空源码 → 空配置，非错误）。"""
        # 懒初始化：预读第一个 token
        first_tok = self._stream.peek()
        # 仅物理耗尽（迭代器无任何 token，含 EOF 哨兵）才视为空列表；
        # 空源码经 FinalTokenizer 总产出 EofToken 哨兵，属合法空配置（非错误）。
        if isinstance(first_tok, NoNextType):
            self._collector.add(diag('parse.empty_token_list', {}, SourceRange.empty()))
            return Document(source=SourceRange.empty())
        doc = Document(source=first_tok.raw.source)
        while True:
            stmt = self._parse_statement(self._stream, self._collector)
            if stmt is None:
                break
            doc.statements.append(stmt)
        # Document.source 覆盖整个文档（首 token → 最后消费 token）
        doc.source = self._stream.span_from(first_tok)
        return doc

    # ═══════════════════════════════════════════════════════
    # 顶层
    # ═══════════════════════════════════════════════════════

    @staticmethod
    def _parse_statement(stream: TokenStream, collector: DiagnosticCollector) -> Statement | None:
        """解析一条顶层语句。

        顶层与块内一致，接受**逗号或换行**分隔（二者等价，可混用）——
        整个文件（含模板定义、字段、结构级约束）可压缩成一行；
        导入语句内部仍强制逗号分隔（见 §3.2）。
        """
        stream.skip_separators()

        # EofToken 或物理耗尽均视为流结束
        if stream.eof():
            return None

        match stream.peek():
            case EnvImportToken() | FileImportToken() | FromImportToken() | VarImportToken():
                return Parser._parse_import_statement(stream, collector)
            case TildeToken():
                return Parser._parse_template_def(stream, collector)
            case IdentifierToken():
                return Parser._parse_field(stream, collector)
            case ColonToken():
                return Parser._parse_constraint_stmt(stream, collector)
            case DoubleStarToken():
                # 顶层（隐式 dict）**expr 解包：展开为顶层字段（disjoint merge，§2.7）
                tok = stream.expect(DoubleStarToken)
                val = Parser._parse_value(stream, collector)
                return UnpackValue(source=stream.span_from(tok), value=val, double=True)
            case _:
                bad_tok = stream.advance()
                collector.add(diag('parse.unrecognized_statement', {'name': bad_tok.raw.type.name}, bad_tok.raw.source))
                return ErrorStatement(
                    source=bad_tok.raw.source,
                    message=f'无法识别的顶层 token: {bad_tok.raw.type.name}',
                )

    # ═══════════════════════════════════════════════════════
    # 导入语句
    # ═══════════════════════════════════════════════════════

    @staticmethod
    def _parse_import_statement(stream: TokenStream, collector: DiagnosticCollector) -> Statement:
        """分发 !env / !file / !from 导入语句"""
        match stream.peek():
            case EnvImportToken() as tok:
                stream.advance()
                return Parser._parse_env_import(stream, collector, tok)
            case FileImportToken() as tok:
                stream.advance()
                return Parser._parse_file_import(stream, collector, tok)
            case FromImportToken() as tok:
                stream.advance()
                return Parser._parse_template_import(stream, collector, tok)
            case VarImportToken() as tok:
                stream.advance()
                return Parser._parse_var_import(stream, collector, tok)
            case _:
                first = stream.peek()
                return ErrorStatement(source=stream.span_from(first), message='无法识别的导入语句')

    @staticmethod
    def _peek_keyword(stream: TokenStream, name: str) -> bool:
        """当前 token 是否为名为 ``name`` 的标识符（import/as 已降级为标识符）。"""
        tok = stream.peek()
        return isinstance(tok, IdentifierToken) and tok.name == name

    @staticmethod
    def _expect_keyword(stream: TokenStream, collector: DiagnosticCollector, name: str) -> None:
        """期望语法位置上的关键字名（import/as），含错误恢复。"""
        if Parser._peek_keyword(stream, name):
            stream.advance()
            return
        tok = stream.peek()
        if isinstance(tok, NoNextType):
            collector.add(
                diag(
                    'parse.unexpected_token',
                    {'expected': f'关键字 {name!r}', 'actual': 'EOF'},
                    stream.span_from(None),
                )
            )
            return
        collector.add(
            diag(
                'parse.unexpected_token', {'expected': f'关键字 {name!r}', 'actual': tok.raw.type.name}, tok.raw.source
            )
        )
        stream.advance()

    @staticmethod
    def _consume_ellipsis(stream: TokenStream) -> bool:
        """若当前是 ``...`` 则消费并返回 True（展开轴标记，§2.8）。"""
        if isinstance(stream.peek(), EllipsisToken):
            stream.advance()
            return True
        return False

    @staticmethod
    def _parse_var_import(stream: TokenStream, collector: DiagnosticCollector, kw_tok: VarImportToken) -> VarStmt:
        """!var <值表达式> import [path] as <alias>（§2.10 本地 $ 空间注入）"""
        value = Parser._parse_value(stream, collector)
        Parser._expect_keyword(stream, collector, 'import')
        json_path = Parser._parse_json_path(stream, collector)
        Parser._expect_keyword(stream, collector, 'as')
        alias_tok = stream.expect(IdentifierToken)

        # 导入语句必须换行/EOF 结尾（同 !env）：否则同一行逗号后的语句会被误吞
        tok = stream.peek()
        if not isinstance(tok, NoNextType) and not (stream.eof() or isinstance(tok, NewlineToken)):
            collector.add(
                diag(
                    'parse.import_requires_newline',
                    {'actual': tok.raw.type.name},
                    stream.single_span(tok),
                )
            )

        return VarStmt(
            source=stream.span_from(kw_tok),
            value=value,
            json_path=json_path,
            alias=alias_tok.name,
        )

    @staticmethod
    def _parse_env_import(stream: TokenStream, collector: DiagnosticCollector, kw_tok: EnvImportToken) -> EnvImportStmt:
        """!env import NAME [as NEW_NAME]"""
        Parser._expect_keyword(stream, collector, 'import')
        name_tok = stream.expect(IdentifierToken)

        alias = None
        if Parser._peek_keyword(stream, 'as'):
            stream.advance()
            alias = stream.expect(IdentifierToken).name

        # 导入语句必须换行/EOF 结尾：!env 无导入项列表，若不加检查，同一行的逗号会被
        # 顶层 skip_separators 吞掉（`!env import A as a, x = 1` 被误认为合法），与
        # !from / !file 的「尾部必须换行」行为不一致。
        tok = stream.peek()
        # 显式排除 NoNextType 以收窄类型：stream.eof() 是方法调用，无法据此收窄 tok，
        # 否则 tok 仍为 Token | NoNextType，访问 tok.raw 会触发类型错误。
        if not isinstance(tok, NoNextType) and not (stream.eof() or isinstance(tok, NewlineToken)):
            collector.add(
                diag(
                    'parse.import_requires_newline',
                    {'actual': tok.raw.type.name},
                    stream.single_span(tok),
                )
            )

        # 注意：不在此消费尾部换行——语句间分隔由 _parse_statement 开头统一处理，
        # 否则语句 source 会把下一行行首吞入（与 Field 不一致）
        return EnvImportStmt(
            source=stream.span_from(kw_tok),
            name=name_tok.name,
            alias=alias,
        )

    @staticmethod
    def _parse_file_import(
        stream: TokenStream, collector: DiagnosticCollector, kw_tok: FileImportToken
    ) -> FileImportStmt:
        """!file "path" [as <format>] import .path.to.key as alias, ..."""
        path_tok = stream.expect(SinglelineStringToken)

        # 可选 as <format>
        fmt = None
        if Parser._peek_keyword(stream, 'as'):
            stream.advance()
            fmt = stream.expect(IdentifierToken).name

        Parser._expect_keyword(stream, collector, 'import')

        # 导入项列表（项之间必须用逗号分隔）
        items: list[FileImportItem] = []
        items.append(Parser._parse_file_import_item(stream, collector))

        while True:
            tok = stream.peek()
            if isinstance(tok, CommaToken):
                stream.advance()
                items.append(Parser._parse_file_import_item(stream, collector))
            elif isinstance(tok, NewlineToken):
                # 换行后若跟 .（非合法顶层语句起始）→ 漏逗号的导入项，容错继续；
                # 否则导入列表结束（换行后是新的顶层语句）
                stream.skip_newlines()
                nxt = stream.peek()
                if isinstance(nxt, DotToken):
                    collector.add(diag('parse.import_missing_comma', {}, nxt.raw.source))
                    items.append(Parser._parse_file_import_item(stream, collector))
                else:
                    break
            elif isinstance(tok, DotToken):
                # 同一行空格分隔后跟 . → 报缺失逗号，容错继续
                collector.add(diag('parse.import_missing_comma', {}, tok.raw.source))
                items.append(Parser._parse_file_import_item(stream, collector))
            else:
                # 同一行残留 token（非分隔符/下一导入项）→ 标识符则报缺失逗号（不静默）
                if isinstance(tok, IdentifierToken):
                    collector.add(diag('parse.import_missing_comma', {}, tok.raw.source))
                break

        # 注意：不在此消费尾部换行（语句间分隔由 _parse_statement 统一处理）
        return FileImportStmt(
            source=stream.span_from(kw_tok),
            file_path=path_tok.value,
            format=fmt,
            imports=items,
        )

    @staticmethod
    def _parse_file_import_item(stream: TokenStream, collector: DiagnosticCollector) -> FileImportItem:
        """解析单个 .path.to.key as alias。

        alias 必须提供——import 的值需要通过 $alias 引用。
        """
        first = stream.peek()
        json_path = Parser._parse_json_path(stream, collector)

        # 路径为空且非 `. as alias`（整文件导入）形式 → 缺 . 起始或 . 后无段名：
        # 报错并跳过该项残余（避免 as/alias 错位、后续 token 残留成顶层语句）
        if not json_path and not Parser._peek_keyword(stream, 'as'):
            tok = stream.peek()
            if isinstance(tok, DotToken):
                detail = '：. 后需要段名或 as 别名'
            else:
                detail = '：路径必须以 . 起始'
            if not isinstance(tok, NoNextType):
                collector.add(diag('parse.invalid_json_path', {'detail': detail}, tok.raw.source))
            Parser._skip_to_import_boundary(stream)
            return FileImportItem(
                source=stream.span_from(first),
                json_path=[],
                alias='',
            )

        Parser._expect_keyword(stream, collector, 'as')
        alias = stream.expect(IdentifierToken).name

        # 注意：不在此处跳过换行——由 _parse_file_import 的列表循环统一处理，
        # 以区分「换行后的新语句」与「同一行残留 token」
        return FileImportItem(
            source=stream.span_from(first),
            json_path=json_path,
            alias=alias,
        )

    @staticmethod
    def _skip_to_import_boundary(stream: TokenStream) -> None:
        """跳过当前导入项的残余 token，直到逗号/换行或 EOF（错误恢复）。"""
        while not stream.eof() and not isinstance(stream.peek(), (CommaToken, NewlineToken)):
            stream.advance()

    @staticmethod
    def _parse_json_path(stream: TokenStream, collector: DiagnosticCollector) -> list[JsonPathSegment]:
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
        tok = stream.peek()
        if not isinstance(tok, DotToken):
            return []
        stream.advance()

        # 第一个段：标识符（非 as）、字符串或下标；`.` 后是 as（别名关键字）→ 整文件导入
        tok = stream.peek()
        if isinstance(tok, IdentifierToken) and tok.name != 'as':
            segments.append(JsonPathKey(source=tok.raw.source, key=tok.name))
            stream.advance()
        elif isinstance(tok, SinglelineStringToken):
            segments.append(JsonPathKey(source=tok.raw.source, key=tok.value))
            stream.advance()
        elif isinstance(tok, LbracketToken):
            # 首段下标：.[N]（统一 path 语义，§4.4）
            lbracket = stream.advance()
            match stream.peek():
                case IntegerToken(value=value):
                    stream.advance()
                    if isinstance(stream.peek(), RbracketToken):
                        stream.advance()
                    else:
                        Parser._report_invalid_json_path(stream, collector, '：[ 下标后缺少 ]')
                    segments.append(JsonPathIndex(source=stream.span_from(lbracket), index=value))
                case _:
                    Parser._report_invalid_json_path(stream, collector, '：[ 后须为整数下标')
                    return []
        else:
            # 只有 .（或 . as alias）→ 导入整个文件
            return []

        # 后续段：".key" 或 "[index]"
        while not stream.eof():
            match stream.peek():
                case DotToken():
                    stream.advance()
                    match stream.peek():
                        case IdentifierToken(name=name) as id_tok:
                            segments.append(JsonPathKey(source=stream.single_span(id_tok), key=name))
                            stream.advance()
                        case SinglelineStringToken(value=value) as str_tok:
                            segments.append(JsonPathKey(source=stream.single_span(str_tok), key=value))
                            stream.advance()
                        case _:
                            Parser._report_invalid_json_path(stream, collector, '：. 后缺少段名')
                            break

                case LbracketToken():
                    lbracket = stream.advance()
                    match stream.peek():
                        case IntegerToken(value=value):
                            stream.advance()
                            if isinstance(stream.peek(), RbracketToken):
                                stream.advance()
                            else:
                                Parser._report_invalid_json_path(stream, collector, '：[ 下标后缺少 ]')
                            segments.append(JsonPathIndex(source=stream.span_from(lbracket), index=value))
                        case _:
                            Parser._report_invalid_json_path(stream, collector, '：[ 后须为整数下标')
                            break

                case _:
                    break

        return segments

    @staticmethod
    def _report_invalid_json_path(stream: TokenStream, collector: DiagnosticCollector, detail: str) -> None:
        """JSON path 段无效 → 报 parse.invalid_json_path（指向当前 token）。"""
        tok = stream.peek()
        if isinstance(tok, NoNextType):
            return
        collector.add(diag('parse.invalid_json_path', {'detail': detail}, tok.raw.source))

    @staticmethod
    def _parse_template_import(
        stream: TokenStream, collector: DiagnosticCollector, kw_tok: FromImportToken
    ) -> TemplateImportStmt:
        """!from "path" import Name1 [as Alias1], Name2, ..."""
        path_tok = stream.expect(SinglelineStringToken)
        Parser._expect_keyword(stream, collector, 'import')

        # 导入项列表（项之间必须用逗号分隔）
        items: list[TemplateImportItem] = []
        items.append(Parser._parse_template_import_item(stream, collector))

        while True:
            tok = stream.peek()
            if isinstance(tok, CommaToken):
                stream.advance()
                items.append(Parser._parse_template_import_item(stream, collector))
            elif isinstance(tok, IdentifierToken):
                # 同一行内空格分隔（无逗号/换行）→ 报缺失逗号，容错继续（漏逗号）
                collector.add(diag('parse.import_missing_comma', {}, tok.raw.source))
                items.append(Parser._parse_template_import_item(stream, collector))
            else:
                # 换行/EOF 等 → 导入列表结束（换行后是新的顶层语句，不是导入项）
                break

        # 注意：不在此消费尾部换行（语句间分隔由 _parse_statement 统一处理）
        return TemplateImportStmt(
            source=stream.span_from(kw_tok),
            from_path=path_tok.value,
            items=items,
        )

    @staticmethod
    def _parse_template_import_item(stream: TokenStream, collector: DiagnosticCollector) -> TemplateImportItem:
        """解析单个导入项: Name [as Alias]。"""
        first = stream.peek()
        name_tok = stream.expect(IdentifierToken)

        alias = None
        if Parser._peek_keyword(stream, 'as'):
            stream.advance()
            alias = stream.expect(IdentifierToken).name

        return TemplateImportItem(
            source=stream.span_from(first),
            name=name_tok.name,
            alias=alias,
        )

    # ═══════════════════════════════════════════════════════
    # 结构级约束语句（顶层）
    # ═══════════════════════════════════════════════════════

    @staticmethod
    def _parse_constraint_stmt(stream: TokenStream, collector: DiagnosticCollector) -> ConstraintStmt:
        """顶层结构级约束: ``: <constraint, ...>`` 或 ``: constraint``。

        顶层是隐式 dict，``:`` 起始的语句约束编译产物 root 的整体。
        """
        first = stream.peek()
        stream.advance()  # 消费 ':'
        parsed = Parser._parse_constraints(stream, collector)
        # 注意：不在此消费尾部分隔符（语句间分隔由 _parse_statement 统一处理）
        return ConstraintStmt(
            source=stream.span_from(first),
            constraints=parsed.constraints,
        )

    # ═══════════════════════════════════════════════════════
    # 模板定义
    # ═══════════════════════════════════════════════════════

    @staticmethod
    def _parse_template_def(stream: TokenStream, collector: DiagnosticCollector) -> TemplateDef:
        """~Name [(config...)] { template_fields... }"""
        first = stream.peek()
        stream.expect(TildeToken)
        name_tok = stream.expect(IdentifierToken)

        # 可选模板配置参数: ~Name(allow_extra=true, ...)
        # 语法层解析为类型化 TemplateConfig（未知键 / 类型错 / 非字面量 → 诊断）
        config = TemplateConfig()
        if isinstance(stream.peek(), LparenToken):
            stream.advance()
            stream.skip_newlines()
            missing_sep_reported = [False]
            while not stream.check(RawTokenType.RPAREN) and not stream.eof():
                key_tok = stream.expect(IdentifierToken)
                stream.expect(EqualsToken)
                # 裸标识符 → 字段名字符串（extra_*_vars = 字段名，§2.9）；其余走通用值
                if isinstance(stream.peek(), IdentifierToken):
                    idv = stream.expect(IdentifierToken)
                    value = LiteralValue(
                        source=stream.single_span(idv),
                        value=SinglelineStringToken(raw=idv.raw, value=idv.name),
                    )
                else:
                    value = Parser._parse_value(stream, collector)
                Parser._apply_template_config(collector, config, key_tok, value)
                had_sep = stream.skip_separators()
                Parser._missing_separator(
                    stream,
                    collector,
                    had_sep,
                    isinstance(stream.peek(), IdentifierToken),
                    RawTokenType.RPAREN,
                    missing_sep_reported,
                )
            stream.expect(RparenToken)

        stream.expect(LbraceToken)
        stream.skip_newlines()

        fields: list[TemplateField] = []
        constraints: list[Constraint] = []
        missing_sep_reported = [False]
        while not stream.check(RawTokenType.RBRACE) and not stream.eof():
            # 结构级约束: : <...>
            if isinstance(stream.peek(), ColonToken):
                stream.advance()
                parsed = Parser._parse_constraints(stream, collector)
                constraints.extend(parsed.constraints)
            else:
                fields.append(Parser._parse_template_field(stream, collector))
            had_sep = stream.skip_separators()
            Parser._missing_separator(
                stream,
                collector,
                had_sep,
                isinstance(stream.peek(), (IdentifierToken, ColonToken)),
                RawTokenType.RBRACE,
                missing_sep_reported,
            )

        stream.expect(RbraceToken)
        # 注意：不在此消费尾部换行（语句间分隔由 _parse_statement 统一处理）

        return TemplateDef(
            source=stream.span_from(first),
            name=name_tok.name,
            fields=fields,
            config=config,
            constraints=constraints,
        )

    @staticmethod
    def _apply_template_config(
        collector: DiagnosticCollector,
        config: TemplateConfig,
        key_tok: IdentifierToken,
        value: Value,
    ) -> None:
        """模板头部配置项 → 类型化字段；未知键 / 类型错 / 非字面量 → 语法诊断。

        config 值是纯字面量（布尔 / 字符串 / 整数），不支持 ``$`` 引用等复杂值。
        """
        key = key_tok.name
        if not isinstance(value, LiteralValue):
            collector.add(diag('parse.template_config_value', {'key': key}, value.source))
            return
        py = Parser._literal_config_value(value)
        if key in _CONFIG_BOOL_KEYS:
            if isinstance(py, bool):
                setattr(config, key, py)
            else:
                collector.add(
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
                collector.add(
                    diag(
                        'parse.template_config_type',
                        {'key': key, 'expected': 'str', 'actual': _py_describe(py)},
                        key_tok.raw.source,
                    )
                )
        else:
            collector.add(
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

    @staticmethod
    def _parse_template_field(stream: TokenStream, collector: DiagnosticCollector) -> TemplateField:
        """解析模板内部字段：必须有类型标注，默认值可选。"""
        first = stream.peek()
        name_tok = stream.expect(IdentifierToken)

        # 类型标注（模板字段必须）：缺失或为空 → 报错并跳过该字段
        if isinstance(stream.peek(), ColonToken):
            stream.advance()
            constraints = Parser._parse_constraints(stream, collector)
            if not constraints.constraints:
                collector.add(
                    diag(
                        'parse.template_field_no_constraint',
                        {'field': name_tok.name},
                        stream.single_span(name_tok),
                    )
                )
        else:
            collector.add(
                diag(
                    'parse.template_field_no_constraint',
                    {'field': name_tok.name},
                    stream.single_span(name_tok),
                )
            )
            Parser._skip_to_field_boundary(stream)
            return TemplateField(
                source=stream.single_span(name_tok),
                name=name_tok.name,
                constraints=Constraints(source=stream.single_span(name_tok)),
                default_value=None,
            )

        # 默认值（可选，省略 = 必填）
        default_value: Value | None = None
        if isinstance(stream.peek(), EqualsToken):
            stream.advance()
            default_value = Parser._parse_value(stream, collector)
        elif isinstance(stream.peek(), (LbraceToken, LbracketToken, IdentifierToken)):
            # 省略等号仅限复合值与模板调用（与普通字段规则一致）
            default_value = Parser._parse_value(stream, collector)
        elif Parser._starts_value(stream.peek()):
            # 字面量 / $ 引用省略等号 → 报错但仍解析（lint 式，尽力恢复）
            collector.add(diag('parse.field_requires_equals', {'name': name_tok.name}, stream.single_span(name_tok)))
            default_value = Parser._parse_value(stream, collector)

        return TemplateField(
            source=stream.span_from(first),
            name=name_tok.name,
            constraints=constraints,
            default_value=default_value,
        )

    @staticmethod
    def _skip_to_field_boundary(stream: TokenStream) -> None:
        """跳过当前模板字段的残余 token，直到分隔符或模板闭合符（错误恢复）。"""
        while not stream.eof() and not isinstance(stream.peek(), (CommaToken, NewlineToken, RbraceToken)):
            stream.advance()

    # ═══════════════════════════════════════════════════════
    # 字段
    # ═══════════════════════════════════════════════════════

    @staticmethod
    def _parse_field(stream: TokenStream, collector: DiagnosticCollector) -> Field:
        """解析普通字段：name[: type] [= value]

        支持省略等号：name { ... }, name [ ... ], name Template(...)
        """
        first = stream.peek()
        name_tok = stream.expect(IdentifierToken)

        # 类型标注 name: <...> 或 name: type 或 name: type?
        constraints: Constraints | None = None
        if isinstance(stream.peek(), ColonToken):
            stream.advance()
            constraints = Parser._parse_constraints(stream, collector)
            if not constraints.constraints:
                # 类型标注为空（a: 后无约束）→ 报错（与模板字段 template_field_no_constraint 对齐）
                collector.add(
                    diag('parse.empty_type_annotation', {'field': name_tok.name}, stream.single_span(name_tok))
                )

        # 值：有 = 时直接解析；省略等号仅限复合值（dict/array）与模板调用
        value: Value | None = None
        tok = stream.peek()
        if isinstance(tok, EqualsToken):
            stream.advance()
            value = Parser._parse_value(stream, collector)
        elif isinstance(tok, (LbraceToken, LbracketToken, IdentifierToken)):
            value = Parser._parse_value(stream, collector)
        elif Parser._starts_value(tok):
            # 字面量 / $ 引用省略等号 → 报错但仍解析（lint 式，尽力恢复）
            collector.add(diag('parse.field_requires_equals', {'name': name_tok.name}, stream.single_span(name_tok)))
            value = Parser._parse_value(stream, collector)

        return Field(
            source=stream.span_from(first),
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

    @staticmethod
    def _missing_separator(
        stream: TokenStream,
        collector: DiagnosticCollector,
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
        if stream.check(closing_type) or stream.check(RawTokenType.EOF):
            return
        tok = stream.peek()
        if not isinstance(tok, NoNextType):
            collector.add(diag('parse.missing_separator', {}, tok.raw.source))
        reported[0] = True

    @staticmethod
    def _skip_to_container_close(stream: TokenStream) -> None:
        """超深嵌套恢复：平衡跳过当前容器的剩余内容。

        从超限点开始跳过 token，遇到开括号也一并跳过（含其配对的闭合符），
        直到重新回到超限点所在容器的闭合符（depth 归零）才停止，不消费该闭合符。
        这样外层逐层退栈时能按各自闭合符正常退出，不产生多余 token 泄漏。
        """
        depth = 0
        while not stream.eof():
            tok = stream.peek()
            if isinstance(tok, (LbraceToken, LbracketToken, LparenToken, LangleToken)):
                depth += 1
                stream.advance()
            elif isinstance(tok, (RbraceToken, RbracketToken, RparenToken, RangleToken)):
                if depth == 0:
                    return
                depth -= 1
                stream.advance()
            else:
                stream.advance()

    # ═══════════════════════════════════════════════════════
    # 约束列表
    # ═══════════════════════════════════════════════════════

    @staticmethod
    def _parse_constraints(stream: TokenStream, collector: DiagnosticCollector) -> Constraints:
        """解析约束。

        支持:
        - int, str, bool, float, list, dict, ?, object
        - type? → one(type, ?)
        - <constraint, constraint, ...> → all(constraint, ...)
        - <any(...)>, <one(...)>, <not(...)>, <all(...)>
        """
        first = stream.peek()

        match first:
            case LangleToken():
                stream.advance()
                stream.skip_newlines()
                constraints: list[Constraint] = []
                missing_sep_reported = [False]
                while not stream.check(RawTokenType.RANGLE) and not stream.eof():
                    # 约束列表内出现 < 嵌套（非法语法）→ 报错并平衡跳过嵌套，
                    # 避免逐层诊断爆炸与多余 > 泄漏到顶层语句
                    tok = stream.peek()
                    if isinstance(tok, LangleToken):
                        collector.add(diag('parse.unrecognized_constraint', {'name': 'LANGLE'}, tok.raw.source))
                        Parser._skip_to_container_close(stream)
                        continue
                    constraints.append(Parser._parse_constraint(stream, collector))
                    had_sep = stream.skip_separators()
                    Parser._missing_separator(
                        stream,
                        collector,
                        had_sep,
                        Parser._starts_constraint(stream.peek()),
                        RawTokenType.RANGLE,
                        missing_sep_reported,
                    )
                stream.expect(RangleToken)
                return Constraints(source=stream.span_from(first), constraints=constraints)

            case IdentifierToken(name=name):
                stream.advance()
                ident = ConstraintIdent(source=stream.single_span(first), name=name)

                if isinstance(stream.peek(), QuestionToken):
                    stream.advance()
                    # 直接展开: type? → one(type, ?)
                    return Constraints(
                        source=stream.span_from(first),
                        constraints=[Parser._nullable(ident)],
                    )

                # 单约束函数调用可省略尖括号: field: regex("re") = ...
                if isinstance(stream.peek(), LparenToken):
                    call = Parser._parse_constraint_call(stream, collector, first)
                    # 调用后也可空: regex("re")? → one(regex("re"), ?)
                    if isinstance(stream.peek(), QuestionToken):
                        stream.advance()
                        call = Parser._nullable(call)
                    return Constraints(
                        source=stream.span_from(first),
                        constraints=[call],
                    )

                return Constraints(
                    source=stream.span_from(first),
                    constraints=[ident],
                )

            case QuestionToken():
                stream.advance()
                return Constraints(
                    source=stream.span_from(first),
                    constraints=[ConstraintIdent(source=stream.single_span(first), name='?')],
                )

            case _:
                # 无效约束起始：报错；不消费容器闭合符（避免吞掉 }/>/）破坏外层解析）
                tok = stream.peek()
                if not isinstance(tok, (NoNextType, EofToken, RangleToken, RbraceToken, RparenToken)):
                    bad_tok = stream.advance()
                    collector.add(
                        diag('parse.unrecognized_constraint', {'name': bad_tok.raw.type.name}, bad_tok.raw.source)
                    )
                return Constraints(source=stream.span_from(first))

    @staticmethod
    def _nullable(c: Constraint) -> ConstraintCall:
        """可空包装：constraint? → one(constraint, ?)。"""
        return ConstraintCall(
            source=c.source,
            name='one',
            arguments=[c, ConstraintIdent(source=c.source, name='?')],
        )

    @staticmethod
    def _parse_constraint(stream: TokenStream, collector: DiagnosticCollector) -> Constraint:
        """解析单个约束（含嵌套深度保护）。"""
        depth = stream.enter_nested()
        if depth > _MAX_NESTING:
            collector.add(diag('parse.nesting_too_deep', {'limit': _MAX_NESTING}, stream.span_from(stream.peek())))
            Parser._skip_to_container_close(stream)
            stream.exit_nested()
            return ErrorConstraint(source=stream.span_from(None), message=f'嵌套层级过深（> {_MAX_NESTING}）')
        try:
            return Parser._parse_constraint_inner(stream, collector)
        finally:
            stream.exit_nested()

    @staticmethod
    def _parse_constraint_inner(stream: TokenStream, collector: DiagnosticCollector) -> Constraint:
        """解析单个约束：标识符、函数调用或字面量（支持可空后缀 ?）。"""
        tok = stream.peek()
        base: Constraint

        match tok:
            case IdentifierToken() as name_tok:
                stream.advance()
                if isinstance(stream.peek(), LparenToken):
                    base = Parser._parse_constraint_call(stream, collector, name_tok)
                else:
                    base = ConstraintIdent(source=stream.single_span(name_tok), name=name_tok.name)

            case QuestionToken():
                stream.advance()
                return ConstraintIdent(source=tok.raw.source, name='?')

            case StringToken() | IntegerToken() | FloatToken() | BoolToken() | NullToken():
                base = Parser._parse_constraint_literal(stream)

            case _:
                if isinstance(tok, (NoNextType, EofToken)):
                    return ErrorConstraint(source=SourceRange.empty(), message='无法解析的约束: EOF')
                bad_tok = stream.advance()
                collector.add(
                    diag('parse.unrecognized_constraint', {'name': bad_tok.raw.type.name}, bad_tok.raw.source)
                )
                return ErrorConstraint(
                    source=stream.single_span(bad_tok),
                    message=f'无法解析的约束: {bad_tok.raw.type.name}',
                )

        # 可空后缀: constraint? → one(constraint, ?)
        if isinstance(stream.peek(), QuestionToken):
            stream.advance()
            return Parser._nullable(base)
        return base

    @staticmethod
    def _parse_constraint_call(
        stream: TokenStream, collector: DiagnosticCollector, name_tok: IdentifierToken
    ) -> ConstraintCall:
        """解析约束函数调用: name(arg, arg, ...)。"""
        stream.expect(LparenToken)
        stream.skip_newlines()
        args: list[Constraint] = []
        missing_sep_reported = [False]
        while not stream.check(RawTokenType.RPAREN) and not stream.eof():
            args.append(Parser._parse_constraint(stream, collector))
            had_sep = stream.skip_separators()
            Parser._missing_separator(
                stream,
                collector,
                had_sep,
                Parser._starts_constraint(stream.peek()),
                RawTokenType.RPAREN,
                missing_sep_reported,
            )
        stream.expect(RparenToken)
        return ConstraintCall(
            source=stream.span_from(name_tok),
            name=name_tok.name,
            arguments=args,
        )

    @staticmethod
    def _parse_constraint_literal(stream: TokenStream) -> ConstraintLiteral:
        """解析约束中的字面量参数，包装为 ConstraintLiteral。"""
        tok = stream.peek()
        stream.advance()
        lit = Parser._wrap_literal(tok)
        return ConstraintLiteral(source=lit.source, value=lit)

    # ═══════════════════════════════════════════════════════
    # 值
    # ═══════════════════════════════════════════════════════

    @staticmethod
    def _parse_value(stream: TokenStream, collector: DiagnosticCollector) -> Value:
        """解析任意值（含嵌套深度保护）。"""
        depth = stream.enter_nested()
        if depth > _MAX_NESTING:
            collector.add(diag('parse.nesting_too_deep', {'limit': _MAX_NESTING}, stream.span_from(stream.peek())))
            Parser._skip_to_container_close(stream)
            stream.exit_nested()
            return ErrorValue(source=stream.span_from(None), message=f'嵌套层级过深（> {_MAX_NESTING}）')
        try:
            return Parser._parse_value_inner(stream, collector)
        finally:
            stream.exit_nested()

    @staticmethod
    def _parse_value_inner(stream: TokenStream, collector: DiagnosticCollector) -> Value:
        """解析任意值（嵌套深度已在包装层保护）。"""
        match stream.peek():
            # ── $ 导入空间引用 ──
            case DollarToken():
                return Parser._parse_dollar_value(stream, collector)

            # ── 字面量（FloatToken 覆盖所有浮点值，含 NaN / ±Inf）──
            case StringToken() | IntegerToken() | FloatToken() | BoolToken() | NullToken() | NoexistToken() as tok:
                stream.advance()
                return Parser._wrap_literal(tok)

            # ── 复合值 ──
            case LbraceToken():
                return Parser._parse_object(stream, collector)
            case LbracketToken():
                return Parser._parse_array(stream, collector)

            # ── 标识符 → 模板调用 ──
            case IdentifierToken():
                ident = stream.expect(IdentifierToken)
                # 标识符后接 = / : → 不是模板调用而是新语句的字段定义：
                # 说明外层数组/对象未闭合。报 parse.value_field 并停止，
                # 避免把后续行误解析为模板调用（消除 template.undefined 级联）。
                nxt = stream.peek()
                if isinstance(nxt, (EqualsToken, ColonToken)):
                    collector.add(diag('parse.value_field', {'name': ident.name}, stream.single_span(ident)))
                    return ErrorValue(source=stream.single_span(ident), message=f'值位置出现字段定义: {ident.name}')
                return Parser._parse_template_call(stream, collector, ident)

            case EllipsisToken() as el_tok:
                # ... 只在模板调用参数上下文合法（§2.8 展开轴 / 展开传播）
                stream.advance()
                collector.add(diag('parse.expand_outside_call', {}, stream.single_span(el_tok)))
                return ErrorValue(source=stream.single_span(el_tok), message='... 只能在模板调用参数上下文使用')

            case tok:
                name = 'EOF' if isinstance(tok, NoNextType) else tok.raw.type.name
                source = SourceRange.empty() if isinstance(tok, NoNextType) else tok.raw.source
                if not isinstance(tok, NoNextType):
                    stream.advance()
                collector.add(diag('parse.unrecognized_value', {'name': name}, source))
                return ErrorValue(source=source, message=f'无法解析的值: {name}')

    @staticmethod
    def _wrap_literal(tok: Token | NoNextType | None) -> LiteralValue:
        """将字面量 Token 包装为 LiteralValue。"""
        assert not isinstance(tok, NoNextType) and tok is not None
        return LiteralValue(source=tok.raw.source, value=tok)  # type: ignore[arg-type]

    @staticmethod
    def _parse_dollar_value(stream: TokenStream, collector: DiagnosticCollector) -> DollarValue:
        """$name [as type] 导入空间引用。"""
        dollar_tok = stream.expect(DollarToken)
        name_tok = stream.expect(IdentifierToken)

        type_cast = None
        if Parser._peek_keyword(stream, 'as'):
            stream.advance()
            cast_tok = stream.peek()
            if isinstance(cast_tok, IdentifierToken):
                name = cast_tok.name
                if name in ('int', 'float', 'bool', 'str'):
                    type_cast = name
                else:
                    collector.add(diag('parse.invalid_cast', {'type': name}, cast_tok.raw.source))
                stream.advance()

        return DollarValue(
            source=stream.span_from(dollar_tok),
            name=name_tok.name,
            type_cast=type_cast,
        )

    @staticmethod
    def _parse_object(stream: TokenStream, collector: DiagnosticCollector) -> DictValue:
        """{ field, ... }

        dict 结构级约束: ``: <constraint, ...>`` 作用于该字面量 dict 的整体。
        """
        lbrace_tok = stream.expect(LbraceToken)
        stream.skip_separators()

        fields: list[Field] = []
        unpacks: list[UnpackValue] = []
        constraints: list[Constraint] = []
        missing_sep_reported = [False]
        while not stream.check(RawTokenType.RBRACE) and not stream.eof():
            # 结构级约束: : <...>
            if isinstance(stream.peek(), ColonToken):
                stream.advance()
                parsed = Parser._parse_constraints(stream, collector)
                constraints.extend(parsed.constraints)
            elif isinstance(stream.peek(), DoubleStarToken):
                # **expr：dict 解包（展开为键值对并入字段集）
                tok = stream.expect(DoubleStarToken)
                val = Parser._parse_value(stream, collector)
                unpacks.append(UnpackValue(source=stream.span_from(tok), value=val, double=True))
            else:
                fields.append(Parser._parse_field(stream, collector))
            had_sep = stream.skip_separators()
            Parser._missing_separator(
                stream,
                collector,
                had_sep,
                isinstance(stream.peek(), (IdentifierToken, ColonToken)),
                RawTokenType.RBRACE,
                missing_sep_reported,
            )

        stream.expect(RbraceToken)
        return DictValue(source=stream.span_from(lbrace_tok), fields=fields, constraints=constraints, unpacks=unpacks)

    @staticmethod
    def _parse_array(stream: TokenStream, collector: DiagnosticCollector) -> ArrayValue:
        """[ value, ... ] 逗号或换行分隔，元素间必须显式分隔。"""
        lbracket_tok = stream.expect(LbracketToken)
        stream.skip_newlines()

        elements: list[Value | UnpackValue] = []
        missing_sep_reported = [False]
        while not stream.check(RawTokenType.RBRACKET) and not stream.eof():
            if isinstance(stream.peek(), StarToken):
                # *expr：list 解包（展开为元素）
                tok = stream.expect(StarToken)
                val = Parser._parse_value(stream, collector)
                elements.append(UnpackValue(source=stream.span_from(tok), value=val, double=False))
            else:
                elements.append(Parser._parse_value(stream, collector))
            had_sep = stream.skip_separators()
            Parser._missing_separator(
                stream,
                collector,
                had_sep,
                Parser._starts_value(stream.peek()),
                RawTokenType.RBRACKET,
                missing_sep_reported,
            )

        stream.expect(RbracketToken)
        return ArrayValue(source=stream.span_from(lbracket_tok), elements=elements)

    @staticmethod
    def _parse_template_call(
        stream: TokenStream, collector: DiagnosticCollector, name_tok: IdentifierToken
    ) -> TemplateCallValue:
        """Name(pos_args..., named_arg=value, ...)"""
        stream.expect(LparenToken)
        stream.skip_newlines()

        positional: list[Value] = []
        named: dict[str, Value] = {}
        unpack_args: list[UnpackValue] = []  # *expr（list → 位置参数）
        unpack_kwargs: list[UnpackValue] = []  # **expr（dict → 命名参数）
        axis_positional: set[int] = set()  # 位置参数中带 ... 的索引（展开轴，§2.8）
        axis_named: set[str] = set()  # 命名参数中带 ... 的键
        axis_unpack_kwargs: set[int] = set()  # **expr 解包参数中带 ... 的索引
        saw_named = False
        missing_sep_reported = [False]

        while not stream.check(RawTokenType.RPAREN) and not stream.eof():
            stream.skip_newlines()
            if stream.check(RawTokenType.RPAREN) or stream.eof():
                break

            tok = stream.peek()

            # 解包参数：**expr（dict → 命名参数）/ *expr（list → 位置参数）
            if isinstance(tok, DoubleStarToken):
                stream.advance()
                val = Parser._parse_value(stream, collector)
                idx = len(unpack_kwargs)
                unpack_kwargs.append(UnpackValue(source=stream.single_span(tok), value=val, double=True))
                if Parser._consume_ellipsis(stream):
                    axis_unpack_kwargs.add(idx)  # **expr...：list[dict] 逐元素解包（§2.8）
                saw_named = True
            elif isinstance(tok, StarToken):
                stream.advance()
                val = Parser._parse_value(stream, collector)
                unpack_args.append(UnpackValue(source=stream.single_span(tok), value=val, double=False))
            # 分支 1：标识符 → 可能是命名参数或模板调用（位置参数）
            elif isinstance(tok, IdentifierToken):
                ident: IdentifierToken = stream.expect(IdentifierToken)  # 消费到缓冲区
                nxt = stream.peek()  # 下一个 token

                if isinstance(nxt, EqualsToken):
                    stream.advance()  # 消费 =
                    if ident.name in named:
                        collector.add(
                            diag(
                                'template.dup_argument',
                                {'template': name_tok.name, 'arg': ident.name},
                                stream.single_span(ident),
                            )
                        )
                    named[ident.name] = Parser._parse_value(stream, collector)
                    if Parser._consume_ellipsis(stream):
                        axis_named.add(ident.name)  # 命名参数轴
                    saw_named = True
                else:
                    # 不是 = → 模板调用（位置参数），复用已消费的 ident
                    positional.append(Parser._parse_template_call(stream, collector, ident))
                    if Parser._consume_ellipsis(stream):
                        axis_positional.add(len(positional) - 1)
            else:
                # 分支 2：其他 token → 一定是位置参数
                if saw_named:
                    collector.add(diag('parse.template_arg_order', {}, stream.single_span(name_tok)))
                positional.append(Parser._parse_value(stream, collector))
                if Parser._consume_ellipsis(stream):
                    axis_positional.add(len(positional) - 1)

            had_sep = stream.skip_separators()
            Parser._missing_separator(
                stream,
                collector,
                had_sep,
                Parser._starts_value(stream.peek()),
                RawTokenType.RPAREN,
                missing_sep_reported,
            )

        stream.expect(RparenToken)
        # 调用级 ...：展开传播（本调用展开结果作为包围模板调用的轴，§2.8）
        propagate = False
        if isinstance(stream.peek(), EllipsisToken):
            stream.advance()
            propagate = True
        return TemplateCallValue(
            source=stream.span_from(name_tok),
            template_name=name_tok.name,
            positional_args=positional,
            named_args=named,
            unpack_args=unpack_args,
            unpack_kwargs=unpack_kwargs,
            axis_positional=frozenset(axis_positional),
            axis_named=frozenset(axis_named),
            axis_unpack_kwargs=frozenset(axis_unpack_kwargs),
            propagate=propagate,
        )
