"""InfinityData —— 声明式配置语言（.infd/.inft）的 Python 编译器库。

编译流水线：RawTokenizer → FinalTokenizer → Parser → SemanticAnalyzer → Converter

用法::

    from infinity_data import compile_source, load

    result = load("app.infd")
    if result.has_errors:
        for d in result.diagnostics:
            print(d.location, d.message)
    else:
        print(result.value)
"""

from infinity_data.pipeline import CompilationResult, compile_source, load
from infinity_data.semantic.models import Diagnostic, Severity

__all__ = [
    'compile_source',
    'load',
    'CompilationResult',
    'Diagnostic',
    'Severity',
]
