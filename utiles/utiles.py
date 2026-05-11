"""字符串感知的 JSON 括号计数工具。

正确处理 JSON 字符串字面量内的花括号和转义字符，
避免被 content 参数值中的 {sorted_arr}、}}}}}} 等内容干扰。
支持增量式逐 token 更新（流式场景）和一次性提取（批量解析场景）。
"""


class JsonBraceCounter:
    """增量式 JSON 括号计数器。

    用法::

        counter = JsonBraceCounter()
        for token in stream:
            counter.feed(token)
            print(counter.depth)   # 始终准确，不受字符串内花括号影响
    """

    __slots__ = ("depth", "in_string", "escape")

    def __init__(self) -> None:
        self.depth: int = 0
        self.in_string: bool = False
        self.escape: bool = False

    def feed(self, text: str) -> None:
        """输入一段文本，更新括号深度（可多次调用）。"""
        for c in text:
            if self.escape:
                self.escape = False
                continue
            if c == '\\' and self.in_string:
                self.escape = True
                continue
            if c == '"':
                self.in_string = not self.in_string
                continue
            if self.in_string:
                continue
            if c == '{':
                self.depth += 1
            elif c == '}':
                self.depth -= 1

    def reset(self) -> None:
        self.depth = 0
        self.in_string = False
        self.escape = False


def extract_balanced_json(text: str, start: int = 0) -> str | None:
    """从 text[start] 开始，提取一个完整的 JSON 对象。

    通过字符串感知的括号深度计数定位闭合位置，
    正确跳过字符串字面量内的花括号。

    返回提取到的完整 JSON 子串，或 None（括号不平衡）。
    """
    counter = JsonBraceCounter()
    for i in range(start, len(text)):
        counter.feed(text[i])
        if not counter.in_string and not counter.escape and counter.depth == 0 and i > start:
            return text[start:i + 1]
    return None
