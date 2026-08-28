"""infd LSP 服务器：JSON-RPC 分发 + 文档同步 + 能力实现。

单线程 stdio 语言服务器。状态只含文档表（uri → 全文），每次变更全量重编译
（Full sync）。.infd 文件都很小，编译代价可忽略。
"""

from __future__ import annotations

import sys
import urllib.parse
from typing import Any

from infinity_data.tools.lsp import language
from infinity_data.tools.lsp.protocol import read_message, write_message

__all__ = ['Server', 'run_stdio', 'main']

_LSP_VERSION = '1.0.0'


def uri_to_path(uri: str) -> str:
    """``file:///a/b/c.infd`` → ``/a/b/c.infd``（百分号解码）。"""
    if uri.startswith('file://'):
        return urllib.parse.unquote(urllib.parse.urlparse(uri).path)
    return uri


class Server:
    """单线程 stdio 语言服务器。

    状态只含文档表（uri → 全文），每次变更全量重编译（Full sync）。
    """

    def __init__(self, reader: Any, writer: Any) -> None:
        self._reader = reader
        self._writer = writer
        self._docs: dict[str, str] = {}
        self._shutdown = False

    # ── 发送辅助 ──────────────────────────────────────────

    def _send(self, obj: dict[str, Any]) -> None:
        write_message(self._writer, obj)

    def _reply(self, msg_id: Any, result: Any) -> None:
        self._send({'jsonrpc': '2.0', 'id': msg_id, 'result': result})

    def _error(self, msg_id: Any, code: int, message: str) -> None:
        self._send({'jsonrpc': '2.0', 'id': msg_id, 'error': {'code': code, 'message': message}})

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        self._send({'jsonrpc': '2.0', 'method': method, 'params': params})

    # ── 主循环 ────────────────────────────────────────────

    def run(self) -> None:
        while not self._shutdown:
            msg = read_message(self._reader)
            if msg is None:
                break
            self._dispatch(msg)

    def _dispatch(self, msg: dict[str, Any]) -> None:
        """分发前包异常保护：任何内部错误只回 -32603，绝不因单个请求/文件崩溃服务器。"""
        try:
            self._dispatch_inner(msg)
        except Exception as e:  # noqa: BLE001
            import traceback

            traceback.print_exc()
            msg_id = msg.get('id')
            if msg_id is not None:
                self._error(msg_id, -32603, f'内部错误: {type(e).__name__}: {e}')

    def _dispatch_inner(self, msg: dict[str, Any]) -> None:
        method = msg.get('method')
        params: dict[str, Any] = msg.get('params') or {}
        msg_id = msg.get('id')

        if method == 'initialize':
            self._reply(msg_id, self._capabilities())
        elif method == 'initialized':
            pass
        elif method == 'shutdown':
            self._shutdown = True
            self._reply(msg_id, None)
        elif method == 'exit':
            sys.exit(0)
        elif method == 'textDocument/didOpen':
            self._on_open(params)
        elif method == 'textDocument/didChange':
            self._on_change(params)
        elif method == 'textDocument/didSave':
            self._on_save(params)
        elif method == 'textDocument/didClose':
            self._on_close(params)
        elif method == 'textDocument/completion':
            self._reply(msg_id, self._completion(params))
        elif method == 'textDocument/hover':
            self._reply(msg_id, self._hover(params))
        elif method == 'textDocument/semanticTokens/full':
            self._reply(msg_id, self._semantic_tokens(params))
        elif method == 'textDocument/documentSymbol':
            self._reply(msg_id, self._document_symbols(params))
        elif method == 'textDocument/definition':
            self._reply(msg_id, self._definition(params))
        elif method == '$/cancelRequest':
            pass  # 无长任务，直接忽略
        else:
            if msg_id is not None:
                self._error(msg_id, -32601, f'方法未实现: {method}')

    def _capabilities(self) -> dict[str, Any]:
        return {
            'capabilities': {
                'textDocumentSync': 1,  # Full
                'completionProvider': {'triggerCharacters': [':', '<', '!', '~', '$', '.', '(', ',']},
                'hoverProvider': True,
                'documentSymbolProvider': True,
                'definitionProvider': True,
                'semanticTokensProvider': {
                    'legend': {
                        'tokenTypes': language.SEMANTIC_TOKEN_TYPES,
                        'tokenModifiers': [],
                    },
                    'full': True,
                },
            },
            'serverInfo': {'name': 'infinity-data-lsp', 'version': _LSP_VERSION},
        }

    # ── 文档生命周期 ───────────────────────────────────────

    def _publish(self, uri: str) -> None:
        text = self._docs.get(uri)
        if text is None:
            return
        path = uri_to_path(uri)
        diags = language.analyze(text, path)
        self._notify('textDocument/publishDiagnostics', {'uri': uri, 'diagnostics': diags})

    def _on_open(self, params: dict[str, Any]) -> None:
        doc = params['textDocument']
        self._docs[doc['uri']] = doc.get('text', '')
        self._publish(doc['uri'])

    def _on_change(self, params: dict[str, Any]) -> None:
        doc = params['textDocument']
        uri = doc['uri']
        changes: list[Any] = params.get('contentChanges') or []
        for change in changes:
            if 'text' in change:  # Full sync：直接取全文
                self._docs[uri] = change['text']
        self._publish(uri)

    def _on_save(self, params: dict[str, Any]) -> None:
        self._publish(params['textDocument']['uri'])

    def _on_close(self, params: dict[str, Any]) -> None:
        uri = params['textDocument']['uri']
        self._docs.pop(uri, None)
        self._notify('textDocument/publishDiagnostics', {'uri': uri, 'diagnostics': []})

    # ── 语言能力 ───────────────────────────────────────────

    def _completion(self, params: dict[str, Any]) -> dict[str, Any]:
        uri = params['textDocument']['uri']
        text = self._docs.get(uri)
        if text is None:
            return {'isIncomplete': False, 'items': []}
        items = language.completion_items(text, uri_to_path(uri), params['position'])
        return {'isIncomplete': False, 'items': items}

    def _hover(self, params: dict[str, Any]) -> dict[str, Any] | None:
        uri = params['textDocument']['uri']
        text = self._docs.get(uri)
        if text is None:
            return None
        return language.hover(text, uri_to_path(uri), params['position'])

    def _semantic_tokens(self, params: dict[str, Any]) -> dict[str, Any]:
        uri = params['textDocument']['uri']
        text = self._docs.get(uri)
        if text is None:
            return {'data': []}
        return {'data': language.semantic_tokens(text, uri_to_path(uri))}

    def _document_symbols(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        uri = params['textDocument']['uri']
        text = self._docs.get(uri)
        if text is None:
            return []
        return language.document_symbols(text, uri_to_path(uri))

    def _definition(self, params: dict[str, Any]) -> dict[str, Any] | None:
        uri = params['textDocument']['uri']
        text = self._docs.get(uri)
        if text is None:
            return None
        return language.definition(text, uri_to_path(uri), params['position'])


def run_stdio() -> None:
    """以 stdio 为传输运行服务器（阻塞直到客户端退出）。"""
    Server(sys.stdin.buffer, sys.stdout.buffer).run()


def main() -> None:
    """控制台脚本入口（``infd-lsp``）。"""
    run_stdio()
