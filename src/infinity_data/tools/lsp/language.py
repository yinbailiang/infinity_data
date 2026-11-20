"""infinity_data 官方 LSP 集成层：把编译器能力映射为 LSP 能力。

- ``analyze``：编译并转出 LSP 诊断（publishDiagnostics）
- ``completion_items``：模板名 + 内置约束名 + 语言关键字 + 模板字段补全
- ``hover``：约束描述 / 编译产物预览（emit 完整转化语义：decimal / path / noexist
  自描述标记）/ 模板结构骨架
- ``document_symbols``：文档大纲（模板定义 + 顶层字段）
- ``definition``：跳转到定义（模板 / ``!from`` 导入 / ``$`` 引用）
- ``semantic_tokens``：基于 RawTokenizer 的语法高亮

位置语义：编译器 ``SourceInfo.line/col`` 为 **1-based 码点**，LSP 为 **0-based
UTF-16 单元**（见 :mod:`infinity_data.tools.lsp.positions`）；``SourceRange.end`` 为
闭区间，LSP end 为开区间。

本模块消费**当前版本**的公开 API：``compile_source`` / ``parse_source(File)`` /
``RawTokenizer`` / ``emit`` / ``semantic``，与玩具版 LSP（老 API）的区别见
:mod:`infinity_data.tools.lsp` 包文档。
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

from infinity_data import SandboxConfig, Severity, compile_source
from infinity_data.emit import dump_to_json
from infinity_data.emit.config import EmitConfig
from infinity_data.frontend import parse_source
from infinity_data.infra.diagnostics import DiagnosticCollector
from infinity_data.infra.file import MemFile
from infinity_data.infra.location import SourceRange
from infinity_data.parser import (
    ArrayValue,
    ConstraintCall,
    ConstraintIdent,
    ConstraintLiteral,
    Constraints,
    DictValue,
    DollarValue,
    EnvImportStmt,
    ErrorConstraint,
    ErrorValue,
    Field,
    FileImportStmt,
    LiteralValue,
    NamedArg,
    TemplateCallValue,
    TemplateDef,
    TemplateField,
    UnpackValue,
    VarStmt,
    walk,
)
from infinity_data.sandbox import Sandbox
from infinity_data.semantic import AstBuilder, ImportResolver, TemplateGraphResolver
from infinity_data.semantic.registry import ConstraintRegistry
from infinity_data.semantic.std import (
    StdArray,
    StdField,
    StdLiteral,
    StdObject,
    StdValue,
)
from infinity_data.tokenizer.identifiers import decode_string_identifier, render_identifier
from infinity_data.tokenizer.keywords import BANG_KEYWORDS, CONTEXTUAL_KEYWORDS, CONTEXTUAL_NAMES, BangKeyword
from infinity_data.tokenizer.models.raw_tokens import RawTokenType
from infinity_data.tokenizer.models.tokens import NoexistToken, NullToken
from infinity_data.tokenizer.tokenizer import RawTokenizer
from infinity_data.tools.lsp.positions import to_lsp_range, utf16_len, utf16_prefix, utf16_to_cp

__all__ = [
    'SEMANTIC_TOKEN_TYPES',
    'analyze',
    'completion_items',
    'hover',
    'document_symbols',
    'folding_ranges',
    'definition',
    'semantic_tokens',
]

_REGISTRY = ConstraintRegistry()
"""内置约束注册表（补全 / 悬停候选）。"""

# 语言级关键字 / 字面量（补全候选）
LANGUAGE_KEYWORDS: list[tuple[str, str]] = [
    *((spec.label, f'{spec.summary}：{spec.usage}') for spec in BANG_KEYWORDS),
    *((spec.name, f'{spec.summary}：{spec.usage}') for spec in CONTEXTUAL_KEYWORDS),
    ('~', '模板定义：~Name { ... }'),
    ('...', '模板展开：参数级 = 展开轴，调用级 = 笛卡尔积'),
    ('^', '笛卡尔积：调用级 ^ 后缀，多轴全组合展开'),
    ('**', '解包：**expr 展开为命名参数 / dict 键值'),
    ('*', '解包：*expr 展开为位置参数 / list 元素'),
    ('null', '字面量：键存在但值为 null'),
    ('noexist', '字面量：键不出现在结果中'),
    ('true', '布尔字面量'),
    ('false', '布尔字面量'),
    ('nan', '浮点字面量 NaN'),
]

_EMPTY_SYMBOL_NAME = '<empty>'
"""错误恢复产生的空名字在大纲中的占位（LSP 要求 name 非空）。"""

_SEVERITY_MAP: dict[Severity, int] = {
    Severity.ERROR: 1,
    Severity.WARNING: 2,
    Severity.INFO: 3,
}


# ── 虚拟环境变量注入（`#env` 注释声明）──────────────────────
# 语法: `#env: NAME "VALUE"` —— 环境变量名在前、虚拟值在后。
# 当进程里未设置 NAME 时，LSP 注入 VALUE，避免 `env_not_set` 中止编译、
# 吞掉同文件其他诊断。真实环境变量优先，仅缺失时用注释里的值兜底。
_ENV_DECL_RE = re.compile(r'#env:\s*([A-Za-z_][A-Za-z0-9_]*)\s*"([^"]*)"')


def collect_env_declarations(text: str) -> dict[str, str]:
    """扫描 ``#env: NAME \"VALUE\"`` 注释，返回 {变量名: 虚拟值}。"""
    return {m.group(1): m.group(2) for m in _ENV_DECL_RE.finditer(text)}


def virtual_env(text: str) -> dict[str, str]:
    """为声明过但当前进程未设置的环境变量提供注释中的虚拟值（已设置的用真实值）。"""
    return {n: v for n, v in collect_env_declarations(text).items() if n not in os.environ}


# ── 语义令牌（分词器 + 语法上下文 → LSP semantic tokens）────────────────
# 使用 VS Code 内置标准类型（主题无需额外配置）：
#   class / type / function / parameter / variable / property /
#   keyword / string / number / operator / comment / decorator
SEMANTIC_TOKEN_TYPES: list[str] = [
    'class',
    'type',
    'function',
    'parameter',
    'variable',
    'property',
    'keyword',
    'string',
    'number',
    'operator',
    'comment',
    'decorator',
]

_TOKEN_INDEX: dict[str, int] = {name: i for i, name in enumerate(SEMANTIC_TOKEN_TYPES)}

_RAW = RawTokenType

# 与语法上下文无关的 token → 语义类型
_FIXED_SEMANTIC: dict[RawTokenType, str] = {
    # 结构定界符 / 运算符
    _RAW.LBRACE: 'operator',
    _RAW.RBRACE: 'operator',
    _RAW.LBRACKET: 'operator',
    _RAW.RBRACKET: 'operator',
    _RAW.LPAREN: 'operator',
    _RAW.RPAREN: 'operator',
    _RAW.LANGLE: 'operator',
    _RAW.RANGLE: 'operator',
    # 赋值 / 类型标注冒号按 keyword 着色（结构分隔符，与普通标点区分开）
    _RAW.EQUALS: 'keyword',
    _RAW.COLON: 'keyword',
    _RAW.COMMA: 'operator',
    _RAW.DOLLAR: 'operator',
    _RAW.DOT: 'operator',
    _RAW.STAR: 'operator',
    _RAW.DOUBLE_STAR: 'operator',
    _RAW.ELLIPSIS: 'operator',
    _RAW.CARET: 'operator',
    # 约束标记 / 字面量关键字
    _RAW.QUESTION: 'keyword',
    _RAW.EXCLAMATION: 'keyword',
    _RAW.BOOL: 'keyword',
    _RAW.NULL: 'keyword',
    _RAW.NOEXIST: 'keyword',
    # 字面量
    _RAW.STRING: 'string',
    _RAW.MULTILINE_STRING: 'string',
    _RAW.PATH: 'string',
    _RAW.INTEGER: 'number',
    _RAW.FLOAT: 'number',
    # Bang 指令 / 模板定义标记
    _RAW.BANG_KEYWORD: 'keyword',
    _RAW.TILDE: 'decorator',
}

