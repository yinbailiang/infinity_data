"""sandbox/schema.py 单元测试：Schema 顶层约束配置。"""

from infinity_data.sandbox import Schema


def test_schema_defaults() -> None:
    s = Schema(template='App')
    assert s.template == 'App'
    assert s.from_file is None
    assert s.mode == 'strict'


def test_schema_full_config() -> None:
    s = Schema(template='App', from_file='templates/App.inft', mode='lenient')
    assert s.from_file == 'templates/App.inft'
    assert s.mode == 'lenient'


def test_schema_modes() -> None:
    assert Schema(template='A', mode='strip').mode == 'strip'
    assert Schema(template='A', mode='lenient').mode == 'lenient'
