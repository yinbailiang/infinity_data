# 实现内部记忆

> **类型**：项目记忆（实现取舍）
> **范围**：编译器实现层隐含的设计决策、取舍与假设（面向当前代码）。
> **语言规范**：[docs/zh-CN/language/](../../../docs/zh-CN/language/index.md)（对外文档）
> **决策记忆**：[decisions.md](./decisions.md)
> **历史记录**：[history.md](./history.md) · [semantic_pipeline.md](./semantic_pipeline.md)
>
> 这些内容散落在代码注释与讨论中，不整理容易在后续重构时被误解或丢失。

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
- 诊断声明**每层一个词汇表文件**，每个声明是 `@dataclass(frozen=True)`
  （`code` / `severity` / `templates` 为 `ClassVar`，字段即类型化参数），
  `@registry.register` 导入即注册并做注册期校验：
  - `tokenizer/diagnostics.py` → `tokenize.*`
  - `parser/diagnostics.py` → `parse.*`（含语法层即报的 `template.dup_argument`）
  - `semantic/diagnostics.py` → `template.*` / `constraint.*` / `value.*` 等
  - `sandbox/errors.py` → `sandbox.*` / `schema.*`（异常携带声明实例 + source）
- 消息由声明模板按语言渲染：精确 `zh-CN` / `en-US`；回退链
  请求语言 → `I18N_LANGS_FALLBACK`（en-US、zh-CN），回退标记写入消息正文；
  `DEFAULT_LANG='en-US'`，每次编译由 `DiagnosticCollector` 构造时确定语言
  （显式 `lang` 优先；缺省按 LANGUAGE > LC_ALL > LC_MESSAGES > LANG 探测；
  C/POSIX 禁用翻译 → en-US）。
  语义/约束层**不手工拼字符串**，也不再用 code + params 映射。

### 取舍：值位置错误的归属在 parser

`ErrorValue` 是 parser 的**恢复产物**。值位置解析失败（遇到非值 token、或
`Identifier` 后接 `=`/`:` 的字段定义）由 parser 自行报告：

- `parse.value_field` —— 值位置出现字段定义（外层容器未闭合）
- `parse.unrecognized_value` —— 无法解析的值

语义层对 `ErrorValue` **不再重复报告**（`_resolve_value` 直接返回 `None`）。
曾有一层 `value.invalid` 在语义层重报 parser 产物，属跨层重复，已删除。

**错误节点序列化容错**：`ErrorStatement` / `ErrorValue` / `ErrorConstraint` 的
`canonical()` 输出 `error("message")` 占位符（**不抛异常**）——错误节点是解析失败
恢复产物，对应源码本就无效、无法还原为等价 AST；canonical 仅作容错（模板真名哈希
/ 调试 / LSP 提示），不承诺 round-trip，`error(...)` 也不是可解析的模板调用语法。

---

## 3. 未闭合括号的健壮性：两级报告

对 `a = [1, 2\nb = 3\n`（数组未闭合），报告设计为两层、各司其职：

| 层 | 机制 | 错误 | 角色 |
|---|---|---|---|
| 词法 | `RawTokenizer` 维护括号栈（`[` `{` `(` `<` 开压、配对弹栈，不配对/多余即时报），EOF 时逐条报告 | `tokenize.unterminated_bracket` / `tokenize.mismatched_bracket` / `tokenize.unexpected_close_bracket` | **根因**：指出未闭合/不匹配的括号及其位置 |
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
- 约束失败诊断的位置**取自被检查的对象**（值本身），而非约束表达式自身：
  - std 树节点统一继承基类 `StdNode`（`source` 字段，keyword-only 且不参与
    相等比较），值（`StdLiteral` / `StdArray` / `StdObject`）/ 字段
    （`StdField`）/ 约束（`ResolvedConstraint`）逐节点携带源文档位置
  - 字段注解约束 → 字段值 `value.source`（无来源回退字段 `field.source`）
  - 结构级约束（dict）→ 对象 `node.source`（无来源回退约束 `spec.source`）
  - 模板即约束 / schema 校验 → 调用处被检查的字段值 / 手写 dict；
    手写 dict 整棵无来源（外部导入数据）时回退**引用它的外层字段**
  - 嵌套约束（`each` / `position` / `field`）→ 被检查的元素 / 字段值
  - 模板展开实例的字段位置 = 调用点参数表达式（外部 `$var` 参数回退至此，
    而非模板定义）
  - **回退链路逐级外扩**：值 → 字段 → 外层被检查对象 → 约束表达式 → `None`。
    `!file` / `!env` / `!var` 导入等合成值整棵子树无来源时，最终落到
    「引用该数据的那条字段 / 外层对象」的位置；全程无来源则 `source=None`
    （渲染为 `<unknown>`）——外部数据本就不存在于源文档，无可指向的位置

