"""官方 LSP 语言能力测试：诊断 / 语义令牌 / 补全 / 悬停 / 大纲 / 定义。"""

from __future__ import annotations

from typing import Any

from infinity_data.tools.lsp import language


def _diag_codes(text: str, file_path: str = 'test.infd') -> list[str]:
    """编译文本并返回属于当前文件的诊断码列表。"""
    return [d['code'] for d in language.analyze(text, file_path)]


def _diag_at(text: str, code: str, file_path: str = 'test.infd') -> dict[str, Any]:
    """返回首个匹配 code 的诊断（断言存在）。"""
    for d in language.analyze(text, file_path):
        if d['code'] == code:
            return d
    raise AssertionError(f'未找到诊断 {code}: {_diag_codes(text, file_path)}')


# ═══════════════════════════════════════════════════════════
# 诊断
# ═══════════════════════════════════════════════════════════


def test_analyze_clean_document() -> None:
    text = 'name = "svc"\nport: <int, range(1, 65535)> = 80\n'
    assert _diag_codes(text) == []


def test_analyze_constraint_violation_position() -> None:
    text = 'port: <int, range(1, 100)> = 200\n'
    d = _diag_at(text, 'constraint.range_above')
    assert d['severity'] == 1  # ERROR
    # 诊断定位到被检查的值 200（第 29 个码点起）
    assert d['range']['start'] == {'line': 0, 'character': 29}
    assert d['range']['end'] == {'line': 0, 'character': 32}


def test_analyze_undefined_template() -> None:
    text = 'ghost = Ghost()\n'
    assert 'template.undefined' in _diag_codes(text)


def test_analyze_dollar_undefined() -> None:
    text = 'x = $NOT_IMPORTED\n'
    assert 'dollar.undefined' in _diag_codes(text)


def test_analyze_severity_warning() -> None:
    """$ 未导入引用 → 警告级诊断。"""
    text = 'x = $NOT_IMPORTED\n'
    d = _diag_at(text, 'dollar.undefined')
    assert d['severity'] == 2  # WARNING


def test_analyze_utf16_range_with_emoji() -> None:
    """含非 BMP 字符（emoji 占 2 个 UTF-16 单元）时位置仍对齐。"""
    text = 'x: <int> = "😀"\n'
    d = _diag_at(text, 'constraint.type_mismatch')
    rng = d['range']
    # 值 "😀" 在码点上跨 [11, 14)，但 emoji 占 2 个 UTF-16 单元 → [11, 15)
    assert rng['start'] == {'line': 0, 'character': 11}
    assert rng['end'] == {'line': 0, 'character': 15}


def test_analyze_virtual_env_injection() -> None:
    """#env 注释声明缺失环境变量 → 注入虚拟值，不产生 env_not_set 中止。"""
    text = '#env: MY_KEY "sk-virtual"\n!env import MY_KEY as k\nx = $k as str\n'
    assert 'env_not_set' not in _diag_codes(text)
    assert language.virtual_env(text) == {'MY_KEY': 'sk-virtual'}


def test_analyze_filters_imported_file_diagnostics(tmp_path: Any) -> None:
    """!from 导入文件里的错误不属于当前文件，不应发布到当前 uri。"""
    (tmp_path / 'lib.inft').write_text('~Bad {\n  x: <int> = "oops"\n}\n', encoding='utf-8')
    text = '!from p"lib.inft" import Bad\nb = Bad()\n'
    # 当前文件路径设为 tmp_path 下的主文件
    codes = _diag_codes(text, str(tmp_path / 'app.infd'))
    # 跨文件诊断（来自 lib.inft 的 constraint.type_mismatch）被过滤
    assert 'constraint.type_mismatch' not in codes
    # Bad 已通过 !from 导入，不应再有 template.undefined
    assert 'template.undefined' not in codes


# ═══════════════════════════════════════════════════════════
# 语义令牌
# ═══════════════════════════════════════════════════════════


