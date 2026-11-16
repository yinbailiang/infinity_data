"""sandbox/errors.py 单元测试：沙盒异常体系。"""

from infinity_data.infra.diagnostics import Diagnostic
from infinity_data.infra.location import SourceRange
from infinity_data.sandbox import SandboxError, SchemaFailed
from infinity_data.sandbox.errors import (
    AccessDeniedError,
    EnvNotAuthorizedError,
    EnvNotSetError,
    SchemaError,
    SchemaMissingRequired,
)


def test_env_not_authorized() -> None:
    e = EnvNotAuthorizedError('USER')
    assert e.code == 'sandbox.env_unauthorized'
    assert e.declaration.parameters() == {'name': 'USER'}
    assert isinstance(e, SandboxError)


def test_env_not_set() -> None:
    e = EnvNotSetError('HOME')
    assert e.code == 'sandbox.env_not_set'
    assert e.declaration.parameters() == {'name': 'HOME'}


def test_access_denied() -> None:
    e = AccessDeniedError('!file', './x.json')
    assert e.code == 'sandbox.access_denied'
    assert e.declaration.parameters() == {'target': '!file', 'path_src': './x.json'}


def test_schema_error_is_sandbox_error() -> None:
    e = SchemaError(SchemaFailed(count=1))
    assert e.code == 'schema.failed'
    assert isinstance(e, SandboxError)
    assert e.diagnostics == []


def test_schema_error_carries_structured_diagnostics() -> None:
    diagnostic = Diagnostic(SchemaMissingRequired(field='name', template='Cfg'), lang='en-US')
    e = SchemaError(SchemaFailed(count=1), diagnostics=[diagnostic])
    assert e.diagnostics == [diagnostic]
    assert e.messages == [diagnostic.render()]
    assert str(e) == diagnostic.render()


def test_schema_error_multiple_messages() -> None:
    d1 = Diagnostic(SchemaMissingRequired(field='name', template='Cfg'), lang='en-US')
    d2 = Diagnostic(SchemaMissingRequired(field='port', template='Cfg'), lang='en-US')
    e = SchemaError(SchemaFailed(count=2), diagnostics=[d1, d2])
    assert e.messages == [d1.render(), d2.render()]
    assert str(e) == f'{d1.render()}\n{d2.render()}'
    assert e.code == 'schema.failed'


def test_message_rendered_with_params() -> None:
    e = EnvNotAuthorizedError('USER', SourceRange.empty())
    assert 'USER' in e.message
    assert str(e) == e.message
