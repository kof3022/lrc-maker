"""用已缓存的转写结果离线对齐歌词并保存 LRC（无需重新识别）。

用法: .venv/Scripts/python scripts/align_offline.py <segments.json> <歌词txt> [歌名] [输出lrc路径]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.aligner import align
from core.lrc import build_lrc
from core.lyrics import parse_lines


def main() -> None:
    if len(sys.argv) < 3:
        print("用法: align_offline.py <segments.json> <歌词txt> [歌名] [输出lrc路径]")
        sys.exit(1)
    data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    lyrics = Path(sys.argv[2]).read_text(encoding="utf-8")
    title = sys.argv[3] if len(sys.argv) > 3 else "歌词"
    out_path = Path(sys.argv[4]) if len(sys.argv) > 4 else Path("data") / f"{title}.lrc"

    lines = parse_lines(lyrics)
    results = align(lines, data["segments"])
    matched = sum(1 for r in results if r["start"] is not None)
    kinds = {"match": 0, "rescue": 0, "interp": 0}
    for r in results:
        if r["start"] is not None:
            kinds[r.get("source", "match")] += 1
    print(f"有时间戳: {matched}/{len(results)}（可靠 {kinds['match']} / 低置信 {kinds['rescue']} / 估算 {kinds['interp']}）")
    for i, r in enumerate(results, 1):
        start = f"{r['start']:7.2f}" if r["start"] is not None else "     --"
        flag = {"match": "OK", "rescue": "RS", "interp": "IN", "none": "--"}.get(
            r.get("source", "match"), "??"
        )
        print(f"{i:2d} {flag} {start}  {r['text']}  conf={r['confidence']}")

    lrc = build_lrc(
        results,
        {"title": title, "artist": "", "album": ""},
    )
    out_path.write_text(lrc, encoding="utf-8")
    print("LRC 已保存:", out_path)


if __name__ == "__main__":
    main()