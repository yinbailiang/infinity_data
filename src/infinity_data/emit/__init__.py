"""产物发射层：Python / std → 输出格式（JSON / YAML / TOML）。

与 semantic 层边界：
- **内部表示（忠实双向）** → :mod:`infinity_data.semantic.std` 的
  ``python_to_std`` / ``std_to_python``（path → PurePosixPath、float → Decimal、
  noexist → :data:`~infinity_data.semantic.std.NOEXIST` 哨兵）
- **本层（emit，有损投影）** → :func:`to_json` / :func:`to_yaml` / :func:`to_toml`，
  按 :class:`EmitConfig` 控制 Decimal 编码与 noexist 标记；:func:`project_output`
  为纯 Python 值的轻量投影；:func:`restore_python` 反向**尝试还原**加载的原始
  dict 为 :data:`~infinity_data.semantic.std.StdPythonValue`

**emit 不应被流水线内部使用**——内部表示一律走 semantic 的忠实转换。
"""

from infinity_data.emit.config import EmitConfig
from infinity_data.emit.converter import (
    dump_to_json,
    load_from_json,
    project_output,
    restore_python,
    to_json,
    to_toml,
    to_yaml,
)

__all__ = [
    'EmitConfig',
    'dump_to_json',
    'load_from_json',
    'project_output',
    'restore_python',
    'to_json',
    'to_toml',
    'to_yaml',
]
