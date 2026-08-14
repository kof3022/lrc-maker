"""歌词-语音自动对齐：Needleman-Wunsch 序列对齐 + 模糊匹配 + 救援/估算。

思路:
1. 把 whisper 的词级时间戳按强标点切分为"人声单元"（更细、更准）；
2. 将用户歌词行与人声单元做全局序列对齐（允许跳过行/单元）；
3. 相似度综合 文本比例 + 部分匹配 + 拼音（识别同音/近似歌词）；
4. 未匹配的行做词级"救援匹配"（在前后已匹配行限定的窗口内，容忍识别误差）；
5. 仍无法匹配的行按前后已匹配行做"估算填补"，并标记 source=interp 供核对。
"""

from __future__ import annotations

import pypinyin
from rapidfuzz import fuzz

from .lyrics import normalize

STRONG_PUNCT = set("。，；！？,!?;")
MIN_SIM = 45  # 相似度达到此值视为可靠匹配
RESCUE_OK = 60  # 救援匹配达到此值才标"已匹配"，否则标"低置信"
RESCUE_MIN = 38  # 救援匹配的最低相似度（容忍识别误差）
MATCH_BASE = 25  # 匹配得分 = 相似度 - 基准
GAP_UNIT = 16  # 跳过一个人声单元的代价
GAP_LINE = 14  # 跳过一行歌词的代价
MAX_SPAN_WORDS = 8  # 词级救援时一次最多拼接的词数
MAX_SPAN_CHARS = 60
MAX_GAP = 1.5  # 救援片段内词与词之间的最大空隙秒数（保持时间连续）

_py_cache: dict[str, str] = {}


def _pinyin(text: str) -> str:
    """转拼音（无声调，空格分隔），带缓存。"""
    if not text:
        return ""
    cached = _py_cache.get(text)
    if cached is None:
        try:
            cached = " ".join(pypinyin.lazy_pinyin(text))
        except Exception:
            cached = ""
        _py_cache[text] = cached
    return cached


def similarity(a: str, b: str) -> float:
    """综合相似度：文本比例 / 部分匹配 / 拼音。"""
    if not a or not b:
        return 0.0
    scores = [fuzz.ratio(a, b), fuzz.partial_ratio(a, b) * 0.92]
    pa = _pinyin(a)
    pb = _pinyin(b)
    if pa and pb:
        scores.append(fuzz.ratio(pa, pb))
    return max(scores)


def _is_punct_only(text: str) -> bool:
    return all(ch in STRONG_PUNCT or ch.isspace() for ch in text)


def _split_words(words: list[dict]) -> list[dict]:
    """按强标点把词序列切成更细的人声单元。"""
    units = []
    cur = []
    for w in words:
        text = (w.get("word") or "").strip()
        if not text or _is_punct_only(text):
            continue
        cur.append(w)
        if text[-1] in STRONG_PUNCT:
            units.append(_make_unit(cur))
            cur = []
    if cur:
        units.append(_make_unit(cur))
    return units


def _make_unit(words: list[dict]) -> dict:
    text = "".join(w["word"] for w in words)
    return {
        "start": words[0]["start"],
        "end": words[-1]["end"],
        "text": text.strip(),
        "words": words,
    }


def to_units(segments: list[dict]) -> list[dict]:
    """把 whisper 分段展开为细粒度人声单元。"""
    units = []
    for seg in segments:
        words = seg.get("words") or []
        if not words:
            text = (seg.get("text") or "").strip()
            if text:
                units.append(
                    {"start": seg["start"], "end": seg["end"], "text": text, "words": []}
                )
            continue
        units.extend(_split_words(words))
    return units


def _word_timeline(units: list[dict]) -> list[dict]:
    """展开全部词（无词级时间戳的单元退化为整段一个词）。"""
    words = []
    for u in units:
        ws = u.get("words") or []
        if ws:
            words.extend(ws)
        else:
            words.append({"start": u["start"], "end": u["end"], "word": u["text"]})
    return words