---

## 5. 沙盒异常边界：在编译核心收敛

- 沙盒异常**只在语义分析内部流转**；`pipeline._compile` 捕获 `SandboxError`，
  转为 ERROR 诊断并返回**空 `StdDocument`**。
- **`strict` 覆盖「白名单内但目标不存在」**：`mediator._open` 在授权通过后追加
  `path.is_file()` 校验，缺失抛 `FileMissingError`（`sandbox.file_missing`）——`!file` /
  `!from` 是配置显式声明的依赖，缺失属于部署错误，不该退化成可用配置（值变 noexist、
  故障推迟到运行时）。非 `strict` 模式保持软失败：语义层产出 `import.file_missing`
  警告、值退化为 noexist，供扫描 / 容错场景使用。
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

---

## 7. 三态标记拆分与完整形状校验（v4 语义）

- **`?` 与 `!` 职责拆分**：`?` 仅表示 `null`（键存在、值为 null），
  `!` 仅表示 `noexist`（键不存在）。
  - 展开：`T?` → `any(T, ?)`、`T!` → `any(T, !)`、`T?!` / `T!?` →
    `any(T, ?, !)`
  - 推荐 `?!`；`!?` 等价但报 `parse.postfix_order` WARNING
- **词法层的 `!`**：`!` + `env/file/from/var` 组合为导入 token；其余位置为独立
  `EXCLAMATION` 标点——裸 `!`、`!@`、`!5` 不再报 `invalid_bang`。
  仅当 `!` 后是**近似导入关键字**的标识符时保留拼写纠正
  （`tokenize.bang_corrected`）或 `tokenize.invalid_bang`。
- **完整形状**：模板即约束 / schema 要求字段显式声明，可选字段也不可缺。
  缺失字段是否放行，唯一判据是**字段约束是否接受 noexist**：
  `executor._accepts_absent` 对合成 `StdLiteral(kind='noexist')` 执行字段约束，
  全部通过才放行（诊断丢弃）；空约束列表不接受。
  不再按「有默认值 → `missing_optional`」一刀切，也不注入默认值。
- 迁移影响：`int?` 不再接受 noexist；`<?> = noexist` 应写 `<dict?!>`，
  `<int?> = noexist` 应写 `<int!>`。
- 实现位置：`tokenizer._read_bang`、`parser._apply_postfix`、
  `registry.types._check_nullable/_check_absent`、`executor._accepts_absent`。

---

## 8. 定义期校验：能静态发现的错不推迟到实例化

- **模板字段重名**属定义错误（§1.1「同一 dict 含模板定义内」）：
  Phase 1 `TemplateGraphResolver._check_duplicate_fields` 报
  `dict.duplicate_key`，定义期去重（保留先到者）后再入模板表；
  实例化不二次报告，重复项不进入必填字段列表。本地模板与 `!from` 导入的
  `.inft` 走同一检查。
- **约束签名**（`constraint.unknown` / `constraint.arg_count`）由 Phase 2b
  `ConstraintExecutor.validate_templates` 静态校验；执行器是唯一同时持有注册表
  与模板表（含真名映射）的组件，Phase 2a 设计上零注册表依赖。
- **只校验顶层约束声明**：`has(x)` / `field(x, c)` 的参数是名字而非约束，
  静态层无法区分；嵌套约束仍在执行时校验。定义期已报非法签名的约束会记录到
  `_invalid_constraint_sources`，实例化 / 默认值 / schema 不再重复执行。
- **参数个数规则单一实现**：`ConstraintEntry.arity_error()`，执行期 `apply`
  与定义期静态校验共用，避免两处漂移。
- **默认值与 `!var` 值也做定义期校验**：Phase 2a 返回 `BuildArtifacts`——
  `document` 是可下发的纯 `StdDocument`，`template_defaults`（定义点 scope
  求值）与 `var_values`（jsonpath 投影**前**的完整值）仅用于 Phase 2b
  `validate_template_defaults` / `validate_var_values`；即使模板从未实例化、
  `!var` 未被 root 引用也会报错。
  - 默认值路径 `Template.field`；`!var` 路径 `$别名`
  - 递归默认值环上的字段跳过（`template.recursive_default` 根因优先）
  - 同源重复诊断由 `DiagnosticCollector` 按 code/参数/位置/级别/语言去重

---

## 9. 模板身份纳入数据依赖（env 取值）

