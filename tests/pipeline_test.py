"""流水线端到端测试：词法 → 语法 → 语义 → 降维。"""

from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from infinity_data import SandboxConfig, Severity, compile_source, load
from infinity_data.infra.file import MemFile
from infinity_data.semantic import StdObject


def compile_ok(source: str) -> dict[str, Any]:
    """编译无错误断言，返回降维 dict。"""
    result = compile_source(source)
    errors = [d for d in result.diagnostics if d.severity is Severity.ERROR]
    assert not errors, [f'{d.location}: {d.render()}' for d in errors]
    assert result.value is not None
    return result.value


# ═══════════════════════════════════════════════════════════
# 基础
# ═══════════════════════════════════════════════════════════


def test_empty_source() -> None:
    assert compile_source('').value == {}
    assert compile_source('   \n  \n').value == {}
    assert compile_source('# 只有注释\n#+ 多行注释\n#-\n').value == {}


def test_compile_source_lang_option() -> None:
    """显式 lang 贯穿收集器与诊断渲染（回退链之外不依赖机器环境）。"""
    en = compile_source('x: int = "a"\n', lang='en-US')
    en_diag = next(d for d in en.diagnostics if d.code == 'constraint.type_mismatch')
    assert en_diag.lang == 'en-US'
    assert 'expected int' in en_diag.render()

    zh = compile_source('x: int = "a"\n', lang='zh-CN')
    zh_diag = next(d for d in zh.diagnostics if d.code == 'constraint.type_mismatch')
    assert zh_diag.lang == 'zh-CN'
    assert '期望 int' in zh_diag.render()


def test_mem_file_chars_stream() -> None:
    """MemFile.chars()：O(1) 构造的逐字符迭代流（词法分析输入），可重复构造。"""
    mem = MemFile(name='mem.infd', root_path=Path('.'), content='a = 1\n')
    assert list(mem.chars()) == list('a = 1\n')
    assert ''.join(mem.chars()) == 'a = 1\n'  # 每次构造新迭代器


def test_string_token_base_is_not_instantiable() -> None:
    """StringToken 是抽象基类：拒绝直接实例化（须用单行/多行子类）。"""
    from infinity_data.tokenizer.models.tokens import StringToken

    with pytest.raises(TypeError):
        StringToken()


def test_scalar_fields() -> None:
    value = compile_ok("""
version = "2.0.0"
debug = false
max_retries = 3
ratio: float = 0.75
""")
    assert value == {
        'version': '2.0.0',
        'debug': False,
        'max_retries': 3,
        'ratio': Decimal('0.75'),
    }


def test_nested_object_and_array() -> None:
    value = compile_ok("""
app {
    name = "demo"
    ports [8080, 8081]
    db {
        host = "localhost"
        port = 5432
    }
}
""")
    assert value == {
        'app': {
            'name': 'demo',
            'ports': [8080, 8081],
            'db': {'host': 'localhost', 'port': 5432},
        },
    }


def test_bare_key_is_rejected() -> None:
    """裸 key（无值字段）不属于设计文档定义的语法，应报错。"""
    result = compile_source('feature_flag\ndebug = true\n')
    assert result.has_errors
    assert any(d.code == 'field.missing_value' for d in result.diagnostics)
    # 其余字段不受影响
    assert result.value == {'debug': True}


def test_null_kept_noexist_dropped() -> None:
    value = compile_ok("""
a: str? = null
b = noexist
c = true
""")
    assert value == {'a': None, 'c': True}


def test_comments() -> None:
    value = compile_ok("""
# 单行注释
a = 1
#+ 多行注释
b = 2
#-
c = 3
""")
    assert value == {'a': 1, 'c': 3}


def test_multiline_string() -> None:
    value = compile_ok('script = `md\ntext\n  code\n`\n')
    assert value == {'script': 'text\n  code'}


def test_number_formats() -> None:
    value = compile_ok("""
a = 1e10
b = 2.5e-3
c = -80
""")
    assert value == {'a': Decimal('1E+10'), 'b': Decimal('2.5E-3'), 'c': -80}


def test_special_floats() -> None:
    value = compile_ok('a = nan\nb = +inf\nc = -inf\n')
    assert value['a'].is_nan()
    assert value['b'] == Decimal('Infinity')
    assert value['c'] == Decimal('-Infinity')


# ═══════════════════════════════════════════════════════════
# 模板
# ═══════════════════════════════════════════════════════════


def test_template_instantiation() -> None:
    value = compile_ok("""
~Server {
    host: str = "0.0.0.0"
    port: <int, range(1, 65535)> = 80
}
api Server(port=443, host="api.example.com")
other Server()
""")
    assert value == {
        'api': {'host': 'api.example.com', 'port': 443},
        'other': {'host': '0.0.0.0', 'port': 80},
    }


def test_document_carries_templates_and_scope() -> None:
    """StdDocument 携带模板表与入口文件可见名表（可见名 → 模板）。"""
    result = compile_source("""
~Server {
    host: str = "0.0.0.0"
}
s = Server()
""")
    doc = result.document
    assert doc is not None
    assert not result.has_errors
    # scope：入口文件可见名 → TemplateKey
    assert 'Server' in doc.scope
    # templates：TemplateKey → 定义，能完整解析
    key = doc.scope['Server']
    assert key in doc.templates
    assert doc.templates[key].name == 'Server'


