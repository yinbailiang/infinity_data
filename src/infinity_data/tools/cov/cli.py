"""infd-cov 入口与主流程：argparse / 编译 / 拒绝阈值 / 渲染分发。

流程层（与 :mod:`infinity_data.tools.cov.convert` 数据转换层分离）：
编译 → 阈值拦截 → 路径提取 → 格式渲染 → stdout/文件输出。
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

from infinity_data import SandboxConfig, Severity, compile_source
from infinity_data.infra.location import format_location
from infinity_data.semantic.std import std_to_python
from infinity_data.tools.cov.convert import DEFAULT_FORMAT, FORMATS, extract_path, render

__all__ = ['main', 'virtual_env']

_SEVERITY_RANK = {
    Severity.DEBUG: 0,
    Severity.INFO: 1,
    Severity.WARNING: 2,
    Severity.ERROR: 3,
}
"""严重级别 → 数值（用于 ``--severity`` 阈值比较）。"""

_ENV_DECL_RE = re.compile(r'#env:\s*([A-Za-z_][A-Za-z0-9_]*)\s*"([^"]*)"')


def virtual_env(text: str) -> dict[str, str]:
    """扫描 ``#env: NAME \"VALUE\"`` 声明，为当前进程缺失的变量提供虚拟值。"""
    return {n: v for n, v in _ENV_DECL_RE.findall(text) if n not in os.environ}


def _load_text(path: str | None) -> tuple[str, str | None]:
    """读输入文本；返回 (text, file_path)。"""
    if path is None:
        return sys.stdin.read(), None
    p = Path(path)
    return p.read_text(encoding='utf-8'), str(p)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog='infd-cov',
        description='编译 .infd/.inft → 各种配置格式（YAML / JSON / TOML）',
    )
    parser.add_argument('input', nargs='?', help='输入 .infd/.inft（缺省读 stdin）')
    parser.add_argument('output', nargs='?', help='输出文件（缺省写 stdout）')
    parser.add_argument(
        '-f',
        '--format',
        choices=FORMATS,
        default=DEFAULT_FORMAT,
        help='输出格式：yaml（默认，零依赖）/ json / toml（需 tomli-w）',
    )
    parser.add_argument(
        '--extract',
        metavar='PATH',
        default='',
        help='点分路径提取：--extract web 去根取 web；--extract web.spec 只取 spec；空 = 整树',
    )
    parser.add_argument(
        '--severity',
        choices=('debug', 'info', 'warning', 'error', 'none'),
        default='error',
        help='拒绝阈值：达到该级别（含更高）即拒绝，诊断报告到 stderr + 退出 1；none = 从不拒绝。默认 error',
    )
    parser.add_argument(
        '--compact',
        action='store_true',
        help='JSON 紧凑输出（不缩进；仅对 json 格式生效）',
    )
    args = parser.parse_args(argv)

    text, file_path = _load_text(args.input)
    if file_path is None:
        file_path = '<stdin>'

    result = compile_source(
        text,
        file_path=file_path,
        sandbox=SandboxConfig.full_access(),
        env=virtual_env(text),
    )

    # 拒绝阈值：达到该级别（含更高）的诊断全部阻止输出
    threshold = None if args.severity == 'none' else _SEVERITY_RANK[Severity(args.severity)]
    blockers = (
        [] if threshold is None else [d for d in result.diagnostics if _SEVERITY_RANK.get(d.severity, 0) >= threshold]
    )
    if blockers:
        for d in blockers:
            print(f'{d.code}: {d.message} ({format_location(d.source)})', file=sys.stderr)
        return 1

    try:
        data = extract_path(std_to_python(result.document.root, keep_noexist=False), args.extract)
    except ValueError as e:
        print(e, file=sys.stderr)
        return 1

    try:
        output_text = render(args.format, data, compact=args.compact)
    except NotImplementedError as e:
        # toml 未安装 tomli-w 等可选依赖
        print(f'{e}（提示: pip install tomli-w 或 uv sync --group tool）', file=sys.stderr)
        return 1
    except (TypeError, ValueError) as e:
        print(f'渲染失败: {e}', file=sys.stderr)
        return 1

    if args.output:
        Path(args.output).write_text(output_text + '\n', encoding='utf-8')
    else:
        print(output_text)
    return 0
