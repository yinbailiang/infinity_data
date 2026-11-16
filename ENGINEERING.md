# 工程质量

InfinityData 是一个工程纪律驱动的声明式配置语言编译器。以下是所有质量保障措施的
完整说明与当前基线。

---

## 类型安全

### Pyright Strict

生产代码与测试均启用 [Pyright](https://github.com/microsoft/pyright) **strict** 模式，
`src/` 目录**零遮蔽**——没有任何 `# type: ignore` 或 `# pyright: ignore` 注释。

| 指标 | 数值 |
| - | - |
| 类型检查模式 | `strict`（`src/` + `tests/`） |
| 生产代码 `# type: ignore` | **0** |
| 当前错误 | **0 errors, 0 warnings** |

```toml
[tool.pyright]
typeCheckingMode = "strict"
pythonVersion = "3.12"
reportMissingTypeStubs = false
reportMissingImports = "error"
include = ["src", "tests"]
```

### Ruff Lint

启用规则组：`E`（pycodestyle）、`F`（pyflakes）、`I`（isort）、`ASYNC`（异步最佳
实践）、`PLE`（pylint 错误）。仅忽略两条，均有明确理由：

```toml
[tool.ruff.lint]
ignore = [
    "E501",     # 行长度由 formatter 处理
    "ASYNC109", # async 函数的 timeout 参数是有意的 API 设计
]
```

---

## 诊断模型

所有阶段的诊断都是**声明式类型化数据**，核心约定：

- 每个诊断 = 一个 `@dataclass(frozen=True)` 类，继承 `DiagnosticDeclaration`
- `code` / `severity` / `templates` 为 `ClassVar`；其余字段是渲染参数
- `@registry.register` 装饰器在导入期完成注册与校验：`code` 唯一、`en-US` 模板必存、
  占位符必须来自字段或保留上下文、禁止 `Any` / `object`、禁止保留字段名
- `Diagnostic` 持有声明实例 + 源码位置 + 语言；`render()` 产出人类可读消息，
  `to_dict()` 产出结构化报告
- 语言回退链：请求语言 → `en-US` → `zh-CN`；环境探测优先级为
  `LANGUAGE` > `LC_ALL` > `LC_MESSAGES` > `LANG`（C/POSIX 禁用翻译 → `en-US`）；
  不支持的环境 locale 直接回落 `en-US`，避免默认落到中文
- 词法 / 语法 / 语义阶段共用一个 `DiagnosticCollector`；收集器按
  `code + 参数 + 位置 + 级别 + 语言` 去重，定义期已报的静态错误不会在实例化处重复
- 多错误场景（如顶层 schema 校验）由 `SandboxError.diagnostics` 携带完整列表，
  `messages` 逐条渲染，`str(e)` 按行拼接；`code` / 摘要声明只做兜底

---

## 文档覆盖

使用 [interrogate](https://github.com/econchick/interrogate) 检查公开 API 的 docstring
覆盖。

| 指标 | 数值 |
| - | - |
| 公开 API docstring 覆盖 | **85.4%** |
| 最低阈值 | 80% |
| 语言文档 | 5 篇 Markdown（`docs/zh-CN/language/`） |

---

## 测试

### 基线

```text
882 passed · 1.7s
覆盖率: 93%（6981 statements / 473 missed）
```

### 架构

`tests/` 完全镜像 `src/infinity_data/`，命名 `module.py → module_test.py`：

```text
tests/
├── conftest.py / helpers.py     共享 fixture 与 StdAst 断言工具
├── frontend_test.py / pipeline_test.py / sandbox_test.py
├── tokenizer/                  词法、字符流、finalizer、fuzz
├── parser/                     LL(1)、模型、token stream、canonical
├── semantic/                   builder / executor / resolver / registry / std
├── emit/                       JSON / YAML / TOML / 自描述标记
├── infra/                      诊断、位置、文件、LL1 流、路径
├── lsp/                        语言服务器与文档同步
└── sandbox/                    配置、中介、错误
```

### 运行

```bash
uv run pytest -q                                              # 全量
uv run pytest --cov=infinity_data --cov-fail-under=90 -q      # 带覆盖率门禁
uv run pytest tests/parser/ -q                                # 单模块
```

---

## Pre-commit 门禁

> 需要 [uv](https://docs.astral.sh/uv/)。钩子通过 `uv run` 调用工具链，
> 确保所有开发环境使用一致的 venv 与依赖版本。

每次提交自动执行，全部通过才允许 commit：

| 钩子 | 范围 | 作用 |
| - | - | - |
| `ruff-check` | `src/`、`tests/` | Lint + 自动修复 |
| `ruff-format` | `src/`、`tests/` | 格式化 |
| `pyright` | `src/`、`tests/` | 类型检查（`--level error`） |
| `interrogate` | `src/` | docstring 覆盖 >= 80% |
| `pytest-cov` | 全量 | 测试 + 覆盖率 >= 90% |
| `docs-build` | 全量 | `mkdocs build --strict`（导航/链接校验） |
| `agent-kit-check` | 全量 | 智能体规则漂移检查（`agent-kit update --check`） |
| `check-ast` | 全项目 | Python 语法校验 |
| `check-toml/yaml/json` | 全项目 | 配置文件校验 |
| `check-merge-conflict` | 全项目 | 合并冲突残留 |
| `end-of-file-fixer` / `trailing-whitespace` | 非 `.py` | 文件末尾换行 / 行尾空白 |

```bash
uv run pre-commit run --all-files   # 手动全量运行
```

---

## CI/CD

| 工作流 | 触发 | 内容 |
| - | - | - |
| `.github/workflows/test.yml` | push / PR | pre-commit + 3 OS × 2 Python 测试矩阵 |
| `.github/workflows/docs.yml` | `docs/**` / `mkdocs.yml` | `mkdocs build --strict` + GitHub Pages 部署 |
| `.github/workflows/publish.yml` | `v*` tag | 全量测试 → 构建 → GitHub Release → PyPI |

测试矩阵覆盖 Linux / Windows / macOS 与 Python 3.12 / 3.13，跨平台路径语义在
Windows 上实测。

---

## 架构与模块化

```text
文件(.infd/.inft)
  │
  ▼
RawTokenizer → FinalTokenizer → Parser (RawAst)
  │
  ▼
TemplateGraphResolver (Phase 1) → ResolvedContext
  │
  ▼
AstBuilder (Phase 2a) → StdDocument
  │
  ▼
ConstraintExecutor (Phase 2b) → 校验后的 root
  │
  ▼
std_to_python（忠实） / emit（有损投影）
```

| 指标 | 数值 |
| - | - |
| 生产文件 | 64 个 `.py` |
| 生产代码 | ~15.1k 行 |
| 测试文件 | 72 个 `.py`（~10.4k 行） |
| 最大单文件 | `semantic/diagnostics.py` ~1623 行 |
| 次大文件 | `parser/parser.py` ~1434 行、`tools/lsp/language.py` ~1063 行 |

核心约束：

- **单一诊断收集器**：词法 → 语法 → 语义全程复用 `DiagnosticCollector`
- **关键字单一事实源**：Bang / 上下文关键字在 `tokenizer/keywords.py` 统一维护，
  tokenizer 拼写纠正与 LSP 补全 / 高亮从表派生
- **诊断声明化**：每层一个 `diagnostics.py`，`@registry.register` 导入即注册并校验；
  声明字段是类型化参数，`code` / `severity` / `templates` 为 `ClassVar`
- **单一选项载体**：`CompileOptions`（env / sandbox / registry / schema / lang）
- **公共 API 薄包装**：统一走 `pipeline._compile`

---

## 文档体系

| 内容 | 位置 |
| - | - |
| 语言规范（对外） | `docs/zh-CN/language/` |
| 快速开始与 API/CLI/LSP（对外） | `README.md` |
| 设计决策与实现取舍（对内） | `.agents/MEMORY/project/` |
| 工程质量与贡献流程 | `ENGINEERING.md` / `CONTRIBUTING.md` |
| 智能体规则与技能 | `AGENT.md` / `.agents/`（由 `infinity-agent-kit` 生成） |

文档站点通过 MkDocs Material 构建：

```bash
uv run mkdocs serve      # 本地预览
uv run mkdocs build --strict
```

智能体规则由 `infinity-agent-kit` 统一生成与同步：

```bash
uv run agent-kit update          # 按 .agents/agent_kit.toml 重新渲染
uv run agent-kit update --check  # 漂移检查（CI / pre-commit）
```

受管文件（`AGENT.md`、`.agents/FOR_AGENT.md`、`MEMORY_RULE.md`、
`TEMP_FILE_RULE.md`、`SKILLS/*.md`）**不要手改**，否则下次 update 会被覆盖；
项目差异通过 `.agents/agent_kit.toml` 的 `extra_sources` / `toolchain` 表达。

---

## 版本策略

- **SemVer**：`MAJOR.MINOR.PATCH`
- Git tag `v*` 触发 PyPI 发布

### 4.0 迁移提示

- `Diagnostic.message` → `Diagnostic.render()`
- `Diagnostic.params` → `Diagnostic.declaration.parameters()`
- `Diagnostic.severity` 现返回实际级别；覆盖值改名为 `severity_override`
- `<...?> = noexist` → `<...?!>` 或 `<...!>`（`?` 只接受 null）
- 校验器要求完整形状：可选字段缺失会报 `template.missing_optional` /
  `schema.missing_optional`，默认值不注入给定值
- 自定义约束的 `fail_result(code, params)` → `fail_result(declaration)`
- `parse.invalid_json_path` 拆分为 `parse.json_path_*`；关键字期望改为
  `parse.expected_keyword`
- `constraint.invalid_value` 拆分为 `constraint.invalid_ip` /
  `constraint.invalid_email` / `constraint.invalid_url` /
  `constraint.invalid_uuid` / `constraint.invalid_hostname`
- `schema.failed` 不再聚合所有错误：具体错误以 `schema.missing_*` /
  `schema.extra_fields` / `constraint.*` 逐条返回，`SchemaError.diagnostics`
  携带完整列表

---

## 提交规范

遵循 [Conventional Commits](https://www.conventionalcommits.org/zh-hans/)：

```text
<type>(<scope>): <subject>
```

| type | 场景 |
| - | - |
| `feat` | 新功能 |
| `fix` | Bug 修复 |
| `docs` | 文档变更 |
| `test` | 测试补全 |
| `refactor` | 重构（不改行为） |
| `chore` | 版本号、依赖、构建工具 |

`scope` 对应模块名：`tokenizer`、`parser`、`semantic`、`sandbox`、`emit`、`lsp`、
`cov`、`pipeline`、`docs` 等。

示例：

```text
feat(sandbox): fail fast when strict target file is missing
fix(parser): report missing separator inside constraints
docs(language): split language reference into docs site pages
```
