"""语义层：数据模型与高级 API（产物面）。

三阶段子模块（按职责命名）：

- :mod:`infinity_data.semantic.resolver`——Phase 1 导入求解器
- :mod:`infinity_data.semantic.builder`——Phase 2a AST 构建器
- :mod:`infinity_data.semantic.executor`——Phase 2b 约束执行器

子模块间仅经数据模型依赖（resolver.models → builder.models → executor），
无对象引用；诊断经共享 :class:`DiagnosticCollector` 由流水线统一收集。

本包导出：
- 数据模型（StdAst / 已解析约束 / Phase 1 上下文）
- 高级 API（:class:`TemplateGraphResolver` / :class:`AstBuilder` /
  :class:`ConstraintExecutor` / :class:`ImportResolver`——流水线组装对象）

导入 :mod:`infinity_data.semantic.diagnostics` 以注册本层全部诊断定义
（副作用，导入即注册进全局注册表）。
"""

from infinity_data.infra.diagnostics import Diagnostic, Severity
from infinity_data.semantic import (
    diagnostics,
)
from infinity_data.semantic.builder import (
    AstBuilder,
    ResolvedConstraint,
    StdArray,
    StdDocument,
    StdField,
    StdLiteral,
    StdObject,
    StdValue,
)
from infinity_data.semantic.executor import ConstraintExecutor
from infinity_data.semantic.resolver import (
    ImportResolver,
    ResolvedContext,
    Scope,
    TemplateGraphResolver,
    TemplateKey,
)

__all__ = [
    'AstBuilder',
    'ConstraintExecutor',
    'Diagnostic',
    'ImportResolver',
    'ResolvedConstraint',
    'ResolvedContext',
    'Scope',
    'Severity',
    'StdArray',
    'StdDocument',
    'StdField',
    'StdLiteral',
    'StdObject',
    'StdValue',
    'TemplateGraphResolver',
    'TemplateKey',
    'diagnostics',
]