# 上下文关键字（词法层为普通标识符，语法层才识别）
_CONTEXTUAL_KEYWORDS = CONTEXTUAL_NAMES

_REGISTRY_NAMES: frozenset[str] = frozenset(_REGISTRY.names)
_CAST_TYPE_NAMES: frozenset[str] = frozenset({'int', 'float', 'bool', 'str', 'path'})


def _classify_identifier(
    tok: Any,
    prev: Any,
    nxt: Any,
    stack: list[str],
    constraint_depth: int,
    bang: BangKeyword | None,
) -> str:
    """标识符 → 语义类型（模板名 / 约束类型 / 函数 / 参数 / 属性 / 变量 / 关键字）。"""
    raw = tok.raw
    prev_type = prev.type if prev is not None else None
    nxt_type = nxt.type if nxt is not None else None
    top = stack[-1] if stack else None

    # 约束位置：<> 内 / 类型标注后 / is 后
    in_constraint = constraint_depth > 0 or prev_type is _RAW.COLON or (prev is not None and prev.raw == 'is')
    # 调用名优先于约束位置：each(str) 的 each 是函数，参数 str 才是类型
    if nxt_type is _RAW.LPAREN:
        return 'function' if raw in _REGISTRY_NAMES else 'class'
    if in_constraint:
        return 'type' if raw in _REGISTRY_NAMES else 'class'
    # 字段名 / 命名参数：后接 = 或 :
    if nxt_type in (_RAW.EQUALS, _RAW.COLON):
        return 'parameter' if top in ('call', 'config') else 'property'
    # 上下文关键字（import / as / is）
    if raw in _CONTEXTUAL_KEYWORDS:
        return 'keyword'
    # $ 引用
    if prev_type is _RAW.DOLLAR:
        return 'variable'
    # 模板定义名（~Name）
    if prev_type is _RAW.TILDE:
        return 'class'
    # $x as type / 导入别名
    if prev is not None and prev.raw == 'as':
        if raw in _CAST_TYPE_NAMES:
            return 'type'
        return 'class' if bang == BangKeyword.FROM else 'variable'
    # JSON path 键
    if prev_type is _RAW.DOT:
        return 'property'
    # 导入列表中的名字（!from → 模板类；!env / !file → 键名）
    if prev is not None and prev.raw == 'import':
        return 'class' if bang == BangKeyword.FROM else 'property'
    return 'variable'


def semantic_tokens(text: str, file_path: str) -> list[int]:
    """用 RawTokenizer 分词 + 语法上下文分类，输出 LSP semanticTokens 扁平数组。

    编码规则（LSP）：每 5 个数为 1 个令牌，位置为相对上一个令牌的增量：
    [deltaLine, deltaStartChar, length, tokenType, tokenModifiers]。
    位置与 length 均按 **UTF-16 单元**；跨行 token（多行字符串/多行注释）按行拆分。

    分类覆盖语言概念（模板 class / 约束 type / 约束调用 function / 命名参数 parameter /
    字段 property / $ 引用 variable / Bang 指令 keyword / ~ decorator），比只分
    variable/keyword 更接近 Python 的语义高亮。

    注释（`#` 单行、`#+...#-` 多行）被词法器跳过、不产生 token，这里单独扫描：
    排除字符串字面量内的 `#`，映射为 VS Code 标准 `comment` 类型（默认主题上灰色）。
    """
    file = MemFile(name=file_path, root_path=Path(file_path).parent, content=text)
    raw_tokens = [
        tok
        for tok in RawTokenizer(file=file, error_collector=DiagnosticCollector())
        if tok.type not in (_RAW.NEWLINE, _RAW.EOF)
    ]
    lines = text.splitlines()

    spans: list[tuple[int, int, int, int]] = []  # (line, char_u16, length, type_idx)
    string_ranges: list[tuple[int, int, int]] = []  # (line, cp_start, cp_end) 排除注释识别
    stack: list[str] = []  # 容器上下文：dict / array / call / config / constraint
    constraint_depth = 0
    bang: BangKeyword | None = None

    for i, tok in enumerate(raw_tokens):
        prev = raw_tokens[i - 1] if i > 0 else None
        nxt = raw_tokens[i + 1] if i + 1 < len(raw_tokens) else None

        # 关闭符号先出栈（分类不受影响：定界符固定为 operator）
        if tok.type in (_RAW.RBRACE, _RAW.RBRACKET, _RAW.RPAREN, _RAW.RANGLE):
            if tok.type is _RAW.RANGLE and constraint_depth > 0:
                constraint_depth -= 1
            if stack:
                stack.pop()

        type_name = _FIXED_SEMANTIC.get(tok.type)
        if tok.type is _RAW.IDENTIFIER:
            type_name = _classify_identifier(tok, prev, nxt, stack, constraint_depth, bang)
        elif tok.type is _RAW.STRING_IDENTIFIER:
            # 字符串标识符只能是字段名 / 命名参数
            type_name = 'parameter' if (stack and stack[-1] in ('call', 'config')) else 'property'
        if type_name is None:
            continue
        type_idx = _TOKEN_INDEX[type_name]

        start = tok.source.start
        raw = tok.raw
        # 跨行 token（多行字符串）：按行拆分为多个令牌，每个令牌限定单行
        parts = raw.split('\n')
        for part_index, part in enumerate(parts):
            if not part:
                continue  # 空片段（空行）无内容可高亮
            line = start.line - 1 + part_index
            line_text = lines[line] if 0 <= line < len(lines) else ''
            char = (start.col - 1) if part_index == 0 else 0
            char_u16 = utf16_prefix(line_text, char)
            spans.append((line, char_u16, utf16_len(part), type_idx))
            if tok.type in (_RAW.STRING, _RAW.MULTILINE_STRING, _RAW.PATH, _RAW.STRING_IDENTIFIER):
                string_ranges.append((line, char, char + len(part)))

        # 入栈（分类使用父容器，故放在分类之后）
        if tok.type is _RAW.LBRACE:
            stack.append('dict')
        elif tok.type is _RAW.LBRACKET:
            stack.append('array')
        elif tok.type is _RAW.LPAREN:
            is_config = (
                prev is not None and prev.type is _RAW.IDENTIFIER and i >= 2 and raw_tokens[i - 2].type is _RAW.TILDE
            )
            stack.append('config' if is_config else 'call')
        elif tok.type is _RAW.LANGLE:
            stack.append('constraint')
            constraint_depth += 1
        elif tok.type is _RAW.BANG_KEYWORD:
            bang = BangKeyword(tok.raw.removeprefix('!'))

    spans.extend(_comment_spans(lines, string_ranges))

    # 按位置排序（注释与普通 token 不重叠：`#` 不是合法 token 起始）
    spans.sort(key=lambda s: (s[0], s[1]))

    data: list[int] = []
    prev_line = 0
    prev_char = 0
    for line, char, length, type_idx in spans:
        delta_line = line - prev_line
        delta_char = char if delta_line > 0 else char - prev_char
        data.extend([delta_line, delta_char, length, type_idx, 0])
        prev_line = line
        prev_char = char
    return data


_COMMENT_IDX = _TOKEN_INDEX['comment']


