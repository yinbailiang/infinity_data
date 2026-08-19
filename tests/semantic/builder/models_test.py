"""semantic/builder/models.py 单元测试：StdAst 模型与三态属性。"""

from infinity_data.semantic.builder import StdArray, StdDocument, StdField, StdLiteral, StdObject


def test_std_literal_kinds() -> None:
    assert StdLiteral(kind='null', value=None).kind == 'null'
    assert StdLiteral(kind='noexist', value=None).kind == 'noexist'


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
