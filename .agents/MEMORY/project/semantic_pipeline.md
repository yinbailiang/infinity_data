# 语义流水线重构记忆

> **类型**：项目记忆（重构记录）
> **说明**：三阶段语义流水线（Resolver / Builder / Executor）拆分与复杂度收敛过程。
> **现行结构**：[internals.md](./internals.md) 与 `src/infinity_data/semantic/`。

## 复杂度收敛重构（2026-08-19）

- registry.py（900 行）拆为 `registry/` 包：`_core.py`（ConstraintResult/Executor/ConstraintEntry/ok_result/fail_result/describe + 共享辅助 as_number/as_str/as_decimal_arg/std_equal/as_std_value/as_spec/spec_name，均无下划线）、`types.py`、`general.py`、`logic.py`、`dict_constraints.py`、`__init__.py`（ConstraintRegistry + _register_builtins 组装）
- 子模块 import 用别名映射回下划线（`as_spec as _as_spec`），函数体零改动；子模块需 `__all__`（否则 pyright reportUnusedFunction）；`_core` 辅助去下划线（否则 reportPrivateUsage）
- `analyzer.py` → `builder.py`（git mv，类 AstBuilder），pipeline/frontend/resolver/models docstring 引用已更新
- `semantic/__init__.py` 收敛：只导出产物面（ResolvedConstraint/ResolvedContext/Std* /Diagnostic/Severity/diagnostics），内部对象（AstBuilder/ConstraintExecutor/Resolver/Registry）不重导出
- `AstBuilder.analyze` 状态注入包装为 `_adopt(context)` 私有方法
- 140 测试全过 / ruff / pyright 零错误

- `semantic/resolver.py`：`TemplateGraphResolver`（Phase 1 导入解析）→ `ResolvedContext`（frozen dataclass，定义在 `models.py`）；`parse_cache`（identity→Document）可选注入；`MAX_IMPORT_DEPTH` 在此
- `semantic/builder.py`：`AstBuilder`（Phase 2a 构建器，原 SemanticAnalyzer，analyzer.py 已 git mv）——值语义 + 约束挂节点（**不执行**）；`analyze` 编排：`_adopt(context)` → `ConstraintExecutor.validate` → `apply_schema`；显式依赖 resolver
- `semantic/executor.py`：`ConstraintExecutor`（Phase 2b）——遍历 StdAst 执行节点约束 + 模板即约束（查模板表）+ schema（strict/lenient/strip）；`apply_schema` 返回 (root, 非致命诊断)，失败抛 SchemaError；`_exec` 签名须匹配 `Executor` 协议（参数名 constraint）
- `semantic/constraints.py`：约束解析纯函数（`resolve_constraints` 字段注解 / `resolve_constraint_list` 结构约束，返回 (specs, diags)）
- **约束只校验不转换**：`ConstraintResult.coerced_value` 已删；`float` 拒绝 int（无提升）；`$x as int` 显式 type_cast 保留（语言特性）
- 模型：`ResolvedConstraint` 在 models.py（挂在 StdAst 节点）；`StdField.constraints`/`StdObject.constraints` 携带已解析约束
- pipeline 是唯一组装者：`ImportResolver` → `TemplateGraphResolver` → `AstBuilder`；resolver 暴露 `registry`/`schema` property（两阶段共享同一实例）
- 关键点：`root_scope` 直接引用（与 template_scopes 内定义点 scope 同一对象）；遮蔽检查用 `registry.names`（只读）
- 140 测试全过；`test_resolver.py`（10 用例，Phase 1 不执行约束）、`test_executor.py`（10 用例，工作在 AST 上）
- **模板头部配置（2026-08-19）**：`TemplateConfig` dataclass 在 `parser/models.py`（allow_extra/positional/description），**语法层解析**（parser 白名单 `_CONFIG_BOOL_KEYS`/`_CONFIG_STR_KEYS`，未知键/类型错/非字面量 → `parse.template_config_*` 3 个新诊断）；executor 读 `tpl.config.allow_extra`（删 `_resolve_config_bool`）；builder：`positional=false` 拒绝位置参数（`template.positional_disabled`）+ 未知命名参数报错（`template.unknown_argument`，不再静默忽略）；146 测试全过
- 坑：`MultilineStringToken` 是 `StringToken` 子类——`case StringToken` 已覆盖，多余子类 case 触发 pyright reportUnnecessaryComparison；config 值用 `_parse_value()` 但限字面量（`_literal_config_value`）
- **StringToken 抽象超类方案（2026-08-19 最终版）**：`StringToken(Token)` 保留为抽象基类（`@dataclass(init=False)` + 自定义 `__init__` 抛 TypeError 强制拒绝实例化；带 value，finalizer 只构造子类），`SinglelineStringToken(StringToken)` + `MultilineStringToken(StringToken)`（多行额外 tags）。关键洞察：match 陷阱的真正根源是"把超类 case 当具体类型（单行）用"；超类语义明确为"任意字符串"后 `case StringToken` 合法无陷阱。消费约定：**任意字符串场景用 `StringToken`**（builder._convert_literal、constraints.literal_python_value、parser _starts_value/_parse_constraint/_parse_value/_literal_config_value、LiteralValue.value 类型），**严格单行场景用 `SinglelineStringToken`**（`expect` 路径/文件名、JSON path 的 `."key"`）——多行串当路径被拒（原 `expect(StringToken)` 经子类意外接受，`!from `反引号`` 静默通过，已修）。parser.py 需 import StringToken + SinglelineStringToken（无 MultilineStringToken）。147 测试全过
- 已知点：`ResolvedContext` frozen 只冻结属性赋值，内部 dict 仍可变（约定只读，未用 MappingProxyType）
- **性能基准（2026-08-19）**：线性 ~100 us/字段（GC 关，无约束）；带约束 ~290 us/字段（常数 2.4x，仍线性）；非线性是 GC 压力（dataclass 对象累积），非算法问题
- **剖析（cProfile，2000 字段带约束 533ms）**：**前端 tokenizer+parser 占 83%（440ms）**，语义+emit 仅 17%（93ms）——约束器不是瓶颈。热点：`infra/ll1_stream.py` 的 advance/peek/eof/_ensure_buf 合计 ~0.55s（近百万次调用）、`tokenizer._make_token`（0.2s）、`char_stream.info` 每 token 构造位置（6 万次）、`isinstance` 84 万次（match 模式匹配底层）
- **优化路线（按序）**：① 纯 Python 正则化 tokenizer（re 批处理替代逐字符预读流，预计 3-4 倍，接口不变）② 位置对象懒构造 ③ 未来 C++ 重写 tokenizer（pybind11，可插拔替换 RawTokenizer，保留纯 Python fallback 以维持零依赖卖点；注意跨边界 token 对象所有权/生命周期）
- **当前专注功能，不做性能优化**
- **2026-08-25**：`registry/general.py` 新增 `_check_position`（数组约束 `position(index, constraint)`——`_as_spec(args[1])` 取嵌套约束 + `executor(spec, elem, ...)` 递归，路径 `{path}[{idx}]`，下标越界/非整数/非 list 各报新诊断）；复用 `_core.py` 的 as_spec/spec_name；parser `_nullable` 可空展开由 `one(c, ?)` 改为 `any(c, ?)`；552 测试全过 / pyright 干净