def _comment_spans(lines: list[str], string_ranges: list[tuple[int, int, int]]) -> list[tuple[int, int, int, int]]:
    """识别单行 `#` 与多行 `#+...#-` 注释，返回 (line, char_u16, length, comment_idx)。

    排除字符串字面量内的 `#`（用 tokenizer 产出的字符串区间）；
    多行注释按行拆分为多个单行令牌（覆盖到结束标记末尾）。
    """
    per_line: dict[int, list[tuple[int, int]]] = {}
    for line, cs, ce in string_ranges:
        per_line.setdefault(line, []).append((cs, ce))

    spans: list[tuple[int, int, int, int]] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        ranges = sorted(per_line.get(i, []))
        # 找本行第一个非字符串内的 `#`
        col = 0
        start = -1
        while col < len(line):
            inside = False
            for cs, ce in ranges:
                if cs <= col < ce:
                    col = ce
                    inside = True
                    break
            if inside:
                continue
            if line[col] == '#':
                start = col
                break
            col += 1
        if start == -1:
            i += 1
            continue

        # 多行注释 `#+` ... `#-`
        if line.startswith('#+', start):
            end = line.find('#-', start + 2)
            if end != -1:
                j = end + 2
                while j < len(line) and line[j] == '-':
                    j += 1
                spans.append((i, utf16_prefix(line, start), utf16_len(line[start:j]), _COMMENT_IDX))
                i += 1
                continue
            # 跨行：本行剩余 + 后续行直到 `#-`
            spans.append((i, utf16_prefix(line, start), utf16_len(line[start:]), _COMMENT_IDX))
            i += 1
            while i < n:
                ln = lines[i]
                end = ln.find('#-')
                if end != -1:
                    j = end + 2
                    while j < len(ln) and ln[j] == '-':
                        j += 1
                    spans.append((i, 0, utf16_len(ln[:j]), _COMMENT_IDX))
                    i += 1
                    break
                spans.append((i, 0, utf16_len(ln), _COMMENT_IDX))
                i += 1
            continue

        # 单行注释：start 到行尾
        spans.append((i, utf16_prefix(line, start), utf16_len(line[start:]), _COMMENT_IDX))
        i += 1
    return spans


# ── 诊断 ──────────────────────────────────────────────


def _belongs_to_current_file(d: Any, file_path: str) -> bool:
    """该诊断是否属于当前文件（排除 ``!from`` / ``!file`` 导入文件的跨文件诊断）。

    判断依据：``source.file.name`` 是编译器的文件显示名——当前文件 = ``compile_source``
    传入的 ``file_path``（MemFile.name），导入文件 = 磁盘路径（DiskFile.name）。
    无 ``source`` 或占位文件（``<unknown>``，错误恢复/合成 token）视为当前编译主
    文件产出（``d.path`` 是字段路径如 ``bad.y``，**不能**用作文件归属判断）。
    """
    if d.source is None:
        return True
    name = d.source.file.name
    if name == '<unknown>':
        return True
    return name == file_path


def analyze(text: str, file_path: str, lang: str | None = None) -> list[dict[str, Any]]:
    """编译当前缓冲区，返回 LSP 诊断列表。

    用 ``compile_source``（内存源码）统一处理磁盘/脏缓冲区；
    ``SandboxConfig.full_access()`` 放行全部 env / 文件 / 模板导入（LSP 场景默认）。

    只发布**属于当前文件**的诊断：跨文件诊断（被 ``!from`` / ``!file`` 导入的
    其他文件的错误）不属于当前 uri，且其位置基于别的文件文本，若一并发布会
    被错误定位到当前文件上，故跳过。
    """
    result = compile_source(
        text,
        file_path=file_path,
        sandbox=SandboxConfig.full_access(),
        env=virtual_env(text),
        lang=lang,
    )
    lines = text.splitlines()
    diags: list[dict[str, Any]] = []
    for d in result.diagnostics:
        if not _belongs_to_current_file(d, file_path):
            continue
        rng = to_lsp_range(d.source, lines)
        if rng is None:
            # 编译器偶有诊断不带 source（如 dollar.undefined 只带 path），
            # 回退到文档开头，避免整个诊断被丢弃。
            rng = {'start': {'line': 0, 'character': 0}, 'end': {'line': 0, 'character': 0}}
        diags.append(
            {
                'range': rng,
                'severity': _SEVERITY_MAP.get(d.severity, 1),
                'code': d.code,
                'source': 'infd',
                'message': d.render(include_location=False),
                'data': d.to_dict(),
            }
        )
    return diags


def _document(text: str, file_path: str, sandbox: SandboxConfig | None = None) -> Any:
    """编译并返回 StdDocument（scope / templates 供补全、悬停、定义用）。

    ``sandbox`` 缺省用 development()（补全沿用）；hover 传 full_access()
    与 analyze 的授权一致（跨目录 !from / !file 也能解析）。
    """
    if sandbox is None:
        sandbox = SandboxConfig.development()
    return compile_source(text, file_path=file_path, sandbox=sandbox, env=virtual_env(text)).document


# ── 文本辅助 ──────────────────────────────────────────


def _quoted_identifier_span(line: str, cp: int) -> tuple[str, int, int] | None:
    """光标位于单引号标识符内 → (解码名, 含引号的起止码点)。"""
    i = 0
    while i < len(line):
        if line[i] != "'":
            i += 1
            continue
        start = i
        i += 1
        while i < len(line):
            ch = line[i]
            if ch == '\\':
                i += 2  # 跳过转义字符（含 \\'）
                continue
            if ch == "'":
                end = i + 1
                # 光标紧贴闭引号（如手敲完 ``''`` 后停在右侧）也算命中：否则补全
                # 不会替换整个引号 token，插入后会多出一个引号
                at_boundary = cp == end and (end >= len(line) or not (line[end].isalnum() or line[end] == '_'))
                if start <= cp < end or at_boundary:
                    raw = line[start:end]
                    value, ok = decode_string_identifier(raw)
                    return (value if ok else raw[1:-1], start, end)
                i = end
                break
            i += 1
        else:
            # 未闭合：只把「引号到光标」视为已输入部分——光标右侧内容（如尾括号）
            # 不属于替换范围，也不参与前缀过滤
            if start <= cp <= len(line):
                return line[start + 1 : cp], start, cp
            return None
    return None


def _lsp_range_at(line_no: int, start: int, end: int, line: str) -> dict[str, Any]:
    """行内码点区间 → LSP range（UTF-16）。"""
    return {
        'start': {'line': line_no, 'character': utf16_len(line[:start])},
        'end': {'line': line_no, 'character': utf16_len(line[:end])},
    }


def _word_span(text: str, position: dict[str, Any]) -> tuple[str, int, int]:
    """光标处（0-based UTF-16）的标识符 → (标识符, 行内码点起始, 行内码点结束)。

    单引号标识符作为整体返回（span 含引号）：否则客户端只能看到 ``\\w+`` 片段
    （如 ``'a-v'`` 只能取到 ``v``），悬停高亮与补全过滤都会错。
    """
    line_no = int(position.get('line', 0))
    char = int(position.get('character', 0))
    lines = text.splitlines()
    if line_no < 0 or line_no >= len(lines):
        return '', 0, 0
    line = lines[line_no]
    cp = utf16_to_cp(line, char)
    cp = min(cp, len(line))
    quoted = _quoted_identifier_span(line, cp)
    if quoted is not None:
        return quoted
    start = cp
    end = cp
    while start > 0 and (line[start - 1].isalnum() or line[start - 1] == '_'):
        start -= 1
    while end < len(line) and (line[end].isalnum() or line[end] == '_'):
        end += 1
    return line[start:end], start, end


def _bang_prefix_at(text: str, position: dict[str, Any]) -> str | None:
    """光标处形如 ``!ass`` 的 Bang 关键字前缀；不以 ``!`` 起始则 None。"""
    line_no = int(position.get('line', 0))
    char = int(position.get('character', 0))
    lines = text.splitlines()
    if line_no < 0 or line_no >= len(lines):
        return None
    line = lines[line_no]
    cp = min(utf16_to_cp(line, char), len(line))
    start = cp
    while start > 0 and (line[start - 1].isalnum() or line[start - 1] == '_'):
        start -= 1
    bang = start - 1
    if bang >= 0 and line[bang] == '!':
        # 排除约束后缀 `int!`：`!` 前是标识符字符时不是 Bang 语句起点
        if bang == 0 or not (line[bang - 1].isalnum() or line[bang - 1] == '_'):
            return line[bang:cp]
    return None