def _decode_semantic(text: str) -> list[tuple[int, int, int, int]]:
    """semanticTokens 扁平数组 → (line, char, length, type) 列表。"""
    data = language.semantic_tokens(text, 'test.infd')
    spans: list[tuple[int, int, int, int]] = []
    line = 0
    char = 0
    for i in range(0, len(data), 5):
        line += data[i]
        char = data[i + 1] if data[i] > 0 else char + data[i + 1]
        spans.append((line, char, data[i + 2], data[i + 3]))
    return spans


def test_semantic_tokens_types() -> None:
    text = 'port: <int, range(1, 100)> = 80  # comment\n'
    spans = _decode_semantic(text)
    types = {t for _, _, _, t in spans}
    # operator / number / keyword / comment / variable
    assert 0 in types  # operator
    assert 2 in types  # number
    assert 5 in types  # comment


def test_semantic_tokens_comment_excluded_inside_string() -> None:
    """字符串内的 # 不应被识别为注释。"""
    text = 'a = "x#y"\n# real comment\n'
    spans = _decode_semantic(text)
    comment_rows = [s for s in spans if s[3] == 5]
    # 只有第 1 行（真注释），第 0 行字符串内 # 不算
    assert [r[0] for r in comment_rows] == [1]


def test_semantic_tokens_utf16_length() -> None:
    """emoji 字符串的 length 按 UTF-16 单元计（含引号：1+2+1=4 单元）。"""
    text = 'a = "😀"\n'
    spans = _decode_semantic(text)
    str_spans = [s for s in spans if s[3] == 1]
    assert str_spans, '应有 string 令牌'
    assert str_spans[0][2] == 4  # "😀" = 引号1 + emoji2 + 引号1


# ═══════════════════════════════════════════════════════════
# 补全
# ═══════════════════════════════════════════════════════════


TEMPLATE_TEXT = """
~Server {
    name: str
    host: str = "0.0.0.0"
    port: <int, range(1, 65535)> = 80
}
s = Server()
"""


def test_completion_template_field_inside_call() -> None:
    """光标在 Server() 参数内 → 补全 Server 的字段。"""
    text = TEMPLATE_TEXT
    # Server() 在最后一行（第 6 行），光标在 () 内
    items = language.completion_items(text, 'test.infd', {'line': 6, 'character': 12})
    labels = {it['label'] for it in items}
    assert {'name', 'host', 'port'} <= labels
    host = next(it for it in items if it['label'] == 'host')
    assert host['insertText'] == 'host = '


def test_completion_template_field_after_newline() -> None:
    """换行后输入部分字段名（na）→ 仍补全该模板字段。"""
    text = '~Server {\n  name: str\n  port: int = 80\n}\ns = Server(\n  na\n)\n'
    items = language.completion_items(text, 'test.infd', {'line': 5, 'character': 3})
    labels = [it['label'] for it in items]
    assert labels == ['name']  # 前缀过滤，不被伪嵌套调用 na(...) 干扰


def test_completion_template_field_unterminated() -> None:
    """未闭合模板调用（无右括号）内输入字段名 → 仍补全。"""
    text = '~Server {\n  name: str\n  port: int = 80\n}\ns = Server(\n  na\n'
    items = language.completion_items(text, 'test.infd', {'line': 5, 'character': 3})
    labels = [it['label'] for it in items]
    assert labels == ['name']


def test_completion_template_field_excludes_used() -> None:
    """已填写的参数名不再提示（只提剩余字段）。"""
    text = '~Server {\n  name: str\n  port: int = 80\n}\ns = Server(\n  name = "x"\n  \n)\n'
    items = language.completion_items(text, 'test.infd', {'line': 6, 'character': 3})
    labels = {it['label'] for it in items}
    assert labels == {'port'}


def test_completion_template_field_required_marked() -> None:
    """无默认值的模板字段 → 补全项标记必填。"""
    text = TEMPLATE_TEXT
    items = language.completion_items(text, 'test.infd', {'line': 6, 'character': 12})
    name = next(it for it in items if it['label'] == 'name')
    assert '必填' in name['detail']
    host = next(it for it in items if it['label'] == 'host')
    assert '可选' in host['detail']


def test_completion_dollar_namespace() -> None:
    text = '!env import API_KEY as key\n!env import OTHER\nx = $\n'
    items = language.completion_items(text, 'test.infd', {'line': 2, 'character': 5})
    labels = {it['label'] for it in items}
    assert 'key' in labels  # 别名
    assert 'OTHER' in labels  # 无别名 → 原名


