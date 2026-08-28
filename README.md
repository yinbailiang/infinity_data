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

## 官方工具

随库内置两个命令行工具（`infd-lsp` 语言服务器 + `infd-cov` 配置转换器），
零依赖手写 JSON-RPC / emitter，直接消费编译器的公开 API
（`compile_source` / `parse_source` / `RawTokenizer` / emit / semantic）。
它们的可选运行依赖（PyYAML / tomli-w）统一放在 **`tool` 依赖组**：

```bash
uv sync --group tool          # 安装 tool 组（本地开发）
uv sync --all-groups          # 或安装全部组
```

### 配置转换（infd-cov）

编译 `.infd` / `.inft` → 各种配置格式（YAML / JSON / TOML）：

```bash
infd-cov app.infd                          # → YAML（stdout，零依赖 emitter）
infd-cov app.infd out.json -f json         # → JSON 文件
infd-cov app.infd -f toml                  # → TOML（需 tomli-w，tool 组）
infd-cov app.infd --extract web.spec       # → 点分路径提取
cat a.infd | infd-cov -f json              # stdin → stdout
```

- `--format`：`yaml`（默认，零依赖手写 emitter）/ `json` / `toml`
- `--extract PATH`：点分路径（如 `web.spec.selector`）；空 = 整树
- `--severity LEVEL`：拒绝阈值（`error`/`warning`/`info`/`debug`/`none`，默认 `error`）
- `#env: NAME "VALUE"` 声明的变量在当前进程缺失时自动注入虚拟值
- 演示文件：`examples/app.infd`（干净配置）/ `examples/demo.infd`（含故意错误）

### 语言服务器（LSP）

`infd-lsp`：零依赖手写 JSON-RPC 2.0 over stdio 语言服务器。

```bash
infd-lsp          # 作为任意 LSP 客户端的后端
# 或
python -m infinity_data.tools.lsp
```

#### 已实现的能力

| 能力 | 说明 |
|---|---|
| 诊断 | `didOpen`/`didChange`/`didSave` → `publishDiagnostics`（精确位置 + 稳定错误码 + 中文消息；UTF-16 对齐） |
| 补全 | 命名空间（`$` 触发）+ 内置约束名 + 当前文件可见模板名 + 模板字段（含必填/可选）+ 语言关键字 |
| 悬停 | 约束描述、**顶层字段编译产物投影**（jsonpath + std_to_python/project_output）、模板结构骨架（必填/可选 + description 元数据） |
| 文档大纲 | `documentSymbol`：模板定义（Class）+ 顶层字段（Property） |
| 跳转定义 | `definition`：模板调用 / `!from` 导入 / `$` 引用（含跨文件） |
| 语义令牌 | `semanticTokens`：直接用 `RawTokenizer` 分词（UTF-16 单元对齐；跨行多行字符串按行拆分） |
| 虚拟环境变量 | 扫描 `#env: NAME "VALUE"` 注释，进程未设置时自动注入虚拟值，避免 `env_not_set` 中止编译 |

#### 在 VS Code 中使用

在项目 `.vscode/settings.json` 里用任意支持自定义 LSP 的扩展（如 `lspConfig`）配置：

```json
{
  "lspConfig.servers": [
    { "language": "infd", "cmd": ["infd-lsp"] },
    { "language": "inft", "cmd": ["infd-lsp"] }
  ]
}
```

打开 `.infd` / `.inft` 文件即可获得：诊断波浪线 + 语法高亮（semantic tokens）+ 补全 + 悬停 + 大纲 + 跳转定义。

#### 端到端演示

```bash
uv run python examples/lsp_demo.py   # 自动起服务器 + 走一遍握手 + 打印结果
```

演示文件在 `examples/demo.infd`（故意含若干错误，展示诊断 / 补全 / 悬停 / 高亮）。

## 开发

```bash
uv run pytest -q      # 测试
uv run ruff check src tests   # lint
uv run pyright        # 类型检查（strict）
uv run python test.py # 错误报告演示
```
