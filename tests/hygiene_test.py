"""仓库卫生守卫：生产代码零类型遮蔽。

项目铁律要求 `src/infinity_data/` 下不得出现任何 `# type:` / `# pyright:` 注释——
遮蔽会让 strict 类型检查静默失效，且不会有任何运行时反馈。本测试把该规则固化进
测试门禁：CI 测试矩阵与 pre-commit 的 pytest 钩子都会执行它。
"""

import re
from pathlib import Path

SRC_PACKAGE_ROOT = Path(__file__).resolve().parents[1] / 'src' / 'infinity_data'

_SUPPRESSION_PATTERN = re.compile(r'#\s*(?:type|pyright)\s*:')


def _python_files(root: Path) -> list[Path]:
    """返回目录下全部 Python 源文件（跳过缓存目录）。"""
    return sorted(path for path in root.rglob('*.py') if '__pycache__' not in path.parts)


def _find_suppressions(root: Path) -> list[tuple[Path, int, str]]:
    """扫描目录，返回 (文件, 行号, 行内容) 形式的类型遮蔽注释。"""
    return [
        (path, line_no, text.strip())
        for path in _python_files(root)
        for line_no, text in enumerate(path.read_text(encoding='utf-8').splitlines(), start=1)
        if _SUPPRESSION_PATTERN.search(text)
    ]


def test_guard_targets_source_package() -> None:
    """守卫目标路径必须真实存在，避免扫描目录写错后静默通过。"""
    assert (SRC_PACKAGE_ROOT / 'pipeline.py').is_file()


def test_source_has_no_type_suppressions() -> None:
    """生产代码中禁止出现类型遮蔽注释。"""
    offenders = [
        f'{path.relative_to(SRC_PACKAGE_ROOT.parent.parent).as_posix()}:{line_no}: {text}'
        for path, line_no, text in _find_suppressions(SRC_PACKAGE_ROOT)
    ]
    assert offenders == [], '生产代码禁止类型遮蔽注释：\n' + '\n'.join(offenders)


def test_suppression_finder_is_effective(tmp_path: Path) -> None:
    """守卫本身必须能命中遮蔽注释，且不误报普通注释。"""
    (tmp_path / 'clean.py').write_text('# 普通注释：解释为什么\nVALUE = 1\n', encoding='utf-8')
    (tmp_path / 'dirty.py').write_text(
        'VALUE = 1  # type: ignore[assignment]\nOTHER = 2  # pyright: reportAny=false\n',
        encoding='utf-8',
    )

    found = _find_suppressions(tmp_path)

    assert [path.name for path, _, _ in found] == ['dirty.py', 'dirty.py']
    assert [line_no for _, line_no, _ in found] == [1, 2]
