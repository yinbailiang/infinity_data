# InfinityData

声明式配置语言（`.infd` / `.inft`）的 Python 编译器库。

- **编译优先**：`.infd` 是源码，JSON/YAML/TOML 是构建产物
- **模板即约束**：模板定义自动注册为约束校验器
- **零信任默认**：库默认 `deny_all` 沙盒，显式开放而非事后限制
- **结构化错误**：稳定错误码 + 结构化参数 + 多语言渲染

## 快速使用

```python
from infinity_data import load, safe_load, SandboxConfig, Schema

result = load('app.infd')              # 默认零信任
if result.has_errors:
    for d in result.diagnostics:
        print(d.location, d.code, d.message)
else:
    print(result.value)                # 降维后的 dict
```

## 文档导航

| 文档 | 内容 |
|---|---|
| [neo_desg.md](./neo_desg.md) | 语言基础设计（语法 / 类型 / 模板 / 约束） |
| [extra_desg.md](./extra_desg.md) | 库 API / CLI / 生态设计 |
| [impl_desg.md](./impl_desg.md) | 编译器实现层的取舍与假设 |

## 开发

```bash
uv run pytest -q      # 测试
uv run ruff check src tests   # lint
uv run pyright        # 类型检查（strict）
uv run python test.py # 错误报告演示
```