def test_std_object_carries_source_template() -> None:
    """StdObject 携带来源模板：模板展开的实例、模板即约束校验的 dict 均有。"""
    result = compile_source("""
~Server {
    host: str = "0.0.0.0"
}
s = Server()
hand: Server = { host = "x" }
plain = { host = "y" }
""")
    doc = result.document
    assert doc is not None and not result.has_errors
    key = doc.scope['Server']

    def template_of(name: str):
        f = doc.root.get(name)
        assert f is not None and isinstance(f.value, StdObject)
        return f.value.template

    # 模板展开的实例 → 携带来源模板
    assert template_of('s') == key
    # 模板即约束校验的手写 dict → 携带来源模板
    assert template_of('hand') == key
    # 纯 dict 字面量 → 无模板
    assert template_of('plain') is None


def test_template_required_field_missing() -> None:
    result = compile_source("""
~Database {
    name: str
    host: str = "localhost"
}
db Database()
""")
    assert result.has_errors
    assert any(
        d.code == 'template.missing_required' and d.declaration.parameters().get('field') == 'name'
        for d in result.diagnostics
    )


def test_template_positional_and_named_args() -> None:
    value = compile_ok("""
~Database {
    name: str
    host: str = "localhost"
}
db Database("mydb", host="db.internal")
""")
    assert value['db'] == {'name': 'mydb', 'host': 'db.internal'}


def test_template_field_constraint_violation() -> None:
    result = compile_source("""
~Server {
    port: <int, range(1, 100)> = 80
}
s Server(port=200)
""")
    assert result.has_errors
    assert any(d.code in ('constraint.range_below', 'constraint.range_above') for d in result.diagnostics)


def test_template_level_constraint() -> None:
    result = compile_source("""
~Server {
    port: int = 80
    tls: bool = false
    : <when(field(port, eq(443)), field(tls, eq(true)))>
}
bad Server(port=443, tls=false)
good Server(port=80, tls=false)
""")
    assert result.has_errors
    assert any(d.code == 'constraint.eq_mismatch' and 'tls' in d.path for d in result.diagnostics)


def test_template_level_constraint_trailing_comma() -> None:
    """模板内 : 约束后允许尾随逗号（与字段一致）。"""
    result = compile_source("""
~Server {
    port: int = 80,
    tls: bool = false,
    : <when(field(port, eq(443)), field(tls, eq(true)))>,
}
bad Server(port=443, tls=false)
""")
    assert result.has_errors
    assert any(d.code == 'constraint.eq_mismatch' and 'tls' in d.path for d in result.diagnostics)


# ═══════════════════════════════════════════════════════════
# 结构级约束（dict 级约束）
# ═══════════════════════════════════════════════════════════


def test_dict_literal_structure_constraint_violation() -> None:
    """dict 字面量内 : 约束作用于整体，违反时报错。"""
    result = compile_source("""
server {
    host = "node-1"
    port = 443
    : <one(has(host), has(ip))>
    : <when(field(port, eq(443)), field(tls, eq(true)))>
}
""")
    assert result.has_errors
    assert any(
        d.code == 'constraint.field_missing' and d.declaration.parameters().get('field') == 'tls'
        for d in result.diagnostics
    )


def test_dict_literal_structure_constraint_pass() -> None:
    """dict 字面量内 : 约束通过时正常产出。"""
    value = compile_ok("""
server {
    host = "node-1"
    port = 80
    : <one(has(host), has(ip))>
}
""")
    assert value == {'server': {'host': 'node-1', 'port': 80}}


def test_dict_literal_structure_constraint_in_template_default() -> None:
    """模板默认值中的 dict 字面量也执行其结构约束。"""
    result = compile_source("""
~App {
    server: dict = {
        port = 443
        : <when(field(port, eq(443)), field(tls, eq(true)))>
    }
}
a App()
""")
    assert result.has_errors
    assert any(
        d.code == 'constraint.field_missing' and d.declaration.parameters().get('field') == 'tls'
        for d in result.diagnostics
    )


def test_top_level_structure_constraint_violation() -> None:
    """顶层 : 约束作用于编译产物 root。"""
    result = compile_source("""
mode = "prod"
tls = false
: <when(field(mode, eq("prod")), field(tls, eq(true)))>
""")
    assert result.has_errors
    assert any(d.code == 'constraint.eq_mismatch' and 'tls' in d.path for d in result.diagnostics)


def test_top_level_structure_constraint_pass() -> None:
    """顶层 : 约束通过时正常产出。"""
    value = compile_ok("""
mode = "dev"
tls = false
: <when(field(mode, eq("prod")), field(tls, eq(true)))>
""")
    assert value == {'mode': 'dev', 'tls': False}


def test_top_level_structure_constraint_interleaved() -> None:
    """顶层 : 约束可与字段交错书写。"""
    result = compile_source("""
name = "demo"
: has(name)
port = 443
: <when(field(port, eq(443)), field(tls, eq(true)))>
""")
    assert result.has_errors
    # tls 未定义 → field(tls, eq(true)) 触发 field_missing
    assert any(
        d.code == 'constraint.field_missing' and d.declaration.parameters().get('field') == 'tls'
        for d in result.diagnostics
    )


def test_dict_structure_constraint_with_template_name() -> None:
    """dict 字面量结构约束中的模板名按书写位置 scope 解析（模板即约束）。"""
    value = compile_ok("""
~Server {
    host: str = "0.0.0.0"
}
srv = {
    host = "x"
    : Server
}
""")
    assert value['srv'] == {'host': 'x'}


