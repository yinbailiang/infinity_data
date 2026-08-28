"""infd-cov CLI 测试：YAML/JSON 输出、提取、拒绝阈值、stdin、输出文件。"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import pytest

from infinity_data.tools.cov import main


def _run(args: list[str]) -> tuple[int, str, str]:
    """运行 main()，捕获 stdout / stderr。"""
    out = io.StringIO()
    err = io.StringIO()
    import contextlib

    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = main(args)
    return rc, out.getvalue(), err.getvalue()


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding='utf-8')
    return path


CLEAN = """
~Server {
    name: str
    port: <int, range(1, 65535)> = 80
}
app {
    name = "demo"
    servers = [Server(name="api", port=443)]
    debug = false
}
"""


# ═══════════════════════════════════════════════════════════
# 基本输出
# ═══════════════════════════════════════════════════════════


def test_yaml_to_stdout(tmp_path: Path) -> None:
    f = _write(tmp_path / 'app.infd', CLEAN)
    rc, out, err = _run([str(f)])
    assert rc == 0
    assert err == ''
    assert out == ('app:\n  name: demo\n  servers:\n    - name: api\n      port: 443\n  debug: false\n')


def test_json_to_stdout(tmp_path: Path) -> None:
    f = _write(tmp_path / 'app.infd', CLEAN)
    rc, out, _ = _run([str(f), '-f', 'json'])
    assert rc == 0
    data = json.loads(out)
    assert data == {'app': {'name': 'demo', 'servers': [{'name': 'api', 'port': 443}], 'debug': False}}


def test_json_compact(tmp_path: Path) -> None:
    f = _write(tmp_path / 'app.infd', CLEAN)
    rc, out, _ = _run([str(f), '-f', 'json', '--compact'])
    assert rc == 0
    assert out.startswith('{') and '\n' not in out.strip()


def test_output_to_file(tmp_path: Path) -> None:
    f = _write(tmp_path / 'app.infd', CLEAN)
    dest = tmp_path / 'out.json'
    rc, out, _ = _run([str(f), str(dest), '-f', 'json'])
    assert rc == 0
    assert out == ''
    assert json.loads(dest.read_text(encoding='utf-8')) == {
        'app': {'name': 'demo', 'servers': [{'name': 'api', 'port': 443}], 'debug': False}
    }


def test_stdin_input(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setattr('sys.stdin', io.StringIO(CLEAN))
    rc, out, _ = _run(['-f', 'json'])
    assert rc == 0
    assert json.loads(out) == {'app': {'name': 'demo', 'servers': [{'name': 'api', 'port': 443}], 'debug': False}}


# ═══════════════════════════════════════════════════════════
# 提取
# ═══════════════════════════════════════════════════════════


def test_extract_subpath(tmp_path: Path) -> None:
    f = _write(tmp_path / 'app.infd', CLEAN)
    rc, out, _ = _run([str(f), '-f', 'json', '--extract', 'app.servers'])
    assert rc == 0
    assert json.loads(out) == [{'name': 'api', 'port': 443}]


def test_extract_missing_path_errors(tmp_path: Path) -> None:
    f = _write(tmp_path / 'app.infd', CLEAN)
    rc, out, err = _run([str(f), '--extract', 'app.nope'])
    assert rc == 1
    assert out == ''
    assert '不存在' in err


# ═══════════════════════════════════════════════════════════
# 拒绝阈值
# ═══════════════════════════════════════════════════════════


def test_severity_error_blocks_output(tmp_path: Path) -> None:
    f = _write(tmp_path / 'bad.infd', 'port: <int, range(1, 100)> = 200\n')
    rc, out, err = _run([str(f)])
    assert rc == 1
    assert out == ''
    assert 'constraint.range_above' in err


def test_severity_none_allows_output(tmp_path: Path) -> None:
    f = _write(tmp_path / 'bad.infd', 'port: <int, range(1, 100)> = 200\n')
    rc, out, _ = _run([str(f), '--severity', 'none'])
    assert rc == 0
    assert 'port: 200' in out


def test_severity_warning_blocks_warning(tmp_path: Path) -> None:
    """$ 未导入引用是 WARNING：--severity warning 时拒绝输出。"""
    f = _write(tmp_path / 'warn.infd', 'x = $NOT_IMPORTED\n')
    rc, _, err = _run([str(f), '--severity', 'warning'])
    assert rc == 1
    assert 'dollar.undefined' in err
    # 默认 error 阈值不拦 warning
    rc2, _, _ = _run([str(f)])
    assert rc2 == 0


# ═══════════════════════════════════════════════════════════
# 虚拟环境变量
# ═══════════════════════════════════════════════════════════


def test_virtual_env_injection(tmp_path: Path) -> None:
    """#env 声明缺失变量 → 注入虚拟值，env_not_set 不阻断。"""
    f = _write(tmp_path / 'env.infd', '#env: MY_KEY "sk-virtual"\n!env import MY_KEY as k\nx = $k as str\n')
    rc, out, err = _run([str(f), '-f', 'json'])
    assert rc == 0, err
    assert json.loads(out) == {'x': 'sk-virtual'}


# ═══════════════════════════════════════════════════════════
# TOML（tool 组保证 tomli-w 已装）
# ═══════════════════════════════════════════════════════════


def test_toml_output(tmp_path: Path) -> None:
    """tool 组保证 tomli-w 已装：-f toml 正常输出。"""
    f = _write(tmp_path / 'app.infd', CLEAN)
    rc, out, _ = _run([str(f), '-f', 'toml'])
    assert rc == 0
    assert 'name' in out


# ═══════════════════════════════════════════════════════════
# 控制台脚本
# ═══════════════════════════════════════════════════════════


def test_console_script_registered() -> None:
    """pyproject 的 console_scripts 声明 infd-cov。"""
    pyproject = Path(__file__).resolve().parent.parent / 'pyproject.toml'
    text = pyproject.read_text(encoding='utf-8')
    assert 'infd-cov = "infinity_data.tools.cov.__main__:main"' in text


@pytest.mark.parametrize('fmt', ['yaml', 'json'])
def test_demo_file_compiles(tmp_path: Path, fmt: str) -> None:
    """examples/app.infd 演示文件可正常转换（回归保护）。"""
    demo = Path(__file__).resolve().parent.parent / 'examples' / 'app.infd'
    if not demo.exists():  # pragma: no cover - 演示文件缺失时跳过
        pytest.skip('examples/app.infd 不存在')
    rc, out, err = _run([str(demo), '-f', fmt])
    assert rc == 0, err
    assert out
