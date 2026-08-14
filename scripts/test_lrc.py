"""LRC 生成单元测试。运行: .venv/Scripts/python scripts/test_lrc.py"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.lrc import build_lrc, format_time


def test_format_time():
    assert format_time(0) == "00:00.00"
    assert format_time(61.5) == "01:01.50"
    assert format_time(3600) == "60:00.00"
    assert format_time(-3) == "00:00.00"


def test_build_lrc():
    lines = [
        {"text": "第一句", "start": 1.25},
        {"text": "第二句", "start": None},
    ]
    lrc = build_lrc(lines, {"title": "歌名", "artist": "歌手"})
    assert "[ti:歌名]" in lrc
    assert "[ar:歌手]" in lrc
    assert "[00:01.25]第一句" in lrc
    assert lrc.rstrip().endswith("第二句")


def main():
    test_format_time()
    test_build_lrc()
    print("test_lrc: OK")


if __name__ == "__main__":
    main()