def test_template_as_constraint() -> None:
    value = compile_ok("""
~Server {
    host: str = "0.0.0.0"
    port: int = 80
}
hand: Server = { host = "manual.local", port = 3000 }
""")
    assert value['hand'] == {'host': 'manual.local', 'port': 3000}


def test_template_as_constraint_extra_field_rejected() -> None:
    result = compile_source("""
~Server {
    host: str = "0.0.0.0"
}
hand: Server = { host = "x", extra = 1 }
""")
    assert result.has_errors
    assert any(d.code == 'template.extra_field' for d in result.diagnostics)


def test_template_as_constraint_allow_extra() -> None:
    value = compile_ok("""
~Server(allow_extra=true) {
    host: str = "0.0.0.0"
}
hand: Server = { host = "x", extra = 1 }
""")
    assert value['hand'] == {'host': 'x', 'extra': 1}


def test_undefined_template() -> None:
    result = compile_source('x = DoesNotExist()\n')
    assert result.has_errors
    assert any(d.code == 'template.undefined' for d in result.diagnostics)


# ═══════════════════════════════════════════════════════════
# 模板头部配置（TemplateConfig，语法层解析）
# ═══════════════════════════════════════════════════════════


def test_template_config_unknown_key_is_error() -> None:
    """未知配置键 → 语法层报错（dataclass 字段即白名单）。"""
    result = compile_source('~X(unknown_key=true) {\n    a: int = 1\n}\n')
    assert result.has_errors
    assert any(d.code == 'parse.template_config_unknown' for d in result.diagnostics)


def test_template_config_type_error() -> None:
    """配置值类型不匹配 → 语法层报错。"""
    result = compile_source('~X(allow_extra="yes") {\n    a: int = 1\n}\n')
    assert result.has_errors
    assert any(d.code == 'parse.template_config_type' for d in result.diagnostics)


def test_template_config_non_literal_is_error() -> None:
    """配置值必须是字面量（$ 引用 / 复杂值 → 报错）。"""
    result = compile_source('~X(description=$VAR) {\n    a: int = 1\n}\n')
    assert result.has_errors
    assert any(d.code == 'parse.template_config_value' for d in result.diagnostics)


def test_template_config_positional_false() -> None:
    """positional=false：位置参数 → ERROR，命名参数正常。"""
    bad = compile_source("""
~X(positional=false) {
    a: int
}
x = X(1)
""")
    assert bad.has_errors
    assert any(d.code == 'template.positional_disabled' for d in bad.diagnostics)
    # 放宽必填绑定：位置值仍绑定必填字段，不产生 missing_required 级联
    assert not any(d.code == 'template.missing_required' for d in bad.diagnostics)
    assert bad.value == {'x': {'a': 1}}

    good = compile_source("""
~X(positional=false) {
    a: int = 1
}
x = X(a=2)
""")
    assert not good.has_errors, [d.render() for d in good.diagnostics]
    assert good.value == {'x': {'a': 2}}


def test_template_arg_conflict_named_wins() -> None:
    """同一字段同时以位置与命名参数提供 → ERROR（arg_conflict），命名优先。"""
    result = compile_source("""
~X {
    a: int
}
x = X(3, a=2)
""")
    assert result.has_errors
    assert any(d.code == 'template.arg_conflict' for d in result.diagnostics)
    # 命名优先：位置 3 被忽略
    assert result.value == {'x': {'a': 2}}


def test_template_unknown_named_argument_is_error() -> None:
    """未知命名参数 → ERROR（拒绝静默忽略）。"""
    result = compile_source("""
~X {
    a: int = 1
}
x = X(bogus=2)
""")
    assert result.has_errors
    assert any(d.code == 'template.unknown_argument' for d in result.diagnostics)
    # 合法字段不受影响
    ok = compile_source("""
~X {
    a: int = 1
}
x = X(a=2)
""")
    assert not ok.has_errors


def test_template_allow_extra_true_accepts_named_args() -> None:
    """allow_extra=true：实例化接受额外命名参数并作为扩展字段内容。"""
    value = compile_ok("""
~X(allow_extra=true) {
    a: int = 1
}
x = X(a=2, bogus=3)
""")
    assert value == {'x': {'a': 2, 'bogus': 3}}


def test_template_allow_extra_true_accepts_extra_alone() -> None:
    """allow_extra=true：只有额外参数也可（默认值生效 + 扩展字段）。"""
    value = compile_ok("""
~X(allow_extra=true) {
    a: int = 1
}
x = X(extra = {k = 1})
""")
    assert value == {'x': {'a': 1, 'extra': {'k': 1}}}


def test_template_allow_extra_false_rejects_named_args() -> None:
    """allow_extra=false（默认）：额外命名参数 → unknown_argument ERROR，不进入内容。"""
    result = compile_source("""
~X {
    a: int = 1
}
x = X(a=2, bogus=3)
""")
    assert result.has_errors
    assert any(d.code == 'template.unknown_argument' for d in result.diagnostics)
    # 额外参数不进入内容（字段展开只遍历声明字段）
    assert result.value == {'x': {'a': 2}}


def test_template_config_description_metadata() -> None:
    """description 是合法元数据（不消费，仅解析通过）。"""
    result = compile_source('~X(description="服务模板") {\n    a: int = 1\n}\nx = X()\n')
    assert not result.has_errors


