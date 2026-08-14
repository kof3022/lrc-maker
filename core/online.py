"""在线语音识别：阿里云百炼 DashScope · 千问实时识别（WebSocket，api-ws 协议）。

把本地音频解码为 16kHz 单声道 PCM 后，通过实时识别接口推送给
paraformer-realtime-v2，返回与本地 faster-whisper 一致的词级时间戳结构，
供对齐模块直接复用。

协议与官方 dashscope SDK 保持一致：
  连接  wss://dashscope.aliyuncs.com/api-ws/v1/inference
  start 消息的 model/parameters/input/task/task_group/function 全部放在 payload 中；
  音频以二进制帧发送，结束后发送 finish-task。
"""

from __future__ import annotations

import base64
import json
import os
import re
import socket
import ssl
import struct
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

REALTIME_URL = "wss://dashscope.aliyuncs.com/api-ws/v1/inference"
DEFAULT_MODEL = "paraformer-realtime-v2"
SAMPLE_RATE = 16000
CHUNK_SECONDS = 0.1
CONNECT_TIMEOUT = 20
IDLE_TIMEOUT = 120
WAIT_AFTER_STOP = 120
# 推流节奏：每块 0.1 秒音频后暂停 30ms（约 3.3 倍实时速率），
# 避免因推流过快被服务端强制断开连接
SEND_PACE_SECONDS = 0.03
# 连接中断等瞬时错误自动重试次数与退避间隔（秒）
RECOGNITION_RETRY = 2
RETRY_BACKOFF_SECONDS = (5, 15)
VOCAB_URL = "https://dashscope.aliyuncs.com/api/v1/services/audio/asr/customization"
VOCAB_TARGET_MODEL = "paraformer-realtime-v2"
VOCAB_PREFIX = "lrcmk"


class OnlineError(RuntimeError):
    """在线识别失败（含用户可读的中文信息）。"""


