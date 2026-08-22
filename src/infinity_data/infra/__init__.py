"""基础设施层：诊断、位置、源码来源与 LL(1) 流抽象。

最底层依赖（不依赖 tokenizer / parser / semantic）：诊断注册表与收集器、
SourceRange / SourceInfo、File 抽象（磁盘 / 内存）、LL1Stream 泛型流。
"""

from infinity_data.infra.diagnostics import Diagnostic, DiagnosticCollector, Severity
from infinity_data.infra.ll1_stream import LL1Stream

__all__ = ['Diagnostic', 'DiagnosticCollector', 'Severity', 'LL1Stream']
