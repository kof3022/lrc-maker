"""歌词解析与规范化单元测试。运行: .venv/Scripts/python scripts/test_lyrics.py"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.lyrics import normalize, parse_lines


def test_parse_lines():
    assert parse_lines("a\n\n  b \n\n\nc") == ["a", "b", "c"]
    assert parse_lines("") == []
    assert parse_lines("   \n\t\n") == []
    assert parse_lines("第一句\n第二句\n") == ["第一句", "第二句"]


def test_normalize():
    assert normalize("Hello, World!") == "hello world"
    assert normalize("你好，世界！") == "你好世界"
    assert normalize("ＦＵＬＬ ＷＩＤＴＨ") == "full width"
    assert normalize("a  b   c") == "a b c"
    assert normalize("！！！") == ""
    assert normalize("What's up?") == "whats up"


def main():
    test_parse_lines()
    test_normalize()
    print("test_lyrics: OK")


if __name__ == "__main__":
    main()