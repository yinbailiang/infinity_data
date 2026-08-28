"""端到端演示客户端：启动 infd-lsp 服务器，走一遍 LSP 握手并打印结果。

用法：
    uv run python others/lsp_demo.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parent.parent
SERVER_CMD = [sys.executable, '-m', 'infinity_data.tools.lsp']
DEMO_URI = 'file:///tmp/demo.infd'
DEMO_FILE = ROOT / 'examples' / 'demo.infd'

# semantic token 类型 → ANSI 颜色（与 language.SEMANTIC_TOKEN_TYPES 顺序一致）
ANSI = {
    0: '\x1b[38;5;244m',  # operator  灰
    1: '\x1b[38;5;197m',  # string    红
    2: '\x1b[38;5;114m',  # number    绿
    3: '\x1b[38;5;111m',  # keyword   蓝
    4: '\x1b[0m',  # variable  默认
    5: '\x1b[38;5;246m',  # comment   浅灰
}
RESET = '\x1b[0m'


def render_semantic(text: str, data: list[Any]) -> None:
    """把 semanticTokens 数组解码成带色文本打印。"""
    spans: list[tuple[int, int, int, int]] = []  # (line, char, length, tokenType)
    cur_line = 0
    cur_char = 0
    for i in range(0, len(data), 5):
        dline = data[i]
        dchar = data[i + 1]
        tok_len = data[i + 2]
        ttype = data[i + 3]
        cur_line += dline
        cur_char = dchar if dline > 0 else cur_char + dchar
        spans.append((cur_line, cur_char, tok_len, ttype))

    out: list[str] = []
    for lineno, linetext in enumerate(text.splitlines()):
        colored = list(linetext)
        row: list[tuple[int, int, int, int]] = [s for s in spans if s[0] == lineno]
        for item in sorted(row, key=lambda s: -s[1]):
            color = ANSI.get(item[3], RESET)
            colored[item[1] : item[1] + item[2]] = [f'{color}{linetext[item[1] : item[1] + item[2]]}{RESET}']
        out.append(''.join(colored))
    print('\n'.join(out))
    print('\n   令牌类型图例: 灰=运算符 红=字符串 绿=数字 蓝=关键字 浅灰=注释')


def frame(obj: dict[str, Any]) -> bytes:
    body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
    return f'Content-Length: {len(body)}\r\n\r\n'.encode('ascii') + body


def _resp_result_items(resp: dict[str, Any], key: str) -> list[Any]:
    """从 LSP 响应取 result[key]；非 dict/非 list 时返回空列表。"""
    result = resp.get('result')
    if isinstance(result, dict):
        v = cast(dict[str, Any], result).get(key)
        if isinstance(v, list):
            return cast(list[Any], v)
    return []


class LspClient:
    def __init__(self, proc: subprocess.Popen[bytes]) -> None:
        self._proc = proc

    def send(self, obj: dict[str, Any]) -> None:
        stdin = self._proc.stdin
        assert stdin is not None
        stdin.write(frame(obj))
        stdin.flush()

    def recv(self) -> dict[str, Any] | None:
        stdout = self._proc.stdout
        assert stdout is not None
        headers: dict[bytes, bytes] = {}
        while True:
            line = stdout.readline()
            if not line:
                return None
            line = line.strip()
            if not line:
                break
            k, _, v = line.partition(b':')
            headers[k.strip().lower()] = v.strip()
        length = int(headers.get(b'content-length', b'0'))
        return json.loads(stdout.read(length))

    def request(self, msg_id: int, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.send({'jsonrpc': '2.0', 'id': msg_id, 'method': method, 'params': params or {}})
        res = self.recv()
        assert res is not None
        return res


def main() -> None:
    # 不注入任何环境变量：靠 demo.infd 里的 `#env: ... "DEEPSEEK_API_KEY"` 声明
    # 让 LSP 自动提供虚拟值，验证该功能（真实环境变量优先，不受影响）。
    proc = subprocess.Popen(SERVER_CMD, stdin=subprocess.PIPE, stdout=subprocess.PIPE, cwd=ROOT, text=False)
    client = LspClient(proc)

    print('== 1. initialize ==')
    print(
        json.dumps(
            client.request(1, 'initialize', {'processId': None, 'rootUri': None, 'capabilities': {}}),
            ensure_ascii=False,
            indent=2,
        )
    )

    text = DEMO_FILE.read_text(encoding='utf-8')
    print('\n== 2. didOpen -> publishDiagnostics ==')
    client.send(
        {
            'jsonrpc': '2.0',
            'method': 'textDocument/didOpen',
            'params': {
                'textDocument': {'uri': DEMO_URI, 'languageId': 'infd', 'version': 1, 'text': text},
            },
        }
    )
    print(json.dumps(client.recv(), ensure_ascii=False, indent=2))

    print('\n== 3. completion（a. 空位置全量  b. `<int` 前缀过滤）==')
    resp = client.request(
        2,
        'textDocument/completion',
        {'textDocument': {'uri': DEMO_URI}, 'position': {'line': 2, 'character': 0}},
    )
    items = _resp_result_items(resp, 'items')
    print('   -- a. 全量候选（前 12 项）--')
    for it in items[:12]:
        print(f'   {it["label"]:<12} | {it.get("detail")}')

    resp = client.request(
        3,
        'textDocument/completion',
        {'textDocument': {'uri': DEMO_URI}, 'position': {'line': 11, 'character': 12}},
    )
    items = _resp_result_items(resp, 'items')
    print('   -- b. 前缀过滤（`<int` 处，期望只剩 int）--')
    for it in items:
        print(f'   {it["label"]:<12} | {it.get("detail")}')

    print('\n== 4. hover（`range` 约束）==')
    print(
        json.dumps(
            client.request(
                4,
                'textDocument/hover',
                {'textDocument': {'uri': DEMO_URI}, 'position': {'line': 11, 'character': 17}},
            ),
            ensure_ascii=False,
            indent=2,
        )
    )

    print('\n== 5. hover（`Server` 模板）==')
    print(
        json.dumps(
            client.request(
                5,
                'textDocument/hover',
                {'textDocument': {'uri': DEMO_URI}, 'position': {'line': 9, 'character': 1}},
            ),
            ensure_ascii=False,
            indent=2,
        )
    )

    print('\n== 6. semanticTokens（分词器高亮，ANSI 渲染）==')
    resp = client.request(6, 'textDocument/semanticTokens/full', {'textDocument': {'uri': DEMO_URI}})
    data = _resp_result_items(resp, 'data')
    render_semantic(text, data)

    print('\n== 7. shutdown / exit ==')
    client.request(7, 'shutdown')
    client.send({'jsonrpc': '2.0', 'method': 'exit'})
    proc.wait(timeout=5)
    print('   服务器已退出，退出码:', proc.returncode)


if __name__ == '__main__':
    main()
