"""流水线端到端测试：词法 → 语法 → 语义 → 降维。"""

from decimal import Decimal

from infinity_data import compile_source, load
from infinity_data.semantic.models import Severity


def compile_ok(source: str) -> dict:
    """编译无错误断言，返回降维 dict。"""
    result = compile_source(source)
    errors = [d for d in result.diagnostics if d.severity is Severity.ERROR]
    assert not errors, [f'{d.location}: {d.message}' for d in errors]
    assert result.value is not None
    return result.value


# ═══════════════════════════════════════════════════════════
# 基础
# ═══════════════════════════════════════════════════════════


def test_empty_source() -> None:
    assert compile_source('').value == {}
    assert compile_source('   \n  \n').value == {}
    assert compile_source('# 只有注释\n#+ 多行注释\n#-\n').value == {}


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
    assert any('缺少值' in d.message for d in result.diagnostics)
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


def test_template_required_field_missing() -> None:
    result = compile_source("""
~Database {
    name: str
    host: str = "localhost"
}
db Database()
""")
    assert result.has_errors
    assert any('name' in d.message and '未提供' in d.message for d in result.diagnostics)


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
    assert any('range' in d.message or '下界' in d.message or '上界' in d.message for d in result.diagnostics)


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
    assert any('tls' in d.message for d in result.diagnostics)


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
    assert any('额外字段' in d.message for d in result.diagnostics)


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
    assert any('未定义的模板' in d.message for d in result.diagnostics)


def test_required_before_optional_rule() -> None:
    result = compile_source("""
~Bad {
    a: int = 1
    b: int
}
""")
    assert result.has_errors
    assert any('可选字段' in d.message for d in result.diagnostics)


# ═══════════════════════════════════════════════════════════
# 导入
# ═══════════════════════════════════════════════════════════


def test_env_import() -> None:
    result = load('test_import.infd', env={'USER': 'alice', 'HOME': '/home/alice'})
    assert not result.has_errors, [d.message for d in result.diagnostics]
    assert result.value == {'app': {'user': 'alice', 'home': '/home/alice'}}


def test_file_import() -> None:
    result = load('test_file_import.infd')
    assert not result.has_errors, [d.message for d in result.diagnostics]
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


# ═══════════════════════════════════════════════════════════
# Golden：综合样例 test.infd
# ═══════════════════════════════════════════════════════════


def test_golden_test_infd() -> None:
    result = load('test.infd')
    errors = [d for d in result.diagnostics if d.severity is Severity.ERROR]
    assert not errors, [f'{d.location}: {d.message}' for d in errors]

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
