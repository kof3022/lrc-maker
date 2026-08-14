"""服务器接口冒烟测试（不加载模型）。运行: .venv/Scripts/python scripts/test_server.py"""

from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import Handler

PORT = 8799


def main():
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    base = f"http://127.0.0.1:{PORT}"

    # 首页
    with urllib.request.urlopen(base + "/") as r:
        html = r.read().decode("utf-8")
        assert r.status == 200 and "歌词时间戳" in html

    # 配置读取
    with urllib.request.urlopen(base + "/api/config") as r:
        cfg = json.loads(r.read())
        assert "model_size" in cfg

    # 缺文件 → 400
    try:
        req = urllib.request.Request(base + "/api/align", data=b"", method="POST")
        urllib.request.urlopen(req)
        raise AssertionError("应返回 400")
    except urllib.error.HTTPError as e:
        assert e.code == 400

    server.shutdown()
    print("test_server: OK")


if __name__ == "__main__":
    main()