def test_required_before_optional_rule() -> None:
    result = compile_source("""
~Bad {
    a: int = 1
    b: int
}
""")
    assert result.has_errors
    assert any(d.code == 'template.required_order' for d in result.diagnostics)


def test_required_order_relaxed_when_positional_disabled() -> None:
    """positional=false 模板：无位置绑定，允许必填与可选交错。"""
    good = compile_source("""
~X(positional=false) {
    a: int = 1
    b: int
}
x = X(b=2)
""")
    assert not good.has_errors, [d.render() for d in good.diagnostics]
    assert good.value == {'x': {'a': 1, 'b': 2}}

    # 普通模板仍强制必填在前
    bad = compile_source("""
~X {
    a: int = 1
    b: int
}
""")
    assert bad.has_errors
    assert any(d.code == 'template.required_order' for d in bad.diagnostics)


def test_template_shadowing_builtin_type_is_error() -> None:
    """~int 与内置类型约束同名 → ERROR，且内置 int 不被遮蔽。"""
    result = compile_source("""
~int {
    v: str = "tpl"
}
a: int = 10
""")
    assert result.has_errors
    assert any(d.code == 'template.shadows_builtin' for d in result.diagnostics)
    # 内置 int 保持可用：a: int = 10 通过，且无"期望 int（对象）"类错误
    assert result.value == {'a': 10}
    assert not any(d.code == 'template.expect_object' for d in result.diagnostics)


def test_template_shadowing_builtin_constraint_is_error() -> None:
    """~range 与内置约束同名 → ERROR，range(1, 100) 仍按内置语义执行。"""
    result = compile_source("""
~range {
    lo: int = 1
}
a: <range(1, 100)> = 42
b: <range(1, 100)> = 200
""")
    assert result.has_errors
    assert any(d.code == 'template.shadows_builtin' for d in result.diagnostics)
    # range 仍为内置：200 超出上界报错
    assert any(d.code == 'constraint.range_above' for d in result.diagnostics)


def test_template_duplicate_definition_is_error() -> None:
    """同文件同名模板重复定义 → ERROR，保留首次定义（拒绝隐式覆盖）。"""
    result = compile_source("""
~Server {
    port: int = 80
}
~Server {
    host: str = "x"
}
s = Server()
""")
    assert result.has_errors
    assert any(d.code == 'template.duplicate' for d in result.diagnostics)
    # 首次定义被保留：Server 只有 port 字段
    assert result.value == {'s': {'port': 80}}


def test_duplicate_template_still_validates_internals() -> None:
    """重复定义的模板仍校验内部（必填排序），一次暴露所有错误。"""
    result = compile_source("""
~Server {
    port: int = 80
}
~Server {
    a: int = 1
    b: int
}
""")
    assert result.has_errors
    assert any(d.code == 'template.duplicate' for d in result.diagnostics)
    # 第二个模板的内部错误也报了（必填字段出现在可选字段之后）
    assert any(d.code == 'template.required_order' for d in result.diagnostics)


def test_template_duplicate_field_reported_at_definition_time() -> None:
    """模板定义内重复字段：未实例化也报 dict.duplicate_key（保留先到者）。"""
    result = compile_source("""
~T {
    a: int = 1,
    a: int = 2
}
""")
    assert result.has_errors
    assert [d.code for d in result.diagnostics].count('dict.duplicate_key') == 1


def test_template_duplicate_field_instantiated_single_diagnostic() -> None:
    """重复字段在定义期去重：实例化不再二次报告，输出保留先到者。"""
    result = compile_source('~T {\n    a: int = 1\n    a: int = 2\n}\nt = T()\n')
    assert [d.code for d in result.diagnostics].count('dict.duplicate_key') == 1
    assert result.value == {'t': {'a': 1}}


def test_template_duplicate_field_and_missing_args_reported_together() -> None:
    """一次编译暴露全部定义期错误（重复字段 + 约束缺参数）。"""
    result = compile_source("""
~Test1(extra_positional_vars="rest") {
    _1: int, _2: int, _2: int, _2: int, _2: int,
    rest: list,
    test: any
}
""")
    codes = [d.code for d in result.diagnostics]
    assert codes.count('dict.duplicate_key') == 3
    assert codes.count('constraint.arg_count') == 1


def test_template_constraint_missing_args_reported_at_definition_time() -> None:
    """模板未实例化时，约束参数个数不符在定义期报 constraint.arg_count。"""
    result = compile_source('~T {\n    x: any\n}\n')
    assert result.has_errors
    assert any(d.code == 'constraint.arg_count' for d in result.diagnostics)


def test_template_constraint_unknown_name_reported_at_definition_time() -> None:
    """模板未实例化时，未知约束名在定义期报 constraint.unknown。"""
    result = compile_source('~T {\n    x: nosuch\n}\n')
    assert result.has_errors
    assert any(d.code == 'constraint.unknown' for d in result.diagnostics)


def test_template_constraint_static_valid_no_false_positive() -> None:
    """合法声明（模板即约束、可空语法糖、多参数逻辑约束）无静态误报。"""
    result = compile_source("""
~A {
    a: int = 1
}
~B {
    x: A = A(),
    y: str? = null,
    z: <any(int, str)> = 1,
    w: <range(1, 10)> = 5
}
""")
    assert not result.has_errors, [d.render() for d in result.diagnostics]


