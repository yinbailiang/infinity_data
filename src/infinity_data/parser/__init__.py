"""语法分析：RawAst 数据模型与解析器。

- :class:`Parser`：LL(1) 递归下降解析器（parser.py）
- RawAst 数据模型（models.py）：Document / 语句 / 值 / 约束 / 模板定义节点

公共面从此包再导出，兼容 ``from infinity_data.parser import Document``；
内部实现文件（models.py / parser.py / token_stream.py）不直接引用。

注意：parser 包内部文件仍从 ``parser.models`` 模块级导入（避免经包根
``__init__`` 触发自引用循环）——此约定与 semantic 子包一致。
"""

from infinity_data.parser.models import (
    ArrayValue,
    AstNode,
    Constraint,
    ConstraintCall,
    ConstraintIdent,
    ConstraintLiteral,
    Constraints,
    ConstraintStmt,
    DictValue,
    Document,
    DollarValue,
    EnvImportStmt,
    ErrorConstraint,
    ErrorStatement,
    ErrorValue,
    Field,
    FileImportItem,
    FileImportStmt,
    JsonPathIndex,
    JsonPathKey,
    JsonPathSegment,
    LiteralValue,
    Statement,
    TemplateCallValue,
    TemplateConfig,
    TemplateDef,
    TemplateField,
    TemplateImportItem,
    TemplateImportStmt,
    UnpackValue,
    Value,
    VarStmt,
    walk,
)
from infinity_data.parser.parser import Parser

__all__ = [
    'ArrayValue',
    'AstNode',
    'Constraint',
    'ConstraintCall',
    'ConstraintIdent',
    'ConstraintLiteral',
    'Constraints',
    'ConstraintStmt',
    'DictValue',
    'Document',
    'DollarValue',
    'EnvImportStmt',
    'ErrorConstraint',
    'ErrorStatement',
    'ErrorValue',
    'Field',
    'FileImportItem',
    'FileImportStmt',
    'JsonPathIndex',
    'JsonPathKey',
    'JsonPathSegment',
    'LiteralValue',
    'Parser',
    'Statement',
    'TemplateCallValue',
    'TemplateConfig',
    'TemplateDef',
    'TemplateField',
    'TemplateImportItem',
    'TemplateImportStmt',
    'UnpackValue',
    'Value',
    'VarStmt',
    'walk',
]
