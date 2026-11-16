# 决策与设计记忆

> **类型**：项目记忆（决策 / 设计）
> **范围**：库 API、安全模型、编译模型、工具链、生态与路线图。
> **语言规范**：[docs/zh-CN/language/](../../../docs/zh-CN/language/index.md)（对外文档）
> **实现取舍**：[internals.md](./internals.md)
> **历史记录**：[history.md](./history.md) · [semantic_pipeline.md](./semantic_pipeline.md)
>
> 本文件是长期维护的项目记忆，记录「为什么这样设计」；对外教程与语言规范见 `docs/`。
>
> **文档状态（v4.0.0，2026-11）**：第 2–5、8 章已按当前代码校准；
> 尚未落地的能力统一标注「规划」。当前实现基线：859 个测试通过、
> ruff 干净、pyright strict 零错误。

---

## 目录

1. [设计取向](#1-设计取向)
2. [库 API 设计](#2-库-api-设计)
3. [安全模型](#3-安全模型)
4. [编译模型](#4-编译模型)
5. [CLI 工具设计](#5-cli-工具设计)
6. [Git 模板生态](#6-git-模板生态)
7. [JSON Schema 双向转换](#7-json-schema-双向转换)
8. [LSP 现状与设计方向](#8-lsp-现状与设计方向)
9. [改进计划](#9-改进计划)

---

## 1. 设计取向

### 1.1 核心哲学

| 原则 | 说明 |
|------|------|
| **渐进增强** | Level 0 裸键值对就能用；按需加类型、加约束、加模板。无概念墙 |
| **编译优先** | .infd 是源码，JSON/YAML/TOML 是构建产物。可审计、可 diff、可签名 |
| **零信任默认** | 库默认 deny all；官方工具（`infd-cov` / `infd-lsp`）默认 full access。显式开放而非事后限制 |
| **模板即约束** | 模板定义三重身份：宏展开、类型校验、JSON Schema 生成 |
| **寄生生态** | 不建新生态，通过编译输出和 JSON Schema 桥接接入已有工具链 |
| **Python-first** | 库 API 为 Python 生态优化；CLI 为通用场景服务 |

### 1.2 不做什么

- ❌ 不做图灵完备 —— 纯声明式，无循环、无递归、无副作用
- ❌ 不做自建 registry —— 寄生 Git，去中心化
- ❌ 不做多语言代码生成 —— 生成 JSON Schema，由已有工具链代劳
- ❌ 不追求往返编译（round-trip）—— 单向编译，产物不可逆回源码

### 1.3 目标用户的心智路径

```
Level 0: "它能替代 YAML"          → 裸键值对
Level 1: "它能防低级类型错误"      → 加 : type
Level 2: "它能保证值的合法性"      → 加约束 range/in/regex
Level 3: "我不想重复写相同结构"    → 抽模板，模板即约束
Level 4: "团队需要共享模板"        → Git 包管理
Level 5: "我要控制安全边界"        → safe_load + SandboxConfig
```

每一步都是在同一种语言、同一个文件中的自然演进。

---

## 2. 库 API 设计

### 2.1 核心入口

```python
from infinity_data import (
    load,               # 加载 + 校验 + 编译 → CompilationResult
    safe_load,          # 零信任加载（deny_all）：禁止所有导入
    compile_source,     # 编译源码字符串 → CompilationResult
    check,              # 仅校验 → list[Diagnostic]
    compile_document,   # 编译为 StdDocument（不降维）
    SandboxConfig,      # 沙盒配置
    SandboxError,       # 沙盒/schema 违规异常基类（load 内部转为诊断）
    Schema,             # 顶层 schema 约束
    SchemaError,        # schema 违规异常（继承 SandboxError）
    CompilationResult,  # 编译结果：document / value / diagnostics / has_errors / warnings
    Diagnostic,         # 诊断（声明实例 + source / path / severity 覆盖 / lang；render() / to_dict()）
    Severity,           # ERROR / WARNING / INFO / DEBUG
)

# 产物输出在独立子包（顶层不导出；可选依赖仅在调用时导入）
from infinity_data.emit import EmitConfig, to_json, to_yaml, to_toml
```

### 2.2 safe_load —— 零信任加载

```python
def safe_load(path: str) -> CompilationResult:
    """零信任加载，等价于 load(path, sandbox=SandboxConfig.deny_all())。

    所有导入语句（!env / !file / !from）均报错；只允许纯字段定义、模板定义、字面量值。
    返回 CompilationResult（.value / .diagnostics / .has_errors），不抛出。

    用途:
    - 读取沙盒配置文件（自举：SandboxConfig(**safe_load(...).value)）
    - 读取纯模板文件 (.inft)
    - 读取不需要外部资源的配置
    """
```

`safe_load` 禁止的能力：
- `!env import` → 报错
- `!file import` → 报错
- `!from import` → 报错
- 只允许：纯字段定义、模板定义、字面量值

### 2.3 load —— 标准加载

```python
def load(
    path: str | Path,
    *,
    env: Mapping[str, str] | None = None,       # 环境变量便捷授权（合并进 sandbox）
    sandbox: SandboxConfig | None = None,       # 默认 deny_all()（零信任，库默认）
    registry: ConstraintRegistry | None = None, # 自定义约束注册表
    schema: Schema | None = None,               # 顶层模板约束
    lang: str | None = None,                    # 诊断语言（zh-CN / en-US；缺省按环境探测）
) -> CompilationResult:
    """加载 .infd/.inft 文件并编译，返回 CompilationResult。

    Args:
        path: 文件路径（相对导入以此为基准）
        其余选项见 CompileOptions（env / sandbox / registry / schema / lang）

    沙盒/schema 违规**不抛出**：编译核心转为 ERROR 诊断，返回空文档
    （result.has_errors / result.diagnostics / result.value）。
    """
```

### 2.4 SandboxConfig —— 沙盒配置

```python
@dataclass
class SandboxConfig:
    """控制 .infd 文件的导入权限。默认零信任（deny_all）。"""

    # ── 环境变量注入：key → value。命中即返回，优先于 allow_env ──
    env: dict[str, str] = field(default_factory=dict)

    # ── 环境变量读取白名单：授权从真实 os.environ 实时读取。
    #    None = 全部允许；[] = 全部禁止（默认，零信任）──
    allow_env: list[str] | None = field(default_factory=lambda: [])

    # ── 文件导入白名单（glob 模式；None = 全部允许；默认 [] = 全部禁止）──
    allow_files: list[str] | None = field(default_factory=lambda: [])

    # ── 模板导入白名单（glob 模式；None = 全部允许；默认 [] = 全部禁止）──
    allow_templates: list[str] | None = field(default_factory=lambda: [])

    # ── 严格模式：True 白名单外或目标不存在 → 抛 SandboxError；False 仅警告 ──
    strict: bool = True

    # ── 工厂方法 ──
    # deny_all()  零信任（库默认）
    # full_access() 全权限（全部环境变量 + 任意文件/模板，CLI 默认）
    # development() 开发模式（**/* 全目录 + 全部环境变量）
    # （无 from_dict；自举直接用 SandboxConfig(**safe_load(...).value) 构造）
```

### 2.5 Schema —— 顶层结构约束

```python
@dataclass
class Schema:
    """顶层模板约束：强制编译产物符合指定模板的结构。"""

    template: str                          # 模板名
    from_file: str | None = None           # 模板所在文件。None = 和配置同文件
    mode: Literal["strict", "lenient", "strip"] = "strict"

    # strict:  额外字段 → 报错。必填字段缺失 → 报错
    # lenient: 额外字段 → 警告。必填字段缺失 → 报错
    # strip:   额外字段 → 静默丢弃。必填字段缺失 → 报错
```

### 2.6 完整加载流程

```python
# ═══════════════════════════════════════════════════════
# 生产级加载：三层保护
# ═══════════════════════════════════════════════════════

from infinity_data import load, safe_load, SandboxConfig, Schema

# 1. 安全读取沙盒定义（Layer 0）——返回 CompilationResult，取 .value 构造沙盒
sandbox = SandboxConfig(**safe_load("environments/production.sandbox.infd").value)

# 2. 带沙盒 + 顶层 schema 加载配置（Layer 1）
result = load(
    "app.infd",
    sandbox=sandbox,
    schema=Schema(
        template="AppConfig",
        from_file="templates/AppConfig.inft",
        mode="strict",
    ),
)
config = result.value   # → dict；result.has_errors / result.diagnostics 可取诊断

# sandbox  → 控制"能读什么"（输入安全）
# schema   → 控制"产出什么"（结构安全）
# 约束链    → 控制"值对不对"（数据安全）
```

### 2.7 转换输出（已实现，emit 层）

> 实现位置：`infinity_data.emit`（**不在** `infinity_data` 顶层导出）。
> 可选运行依赖 PyYAML / tomli-w 由 `tool` extra 提供；
> `infd-cov` 默认 YAML 输出使用零依赖 `yaml_dump`。

```python
from infinity_data import load
from infinity_data.emit import EmitConfig, to_json, to_yaml, to_toml

result = load("app.infd")

json_str = to_json(result.document.root, config=EmitConfig(indent=2))  # std 值
yaml_str = to_yaml(result.value)                                      # 需 PyYAML
toml_str = to_toml(result.value)                                      # 需 tomli-w
```

输出入口：
- `to_json(value, *, config=None)`：JSON 文本；接受 `StdValue`（如
  `result.document.root`，完整选项可用）或 Python 值（如 `result.value`）
- `to_yaml(value, *, config=None)`：基于 PyYAML（未安装 → `ImportError`）
- `to_toml(value, *, config=None)`：基于 tomli-w（未安装 → `NotImplementedError`）
- `yaml_dump(value)`：**零依赖** YAML block emitter（覆盖配置常用值），
  `infd-cov` 默认 YAML 输出使用；不依赖 PyYAML
- `project_output(value)`：纯 Python 值的轻量有损投影（path → POSIX 字符串）
- `dump_to_json` / `load_from_json`：默认开启全部自描述标记的无损 JSON 闭环；
  `restore_python` 负责反向还原
- 无 `to_json_file` 之类写文件 API；写文件由调用方（如 `infd-cov`）完成

分层约定（与 `semantic.std` 的忠实转换区分）：
- `CompilationResult.value` / `std_to_python`：**忠实**（path → `PurePosixPath`、
  float → `Decimal`、noexist → `NOEXIST` 哨兵）
- `emit` 层：**有损投影**（输出格式无需完整性）

特殊值处理（由 `EmitConfig` 控制）：

| 值 | 默认输出 | 自描述标记（可选） |
|---|---|---|
| `noexist` | 键不出现（`keep_noexist=False`） | `{"__type__": "noexist"}`（`keep_noexist=True`） |
| `null` | 保留键，值为 `null` / `None` | — |
| 有限 `float`（Decimal） | JSON 数字（整值转 int） | `{"__type__": "decimal", "num": "1.5"}`（`full_float=True`） |
| `nan` / `+inf` / `-inf` | `{"__type__": "decimal", "num": "NaN"}` 等标记 | 同左（无法用 JSON 数字表达） |
| `path` | POSIX 字符串 | `{"__type__": "path", "path": "/c/foo"}`（`full_path=True`） |

### 2.8 JSON Schema 转换（规划 M5，**尚未实现**）

> `to_json_schema` / `from_json_schema` / `verify_schema_equivalence` 仍为规划 API
> （顶层未导出、仓库内无实现）。约束注册表已预留扩展点：`ConstraintEntry` 计划追加
> json_schema 生成回调。以下为**目标用法**，不代表当前可运行。

```python
from infinity_data import (
    safe_load,
    to_json_schema,
    from_json_schema,
    verify_schema_equivalence,
)

# .inft → JSON Schema
doc = safe_load("templates/server.inft")
schema = to_json_schema(doc, draft="2020-12")

# JSON Schema → .inft
with open("schemas/server.json") as f:
    json_schema = json.load(f)
inft_source = from_json_schema(json_schema)
from_json_schema(json_schema, output="templates/auto_server.inft")

# 双向等价校验
result = verify_schema_equivalence("templates/server.inft", "schemas/server.json")
if not result.equivalent:
    for diff in result.differences:
        print(diff)
```

### 2.9 便捷函数

```python
from infinity_data import check, compile_document

# 仅校验，不输出（等价 load(...).diagnostics）
diagnostics = check("app.infd", sandbox=sandbox, schema=...)
# → list[Diagnostic]

# 编译为 StdDocument（不经过降维，不输出字符串）
doc = compile_document("app.infd", sandbox=sandbox, schema=...)
# → StdDocument，含 .root (StdObject) / .templates / .scope
#   （纯数据，不携带诊断；诊断经 load().diagnostics 获取）
#   沙盒/schema 违规时返回**空文档**（不抛出）
```

---

## 3. 安全模型

### 3.1 分层信任

```
Layer 0: safe_load()
  ├── 零导入能力
  ├── 纯数据 + 模板定义
  └── 输出: dict → SandboxConfig(**value)（无 from_dict，直接关键字构造）

Layer 1: load(sandbox=..., schema=...)
  ├── 受控导入 (sandbox 授权)
  ├── 顶层结构约束 (schema 限定)
  └── 字段级约束 (约束链)
```

### 3.2 两个场景，两种默认

| | 官方工具（`infd-cov` / `infd-lsp`） | 库 (`infd.load()`) |
|------|:--:|:--:|
| **默认 sandbox** | `full_access()`（LSP 补全缺省 `development()`） | `deny_all()` |
| **信任假设** | 用户 = 文件作者 = 机器主人 | 文件作者 ≠ 调用者 |
| **安全模型** | "我信任我自己" | "我不信任输入" |

### 3.3 沙盒控制矩阵

| 导入类型 | sandbox 控制 | 默认 (deny_all) | 默认 (full_access) |
|------|------|:--:|:--:|
| `!env import NAME` | `env` 注入 dict（优先）+ `allow_env` 白名单（OS 实时读取） | ❌ 禁止 | ✅ 真实 OS 环境变量 |
| `!file p"path"` | `allow_files` glob 列表 | ❌ 禁止 | ✅ 任意文件 |
| `!from p"path"` | `allow_templates` glob 列表 | ❌ 禁止 | ✅ 任意模板 |

### 3.4 安全保证

- **确定性**：相同 sandbox + 相同源文件 = 相同编译产物（可复现构建）
- **隔离性**：sandbox 未授权的资源不可读
- **可审计性**：编译产物可提交 Git、可 diff、可 hash、可签名
- **最小权限**：默认 zero，显式开放。不存在"意外泄露"

---

## 4. 编译模型

### 4.1 编译 vs 解释

```
解释型 (Dhall/CUE):
  源码 → 每次运行时解析 + 取远程依赖 → 输出
  问题: 不可审计、不可 diff、产物不可提交 Git

编译型 (InfinityData):
  源码 → 编译 → 构建产物（纯数据，零依赖）
  优势: 可审计、可 diff、可签名、产物可独立部署
```

### 4.2 编译流水线

```
文件(.infd/.inft)
  │
  ▼
RawTokenizer ──→ RawToken 流（容错，收集词法错误）
  │
  ▼
FinalTokenizer ──→ Token 流（值语义：转义 / 数值转换）
  │
  ▼
Parser ──→ RawAst（语法树）
  │
  ▼
TemplateGraphResolver（Phase 1）──→ ResolvedContext
  │                                  （模板图 / 可见名表 / $ 命名空间）
  ▼
AstBuilder（Phase 2a）──→ StdDocument（展开模板、挂载约束，不执行）
  │
  ▼
ConstraintExecutor（Phase 2b）──→ 校验后的 root（字段/结构约束 + schema）
  │
  ▼
std_to_python ──→ 忠实 Python 值（PurePosixPath / Decimal / NOEXIST）
  │
  ▼
emit ──→ to_json() / to_yaml() / to_toml()（有损投影）
```

- 前端（RawTokenizer → Parser）由 `frontend.parse_source` 统一组装，
  主文件与 `!from` 导入文件共用
- 三阶段语义流水线在 `pipeline._compile` 顶层组装，阶段间只经数据模型耦合；
  单一 `DiagnosticCollector` 从词法到语义全程复用
- **定义期校验**：Phase 2a 额外产出模板默认值与 `!var` 完整值（jsonpath
  投影前），Phase 2b 即使模板未实例化 / `!var` 未被引用也校验（
  [internals §8](./internals.md#8-定义期校验能静态发现的错不推迟到实例化)）
- **完整形状**：模板即约束 / schema 要求可选字段也显式声明；缺失字段是否
  放行，唯一判据是字段约束是否接受 noexist（[internals §7](./internals.md#7-三态标记拆分与完整形状校验v4-语义)）
- 公共 API（`load` / `safe_load` / `compile_source` / `check` / `compile_document`）
  都是 `_compile` 的薄包装

### 4.3 产物管理

```bash
# 当前可用（随库内置）
infd-cov app.infd                        # → YAML（stdout，零依赖 emitter）
infd-cov app.infd dist/app.json -f json  # → JSON 文件
infd-cov app.infd -f toml                # → TOML（需 tomli-w）
infd-cov app.infd --extract web.spec     # → 点分路径提取
infd-cov app.infd --severity warning     # → 达到阈值即拒绝（stderr + 退出 1）

# 规划中（尚未实现）
infd build app.infd -o dist/app.json
infd sign dist/app.json --key team-key.pem
infd verify dist/app.json --key team-key.pub
```

构建产物是可独立部署的纯数据文件。生产环境不需要安装 InfinityData。

---

## 5. CLI 工具设计

### 5.1 已实现：随库内置的两个工具

| 工具 | 入口 | 说明 |
|---|---|---|
| `infd-cov` | `infinity_data.tools.cov.__main__:main` | 编译 `.infd`/`.inft` → YAML / JSON / TOML |
| `infd-lsp` | `infinity_data.tools.lsp.__main__:main` | 零依赖 JSON-RPC 2.0 over stdio 语言服务器 |

两个工具都直接消费编译器公开 API（`compile_source` / `parse_source` /
`RawTokenizer` / `emit` / `semantic`），不复制编译逻辑。可选运行依赖
（PyYAML / tomli-w）由 `tool` extra 提供。

```bash
# 配置转换
infd-cov app.infd                          # → YAML（stdout，零依赖 emitter）
infd-cov app.infd out.json -f json         # → JSON 文件
infd-cov app.infd -f toml                  # → TOML（需 tomli-w）
infd-cov app.infd --extract web.spec       # → 点分路径提取
infd-cov app.infd --severity none          # → 从不拒绝（默认 error）
cat a.infd | infd-cov -f json              # stdin → stdout

# 语言服务器
infd-lsp                                   # 作为任意 LSP 客户端后端
python -m infinity_data.tools.lsp          # 等价模块入口
```

`#env: NAME "VALUE"` 声明在当前进程缺失时会自动注入虚拟值（两个工具一致），
详见 [README](./README.md#虚拟环境变量env-注释)。

### 5.2 规划中的统一 CLI（尚未实现）

> 以下为面向生态的完整 `infd` 命令设计，当前**未实现**。

```bash
# ═══════════════════════════════════════════════════════
# 项目管理
# ═══════════════════════════════════════════════════════

infd init                      # 初始化项目，生成 infd.yaml
infd init --template aws/lambda # 从远程模板初始化


# ═══════════════════════════════════════════════════════
# 校验
# ═══════════════════════════════════════════════════════

infd check                     # 校验当前目录所有 .infd 文件
infd check --strict            # 严格模式（额外字段报错）
infd check --watch             # 持续监听文件变更并校验


# ═══════════════════════════════════════════════════════
# 编译
# ═══════════════════════════════════════════════════════

infd build                     # 编译所有 .infd → dist/
infd build --format json       # 指定输出格式: json | yaml | toml
infd build --format yaml -o k8s/
infd build --watch             # 监听变更自动编译


# ═══════════════════════════════════════════════════════
# 依赖管理（Git 模板）
# ═══════════════════════════════════════════════════════

infd template add github.com/infd/aws     # 添加模板依赖
infd template add github.com/infd/aws --version v1.2.0
infd template update                       # 更新所有模板依赖
infd template update aws                   # 更新指定模板
infd template list                         # 列出已安装模板
infd template search aws                   # 搜索可用模板


# ═══════════════════════════════════════════════════════
# JSON Schema
# ═══════════════════════════════════════════════════════

infd schema export templates/server.inft              # → stdout
infd schema export templates/ -o schemas/             # 批量
infd schema export templates/server.inft --draft 2020-12

infd schema import server.json -o templates/server.inft
infd schema import schemas/ -o templates/             # 批量
infd schema import openapi.yaml -o templates/         # OpenAPI → .inft

infd schema verify templates/server.inft schemas/server.json
infd schema verify templates/server.inft schemas/server.json --diff


# ═══════════════════════════════════════════════════════
# 工具
# ═══════════════════════════════════════════════════════

infd fmt                       # 格式化 .infd/.inft 文件
infd fmt --check               # 仅检查格式（CI 用）
infd lint                      # 静态分析（未使用模板、冗余约束等）
```

### 5.3 项目配置 (infd.yaml，规划)

```yaml
# infd.yaml —— 项目根目录
name: my-project
version: "1.0.0"

# 模板依赖
templates:
  aws:
    repo: github.com/infd/aws
    version: v1.2.0
  k8s:
    repo: github.com/infd/k8s
    version: v1.0.0

# 编译配置
build:
  source: src/                   # .infd 源码目录
  output: dist/                  # 编译产物目录
  format: json                   # 默认输出格式
  schema: templates/AppConfig.inft  # 顶层 schema
  strip_noexist: true            # 编译产物中去掉 noexist 字段
  keep_null: true                # 编译产物中保留 null 字段

# 沙盒配置（CLI 模式下控制外部资源访问）
sandbox:
  env:
    - APP_ENV                    # 允许读取的环境变量列表
    - DATABASE_URL
  allow_files:
    - ./configs/**/*.json
    - /etc/app/*.yaml
  allow_templates:
    - ./templates/**/*.inft
    - github.com/my-org/*

# Lint 配置
lint:
  strict: false                  # 严格模式
  no_unused_templates: true      # 检查未使用的模板
  require_types: false           # 强制要求类型标注
```

---

## 6. Git 模板生态

### 6.1 设计原则

- **寄生 Git**：不需要自建 registry。GitHub/GitLab/Gitee 即 registry
- **版本锁定**：通过 Git tag 或 commit hash 锁定版本，可复现构建
- **去中心化**：任何人可以发布模板仓库，fork 即自定义
- **零服务器**：没有中心化 API、没有审核流程、没有单点故障

### 6.2 模板仓库结构

```
github.com/infd/aws/
├── infd.yaml                    # 模板包元信息
│   name: aws
│   version: "1.0.0"
│   description: "AWS 服务配置模板"
│   author: "infd-community"
│   license: MIT
│
├── lambda.inft                  # AWS Lambda 模板
├── ecs.inft                     # ECS 模板
├── eks.inft                     # EKS 模板
├── rds.inft                     # RDS 模板
├── s3.inft                      # S3 模板
├── vpc.inft                     # VPC 模板
├── iam.inft                     # IAM Role 模板
│
├── examples/
│   ├── simple-lambda.infd       # 示例：最小 Lambda
│   ├── full-stack.infd          # 示例：完整三层架构
│   └── README.md
│
└── README.md
```

### 6.3 使用方式

```infd
# !from 使用远程模板
!from p"github.com/infd/aws" import Lambda, EKS, RDS

my_api = Lambda(
    name = "user-service",
    runtime = "python3.12",
    memory = 512,
)
```

### 6.4 模板发现

```bash
# 搜索 GitHub 上带 infd-template topic 的仓库
$ infd template search aws

# 结果:
# github.com/infd/aws          ⭐ 234  AWS 服务配置模板
# github.com/company-x/aws     ⭐ 45   定制 AWS 模板
# github.com/user-y/aws-lite   ⭐ 12   轻量 AWS 模板
```

### 6.5 安全

- 模板在 `safe_load` + `sandbox` 保护下加载
- `allow_templates` 白名单控制可导入的模板源
- 模板仓库内容可审计（Git = 完整历史）
- 版本锁定防止上游变更破坏下游

---

## 7. JSON Schema 双向转换

> **状态（v4.0.0）：规划（M5，尚未实现）。** 本章描述目标映射与设计；
> `ConstraintEntry` 已预留 json_schema 生成回调的扩展点。

### 7.1 映射覆盖

```
.inft 约束              →  JSON Schema                  往返
───────────────────────────────────────────────────────────
str                     →  {"type": "string"}            ✅
int                     →  {"type": "integer"}           ✅
float                   →  {"type": "number"}            ✅
bool                    →  {"type": "boolean"}           ✅
list                    →  {"type": "array"}             ✅
dict                    →  {"type": "object"}            ✅
?                       →  {"type": "null"}              ✅
range(ge, le)           →  {"minimum": ge, "maximum": le} ✅
size(ge, le)            →  {"minLength"/"minItems": ...} ✅
each(c)                 →  {"items": c_schema}           ✅
in(a, b, c)             →  {"enum": [a, b, c]}           ✅
regex("re")             →  {"pattern": "re"}             ✅
ip4                     →  {"format": "ipv4"}            ✅
ip6                     →  {"format": "ipv6"}            ✅
not(c)                  →  {"not": c_schema}             ✅
any(c1, c2)             →  {"anyOf": [...]}              ✅
one(c1, c2)             →  {"oneOf": [...]}              ✅
all(c1, c2)             →  {"allOf": [...]}              ✅
TemplateName            →  {"$ref": "#/$defs/..."}       ✅
= default               →  {"default": value}            ✅
必填字段(无默认值)        →  {"required": [...]}           ✅
strict mode             →  {"additionalProperties": false} ✅
```

日常 JSON Schema 约 90% 特性可无损双向转换。

### 7.2 应用场景

1. **现有项目迁移**：`infd schema import` 一键转换 JSON Schema → `.inft`
2. **跨语言共享**：生成 JSON Schema → quicktype → Go/TypeScript/Rust 类型
3. **IDE 集成**：生成的 JSON Schema 直接被 VS Code/IntelliJ 消费
4. **CI 校验一致性**：`.inft` 和 JSON Schema 双向同步，CI 自动检查
5. **OpenAPI 互操作**：OpenAPI schemas → `.inft` → 更好的编辑体验 → 导回 OpenAPI

### 7.3 定位

InfinityData 作为 JSON Schema 的"最佳编写方式"：
- 写模板比写 JSON Schema 更快、更安全（编译时校验）
- 生成 JSON Schema 给下游消费
- 不替代 JSON Schema，而是成为它的超级前端

---

## 8. LSP 现状与设计方向

### 8.1 为什么 InfinityData 天然适合 LSP

- 语法简单（接近 LL(1)），解析极快
- 约束就是类型标注，零类型推断
- 纯声明式，无控制流
- 单文件通常 < 500 行
- 全量重分析开销小 → 不需要复杂的增量编译框架（当前实现为 Full sync）

### 8.2 已实现能力（`infd-lsp`，v4.0.0）

| 能力 | 状态 | 说明 |
|------|:--:|------|
| **诊断 (Diagnostics)** | ✅ | `didOpen`/`didChange`/`didSave` → `publishDiagnostics`；精确 `SourceRange` + 稳定错误码 + 多语言消息（zh-CN / en-US）；UTF-16 对齐 |
| **补全 (Completion)** | ✅ | `$` 命名空间、内置约束名、当前文件可见模板名、模板字段（必填/可选）、语言关键字 |
| **悬停 (Hover)** | ✅ | 约束描述、编译产物预览、被实例化的模板、`$` 变量值（定义点/调用点）、模板结构骨架 |
| **跳转定义 (Definition)** | ✅ | 模板调用 / `!from` 导入 / `$` 引用（含跨文件） |
| **文档符号 (Document Symbols)** | ✅ | 模板定义（Class）+ 顶层字段（Property） |
| **语义令牌 (Semantic Tokens)** | ✅ | 直接复用 `RawTokenizer`；UTF-16 单元对齐；多行字符串按行拆分 |
| **虚拟环境变量** | ✅ | 扫描 `#env: NAME "VALUE"`，进程未设置时注入虚拟值，避免 `env_not_set` 中止编译 |
| **代码操作 (Code Actions)** | ❌ | 规划：Quick Fix（改值满足约束、补缺失字段等） |
| **格式化 (Formatting)** | ❌ | 规划：标准缩进、逗号/换行规范化 |
| **重命名 (Rename)** | ❌ | 规划：模板名 / 字段名语义重命名 |

传输与部署：单线程 stdio、JSON-RPC 2.0 手写实现（零依赖）；VS Code 目前经
任意自定义 LSP 客户端扩展（如 `lspConfig`）接入，配置见
[README](./README.md#在-vs-code-中使用)。

### 8.3 体验设计（✅ 已实现 / 🚧 规划）

- ✅ **模板即约束补全**：在模板调用参数内自动补全该模板的字段
- ✅ **必填字段标记**：模板字段悬停与补全项区分必填/可选
- ✅ **约束文档内联**：约束名悬停显示参数说明
- 🚧 **约束阶梯提示**：`<int, range(1, 65535), not(in(80, 443))>` 分层展示
  （当前整体展示约束描述）
- 🚧 **智能 Quick Fix**：值不满足 `in("debug", "info")` 时建议最近匹配项

---

## 9. 改进计划

### 9.1 总体路线（含当前状态）

```
Phase 1: 地基加固          ✅ 已完成
Phase 2: 边界清晰化        ✅ 已完成
Phase 3: CLI + 生态        🚧 部分完成（infd-cov / infd-lsp 已交付）
Phase 4: LSP + 体验        🚧 部分完成（LSP 服务器已交付）
Phase 5: 模板市场 + 推广    ⏳ 未开始
```

### 9.2 Phase 1: 地基加固 ✅

**目标**：代码从原型变成可维护项目

- [x] **补测试** —— 753 个用例，测试目录完全镜像 `src/`
  - [x] Tokenizer 测试（字面量、多行字符串、多行注释、特殊浮点、fuzz）
  - [x] Parser 测试（各语句、类型标注、约束解析、错误恢复）
  - [x] Semantic 测试（resolver / builder / executor / registry / sandbox）
  - [x] Emit 测试（noexist 过滤、特殊值、JSON/YAML/TOML 输出）
- [x] **修复约束组合引擎** —— 递归约束执行（逻辑约束 `not/any/one/all` 递归内部约束）
- [x] **统一错误处理** —— 稳定错误码 + 结构化参数 + 集中注册表；错误节点容错；
  单字段失败不影响其他字段
- [x] **消除全局单例** —— `ConstraintRegistry` 实例由流水线注入（`CompileOptions`）
- [x] **循环引用检测** —— 模板依赖环（DFS 栈）+ 默认值引用图静态环检测

### 9.3 Phase 2: 边界清晰化 ✅

**目标**：建立干净的公开 API

- [x] **分离 CLI 和 Library** —— 工具收敛到 `infinity_data.tools`（lsp / cov），
  库 API 经 `infinity_data` 顶层导出
- [x] **补全 `__init__.py` 导出** —— parser / tokenizer / semantic / emit 公共面
- [x] **实现 SandboxConfig**
  - [x] 完整沙盒模型（env、allow_env、allow_files、allow_templates、strict）
  - [x] 工厂方法（deny_all、full_access、development；无 from_dict，自举用 SandboxConfig(**value)）
  - [x] `strict` 覆盖「白名单内但目标不存在」（`sandbox.file_missing`）
- [x] **实现 Schema 顶层约束** —— `Schema` + strict / lenient / strip 模式
- [x] **实现 safe_load** —— 等价 `load(path, sandbox=SandboxConfig.deny_all())`
- [x] **扩展 converter → emit 层**
  - [x] `to_json()` / `to_yaml()` / `to_toml()` + `EmitConfig`
  - [x] `dump_to_json` / `load_from_json` 无损标记闭环；`yaml_dump` 零依赖 YAML
  - [ ] `to_json_file` 写文件 API（未提供；由调用方写文件）
- [x] **文件类型检查** —— `.inft` 非模板/导入语句 → `inft.not_allowed` ERROR

### 9.4 Phase 3: CLI + 生态 🚧

**目标**：可发布的 CLI 工具 + Git 模板支持

- [ ] **统一 `infd` CLI**（尚未实现）
  - [x] `infd-cov`：编译 → YAML/JSON/TOML（`--format` / `--extract` / `--severity` / stdin）
  - [x] `infd-lsp`：语言服务器（见第 8 章）
  - [ ] `infd init`
  - [ ] `infd check`（含 `--watch`）
  - [ ] `infd build`（含 `--format`、`-o`）
  - [ ] `infd fmt`
  - [ ] `infd lint`
- [ ] **Git 模板管理**
  - [ ] `infd template add`
  - [ ] `infd template update`
  - [ ] `infd template list`
  - [ ] Git clone + 缓存机制
  - [ ] 版本解析（tag / branch / commit）
- [ ] **infd.yaml 项目配置**
  - [ ] 模板依赖声明
  - [ ] 编译配置
  - [ ] Sandbox 配置
- [ ] **JSON Schema 转换**
  - [ ] `infd schema export`
  - [ ] `infd schema import`
  - [ ] `infd schema verify`
- [ ] **AWS Lambda 模板包**（第一个官方模板）
  - [ ] Lambda、API Gateway、DynamoDB、S3、IAM、VPC
  - [ ] 示例配置
  - [ ] README 文档

### 9.5 Phase 4: LSP + 体验 🚧

**目标**：IDE 体验达到同类最佳

- [x] **LSP 服务器**
  - [x] 诊断（全量重编译，精确位置 + 稳定错误码）
  - [x] 补全（模板字段、约束名、`$` 命名空间）
  - [x] 悬停（约束文档、编译产物预览、模板骨架）
  - [x] 跳转定义（模板 / `!from` / `$` 引用，含跨文件）
  - [x] 文档符号
  - [x] 语义令牌（高亮）
  - [ ] Code Actions（Quick Fix）
  - [ ] 格式化
  - [ ] 重命名
- [ ] **VS Code 扩展**
  - [x] 语法高亮（经 LSP semanticTokens，无需 TextMate grammar）
  - [x] LSP 客户端配置（经 `lspConfig`，见 README）
  - [ ] 独立扩展发布 / 图标 / 文件关联
- [x] **错误信息优化**
  - [x] 中文错误信息（默认语言，可切换）
  - [x] 稳定错误码 + 结构化参数 + 精确 SourceRange
  - [ ] 约束违反时展示分层约束链（当前诊断携带约束表达式与位置）

### 9.6 Phase 5: 模板市场 + 推广

**目标**：建立社区和生态

- [ ] **Kubernetes 模板包**（第二个官方模板）
  - [ ] Deployment、Service、Ingress、ConfigMap、Secret、HPA
  - [ ] 最佳实践默认值
- [ ] **模板发现机制**
  - [ ] GitHub Topic: `infd-template`
  - [ ] `infd template search` 命令
- [ ] **文档**
  - [ ] 语言教程（渐进式）
  - [ ] API 参考
  - [ ] 迁移指南（从 JSON Schema、YAML、HCL）
- [ ] **CI/CD 集成**
  - [ ] GitHub Action: `infd-check`
  - [ ] GitLab CI template
- [ ] **社区建设**
  - [ ] Show HN / Reddit 发布
  - [ ] 2 分钟演示视频
  - [ ] 真实案例（K8s 部署 + AWS 基础设施）

### 9.7 后续优先级

```
当前（v4.0.0）：Phase 1–2 完成；Phase 3–4 部分完成（infd-cov / infd-lsp）；
Phase 5 未开始。

下一步（建议顺序）：
  1. JSON Schema 双向转换（M5）——生态桥接的关键
  2. 统一 infd CLI（build / check / fmt / lint）
  3. LSP Code Actions / 格式化 / 重命名
  4. Git 模板生态（infd template *）
```

Phase 1–2 的完成是后续工作的基础；剩余项按「生态桥接 → 工具链 → 编辑体验」推进。
