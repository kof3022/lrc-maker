"""诊断：打印 whisper 原始分段 + 未匹配歌词行的最佳候选单元。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.aligner import to_units
from core.config import load_config
from core.lyrics import normalize
from core.transcriber import Transcriber
from rapidfuzz import fuzz


def main() -> None:
    mp3 = sys.argv[1]
    cfg = load_config()
    tr = Transcriber(
        model_size=cfg["model_size"],
        language=cfg["language"] or None,
        initial_prompt=cfg.get("initial_prompt"),
        no_speech_threshold=cfg.get("no_speech_threshold"),
    )
    segments, duration = tr.transcribe_file(mp3)
    print(f"时长 {duration:.2f}s, 段落数 {len(segments)}")
    for i, seg in enumerate(segments):
        print(f"S{i+1:2d} [{seg['start']:7.2f}-{seg['end']:7.2f}] {seg['text']}")

    units = to_units(segments)
    unmatched = ["学不会喊累 也学不会停", "也挺好的", "我们还在 慢慢地 往前走", "慢慢地 往前走"]
    for line in unmatched:
        nl = normalize(line)
        scored = sorted(
            ((fuzz.ratio(nl, normalize(u["text"])), u) for u in units),
            key=lambda x: -x[0],
        )
        print(f"--- 候选: {line}")
        for sim, u in scored[:5]:
            print(f"    sim={sim:5.1f}  [{u['start']:6.2f}-{u['end']:6.2f}]  {u['text']}")


if __name__ == "__main__":
    main()