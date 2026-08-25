"""semantic/builder/models.py 单元测试：StdAst 模型与三态属性。"""

from infinity_data.infra.location import SourceRange
from infinity_data.semantic.builder import StdArray, StdDocument, StdField, StdLiteral, StdObject
from infinity_data.semantic.std import StdNode, is_std_node


def test_std_literal_kinds() -> None:
    assert StdLiteral(kind='null', value=None).kind == 'null'
    assert StdLiteral(kind='noexist', value=None).kind == 'noexist'


def test_std_nodes_inherit_stdnode_source() -> None:
    """std 树节点统一继承 StdNode：source 为 keyword-only、compare=False。"""
    lit = StdLiteral(kind='int', value=3, source=None)
    field = StdField(name='x', value=lit, source=None)
    arr = StdArray(elements=[lit], source=None)
    obj = StdObject(fields=[field], source=None)
    for n in (lit, field, arr, obj):
        assert isinstance(n, StdNode)
        assert n.source is None
        assert is_std_node(n)
    # source 为 keyword-only：位置参数构造照常（kind/value/name 仍可位置传参）
    assert StdLiteral('int', 3).kind == 'int'
    assert StdField('x', lit).name == 'x'
    # compare=False：相等比较忽略来源位置
    s1, s2 = SourceRange.empty(), SourceRange.empty()
    assert StdLiteral(kind='int', value=3, source=s1) == StdLiteral(kind='int', value=3, source=s2)


def test_std_field_three_state() -> None:
    noexist = StdField(name='a', value=StdLiteral(kind='noexist', value=None))
    null = StdField(name='b', value=StdLiteral(kind='null', value=None))
    val = StdField(name='c', value=StdLiteral(kind='int', value=1))
    assert noexist.is_noexist and not noexist.is_null
    assert null.is_null and not null.is_noexist
    assert not val.is_noexist and not val.is_null


def test_std_field_defaults() -> None:
    f = StdField(name='x', value=StdLiteral(kind='int', value=1))
    assert f.source is None
    assert f.constraints == []


def test_std_containers() -> None:
    obj = StdObject(fields=[StdField(name='a', value=StdLiteral(kind='int', value=1))])
    assert len(obj.fields) == 1
    arr = StdArray(elements=[StdLiteral(kind='int', value=1)])
    assert len(arr.elements) == 1


def test_std_document_defaults() -> None:
    doc = StdDocument()
    assert doc.root is not None
    assert doc.templates == {}
    assert doc.scope == {}