def _dollar_prefix_at(text: str, position: dict[str, Any]) -> str | None:
    """光标处形如 ``$scr`` 的命名空间引用前缀；不在 ``$`` 名内则 None。

    只认 **紧贴光标标识符** 的 ``$``：同一行前面出现过 ``$`` 不代表光标仍
    在引用里。否则 ``!assert $script is st`` 的 ``st`` 也会被当成命名空间
    前缀，约束补全全被吞掉。
    """
    line_no = int(position.get('line', 0))
    char = int(position.get('character', 0))
    lines = text.splitlines()
    if line_no < 0 or line_no >= len(lines):
        return None
    line = lines[line_no]
    cp = min(utf16_to_cp(line, char), len(line))
    start = cp
    while start > 0 and (line[start - 1].isalnum() or line[start - 1] == '_'):
        start -= 1
    if start > 0 and line[start - 1] == '$':
        return line[start:cp]
    return None


def _namespace_names(text: str, file_path: str) -> set[str]:
    """收集 !env / !file / !var 导入的可见名（$ 引用补全候选）。"""
    file = MemFile(name=file_path, root_path=Path(file_path).parent, content=text)
    doc, _ = parse_source(file)
    names: set[str] = set()
    for stmt in doc.statements:
        if isinstance(stmt, EnvImportStmt):
            for item in stmt.items:
                names.add(item.alias or item.name)
        elif isinstance(stmt, FileImportStmt):
            for item in stmt.imports:
                names.add(item.alias)
        elif isinstance(stmt, VarStmt):  # !var 注入 $ 空间别名
            names.add(stmt.alias)
    return names


# ── 模板字段补全（光标在 TemplateName(...) 参数内 → 提示字段名）────


def _template_call_at(
    text: str,
    file_path: str,
    position: dict[str, Any],
    doc: Any | None = None,
    known: set[str] | None = None,
) -> TemplateCallValue | None:
    """返回覆盖光标位置的模板调用（嵌套时取最内层），无则 None。

    ``doc``：可传入已解析的 Document 避免重复 parse（hover 复用）。
    ``known``：可见模板名集合；传入时**跳过名字不在其中的调用**——部分输入的
    字段名（如 ``Server(\n na`` 里的 ``na``）会被解析器当成伪嵌套模板调用，
    跳过它才能定位到真正的 ``Server(...)``。缺省 None 时保持原行为（取最内层）。
    """
    if doc is None:
        file = MemFile(name=file_path, root_path=Path(file_path).parent, content=text)
        doc, _ = parse_source(file)
    cursor = _pos_index(text, position)
    best: TemplateCallValue | None = None
    best_size = 1 << 60

    def visit(v: Any) -> None:
        nonlocal best, best_size
        if isinstance(v, TemplateCallValue):
            s = v.source
            if s.start.index <= cursor <= s.end.index:
                if known is None or v.template_name in known:
                    size = s.end.index - s.start.index
                    if size < best_size:
                        best = v
                        best_size = size
            for a in v.positional_args:
                visit(a)
            for a in v.named_args:
                visit(a.value)  # NamedArg / UnpackValue 均带 .value
        elif isinstance(v, UnpackValue):
            visit(v.value)
        elif isinstance(v, ArrayValue):
            for e in v.elements:
                visit(e)
        elif isinstance(v, DictValue):
            for item in v.items:
                if isinstance(item, Field):
                    visit(item.value)
                else:  # UnpackValue
                    visit(item)
        elif isinstance(v, NamedArg):
            visit(v.value)

    for stmt in doc.statements:
        if isinstance(stmt, Field):
            visit(stmt.value)
    return best


def _pos_index(text: str, position: dict[str, Any]) -> int:
    """LSP 位置（0-based, UTF-16）→ 码点 index（与 tokenizer SourceInfo.index 对齐）。"""
    lines = text.split('\n')
    line_no = int(position.get('line', 0))
    char = int(position.get('character', 0))
    index = 0
    for i, ln in enumerate(lines):
        if i == line_no:
            index += utf16_to_cp(ln, char)
            break
        index += len(ln) + 1  # +1 = 换行符
    return index


def _constraint_text(c: Any) -> str:
    """约束 → 文本（如 int / range(1, 10) / ?）；解析失败节点→ ``<错误>``。"""
    if isinstance(c, ConstraintIdent):
        return c.name
    if isinstance(c, ConstraintCall):
        args = ', '.join(_constraint_text(a) for a in c.arguments)
        return f'{c.name}({args})'
    if isinstance(c, ConstraintLiteral):
        tok = c.value.value
        if isinstance(tok, NoexistToken):
            return 'noexist'
        if isinstance(tok, NullToken):
            return 'null'
        return str(tok.value)
    if isinstance(c, ErrorConstraint):
        return '<错误>'
    return '?'


def _template_field_items(tpl: TemplateDef) -> list[dict[str, Any]]:
    """模板字段 → 补全项（``name = `` 形式，带 必填/可选 + 类型）。

    名字用 canonical 拼写插入：无法裸写的字段（如 ``test-1``）自动带单引号；
    ``filterText`` 保留裸名，输入 ``te`` 也能匹配。
    """
    items: list[dict[str, Any]] = []
    for f in tpl.fields:
        required = '必填' if f.default_value is None else '可选'
        type_text = _constraint_list_text(f.constraints)
        spelling = render_identifier(f.name)
        doc_lines = [f'**`{spelling}`** — 模板字段（{required}）', '', f'- 类型: `{type_text}`']
        if f.default_value is not None:
            doc_lines.append('- 默认值: 省略时使用模板默认值')
        items.append(
            {
                'label': spelling,
                'kind': 13,  # Property
                'detail': f'模板字段·{required}·{type_text}',
                'insertText': f'{spelling} = ',
                'filterText': f.name,
                'documentation': {'kind': 'markdown', 'value': '\n'.join(doc_lines)},
            }
        )
    return items


def completion_items(text: str, file_path: str, position: dict[str, Any]) -> list[dict[str, Any]]:
    """返回补全项：命名空间（$ 触发）/ 内置约束 / 模板 / 关键字。"""
    lines = text.splitlines()
    line_no = int(position.get('line', 0))
    line_text = lines[line_no] if 0 <= line_no < len(lines) else ''

    # 光标前紧贴 `$`（或 `$` 后已输入部分名字）→ 命名空间引用补全
    dollar_prefix = _dollar_prefix_at(text, position)
    if dollar_prefix is not None:
        return [
            {'label': name, 'kind': 6, 'detail': '命名空间引用（$）', 'insertText': name}
            for name in sorted(_namespace_names(text, file_path))
            if name.startswith(dollar_prefix)
        ]

    word, word_start, word_end = _word_span(text, position)
    bang_prefix = _bang_prefix_at(text, position)

    # 模板调用参数内 → 补全该模板的字段名（最高优先级）
    doc = _document(text, file_path)
    call = _template_call_at(text, file_path, position, known=set(doc.scope))
    if call is not None:
        key = doc.scope.get(call.template_name)
        if key is not None:
            tpl = doc.templates.get(key)
            if tpl is not None:
                fields = _template_field_items(tpl)
                # 已用参数名不再提示（避免重复填写）
                used = {a.name for a in call.named_args if isinstance(a, NamedArg)}
                fields = [it for it in fields if it['filterText'] not in used]
                if word:
                    fields = [it for it in fields if it['filterText'].startswith(word)]
                # 引号内输入时客户端的匹配文本带引号 → 换用 canonical 拼写，否则会被过滤掉
                in_quotes = word_start < word_end and line_text[word_start] == "'"
                if in_quotes:
                    fields = [{**it, 'filterText': it['label']} for it in fields]
                if word_end > word_start:
                    # 用 textEdit 替换整个光标词/引号标识符，避免插入后变成 ''test-1''
                    edit_range = _lsp_range_at(line_no, word_start, word_end, line_text)
                    fields = [{**it, 'textEdit': {'range': edit_range, 'newText': it['insertText']}} for it in fields]
                return fields

    items: list[dict[str, Any]] = []

    for name in _REGISTRY.names:
        entry = _REGISTRY.lookup(name)
        items.append(
            {
                'label': name,
                'kind': 10,  # Function
                'detail': '内置约束',
                'documentation': {'kind': 'markdown', 'value': entry.description if entry else ''},
            }
        )

    for visible in doc.scope:  # 当前文件可见模板名（含 !from 导入）
        items.append(
            {
                'label': visible,
                'kind': 7,  # Class
                'detail': '模板',
                'documentation': {'kind': 'markdown', 'value': f'模板 `~{visible}`'},
            }
        )

    for label, desc in LANGUAGE_KEYWORDS:
        items.append(
            {'label': label, 'kind': 14, 'detail': '关键字', 'documentation': {'kind': 'markdown', 'value': desc}}
        )

    if bang_prefix is not None:
        items = [it for it in items if it['label'].startswith(bang_prefix)]
        # ``!`` 已由用户输入（且是触发字符）：只插入关键字名，匹配文本也用裸名。
        # 否则接受 ``!assert`` 会在已有的 ``!`` 后面拼成 ``!!assert``
        items = [{**it, 'filterText': it['label'][1:], 'insertText': it['label'][1:]} for it in items]
    elif word:
        items = [it for it in items if it['label'].startswith(word)]
    return items


