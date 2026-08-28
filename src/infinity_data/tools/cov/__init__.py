"""infd-cov：编译 .infd/.inft → 各种配置格式（YAML / JSON / TOML）。

用法::

    infd-cov app.infd                          # → YAML（stdout，零依赖 emitter）
    infd-cov app.infd out.json -f json         # → JSON 文件
    infd-cov app.infd -f toml                  # → TOML（需 tomli-w）
    infd-cov app.infd --extract web.spec       # → 点分路径提取
    cat a.infd | infd-cov -f json              # stdin → stdout

行为:
    - 沙盒 ``SandboxConfig.full_access()``：放行全部导入（含跨目录 ``!from`` 模板导入）
    - ``#env: NAME "VALUE"`` 声明的变量在当前进程缺失时自动注入虚拟值
    - ``--severity LEVEL``：拒绝阈值（error/warning/info/debug/none，默认 error）。
      达到该级别（含更高）的诊断 → 全部报告到 stderr + 退出 1（不输出）；
      none = 从不拒绝
    - ``--extract PATH``：点分路径（如 ``web.spec.selector``）；空 = 整树；
      路径不存在 → stderr + 退出 1
    - noexist 字段（键不出现）已在 reduce 阶段过滤

模块划分（与 lsp 相同的包结构）：
    - :mod:`~infinity_data.tools.cov.cli`：入口与主流程（argparse / 编译 / 阈值）
    - :mod:`~infinity_data.tools.cov.convert`：格式渲染（YAML/JSON/TOML）+ 路径提取
"""

from infinity_data.tools.cov.cli import main, virtual_env

__version__ = '1.0.0'

__all__ = ['main', 'virtual_env', '__version__']