def _rescue(results: list[dict], units: list[dict], norm_lines: list[str]) -> None:
    """词级救援：在前后已匹配行限定的时间窗口内，为未匹配行找最接近的词片段。

    打分只用 文本比例 + 拼音比例，不用部分匹配；片段内词须时间连续。
    用时间游标保证连续的行不会共享同一片段。
    """
    words = _word_timeline(units)
    if not words:
        return
    n = len(results)

    # 每行的搜索窗口: [lo, hi) —— 上一已匹配行的起点 ~ 下一已匹配行的起点
    lo = [0.0] * n
    prev_start = 0.0
    for i in range(n):
        if results[i]["start"] is not None:
            prev_start = results[i]["start"]
        else:
            lo[i] = prev_start
    hi = [float("inf")] * n
    next_start = float("inf")
    for i in range(n - 1, -1, -1):
        if results[i]["start"] is not None:
            next_start = results[i]["start"]
        else:
            hi[i] = next_start

    word_norm = [normalize(w["word"]) for w in words]
    word_py = [_pinyin(n) for n in word_norm]
    cursor = 0  # 时间游标：下一个可用的词下标
    for i, r in enumerate(results):
        if r["start"] is not None:
            # 已匹配的行：游标推进到其起点之后，保证后续行不重复用前面的词
            while cursor < len(words) and words[cursor]["end"] <= r["start"]:
                cursor += 1
            continue
        nl = norm_lines[i]
        if not nl:
            continue
        nl_py = _pinyin(nl)
        best = None  # (score, start_idx, end_idx)
        for s in range(cursor, len(words)):
            if words[s]["start"] < lo[i]:
                continue
            if words[s]["start"] >= hi[i]:
                break  # 词按时间有序，之后的词都在窗口外
            chars = 0
            last_e = None
            for e in range(s, min(len(words), s + MAX_SPAN_WORDS)):
                if words[e]["start"] >= hi[i]:
                    break
                if not word_norm[e]:
                    continue
                if (
                    last_e is not None
                    and words[e]["start"] - words[last_e]["end"] > MAX_GAP
                ):
                    break
                last_e = e
                chars += len(word_norm[e])
                if chars > MAX_SPAN_CHARS:
                    break
                parts = [word_norm[k] for k in range(s, e + 1) if word_norm[k]]
                span_norm = "".join(parts)
                span_py = " ".join(p for p in word_py[s : e + 1] if p)
                score = fuzz.ratio(nl, span_norm)
                if nl_py and span_py:
                    score = max(score, fuzz.ratio(nl_py, span_py))
                if best is None or score > best[0]:
                    best = (score, s, e)
                if score > 95:
                    break
            if best and best[0] > 95:
                break
        if best and best[0] >= RESCUE_MIN:
            _, s, e = best
            r["start"] = round(words[s]["start"], 2)
            r["end"] = round(words[e]["end"], 2)
            r["confidence"] = round(best[0], 1)
            r["matched"] = best[0] >= RESCUE_OK
            r["source"] = "rescue"
            cursor = e + 1  # 后续行从更晚的词开始找，保持时间顺序


