from collections.abc import AsyncIterable

from infinity_data.infra.ll1_stream import LL1Stream
from infinity_data.tokenizer.models.raw_tokens import SourceInfo


class LineCounter:
    """行号/列号/字符序号计数器。"""

    def __init__(self) -> None:
        self._index: int = 0
        self._line: int = 1
        self._col: int = 1
        self._last_was_cr: bool = False

    def step(self, ch: str) -> None:
        """根据当前消费的字符推进 index/line/col。"""
        for c in ch:
            self._index += 1
            if c == '\n':
                self._line += 1
                self._col = 1
            else:
                self._col += 1

    @property
    def index(self) -> int:
        return self._index

    @property
    def line(self) -> int:
        return self._line

    @property
    def col(self) -> int:
        return self._col


class CharStream(LL1Stream[str]):
    """字符流：在 LL(1) 流基础上附加行列位置跟踪。"""

    def __init__(self, source: AsyncIterable[str]) -> None:
        super().__init__(source)
        self._counter: LineCounter = LineCounter()

    # ── 同步行列属性 ──────────────────────────────────────

    @property
    def index(self) -> int:
        return self._counter.index

    @property
    def line(self) -> int:
        return self._counter.line

    @property
    def col(self) -> int:
        return self._counter.col

    def info(self, file_path: str) -> SourceInfo:
        return SourceInfo(
            file_path=file_path,
            index=self.index,
            line=self.line,
            col=self.col,
        )

    # ── 内部钩子 ──────────────────────────────────────────

    async def _on_advance(self, item: str) -> None:
        """消费字符时同步更新行列计数器。"""
        self._counter.step(item)
