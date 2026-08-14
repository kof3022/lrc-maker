"""对齐算法单元测试（纯合成数据，不依赖模型）。运行: .venv/Scripts/python scripts/test_aligner.py"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.aligner import align


def unit(text, start, end, word=None):
    w = word if word is not None else text
    return {
        "start": start,
        "end": end,
        "text": text,
        "words": [{"start": start, "end": end, "word": w}],
    }


def test_basic():
    lyrics = ["第一句歌词", "第二句歌词"]
    segments = [
        unit("第一句歌词", 3.0, 5.0),
        unit("第二句歌词", 8.0, 10.0),
    ]
    res = align(lyrics, segments)
    assert res[0]["start"] == 3.0 and res[0]["matched"]
    assert res[1]["start"] == 8.0 and res[1]["matched"]


def test_chorus_repeat():
    lyrics = ["副歌", "主歌", "副歌"]
    segments = [
        unit("副歌", 2.0, 3.0),
        unit("主歌", 5.0, 6.0),
        unit("副歌", 9.0, 10.0),
    ]
    res = align(lyrics, segments)
    assert [r["start"] for r in res] == [2.0, 5.0, 9.0]


def test_skip_segment():
    lyrics = ["真正的歌词"]
    segments = [
        unit("纯音乐旋律没有歌词", 0.5, 1.5),
        unit("真正的歌词", 3.0, 4.0),
    ]
    res = align(lyrics, segments)
    assert res[0]["start"] == 3.0 and res[0]["matched"]


def test_extra_line():
    """歌词里有、但音频里没有的行，也会被覆盖（救援或估算），时间落在音频区间内。"""
    lyrics = ["唱的歌词", "歌词里没有这一句", "另一句歌词"]
    segments = [
        unit("唱的歌词", 1.0, 2.0),
        unit("另一句歌词", 4.0, 5.0),
    ]
    res = align(lyrics, segments)
    assert res[0]["start"] == 1.0
    assert res[1]["source"] in ("interp", "rescue")
    assert res[1]["start"] is not None and 1.0 <= res[1]["start"] <= 4.0
    assert res[2]["start"] == 4.0


def test_split_on_punct():
    """whisper 把两句并成一段时，应按标点切分后分别对齐。"""
    segments = [
        {
            "start": 2.0,
            "end": 6.0,
            "text": "第一句。第二句",
            "words": [
                {"start": 2.0, "end": 3.5, "word": "第一句。"},
                {"start": 4.5, "end": 6.0, "word": "第二句"},
            ],
        }
    ]
    lyrics = ["第一句", "第二句"]
    res = align(lyrics, segments)
    assert res[0]["start"] == 2.0 and res[0]["matched"]
    assert res[1]["start"] == 4.5 and res[1]["matched"]


def test_no_segments():
    lyrics = ["歌词一", "歌词二"]
    res = align(lyrics, [])
    assert all(r["start"] is None for r in res)


def test_rescue_homophone():
    """识别成同音/近似词时，救援匹配应补上行。"""
    lyrics = ["像我这样的人啊", "学不会喊累 也学不会停"]
    segments = [
        {
            "start": 48.62,
            "end": 61.83,
            "text": "像我这样的人啊却不会很累",
            "words": [
                {"start": 48.62, "end": 50.0, "word": "像我"},
                {"start": 50.0, "end": 51.2, "word": "这样"},
                {"start": 51.2, "end": 52.4, "word": "的人啊"},
                {"start": 52.4, "end": 53.6, "word": "却"},
                {"start": 53.6, "end": 54.8, "word": "不会"},
                {"start": 54.8, "end": 56.0, "word": "很累"},
            ],
        }
    ]
    res = align(lyrics, segments)
    assert res[0]["start"] == 48.62
    assert res[1]["start"] is not None
    assert res[1]["start"] >= res[0]["start"]
    assert res[1]["source"] == "rescue"


def test_interp_bounded():
    """完全没识别到的行，应在前后已匹配行之间估算时间。"""
    lyrics = ["第一句", "中间没识别到", "第三句"]
    segments = [
        unit("第一句", 1.0, 2.0),
        unit("第三句", 10.0, 11.0),
    ]
    res = align(lyrics, segments)
    assert res[0]["start"] == 1.0
    assert res[1]["source"] == "interp"
    assert 2.0 <= res[1]["start"] <= 10.0
    assert res[2]["start"] == 10.0


def test_interp_trailing():
    """结尾没识别到的行，应跟在最后已匹配行之后估算。"""
    lyrics = ["第一句", "结尾两句没识别到", "也没识别到"]
    segments = [unit("第一句", 1.0, 2.0)]
    res = align(lyrics, segments)
    assert res[0]["start"] == 1.0
    assert res[1]["start"] is not None and res[1]["start"] >= 2.0
    assert res[2]["start"] is not None and res[2]["start"] >= res[1]["start"]


def main():
    test_basic()
    test_chorus_repeat()
    test_skip_segment()
    test_extra_line()
    test_split_on_punct()
    test_no_segments()
    test_rescue_homophone()
    test_interp_bounded()
    test_interp_trailing()
    print("test_aligner: OK")


if __name__ == "__main__":
    main()