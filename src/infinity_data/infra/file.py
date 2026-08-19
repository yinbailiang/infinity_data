"""源码来源抽象：磁盘文件与内存源码统一为 :class:`File`。

编译入口（``load`` / ``compile_source``）与模板导入链（``!from``）都消费 File：

- ``name``：诊断显示名（``file:line:col`` 中的 file）
- ``root_path``：相对导入解析基准（所在目录）
- ``read()``：源码内容
- ``chars()``：逐字符迭代流（词法分析输入）
- ``identity``：唯一身份（磁盘 = resolve 后绝对路径；内存 = ``路径:mem:内容hash``）；模板身份（TemplateKey）基于它，含来源路径
- ``content_hash()``：内容 sha256 前缀（MemFile 身份的一部分 / 内容校验）
"""

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

__all__ = ['File', 'DiskFile', 'MemFile']


@dataclass(frozen=True)
class File:
    """源码来源基类。"""

    name: str
    root_path: Path

    def read(self) -> str:
        """读取源码内容。"""
        raise NotImplementedError

    def chars(self) -> Iterable[str]:
        """逐字符迭代流（词法分析输入）。"""
        return iter(self.read())

    @property
    def identity(self) -> str:
        """唯一身份（循环导入防护 / 模板身份（TemplateKey）基础，含来源路径）。"""
        raise NotImplementedError

    def content_hash(self) -> str:
        """内容 sha256 前缀（MemFile 身份的一部分；内容校验，非模板身份本身）。"""
        return hashlib.sha256(self.read().encode('utf-8')).hexdigest()[:12]


@dataclass(frozen=True)
class DiskFile(File):
    """磁盘文件。path 为单一事实来源；name/root_path 由构造方从它派生。"""

    @property
    def path(self) -> Path:
        return Path(self.name)

    def read(self) -> str:
        return self.path.read_text(encoding='utf-8')

    @property
    def identity(self) -> str:
        return str(self.path.resolve())

    @classmethod
    def from_fullpath(cls, fullpath: str | Path) -> 'DiskFile':
        """从完整路径构造（与调用点一致的规范化入口）。"""
        p = Path(fullpath)
        return cls(name=str(p), root_path=p.parent)


@dataclass(frozen=True)
class MemFile(File):
    """内存源码（测试/嵌入式场景）。身份 = 根路径:mem:内容hash（含路径）。"""

    content: str

    def read(self) -> str:
        return self.content

    def chars(self) -> Iterable[str]:
        """逐字符迭代流（O(1) 构造，直连内容）。"""
        return iter(self.content)

    @property
    def identity(self) -> str:
        return str(self.root_path.resolve()) + ':mem:' + self.content_hash()
