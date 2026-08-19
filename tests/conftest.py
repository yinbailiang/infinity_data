"""共享测试 fixtures（event_bus 风格）：跨测试文件复用。"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest


@pytest.fixture
def infd_file(tmp_path: Path) -> Callable[[str, str], Path]:
    """写入临时 .infd 文件的辅助：infd_file('app.infd', 'a = 1\\n') → Path。"""

    def _write(name: str, text: str) -> Path:
        p = tmp_path / name
        p.write_text(text, encoding='utf-8')
        return p

    return _write
