"""sandbox/mediator.py 单元测试：glob 匹配器与沙盒授权。"""

from pathlib import Path

import pytest

from infinity_data.sandbox import SandboxConfig, SandboxError
from infinity_data.sandbox.mediator import Sandbox, _match_pattern  # type: ignore[reportPrivateUsage]


def test_match_double_star_crosses_depth() -> None:
    assert _match_pattern('**/*.json', ('configs', 'dev', 'data.json'))
    assert _match_pattern('**/*.json', ('data.json',))  # ** 匹配零段


def test_match_single_star_does_not_cross_separator() -> None:
    assert not _match_pattern('configs/*.json', ('configs', 'dev', 'data.json'))
    assert _match_pattern('configs/*.json', ('configs', 'data.json'))


def test_match_dir_double_star() -> None:
    assert _match_pattern('configs/**', ('configs', 'dev', 'data.json'))
    assert _match_pattern('configs/**', ('configs',))


def test_match_exact_segments() -> None:
    assert _match_pattern('data.json', ('data.json',))
    assert not _match_pattern('data.json', ('configs', 'data.json'))


def test_getenv_injected() -> None:
    sb = Sandbox(SandboxConfig(env={'A': '1'}), base_dir=Path('.'))
    assert sb.getenv('A') == '1'


def test_getenv_unauthorized_raises() -> None:
    sb = Sandbox(SandboxConfig(), base_dir=Path('.'))
    with pytest.raises(SandboxError):
        sb.getenv('A')


def test_getenv_injection_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    """注入值优先于 allow_env 的真实读取。"""
    monkeypatch.setenv('A', 'from-os')
    sb = Sandbox(SandboxConfig(env={'A': 'injected'}, allow_env=['A']), base_dir=Path('.'))
    assert sb.getenv('A') == 'injected'