def test_template_constraint_bad_signature_reported_once() -> None:
    """同一非法签名只在定义期报一次，不在默认值与实例化处重复/级联。"""
    result = compile_source('~T {\n    x: any = 1\n}\nt = T()\n')
    diags = [d for d in result.diagnostics if d.code == 'constraint.arg_count']
    assert len(diags) == 1
    assert diags[0].path == ''


# ═══════════════════════════════════════════════════════════
# 模板默认值 / 完整形状（定义期）
# ═══════════════════════════════════════════════════════════


def test_template_default_validated_at_definition_time() -> None:
    """默认值不依赖实例化：非法默认值在定义期即报（路径 Template.field）。"""
    result = compile_source('~T {\n    tmp: dict = 123\n}\n')
    assert result.has_errors
    diag = next(d for d in result.diagnostics if d.code == 'constraint.type_mismatch')
    assert diag.path == 'T.tmp'


def test_template_default_reported_once_at_definition() -> None:
    """默认值错误只在定义点报一次（同源位置去重）。"""
    result = compile_source('~T {\n    tmp: dict = 123\n}\nx = T()\n')
    paths = {d.path for d in result.diagnostics if d.code == 'constraint.type_mismatch'}
    assert paths == {'T.tmp'}


def test_template_valid_default_no_error() -> None:
    """合法默认值（含嵌套模板 / 可空字面量）不误报。"""
    result = compile_source("""
~Inner {
    v: dict = {}
}
~T {
    inner: Inner = Inner(),
    n: int = 1,
    s: str? = null
}
""")
    assert not result.has_errors, [d.render() for d in result.diagnostics]


def test_validator_requires_optional_fields() -> None:
    """校验器要求完整形状：可选字段缺失 → template.missing_optional（不注入默认值）。"""
    result = compile_source('~T {\n    tmp: dict = {}\n}\na: T {}\n')
    assert result.has_errors
    diag = next(d for d in result.diagnostics if d.code == 'template.missing_optional')
    assert diag.path == 'a.tmp'
    assert result.value == {'a': {}}


def test_validator_provided_optional_field_validated() -> None:
    """完整形状下，提供的可选字段照常执行约束。"""
    result = compile_source('~T {\n    tmp: dict = {}\n}\na: T { tmp = 123 }\n')
    assert any(d.code == 'constraint.type_mismatch' for d in result.diagnostics)


def test_absent_suffix_allows_missing_field() -> None:
    """`!`：约束接受 noexist → 校验器允许字段缺失。"""
    result = compile_source('~T {\n    opt: dict! = {}\n}\na: T {}\n')
    assert not result.has_errors, [d.render() for d in result.diagnostics]


def test_absent_nullable_suffix_allows_missing_or_null() -> None:
    """`?!`：字段可缺失、可为 null；两者都通过。"""
    missing = compile_source('~T {\n    opt: dict?! = {}\n}\na: T {}\n')
    null = compile_source('~T {\n    opt: dict?! = {}\n}\na: T { opt = null }\n')
    assert not missing.has_errors, [d.render() for d in missing.diagnostics]
    assert not null.has_errors, [d.render() for d in null.diagnostics]


def test_nullable_suffix_does_not_allow_missing() -> None:
    """`?` 仅允许 null：字段仍须声明（完整形状）。"""
    result = compile_source('~T {\n    opt: dict? = {}\n}\na: T {}\n')
    assert any(d.code == 'template.missing_optional' for d in result.diagnostics)


def test_reverse_postfix_order_warns_but_is_equivalent() -> None:
    """`!?` 与 `?!` 等价，但报 parse.postfix_order 警告。"""
    result = compile_source('x: int!? = null\n')
    assert not result.has_errors, [d.render() for d in result.diagnostics]
    assert any(d.code == 'parse.postfix_order' for d in result.warnings)
    assert result.value == {'x': None}


def test_bare_nullable_absent_markers_combine() -> None:
    """裸 `?` / `!` 也支持组合：`?!` / `!?` 等价 any(?, !)。"""
    result = compile_source('a: ?! = null\nb: !? = noexist\n')
    assert not result.has_errors, [d.render() for d in result.diagnostics]
    assert any(d.code == 'parse.postfix_order' for d in result.warnings)
    assert result.value == {'a': None}


def test_angle_bare_markers_are_any_not_all() -> None:
    """尖括号内裸 `?!` 是 any(?, !)，不是永远失败的 all(?, !)。"""
    result = compile_source('x: <?!> = null\n')
    assert not result.has_errors, [d.render() for d in result.diagnostics]
    assert result.value == {'x': None}


def test_english_diagnostics_do_not_contain_chinese_params() -> None:
    """英文渲染不应混入中文：覆盖历史“参数即文案”的声明。"""
    import re

    samples = [
        'x: ip4 = "999.1.1.1"\n',
        'x: email = "bad"\n',
        'x: same_target(1) = p"a"\n',
        'x: extension(3) = p"a.txt"\n',
        '!template\n',
        '!file .a[\n',
    ]
    for source in samples:
        result = compile_source(source, lang='en-US')
        for diagnostic in result.diagnostics:
            message = diagnostic.render(include_location=False)
            assert not re.search(r'[\u4e00-\u9fff]', message), (source, message)


def test_var_value_referenced_reports_once() -> None:
    """被 root 引用的 !var 值只报一次，不在定义点与引用点重复。"""
    result = compile_source('~V {\n    n: int\n}\n!var V(n = "x") import . as v\na = $v\n')
    diags = [d for d in result.diagnostics if d.code == 'constraint.type_mismatch']
    assert len(diags) == 1


