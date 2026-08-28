"""官方 LSP 服务器测试：协议传输 + 消息分发 + 能力响应。"""

from __future__ import annotations

import io
import json
from typing import Any

from infinity_data.tools.lsp import protocol, server


class _FakeStream:
    """内存二进制读写对：模拟 stdio 管道（支持 readline/read/write）。"""

    def __init__(self) -> None:
        self._buffer = io.BytesIO()
        self._pos = 0

    def write(self, data: bytes) -> int:
        self._buffer.seek(0, io.SEEK_END)
        self._buffer.write(data)
        return len(data)

    def flush(self) -> None:
        pass

    def readline(self) -> bytes:
        self._buffer.seek(self._pos)
        line = self._buffer.readline()
        self._pos = self._buffer.tell()
        return line

    def read(self, length: int = -1) -> bytes:
        self._buffer.seek(self._pos)
        data = self._buffer.read(length) if length >= 0 else self._buffer.read()
        self._pos = self._buffer.tell()
        return data

    def read_into(self) -> bytes:
        """取走已写入的所有字节（供输出端断言）。"""
        self._buffer.seek(0)
        data = self._buffer.read()
        self._buffer = io.BytesIO()
        self._pos = 0
        return data

    def push(self, data: bytes) -> None:
        """把字节灌回（供输入端消费）。"""
        self._buffer.seek(0, io.SEEK_END)
        self._buffer.write(data)


def _frame(obj: dict[str, Any]) -> bytes:
    body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
    return f'Content-Length: {len(body)}\r\n\r\n'.encode('ascii') + body


# ═══════════════════════════════════════════════════════════
# 协议传输层
# ═══════════════════════════════════════════════════════════


def test_write_message_framing() -> None:
    stream = _FakeStream()
    protocol.write_message(stream, {'jsonrpc': '2.0', 'id': 1, 'result': {'ok': True}})
    raw = stream.read_into()
    assert raw.startswith(b'Content-Length: ')
    header, _, body = raw.partition(b'\r\n\r\n')
    assert int(header.split(b':')[1]) == len(body)
    assert json.loads(body) == {'jsonrpc': '2.0', 'id': 1, 'result': {'ok': True}}


def test_read_message_roundtrip() -> None:
    stream = _FakeStream()
    msg = {'jsonrpc': '2.0', 'method': 'textDocument/didOpen', 'params': {'uri': 'x'}}
    stream.push(_frame(msg))
    assert protocol.read_message(stream) == msg


def test_read_message_eof() -> None:
    stream = _FakeStream()
    assert protocol.read_message(stream) is None


def test_read_message_bad_json_skipped() -> None:
    stream = _FakeStream()
    stream.push(b'Content-Length: 5\r\n\r\n{{{{')
    assert protocol.read_message(stream) is None


# ═══════════════════════════════════════════════════════════
# 服务器分发
# ═══════════════════════════════════════════════════════════


class _ServerHarness:
    """把消息灌给服务器并收集全部响应的夹具。

    ``run(*msgs)``：按序发送消息，末尾自动追加 shutdown（结束循环），
    返回服务器写出的全部响应消息（含 shutdown 的 reply）。
    """

    def __init__(self) -> None:
        self.reader = _FakeStream()
        self.writer = _FakeStream()
        self.srv = server.Server(self.reader, self.writer)

    def run(self, *msgs: dict[str, Any]) -> list[dict[str, Any]]:
        for m in msgs:
            self.reader.push(_frame(m))
        # shutdown 让 run() 循环自然退出
        self.reader.push(_frame({'jsonrpc': '2.0', 'id': -1, 'method': 'shutdown'}))
        self.srv.run()
        return self.responses()

    def responses(self) -> list[dict[str, Any]]:
        """解析 writer 中累积的所有消息。"""
        raw = self.writer.read_into()
        out: list[dict[str, Any]] = []
        pos = 0
        while True:
            end = raw.find(b'\r\n\r\n', pos)
            if end == -1:
                break
            header = raw[pos:end].decode('ascii')
            length = int(header.split(':')[1])
            body_start = end + 4
            out.append(json.loads(raw[body_start : body_start + length]))
            pos = body_start + length
        return out


def _open_doc(uri: str, text: str) -> dict[str, Any]:
    return {
        'jsonrpc': '2.0',
        'method': 'textDocument/didOpen',
        'params': {'textDocument': {'uri': uri, 'languageId': 'infd', 'version': 1, 'text': text}},
    }


def _pick(msgs: list[dict[str, Any]], msg_id: int) -> dict[str, Any]:
    """取指定 id 的响应（断言存在）。"""
    for m in msgs:
        if m.get('id') == msg_id:
            return m
    raise AssertionError(f'未找到 id={msg_id} 的响应: {msgs}')


def test_initialize_capabilities() -> None:
    h = _ServerHarness()
    msgs = h.run(
        {
            'jsonrpc': '2.0',
            'id': 1,
            'method': 'initialize',
            'params': {'processId': None, 'rootUri': None, 'capabilities': {}},
        }
    )
    resp = _pick(msgs, 1)
    caps = resp['result']['capabilities']
    assert caps['textDocumentSync'] == 1  # Full
    assert caps['hoverProvider'] is True
    assert caps['definitionProvider'] is True
    assert caps['documentSymbolProvider'] is True
    assert 'semanticTokensProvider' in caps
    assert caps['completionProvider']['triggerCharacters'] == [':', '<', '!', '~', '$', '.', '(', ',']
    assert resp['result']['serverInfo']['name'] == 'infinity-data-lsp'


