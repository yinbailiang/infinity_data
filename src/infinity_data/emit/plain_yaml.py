"""零依赖 YAML emitter（block style，覆盖配置常用值）。

与 :func:`infinity_data.emit.converter.to_yaml`（基于 PyYAML）的关系：
本模块是**零依赖**轻量实现，供 ``infd-cov`` 默认 YAML 输出使用；PyYAML 未安装
时也可用。只覆盖配置场景常见值（dict / list / 标量 / Decimal / 多行字符串），
不做完整 YAML 规范实现。

- ``yaml_dump(obj)``：任意 Python 值 → YAML block 文本
- 值域与 :data:`~infinity_data.semantic.std.StdPythonValue` 对齐：Decimal（infd
  浮点字面量）经 ``str()`` 输出；``null`` → ``null``；多行字符串 → ``|-``
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Any

__all__ = ['yaml_dump']

# 可序列化值（reduce 后的配置值；Decimal 为 infd 浮点字面量）。
# PEP 695 递归别名：容器值也是 YamlValue，isinstance 收窄后无 Unknown。
type YamlValue = Mapping[str, YamlValue] | list[YamlValue] | str | int | float | bool | Decimal | None


def yaml_dump(obj: Any) -> str:
    """任意 Python 值 → YAML block 文本。"""
    out: list[str] = []
    _dump(obj, out, 0)
    return '\n'.join(out)


def _dump(obj: YamlValue, out: list[str], indent: int) -> None:
    pad = '  ' * indent
    if isinstance(obj, Mapping):
        if not obj:
            out.append(f'{pad}{{}}')
            return
        for k, v in obj.items():
            key = _plain(str(k))
            if isinstance(v, Mapping):
                if not v:
                    out.append(f'{pad}{key}: {{}}')
                else:
                    out.append(f'{pad}{key}:')
                    _dump(v, out, indent + 1)
            elif isinstance(v, list):
                if not v:
                    out.append(f'{pad}{key}: []')
                else:
                    out.append(f'{pad}{key}:')
                    _dump(v, out, indent + 1)
            else:
                if isinstance(v, str) and '\n' in v:
                    out.append(f'{pad}{key}: |-')
                    out.extend(_block_scalar_lines(v, indent))
                else:
                    out.append(f'{pad}{key}: {_scalar(v)}')
    elif isinstance(obj, list):
        if not obj:
            out.append(f'{pad}[]')
            return
        for v in obj:
            if isinstance(v, Mapping):
                if not v:
                    out.append(f'{pad}- {{}}')
                    continue
                first = True
                for k, vv in v.items():
                    key = _plain(str(k))
                    prefix = f'{pad}- ' if first else f'{pad}  '
                    first = False
                    if isinstance(vv, Mapping):
                        if not vv:
                            out.append(f'{prefix}{key}: {{}}')
                        else:
                            out.append(f'{prefix}{key}:')
                            _dump(vv, out, indent + 2)
                    elif isinstance(vv, list):
                        if not vv:
                            out.append(f'{prefix}{key}: []')
                        else:
                            out.append(f'{prefix}{key}:')
                            _dump(vv, out, indent + 2)
                    else:
                        if isinstance(vv, str) and '\n' in vv:
                            out.append(f'{prefix}{key}: |-')
                            out.extend(_block_scalar_lines(vv, indent + 1))
                        else:
                            out.append(f'{prefix}{key}: {_scalar(vv)}')
            elif isinstance(v, list):
                out.append(f'{pad}-')
                _dump(v, out, indent + 1)
            else:
                if isinstance(v, str) and '\n' in v:
                    out.append(f'{pad}- |-')
                    out.extend(_block_scalar_lines(v, indent))
                else:
                    out.append(f'{pad}- {_scalar(v)}')
    else:
        out.append(f'{pad}{_scalar(obj)}')


def _block_scalar_lines(s: str, indent: int) -> list[str]:
    """多行字符串 → YAML 块标量内容行（调用处负责输出 ``key: |-`` 头行）。

    内容行缩进 = 2 * (indent + 1)（比 key 多一级）；空行保持完全空白，
    避免因缩进不足提前结束块；尾部空行去除（配合 ``|-`` 无末尾换行）。
    """
    pad = '  ' * (indent + 1)
    lines = s.split('\n')
    while lines and lines[-1] == '':
        lines.pop()
    return [f'{pad}{line}' if line else '' for line in lines]


def _scalar(v: Any) -> str:
    """标量 → YAML 文本。"""
    if v is None:
        return 'null'
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if isinstance(v, (int, float, Decimal)):
        # nan / ±inf：YAML 接受 .nan/.inf，str() 输出的 nan/inf 也常见可读
        return str(v)
    return _plain(str(v))


def _plain(s: str) -> str:
    """普通字符串；含 YAML 特殊字符/歧义时加单引号。"""
    if s == '':
        return "''"
    # YAML 1.1 歧义字面量 → 引号
    if s in (
        'null',
        'Null',
        'NULL',
        'true',
        'True',
        'TRUE',
        'false',
        'False',
        'FALSE',
        'yes',
        'Yes',
        'YES',
        'no',
        'No',
        'NO',
        'on',
        'On',
        'ON',
        'off',
        'Off',
        'OFF',
        '~',
        '.nan',
        '.inf',
        '-.inf',
        '+.inf',
    ):
        return f"'{s}'"
    # 首字符/内嵌特殊 → 引号
    if s[0] in '-?:,[]{}#&*!|>\'"%@`' or s[0] in ' \t':
        return _quote(s)
    if ': ' in s or ' #' in s or '\n' in s or '\t' in s or s.rstrip() != s:
        return _quote(s)
    return s


def _quote(s: str) -> str:
    """单引号引用（'' 转义单引号）。"""
    return "'" + s.replace("'", "''") + "'"