class _WS:
    """极简 WebSocket 客户端（覆盖本服务需要的帧类型）。"""

    def __init__(self, url: str, headers: dict[str, str]):
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "wss":
            raise OnlineError("仅支持 wss 协议")
        host = parsed.hostname or "dashscope.aliyuncs.com"
        port = parsed.port or 443
        self._sock = socket.create_connection((host, port), timeout=CONNECT_TIMEOUT)
        try:
            ctx = ssl.create_default_context()
            self._sock = ctx.wrap_socket(self._sock, server_hostname=host)
            key = base64.b64encode(os.urandom(16)).decode()
            path = parsed.path or "/"
            if parsed.query:
                path += "?" + parsed.query
            req = (
                f"GET {path} HTTP/1.1\r\n"
                f"Host: {host}:{port}\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {key}\r\n"
                "Sec-WebSocket-Version: 13\r\n"
            )
            for k, v in headers.items():
                req += f"{k}: {v}\r\n"
            req += "\r\n"
            self._sock.sendall(req.encode("utf-8"))
            resp = b""
            while b"\r\n\r\n" not in resp:
                chunk = self._sock.recv(4096)
                if not chunk:
                    raise OnlineError("WebSocket 握手失败：连接被关闭")
                resp += chunk
            first = resp.split(b"\r\n", 1)[0].decode("latin-1", "replace")
            if " 101 " not in first:
                body = b""
                try:
                    self._sock.settimeout(5)
                    while True:
                        chunk = self._sock.recv(4096)
                        if not chunk:
                            break
                        body += chunk
                except Exception:
                    pass
                detail = body.decode("utf-8", "replace")[:400]
                raise OnlineError(f"WebSocket 握手失败: {first} {detail}")
            self._sock.settimeout(IDLE_TIMEOUT)
        except Exception:
            try:
                self._sock.close()
            except Exception:
                pass
            raise

    def _send_frame(self, opcode: int, payload: bytes):
        mask = os.urandom(4)
        n = len(payload)
        header = struct.pack("!B", 0x80 | opcode)
        if n < 126:
            header += struct.pack("!B", 0x80 | n)
        elif n < 65536:
            header += struct.pack("!BH", 0x80 | 126, n)
        else:
            header += struct.pack("!BQ", 0x80 | 127, n)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self._sock.sendall(header + mask + masked)

    def send_text(self, text: str):
        self._send_frame(0x1, text.encode("utf-8"))

    def send_bytes(self, data: bytes):
        self._send_frame(0x2, data)

    def _read(self, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = self._sock.recv(n - len(buf))
            if not chunk:
                raise OnlineError("WebSocket 连接已关闭")
            buf += chunk
        return buf

    def recv_frame(self) -> tuple[int, bytes]:
        """返回 (opcode, payload)。opcode: 1 文本 / 2 二进制 / 8 关闭 / 9 ping / 10 pong。"""
        b1, b2 = self._read(2)
        opcode = b1 & 0x0F
        masked = b2 & 0x80
        n = b2 & 0x7F
        if n == 126:
            n = struct.unpack("!H", self._read(2))[0]
        elif n == 127:
            n = struct.unpack("!Q", self._read(8))[0]
        mask = self._read(4) if masked else None
        payload = self._read(n)
        if mask:
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        return opcode, payload

    def close(self):
        try:
            self._send_frame(0x8, b"")
        except Exception:
            pass
        try:
            self._sock.close()
        except Exception:
            pass


class _RealtimeClient:
    def __init__(self, api_key: str, language: str, vocabulary_id: str | None = None):
        self.api_key = api_key
        self.language = language
        self.vocabulary_id = vocabulary_id
        self.events: list[dict] = []
        self.error: str | None = None
        self.finished = False  # 是否已收到 task-finished
        self.close_code: int | None = None  # 服务端关闭帧 code
        self.close_reason = ""  # 服务端关闭帧 reason
        self._task_id = uuid.uuid4().hex
        self._started = threading.Event()
        self._done = threading.Event()
        self._ws = _WS(
            REALTIME_URL,
            {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "User-Agent": "lrc-maker/1.0",
            },
        )
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    def _read_loop(self):
        try:
            while not self._done.is_set():
                opcode, payload = self._ws.recv_frame()
                if opcode == 8:
                    # 记录服务端关闭帧的 code/reason，便于区分限流与正常结束
                    if len(payload) >= 2:
                        self.close_code = struct.unpack("!H", payload[:2])[0]
                        self.close_reason = payload[2:].decode("utf-8", "replace")
                    if not self.finished:
                        self.error = "识别服务连接中断（可能为临时限流或网络波动）"
                    self._done.set()
                    return
                if opcode == 9:
                    self._ws._send_frame(0xA, payload)
                    continue
                if opcode == 1:
                    try:
                        msg = json.loads(payload.decode("utf-8"))
                    except Exception:
                        continue
                    self.events.append(msg)
                    header = msg.get("header") or {}
                    event = header.get("event", "")
                    if event == "task-started":
                        self._started.set()
                    elif event == "task-failed":
                        self.error = (
                            header.get("error_message")
                            or header.get("message")
                            or f"识别失败(code={header.get('error_code')})"
                        )
                        self._done.set()
                    elif event == "task-finished":
                        self.finished = True
                        self._done.set()
        except Exception as exc:
            if not self._done.is_set():
                self.error = str(exc)
                self._done.set()

    def _send(self, msg: dict):
        self._ws.send_text(json.dumps(msg, ensure_ascii=False))

    def start(self):
        """发送 run-task 建立识别会话，并等待服务端 task-started 确认。"""
        msg = {
            "header": {
                "task_id": self._task_id,
                "streaming": "duplex",
                "action": "run-task",
            },
            "payload": {
                "model": DEFAULT_MODEL,
                "parameters": {
                    "format": "pcm",
                    "sample_rate": SAMPLE_RATE,
                    "stream": True,
                    "language_hints": [self.language] if self.language else [],
                    "enable_partial_result": False,
                    "enable_punctuation_prediction": True,
                    "enable_inverse_text_normalization": True,
                    "timestamp_alignment_enabled": True,
                    "disfluency_removal_enabled": False,
                    "max_sentence_silence": 800,
                    "speech_noise_threshold": 0.5,
                },
                "input": {},
                "task": "asr",
                "task_group": "audio",
                "function": "recognition",
            },
        }
        if self.vocabulary_id:
            msg["payload"]["parameters"]["vocabulary_id"] = self.vocabulary_id
        self._send(msg)
        if not self._started.wait(15) and not self.error:
            raise OnlineError("识别服务未响应（等待 task-started 超时）")
        if self.error:
            raise OnlineError(f"识别服务拒绝: {self.error}")

    def finish(self):
        """发送 finish-task，通知服务端音频已发送完毕。"""
        msg = {
            "header": {
                "task_id": self._task_id,
                "action": "finish-task",
            },
            "payload": {"input": {}},
        }
        self._send(msg)

    def send_audio(self, data: bytes):
        self._ws.send_bytes(data)

    def close(self):
        self._ws.close()


def _iter_pcm(path, chunk_bytes: int):
    """把任意音频解码为 16kHz 单声道 16bit PCM，逐块产出。"""
    try:
        import av
    except Exception as exc:
        raise OnlineError("缺少音频解码库 av，无法转换音频格式") from exc
    container = av.open(str(path))
    try:
        stream = next((s for s in container.streams if s.type == "audio"), None)
        if stream is None:
            raise OnlineError("音频文件中没有音轨")
        resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
        buf = bytearray()
        for frame in container.decode(stream):
            for out in resampler.resample(frame):
                buf += out.to_ndarray().tobytes()
                while len(buf) >= chunk_bytes:
                    yield bytes(buf[:chunk_bytes])
                    del buf[:chunk_bytes]
        for out in resampler.resample(None):
            buf += out.to_ndarray().tobytes()
        while len(buf) >= chunk_bytes:
            yield bytes(buf[:chunk_bytes])
            del buf[:chunk_bytes]
        if buf:
            yield bytes(buf)
    finally:
        container.close()


def _collect_sentences(events: list[dict]) -> list[dict]:
    sentences = []
    seen = set()
    for ev in events:
        header = ev.get("header") or {}
        event = header.get("event", "")
        payload = ev.get("payload") or {}
        output = payload.get("output") or {}
        sent = output.get("sentence") or payload.get("sentence") or {}
        if event not in ("result-generated", "result", "sentence.end"):
            continue
        if event == "result" and sent.get("is_final") is False:
            continue
        text = (sent.get("text") or "").strip()
        if not text:
            continue
        if sent.get("end_time") in (None, ""):
            continue  # 中间结果（partial），尚无结束时间，丢弃
        key = (sent.get("sentence_id"), sent.get("begin_time"), text)
        if key in seen:
            continue
        seen.add(key)
        start = float(sent.get("begin_time", 0) or 0) / 1000.0
        end = float(sent.get("end_time", 0) or 0) / 1000.0
        words = []
        for w in sent.get("words") or []:
            word = (w.get("text") or w.get("word") or "").strip()
            if word:
                words.append(
                    {
                        "start": float(w.get("begin_time", 0) or 0) / 1000.0,
                        "end": float(w.get("end_time", 0) or 0) / 1000.0,
                        "word": word,
                    }
                )
        sentences.append({"start": start, "end": end, "text": text, "words": words})
    sentences.sort(key=lambda s: s["start"])
    return sentences


def _http_json(url: str, api_key: str, payload: dict) -> dict:
    """POST JSON 到百炼 HTTP 接口（热词表管理）。"""
    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:400]
        raise OnlineError(f"热词表接口错误({exc.code}): {body}") from exc
    except OSError as exc:
        raise OnlineError(f"热词表接口连接失败: {exc}") from exc


