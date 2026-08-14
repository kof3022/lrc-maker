"""本地配置读写。config.local.json 仅保存在本机，不会上传。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    CONFIG_PATH = Path(sys.executable).resolve().parent / "config.local.json"
else:
    CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.local.json"

DEFAULTS = {
    "model_size": "medium",
    "language": "zh",
    "initial_prompt": "以下是歌曲的歌词。",
    "no_speech_threshold": 0.75,
    "provider": "local",
    "api_key": "",
    "hotword_boost": True,
}


def load_config() -> dict:
    """读取配置，缺失字段用默认值补齐。"""
    cfg = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except Exception:
            pass
    return cfg


def save_config(values: dict) -> None:
    """保存配置（合并默认值，覆盖写入）。"""
    cfg = dict(DEFAULTS)
    cfg.update(values)
    CONFIG_PATH.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
    )