def _constraint_list_text(constraints: Constraints | None) -> str:
    """约束列表 → 展示文本（``?`` 表示无约束）。"""
    if constraints is None or not constraints.constraints:
        return '?'
    return ', '.join(_constraint_text(c) for c in constraints.constraints)


def _statement_name_range(source: SourceRange, lines: list[str], *, after_tilde: bool) -> dict[str, Any]:
    """语句名字的 LSP range（``selectionRange``）：跳过 ``~``/空白，支持引号标识符。"""
    line_no = source.start.line - 1
    line = lines[line_no] if 0 <= line_no < len(lines) else ''
    i = max(source.start.col - 1, 0)
    if after_tilde and i < len(line) and line[i] == '~':
        i += 1
    while i < len(line) and line[i] in ' \t':
        i += 1
    if i < len(line) and line[i] == "'":
        span = _quoted_identifier_span(line, i)
        end = span[2] if span is not None else min(i + 1, len(line))
    else:
        end = i
        while end < len(line) and (line[end].isalnum() or line[end] == '_'):
            end += 1
    return _lsp_range_at(line_no, i, end, line)


def _template_signature(tpl: TemplateDef) -> str:
    """模板签名（面包屑 / Outline 的 detail）：``~Name(config) { field: type, ... }``。"""
    fields = ', '.join(f'{render_identifier(f.name)}: {_constraint_list_text(f.constraints)}' for f in tpl.fields)
    head = f'~{tpl.name}{tpl.config.canonical()}'
    return f'{head} {{ {fields} }}' if fields else f'{head} {{}}'


def _preview_inline(value: Any, depth: int = 0) -> str:
    """值 → 单行预览（Outline / 面包屑 detail，不追求完整恢复）。"""
    if isinstance(value, LiteralValue):
        return value.canonical()
    if isinstance(value, DollarValue):
        return value.canonical()
    if isinstance(value, TemplateCallValue):
        return f'{value.template_name}(…)'
    if isinstance(value, UnpackValue):
        return ('**' if value.double else '*') + _preview_inline(value.value, depth + 1)
    if isinstance(value, DictValue):
        if depth >= 2:
            return '{…}'
        fields = [item for item in value.items if isinstance(item, Field)]
        names = [render_identifier(f.name) for f in fields[:3]]
        if not names:
            return '{ }'
        return '{ ' + ', '.join(names) + (', …' if len(fields) > 3 else '') + ' }'
    if isinstance(value, ArrayValue):
        if depth >= 2:
            return '[…]'
        parts = [_preview_inline(e, depth + 1) for e in value.elements[:3]]
        more = ', …' if len(value.elements) > 3 else ''
        return '[' + ', '.join(parts) + more + ']'
    if isinstance(value, ErrorValue):
        return '<错误>'
    return '?'


def _value_preview_text(value: Any, limit: int = 32) -> str:
    """值预览（超长截断），作为无类型字段 / 无名元素的 detail。"""
    text = _preview_inline(value)
    return text if len(text) <= limit else text[: limit - 1] + '…'


def _field_symbol(
    name: str,
    constraints: Constraints | None,
    source: SourceRange,
    lines: list[str],
    value: Any | None = None,
) -> dict[str, Any] | None:
    """字段 → DocumentSymbol（Property）；位置无法转换时返回 None。

    detail：有类型约束显示类型，否则显示值预览（避免出现无意义的 ``?``）。
    """
    rng = to_lsp_range(source, lines)
    if rng is None:
        return None
    if constraints is not None and constraints.constraints:
        detail = _constraint_list_text(constraints)
    else:
        detail = _value_preview_text(value) if value is not None else ''
    return {
        'name': render_identifier(name) if name else _EMPTY_SYMBOL_NAME,
        'kind': 13,
        'detail': detail,
        'range': rng,
        'selectionRange': _statement_name_range(source, lines, after_tilde=False),
    }


_MAX_SYMBOL_DEPTH = 20
"""值树递归生成子符号的深度上限（防御病态嵌套）。"""


def _merged_span(start: SourceRange, end: SourceRange) -> SourceRange:
    """两个范围合并（命名参数符号：从名字到值末尾）。"""
    return SourceRange(file=start.file, start=start.start, end=end.end)


def _named_arg_symbol(arg: NamedArg, lines: list[str], depth: int) -> dict[str, Any] | None:
    """模板调用命名参数 → DocumentSymbol（面包屑可进入参数值的嵌套结构）。"""
    rng = to_lsp_range(_merged_span(arg.source, arg.value.source), lines)
    if rng is None:
        return None
    symbol: dict[str, Any] = {
        'name': render_identifier(arg.name) if arg.name else _EMPTY_SYMBOL_NAME,
        'kind': 13,
        'detail': _value_preview_text(arg.value),
        'range': rng,
        'selectionRange': _statement_name_range(arg.source, lines, after_tilde=False),
    }
    children = _value_children(arg.value, lines, depth + 1)
    if children:
        symbol['children'] = children
    return symbol


def _index_symbol(index: int, value: Any, lines: list[str], depth: int) -> dict[str, Any] | None:
    """数组元素 / 位置参数 → DocumentSymbol（``[i]``，无名位置的面包屑锚点）。"""
    rng = to_lsp_range(value.source, lines)
    if rng is None:
        return None
    symbol: dict[str, Any] = {
        'name': f'[{index}]',
        'kind': 13,
        'detail': _value_preview_text(value),
        'range': rng,
        'selectionRange': rng,
    }
    children = _value_children(value, lines, depth + 1)
    if children:
        symbol['children'] = children
    return symbol


def _unpack_symbol(index: int, unpack: UnpackValue, lines: list[str]) -> dict[str, Any] | None:
    """解包项 → 区间符号 ``[i..]``（源码序号起点；展开宽度不可静态确定）。"""
    rng = to_lsp_range(unpack.source, lines)
    if rng is None:
        return None
    return {
        'name': f'[{index}..]',
        'kind': 13,
        'detail': ('**' if unpack.double else '*') + _value_preview_text(unpack.value),
        'range': rng,
        'selectionRange': rng,
    }