def test_assert_statements_validate_values_without_output() -> None:
    """!assert 在编译期校验值，不进入输出；成功静默，失败保留具体约束诊断。"""
    result = compile_source('!assert [1, 3, 4] is <list, each(int)>\n!assert p"." is path\n')
    assert not result.has_errors, [d.render() for d in result.diagnostics]
    assert result.value == {}

    bad = compile_source('!assert [1, "x"] is <list, each(int)>\n')
    assert any(d.code == 'constraint.type_mismatch' for d in bad.diagnostics)
    assert bad.value == {}


def test_assert_can_use_var_values() -> None:
    """!assert 可按本文件 $ 命名空间引用 !var 求值结果。"""
    result = compile_source('!var 1 import . as v\n!assert $v is int\n')
    assert not result.has_errors, [d.render() for d in result.diagnostics]


def test_assert_in_imported_template_file(tmp_path: Path) -> None:
    """.inft 内的 !assert 按该文件 scope 求值，且不会触发 inft.not_allowed。"""
    (tmp_path / 'rules.inft').write_text(
        '~T {\n    x: int\n}\n!assert T(x="bad") is T\n',
        encoding='utf-8',
    )
    app = tmp_path / 'app.infd'
    app.write_text('!from p"rules.inft" import T\na = T(x=1)\n', encoding='utf-8')
    result = load(str(app), sandbox=SandboxConfig(allow_templates=['./rules.inft']))
    assert any(d.code == 'constraint.type_mismatch' for d in result.diagnostics)
    assert not any(d.code == 'inft.not_allowed' for d in result.diagnostics)
    assert result.value == {'a': {'x': 1}}


def test_absent_suffix_rejects_null() -> None:
    """`!` 仅允许 noexist：null 不满足。"""
    result = compile_source('x: int! = null\n')
    assert result.has_errors


def test_imported_template_default_validated(tmp_path: Path) -> None:
    """导入的 .inft 模板默认值同样在定义期校验。"""
    (tmp_path / 'extra.inft').write_text('~Extra {\n    v: int = "oops"\n}\n', encoding='utf-8')
    app = tmp_path / 'app.infd'
    app.write_text('!from p"extra.inft" import Extra\n', encoding='utf-8')
    result = load(str(app), sandbox=SandboxConfig(allow_templates=['./extra.inft']))
    assert result.has_errors
    assert any(d.code == 'constraint.type_mismatch' for d in result.diagnostics)


def test_var_value_constraints_validated() -> None:
    """!var 求值结果携带的约束在编译期校验（含未被 root 引用的 var）。"""
    result = compile_source('~V {\n    n: int\n}\n!var V(n = "x") import . as v\n')
    assert result.has_errors
    diag = next(d for d in result.diagnostics if d.code == 'constraint.type_mismatch')
    assert diag.path == '$v.n'


def test_var_dict_literal_constraints_validated() -> None:
    """!var 的 dict 字面量约束同样编译期校验。"""
    result = compile_source('!var { n: int = "x" } import . as v\n')
    assert any(d.code == 'constraint.type_mismatch' and d.path == '$v.n' for d in result.diagnostics)


# ═══════════════════════════════════════════════════════════
# 导入
# ═══════════════════════════════════════════════════════════


def test_env_import() -> None:
    result = compile_source(
        """\
# 测试 !env import
!env import USER as system_user
!env import HOME

# 测试 $ 引用 + 类型转换
app {
    user = $system_user
    home = $HOME
}
""",
        env={'USER': 'alice', 'HOME': '/home/alice'},
    )
    assert not result.has_errors, [d.render() for d in result.diagnostics]
    assert result.value == {'app': {'user': 'alice', 'home': '/home/alice'}}


def test_file_import(infd_file: Callable[[str, str], Path]) -> None:
    # M3 零信任：!file 需要显式授权（allow_files glob 白名单）
    infd_file(
        'test_config.json',
        """{
    "server": {
        "host": "prod.example.com",
        "port": 443,
        "features": ["http2", "tls1.3"]
    }
}""",
    )
    path = infd_file(
        'test_file_import.infd',
        """\
!file p"test_config.json" as json import .server.host as srv_host, .server.port as srv_port, .server.features as srv_features

config {
    host = $srv_host
    port = $srv_port
    features = $srv_features
}
""",
    )
    result = load(
        path,
        sandbox=SandboxConfig(allow_files=['./test_config.json']),
    )
    assert not result.has_errors, [d.render() for d in result.diagnostics]
    assert result.value == {
        'config': {
            'host': 'prod.example.com',
            'port': 443,
            'features': ['http2', 'tls1.3'],
        },
    }


# ═══════════════════════════════════════════════════════════
# 容错
# ═══════════════════════════════════════════════════════════


def test_missing_separator_in_array() -> None:
    """空格不构成分隔符：[1 2] → parse.missing_separator（尽力恢复两个元素）。"""
    result = compile_source('x = [1 2]\n')
    assert result.has_errors
    assert any(d.code == 'parse.missing_separator' for d in result.diagnostics)
    assert result.value == {'x': [1, 2]}


def test_separator_comma_or_newline() -> None:
    """逗号与换行等价分隔；合法写法不受影响。"""
    assert not compile_source('x = [1, 2, 3]\n').has_errors
    assert not compile_source('x = [1, 2, 3,]\n').has_errors
    assert not compile_source('x = [1\n2\n3]\n').has_errors
    assert not compile_source('x = [1, 2\n3]\n').has_errors
    assert not compile_source('x = {a = 1\nb = 2}\n').has_errors
    assert not compile_source('x = {a = 1, b = 2}\n').has_errors


