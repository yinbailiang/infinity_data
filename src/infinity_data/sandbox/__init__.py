"""M3 安全模型：沙盒配置、沙盒中介、顶层 Schema 约束与安全异常。

子模块：
- :mod:`config`：SandboxConfig（授权数据 + 工厂）
- :mod:`mediator`：Sandbox（系统访问中介，File 的唯一产出者）
- :mod:`errors`：SandboxError / SchemaError
- :mod:`schema`：Schema（顶层模板约束）

公共 API 从此包再导出，兼容 ``from infinity_data.sandbox import ...``。
"""

from infinity_data.sandbox.config import SandboxConfig
from infinity_data.sandbox.errors import (
    AccessDeniedError,
    EnvNotAuthorizedError,
    EnvNotSetError,
    SandboxError,
    SchemaError,
)
from infinity_data.sandbox.mediator import Sandbox
from infinity_data.sandbox.schema import Schema

__all__ = [
    'Sandbox',
    'SandboxConfig',
    'SandboxError',
    'EnvNotAuthorizedError',
    'EnvNotSetError',
    'AccessDeniedError',
    'SchemaError',
    'Schema',
]
