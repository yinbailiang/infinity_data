"""sandbox/errors.py 单元测试：沙盒异常体系。"""

from infinity_data.infra.location import SourceRange
from infinity_data.sandbox import SandboxError
from infinity_data.sandbox.errors import AccessDeniedError, EnvNotAuthorizedError, EnvNotSetError, SchemaError


def test_env_not_authorized() -> None:
    e = EnvNotAuthorizedError('USER')
    assert e.code == 'sandbox.env_unauthorized'
    assert e.params == {'name': 'USER'}
    assert isinstance(e, SandboxError)


def test_env_not_set() -> None:
    e = EnvNotSetError('HOME')
    assert e.code == 'sandbox.env_not_set'
    assert e.params == {'name': 'HOME'}


def test_access_denied() -> None:
    e = AccessDeniedError('文件', './x.json')
    assert e.code == 'sandbox.access_denied'
    assert e.params == {'label': '文件', 'path_src': './x.json'}


def test_schema_error_is_sandbox_error() -> None:
    e = SchemaError('schema.failed', {'detail': 'x'})
    assert e.code == 'schema.failed'
    assert isinstance(e, SandboxError)


def test_message_rendered_with_params() -> None:
    e = EnvNotAuthorizedError('USER', SourceRange.empty())
    assert 'USER' in e.message
    assert str(e) == e.message
