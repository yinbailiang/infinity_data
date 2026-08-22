"""模板真名计算：直接依赖组合哈希（§2.5）。

    identity(T) = SHA256(canon(T) || sorted(identity(直接依赖模板)))

- ``canon(T)``：:meth:`TemplateDef.canonical` —— AST 规范化序列化，输出**标准
  infd 源码**（可被 parser 还原，round-trip；排除 source/位置，注释不影响）
- 直接依赖：T 定义文件 scope 中、T 实际引用的模板（值位置模板调用 + 约束中的
  模板名，排除注册约束名——模板名不与已注册约束同名，见 ``template.shadows_builtin``）
- 闭包无需显式计算（Merkle 式）：直接依赖的 identity 已含其自身依赖子树
- 环处理：DFS 栈上的依赖退化为「该模板内容 hash」（不递归），保证终止、确定、路径无关

结果：内容与依赖闭包相同 → 真名相同，与机器/路径无关（可复现构建、可签名）；
依赖语义差异（``!from`` 按定义文件目录解析到不同模板）→ 依赖 identity 不同 →
组合 hash 不同（保留「内容相同但依赖不同 → 不同身份」的区分能力）。
"""

from __future__ import annotations

import hashlib
from collections.abc import Collection

from infinity_data.parser import (
    ConstraintCall,
    ConstraintIdent,
    TemplateCallValue,
    TemplateDef,
    walk,
)
from infinity_data.semantic.resolver.models import Scope, TemplateKey

IDENTITY_PREFIX = 'h:'
CONTENT_HASH_LEN = 16


# ═══════════════════════════════════════════════════════════
# 直接依赖提取
# ═══════════════════════════════════════════════════════════


def extract_dependencies(tpl: TemplateDef, scope: Scope, builtin_names: Collection[str]) -> set[TemplateKey]:
    """模板 T 的直接依赖：walk 遍历 T 定义树，收集模板调用名 + 约束名中的模板名。

    基于 :func:`walk`（节点自带 ``children``）统一遍历——值位置模板调用与
    约束名（模板即约束）都覆盖；注册约束名排除。
    """
    names: set[str] = set()
    for node in walk(tpl):
        if isinstance(node, TemplateCallValue):
            names.add(node.template_name)
        elif isinstance(node, (ConstraintIdent, ConstraintCall)):
            names.add(node.name)
    deps: set[TemplateKey] = set()
    for n in names:
        if n in builtin_names:
            continue  # 注册约束（内置/自定义）名，非模板依赖
        key = scope.get(n)
        if key is not None:
            deps.add(key)
    return deps


# ═══════════════════════════════════════════════════════════
# 依赖闭包组合哈希
# ═══════════════════════════════════════════════════════════


def _content_hash(tpl: TemplateDef) -> str:
    return hashlib.sha256(tpl.canonical().encode('utf-8')).hexdigest()[:CONTENT_HASH_LEN]


def compute_identity_map(
    templates: dict[TemplateKey, TemplateDef],
    template_scopes: dict[TemplateKey, Scope],
    builtin_names: Collection[str],
) -> dict[TemplateKey, TemplateKey]:
    """计算 old → new 的 TemplateKey 映射（新 identity = 依赖闭包组合哈希）。

    - 无环：``identity = hash(content_hash || sorted(依赖 identity))``
    - 环：DFS 栈上依赖退化为内容 hash（不递归）——终止、确定、路径无关
    """
    content_hashes: dict[TemplateKey, str] = {}
    dependencies: dict[TemplateKey, set[TemplateKey]] = {}
    for key, tpl in templates.items():
        content_hashes[key] = _content_hash(tpl)
        dependencies[key] = extract_dependencies(tpl, template_scopes.get(key, {}), builtin_names)

    memo: dict[TemplateKey, str] = {}
    stack: set[TemplateKey] = set()

    def identity_of(key: TemplateKey) -> str:
        if key in memo:
            return memo[key]
        if key in stack:
            return content_hashes[key]  # 环：依赖退化为内容 hash（不递归）
        stack.add(key)
        dep_ids = sorted(identity_of(d) for d in dependencies[key])
        combined = content_hashes[key] + '|' + ','.join(dep_ids)
        ident = IDENTITY_PREFIX + hashlib.sha256(combined.encode('utf-8')).hexdigest()
        memo[key] = ident
        stack.remove(key)
        return ident

    for key in templates:
        identity_of(key)

    return {key: TemplateKey(identity=memo[key], name=key.name) for key in templates}
