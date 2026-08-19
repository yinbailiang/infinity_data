"""sandbox/config.py 单元测试：SandboxConfig 工厂与零信任语义。"""

from infinity_data.sandbox import SandboxConfig


def test_deny_all_is_zero_trust() -> None:
    c = SandboxConfig.deny_all()
    assert c.env == {}
    assert c.allow_env == []
    assert c.allow_files == []
    assert c.allow_templates == []
    assert c.strict is True


def test_full_access_opens_everything() -> None:
    c = SandboxConfig.full_access()
    assert c.allow_env is None  # None = 全部允许
    assert c.allow_files is None
    assert c.allow_templates is None
    assert c.strict is True


def test_default_equals_deny_all() -> None:
    assert SandboxConfig() == SandboxConfig.deny_all()


def test_bootstrap_by_kwargs() -> None:
    """自举：SandboxConfig(**safe_load(...).value) 直接关键字构造。"""
    c = SandboxConfig(env={'A': '1'}, allow_files=['./x.json'], strict=False)
    assert c.env == {'A': '1'}
    assert c.allow_files == ['./x.json']
    assert c.strict is False
