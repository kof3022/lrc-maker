"""歌词文本解析与规范化。"""

from __future__ import annotations

import re
import unicodedata


def parse_lines(text: str) -> list[str]:
    """把歌词文本按行拆分为数组：去除首尾空白、空行。"""
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if line:
            lines.append(line)
    return lines


def normalize(text: str) -> str:
    """规范化文本用于模糊匹配：全角转半角、小写、去标点、压缩空白。"""
    text = unicodedata.normalize("NFKC", text).lower()
    text = re.sub(r"[^\w\s\u4e00-\u9fff]", "", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()