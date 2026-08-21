"""tokenizer 模糊测试（自制轻量 fuzz，零依赖、确定性 seed）。

目标：验证 RawTokenizer + FinalTokenizer 对任意输入：
1. 不崩溃（任何输入都不抛异常）；
2. token 流总是以 EOF 终止（不无限循环）；
3. 所有诊断 code 均已注册且参数可渲染（无未知 code / 缺参）；
4. 产出的 raw 结构合法（直接校验错误恢复不变量不回归）：
   - STRING / MULTILINE_STRING：定界符闭合
   - INTEGER：int() 可解析
   - FLOAT：Decimal 可解析（或 nan / ±inf）
   - IDENTIFIER：符合标识符文法（+foo 之类已被拦截）

策略：
- 随机生成：从字符池（覆盖 tokenizer 全部边界字符）生成随机串；
- 种子变异：从真实/错误恢复案例种子集合做插入/删除/替换/截断。
"""

import random
import re
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

from infinity_data.infra.diagnostics import DiagnosticCollector, render_message
from infinity_data.infra.file import MemFile
from infinity_data.infra.location import SourceRange
from infinity_data.parser.parser import Parser
from infinity_data.tokenizer.finalizer import FinalTokenizer
from infinity_data.tokenizer.models.raw_tokens import RawToken, RawTokenType
from infinity_data.tokenizer.models.tokens import EofToken
from infinity_data.tokenizer.tokenizer import RawTokenizer

# 边界字符：tokenizer 全部关键分支 + 引号/单引号/方括号等（用户点名场景）
_BOUNDARY_CHARS: tuple[str, ...] = (
    '{',
    '}',
    '[',
    ']',
    '(',
    ')',
    '<',
    '>',
    '=',
    ':',
    ',',
    '~',
    '?',
    '$',
    '.',
    '\n',
    '"',
    "'",
    '`',
    '!',
    '#',
    '+',
    '-',
    'e',
    'E',
    '0',
    '5',
    '9',
    'a',
    'z',
    'A',
    'Z',
    '_',
    ' ',
    '\t',
    '\\',
    '\ufeff',
    '\x00',
    '\x1f',
    '\x7f',
    '\r',
)


def _build_char_pool() -> tuple[str, ...]:
    """候选字符池：可打印 ASCII + 常见 Unicode 中固定 seed 随机抽 100 个，合并边界字符。"""
    rng = random.Random(20260823)
    space = [chr(c) for c in range(32, 127)] + ['é', '中', '😀', '٣', '²', 'Ω', 'ß', 'ñ', '€', 'Ж']
    sampled = tuple(rng.choice(space) for _ in range(100))
    pool: list[str] = []
    seen: set[str] = set()
    for ch in sampled + _BOUNDARY_CHARS:
        if ch not in seen:
            seen.add(ch)
            pool.append(ch)
    return tuple(pool)


# 覆盖 tokenizer 全部关键分支 + 随机抽取字符的候选池（确定性 seed）
_CHARS: tuple[str, ...] = _build_char_pool()

# 真实语法 + 本会话全部错误恢复案例
_SEEDS: tuple[str, ...] = (
    'a = 1\n',
    'x = "hi"\n',
    'field: <int> = 10\n',
    '!env import X\n',
    '!file "a.infd" import Y\n',
    '!from "b.infd" import Z\n',
    'a = [1, 2, {3: 4}]\n',
    'x = `hello`\n',
    'x = 3.14e-2\n',
    'x = +inf\n',
    'x = nan\n',
    # 错误恢复案例
    'a = [1, 2\n',
    'x = "abc\n',
    'x = 5e+\n',
    'x = +\n',
    '!bad\n',
    '!envv import X\n',
    'a = (1]\n',
    'a = 1)\n',
    '#+unterminated',
    '`unterminated',
    'a = 42.\n',
    'x = +nan\n',
    'x = "a\\qb"\n',
)


def _assert_raw_valid(t: RawToken, src: str) -> None:
    """断言单个 token 的 raw 结构合法（错误恢复不变量）。"""
    if t.type is RawTokenType.STRING:
        assert t.raw.startswith('"') and t.raw.endswith('"'), f'字符串定界符未闭合: {t.raw!r} from {src!r}'
    elif t.type is RawTokenType.MULTILINE_STRING:
        assert t.raw.startswith('`') and t.raw.endswith('`'), f'多行字符串定界符未闭合: {t.raw!r} from {src!r}'
    elif t.type is RawTokenType.INTEGER:
        int(t.raw)  # 必须可解析
    elif t.type is RawTokenType.FLOAT:
        if t.raw not in ('nan', '+inf', '-inf'):
            Decimal(t.raw)  # 必须可解析
    elif t.type is RawTokenType.IDENTIFIER:
        assert re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', t.raw), f'非法标识符 raw: {t.raw!r} from {src!r}'


