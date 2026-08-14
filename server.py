"""歌词时间戳 · 本地网页服务器（MP3 + 歌词 → LRC）。

运行: .venv/Scripts/python server.py [--port 8766] [--no-browser]
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import re
import sys
import threading
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from core.aligner import align
from core.config import load_config, save_config
from core.lrc import build_lrc
from core.lyrics import parse_lines
from core.transcriber import Transcriber

if getattr(sys, "frozen", False):
    ROOT = Path(sys.executable).resolve().parent
    WEB_DIR = Path(sys._MEIPASS) / "web"
    IMG_DIR = Path(sys._MEIPASS) / "img"
else:
    ROOT = Path(__file__).resolve().parent
    WEB_DIR = ROOT / "web"
    IMG_DIR = ROOT / "img"

UPLOAD_DIR = ROOT / "data" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_EXTS = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac"}
mimetypes.add_type("audio/mpeg", ".mp3")
mimetypes.add_type("audio/wav", ".wav")
def build_result(lines: list[str], segments: list, duration: float) -> dict:
    results = align(lines, segments)
    matched = sum(1 for r in results if r["start"] is not None)
    return {
        "duration": round(duration, 2),
        "segments": len(segments),
        "lines": results,
        "coverage": round(matched / len(results), 3) if results else 0,
    }


class AlignerService:
    """模型单例 + 串行化转写。"""

    def __init__(self):
        self.lock = threading.Lock()
        self.transcriber: Transcriber | None = None

    def run(self, path: Path, lyrics: str, cfg: dict) -> dict:
        with self.lock:
            if self.transcriber is None:
                self.transcriber = Transcriber(
                    model_size=cfg["model_size"],
                    language=cfg["language"] or None,
                    initial_prompt=cfg.get("initial_prompt") or None,
                    no_speech_threshold=cfg.get("no_speech_threshold") or None,
                )
            segments, duration = self.transcriber.transcribe_file(path)
        return build_result(parse_lines(lyrics), segments, duration)


class Handler(BaseHTTPRequestHandler):
    service = AlignerService()

    def log_message(self, fmt, *args):  # 精简日志
        pass

    # ---------- 工具 ----------
    def _json(self, obj, status=200):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _file(self, path: Path, content_type: str):
        if not path.is_file():
            self._json({"error": "文件不存在"}, 404)
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _parse_multipart(self) -> tuple[dict, dict]:
        """解析 multipart/form-data，返回 (文本字段, 文件字段)。"""
        ctype = self.headers.get("Content-Type", "")
        if "boundary=" not in ctype:
            return {}, {}
        boundary = ctype.split("boundary=", 1)[1].strip().strip('"').encode()
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length)
        fields, files = {}, {}
        for raw in body.split(b"--" + boundary):
            raw = raw.strip(b"\r\n")
            if not raw or raw == b"--":
                continue
            head, sep, content = raw.partition(b"\r\n\r\n")
            if not sep:
                continue
            headers = {}
            for line in head.split(b"\r\n"):
                if b":" in line:
                    k, v = line.split(b":", 1)
                    headers[k.strip().decode("latin-1").lower()] = v.strip().decode(
                        "latin-1"
                    )
            disp = headers.get("content-disposition", "")
            name, filename = None, None
            for piece in disp.split(";"):
                piece = piece.strip()
                if piece.lower().startswith("name="):
                    name = piece[5:].strip('"')
                elif piece.lower().startswith("filename="):
                    filename = piece[9:].strip('"')
            if name is None:
                continue
            if filename is not None:
                files[name] = {"filename": filename, "content": content}
            else:
                fields[name] = content.decode("utf-8", errors="replace")
        return fields, files

    # ---------- 路由 ----------
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            self._file(WEB_DIR / "index.html", "text/html; charset=utf-8")
        elif path.startswith("/img/"):
            name = Path(path[len("/img/") :]).name
            if not re.fullmatch(r"[A-Za-z0-9._-]+", name or ""):
                self._json({"error": "非法文件名"}, 400)
                return
            self._file(
                IMG_DIR / name,
                mimetypes.guess_type(name)[0] or "application/octet-stream",
            )
        elif path.startswith("/media/"):
            name = Path(path[len("/media/") :]).name
            if not re.fullmatch(r"[A-Za-z0-9._-]+", name or ""):
                self._json({"error": "非法文件名"}, 400)
                return
            self._file(
                UPLOAD_DIR / name,
                mimetypes.guess_type(name)[0] or "application/octet-stream",
            )
        elif path == "/api/config":
            self._json(load_config())
        else:
            self._json({"error": "未找到"}, 404)

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/config":
            try:
                length = int(self.headers.get("Content-Length", 0) or 0)
                values = json.loads(self.rfile.read(length) or b"{}")
            except Exception:
                self._json({"error": "配置格式错误"}, 400)
                return
            cfg = load_config()
            cfg.update({k: v for k, v in values.items() if k in cfg})
            save_config(cfg)
            self._json({"ok": True})
        elif path == "/api/align":
            self._handle_align()
        else:
            self._json({"error": "未找到"}, 404)

    def _handle_align(self):
        fields, files = self._parse_multipart()
        if "file" not in files:
            self._json({"error": "缺少音频文件"}, 400)
            return
        audio = files["file"]
        ext = Path(audio["filename"]).suffix.lower()
        if ext not in ALLOWED_EXTS:
            self._json({"error": f"不支持的格式: {ext or '未知'}"}, 400)
            return
        name = f"{uuid.uuid4().hex}{ext}"
        path = UPLOAD_DIR / name
        path.write_bytes(audio["content"])
        cfg = load_config()
        provider = cfg.get("provider", "local")
        lyrics = fields.get("lyrics", "")
        try:
            if provider == "local":
                result = self.service.run(path, lyrics, cfg)
            else:
                from core.online import transcribe
                segments, duration = transcribe(
                    path,
                    api_key=cfg.get("api_key", ""),
                    language=cfg.get("language", ""),
                    lyrics=fields.get("lyrics", "")
                    if cfg.get("hotword_boost", True)
                    else "",
                )
                result = build_result(parse_lines(lyrics), segments, duration)
        except Exception as exc:  # 模型/识别异常
            self._json({"error": f"识别失败: {exc}"}, 500)
            return
        result["media_url"] = f"/media/{name}"
        result["lrc"] = build_lrc(
            result["lines"],
            {
                "title": fields.get("title", ""),
                "artist": fields.get("artist", ""),
                "album": fields.get("album", ""),
            },
        )
        self._json(result)


def main() -> None:
    parser = argparse.ArgumentParser(description="歌词时间戳工具")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}"
    print(f"歌词时间戳已启动: {url}")
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已退出")


if __name__ == "__main__":
    main()