# InfinityData 实现设计笔记

> 记录编译器实现中**隐含的设计决策、取舍与假设**。它们散落在代码注释与讨论中，
> 不整理容易在后续重构时被误解或丢失。
>
> 文档体系：
> - [neo_desg.md](./neo_desg.md) —— 语言基础设计（语法/类型/模板/约束）
> - [extra_desg.md](./extra_desg.md) —— 库 API / CLI / 生态设计（面向未来）
> - **本文件** —— 编译器实现层的取舍（面向当前代码）

---

## 1. EOF 语义：EofToken 是流耗尽的哨兵

### 现状

- `FinalTokenizer` 产出**真实的 `EofToken`** 作为 token 流中最后一个 token，
  携带**文件末尾的精确位置**（如 `3:1`）。
- 泛型 `LL1Stream.eof()` 只认**物理耗尽**：`_next is NoNextType`，
  即 EofToken 被 `advance()` 消费**之后**才为 True。
  它被 `CharStream`（纯字符流，无 EofToken）共用，**语义不可修改**。
- `TokenStream.eof()` **重写**为：

  ```python
  return isinstance(self.peek(), (EofToken, NoNextType))
  ```

  即「当前是 EofToken，或已物理耗尽」均视为结束。**parser 层只有一个结束概念。**

### 取舍：为什么保留 EofToken 而不是去掉

EOF 需要一个**位置载体**："期望 `]`，实际为 EOF" 要指向文件末尾（`3:1`），
而不是退化为 `span_from(None)`（最后一个已消费 token 的跨度）。在编辑器/LSP 里，
错误高亮应落在"缺定界符的文件结尾"，而非最后一个 token。

去掉 EofToken **并不会减少** `NoNextType` 处理：错误恢复中 `expect()` 消费掉
EofToken 后 `peek()` 仍会返回 `NoNextType`，相关守卫只是从"兜底"变成"唯一路径"。

### 取舍：为什么不做「虚拟无限 EofToken」

让 `TokenStream` 在底层耗尽后继续虚拟吐出 EofToken（parser 永远见不到
`NoNextType`）在概念上最纯，但要给 `TokenStream` 增加虚拟结尾机制
（缓存虚拟 EofToken、`advance()` 在末尾不抛错、`span_from`/`_last` 不引用假 token），
收益仅是删除约 6 条防御性守卫。对"当前专注功能"的阶段性价比低。

### 使用约定

- 容器循环（数组/对象/模板定义/约束列表/模板调用参数）统一
  `while not check(定界符) and not eof()`，**在 EofToken 前停下**；
  缺失定界符由循环外 `expect()` 报「实际为 EOF」并消费哨兵。
- `expect()` / `_expect_keyword` 两条路径都要覆盖：
  `NoNextType`（哨兵已被消费）与非匹配 token（EofToken 落入此分支，
  `type.name == 'EOF'`，还带真实位置）。
- parser 里的 `isinstance(tok, NoNextType)` 守卫在**恢复路径可达**，不是死代码，
  勿删除。

---

## 2. 错误模型：分层与归属

### 总原则

- **词法/语法/语义错误**统一为 `Diagnostic`（纯数据），容错收集，**从不抛异常**。
- **沙盒错误**用异常 `SandboxError`（子类 `EnvNotAuthorizedError` /
  `EnvNotSetError` / `AccessDeniedError` / `SchemaError`）——因为必须**中止编译**
  （控制流），无法靠容错恢复继续。
- 诊断定义**每层一个词汇表文件**，导入时经 `register_diagnostic_define()`
  合并进全局注册表：
  - `tokenizer/diagnostics.py` → `tokenize.*`
  - `parser/diagnostics.py` → `parse.*`
  - `semantic/diagnostics.py` → `template.*` / `constraint.*` / `value.*` 等
  - `sandbox/errors.py` → `sandbox.*` / `schema.*`（异常携带 code/params/source）
- 消息由注册表按错误码 + 结构化 params 渲染（缺译回退 `DEFAULT_LANG='zh'`），
  语义/约束层**不手工拼字符串**。

### 取舍：值位置错误的归属在 parser

`ErrorValue` 是 parser 的**恢复产物**。值位置解析失败（遇到非值 token、或
`Identifier` 后接 `=`/`:` 的字段定义）由 parser 自行报告：

- `parse.value_field` —— 值位置出现字段定义（外层容器未闭合）
- `parse.unrecognized_value` —— 无法解析的值

语义层对 `ErrorValue` **不再重复报告**（`_resolve_value` 直接返回 `None`）。
曾有一层 `value.invalid` 在语义层重报 parser 产物，属跨层重复，已删除。

---

## 3. 未闭合括号的健壮性：两级报告

对 `a = [1, 2\nb = 3\n`（数组未闭合），报告设计为两层、各司其职：

| 层 | 机制 | 错误 | 角色 |
|---|---|---|---|
| 词法 | `RawTokenizer` 维护括号栈（`[` `{` `(` `<` 开压闭弹），EOF 时逐条报告 | `tokenize.unterminated_bracket` | **根因**：指出未闭合的括号及其位置 |
| 语法 | `_parse_value` 识别 `Identifier` 后接 `=`/`:`（新语句边界） | `parse.value_field` | **后果**：解释下一行字段为何解析失败 |

### 为什么语法层也要处理

未闭合数组会让后续行的 `b = 3` 被当成数组元素解析——`b` 会被当作模板调用
（期待 `(` 却遇 `=`），产生误导的 `template.undefined`（语义层）和
Lparen/Rparen 级联错误。在值位置识别字段定义边界可以**止住级联**。

---

## 4. 位置（SourceRange）约定

- `SourceRange = file + start + end`。词法阶段多为零宽（`start == end`）；
  但 token、约束表达式、语句跨度都是**非零宽**范围。
- `format_location`：
  - 零宽 → `file:line:col`
  - 非零宽 → `file:line:col-line:col`（区间）
- 诊断与沙盒异常的位置统一取自 `SourceRange`
  （`Diagnostic.source` / `SandboxError.source`）。
- 约束失败诊断的位置取自约束表达式自身（`spec.source`），
  回退规则：`spec.source or 外层 source`。

---

## 5. 沙盒异常边界：在编译核心收敛

- 沙盒异常**只在语义分析内部流转**；`pipeline._compile` 捕获 `SandboxError`，
  转为 ERROR 诊断并返回**空 `StdDocument`**。
- 因此 `load` / `safe_load` **不抛出**（空文档即"失败"信号）；`check` 是纯转发
  （`load(...).diagnostics`）；`compile_document` 违规时返回空文档。
- 库默认零信任（`deny_all`）；`env` 三态模型（注入 / `allow_env` 白名单实时读 /
  未授权失败）；glob 用自写段级匹配器（消除 `Path.match` 的 3.13+ 版本依赖）。

---

## 6. 公共 API 与编译核心

- `CompileOptions`（frozen dataclass：`env` / `sandbox` / `registry` / `schema` +
  `effective_sandbox()` 合并 env）是共享选项的**唯一载体**。
- 公共 API（`load` / `compile_source` / `safe_load` / `check` / `compile_document`）
  是**薄包装**，内部统一走单一核心 `_compile(file, options)`。
- 空源码 → 空 `StdDocument`（不算错误）。
- **BOM 归词法层**：`RawTokenizer._detect_bom` 报 `tokenize.bom`（WARNING）并跳过
  ——文件格式问题由词法层报告，而非编译核心。
