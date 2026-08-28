"""JSON-RPC 2.0 over stdio 传输层（LSP 用）。

LSP 消息 = ``Content-Length: N\\r\\n\\r\\n`` + UTF-8 JSON 体。
直接读写二进制流（``sys.stdin.buffer`` / ``sys.stdout.buffer``），
避免文本层缓冲导致 readline/read 错位。

本模块零外部依赖，与编译器本体共用同一包（``infinity_data.tools.lsp``）。
"""

from __future__ import annotations

import json
from typing import Any

__all__ = ['read_message', 'write_message']


def read_message(binary: Any) -> dict[str, Any] | None:
    """从二进制流读取一条消息；EOF（客户端关闭）返回 None。

    坏消息（非法 JSON / 非 UTF-8 / 缺 Content-Length）→ 返回 None 跳过，
    绝不崩溃服务器（客户端可能发来被截断的半帧）。
    """
    headers: dict[str, str] = {}
    while True:
        line = binary.readline()
        if not line:
            return None  # EOF
        line = line.strip()
        if not line:
            break  # 空行 = header 结束
        key, _, value = line.partition(b':')
        headers[key.strip().lower().decode('ascii', 'replace')] = value.strip().decode('utf-8', 'replace')

    try:
        length = int(headers.get('content-length', '0'))
    except ValueError:
        return None
    if length <= 0:
        return None
    body = binary.read(length)
    try:
        return json.loads(body.decode('utf-8'))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


def write_message(binary: Any, obj: dict[str, Any]) -> None:
    """向二进制流写一条消息（Content-Length 帧）。"""
    body = json.dumps(obj, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    binary.write(f'Content-Length: {len(body)}\r\n\r\n'.encode('ascii'))
    binary.write(body)
    binary.flush()


# ── JSON-RPC 构造辅助（测试 / 客户端复用） ─────────────────────


def request(msg_id: int | str, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """构造 JSON-RPC 请求。"""
    return {'jsonrpc': '2.0', 'id': msg_id, 'method': method, 'params': params or {}}


def response(msg_id: int | str, result: Any) -> dict[str, Any]:
    """构造 JSON-RPC 成功响应。"""
    return {'jsonrpc': '2.0', 'id': msg_id, 'result': result}


def error_response(msg_id: int | str, code: int, message: str) -> dict[str, Any]:
    """构造 JSON-RPC 错误响应。"""
    return {'jsonrpc': '2.0', 'id': msg_id, 'error': {'code': code, 'message': message}}


def notification(method: str, params: dict[str, Any]) -> dict[str, Any]:
    """构造 JSON-RPC 通知。"""
    return {'jsonrpc': '2.0', 'method': method, 'params': params}