def create_vocabulary(api_key: str, entries: list[dict]) -> str:
    """创建 ASR 热词表，返回 vocabulary_id。"""
    body = _http_json(
        VOCAB_URL,
        api_key,
        {
            "model": "speech-biasing",
            "input": {
                "action": "create_vocabulary",
                "target_model": VOCAB_TARGET_MODEL,
                "prefix": VOCAB_PREFIX,
                "vocabulary": entries,
            },
            "parameters": {},
        },
    )
    try:
        return body["output"]["vocabulary_id"]
    except (KeyError, TypeError):
        raise OnlineError(
            f"热词表创建失败: {json.dumps(body, ensure_ascii=False)[:300]}"
        )


def delete_vocabulary(api_key: str, vocab_id: str) -> None:
    """删除热词表；清理失败静默忽略，不影响识别结果。"""
    try:
        _http_json(
            VOCAB_URL,
            api_key,
            {
                "model": "speech-biasing",
                "input": {"action": "delete_vocabulary", "vocabulary_id": vocab_id},
                "parameters": {},
            },
        )
    except Exception:
        pass


_HAN = re.compile(r"[\u4e00-\u9fff]+")
_LATIN = re.compile(r"[A-Za-z]+")


def build_hotwords(lyrics: str, limit: int = 200) -> list[dict]:
    """从歌词文本提取热词：整句歌词 + 中文词块 + 英文单词，用于在线识别增强。"""
    entries: list[tuple[str, int]] = []
    seen: set[str] = set()

    def add(text: str, weight: int):
        text = text.strip()
        if len(text) < 2 or len(text) > 40 or text in seen:
            return
        seen.add(text)
        entries.append((text, weight))

    for line in lyrics.splitlines():
        line = re.sub(r"\[[^\]]*\]", "", line).strip()  # 去掉 [ti:] 等标签
        if not line:
            continue
        add(line, 10)  # 整句歌词权重最高
        for han in _HAN.findall(line):
            if len(han) <= 4:
                add(han, 5)
            else:
                for n in (2, 3, 4):
                    for i in range(len(han) - n + 1):
                        add(han[i : i + n], 5)
        for word in _LATIN.findall(line):
            w = word.lower()
            if len(w) >= 3:
                add(w, 5)
    entries.sort(key=lambda item: (-item[1], -len(item[0])))
    return [{"text": item[0], "weight": item[1]} for item in entries[:limit]]


