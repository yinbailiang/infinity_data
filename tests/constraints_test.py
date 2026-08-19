"""约束引擎单元测试：类型约束、一般约束、逻辑约束、模板即约束。"""

from decimal import Decimal
from typing import Any

from infinity_data import CompilationResult, compile_source
from infinity_data.semantic.models import Severity


def errors_of(result: CompilationResult) -> list[str]:
    return [d.message for d in result.diagnostics if d.severity is Severity.ERROR]


def compile_ok(source: str) -> dict[str, Any]:
    result = compile_source(source)
    assert not errors_of(result), errors_of(result)
    return result.value


# ═══════════════════════════════════════════════════════════
# 类型约束
# ═══════════════════════════════════════════════════════════


def test_type_int_rejects_float() -> None:
    result = compile_source('x: int = 1.5\n')
    assert result.has_errors


def test_type_float_rejects_int() -> None:
    """约束只校验不转换：float 约束不接受 int（无自动提升）。"""
    result = compile_source('x: float = 3\n')
    assert result.has_errors
    assert any(d.code == 'constraint.type_mismatch' for d in result.diagnostics)


def test_type_nullable() -> None:
    value = compile_ok('a: str? = null\nb: str? = "x"\nc: int? = 7\n')
    assert value == {'a': None, 'b': 'x', 'c': 7}


def test_pure_nullable_question() -> None:
    value = compile_ok('a: ? = null\nb: ? = noexist\n')
    assert value == {'a': None}  # noexist 不出现


def test_special_float_passes_float_constraint() -> None:
    value = compile_ok('a: float = nan\nb: float = +inf\n')
    assert value['a'].is_nan()
    assert value['b'] == Decimal('Infinity')


# ═══════════════════════════════════════════════════════════
# 一般约束
# ═══════════════════════════════════════════════════════════


def test_range() -> None:
    compile_ok('x: <int, range(1, 100)> = 50\n')
    compile_ok('x: <int, range(1,)> = 50\n')  # 单参数 = 下界
    assert compile_source('x: <int, range(1, 100)> = 200\n').has_errors


def test_size() -> None:
    compile_ok('s: <str, size(1, 5)> = "abc"\n')
    assert compile_source('s: <str, size(1, 5)> = "abcdef"\n').has_errors
    compile_ok('l: <list, size(2, 2)> = [1, 2]\n')


def test_in() -> None:
    compile_ok('x: <str, in("a", "b")> = "a"\n')
    assert compile_source('x: <str, in("a", "b")> = "c"\n').has_errors


def test_each_nested_call() -> None:
    """each 内嵌调用约束（旧版实现会丢失嵌套调用）。"""
    compile_ok('x: <list, each(in("a", "b"))> = ["a", "b"]\n')
    assert compile_source('x: <list, each(in("a", "b"))> = ["a", "c"]\n').has_errors


def test_each_on_dict() -> None:
    compile_ok('x: <dict, each(int)> = { a = 1, b = 2 }\n')
    assert compile_source('x: <dict, each(int)> = { a = 1, b = "x" }\n').has_errors


def test_ip_family() -> None:
    compile_ok('a: ip = "192.168.0.1"\nb: ip4 = "10.0.0.1"\nc: ip6 = "::1"\n')
    assert compile_source('a: ip = "999.1.1.1"\n').has_errors
    assert compile_source('b: ip4 = "::1"\n').has_errors


def test_regex() -> None:
    compile_ok('x: regex("a+") = "aaa"\n')
    assert compile_source('x: regex("a+") = "bbb"\n').has_errors


def test_email_url_uuid_hostname() -> None:
    compile_ok("""
a: email = "user@example.com"
b: url = "https://example.com/x"
c: uuid = "550e8400-e29b-41d4-a716-446655440000"
d: hostname = "api.example.com"
""")
    assert compile_source('a: email = "not-an-email"\n').has_errors
    assert compile_source('b: url = "not a url"\n').has_errors
    assert compile_source('c: uuid = "xyz"\n').has_errors
    assert compile_source('d: hostname = "-bad-.com"\n').has_errors


def test_sign_constraints() -> None:
    compile_ok('a: positive = 1\nb: negative = -1\nc: nonnegative = 0\n')
    assert compile_source('a: positive = -1\n').has_errors
    assert compile_source('b: negative = 1\n').has_errors
    assert compile_source('c: nonnegative = -1\n').has_errors


def test_eq() -> None:
    compile_ok('x: eq(42) = 42\n')
    assert compile_source('x: eq(42) = 43\n').has_errors


