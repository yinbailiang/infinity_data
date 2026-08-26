"""emit/converter.py 单元测试：Python 值 → 输出有损投影（path → POSIX 字符串）。

与 semantic 层的忠实互转（std_to_python，path 保持 PurePosixPath）区分：
本层是从 Python 出发的**有损**投影，仅供输出格式（JSON/YAML/TOML）消费。
"""

from decimal import Decimal
from pathlib import PurePosixPath

from infinity_data.emit import project_output


def test_project_output_passthrough_scalars() -> None:
    value = {'i': 1, 'b': True, 's': 'x', 'n': None, 'd': Decimal('1.5'), 'l': [1, 'a']}
    assert project_output(value) == value


def test_project_output_path_to_posix_string() -> None:
    value = {'cert': PurePosixPath('/etc/certs/a.pem'), 'p': PurePosixPath('./a/../b')}
    # as_posix() 归一掉前导 ./，保留内部 ..
    assert project_output(value) == {'cert': '/etc/certs/a.pem', 'p': 'a/../b'}


def test_project_output_nested() -> None:
    value = {'s': {'p': PurePosixPath('/x')}, 'list': [PurePosixPath('/a'), 'plain']}
    assert project_output(value) == {'s': {'p': '/x'}, 'list': ['/a', 'plain']}