def _is_retryable_error(exc: OnlineError) -> bool:
    """连接中断、超时、限流等瞬时错误可自动重试；参数/热词等明确错误不重试。"""
    text = str(exc)
    low = text.lower()
    return (
        "连接中断" in text
        or "连接已关闭" in text
        or "识别超时" in text
        or "未识别到语音内容" in text
        or "task-started 超时" in text
        or "throttl" in low
        or "限流" in text
        or "quota" in low
        or "429" in text
    )


def transcribe(
    path, api_key: str = "", language: str = "", lyrics: str = ""
) -> tuple[list[dict], float]:
    """在线转写音频文件，返回 (段列表, 时长秒)，段结构与本地识别一致。

    lyrics 非空时，自动从歌词提取热词并创建临时热词表增强识别（识别后删除）。
    """
    if not api_key or not api_key.strip():
        raise OnlineError("未配置百炼 API Key，请先在「设置」中填写")
    api_key = api_key.strip()
    vocab_id = None
    if (lyrics or "").strip():
        try:
            entries = build_hotwords(lyrics)
            if entries:
                vocab_id = create_vocabulary(api_key, entries)
        except Exception:
            vocab_id = None  # 热词增强不可用时退回普通识别，不阻断任务
    chunk = int(SAMPLE_RATE * 2 * CHUNK_SECONDS)
    last_error: str | None = None
    for attempt in range(RECOGNITION_RETRY + 1):
        client = _RealtimeClient(
            api_key, (language or "").strip(), vocabulary_id=vocab_id
        )
        try:
            client.start()
            for pcm in _iter_pcm(path, chunk):
                client.send_audio(pcm)
                time.sleep(SEND_PACE_SECONDS)  # 有节奏推流，避免被服务端断开
            client.finish()
            if not client._done.wait(WAIT_AFTER_STOP) and not client.error:
                raise OnlineError("识别超时，请重试")
            if client.error:
                suffix = ""
                if client.close_code:
                    suffix = f"（服务端关闭 code={client.close_code}）"
                raise OnlineError(f"识别连接异常: {client.error}{suffix}")
            sentences = _collect_sentences(client.events)
            if not sentences:
                raise OnlineError("未识别到语音内容")
            duration = max(s["end"] for s in sentences)
            return sentences, duration
        except OnlineError as exc:
            last_error = str(exc)
            if attempt < RECOGNITION_RETRY and _is_retryable_error(exc):
                time.sleep(RETRY_BACKOFF_SECONDS[attempt])
                continue
            if attempt > 0:
                raise OnlineError(
                    f"{last_error}（已自动重试 {attempt} 次仍失败）。"
                    "这通常是百炼服务端临时限流或网络波动，请稍候再试；"
                    "若持续失败，可在百炼控制台检查配额用量或更换 API Key。"
                ) from exc
            raise
    raise OnlineError(f"识别失败：{last_error or '未知错误'}")
