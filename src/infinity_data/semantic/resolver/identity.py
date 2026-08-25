"""模板真名计算：直接依赖组合哈希（§2.5，含 `$` 数据依赖）。

    identity(T) = SHA256(canon(T) || sorted(identity(直接依赖模板)) || sorted(import_identity(T 的 $ 引用)))

- ``canon(T)``：:meth:`TemplateDef.canonical` —— AST 规范化序列化，输出**标准
  infd 源码**（可被 parser 还原，round-trip；排除 source/位置，注释不影响）
- 直接依赖：T 定义文件 scope 中、T 实际引用的模板（值位置模板调用 + 约束中的
  模板名，排除注册约束名——模板名不与已注册约束同名，见 ``template.shadows_builtin``）
- ``import_identity``：T 定义文件命名空间中其 `$` 引用对应绑定的**导入真名**（§1.8）
  ——模板身份覆盖数据依赖（!file/!env/!var 来源变化 → 身份变化，可审计）
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
    DollarValue,
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
        key = scope.visible.get(n)
        if key is not None:
            deps.add(key)
    return deps


def extract_import_dependencies(tpl: TemplateDef, scope: Scope) -> set[str]:
    """模板 T 的 `$` 数据依赖：walk 收集 ``$`` 引用名，映射为定义文件命名空间的**导入真名**（§1.8）。

    导入真名由 scope 对象自身携带（``scope.import_identities``）；真名是叶子哈希
    （无递归），直接进入模板身份组合；找不到映射（如 `$` 未定义或该文件无对应
    导入绑定）→ 跳过。数据来源变化 → 导入真名变化 → 模板身份变化。
    """
    idents = scope.import_identities
    if not idents:
        return set()
    names = {node.name for node in walk(tpl) if isinstance(node, DollarValue)}
    return {idents[n] for n in names if n in idents}


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
    """计算 old → new 的 TemplateKey 映射（新 identity = 依赖闭包组合哈希 + $ 数据依赖）。

    - 无环：``identity = hash(content_hash || sorted(依赖 identity) || sorted(导入真名))``
    - 环：DFS 栈上依赖退化为内容 hash（不递归）——终止、确定、路径无关
    - `$` 导入真名由各定义点 scope 自身携带（§1.8，``scope.import_identities``）
    """
    content_hashes: dict[TemplateKey, str] = {}
    dependencies: dict[TemplateKey, set[TemplateKey]] = {}
    import_deps: dict[TemplateKey, set[str]] = {}
    for key, tpl in templates.items():
        content_hashes[key] = _content_hash(tpl)
        scope = template_scopes.get(key, Scope())
        dependencies[key] = extract_dependencies(tpl, scope, builtin_names)
        import_deps[key] = extract_import_dependencies(tpl, scope)

    memo: dict[TemplateKey, str] = {}
    stack: set[TemplateKey] = set()

    def identity_of(key: TemplateKey) -> str:
        if key in memo:
            return memo[key]
        if key in stack:
            return content_hashes[key]  # 环：依赖退化为内容 hash（不递归）
        stack.add(key)
        dep_ids = sorted(identity_of(d) for d in dependencies[key])
        import_ids = sorted(import_deps[key])
        combined = content_hashes[key] + '|' + ','.join(dep_ids) + '|' + ','.join(import_ids)
        ident = IDENTITY_PREFIX + hashlib.sha256(combined.encode('utf-8')).hexdigest()
        memo[key] = ident
        stack.remove(key)
        return ident

    for key in templates:
        identity_of(key)

    return {key: TemplateKey(identity=memo[key], name=key.name) for key in templates}
