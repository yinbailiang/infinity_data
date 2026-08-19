"""Phase 2b（约束执行器）：遍历 StdAst 执行约束 + 顶层 schema 校验。

- :class:`ConstraintExecutor`：消费 Phase 2a 产出的标准 AST（executor.py）

子模块导出自身类，供流水线（pipeline / 测试）直接引用。
"""

from infinity_data.semantic.executor.executor import ConstraintExecutor

__all__ = ['ConstraintExecutor']