def test_eq_works_on_std_nodes() -> None:
    """eq 直接在 Std 节点上比较：int/float 数值交叉相等，bool 与 int 不相等。"""
    compile_ok('x: <float, eq(42)> = 42.0\n')  # 同类型；约束不做 int→float 提升
    compile_ok('x: <int, eq(1)> = 1\n')
    # Python True == 1 的陷阱被 Std 语义排除
    assert compile_source('x: eq(1) = true\n').has_errors
    assert compile_source('x: eq(true) = 1\n').has_errors


def test_eq_object_and_array_structure() -> None:
    """约束比较直接工作在 Std 节点：数组结构相等（unique 走 Std 比较）。"""
    compile_ok('x: <list, unique> = [1, 2, 3]\n')
    assert compile_source('x: <list, unique> = [1, 2, 1]\n').has_errors


def test_unique() -> None:
    compile_ok('x: unique = [1, 2, 3]\n')
    assert compile_source('x: unique = [1, 2, 1]\n').has_errors


# ═══════════════════════════════════════════════════════════
# 字典约束
# ═══════════════════════════════════════════════════════════


def test_has() -> None:
    compile_ok('x: has(a) = { a = 1 }\n')
    assert compile_source('x: has(a) = { b = 1 }\n').has_errors


def test_field() -> None:
    compile_ok('x: field(port, range(1, 100)) = { port = 80 }\n')
    assert compile_source('x: field(port, range(1, 100)) = { port = 200 }\n').has_errors
    assert compile_source('x: field(missing, int) = { port = 80 }\n').has_errors


# ═══════════════════════════════════════════════════════════
# 逻辑约束
# ═══════════════════════════════════════════════════════════


def test_not() -> None:
    compile_ok('x: not(eq(1)) = 2\n')
    assert compile_source('x: not(eq(1)) = 1\n').has_errors


def test_any() -> None:
    compile_ok('x: <any(int, str)> = 5\nx2: <any(int, str)> = "s"\n')
    assert compile_source('x: <any(int, str)> = true\n').has_errors


def test_one() -> None:
    compile_ok('x: <one(int, str)> = 5\nx2: <one(int, str)> = "s"\n')
    assert compile_source('x: <one(int, eq(5))> = 5\n').has_errors  # 两个都满足


def test_all_default_sugar() -> None:
    """<a, b> 等价 all(a, b)。"""
    compile_ok('x: <int, range(1, 10)> = 5\n')
    assert compile_source('x: <int, range(1, 10)> = "s"\n').has_errors


def test_when() -> None:
    compile_ok("""
x: <dict, when(field(mode, eq("prod")), field(tls, eq(true)))> = {
    mode = "dev"
    tls = false
}
""")
    assert compile_source("""
x: <dict, when(field(mode, eq("prod")), field(tls, eq(true)))> = {
    mode = "prod"
    tls = false
}
""").has_errors


def test_unknown_constraint() -> None:
    result = compile_source('x: not_a_constraint = 1\n')
    assert result.has_errors
    assert any(d.code == 'constraint.unknown' for d in result.diagnostics)


# ═══════════════════════════════════════════════════════
# NaN 防护：Decimal NaN 参与比较会抛 InvalidOperation，必须产出诊断而非崩溃
# ═══════════════════════════════════════════════════════


def test_nan_with_range_does_not_crash() -> None:
    result = compile_source('x: <float, range(1, 100)> = nan\n')
    assert result.has_errors
    assert any(d.code == 'constraint.nan_not_allowed' for d in result.diagnostics)


def test_nan_with_sign_constraints_does_not_crash() -> None:
    result = compile_source('a: positive = nan\nb: negative = nan\nc: nonnegative = nan\n')
    assert result.has_errors
    assert any(d.code == 'constraint.nan_not_allowed' for d in result.diagnostics)


def test_nan_with_eq_does_not_crash() -> None:
    """IEEE 754：NaN 不等于自身，eq(nan) 应失败而非崩溃。"""
    result = compile_source('x: eq(nan) = nan\n')
    assert result.has_errors


def test_nan_with_in_and_unique_does_not_crash() -> None:
    result = compile_source('x: <float, in(1, 2)> = nan\n')
    assert result.has_errors
    result2 = compile_source('x: unique = [1, nan, nan]\n')
    # NaN 不与其他值相等 → 不判定重复（不崩溃即可，NaN != NaN）
    assert not result2.has_errors


def test_nan_as_range_argument_is_rejected() -> None:
    result = compile_source('x: <float, range(nan, 100)> = 1\n')
    assert result.has_errors