def test_missing_separator_in_object() -> None:
    result = compile_source('x = {a = 1 b = 2}\n')
    assert result.has_errors
    assert any(d.code == 'parse.missing_separator' for d in result.diagnostics)
    assert result.value == {'x': {'a': 1, 'b': 2}}


def test_missing_separator_in_template_args() -> None:
    result = compile_source('~X {\n    a: int\n    b: int\n}\nx = X(1 2)\n')
    assert result.has_errors
    assert any(d.code == 'parse.missing_separator' for d in result.diagnostics)
    assert result.value == {'x': {'a': 1, 'b': 2}}


def test_missing_separator_in_template_config() -> None:
    """模板配置同受显式分隔符约束：空格分隔 → parse.missing_separator。"""
    bad = compile_source('~X(allow_extra = true positional = false) {\n    a: int\n}\n')
    assert bad.has_errors
    assert any(d.code == 'parse.missing_separator' for d in bad.diagnostics)

    assert not compile_source('~X(allow_extra = true, positional = false) {\n    a: int\n}\n').has_errors
    assert not compile_source('~X(allow_extra = true\npositional = false) {\n    a: int\n}\n').has_errors


def test_error_recovery_unclosed_array() -> None:
    """错误恢复：未闭合数组不应崩溃，且记录错误。"""
    result = compile_source('a = [1, 2\nb = 3\n')
    assert result.has_errors


def test_error_recovery_unclosed_constraints() -> None:
    """错误恢复：未闭合尖括号不应崩溃。"""
    result = compile_source('x: <int = 3\n')
    assert result.has_errors


def test_error_recovery_unknown_char() -> None:
    result = compile_source('a = 1\nb = 2 @\nc = 3\n')
    assert result.has_errors
    assert result.value.get('a') == 1


def test_omit_equals_only_composite_or_template() -> None:
    """省略等号仅限复合值与模板调用；字面量/$ 引用须显式 =（lint 式恢复值）。"""
    assert not compile_source('server { port = 8080 }\n').has_errors
    assert not compile_source('server [1, 2]\n').has_errors

    for src, expect in (
        ('x 123\n', {'x': 123}),
        ('x "str"\n', {'x': 'str'}),
        ('x true\n', {'x': True}),
    ):
        result = compile_source(src)
        assert result.has_errors, src
        assert any(d.code == 'parse.field_requires_equals' for d in result.diagnostics)
        assert result.value == expect  # lint 式：报错但值保留


def test_template_field_requires_constraint() -> None:
    """模板字段必须带类型标注；缺失/为空 → parse.template_field_no_constraint（不崩溃）。"""
    for src in ('~X {\n    a\n}\n', '~X {\n    a:\n}\n', '~X {\n    b = { a }\n}\n'):
        result = compile_source(src)
        assert result.has_errors, src
        assert any(d.code == 'parse.template_field_no_constraint' for d in result.diagnostics), src


def test_value_less_field_reports_and_skips() -> None:
    """模板外字段无值 → field.missing_value + 字段跳过（noexist 语义）。"""
    for src, expect in (
        ('x\n', {}),
        ('x: int\n', {}),
        ('y = {a = 1, x}\n', {'y': {'a': 1}}),
    ):
        result = compile_source(src)
        assert result.has_errors, src
        assert any(d.code == 'field.missing_value' for d in result.diagnostics), src
        assert result.value == expect


def test_value_error_not_double_reported_as_missing() -> None:
    """值解析失败（parse 已报）不再叠加 field.missing_value。"""
    result = compile_source('x = = 5\n')
    assert result.has_errors
    assert any(d.code == 'parse.unrecognized_value' for d in result.diagnostics)
    assert not any(d.code == 'field.missing_value' for d in result.diagnostics)


def test_no_silent_top_level_garbage() -> None:
    """顶层垃圾 token 必须报告（parse.unrecognized_statement），不静默吞掉。"""
    for src in (')\n', '= 5\n'):
        result = compile_source(src)
        assert result.has_errors, src
        assert any(d.code == 'parse.unrecognized_statement' for d in result.diagnostics), src


def test_no_silent_constraint_garbage() -> None:
    """约束起始垃圾 token 必须报告（parse.unrecognized_constraint）。"""
    result = compile_source('x: , = 5\n')
    assert result.has_errors
    assert any(d.code == 'parse.unrecognized_constraint' for d in result.diagnostics)


def test_no_silent_invalid_cast() -> None:
    """$VAR as 非法类型必须报告（parse.invalid_cast）。"""
    result = compile_source('!env import VAR\nx = $VAR as nonsense\n', env={'VAR': '42'})
    assert result.has_errors
    assert any(d.code == 'parse.invalid_cast' for d in result.diagnostics)


def test_noexist_in_array_is_error() -> None:
    """noexist 仅用于 dict 字段；数组元素 → 报错并按 null 处理（位置保留）。"""
    result = compile_source('x = [noexist, 1]\n')
    assert result.has_errors
    assert any(d.code == 'value.noexist_in_array' for d in result.diagnostics)
    assert result.value == {'x': [None, 1]}