def _check_invariants(src: str) -> None:
    """对单个输入做词法 + 语法不变式校验（任何违反即测试失败）。"""
    col = DiagnosticCollector()
    file = MemFile(name='t.infd', root_path=Path('.'), content=src)

    raw_tokens = list(RawTokenizer(file=file, error_collector=col))
    assert raw_tokens and raw_tokens[-1].type is RawTokenType.EOF, f'非 EOF 终止: {src!r}'

    # 诊断均可渲染（code 已注册 + params 齐全）
    for d in col:
        render_message(d.code, d.params, location='x:1:1')

    # raw 结构合法
    for t in raw_tokens:
        _assert_raw_valid(t, src)

    # finalizer 不崩溃且 EOF 终止
    fcol = DiagnosticCollector()
    ftokens = list(FinalTokenizer(RawTokenizer(file=file, error_collector=fcol), error_collector=fcol))
    assert ftokens and isinstance(ftokens[-1], EofToken), f'finalizer 非 EOF 终止: {src!r}'

    # parser 不变量：不崩溃 + AST 所有 SourceRange 合法（不反转/不越界/file 正确）
    pcol = DiagnosticCollector()
    doc = Parser(FinalTokenizer(RawTokenizer(file=file, error_collector=pcol)), collector=pcol).parse()
    _assert_ranges_valid(doc, src, file)


def _assert_ranges_valid(obj: Any, src: str, file: MemFile) -> None:
    """递归校验 AST 中所有 SourceRange 不反转/不越界/file 正确。"""
    if isinstance(obj, SourceRange):
        s, e = obj.start.index, obj.end.index
        assert 0 <= s <= e <= len(src), f'非法 range [{s}:{e}] from {src!r}'
        assert obj.file is file or obj.file.name == '<unknown>', f'range file 错误: {obj.file.name}'
    elif hasattr(obj, '__dataclass_fields__'):
        for f in obj.__dataclass_fields__:
            _assert_ranges_valid(getattr(obj, f), src, file)
    elif isinstance(obj, list):
        for x in cast(list[Any], obj):
            _assert_ranges_valid(x, src, file)


def _random_source(rng: random.Random) -> str:
    """随机长度：0-10（边界密集）/0-50/0-300 三档随机，兼顾短边界与长串。"""
    n = rng.choice((rng.randint(0, 10), rng.randint(0, 50), rng.randint(0, 300)))
    return ''.join(rng.choice(_CHARS) for _ in range(n))


def _mutate(rng: random.Random, src: str) -> str:
    chars = list(src)
    for _ in range(rng.randint(1, 10)):
        if not chars:
            chars.append(rng.choice(_CHARS))
            continue
        i = rng.randrange(len(chars))
        op = rng.randrange(4)
        if op == 0:  # 插入
            chars.insert(i, rng.choice(_CHARS))
        elif op == 1:  # 删除
            del chars[i]
        elif op == 2:  # 替换
            chars[i] = rng.choice(_CHARS)
        else:  # 截断
            chars = chars[:i]
    return ''.join(chars)


def test_fuzz_seeds_directly() -> None:
    for seed in _SEEDS:
        _check_invariants(seed)


def test_fuzz_random_inputs_never_crash() -> None:
    rng = random.Random(20260821)
    for _ in range(300):
        _check_invariants(_random_source(rng))


def test_fuzz_random_extended_pool_never_crash() -> None:
    """大规模随机池：500 个随机串（长度 0-500），覆盖随机抽取字符与边界字符。"""
    rng = random.Random(20260824)
    for _ in range(500):
        n = rng.randint(0, 500)
        src = ''.join(rng.choice(_CHARS) for _ in range(n))
        _check_invariants(src)


def test_fuzz_mutated_seeds_never_crash() -> None:
    rng = random.Random(20260822)
    for _ in range(300):
        seed = rng.choice(_SEEDS)
        _check_invariants(_mutate(rng, seed))