def _interpolate(results: list[dict], norm_lines: list[str]) -> None:
    """估算填补：在前后已匹配行之间按行长度比例分配时间。"""
    n = len(results)
    i = 0
    while i < n:
        if results[i]["start"] is not None:
            i += 1
            continue
        a = i
        while i < n and results[i]["start"] is None:
            i += 1
        b = i - 1
        prev_idx = a - 1
        prev_start = results[prev_idx]["start"] if prev_idx >= 0 else 0.0
        prev_end = (
            results[prev_idx]["end"]
            if prev_idx >= 0 and results[prev_idx]["end"] is not None
            else prev_start
        )
        count = b - a + 1
        if i < n:
            next_start = results[i]["start"]
            gap = max(0.0, next_start - prev_end)
            budget = gap if gap > 0 else 2.5 * count
            chars = [max(1, len(norm_lines[k])) for k in range(a, b + 1)]
            total = sum(chars)
            cursor = prev_end
            for k in range(a, b + 1):
                dur = budget * chars[k - a] / total
                results[k]["start"] = round(cursor, 2)
                results[k]["end"] = round(cursor + dur, 2)
                results[k]["confidence"] = 0
                results[k]["matched"] = False
                results[k]["source"] = "interp"
                cursor += dur
        else:
            cursor = prev_end
            for k in range(a, b + 1):
                dur = 1.2 + 0.25 * len(norm_lines[k])
                results[k]["start"] = round(cursor, 2)
                results[k]["end"] = round(cursor + dur, 2)
                results[k]["confidence"] = 0
                results[k]["matched"] = False
                results[k]["source"] = "interp"
                cursor += dur


def align(lyric_lines: list[str], segments: list[dict]) -> list[dict]:
    """把歌词行与识别段落对齐，返回每行的结果。

    结果项: {text, start, end, confidence, matched, source}
    source: match（可靠匹配）/ rescue（低置信匹配）/ interp（估算填补）
    start 为 None 表示该行未匹配到语音（也无从估算）。
    """
    units = to_units(segments)
    norm_lines = [normalize(line) for line in lyric_lines]
    norm_units = [normalize(u["text"]) for u in units]
    n, m = len(norm_lines), len(norm_units)

    if n == 0:
        return []
    if m == 0:
        return [
            {
                "text": t,
                "start": None,
                "end": None,
                "confidence": 0,
                "matched": False,
                "source": "none",
            }
            for t in lyric_lines
        ]

    # 相似度矩阵
    sim = [[0.0] * m for _ in range(n)]
    for i in range(n):
        if not norm_lines[i]:
            continue
        for j in range(m):
            if norm_units[j]:
                sim[i][j] = similarity(norm_lines[i], norm_units[j])

    # DP 全局对齐
    NEG = float("-inf")
    dp = [[NEG] * (m + 1) for _ in range(n + 1)]
    back = [[0] * (m + 1) for _ in range(n + 1)]
    dp[0][0] = 0.0
    for j in range(1, m + 1):
        dp[0][j] = dp[0][j - 1] - GAP_UNIT
        back[0][j] = 1
    for i in range(1, n + 1):
        dp[i][0] = dp[i - 1][0] - GAP_LINE
        back[i][0] = 2
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            best = dp[i - 1][j - 1] + sim[i - 1][j - 1] - MATCH_BASE
            b = 0
            s = dp[i][j - 1] - GAP_UNIT
            if s > best:
                best, b = s, 1
            s = dp[i - 1][j] - GAP_LINE
            if s > best:
                best, b = s, 2
            dp[i][j] = best
            back[i][j] = b

    # 回溯得到匹配对 (行, 单元)
    pairs = []
    i, j = n, m
    while i > 0 or j > 0:
        b = back[i][j]
        if b == 0:
            pairs.append((i - 1, j - 1))
            i -= 1
            j -= 1
        elif b == 1:
            j -= 1
        else:
            i -= 1
    pairs.reverse()

    by_line: dict[int, tuple[int, float]] = {}
    for li, uj in pairs:
        by_line[li] = (uj, sim[li][uj])

    results = []
    for li, text in enumerate(lyric_lines):
        pair = by_line.get(li)
        if pair is None:
            results.append(
                {
                    "text": text,
                    "start": None,
                    "end": None,
                    "confidence": 0,
                    "matched": False,
                    "source": "none",
                }
            )
            continue
        uj, conf = pair
        unit = units[uj]
        results.append(
            {
                "text": text,
                "start": round(unit["start"], 2),
                "end": round(unit["end"], 2),
                "confidence": round(conf, 1),
                "matched": conf >= MIN_SIM,
                "source": "match",
            }
        )

    _rescue(results, units, norm_lines)
    _interpolate(results, norm_lines)
    return results