"""InfinityData 演示：加载配置并打印错误报告。

运行：uv run python test.py
"""

from __future__ import annotations

from pathlib import Path
import tempfile

from infinity_data import CompilationResult, check, load

_TAG = {
    'error': '✗ ERROR',
    'warning': '⚠ WARNING',
    'info': 'ℹ INFO',
}


def _write(root: Path, name: str, text: str) -> Path:
    p = root / name
    p.write_text(text, encoding='utf-8')
    return p


def print_report(title: str, result: CompilationResult) -> None:
    """打印一次编译的诊断报告（按源码位置排序，含定位与渲染消息）。"""
    print(f'═══ {title} ═══')
    diags = result.diagnostics
    if not diags:
        print('  无诊断，编译成功 ✓')
    for d in diags:
        tag = _TAG.get(d.severity.value, d.severity.value)
        print(f'  [{tag}] {d.code}')
        print(f'      at {d.location}')
        print(f'      {d.message}')
    if result.has_errors:
        print(f'  → value = {result.value}（出错时为空文档或部分结果）')
    print()


def main() -> None:
    with tempfile.TemporaryDirectory(prefix='infd-demo-') as td:
        root = Path(td)

        # ── 1. 正常配置 ──────────────────────────────────────
        _write(
            root,
            'app.infd',
            '''
server {
    host = "0.0.0.0"
    port: <int, range(1, 65535)> = 8080
    tls = true
}
name = "demo"
''',
        )
        result = load(root / 'app.infd')
        print_report('1. 正常配置 app.infd', result)
        print(f'   编译结果: {result.value}\n')

        # ── 2. 语法错误（数组未闭合，验证容错恢复）─────────────
        _write(root, 'syntax.infd', 'a = [1, 2\nb = 3\n')
        result = load(root / 'syntax.infd')
        print_report('2. 语法错误 syntax.infd', result)

        # ── 3. 约束违规（类型 + 值域）─────────────────────────
        _write(
            root,
            'constraint.infd',
            '''
port: <int, range(1, 65535)> = 70000
mode: <str, in("prod", "staging")> = "dev"
''',
        )
        result = load(root / 'constraint.infd')
        print_report('3. 约束违规 constraint.infd', result)

        # ── 4. 沙盒违规（库默认零信任 deny_all）────────────────
        _write(root, 'sandbox.infd', '!env import DATABASE_URL\nurl = $DATABASE_URL\n')
        result = load(root / 'sandbox.infd')
        print_report('4. 沙盒违规 sandbox.infd（!env 未授权）', result)

        # ── 5. 授权后重新加载 ─────────────────────────────────
        result = load(root / 'sandbox.infd', env={'DATABASE_URL': 'postgres://localhost/db'})
        print_report('5. 授权后 sandbox.infd', result)
        print(f'   编译结果: {result.value}\n')

        # ── 6. check() 仅校验（不输出）────────────────────────
        diags = check(root / 'constraint.infd')
        print(f'check() 仅校验 constraint.infd → 共 {len(diags)} 条诊断')
        for d in diags:
            print(f'   {d.code} @ {d.location}')


if __name__ == '__main__':
    main()
