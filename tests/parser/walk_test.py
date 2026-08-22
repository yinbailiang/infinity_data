"""AST 通用遍历 walk（节点自带 children）测试。

- walk 深度优先产出所有节点（值 / 约束 / 解包 / 模板调用）
- 每节点恰好一次（无重复）
- walk + isinstance 过滤（identity / builder 依赖提取的用法）
"""

from pathlib import Path

from infinity_data.frontend import parse_source
from infinity_data.infra.file import MemFile
from infinity_data.parser import (
    ArrayValue,
    ConstraintCall,
    ConstraintIdent,
    DictValue,
    Document,
    LiteralValue,
    TemplateCallValue,
    TemplateDef,
    UnpackValue,
    walk,
)


def _parse(src: str) -> Document:
    doc, _ = parse_source(MemFile(name='t.infd', root_path=Path('.'), content=src))
    return doc


def _tpl(doc: Document) -> TemplateDef:
    for s in doc.statements:
        if isinstance(s, TemplateDef):
            return s
    raise AssertionError('no template found')


def test_walk_covers_all_value_nodes() -> None:
    """walk 遍历值树：字面量 / dict / 数组 / 解包 / 模板调用。"""
    doc = _parse('x = { a = [1, *[2]], b = T(c = 3, **{ d = 4 }) }\n')
    nodes = list(walk(doc.statements[0]))
    kinds = {type(n) for n in nodes}
    assert DictValue in kinds
    assert ArrayValue in kinds
    assert UnpackValue in kinds
    assert TemplateCallValue in kinds
    assert LiteralValue in kinds


def test_walk_visits_every_node_once() -> None:
    """每个节点恰好访问一次（无重复无遗漏）。"""
    doc = _parse('~X {\n    a: <int, range(1, 10)> = [1, { b = "s" }]\n    : <one(has(a), has(b))>\n}\n')
    nodes = list(walk(_tpl(doc)))
    assert len(nodes) == len({id(n) for n in nodes})


def test_walk_filters_template_calls() -> None:
    """walk + isinstance 过滤模板调用（identity / builder 依赖提取用法）。"""
    doc = _parse('x = { a = Inner(), b = [Outer()] }\n')
    calls = [n for n in walk(doc.statements[0]) if isinstance(n, TemplateCallValue)]
    assert {c.template_name for c in calls} == {'Inner', 'Outer'}


def test_walk_covers_constraint_tree() -> None:
    """约束树（字段标注 + 结构级约束）里的名字/调用可达。"""
    doc = _parse('~X {\n    a: <int, range(1, 10)> = 1\n    : <one(has(a), has(b))>\n}\n')
    tpl = _tpl(doc)
    ident_names = {n.name for n in walk(tpl) if isinstance(n, ConstraintIdent)}
    call_names = {n.name for n in walk(tpl) if isinstance(n, ConstraintCall)}
    assert {'int', 'a', 'b'} <= ident_names
    assert {'range', 'one', 'has'} <= call_names
