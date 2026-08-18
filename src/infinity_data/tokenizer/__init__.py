"""词法分析：字符流与两遍词法分析器。

- :class:`RawTokenizer`：容错第一遍，产出 ``RawToken`` 并收集词法错误
- :class:`FinalTokenizer`：值语义第二遍，产出 ``Token``（转义解析、数值转换）
"""

from infinity_data.tokenizer.char_stream import CharStream, LineCounter
from infinity_data.tokenizer.diagnostics import diag
from infinity_data.tokenizer.finalizer import FinalTokenizer
from infinity_data.tokenizer.tokenizer import RawTokenizer

__all__ = [
    'CharStream',
    'LineCounter',
    'FinalTokenizer',
    'RawTokenizer',
    'diag',
]
