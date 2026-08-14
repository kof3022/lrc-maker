"""LRC 文件生成。"""

from __future__ import annotations


def format_time(seconds: float) -> str:
    """秒 → LRC 时间格式 mm:ss.xx。"""
    seconds = max(0.0, float(seconds))
    m = int(seconds // 60)
    s = seconds - m * 60
    return f"{m:02d}:{s:05.2f}"


def build_lrc(lines: list[dict], meta: dict | None = None) -> str:
    """由对齐结果生成 LRC 文本。

    lines: [{text, start}]，start 为 None 的行保留为无时间戳纯文本。
    meta: {title, artist, album} 可选元数据。
    """
    meta = meta or {}
    out = []
    for key, label in (("title", "ti"), ("artist", "ar"), ("album", "al")):
        value = (meta.get(key) or "").strip()
        if value:
            out.append(f"[{label}:{value}]")
    for line in lines:
        text = line["text"].strip()
        if not text:
            continue
        start = line.get("start")
        if start is None:
            out.append(text)
        else:
            out.append(f"[{format_time(start)}]{text}")
    return "\n".join(out) + "\n"