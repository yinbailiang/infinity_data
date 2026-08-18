"""InfinityData —— 声明式配置语言（.infd/.inft）的 Python 编译器库。

编译流水线：RawTokenizer → FinalTokenizer → Parser → SemanticAnalyzer → Converter

用法::

    from infinity_data import load, safe_load, SandboxConfig, Schema

    result = safe_load("app.infd")
    if result.has_errors:
        for d in result.diagnostics:
            print(d.location, d.message)
    else:
        print(result.value)
"""

from infinity_data.pipeline import (
    CompilationResult,
    check,
    compile_document,
    compile_source,
    load,
    safe_load,
)
from infinity_data.sandbox import SandboxConfig, SandboxError, Schema, SchemaError
from infinity_data.semantic.models import Diagnostic, Severity

__all__ = [
    'compile_source',
    'load',
    'safe_load',
    'check',
    'compile_document',
    'CompilationResult',
    'SandboxConfig',
    'SandboxError',
    'Schema',
    'SchemaError',
    'Diagnostic',
    'Severity',
]
