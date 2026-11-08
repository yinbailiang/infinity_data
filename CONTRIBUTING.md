# 贡献指南

## 环境搭建

> 本项目唯一合法的 Python 工具链是 [uv](https://docs.astral.sh/uv/)。

```bash
git clone https://github.com/yinbailiang/infinity_data.git
cd infinity_data
uv sync --group dev
uv run pre-commit install
```

## 目录约定

```text
src/infinity_data/        → 源码（pyright strict，零 # type: ignore）
tests/                    → 测试（与 src 路径镜像）
docs/zh-CN/               → 对外文档（语言规范，MkDocs）
.agents/MEMORY/project/   → 对内记忆（决策 / 实现取舍 / 历史）
README.md                 → 快速开始与 API / CLI / LSP 入口
ENGINEERING.md            → 工程质量标准与指标
```

## 开发循环

1. **改代码** — 修改 `src/infinity_data/` 中的实现
2. **写测试** — 在 `tests/` 镜像路径下编写测试
3. **同步文档** — 语言语义变更更新 `docs/zh-CN/language/`；API 变更更新 README
4. **记录决策** — 涉及设计取舍时更新 `.agents/MEMORY/project/`
5. **验证**

   ```bash
   uv run pytest --cov=infinity_data --cov-fail-under=90 -q
   uv run pre-commit run --all-files
   uv run mkdocs build --strict
   ```

## 文档与记忆

| 内容 | 写入位置 |
| - | - |
| 语言规范（语法/类型/约束/模板/导入/词法） | `docs/zh-CN/language/` |
| 快速开始、库 API、CLI、LSP 用法 | `README.md` |
| 设计决策、实现取舍、历史坑位 | `.agents/MEMORY/project/` |
| 临时草稿与调试输出 | `.agents/TEMP_FILES/tmps/`（不提交） |

新增文档页面时同步 `mkdocs.yml` 的 `nav`；语言章节编号沿用完整规范（§x.y）。

`.agents/` 静态规则（`AGENT.md`、`FOR_AGENT.md`、`MEMORY_RULE.md`、
`TEMP_FILE_RULE.md`、`SKILLS/*.md`）由 `infinity-agent-kit` 生成，**不要手改**。
需要调整项目参数时修改 `.agents/agent_kit.toml`，然后运行：

```bash
uv run agent-kit update          # 重新渲染
uv run agent-kit update --check  # 漂移检查
```

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

详见 [ENGINEERING.md#提交规范](ENGINEERING.md#提交规范)。

## 质量门禁

所有提交前自动运行：Ruff → Pyright → interrogate → pytest（覆盖率 ≥ 90%）→
mkdocs（strict）。

## 发版流程

1. 更新 `pyproject.toml` 中的版本号
2. 全量验证并同步 `ENGINEERING.md` 基准快照
3. 提交：`git commit -m "chore: bump version to X.Y.Z"`
4. 推送：`git push`
5. 打标签：`git tag -a vX.Y.Z` 并 `git push origin vX.Y.Z`
6. CI 自动构建 wheel → GitHub Release → PyPI

详见 [.agents/SKILLS/publish.md](.agents/SKILLS/publish.md)。
