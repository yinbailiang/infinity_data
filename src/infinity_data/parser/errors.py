"""语法分析阶段错误类型与收集器"""

from dataclasses import dataclass

from infinity_data.infra.errors import ErrorCollector, InfinityDataError

# ═══════════════════════════════════════════════════════════
# 错误类型
# ═══════════════════════════════════════════════════════════


@dataclass
class ParseError(InfinityDataError):
    """语法分析阶段错误基类。

    ``source`` 字段和 ``message`` 属性 / ``__str__`` 方法
    由 :class:`InfinityDataError` 提供。
    """

    def _format_message(self) -> str:
        return '语法分析错误'


@dataclass
class UnexpectedTokenError(ParseError):
    """期望某类 token 但实际遇到其他 token。"""

    expected: str
    actual: str

    def _format_message(self) -> str:
        return f'[{self.location}] 期望 {self.expected}，实际为 {self.actual}'


@dataclass
class TemplateArgOrderError(ParseError):
    """模板调用中位置参数出现在命名参数之后。"""

    def _format_message(self) -> str:
        return f'[{self.location}] 位置参数不能出现在命名参数之后'


@dataclass
class EmptyTokenListError(ParseError):
    """Token 列表为空，无法解析。"""

    def _format_message(self) -> str:
        return 'Token 列表为空，无法解析'


@dataclass
class InvalidJsonPathError(ParseError):
    """无效 JSON 路径。"""

    detail: str = ''

    def _format_message(self) -> str:
        msg = f'[{self.location}] 无效的 JSON 路径'
        if self.detail:
            msg += f': {self.detail}'
        return msg


# ═══════════════════════════════════════════════════════════
# 错误收集器
# ═══════════════════════════════════════════════════════════


class ParseErrorCollector(ErrorCollector[ParseError]):
    """语法分析错误收集器。

    用法:
        collector = ParseErrorCollector()
        parser = Parser(tokens, error_collector=collector)
        doc = parser.parse()
        for err in collector:
            print(err.message)
    """
