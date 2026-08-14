"""把音频转写结果（含词级时间戳）存为 JSON，供离线调试对齐。

用法: .venv/Scripts/python scripts/dump_segments.py <mp3路径> <输出json路径>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import load_config
from core.transcriber import Transcriber


def main() -> None:
    if len(sys.argv) < 3:
        print("用法: dump_segments.py <mp3路径> <输出json路径>")
        sys.exit(1)
    mp3 = sys.argv[1]
    out = Path(sys.argv[2])
    cfg = load_config()
    tr = Transcriber(
        model_size=cfg["model_size"],
        language=cfg["language"] or None,
        initial_prompt=cfg.get("initial_prompt"),
        no_speech_threshold=cfg.get("no_speech_threshold"),
    )
    segments, duration = tr.transcribe_file(mp3)
    out.write_text(
        json.dumps({"duration": duration, "segments": segments}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(f"已保存 {len(segments)} 段, 时长 {duration:.2f}s → {out}")


if __name__ == "__main__":
    main()