def _value_children(value: Any, lines: list[str], depth: int) -> list[dict[str, Any]]:
    """值的嵌套子符号：dict 字段 / 数组元素 / 模板调用参数（递归）。"""
    if depth > _MAX_SYMBOL_DEPTH:
        return []
    children: list[dict[str, Any]] = []
    if isinstance(value, DictValue):
        for item in value.items:
            if not isinstance(item, Field):
                continue
            symbol = _field_symbol(item.name, item.constraints, item.source, lines, item.value)
            if symbol is None:
                continue
            nested = _value_children(item.value, lines, depth + 1)
            if nested:
                symbol['children'] = nested
            children.append(symbol)
    elif isinstance(value, ArrayValue):
        for index, element in enumerate(value.elements):
            if isinstance(element, UnpackValue):
                symbol = _unpack_symbol(index, element, lines)
            else:
                symbol = _index_symbol(index, element, lines, depth)
            if symbol is not None:
                children.append(symbol)
    elif isinstance(value, TemplateCallValue):
        for index, arg in enumerate(value.positional_args):
            if isinstance(arg, UnpackValue):
                symbol = _unpack_symbol(index, arg, lines)
            else:
                symbol = _index_symbol(index, arg, lines, depth)
            if symbol is not None:
                children.append(symbol)
        for arg in value.named_args:
            if not isinstance(arg, NamedArg):
                continue
            symbol = _named_arg_symbol(arg, lines, depth)
            if symbol is not None:
                children.append(symbol)
    return children


def _string_ranges(text: str, file_path: str) -> list[tuple[int, int, int]]:
    """字符串类 token 的行内码点区间（块注释扫描时排除其中的 ``#``）。"""
    file = MemFile(name=file_path, root_path=Path(file_path).parent, content=text)
    tokens = RawTokenizer(file=file, error_collector=DiagnosticCollector())
    ranges: list[tuple[int, int, int]] = []
    for tok in tokens:
        if tok.type not in (_RAW.STRING, _RAW.MULTILINE_STRING, _RAW.PATH, _RAW.STRING_IDENTIFIER):
            continue
        start = tok.source.start
        for i, part in enumerate(tok.raw.split('\n')):
            if not part:
                continue
            char = (start.col - 1) if i == 0 else 0
            ranges.append((start.line - 1 + i, char, char + len(part)))
    return ranges


def _block_comment_folds(lines: list[str], string_ranges: list[tuple[int, int, int]]) -> list[tuple[int, int]]:
    """多行块注释 ``#+ ... #-`` 的 (起行, 止行)，排除字符串内的 ``#``。"""
    per_line: dict[int, list[tuple[int, int]]] = {}
    for line, cs, ce in string_ranges:
        per_line.setdefault(line, []).append((cs, ce))

    def first_hash(line_no: int) -> int:
        line = lines[line_no]
        ranges = sorted(per_line.get(line_no, []))
        col = 0
        while col < len(line):
            if any(cs <= col < ce for cs, ce in ranges):
                col = next(ce for cs, ce in ranges if cs <= col < ce)
                continue
            if line[col] == '#':
                return col
            col += 1
        return -1

    folds: list[tuple[int, int]] = []
    start: int | None = None
    for line_no, line in enumerate(lines):
        col = first_hash(line_no)
        if col == -1:
            continue
        if start is None and line.startswith('#+', col):
            if line.find('#-', col + 2) == -1:
                start = line_no
        elif start is not None and line.startswith('#-', col):
            if line_no > start:
                folds.append((start, line_no))
            start = None
    return folds


def folding_ranges(text: str, file_path: str) -> list[dict[str, Any]]:
    """LSP foldingRange：AST 结构区域 + 多行块注释。

    结构区域来自模板定义 / dict / 数组 / 多行模板调用，不依赖缩进——不提供
    provider 时客户端会按缩进猜，花括号语言的折叠边界会与语法结构不一致。
    """
    file = MemFile(name=file_path, root_path=Path(file_path).parent, content=text)
    doc, _ = parse_source(file)
    lines = text.splitlines()
    ranges: list[dict[str, Any]] = []

    def add(start_line: int, end_line: int, kind: str) -> None:
        if 0 <= start_line < end_line < len(lines):
            ranges.append({'startLine': start_line, 'endLine': end_line, 'kind': kind})

    for stmt in doc.statements:
        for node in walk(stmt):
            if isinstance(node, (TemplateDef, DictValue, ArrayValue, TemplateCallValue)):
                add(node.source.start.line - 1, node.source.end.line - 1, 'region')

    for start_line, end_line in _block_comment_folds(lines, _string_ranges(text, file_path)):
        add(start_line, end_line, 'comment')

    ranges.sort(key=lambda r: (r['startLine'], r['endLine']))
    return ranges


def document_symbols(text: str, file_path: str) -> list[dict[str, Any]]:
    """文档大纲：模板定义（Class，含字段 children）+ 顶层字段（Property）。

    层级化供面包屑 / sticky scroll 使用：模板 ``range`` 覆盖整个定义体，
    ``selectionRange`` 指向名字；``detail`` 为完整签名。

    LSP 客户端要求 ``DocumentSymbol.name`` 非空；错误恢复产生的空名字（如空标识符
    ``'' = 1``）用 ``<empty>`` 占位——保留大纲条目与位置，避免静默丢失。
    """
    file = MemFile(name=file_path, root_path=Path(file_path).parent, content=text)
    doc, _ = parse_source(file)
    lines = text.splitlines()
    symbols: list[dict[str, Any]] = []
    for stmt in doc.statements:
        if isinstance(stmt, TemplateDef):
            rng = to_lsp_range(stmt.source, lines)
            if rng is None:
                continue
            children: list[dict[str, Any]] = []
            for tf in stmt.fields:
                child = _field_symbol(tf.name, tf.constraints, tf.source, lines, tf.default_value)
                if child is not None:
                    children.append(child)
            symbols.append(
                {
                    'name': f'~{stmt.name or _EMPTY_SYMBOL_NAME}',
                    'detail': _template_signature(stmt),
                    'kind': 5,  # Class
                    'range': rng,
                    'selectionRange': _statement_name_range(stmt.source, lines, after_tilde=True),
                    'children': children,
                }
            )
        elif isinstance(stmt, Field):
            symbol = _field_symbol(stmt.name, stmt.constraints, stmt.source, lines, stmt.value)
            if symbol is not None:
                children = _value_children(stmt.value, lines, 0)
                if children:
                    symbol['children'] = children
                symbols.append(symbol)
    return symbols


# ── 悬停 ──────────────────────────────────────────────


_NOEXIST = object()
"""noexist 哨兵：结构骨架预览中跳过（键不出现）。"""

_PREVIEW_EMIT = EmitConfig(full_float=True, full_path=True, keep_noexist=True)
"""预览 JSON 配置：保留完整转化语义。

``full_float`` / ``full_path`` / ``keep_noexist`` 让 Decimal / PurePosixPath /
noexist 以 ``{"__type__": ...}`` 自描述标记输出，而不是退化为 float / 字符串 /
静默丢弃——预览与编译器真实产物一致。"""


def _preview_json(value: Any) -> str:
    """预览 JSON 文本：走 emit 层（含 std 输入），保留完整转化语义。

    ``value`` 可为 StdValue（编译产物）或已投影的 Python 值（结构骨架）。
    """
    return dump_to_json(value, config=_PREVIEW_EMIT)


def _template_preview(tpl: TemplateDef) -> str:
    """模板字段默认值 → 结构骨架 JSON（hover 预览，**不实例化**）。

    - 必填字段（无默认值）→ ``<必填>`` 占位
    - ``noexist`` 默认字段跳过（键不出现）
    - 嵌套模板调用只显示 ``Name(…)``、``$`` 引用保留、解包用 ``…`` 占位
      （要看真实结果请悬停到实例化字段上，见 ``_field_preview``）
    - 字面量取值的类型语义由 emit 保留（Decimal / path 自描述标记）
    """
    obj: dict[str, Any] = {}
    for f in tpl.fields:
        if f.default_value is None:
            obj[f.name] = '<必填>'
            continue
        rv = _structure_value(f.default_value)
        if rv is _NOEXIST:
            continue
        obj[f.name] = rv
    return _preview_json(obj)


