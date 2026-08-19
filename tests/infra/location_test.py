"""infra/location.py 单元测试：SourceInfo / SourceRange / format_location。"""

from pathlib import Path

from infinity_data.infra.file import MemFile
from infinity_data.infra.location import SourceInfo, SourceRange, format_location


def _mem(name: str = 'x.infd') -> MemFile:
    return MemFile(name=name, root_path=Path('.'), content='')


def test_source_info_fields() -> None:
    info = SourceInfo(line=2, col=3, index=10)
    assert (info.line, info.col, info.index) == (2, 3, 10)


def test_source_range_at_is_zero_width() -> None:
    f = _mem()
    pos = SourceInfo(line=1, col=5, index=4)
    rng = SourceRange.at(f, pos)
    assert rng.start == pos
    assert rng.end == pos


def test_format_location_none() -> None:
    assert format_location(None) == '<unknown>'


def test_format_location_zero_width() -> None:
    rng = SourceRange.at(_mem('app.infd'), SourceInfo(line=3, col=7, index=20))
    assert format_location(rng) == 'app.infd:3:7'


def test_format_location_nonzero_width() -> None:
    rng = SourceRange(
        file=_mem('app.infd'),
        start=SourceInfo(line=2, col=3, index=5),
        end=SourceInfo(line=2, col=9, index=11),
    )
    assert format_location(rng) == 'app.infd:2:3-2:9'


def test_source_range_empty() -> None:
    rng = SourceRange.empty()
    assert rng.start == rng.end
    assert format_location(rng) == '<unknown>:0:0'
