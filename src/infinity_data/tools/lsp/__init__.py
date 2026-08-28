"""InfinityData 官方语言服务器（.infd/.inft）—— LSP 实现。

零依赖手写 JSON-RPC 2.0 over stdio，直接消费本包编译器能力
（``compile_source`` / ``parse_source(File)`` / ``RawTokenizer`` / emit / semantic）。

能力：
- 诊断（``textDocument/publishDiagnostics``，精确位置 + 稳定错误码 + 中文消息）
- 补全（命名空间 ``$`` / 内置约束 / 可见模板 / 关键字 / 模板字段）
- 悬停（约束描述 / 顶层字段编译产物投影 / 模板结构骨架）
- 文档大纲（``textDocument/documentSymbol``）
- 跳转到定义（``textDocument/definition``：模板 / ``!from`` 导入 / ``$`` 引用）
- 语义令牌（``textDocument/semanticTokens/full``，基于 RawTokenizer）

与玩具版 ``infinity_data_lsp``（老 API）的主要差异：
- ``EnvImportStmt.items``（老版直接 ``stmt.alias/name``）
- ``DictValue.items``（老版 ``fields``/``unpacks`` 分离）
- ``TemplateCallValue.named_args`` 为列表（老版 dict）
- ``TemplateField.constraints`` 为 :class:`Constraints` 包装
- ``TemplateConfig.description`` 直接属性（老版 ``config`` 为 dict）
- 新增 ``textDocument/definition``

位置语义：编译器位置为 1-based 码点，LSP 为 0-based UTF-16 单元
（见 :mod:`infinity_data.tools.lsp.positions`）。
"""

from infinity_data.tools.lsp.language import SEMANTIC_TOKEN_TYPES
from infinity_data.tools.lsp.server import Server, run_stdio

__version__ = '1.0.0'

__all__ = ['Server', 'run_stdio', 'SEMANTIC_TOKEN_TYPES', '__version__']