def _structure_value(v: Any) -> Any:
    """AST 值 → 结构骨架（模板预览用）：不实例化模板调用、不求值 ``$``、不解包。

    容错：解析失败节点（``ErrorValue``）→ ``<错误>`` 占位，不中断预览。
    """
    if v is None:
        return None
    if isinstance(v, ErrorValue):
        return '<错误>'
    if isinstance(v, LiteralValue):
        tok = v.value
        if isinstance(tok, NullToken):
            return None
        if isinstance(tok, NoexistToken):
            return _NOEXIST
        return tok.value
    if isinstance(v, ArrayValue):
        items: list[Any] = []
        for e in v.elements:
            rv = _structure_value(e)
            if rv is not _NOEXIST:
                items.append(rv)
        return items
    if isinstance(v, DictValue):
        obj: dict[str, Any] = {}
        for item in v.items:
            if isinstance(item, UnpackValue):  # **expr 解包项：结构上只占位
                obj['**…' if item.double else '*…'] = '…'
                continue
            rv = _structure_value(item.value)
            if rv is not _NOEXIST:
                obj[item.name] = rv
        return obj
    if isinstance(v, DollarValue):
        return f'${v.name}' if v.type_cast is None else f'${v.name} as {v.type_cast}'
    if isinstance(v, UnpackValue):
        return ('**' if v.double else '*') + '…'
    if isinstance(v, TemplateCallValue):
        return f'{v.template_name}(…)'
    return '…'


# ── 悬停增强：$ 命名空间 / 编译产物树节点定位 ─────────────


def _namespaces(text: str, file_path: str) -> dict[str, StdValue]:
    """解析当前文件的 ``$`` 命名空间（!env / !file / !var 别名 → 值）。

    复用公开的 resolver + builder（与 pipeline Phase 1/2a 一致）：resolver 只含
    !env/!file，!var 由 builder 求值后写入同一 scope.namespaces。
    hover 尽力而为：任何失败（沙盒 / 文件 IO / 导入错误）→ 空 dict。
    """
    file = MemFile(name=file_path, root_path=Path(file_path).parent, content=text)
    collector = DiagnosticCollector()
    doc, _ = parse_source(file, collector)
    try:
        config = replace(SandboxConfig.full_access(), env=virtual_env(text))
        resolver = TemplateGraphResolver(
            registry=None,
            import_resolver=ImportResolver(sandbox=Sandbox(config=config, base_dir=file.root_path)),
            schema=None,
        )
        context = resolver.resolve(doc, file, collector)
        AstBuilder().build(doc, context, collector)
        return dict(context.root_scope.namespaces)
    except Exception:  # noqa: BLE001 - hover 尽力而为，不崩溃
        return {}


def _visit_std_tree(root: Any, fn: Callable[[Any], None]) -> None:
    """遍历编译产物树（StdValue + StdField），对每个节点调 fn(node)。"""

    def visit(v: Any) -> None:
        fn(v)
        if isinstance(v, StdObject):
            for f in v.fields:
                visit(f)
                if f.value is not None:
                    visit(f.value)
        elif isinstance(v, StdArray):
            for e in v.elements:
                visit(e)

    visit(root)


def _node_at(root: Any, cursor: int, file_path: str) -> Any:
    """编译产物树中覆盖光标（码点 index）的最深 StdNode（仅当前文件 source）。"""
    best: Any = None
    best_size = 1 << 60

    def consider(v: Any) -> None:
        nonlocal best, best_size
        src = getattr(v, 'source', None)
        if (
            src is not None
            and src.file.name == file_path
            and src.end.index > src.start.index
            and src.start.index <= cursor <= src.end.index
        ):
            size = src.end.index - src.start.index
            if size < best_size:
                best = v
                best_size = size

    _visit_std_tree(root, consider)
    return best


def _value_at_source(root: Any, start_index: int, file_path: str) -> Any:
    """编译树中 source 起点 == start_index 的最深**值节点**（模板参数值定位）。

    只匹配值节点（StdLiteral / StdObject / StdArray），跳过 StdField 包装——
    实例字段的 source 与值表达式起点相同，取字段会给预览层喂非值对象。
    """
    best: Any = None
    best_size = 1 << 60

    def consider(v: Any) -> None:
        nonlocal best, best_size
        if isinstance(v, StdField):
            return
        src = getattr(v, 'source', None)
        if src is not None and src.file.name == file_path and src.start.index == start_index:
            size = src.end.index - src.start.index
            if size < best_size:
                best = v
                best_size = size

    _visit_std_tree(root, consider)
    return best


def _named_arg_at(call: TemplateCallValue, cursor: int, word: str) -> NamedArg | None:
    """模板调用中光标所在命名参数槽（且名字 == word）。"""
    for a in call.named_args:
        if isinstance(a, NamedArg) and a.name == word and a.source.start.index <= cursor <= a.source.end.index:
            return a
    return None


def _namespace_key_at(doc: Any, cursor: int, word: str) -> str | None:
    """光标所在导入项的名字/别名 → 命名空间键（!env/!file/!var），无则 None。"""
    for stmt in doc.statements:
        if isinstance(stmt, EnvImportStmt):
            for item in stmt.items:
                if item.source.start.index <= cursor <= item.source.end.index and word in (item.alias, item.name):
                    return item.alias or item.name
        elif isinstance(stmt, FileImportStmt):
            for item in stmt.imports:
                if item.source.start.index <= cursor <= item.source.end.index and word == item.alias:
                    return item.alias
        elif isinstance(stmt, VarStmt):
            if stmt.source.start.index <= cursor <= stmt.source.end.index and word == stmt.alias:
                return stmt.alias
    return None


def _template_field_at(doc: Any, cursor: int) -> tuple[TemplateDef | None, TemplateField | None]:
    """光标在 ~Template 定义内 → (TemplateDef, 该处字段 | None)。"""
    for stmt in doc.statements:
        if isinstance(stmt, TemplateDef) and stmt.source.start.index <= cursor <= stmt.source.end.index:
            for f in stmt.fields:
                if f.source.start.index <= cursor <= f.source.end.index:
                    return stmt, f
            return stmt, None
    return None, None


def _std_preview(value: Any) -> str:
    """StdValue → 预览 JSON（emit 完整语义：decimal / path / noexist 自描述标记）。"""
    return _preview_json(value)


def _value_hover(word: str, title: str, value: Any) -> dict[str, Any]:
    """值悬停：标题 + JSON 预览。"""
    return {
        'contents': {
            'kind': 'markdown',
            'value': f'**`{word}`** — {title}\n\n```json\n{_std_preview(value)}\n```',
        }
    }


def _template_skeleton_hover(tpl: TemplateDef) -> str:
    """模板 → 结构骨架 markdown（~名 + description + JSON 骨架 + 字段列表）。"""
    md = [f'**`~{tpl.name}`** — 模板', '']
    desc = tpl.config.description
    if desc:
        md.append(desc)
        md.append('')
    preview = _template_preview(tpl)
    if preview != '{}':
        md.append('```json')
        md.append(preview)
        md.append('```')
        md.append('')
    for f in tpl.fields:
        required = '必填' if f.default_value is None else '可选'
        md.append(f'- `{f.name}`（{required}）')
    return '\n'.join(md)


def _node_hover(node: Any, word: str) -> dict[str, Any] | None:
    """编译产物节点 → 悬停。

    字段标题用 ``node.name``（而非光标词）：字符串标识符含 ``-`` / ``@`` 等字符时，
    光标词只是名字的一个片段（如 ``'a-v'`` 里取到 ``v``）。
    """
    if isinstance(node, StdField):
        if node.value is None:
            return None
        return _value_hover(node.name, '字段值（编译结果）', node.value)
    if isinstance(node, StdObject):
        title = '模板实例（编译结果）' if node.template is not None else '对象值（编译结果）'
        return _value_hover(word, title, node)
    if isinstance(node, StdArray):
        return _value_hover(word, '数组值（编译结果）', node)
    if isinstance(node, StdLiteral):
        return _value_hover(word, '值（编译结果）', node)
    return None


