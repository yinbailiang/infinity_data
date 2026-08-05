"""语法分析阶段错误类型与收集器"""

from dataclasses import dataclass

from infinity_data.tokenizer.models.raw_tokens import SourceRange

# ═══════════════════════════════════════════════════════════
# 错误类型
# ═══════════════════════════════════════════════════════════

@dataclass
class ParseError(Exception):
    """语法分析阶段错误基类。"""
    source: SourceRange

    @property
    def message(self) -> str:
        """人类可读的错误消息。"""
        return self._format_message()

    def _format_message(self) -> str:
        return "语法分析错误"


@dataclass
class UnexpectedTokenError(ParseError):
    """期望某类 token 但实际遇到其他 token。"""
    expected: str
    actual: str

    def _format_message(self) -> str:
        loc = f"{self.source.start.file_path}:{self.source.start.line}:{self.source.start.col}"
        return f"[{loc}] 期望 {self.expected}，实际为 {self.actual}"


@dataclass
class InvalidImportKeywordError(ParseError):
    """! 导入语句后跟非法关键字（非 env/file/from）。"""
    actual: str

    def _format_message(self) -> str:
        loc = f"{self.source.start.file_path}:{self.source.start.line}"
        return f"[{loc}] ! 后期望 env/file/from，实际为 {self.actual}"


@dataclass
class TemplateArgOrderError(ParseError):
    """模板调用中位置参数出现在命名参数之后。"""

    def _format_message(self) -> str:
        loc = f"{self.source.start.file_path}:{self.source.start.line}"
        return f"[{loc}] 位置参数不能出现在命名参数之后"


@dataclass
class EmptyTokenListError(ParseError):
    """Token 列表为空，无法解析。"""

    def _format_message(self) -> str:
        return "Token 列表为空，无法解析"


@dataclass
class InvalidJsonPathError(ParseError):
    """无效 JSON 路径。"""
    detail: str = ""

    def _format_message(self) -> str:
        loc = f"{self.source.start.file_path}:{self.source.start.line}"
        msg = f"[{loc}] 无效的 JSON 路径"
        if self.detail:
            msg += f": {self.detail}"
        return msg


# ═══════════════════════════════════════════════════════════
# 错误收集器
# ═══════════════════════════════════════════════════════════

class ParseErrorCollector:
    """语法分析错误收集器。

    用法:
        collector = ParseErrorCollector()
        parser = Parser(tokens, error_collector=collector)
        doc = parser.parse()
        for err in collector.errors:
            print(err.message)
    """

    def __init__(self) -> None:
        self._errors: list[ParseError] = []

    def add(self, error: ParseError) -> None:
        """添加一个错误。"""
        self._errors.append(error)

    @property
    def errors(self) -> list[ParseError]:
        """返回所有已收集错误的副本。"""
        return self._errors.copy()

    @property
    def has_errors(self) -> bool:
        """是否有已收集的错误。"""
        return len(self._errors) > 0
