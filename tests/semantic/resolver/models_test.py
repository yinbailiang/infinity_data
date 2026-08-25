"""semantic/resolver/models.py 单元测试：Phase 1 数据模型（模板身份 / 可见名表 / 上下文）。"""

from infinity_data.infra.location import SourceRange
from infinity_data.parser import TemplateConfig, TemplateDef
from infinity_data.semantic.builder.models import python_to_std
from infinity_data.semantic.resolver import ResolvedContext, Scope, TemplateKey


def _tpl(name: str) -> TemplateDef:
    return TemplateDef(name=name, fields=[], constraints=[], config=TemplateConfig(), source=SourceRange.empty())


def test_template_key_identity_and_str() -> None:
    key = TemplateKey(identity='/app.infd', name='Server')
    assert key.identity == '/app.infd'
    assert key.name == 'Server'
    assert str(key) == '/app.infd:Server'


def test_template_key_frozen_and_hashable() -> None:
    a = TemplateKey(identity='mem:abc', name='X')
    b = TemplateKey(identity='mem:abc', name='X')
    assert a == b
    assert len({a, b}) == 1  # frozen 可哈希：直接作模板表等映射的键


def test_scope_maps_visible_name_to_key() -> None:
    scope: Scope = Scope(visible={'A': TemplateKey(identity='i', name='A')})
    assert scope.visible['A'].name == 'A'
    # Scope 携带就地解析关联（§1.8）：默认空命名空间 / 无 !var / 无导入真名
    assert scope.namespaces == {}
    assert scope.var_statements == []
    assert scope.import_identities == {}


def test_resolved_context_holds_phase1_product() -> None:
    key = TemplateKey(identity='app.infd', name='A')
    root = Scope(visible={'A': key})
    ctx = ResolvedContext(
        templates={key: _tpl('A')},
        template_scopes={key: root},
        root_scope=root,
        schema_scope=None,
        namespace={'USER': python_to_std('alice')},
    )
    assert ctx.templates[key].name == 'A'
    assert ctx.template_scopes[key] is ctx.root_scope
    assert ctx.schema_scope is None
    assert ctx.namespace['USER'] == python_to_std('alice')