# ═══════════════════════════════════════════════════════
# 可空约束（? 后缀）：裸 type? 与 <type?> 均须展开为 one(type, ?)
# ═══════════════════════════════════════════════════════


def test_nullable_in_brackets_int() -> None:
    """<int?> 尖括号内可空：null 与值都应通过（回归：曾拆成 <int, ?> 永不满足）。"""
    assert not compile_source('x: <int?> = null\n').has_errors
    assert not compile_source('x: <int?> = 5\n').has_errors


def test_nullable_in_brackets_template() -> None:
    """<A?> 模板可空：null 与合法值都应通过。"""
    src = '~A {\n    v: int = 1\n}\n~B {\n    a: <A?> = null\n}\nb = B(a = null)\n'
    assert not compile_source(src).has_errors
    src2 = '~A {\n    v: int = 1\n}\n~B {\n    a: <A?> = null\n}\nb = B(a = A())\n'
    assert not compile_source(src2).has_errors


def test_nullable_after_constraint_call() -> None:
    """裸约束调用 + ?：regex("a+")? → one(regex("a+"), ?)。"""
    assert not compile_source('x: regex("a+")? = null\n').has_errors
    assert not compile_source('x: regex("a+")? = "aaa"\n').has_errors


def test_nullable_self_referential_template() -> None:
    """自引用模板的可空引用：Node? 嵌套展开应通过。"""
    src = '~Node {\n    child: <Node?> = null\n}\nn = Node(child = Node())\n'
    result = compile_source(src)
    assert not result.has_errors, [d.message for d in result.diagnostics]
    assert result.value == {'n': {'child': {'child': None}}}


# ═══════════════════════════════════════════════════════
# 递归默认值防护（静态环检测，方案 C）
# ═══════════════════════════════════════════════════════


def test_recursive_default_direct() -> None:
    """默认值自引用 → 静态检测 template.recursive_default（不再展开 200 层）。"""
    result = compile_source('~Node {\n    child: Node = Node()\n}\nn = Node()\n')
    assert result.has_errors
    assert any(d.code == 'template.recursive_default' for d in result.diagnostics)
    assert not any(d.code == 'value.nesting_depth' for d in result.diagnostics)


def test_recursive_default_indirect_cycle() -> None:
    """间接环：A 默认 → B，B 默认 → A，均应被标记。"""
    result = compile_source('~A {\n    b: B = B()\n}\n~B {\n    a: A = A()\n}\nx = A()\n')
    assert result.has_errors
    assert any(d.code == 'template.recursive_default' for d in result.diagnostics)


def test_recursive_default_unused_still_detected() -> None:
    """未实例化的递归默认模板也应被静态检测（定义即非法）。"""
    result = compile_source('~Node {\n    child: Node = Node()\n}\n')
    assert result.has_errors
    assert any(d.code == 'template.recursive_default' for d in result.diagnostics)


def test_nullable_recursive_default_is_legal() -> None:
    """可空递归 + 默认 null：默认值为字面量，不构成引用环，合法。"""
    result = compile_source('~Node {\n    child: <Node?> = null\n}\nn = Node()\n')
    assert not result.has_errors, [d.message for d in result.diagnostics]


# ═══════════════════════════════════════════════════════════
# 模板即约束（嵌套与可空）
# ═══════════════════════════════════════════════════════════


def test_template_as_constraint_with_each() -> None:
    value = compile_ok("""
~Endpoint {
    path: str = "/"
    method: str = "GET"
}
cluster: <list, each(Endpoint)> = [
    { path = "/users", method = "GET" },
    { path = "/users", method = "POST" },
]
""")
    assert value['cluster'] == [
        {'path': '/users', 'method': 'GET'},
        {'path': '/users', 'method': 'POST'},
    ]


def test_template_constraint_required_field_missing() -> None:
    result = compile_source("""
~Database {
    name: str
    host: str = "localhost"
}
db: Database = { host = "h" }
""")
    assert result.has_errors
    assert any(d.code == 'template.missing_field' for d in result.diagnostics)


def test_template_constraint_null_requires_nullable() -> None:
    assert compile_source("""
~Server {
    host: str = "0.0.0.0"
}
x: Server = null
""").has_errors
    compile_ok("""
~Server {
    host: str = "0.0.0.0"
}
x: Server? = null
""")


def test_template_constraint_applies_level_constraints() -> None:
    result = compile_source("""
~Server {
    port: int = 80
    tls: bool = false
    : <when(field(port, eq(443)), field(tls, eq(true)))>
}
hand: Server = { port = 443, tls = false }
""")
    assert result.has_errors