def test_did_open_publishes_diagnostics() -> None:
    h = _ServerHarness()
    msgs = h.run(_open_doc('file:///t/app.infd', 'bad_port: <int, range(1, 100)> = 200\n'))
    notif = next(m for m in msgs if m.get('method') == 'textDocument/publishDiagnostics')
    assert notif['params']['uri'] == 'file:///t/app.infd'
    assert any(d['code'] == 'constraint.range_above' for d in notif['params']['diagnostics'])


def test_did_change_full_sync_reanalyzes() -> None:
    h = _ServerHarness()
    msgs = h.run(
        _open_doc('file:///t/app.infd', 'a = 1\n'),
        {
            'jsonrpc': '2.0',
            'method': 'textDocument/didChange',
            'params': {
                'textDocument': {'uri': 'file:///t/app.infd', 'version': 2},
                'contentChanges': [{'text': 'bad_port: <int, range(1, 100)> = 200\n'}],
            },
        },
    )
    notifs = [m for m in msgs if m.get('method') == 'textDocument/publishDiagnostics']
    assert any(d['code'] == 'constraint.range_above' for d in notifs[-1]['params']['diagnostics'])


def test_completion_request() -> None:
    h = _ServerHarness()
    msgs = h.run(
        _open_doc('file:///t/app.infd', 'port: <int, range(1, 100)> = 80\n\n'),
        {
            'jsonrpc': '2.0',
            'id': 2,
            'method': 'textDocument/completion',
            'params': {'textDocument': {'uri': 'file:///t/app.infd'}, 'position': {'line': 1, 'character': 0}},
        },
    )
    resp = _pick(msgs, 2)
    labels = {it['label'] for it in resp['result']['items']}
    assert 'int' in labels


def test_hover_request() -> None:
    h = _ServerHarness()
    msgs = h.run(
        _open_doc('file:///t/app.infd', 'port: <int, range(1, 100)> = 80\n'),
        {
            'jsonrpc': '2.0',
            'id': 3,
            'method': 'textDocument/hover',
            'params': {'textDocument': {'uri': 'file:///t/app.infd'}, 'position': {'line': 0, 'character': 12}},
        },
    )
    resp = _pick(msgs, 3)
    assert 'range' in resp['result']['contents']['value']


def test_semantic_tokens_request() -> None:
    h = _ServerHarness()
    msgs = h.run(
        _open_doc('file:///t/app.infd', 'a = 1\n'),
        {
            'jsonrpc': '2.0',
            'id': 4,
            'method': 'textDocument/semanticTokens/full',
            'params': {'textDocument': {'uri': 'file:///t/app.infd'}},
        },
    )
    resp = _pick(msgs, 4)
    data = resp['result']['data']
    assert data and len(data) % 5 == 0


def test_document_symbols_request() -> None:
    h = _ServerHarness()
    msgs = h.run(
        _open_doc('file:///t/app.infd', '~Server {\n  port: int = 80\n}\nname = "x"\n'),
        {
            'jsonrpc': '2.0',
            'id': 5,
            'method': 'textDocument/documentSymbol',
            'params': {'textDocument': {'uri': 'file:///t/app.infd'}},
        },
    )
    resp = _pick(msgs, 5)
    assert [s['name'] for s in resp['result']] == ['~Server', 'name']


def test_definition_request() -> None:
    h = _ServerHarness()
    msgs = h.run(
        _open_doc('file:///t/app.infd', '~Server {\n  port: int = 80\n}\ns = Server()\n'),
        {
            'jsonrpc': '2.0',
            'id': 6,
            'method': 'textDocument/definition',
            'params': {'textDocument': {'uri': 'file:///t/app.infd'}, 'position': {'line': 3, 'character': 6}},
        },
    )
    resp = _pick(msgs, 6)
    assert resp['result']['range']['start'] == {'line': 0, 'character': 0}


def test_unknown_method_returns_error() -> None:
    h = _ServerHarness()
    msgs = h.run({'jsonrpc': '2.0', 'id': 7, 'method': 'textDocument/unknown'})
    resp = _pick(msgs, 7)
    assert resp['error']['code'] == -32601


def test_internal_error_is_caught() -> None:
    """内部异常 → -32603，不崩溃服务器（对带 id 的请求返回错误响应）。"""

    def boom(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        raise RuntimeError('boom')

    original = server.language.completion_items
    server.language.completion_items = boom
    try:
        h = _ServerHarness()
        msgs = h.run(
            _open_doc('file:///t/app.infd', 'a = 1\n'),
            {
                'jsonrpc': '2.0',
                'id': 42,
                'method': 'textDocument/completion',
                'params': {'textDocument': {'uri': 'file:///t/app.infd'}, 'position': {'line': 0, 'character': 0}},
            },
        )
    finally:
        server.language.completion_items = original
    resp = _pick(msgs, 42)
    assert resp['error']['code'] == -32603
    assert 'boom' in resp['error']['message']


def test_shutdown_ends_run_loop() -> None:
    """发送 shutdown 后服务器应答并结束主循环（run() 返回）。"""
    h = _ServerHarness()
    msgs = h.run()
    shutdown = next(m for m in msgs if m.get('id') == -1)
    assert shutdown['result'] is None
