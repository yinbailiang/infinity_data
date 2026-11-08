# InfinityData

**声明式配置语言（`.infd` / `.inft`）的 Python 编译器库。**

- **编译优先**：`.infd` 是源码，JSON/YAML/TOML 是构建产物
- **模板即约束**：模板定义自动注册为约束校验器
- **零信任默认**：库默认 `deny_all` 沙盒，显式开放而非事后限制
- **结构化错误**：稳定错误码 + 结构化参数 + 多语言渲染

## 安装

```bash
uv add infinity-data        # 或 pip install infinity-data
```

## 快速开始

```python
from infinity_data import load

result = load('app.infd')
if result.has_errors:
    for d in result.diagnostics:
        print(d.location, d.code, d.message)
else:
    print(result.value)     # 降维后的 dict
```

```infd
~Server {
    host: str = "0.0.0.0",
    port: <int, range(1, 65535)> = 80,
}

api = Server(port = 443)
```

## 文档导航

| 文档 | 内容 |
|---|---|
| [语言参考](language/index.md) | 语法、类型、约束、模板、导入、词法 |
| [README](https://github.com/yinbailiang/infinity_data/blob/master/README.md) | 安装、库 API、CLI、LSP 快速入口 |
| [ENGINEERING](https://github.com/yinbailiang/infinity_data/blob/master/ENGINEERING.md) | 工程质量标准与指标 |
| [CONTRIBUTING](https://github.com/yinbailiang/infinity_data/blob/master/CONTRIBUTING.md) | 贡献流程与提交规范 |

## 官方工具

随库内置两个命令行工具：

```bash
infd-cov app.infd                 # 编译 → YAML（默认）
infd-cov app.infd -f json         # 编译 → JSON
infd-lsp                          # LSP 语言服务器（stdio）
```

工具的安装与 VS Code 配置见 [README](https://github.com/yinbailiang/infinity_data/blob/master/README.md)。