def test_three_state_nullability_survives_to_emit() -> None:
    """三态可空在 emit 完整保留：noexist 键丢弃、null 键保留、值保留。"""
    result = compile_source('y = {a = noexist, b = null, c = 1}\n')
    assert not result.has_errors
    assert result.value == {'y': {'b': None, 'c': 1}}


def test_bang_non_import_keyword_is_tokenize_error() -> None:
    """! 后跟非 env/file/from 是词法错误（语言不允许单独 !），其余字段不受影响。"""
    result = compile_source('a = 1\n!bad\nb = 2\n')
    assert result.has_errors
    assert any(d.code == 'tokenize.invalid_bang' for d in result.diagnostics)
    assert result.value == {'a': 1, 'b': 2}


def test_bang_at_eof_is_tokenize_error() -> None:
    """裸 ! 现在是独立标点（后缀/独立标记），语句位置无法解析 → 语法错误。"""
    result = compile_source('a = 1\n!\n')
    assert result.has_errors
    assert result.value == {'a': 1}


# ═══════════════════════════════════════════════════════════
# Golden：综合样例 test.infd
# ═══════════════════════════════════════════════════════════


def test_golden_test_infd() -> None:
    result = compile_source("""\
# ============================================================
# 综合测试：覆盖语言各项语法特性
# ============================================================

# -- 模板定义 -------------------------------------------------

~Server {
    host: str = "0.0.0.0"
    port: <int, range(1, 65535)> = 80
    features: dict {
        caching: <dict?!> = noexist
        compression: bool = true
    }
    tags: <list, each(str)> = ["web"]
}

~Database {
    host: str = "localhost"
    port: int = 5432
    name: str = "mydb"
    pool_size: <int, range(1, 100)> = 10
}

# -- 应用配置 -------------------------------------------------

MyApp {
    # 简单字段 + 类型推断
    version = "2.0.0"
    debug = false
    max_retries = 3

    # 带约束的类型标注
    timeout: <int, range(1, 300)> = 30
    log_level: <str, in("debug", "info", "warn", "error")> = "info"
    ratio: float = 0.75

    # 存在性标记
    experimental_features = noexist
    maintenance_mode = noexist

    # 可空字段
    description: str? = null
    backup_host: str? = "fallback.example.com"

    # 嵌套对象
    database {
        adapter = "postgresql"
        host = "db.internal"
        port = 5432
        credentials {
            username = "admin"
            password = "secret123"
        }
    }

    # 对象数组
    servers [
        {
            name = "api-01"
            ip = "10.0.0.1"
            weight = 100
        }
        {
            name = "api-02"
            ip = "10.0.0.2"
            weight = 80
        }
    ]

    # 模板实例化
    api Server(
        port = 443
        host = "api.example.com"
        features = {
            caching=null
            compression=true
        }
    )
    other Server()
    db Database(pool_size=20)

    # 嵌套对象中使用模板调用
    cache {
        redis Server(host="redis.internal", port=6379)
        ttl_seconds = 3600
    }

    # 多行字符串数组
    allowed_origins [
        "https://app.example.com"
        "https://admin.example.com"
        "http://localhost:3000"
    ]

    # 混合类型数组
    mixed_values [
        42
        3.14
        "hello"
        true
        null
    ]
}
""")
    errors = [d for d in result.diagnostics if d.severity is Severity.ERROR]
    assert not errors, [f'{d.location}: {d.render()}' for d in errors]

    app = result.value['MyApp']
    assert app['version'] == '2.0.0'
    assert app['debug'] is False
    assert app['max_retries'] == 3
    assert app['timeout'] == 30
    assert app['log_level'] == 'info'
    assert app['ratio'] == Decimal('0.75')
    assert app['description'] is None
    assert app['backup_host'] == 'fallback.example.com'
    assert app['database'] == {
        'adapter': 'postgresql',
        'host': 'db.internal',
        'port': 5432,
        'credentials': {'username': 'admin', 'password': 'secret123'},
    }
    assert len(app['servers']) == 2
    assert app['servers'][0]['name'] == 'api-01'
    assert app['api'] == {
        'host': 'api.example.com',
        'port': 443,
        'features': {'caching': None, 'compression': True},
        'tags': ['web'],
    }
    assert app['other'] == {
        'host': '0.0.0.0',
        'port': 80,
        # 模板默认值 caching = noexist → 不出现在输出
        'features': {'compression': True},
        'tags': ['web'],
    }
    assert app['db'] == {
        'host': 'localhost',
        'port': 5432,
        'name': 'mydb',
        'pool_size': 20,
    }
    assert app['cache']['redis'] == {
        'host': 'redis.internal',
        'port': 6379,
        'features': {'compression': True},
        'tags': ['web'],
    }
    assert app['allowed_origins'] == [
        'https://app.example.com',
        'https://admin.example.com',
        'http://localhost:3000',
    ]
    assert app['mixed_values'] == [42, Decimal('3.14'), 'hello', True, None]
    # 裸 key → noexist → 不出现在输出
    assert 'experimental_features' not in app
    assert 'maintenance_mode' not in app


# ── 字符串标识符 ───────────────────────────────


def test_quoted_field_name_e2e() -> None:
    assert compile_ok("'a-b@c$d' = 1\n") == {'a-b@c$d': 1}


def test_quoted_and_bare_same_name_duplicate_key() -> None:
    result = compile_source("'a' = 1\na = 2\n")
    assert 'dict.duplicate_key' in [d.code for d in result.diagnostics]
    assert result.value == {'a': 1}
