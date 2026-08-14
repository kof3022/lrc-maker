"""端到端冒烟测试：真实音频 → whisper 词级转写 → 歌词对齐。

用法: .venv/Scripts/python scripts/test_pipeline.py <音频> <模型大小> <语言> [歌词行...]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.aligner import align
from core.transcriber import Transcriber


def main() -> None:
    if len(sys.argv) < 4:
        print("用法: test_pipeline.py <音频> <模型大小> <语言> [歌词行...]")
        sys.exit(1)
    wav = sys.argv[1]
    model_size = sys.argv[2]
    language = sys.argv[3] or None
    lyrics = sys.argv[4:]

    tr = Transcriber(
        model_size=model_size,
        language=language,
        initial_prompt=None if language != "zh" else "以下是歌曲的歌词。",
    )
    segments, duration = tr.transcribe_file(wav)
    print(f"时长: {duration:.2f}s, 段落数: {len(segments)}")
    for seg in segments:
        words = " ".join(w["word"] for w in seg["words"][:8])
        print(f"  [{seg['start']:.2f}-{seg['end']:.2f}] {seg['text']} | words: {words}")

    if lyrics:
        results = align(lyrics, segments)
        matched = sum(1 for r in results if r["start"] is not None)
        print(f"对齐: {matched}/{len(results)} 行匹配")
        for r in results:
            start = f"{r['start']:.2f}" if r["start"] is not None else "  --  "
            flag = "OK " if r["matched"] else ("-- " if r["start"] is None else "?? ")
            print(f"  {flag} {start}s  {r['text']}")


if __name__ == "__main__":
    main()