- **环境变量取值必须进入模板身份哈希**：早期「跨机器可复现」假设是错的——
  静默漂移（不同机器 env 值不同、身份却相同）比身份不稳定更危险。
- 导入真名：`!env` = `SHA256("env" || 名称 || 值)`，值取自 `$` 命名空间
  （与实际绑定同源，不二次读环境）；`!var` 真名包含依赖绑定的真名
  （env / file / var 链）；var 环退化为自身 payload 哈希（终止、可复现）。
- 模板身份沿 Merkle 链间接覆盖 env 取值；未引用 `$` 的模板不受影响。
- **已知局限**：`!var` 表达式内调用模板时，模板默认值里的 `$` 依赖不进入
  var 真名（会与模板身份形成环），此类漂移目前不可见。
- 实现位置：`semantic/resolver/imports.py#import_identities`、
  `semantic/resolver/identity.py`；文档 §1.8 / §2.5。

---

## 10. 诊断声明与多语言渲染（v4.0.0）

- **单层定义**：声明类本身即参数 dataclass（`code` / `severity` / `templates`
  为 `ClassVar`，字段为真实类型参数）；`@registry.register` 导入即注册并校验：
  dataclass、code 全局唯一、`en-US` 必存、模板非空、占位符 ⊆ 字段 ∪
  保留上下文（`location_prefix` / `path_prefix`）、禁止 `Any` / `object`。
- `Diagnostic` 持有声明实例 + `source` / `path` / `severity_override` / `lang`；
  提供实际级别属性 `severity`、`render(lang, include_location)`、`to_dict()`。
  沙盒异常同样持有声明实例，不再用 code + params 映射。
- **语言**：`DEFAULT_LANG='en-US'`；每次编译由 `DiagnosticCollector` 构造时确定
  （显式 `lang` 优先；缺省按 `LANGUAGE > LC_ALL > LC_MESSAGES > LANG` 探测；
  C/POSIX 禁用翻译 → en-US）。
  回退链固定为请求语言 → `en-US` → `zh-CN`，不扫描任意模板键；回退标记
  `[fallback: lang]` 写入消息正文（有意可见），渲染异常返回固定错误文案。
- **已删除兼容层**：`Diagnostic.message` / `.params`、`DiagnosticDefine`、
  `render_message`、`diagnostic_define`、`register_diagnostic_define`、
  `registered_diagnostic_defines`。`ErrorValue` / `ErrorConstraint.message`
  仅为 parser 恢复载荷；`error.generic` 重复报告已删除。
- 注册声明 160 条（tokenizer / parser / semantic / sandbox 四层词汇表，
  全部 zh-CN + en-US）。`CompileOptions.lang` 贯穿公共 API；
  CLI `--lang` / `--diag-format json`；LSP `initializationOptions.lang` +
  `diagnostic.data`。

---

## 11. LSP 预览统一走 emit

- LSP 悬停/结构预览不再自写 JSON 序列化：
  `_preview_json` 使用
  `dump_to_json(value, EmitConfig(full_float=True, full_path=True, keep_noexist=True))`。
- 编译产物直接传 `StdValue`（emit 支持 std 输入）；模板骨架传已投影的 Python 值。
  path → `{"__type__": "path", ...}`、Decimal → `{"__type__": "decimal", ...}`、
  noexist → `{"__type__": "noexist"}`。
- 旧 `_dump_json` 把 Decimal 转 float（丢精度），path 直接 `TypeError`
  （模板默认值为 path 时悬停崩溃）——已由 emit 统一修复。
- **错误节点容错**：`_structure_value(ErrorValue)` 与 `_constraint_text(ErrorConstraint)`
  返回 `<错误>` 占位；未知节点回退 `…`，悬停对畸形文档任意位置不抛异常。
- 相关测试：`tests/lsp/language_test.py` 预览段（完整语义 + 错误节点）。

---

## 12. 文件读取缓存与编译内快照

- `DiskFile` 用 `cached_property` 按实例缓存文本；`MemFile` 内容本就在内存中，
  不引入额外缓存状态。`content_hash()` 复用已缓存文本，不再二次读盘。
- `Sandbox` 在一次编译生命周期内按**解析后路径**复用 `DiskFile`：
  `resolve` 与后续 `import_identities` 共享同一实例，避免 `!file` 内容被重复读取。
- 语义是**编译内快照**：编译过程中磁盘文件变化不会反映到已缓存实例；
  需要观察新内容时重新构造 `DiskFile` / `Sandbox` 或重新编译。
- 回归测试：`tests/infra/file_test.py`（实例缓存 + Sandbox 复用）、
  `tests/semantic/resolver/imports_test.py`（resolve 后 identity 只读一次）。
