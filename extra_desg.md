# InfinityData 进阶设计文档

> 基于讨论沉淀的库特性、设计取向、工具设计与改进计划。
> 前置阅读：[neo_desg.md](./neo_desg.md)（语言基础设计）

---

## 目录

1. [设计取向](#1-设计取向)
2. [库 API 设计](#2-库-api-设计)
3. [安全模型](#3-安全模型)
4. [编译模型](#4-编译模型)
5. [CLI 工具设计](#5-cli-工具设计)
6. [Git 模板生态](#6-git-模板生态)
7. [JSON Schema 双向转换](#7-json-schema-双向转换)
8. [LSP 设计方向](#8-lsp-设计方向)
9. [改进计划](#9-改进计划)

---

## 1. 设计取向

### 1.1 核心哲学

| 原则 | 说明 |
|------|------|
| **渐进增强** | Level 0 裸键值对就能用；按需加类型、加约束、加模板。无概念墙 |
| **编译优先** | .infd 是源码，JSON/YAML/TOML 是构建产物。可审计、可 diff、可签名 |
| **零信任默认** | 库默认 deny all；CLI 默认 full access。显式开放而非事后限制 |
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
    load,           # 主入口：加载 + 校验 + 编译
    safe_load,      # 零信任加载：禁止所有导入
    SandboxConfig,  # 沙盒配置
    Schema,         # 顶层 schema 约束
)
```

### 2.2 safe_load —— 零信任加载

```python
def safe_load(path: str) -> dict[str, Any]:
    """加载纯 .infd 文件。所有导入语句报错。

    等价于 load(path, sandbox=SandboxConfig.deny_all())

    用途:
    - 读取沙盒配置文件 (infd.sandbox.infd)
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
    path: str,
    *,
    sandbox: SandboxConfig | None = None,  # 默认 deny_all()
    schema: Schema | str | None = None,    # 顶层结构约束
) -> dict[str, Any]:
    """加载 .infd 文件，返回 Python dict。

    Args:
        path: .infd 文件路径
        sandbox: 沙盒配置。None = 零信任（库默认）
        schema: 顶层模板约束。str = 模板名（从同文件或 sandbox 中查找）

    Raises:
        SandboxError: 导入超出沙盒授权
        SchemaError: 输出不符合顶层 schema 约束
        ConstraintError: 字段约束违反
    """
```

### 2.4 SandboxConfig —— 沙盒配置

```python
@dataclass
class SandboxConfig:
    """控制 .infd 文件的导入权限。

    默认零信任：所有导入能力关闭，调用者必须显式开放。
    """

    # ── 环境变量注入 ──
    env: dict[str, str]          # key → value。未列出的变量 !env import 时报错

    # ── 文件导入白名单 ──
    allow_files: list[str]       # glob 模式。如 ["./configs/*.json"]

    # ── 模板导入白名单 ──
    allow_templates: list[str]   # glob 模式。如 ["./templates/*.inft", "github.com/**/*"]

    # ── 严格模式 ──
    strict: bool = True          # True: 白名单外的导入 → 报错。False: 仅警告

    # ── 工厂方法 ──

    @staticmethod
    def deny_all() -> SandboxConfig:
        """零信任：所有导入关闭。库默认。"""

    @staticmethod
    def full_access() -> SandboxConfig:
        """全权限：继承当前进程的所有能力。CLI 默认。"""

    @staticmethod
    def development() -> SandboxConfig:
        """开发模式：当前目录全权限 + 完整环境变量。"""

    @staticmethod
    def from_dict(d: dict) -> SandboxConfig:
        """从 safe_load 的结果构造 SandboxConfig。
        用于自举：用 safe_load 读 sandbox 定义，再构造沙盒。
        """
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

# 1. 安全读取沙盒定义（Layer 0）
sandbox_def = safe_load("environments/production.sandbox.infd")
sandbox = SandboxConfig.from_dict(sandbox_def)

# 2. 带沙盒 + 顶层 schema 加载配置（Layer 1）
config = load(
    "app.infd",
    sandbox=sandbox,
    schema=Schema(
        template="AppConfig",
        from_file="templates/AppConfig.inft",
        mode="strict",
    ),
)

# sandbox  → 控制"能读什么"（输入安全）
# schema   → 控制"产出什么"（结构安全）
# 约束链    → 控制"值对不对"（数据安全）
```

### 2.7 转换输出

```python
from infinity_data import load, to_json, to_yaml, to_toml

config = load("app.infd")

json_str = to_json(config, indent=2)           # → JSON 字符串
yaml_str = to_yaml(config)                     # → YAML 字符串
toml_str = to_toml(config)                     # → TOML 字符串

to_json_file(config, "dist/app.json")          # 直接写文件
```

特殊值处理：
- `noexist` → 键不出现在输出
- `null` → 保留键，值为 `null`/`None`
- `nan` → JSON: `"NaN"`（自定义 encoder）；YAML: `.nan`
- `+inf`/`-inf` → JSON: `"Infinity"`/`"-Infinity"`；YAML: `.inf`/`-.inf`

### 2.8 JSON Schema 转换

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
from infinity_data import check, compile_to_dict

# 仅校验，不输出
diagnostics = check("app.infd", sandbox=sandbox, schema=...)
# → list[Diagnostic]

# 编译为 dict（不经过 JSON 字符串）
result = compile_to_dict("app.infd", sandbox=sandbox, schema=...)
# → StdDocument，含 .root (StdObject) 和 .diagnostics
```

---

## 3. 安全模型

### 3.1 分层信任

```
Layer 0: safe_load()
  ├── 零导入能力
  ├── 纯数据 + 模板定义
  └── 输出: dict → SandboxConfig.from_dict()

Layer 1: load(sandbox=..., schema=...)
  ├── 受控导入 (sandbox 授权)
  ├── 顶层结构约束 (schema 限定)
  └── 字段级约束 (约束链)
```

### 3.2 两个场景，两种默认

| | CLI (`infd build`) | 库 (`infd.load()`) |
|------|:--:|:--:|
| **默认 sandbox** | `full_access()` | `deny_all()` |
| **信任假设** | 用户 = 文件作者 = 机器主人 | 文件作者 ≠ 调用者 |
| **安全模型** | "我信任我自己" | "我不信任输入" |

### 3.3 沙盒控制矩阵

| 导入类型 | sandbox 控制 | 默认 (deny_all) | 默认 (full_access) |
|------|------|:--:|:--:|
| `!env import NAME` | `env` dict | ❌ 禁止 | ✅ 真实 OS 环境变量 |
| `!file "path"` | `allow_files` glob 列表 | ❌ 禁止 | ✅ 任意文件 |
| `!from "path"` | `allow_templates` glob 列表 | ❌ 禁止 | ✅ 任意模板 |

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
RawTokenizer ──→ RawToken 流 (容错，收集错误)
  │
  ▼
FinalTokenizer ──→ Token 流 (值转换)
  │
  ▼
Parser ──→ RawAst (语法树)
  │
  ▼
SemanticAnalyzer ──→ StandardAst (展开模板、执行约束、解析导入)
  │
  ▼
Converter ──→ Python dict
  │
  ├──→ to_json()  ──→ JSON 字符串
  ├──→ to_yaml()  ──→ YAML 字符串
  └──→ to_toml()  ──→ TOML 字符串
```

### 4.3 产物管理

```bash
# 编译
infd build app.infd -o dist/app.json

# 签名
infd sign dist/app.json --key team-key.pem
# → dist/app.json.sig

# 验证签名
infd verify dist/app.json --key team-key.pub

# CI 校验一致性
infd build app.infd -o /tmp/app.json
diff /tmp/app.json dist/app.json   # 不一致 → CI 报错
```

构建产物是可独立部署的纯数据文件。生产环境不需要安装 InfinityData。

---

## 5. CLI 工具设计

### 5.1 命令一览

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

### 5.2 项目配置 (infd.yaml)

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
!from "github.com/infd/aws" import Lambda, EKS, RDS

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

## 8. LSP 设计方向

### 8.1 为什么 InfinityData 天然适合 LSP

- 语法简单（接近 LL(1)），解析极快
- 约束就是类型标注，零类型推断
- 纯声明式，无控制流
- 单文件通常 < 500 行
- 全量重分析 < 10ms → 不需要复杂的增量编译框架

### 8.2 计划支持的功能

| 功能 | 说明 |
|------|------|
| **诊断 (Diagnostics)** | 约束违反实时波浪线 + 错误信息 |
| **补全 (Completion)** | 模板字段补全、约束名补全、关键字补全 |
| **悬停 (Hover)** | 约束文档、类型信息、默认值来源 |
| **跳转 (Go to Definition)** | 模板定义、`!from` 路径、`$` 引用 |
| **代码操作 (Code Actions)** | Quick Fix（修改值满足约束、添加缺失字段等） |
| **格式化 (Formatting)** | 标准缩进、逗号/换行规范化 |
| **重命名 (Rename)** | 模板名、字段名语义重命名 |
| **文档符号 (Document Symbols)** | 文件大纲（模板定义、字段列表） |

### 8.3 独特体验

- **约束阶梯提示**：`<int, range(1, 65535), not(in(80, 443))>` 拆分为三层，每层可 hover 查看详情
- **模板即约束补全**：在 `Server = {` 内自动补全 `Server` 的所有字段
- **必填字段星标**：补全列表中必填字段标记 ★
- **智能 Quick Fix**：值不满足 `in("debug", "info")` 时建议最近匹配项
- **约束文档内联**：`range` 悬停显示参数说明

---

## 9. 改进计划

### 9.1 总体路线

```
Phase 1: 地基加固 (1-2 周)
Phase 2: 边界清晰化 (1-2 周)
Phase 3: CLI + 生态 (2-3 周)
Phase 4: LSP + 体验 (3-4 周)
Phase 5: 模板市场 + 推广 (持续)
```

### 9.2 Phase 1: 地基加固

**目标**：代码从原型变成可维护项目

- [ ] **补测试** —— 最高优先级。核心路径覆盖率 > 80%
  - [ ] Tokenizer 测试（字面量、多行字符串、多行注释、特殊浮点）
  - [ ] Parser 测试（各种语句、类型标注、约束解析）
  - [ ] SemanticAnalyzer 测试（模板展开、约束执行、导入解析）
  - [ ] Converter 测试（noexist 过滤、特殊值处理、各格式输出）
- [ ] **修复约束组合引擎** —— 改为递归约束执行
  - [ ] `apply_constraint_by_name` 的 `args` 保留为 `Constraint` 列表而非扁平值
  - [ ] 逻辑约束 `not/any/one/all` 递归执行内部约束
- [ ] **统一错误处理**
  - [ ] 消除静默错误兜底（如 `ConstraintIdent(name="?")`）
  - [ ] 引入明确的错误标记 `<error>`
  - [ ] 错误恢复：一个字段失败不影响其他字段
- [ ] **消除全局单例**
  - [ ] 去掉 `constraints.py` 中的 `_default_registry`
  - [ ] `SemanticAnalyzer` 持有 `registry` 实例
- [ ] **循环引用检测** —— 模板 A → B → A

### 9.3 Phase 2: 边界清晰化

**目标**：建立干净的公开 API

- [ ] **分离 CLI 和 Library**
  - [ ] `main.py` → `cli.py`
  - [ ] 库 API 通过 `__init__.py` 导出
- [ ] **补全 `__init__.py` 导出**
  - [ ] `parser/__init__.py`
  - [ ] `tokenizer/__init__.py`
- [ ] **实现 SandboxConfig**
  - [ ] 完整沙盒模型（env、allow_files、allow_templates）
  - [ ] 工厂方法（deny_all、full_access、development、from_dict）
  - [ ] `SemanticAnalyzer` 集成沙盒
- [ ] **实现 Schema 顶层约束**
  - [ ] `Schema` 数据类 + mode 参数
  - [ ] strict / lenient / strip 模式
- [ ] **实现 safe_load**
  - [ ] 等价于 `load(path, sandbox=SandboxConfig.deny_all())`
- [ ] **扩展 converter**
  - [ ] `to_json()`——自定义 encoder 处理 nan/+inf/-inf
  - [ ] `to_yaml()`
  - [ ] `to_toml()`
- [ ] **文件类型检查** —— `.inft` 文件不允许数据定义

### 9.4 Phase 3: CLI + 生态

**目标**：可发布的 CLI 工具 + Git 模板支持

- [ ] **CLI 命令**
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

### 9.5 Phase 4: LSP + 体验

**目标**：IDE 体验达到同类最佳

- [ ] **LSP 服务器**
  - [ ] 诊断（全量重分析 < 10ms）
  - [ ] 补全（模板字段、约束名）
  - [ ] 悬停（约束文档、类型信息）
  - [ ] 跳转定义
  - [ ] Code Actions（Quick Fix）
  - [ ] 格式化
  - [ ] 文档符号
- [ ] **VS Code 扩展**
  - [ ] 语法高亮（TextMate grammar）
  - [ ] LSP 客户端配置
  - [ ] 图标 / 文件关联
- [ ] **错误信息优化**
  - [ ] 中文错误信息
  - [ ] 约束违反时展示约束链
  - [ ] Source location 精确到字符

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

### 9.7 优先级矩阵

```
                    高影响              低影响
              ┌──────────────────┬──────────────────┐
  高紧急      │ 补测试            │ 模板市场          │
              │ 修复约束引擎      │                   │
              │ 消除静默错误      │                   │
              ├──────────────────┼──────────────────┤
  低紧急      │ CLI + sandbox    │ LSP               │
              │ Git 模板管理      │ 文档              │
              │ JSON Schema 互转  │ 社区建设          │
              └──────────────────┴──────────────────┘
```

Phase 1 的每一项都是阻塞性的——不做这些，后续工作都在沙上建塔。