def test_completion_builtin_constraints_and_templates() -> None:
    text = TEMPLATE_TEXT
    items = language.completion_items(text, 'test.infd', {'line': 0, 'character': 0})
    labels = {it['label'] for it in items}
    assert 'int' in labels  # 内置约束
    assert 'range' in labels  # 内置约束
    assert 'Server' in labels  # 可见模板
    assert '!env' in labels  # 关键字


def test_completion_prefix_filter() -> None:
    text = '<int, range(1, 100)> = 80\n'
    items = language.completion_items(text, 'test.infd', {'line': 0, 'character': 1})
    assert all(it['label'].startswith('i') for it in items)
    assert 'int' in {it['label'] for it in items}


# ═══════════════════════════════════════════════════════════
# 悬停
# ═══════════════════════════════════════════════════════════


def test_hover_constraint_description() -> None:
    text = 'port: <int, range(1, 100)> = 80\n'
    h = language.hover(text, 'test.infd', {'line': 0, 'character': 12})  # 在 range 上
    assert h is not None
    assert 'range' in h['contents']['value']
    assert '内置约束' in h['contents']['value']


def test_hover_field_compiled_value() -> None:
    text = 'count = 3\n'
    h = language.hover(text, 'test.infd', {'line': 0, 'character': 1})
    assert h is not None
    assert 'count' in h['contents']['value']
    assert '3' in h['contents']['value']


def test_hover_template_skeleton() -> None:
    text = TEMPLATE_TEXT
    h = language.hover(text, 'test.infd', {'line': 1, 'character': 4})  # ~Server 上
    assert h is not None
    assert '~Server' in h['contents']['value']
    assert 'name' in h['contents']['value']  # 必填字段
    assert '必填' in h['contents']['value']
    assert 'host' in h['contents']['value']
    assert 'port' in h['contents']['value']


def test_hover_template_description_metadata() -> None:
    text = '~Svc(description="服务配置") {\n  port: int = 80\n}\n'
    h = language.hover(text, 'test.infd', {'line': 0, 'character': 3})
    assert h is not None
    assert '服务配置' in h['contents']['value']


# ── 子字段 / 模板实例 / 模板参数 / $ 变量 ──────────────────


HOVER_TEXT = """#env: MY_KEY "sk-virtual"
!env import MY_KEY as k
~Server {
    name: str
    port: int = 80
}
!var {a = 1, b = 2} import . as obj
app {
    servers = [Server(name="api", port=443)]
    features {
        auth = true
    }
    x = $k as str
    y = $obj
}
"""


def test_hover_subfield_value() -> None:
    """嵌套 dict 子字段 → 编译产物投影。"""
    h = language.hover(HOVER_TEXT, 'test.infd', {'line': 9, 'character': 10})  # auth
    assert h is not None
    assert 'auth' in h['contents']['value']
    assert 'true' in h['contents']['value']


def test_hover_subfield_object() -> None:
    """子对象字段 → 编译产物投影（含下级）。"""
    h = language.hover(HOVER_TEXT, 'test.infd', {'line': 9, 'character': 7})  # features
    assert h is not None
    assert 'features' in h['contents']['value']
    assert 'auth' in h['contents']['value']


def test_hover_template_instance() -> None:
    """被实例化的模板调用 → 模板提示（骨架）在前 + 实例预览在后。"""
    h = language.hover(HOVER_TEXT, 'test.infd', {'line': 8, 'character': 17})  # Server
    assert h is not None
    value = h['contents']['value']
    # 模板提示（骨架）
    assert '~Server' in value
    assert '必填' in value
    # 实例预览
    assert '模板实例' in value
    assert 'api' in value
    assert '443' in value
    # 顺序：模板提示在实例预览之前
    assert value.index('~Server') < value.index('模板实例')


def test_hover_template_argument_name() -> None:
    """模板调用命名参数名 → 该参数编译值。"""
    h = language.hover(HOVER_TEXT, 'test.infd', {'line': 8, 'character': 23})  # name= 关键字
    assert h is not None
    assert '模板参数' in h['contents']['value']
    assert 'api' in h['contents']['value']


