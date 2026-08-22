"""Phase 1（导入求解）数据模型：模板身份、可见名表与解析上下文。

本子模块**只定义数据**，不包含任何解析逻辑（解析器见 :mod:`resolver`）。
Phase 2（构建 / 执行）通过 :class:`ResolvedContext` 消费本层产物——
子模块间仅经数据模型依赖，无对象引用。

- ``TemplateKey``：模板真名（来源文件身份 + 本地名）
- ``Scope``：文件级可见名表（可见名 → 真名）
- ``ResolvedContext``：Phase 1 完整产物（模板图 + 可见名表 + 数据命名空间）
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from infinity_data.parser import TemplateDef

if TYPE_CHECKING:
    from infinity_data.semantic.std import StdValue

__all__ = ['ResolvedContext', 'Scope', 'TemplateKey']


@dataclass(frozen=True)
class TemplateKey:
    """模板唯一身份：依赖闭包组合哈希 + 模板本地名。

    - ``identity``：依赖闭包组合哈希（§2.5）——内容 + 依赖闭包相同 → 同身份，
      与机器 / 路径无关（可复现构建、可签名）；计算见
      :mod:`infinity_data.semantic.resolver.identity`
    - ``name``：模板在来源文件中的本地名（诊断显示用）

    frozen 保证可哈希，直接作为模板表等映射的键。
    """

    identity: str
    name: str

    def __str__(self) -> str:
        return f'{self.identity}:{self.name}'


Scope = dict[str, TemplateKey]
"""文件级可见名表：可见名 → 模板真名（:class:`TemplateKey`）。"""


@dataclass(frozen=True)
class ResolvedContext:
    """导入求解（Phase 1）产物：模板图 + 可见名表 + 数据命名空间。

    由 :class:`infinity_data.semantic.resolver.TemplateGraphResolver` 产出，
    供 Phase 2a（构建）经数据模型消费。
    只含名字与模板定义，不含任何约束执行结果（约束求值属 Phase 2），
    也不含诊断——诊断经共享 :class:`DiagnosticCollector` 收集（流水线单一收集器）。

    - ``templates``：全部已加载模板（本地 + ``!from`` 导入）
    - ``template_scopes``：每个模板定义点的可见名表（展开/校验按定义点可见性解析）
    - ``root_scope``：入口文件可见名表（可见名 → :class:`TemplateKey`）
    - ``schema_scope``：schema.from_file 隐式导入的可见名表（无则 None）
    - ``namespace``：``$`` 引用命名空间（``!env`` / ``!file`` / ``!var`` 解析结果，统一为 StdValue）
    """

    templates: dict[TemplateKey, TemplateDef]
    template_scopes: dict[TemplateKey, Scope]
    root_scope: Scope
    schema_scope: Scope | None
    namespace: dict[str, 'StdValue']