def _hover_impl(text: str, file_path: str, position: dict[str, Any]) -> dict[str, Any] | None:
    """悬停：约束描述 / 字段与子字段 / 模板与实例 / 模板参数 / $ 变量 / 模板骨架。

    优先级：
    1. 内置约束（word 查注册表）
    2. ``$`` 引用调用点（光标前是 ``$``）→ 命名空间值
    3. ~模板定义内字段（类型 + 默认值）
    4. 模板调用命名参数名 → 该参数编译值
    5. 编译产物树节点定位（字段/子字段/模板实例/字面量/数组）——
       被实例化的模板：模板提示（骨架）在前 + 实例预览在后
    6. ``$`` 定义点（!env/!file/!var 的名字/别名）→ 命名空间值
    7. 模板名 → 结构骨架
    """
    word, start, _ = _word_span(text, position)
    if not word:
        return None
    lines = text.splitlines()
    line_no = int(position.get('line', 0))
    line_text = lines[line_no] if 0 <= line_no < len(lines) else ''

    # 1. 内置约束
    entry = _REGISTRY.lookup(word)
    if entry is not None:
        desc = entry.description or '（无描述）'
        return {'contents': {'kind': 'markdown', 'value': f'**`{word}`** — 内置约束\n\n{desc}'}}

    file = MemFile(name=file_path, root_path=Path(file_path).parent, content=text)
    ast, _ = parse_source(file)
    cursor = _pos_index(text, position)

    namespaces: dict[str, StdValue] | None = None

    def ns() -> dict[str, StdValue]:
        nonlocal namespaces
        if namespaces is None:
            namespaces = _namespaces(text, file_path)
        return namespaces

    # 2. $ 引用（调用点）
    if start > 0 and line_text[start - 1] == '$':
        value = ns().get(word)
        if value is not None:
            return _value_hover(f'${word}', '$ 变量（编译结果）', value)

    # 3. ~模板定义内字段（类型 + 默认值）
    _def_tpl, tf = _template_field_at(ast, cursor)
    if tf is not None:
        type_text = _constraint_list_text(tf.constraints)
        required = '必填' if tf.default_value is None else '可选'
        md = [f'**`{tf.name}`** — 模板字段（{required}）', '', f'- 类型: `{type_text}`']
        if tf.default_value is not None:
            rv = _structure_value(tf.default_value)
            if rv is _NOEXIST:
                md.append('- 默认值: `noexist`')
            else:
                md.append('- 默认值:')
                md.append('```json')
                md.append(_preview_json(rv))
                md.append('```')
        return {'contents': {'kind': 'markdown', 'value': '\n'.join(md)}}

    doc = _document(text, file_path, sandbox=SandboxConfig.full_access())

    # 4. 模板调用命名参数名 → 该参数编译值
    call = _template_call_at(text, file_path, position, doc=ast, known=set(doc.scope))
    if call is not None:
        arg = _named_arg_at(call, cursor, word)
        if arg is not None:
            value = _value_at_source(doc.root, arg.value.source.start.index, file_path)
            if value is not None:
                return _value_hover(arg.name, '模板参数（编译结果）', value)

    # 5. 编译产物树节点定位
    node = _node_at(doc.root, cursor, file_path)
    if node is not None:
        # 被实例化的模板：模板提示（骨架）在前，实例预览在后
        if isinstance(node, StdObject) and node.template is not None:
            tpl = doc.templates.get(node.template)
            if tpl is not None:
                skeleton = _template_skeleton_hover(tpl)
                instance = _value_hover(word, '模板实例（编译结果）', node)
                combined = f'{skeleton}\n\n---\n\n{instance["contents"]["value"]}'
                return {'contents': {'kind': 'markdown', 'value': combined}}
        hv = _node_hover(node, word)
        if hv is not None:
            return hv

    # 6. $ 定义点
    key = _namespace_key_at(ast, cursor, word)
    if key is not None:
        value = ns().get(key)
        if value is not None:
            return _value_hover(key, '$ 变量定义（编译结果）', value)

    # 7. 模板名 → 结构骨架
    tkey = doc.scope.get(word)
    if tkey is not None:
        tpl = doc.templates.get(tkey)
        if tpl is not None:
            return {'contents': {'kind': 'markdown', 'value': _template_skeleton_hover(tpl)}}
    return None


def hover(text: str, file_path: str, position: dict[str, Any]) -> dict[str, Any] | None:
    """悬停入口：附加 ``range``，让客户端高亮完整标识符（含单引号）。"""
    result = _hover_impl(text, file_path, position)
    if result is None:
        return None
    _, start, end = _word_span(text, position)
    if end > start:
        line_no = int(position.get('line', 0))
        lines = text.splitlines()
        line = lines[line_no] if 0 <= line_no < len(lines) else ''
        result['range'] = _lsp_range_at(line_no, start, end, line)
    return result


# ── 跳转到定义 ────────────────────────────────────────


def _lsp_location(text: str, source: SourceRange | None) -> dict[str, Any] | None:
    """SourceRange → LSP Location（None 表示无位置）。"""
    if source is None:
        return None
    lines = text.splitlines()
    rng = to_lsp_range(source, lines)
    if rng is None:
        return None
    return {'uri': _file_uri(source.file.name), 'range': rng}


def _file_uri(name: str) -> str:
    """编译器文件显示名 → file:// uri（导入文件的磁盘路径 / 当前文件路径）。"""
    import urllib.parse

    return 'file://' + urllib.parse.quote(name)


def _dollar_definition(doc: Any, word: str) -> SourceRange | None:
    """$ 引用 word → 定义它的导入语句（!env / !file / !var）SourceRange。"""
    for stmt in doc.statements:
        if isinstance(stmt, EnvImportStmt):
            for item in stmt.items:
                if (item.alias or item.name) == word:
                    return stmt.source
        elif isinstance(stmt, FileImportStmt):
            for item in stmt.imports:
                if item.alias == word:
                    return stmt.source
        elif isinstance(stmt, VarStmt):
            if stmt.alias == word:
                return stmt.source
    return None


def _template_definition(doc: Any, word: str) -> SourceRange | None:
    """可见模板名 word → 模板定义 SourceRange（含 !from 导入的外部模板）。"""
    key = doc.scope.get(word)
    if key is None:
        return None
    tpl = doc.templates.get(key)
    if tpl is None:
        return None
    return tpl.source


def definition(text: str, file_path: str, position: dict[str, Any]) -> dict[str, Any] | None:
    """跳转到定义：``$`` 引用 → 导入语句；模板名（调用 / ``!from`` 导入）→ 模板定义。"""
    word, start, _ = _word_span(text, position)
    if not word:
        return None
    lines = text.splitlines()
    line_no = int(position.get('line', 0))
    line_text = lines[line_no] if 0 <= line_no < len(lines) else ''

    file = MemFile(name=file_path, root_path=Path(file_path).parent, content=text)
    doc, _ = parse_source(file)

    # 1. `$` 引用 → 定义该名字的导入语句
    if start > 0 and line_text[start - 1] == '$':
        src = _dollar_definition(doc, word)
        return _lsp_location(text, src)

    # 2. 模板名（模板调用 / !from 导入项 / 其他引用）→ 模板定义
    compiled = _document(text, file_path)
    src = _template_definition(compiled, word)
    if src is not None:
        # 当前文件内定义的模板 → 直接映射到当前文本
        if src.file.name == file_path:
            return _lsp_location(text, src)
        # 跨文件（!from 导入）：返回定义所在文件的位置
        try:
            file_text = src.file.read() or ''
        except OSError:
            return None
        rng = to_lsp_range(src, file_text.splitlines())
        if rng is None:
            return None
        return {'uri': _file_uri(src.file.name), 'range': rng}
    return None
