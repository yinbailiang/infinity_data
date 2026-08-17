"""产物发射层：StdAst → 宿主表示（Python dict / list / 标量）。

语义分析（semantic/）负责"值是否正确"，本层负责"产物长什么样"。
M4 的 JSON/YAML/TOML 转换、M5 的 JSON Schema 生成均在此层扩展。
"""

from infinity_data.emit.converter import reduce_array, reduce_object, reduce_value

__all__ = ['reduce_array', 'reduce_object', 'reduce_value']
