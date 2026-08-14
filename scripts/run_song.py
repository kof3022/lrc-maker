"""命令行跑完整流程：上传 MP3 + 歌词 → 识别 → 对齐 → 保存 LRC。

用法: .venv/Scripts/python scripts/run_song.py <mp3路径> <歌词txt路径> [歌名] [输出lrc路径]
"""

from __future__ import annotations

import json
import sys
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import Handler

PORT = 8802


def main() -> None:
    if len(sys.argv) < 3:
        print("用法: run_song.py <mp3路径> <歌词txt路径> [歌名] [输出lrc路径]")
        sys.exit(1)
    mp3 = Path(sys.argv[1])
    lyrics_path = Path(sys.argv[2])
    title = sys.argv[3] if len(sys.argv) > 3 else mp3.stem
    out_path = Path(sys.argv[4]) if len(sys.argv) > 4 else Path("data") / f"{title}.lrc"

    lyrics = lyrics_path.read_text(encoding="utf-8")

    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    boundary = "----lrcrunboundary9384"

    def field(name: str, value: str) -> bytes:
        return (
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'
            f"{value}\r\n"
        ).encode("utf-8")

    body = b"".join(
        [
            field("lyrics", lyrics),
            field("title", title),
            field("artist", ""),
            field("album", ""),
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{mp3.name}"\r\nContent-Type: audio/mpeg\r\n\r\n'.encode(
                "utf-8"
            )
            + mp3.read_bytes()
            + b"\r\n",
            f"--{boundary}--\r\n".encode("utf-8"),
        ]
    )

    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}/api/align",
        data=body,
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    print("识别中，请耐心等待（本地运行）…")
    with urllib.request.urlopen(req, timeout=1800) as r:
        data = json.loads(r.read().decode("utf-8"))

    out_path.write_text(data["lrc"], encoding="utf-8")
    print(f"时长: {data['duration']}s | 覆盖: {data['coverage'] * 100:.0f}%")
    for i, ln in enumerate(data["lines"], 1):
        start = f"{ln['start']:7.2f}" if ln["start"] is not None else "     --"
        flag = "OK" if ln["matched"] else ("--" if ln["start"] is None else "??")
        print(f"{i:2d} {flag} {start}  {ln['text']}  conf={ln['confidence']}")
    print("LRC 已保存:", out_path)
    server.shutdown()


if __name__ == "__main__":
    main()