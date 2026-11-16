# 项目记忆索引

> 静态项目记忆（随仓库提交）。运行时记忆见 `../memorys/`。
>
> `infinity-agent-kit` 的 `MEMORY_RULE.md` 约束的是运行时 `memorys/`；
> `project/` 是项目级静态扩展，由维护者随代码提交、记录「为什么」。

| 文件 | 内容 |
| --- | --- |
| [decisions.md](./decisions.md) | 库 API / 安全模型 / 编译模型 / 工具链 / 生态与路线图决策 |
| [internals.md](./internals.md) | 编译器实现层取舍（EOF、错误模型、三态与完整形状、定义期校验、编译期断言、关键字元数据、模板身份、位置、沙盒边界、诊断多语言、LSP 预览、公共 API） |
| [history.md](./history.md) | 历史开发记录、修复过程与已知坑位 |
| [semantic_pipeline.md](./semantic_pipeline.md) | 三阶段语义流水线拆分与复杂度收敛记录 |

## 维护约定

- **新决策**写入 `decisions.md`；**实现取舍**写入 `internals.md`
- **历史记录**只追加、不篡改；结论变化时在最新文档中标注日期与原因
- **语言规范**在 [`docs/zh-CN/language/`](../../../docs/zh-CN/language/index.md)，
  不复制到记忆
- 对外教程与 API 用法在 `README.md` 与 `docs/`；记忆只记录「为什么」