def test_hover_template_argument_value() -> None:
    """模板调用参数值字面量 → 编译值。"""
    h = language.hover(HOVER_TEXT, 'test.infd', {'line': 8, 'character': 29})  # "api"
    assert h is not None
    assert 'api' in h['contents']['value']


def test_hover_dollar_call_point() -> None:
    """$ 引用（调用点）→ 命名空间值。"""
    h = language.hover(HOVER_TEXT, 'test.infd', {'line': 12, 'character': 10})  # $k
    assert h is not None
    assert 'sk-virtual' in h['contents']['value']


def test_hover_dollar_definition_point() -> None:
    """!env 导入的名字/别名（定义点）→ 命名空间值。"""
    h = language.hover(HOVER_TEXT, 'test.infd', {'line': 1, 'character': 22})  # 别名 k
    assert h is not None
    assert 'sk-virtual' in h['contents']['value']
    # 原名 MY_KEY 也能预览
    h2 = language.hover(HOVER_TEXT, 'test.infd', {'line': 1, 'character': 14})
    assert h2 is not None
    assert 'sk-virtual' in h2['contents']['value']


def test_hover_var_definition_point() -> None:
    """!var 别名（定义点）→ 求值结果。"""
    h = language.hover(HOVER_TEXT, 'test.infd', {'line': 6, 'character': 34})  # obj
    assert h is not None
    assert 'a' in h['contents']['value']
    assert '1' in h['contents']['value']


def test_hover_dollar_call_point_bare() -> None:
    """裸 $ 引用（无 as 转换）→ 命名空间值。"""
    h = language.hover(HOVER_TEXT, 'test.infd', {'line': 13, 'character': 10})  # $obj
    assert h is not None
    assert 'b' in h['contents']['value']
    assert '2' in h['contents']['value']


def test_hover_template_def_field() -> None:
    """模板定义内字段 → 类型 + 默认值。"""
    h = language.hover(HOVER_TEXT, 'test.infd', {'line': 4, 'character': 6})  # port
    assert h is not None
    assert '模板字段' in h['contents']['value']
    assert 'int' in h['contents']['value']
    assert '80' in h['contents']['value']


# ═══════════════════════════════════════════════════════════
# 文档大纲
# ═══════════════════════════════════════════════════════════


def test_document_symbols() -> None:
    text = '~Server {\n  host: str = "x"\n}\nname = "svc"\n'
    symbols = language.document_symbols(text, 'test.infd')
    names = [s['name'] for s in symbols]
    assert names == ['~Server', 'name']
    server = symbols[0]
    assert server['kind'] == 5  # Class
    assert server['range']['start'] == {'line': 0, 'character': 0}
    field = symbols[1]
    assert field['kind'] == 13  # Property


# ═══════════════════════════════════════════════════════════
# 跳转到定义
# ═══════════════════════════════════════════════════════════


def test_definition_template_call() -> None:
    text = '~Server {\n  host: str = "x"\n}\ns = Server()\n'
    loc = language.definition(text, 'test.infd', {'line': 3, 'character': 6})  # Server 上
    assert loc is not None
    assert loc['range']['start'] == {'line': 0, 'character': 0}


def test_definition_dollar_reference() -> None:
    text = '!env import API_KEY as key\nx = $key as str\n'
    loc = language.definition(text, 'test.infd', {'line': 1, 'character': 7})  # $key 上
    assert loc is not None
    assert loc['range']['start']['line'] == 0


def test_definition_unknown_returns_none() -> None:
    text = 'a = 1\n'
    loc = language.definition(text, 'test.infd', {'line': 0, 'character': 2})
    assert loc is None


def test_definition_from_import(tmp_path: Any) -> None:
    """!from 导入的模板 → 定义在外部文件（跨文件 uri）。"""
    (tmp_path / 'lib.inft').write_text('~Tpl {\n  port: int = 80\n}\n', encoding='utf-8')
    text = '!from p"lib.inft" import Tpl\nx = Tpl()\n'
    loc = language.definition(text, str(tmp_path / 'app.infd'), {'line': 1, 'character': 6})
    assert loc is not None
    assert 'lib.inft' in loc['uri']
