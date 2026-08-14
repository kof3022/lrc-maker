"""语音识别模块（本地 faster-whisper，离线运行），输出词级时间戳。"""

from __future__ import annotations

import sys
from pathlib import Path


class Transcriber:
    """本地语音识别。

    参数:
        model_size: 模型大小（small / base / medium / large-v3）
        language: 识别语言（"zh" / "en" / None 自动检测）
        initial_prompt: 开头提示词，引导模型理解内容类型（如"以下是歌曲的歌词。"）
        no_speech_threshold: 无语音判定阈值（越大越倾向跳过纯音乐/静音）
    """

    def __init__(
        self,
        model_size: str = "medium",
        language: str | None = "zh",
        device: str = "cpu",
        compute_type: str = "int8",
        initial_prompt: str | None = None,
        no_speech_threshold: float | None = None,
    ):
        self.model_size = model_size
        self.language = language  # None 表示自动检测
        self.device = device
        self.compute_type = compute_type
        self.initial_prompt = initial_prompt
        self.no_speech_threshold = no_speech_threshold
        self._model = None
        self._converter = None

    def _local_model_dir(self) -> str | None:
        """打包后优先使用 exe 旁的 models/<尺寸> 目录，实现完全离线。"""
        if getattr(sys, "frozen", False):
            base = Path(sys.executable).resolve().parent
        else:
            base = Path(__file__).resolve().parent.parent
        model_dir = base / "models" / self.model_size
        if (model_dir / "model.bin").exists():
            return str(model_dir)
        return None

    def _ensure_model(self):
        if self._model is None:
            from faster_whisper import WhisperModel

            model_path = self._local_model_dir() or self.model_size
            self._model = WhisperModel(
                model_path, device=self.device, compute_type=self.compute_type
            )
        return self._model

    def _simplify(self, text: str) -> str:
        """把繁体中文转为简体（whisper 中文输出常为繁体）。"""
        if self.language != "zh":
            return text
        if self._converter is None:
            import opencc

            self._converter = opencc.OpenCC("t2s")
        return self._converter.convert(text)

    def transcribe_file(self, path: str | Path) -> tuple[list[dict], float]:
        """转写音频文件，返回 (段列表, 时长秒)。

        每段: {start, end, text, words: [{start, end, word}]}
        """
        model = self._ensure_model()
        segments, info = model.transcribe(
            str(path),
            language=self.language,
            beam_size=5,
            vad_filter=True,
            initial_prompt=self.initial_prompt,
            no_speech_threshold=self.no_speech_threshold,
            word_timestamps=True,
        )
        result = []
        for seg in segments:
            words = []
            for w in seg.words or []:
                word = (w.word or "").strip()
                if word:
                    words.append(
                        {"start": float(w.start), "end": float(w.end), "word": word}
                    )
            result.append(
                {
                    "start": float(seg.start),
                    "end": float(seg.end),
                    "text": self._simplify(seg.text.strip()),
                    "words": words,
                }
            )
        duration = float(getattr(info, "duration", 0.0) or 0.0)
        return result, duration