#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
audio_align.py — 把「整段音频 + 文字稿」对齐成逐句时间轴，供精听/听写使用。

典型用法（Windows / macOS / Linux 都一样）：

    # 1) 装依赖（建议 Python 3.10–3.12）
    python -m venv .venv
    .venv\\Scripts\\activate          # macOS/Linux: source .venv/bin/activate
    pip install -r requirements.txt

    # 2) 国内下载 Whisper 模型慢的话（可选）
    set HF_ENDPOINT=https://hf-mirror.com      # PowerShell: $env:HF_ENDPOINT="https://hf-mirror.com"
    # 脚本默认禁用 Xet（HF_HUB_DISABLE_XET=1），否则部分网络会卡在 0 字节

    # 3) 对齐
    python audio_align.py ^
      --audio  ep.mp3 ^
      --transcript ep.txt ^
      --out out ^
      --title "Episode title" ^
      --model small.en

输出：
    out/episode.json   每句 text / start / end / confidence
    out/preview.html   可点的校对页（播放每句、±0.1s 微调、导出 JSON）
    out/asr_words.json Whisper 原始词级时间戳（排查用）

说明：
- BBC Learning English 的文字稿不是逐字稿（页面自己写着 "not a word-for-word
  transcript"），所以只做「句级」对齐，不做词级卡拉 OK。
- 对齐 = Whisper 词级时间戳 + 文稿词序列模糊匹配。没有匹配上的句子用前后句
  插值，并标 needs_review。
- 音频只读取本地文件，不上传；浏览器校对页也是本地 file:// 打开。
"""

from __future__ import annotations

import argparse
import html
import json
import math
import os
import re
import sys
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import NoReturn
from urllib.parse import quote

# faster-whisper / av 是可选依赖，装在运行脚本的 venv 里；IDE 解析不到是正常的。
# pyright: reportMissingImports=false


# --------------------------------------------------------------------------- #
# 基础
# --------------------------------------------------------------------------- #

def log(msg: str) -> None:
    print(f"[audio-align] {msg}", file=sys.stderr, flush=True)


def die(msg: str) -> NoReturn:
    print(f"[audio-align] ERROR: {msg}", file=sys.stderr, flush=True)
    raise SystemExit(1)


@dataclass
class Seed:
    speaker: str
    text: str


@dataclass
class Word:
    word: str
    start: float
    end: float


# 常见缩写：句点不能断句
ABBREV = {
    "mr", "mrs", "ms", "dr", "prof", "st", "jr", "sr", "vs", "etc",
    "e.g", "i.e", "u.s", "u.k", "no", "fig", "approx", "dept", "est",
    "min", "max", "a.m", "p.m", "inc", "ltd", "co", "gen", "gov", "sen",
    "rep", "capt", "lt", "col", "maj", "sgt", "rev", "hon",
}

# 数字统一成阿拉伯数字，避免 "thirty" vs "30" 对不上
WORD_NUM = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
    "ten": "10", "eleven": "11", "twelve": "12", "thirteen": "13",
    "fourteen": "14", "fifteen": "15", "sixteen": "16", "seventeen": "17",
    "eighteen": "18", "nineteen": "19", "twenty": "20", "thirty": "30",
    "forty": "40", "fifty": "50", "sixty": "60", "seventy": "70",
    "eighty": "80", "ninety": "90", "hundred": "100", "thousand": "1000",
    "million": "1000000",
}

# 常见缩写词展开，提升 "don't" vs "do not" 的匹配率
CONTRACTIONS = {
    "i'm": ["i", "am"], "i've": ["i", "have"], "i'll": ["i", "will"],
    "i'd": ["i", "would"], "you're": ["you", "are"], "you've": ["you", "have"],
    "you'll": ["you", "will"], "you'd": ["you", "would"],
    "he's": ["he", "is"], "she's": ["she", "is"], "it's": ["it", "is"],
    "we're": ["we", "are"], "we've": ["we", "have"], "we'll": ["we", "will"],
    "they're": ["they", "are"], "they've": ["they", "have"],
    "that's": ["that", "is"], "there's": ["there", "is"],
    "here's": ["here", "is"], "what's": ["what", "is"],
    "who's": ["who", "is"], "let's": ["let", "us"],
    "don't": ["do", "not"], "doesn't": ["does", "not"],
    "didn't": ["did", "not"], "isn't": ["is", "not"],
    "aren't": ["are", "not"], "wasn't": ["was", "not"],
    "weren't": ["were", "not"], "haven't": ["have", "not"],
    "hasn't": ["has", "not"], "hadn't": ["had", "not"],
    "can't": ["can", "not"], "cannot": ["can", "not"],
    "couldn't": ["could", "not"], "won't": ["will", "not"],
    "wouldn't": ["would", "not"], "shouldn't": ["should", "not"],
}

# 英式拼写 / ASR 常见写法归一
SYNONYMS = {
    "okay": "ok",
    "tonnes": "tons", "tonne": "ton",
    "programme": "program", "programmes": "programs",
    "jewellery": "jewelry",
    "colour": "color", "colours": "colors", "coloured": "colored",
    "favourite": "favorite",
    "realise": "realize", "realised": "realized",
    "organisation": "organization",
    "centre": "center", "theatre": "theater",
    "defence": "defense",
    "travelling": "traveling",
    "u.s": "us",
}


# --------------------------------------------------------------------------- #
# 文稿解析 / 分句
# --------------------------------------------------------------------------- #

BOLD_SPEAKER = re.compile(r"^\*\*(.+?)\*\*\s*(.*)$")
COLON_SPEAKER = re.compile(r"^([A-Z][A-Za-z .'\-]{0,24}):\s+(.+)$")
NOISE_LINE = re.compile(
    r"^(note\s*:|this is not a word-for-word|transcript\b|vocabulary\b|"
    r"introduction\b|download\b|worksheet\b|quiz\b|this week's question\b|"
    r"bbc learning english\b|6 minute english\s*$)",
    re.I,
)
FOOTER_LINE = re.compile(
    r"(©?\s*british broadcasting corporation|"
    r"\bpage \d+ of \d+\b|"
    r"^bbclearningenglish\.com\s*$)",
    re.I,
)


def split_sentences(text: str) -> list[str]:
    """按 . ! ? 切句，跳过小数点和常见缩写。"""
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []

    out: list[str] = []
    start = 0
    i = 0
    n = len(text)

    while i < n:
        c = text[i]
        if c not in ".!?":
            i += 1
            continue

        # 小数点：3.14 / 6.30
        if c == "." and 0 < i < n - 1 and text[i - 1].isdigit() and text[i + 1].isdigit():
            i += 1
            continue

        # 缩写：Mr. / U.S. / e.g.
        j = i - 1
        while j >= 0 and (text[j].isalnum() or text[j] in ".'"):
            j -= 1
        word = text[j + 1:i].lower().strip(".")
        if c == "." and word in ABBREV:
            i += 1
            continue

        # 结尾引号/括号跟着句子走
        k = i + 1
        while k < n and text[k] in "\"')]}”’":
            k += 1

        if k >= n or text[k].isspace():
            sent = text[start:k].strip()
            if sent:
                out.append(sent)
            start = k
            i = k
            continue

        i += 1

    tail = text[start:].strip()
    if tail:
        out.append(tail)
    return out


def _looks_like_speaker_line(s: str) -> bool:
    """裸名字行：Neil / Georgie / Neil Armstrong（无标点、短）。"""
    if not s or s.startswith("*") or ":" in s or "?" in s or "." in s or "!" in s:
        return False
    if not re.fullmatch(r"[A-Z][A-Za-z'\-]*(?: [A-Z][A-Za-z'\-]*)?", s):
        return False
    return len(s) <= 24


def _merge_ellipsis_fragments(seeds: list[Seed]) -> list[Seed]:
    """把 "It's..." 这种 ≤3 词的省略号碎片并进下一句（同说话人）。"""
    out: list[Seed] = []
    i = 0
    while i < len(seeds):
        cur = seeds[i]
        nxt = seeds[i + 1] if i + 1 < len(seeds) else None
        words = len(re.findall(r"[A-Za-z0-9']+", cur.text))
        if (nxt is not None and nxt.speaker == cur.speaker
                and cur.text.rstrip().endswith("...") and words <= 3):
            out.append(Seed(cur.speaker, f"{cur.text} {nxt.text}"))
            i += 2
        else:
            out.append(cur)
            i += 1
    return out


def parse_transcript(path: Path) -> list[Seed]:
    """解析 BBC 风格文稿：**Neil**、Neil:、或单独一行的 Neil。"""
    raw = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()

    # BBC 页面在 TRANSCRIPT 之前还有标题、问题、词汇表；只从标记之后开始解析
    # 取最后一次：页面顶部可能还有 "Transcript" 导航链接
    start_at = 0
    for i, line in enumerate(raw):
        label = line.strip().strip("*").strip().rstrip(":：").strip().lower()
        if label == "transcript":
            start_at = i + 1
    if start_at:
        raw = raw[start_at:]

    seeds: list[Seed] = []
    speaker = ""
    speaker_seen = False
    buf: list[str] = []

    def flush() -> None:
        nonlocal buf
        text = " ".join(x.strip() for x in buf if x.strip()).strip()
        buf = []
        if not text:
            return
        # 纯音效行：(music) [MUSIC] 之类
        if re.fullmatch(r"[\[(].*?[\])]", text):
            return
        for sent in split_sentences(text):
            seeds.append(Seed(speaker, sent))

    def set_speaker(label: str) -> None:
        nonlocal speaker, speaker_seen
        if not speaker_seen:
            # 第一个说话人之前是标题/说明，不是正文
            buf.clear()
        else:
            flush()
        speaker = label
        speaker_seen = True

    for idx, line in enumerate(raw):
        s = line.strip()
        prev = ""
        for j in range(idx - 1, -1, -1):
            x = raw[j].strip()
            if not x or FOOTER_LINE.search(x):
                continue
            prev = x
            break
        prev_boundary = (not prev) or prev[-1] in ".!?" or bool(
            NOISE_LINE.match(prev.strip("* ").strip())
        )
        if not s:
            if speaker_seen:
                flush()
            else:
                buf.clear()
            continue

        # PDF 页脚：bbclearningenglish.com / ©British Broadcasting... / Page 1 of 5
        if FOOTER_LINE.search(s):
            continue

        # PDF / 网页表格的页脚：|6 Minute English|©BBC...|
        if s.startswith("|"):
            continue

        # Markdown 标题：PDF 提取常见是 "### Georgie" / "### VOCABULARY"
        if s.startswith("#"):
            label = re.sub(r"^#+\s*", "", s).strip().strip("*").strip()
            low = label.lower()
            if low.startswith("vocabulary"):
                flush()
                break
            if low in {"transcript", "bbc learning english"} or low.startswith(
                "this is not a word-for-word"
            ):
                if speaker_seen:
                    flush()
                else:
                    buf.clear()
                continue
            if _looks_like_speaker_line(label):
                set_speaker(label)
            elif speaker_seen:
                flush()
            else:
                buf.clear()
            continue

        # 行首 [00:12] / [01:02:03] 时间码
        s = re.sub(r"^\[\d{1,2}:\d{2}(?::\d{2})?\]\s*", "", s)
        if not s:
            continue

        # 从网页复制时可能把 **Georgie** 拆成两行：先出现 **Georgie
        # 只认单个短名字，避免把 "** Hello, this is..." 误当说话人
        m = re.match(r"^\*\*([A-Za-z][A-Za-z.'-]{0,20})$", s)
        if m:
            set_speaker(m.group(1).strip())
            continue

        # 正文到此结束，后面是词汇表（必须在 NOISE 之前，否则 VOCABULARY 只被跳过不终止）
        if s.strip("* ").strip().rstrip(":：").lower() in {"vocabulary", "vocab"}:
            flush()
            break

        if NOISE_LINE.match(s):
            if speaker_seen:
                flush()
            else:
                buf.clear()
            continue

        m = BOLD_SPEAKER.match(s)
        if m:
            label = m.group(1).strip().strip("*").strip()
            rest = m.group(2).strip()
            if label.lower() in {"transcript", "vocabulary", "introduction", "note"}:
                continue
            # **Alchemy** is ... 这种句首粗体词不是说话人
            if rest and not (rest[0].isupper() or rest[0].isdigit() or rest[0] in "\"'“("):
                buf.append(s.replace("**", "").strip())
                continue
            set_speaker(label)
            if rest:
                buf.append(rest.replace("**", "").strip())
            continue

        # 裸名字行：上一行是句末/空行/标题，且下一行是文本（不是另一个名字）
        if prev_boundary and _looks_like_speaker_line(s):
            nxt = ""
            for x in raw[idx + 1:]:
                if x.strip():
                    nxt = x.strip()
                    break
            if nxt and not _looks_like_speaker_line(nxt):
                set_speaker(s)
                continue

        m = COLON_SPEAKER.match(s)
        if m and m.group(1).lower() not in {"note", "transcript", "vocabulary"}:
            set_speaker(m.group(1).strip())
            buf.append(m.group(2).strip().replace("**", ""))
            continue

        # ** Hello...（上一行是 **Georgie 的情况）
        if s.startswith("**"):
            s = s[2:].strip()
            if not s:
                continue

        buf.append(s.replace("**", "").strip())

    flush()
    return _merge_ellipsis_fragments(seeds)


# --------------------------------------------------------------------------- #
# 词归一化 / 对齐
# --------------------------------------------------------------------------- #

def expand_token(word: str) -> list[str]:
    """一个原始词 → 若干可比较的归一化 token。"""
    w = unicodedata.normalize("NFKC", word).lower()
    w = (w.replace("’", "'").replace("‘", "'")
           .replace("“", '"').replace("”", '"'))
    w = w.strip()
    if not w:
        return []

    w = w.replace("—", "-").replace("–", "-")
    # 千分位：50,000 → 50 + 000（ASR 常把它切成两个词）
    w = re.sub(r"(?<=\d),(?=\d)", " ", w)
    out: list[str] = []

    for part in re.split(r"[\s\-/]+", w):
        p = re.sub(r"^[^a-z0-9']+|[^a-z0-9']+$", "", part)
        if not p:
            continue
        if p in CONTRACTIONS:
            out.extend(CONTRACTIONS[p])
        elif p in WORD_NUM:
            out.append(WORD_NUM[p])
        else:
            # 域名/缩写：bbclearningenglish.com → bbclearningenglish + com
            if (p not in {"u.s", "u.k", "e.g", "i.e", "a.m", "p.m"}
                    and "." in p and any(ch.isalpha() for ch in p)):
                bits = [b for b in p.split(".") if b]
                if len(bits) >= 2:
                    out.extend(bits)
                    continue
            out.append(SYNONYMS.get(p, p))
    return out


def build_transcript_tokens(sentences: list[dict]) -> list[str]:
    tokens: list[str] = []
    for s in sentences:
        s["start_tok"] = len(tokens)
        for raw in re.findall(r"\S+", s["text"]):
            tokens.extend(expand_token(raw))
        s["end_tok"] = len(tokens)
    return tokens


def _pick_cluster(pairs: list[tuple[int, int, int]]) -> list[tuple[int, int, int]]:
    """把一句里的匹配按 ASR 词序号聚簇，避免重复短语把句首匹配到上一句。"""
    if not pairs:
        return []
    clusters: list[list[tuple[int, int, int]]] = [[pairs[0]]]
    for p in pairs[1:]:
        if p[2] - clusters[-1][-1][2] >= 4:
            clusters.append([p])
        else:
            clusters[-1].append(p)
    # 词数多的簇优先；一样多取靠后的（重复短语通常后一次才是本句）
    return max(clusters, key=lambda c: (len(c), c[-1][2]))


def _recover_edges(
    sentence: dict,
    chosen: list[tuple[int, int, int]],
    asr_tokens: list[str],
    transcript_tokens: list[str],
) -> list[int]:
    """簇没覆盖到句首/句尾时，若相邻 ASR 词正好能一一对上，就补回来。"""
    if not chosen:
        return []
    extra: list[int] = []

    first_ti, first_ai, _ = chosen[0]
    lead = first_ti - sentence["start_tok"]
    if 0 < lead <= first_ai:
        ok = True
        for k in range(lead):
            if transcript_tokens[sentence["start_tok"] + k] != asr_tokens[first_ai - lead + k]:
                ok = False
                break
        if ok:
            extra.extend(range(first_ai - lead, first_ai))

    last_ti, last_ai, _ = chosen[-1]
    trail = sentence["end_tok"] - 1 - last_ti
    if trail > 0 and last_ai + trail < len(asr_tokens):
        ok = True
        for k in range(1, trail + 1):
            if transcript_tokens[last_ti + k] != asr_tokens[last_ai + k]:
                ok = False
                break
        if ok:
            extra.extend(range(last_ai + 1, last_ai + trail + 1))

    return extra


def align(
    sentences: list[dict],
    transcript_tokens: list[str],
    words: list[Word],
    duration: float,
    pad_start: float,
    pad_end: float,
    min_confidence: float,
) -> dict:
    asr_tokens: list[str] = []
    asr_owner: list[int] = []
    for wi, w in enumerate(words):
        for t in expand_token(w.word):
            asr_tokens.append(t)
            asr_owner.append(wi)

    if not asr_tokens:
        die("Whisper 没有返回任何词。音频可能是静音，或模型/语言不对。")

    matcher = SequenceMatcher(None, asr_tokens, transcript_tokens, autojunk=False)
    token_match: dict[int, int] = {}
    for a0, b0, size in matcher.get_matching_blocks():
        for k in range(size):
            token_match[b0 + k] = a0 + k

    matched_tokens = 0
    for s in sentences:
        hits = [ti for ti in range(s["start_tok"], s["end_tok"]) if ti in token_match]
        pairs = [(ti, token_match[ti], asr_owner[token_match[ti]]) for ti in hits]
        chosen = _pick_cluster(pairs)
        recovered = _recover_edges(s, chosen, asr_tokens, transcript_tokens)

        total = max(1, s["end_tok"] - s["start_tok"])
        matched_here = len(chosen) + len(recovered)
        matched_tokens += matched_here
        ratio = matched_here / total
        s["confidence"] = round(ratio, 3)
        s["needs_review"] = ratio < min_confidence

        ai_list = [ai for _, ai, _ in chosen] + recovered
        owners = sorted({asr_owner[ai] for ai in ai_list})
        if owners:
            s["start"] = min(words[i].start for i in owners)
            s["end"] = max(words[i].end for i in owners)
        else:
            s["start"] = None
            s["end"] = None

    # ---- 没匹配上的句子：在前后已知句之间按字符数插值 ----
    known = [i for i, s in enumerate(sentences) if s["start"] is not None]
    if not known:
        log("warning: 文稿和 ASR 一个词都没对上，退化为按字数均分整段音频")
        total_chars = sum(len(s["text"]) for s in sentences) or 1
        t = 0.0
        for s in sentences:
            d = max(0.4, duration * len(s["text"]) / total_chars)
            s["start"], s["end"] = t, min(duration, t + d)
            s["confidence"] = 0.0
            s["needs_review"] = True
            t += d
    else:
        i = 0
        while i < len(sentences):
            if sentences[i]["start"] is not None:
                i += 1
                continue
            j = i
            while j < len(sentences) and sentences[j]["start"] is None:
                j += 1
            prev_end = sentences[i - 1]["end"] if i > 0 else 0.0
            next_start = sentences[j]["start"] if j < len(sentences) else duration
            gap = max(0.3, next_start - prev_end)
            chars = sum(len(sentences[k]["text"]) for k in range(i, j)) or 1
            t = prev_end
            for k in range(i, j):
                d = gap * len(sentences[k]["text"]) / chars
                sentences[k]["start"] = t
                sentences[k]["end"] = t + d
                t += d
            i = j

    if not duration or duration <= 0:
        duration = max([s["end"] for s in sentences if s["end"]] or [0.0]) + 2.0

    # ---- 前后留气口，但不能吃掉相邻句的词 ----
    # 用「未加 padding 的原始词边界」做上限/下限：先 padding 再和邻居的
    # padded 边界比较，会把短句的最后一个词直接切掉（如 "Is it:" 只剩 "Is"）。
    raw = [(float(s["start"]), float(s["end"])) for s in sentences]
    for i, s in enumerate(sentences):
        start = max(0.0, raw[i][0] - pad_start)
        end = min(duration, raw[i][1] + pad_end)
        if i > 0:
            start = max(start, raw[i - 1][1])
        if i < len(sentences) - 1:
            end = min(end, raw[i + 1][0])
        if end <= start:
            end = start + 0.15
        s["start"], s["end"] = start, end

    # 兜底：极端插值导致的交叉
    for i in range(len(sentences) - 1):
        if sentences[i]["end"] > sentences[i + 1]["start"]:
            mid = (sentences[i]["end"] + sentences[i + 1]["start"]) / 2
            sentences[i]["end"] = max(sentences[i]["start"] + 0.1, mid)
            sentences[i + 1]["start"] = max(mid, sentences[i]["end"] + 0.01)

    for s in sentences:
        s["start"] = round(max(0.0, s["start"]), 3)
        s["end"] = round(min(duration, max(s["start"] + 0.15, s["end"])), 3)

    confs = [s["confidence"] for s in sentences]
    return {
        "sentences": len(sentences),
        "low_confidence": sum(1 for s in sentences if s["needs_review"]),
        "mean_confidence": round(sum(confs) / len(confs), 3) if confs else 0.0,
        "matched_tokens": matched_tokens,
        "transcript_tokens": len(transcript_tokens),
        "asr_tokens": len(asr_tokens),
    }


# --------------------------------------------------------------------------- #
# ASR
# --------------------------------------------------------------------------- #

def probe_duration(path: Path) -> float:
    try:
        import av  # faster-whisper 自带
        with av.open(str(path)) as container:
            if container.duration:
                return float(container.duration / av.time_base)
    except Exception as exc:  # noqa: BLE001
        log(f"warning: 读不到音频时长（{exc}）")
    return 0.0


def transcribe(
    audio: Path,
    model_name: str,
    device: str,
    compute_type: str,
    language: str,
    model_dir: Path,
    beam_size: int,
) -> tuple[list[Word], float]:
    try:
        import av
        if int(str(av.__version__).split(".")[0]) >= 19:
            die("PyAV 19 移除了 metadata_errors，和 faster-whisper 1.2.x 不兼容；"
                "请执行: pip install \"av<19\"")
    except ImportError:
        pass

    # 部分网络在 Xet 协议上会卡住 0 字节；HTTP 下载更稳
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

    try:
        import importlib
        fw = importlib.import_module("faster_whisper")
        WhisperModel = fw.WhisperModel
    except ImportError:
        die("缺少 faster-whisper。先运行: pip install -r requirements.txt")

    log(f"加载模型 {model_name}（{device}/{compute_type}）…")
    kwargs = {}
    if model_dir:
        model_dir.mkdir(parents=True, exist_ok=True)
        kwargs["download_root"] = str(model_dir)
    try:
        model = WhisperModel(model_name, device=device, compute_type=compute_type, **kwargs)
    except Exception as exc:  # noqa: BLE001
        die(f"加载模型失败：{exc}\n"
            "提示：国内网络先设置 HF_ENDPOINT=https://hf-mirror.com；"
            "或手动下载模型目录后用 --model <本地目录>")

    log("开始转写…")
    segments, info = model.transcribe(
        str(audio),
        language=language,
        beam_size=beam_size,
        word_timestamps=True,
        vad_filter=True,
        condition_on_previous_text=False,
    )

    words: list[Word] = []
    n = 0
    for seg in segments:
        n += 1
        if seg.words:
            for w in seg.words:
                text = (w.word or "").strip()
                if text:
                    words.append(Word(text, float(w.start), float(w.end)))
        if n % 20 == 0:
            log(f"  {n} 段 / {len(words)} 词 / 到 {seg.end:.1f}s")
    log(f"转写完成：{len(words)} 个词")

    duration = float(getattr(info, "duration", 0.0) or 0.0)
    if duration <= 0:
        duration = probe_duration(audio)
    return words, duration


def load_asr_json(path: Path) -> list[Word]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    items: list = []
    if isinstance(raw, dict) and "words" in raw:
        items = raw["words"]
    elif isinstance(raw, dict) and "segments" in raw:
        for seg in raw["segments"]:
            items.extend(seg.get("words", []))
    elif isinstance(raw, list):
        items = raw
    else:
        die("--asr-json 需要 {\"words\": [...]}、{\"segments\": [...]} 或数组")

    words: list[Word] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        text = it.get("word") or it.get("text") or ""
        st, en = it.get("start"), it.get("end")
        if text and st is not None and en is not None:
            words.append(Word(str(text), float(st), float(en)))
    if not words:
        die("--asr-json 里没有可用的 word/start/end")
    return words


# --------------------------------------------------------------------------- #
# 校对页
# --------------------------------------------------------------------------- #

PREVIEW_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>对齐校对 · __TITLE__</title>
<style>
  :root{
    --paper:#F6F1E6; --surface:#FFFCF5; --low:#F8F2E6; --ink:#1F241F;
    --muted:#5F5749; --line:#E0D3BC; --green:#2F5D50; --green-soft:#DCE8E2;
    --amber:#C98A3E; --red:#B3261E; --red-soft:#F9E6E3; --mono:ui-monospace,SFMono-Regular,Consolas,monospace;
  }
  *{box-sizing:border-box}
  body{margin:0;background:#EFE8D8;color:var(--ink);
    font-family:-apple-system,"Segoe UI","Noto Sans SC","Microsoft YaHei",sans-serif;}
  .wrap{max-width:980px;margin:0 auto;padding:22px 18px 60px}
  header{background:var(--paper);border:1px solid var(--line);border-radius:16px;padding:18px 20px}
  .kicker{font-size:10px;letter-spacing:1.6px;color:var(--amber);font-weight:700}
  h1{font-family:Georgia,"Noto Serif SC",serif;font-size:24px;margin:6px 0 4px;font-weight:600}
  .sub{font-size:11.5px;color:var(--muted);line-height:1.6}
  .sub code{font-family:var(--mono);font-size:11px}
  .bar{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin-top:12px}
  .bar label{font-size:11.5px;color:var(--muted);display:flex;align-items:center;gap:6px}
  .bar input[type=number]{width:64px;padding:5px 6px;border:1px solid var(--line);
    border-radius:7px;background:var(--surface);font-family:var(--mono);font-size:12px}
  button{border:1px solid var(--line);background:var(--surface);color:var(--ink);
    border-radius:8px;padding:5px 10px;font-size:11.5px;cursor:pointer;font-family:inherit}
  button:hover{border-color:var(--green);color:var(--green)}
  button.primary{background:var(--green);border-color:var(--green);color:#fff;font-weight:600}
  button.primary:hover{background:#254b40;color:#fff}
  .player{position:sticky;top:0;z-index:5;margin-top:14px;background:var(--surface);
    border:1px solid var(--line);border-radius:14px;padding:10px 14px;
    display:flex;align-items:center;gap:12px;box-shadow:0 4px 14px rgba(60,45,20,.08)}
  .player audio{display:none}
  #playBtn{width:42px;height:42px;border-radius:50%;background:var(--green);
    border-color:var(--green);color:#fff;font-size:15px;flex:0 0 42px}
  .clock{font-family:var(--mono);font-size:12px;color:var(--muted);flex:0 0 auto}
  .now{flex:1;min-width:0;font-size:11.5px;color:var(--muted);
    white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  #speed{padding:4px 6px;border:1px solid var(--line);border-radius:7px;
    background:var(--surface);font-size:11px}
  #list{margin-top:14px;display:flex;flex-direction:column;gap:8px}
  .row{background:var(--surface);border:1px solid var(--line);border-radius:12px;
    padding:10px 13px;display:grid;grid-template-columns:52px 1fr auto;gap:12px;
    cursor:pointer;transition:background .12s,border-color .12s}
  .row:hover{border-color:#C9B99C}
  .row.sel{border-color:var(--green);background:#FBFDFB}
  .row.playing{background:var(--green-soft);border-color:var(--green)}
  .row.low{border-left:4px solid var(--amber)}
  .row.hide{display:none}
  .idx{padding-top:2px}
  .idx b{font-family:var(--mono);font-size:12px;color:var(--muted);display:block}
  .idx span{display:block;font-size:9px;color:var(--amber);margin-top:2px;
    white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .body p{margin:0;font-family:Georgia,"Times New Roman",serif;font-size:15px;line-height:1.6}
  .meta{text-align:right;font-family:var(--mono);font-size:10.5px;color:var(--muted);
    display:flex;flex-direction:column;align-items:flex-end;gap:5px;white-space:nowrap}
  .conf{font-size:9px;padding:1px 6px;border-radius:99px;font-family:-apple-system,sans-serif}
  .conf.ok{background:#DCE8E2;color:#17362D}
  .conf.mid{background:#F3E3C8;color:#5A3E1E}
  .conf.bad{background:var(--red-soft);color:var(--red)}
  .edit{display:none;gap:6px;flex-wrap:wrap;margin-top:8px}
  .row.sel .edit{display:flex}
  .edit button{padding:3px 7px;font-size:10px;border-radius:6px}
  footer{margin-top:22px;font-size:10.5px;color:var(--muted);line-height:1.7}
  @media (max-width:640px){
    .row{grid-template-columns:38px 1fr}
    .meta{grid-column:2;flex-direction:row;justify-content:flex-start;gap:10px;text-align:left}
    .now{display:none}
  }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="kicker">AUDIO ALIGN · 逐句校对</div>
    <h1>__TITLE__</h1>
    <div class="sub"><span id="stats"></span> · 音频 <code>__AUDIO__</code></div>
    <div class="bar">
      <label>整体偏移 <input id="offset" type="number" step="0.1" value="0"> 秒
        <button id="applyOffset">应用</button></label>
      <label><input type="checkbox" id="lowOnly"> 只看低置信度</label>
      <button id="export" class="primary">导出 episode.json</button>
    </div>
  </header>

  <div class="player">
    <audio id="audio" src="__AUDIO__" preload="metadata"></audio>
    <button id="playBtn" title="空格：播放/暂停">▶</button>
    <div class="clock"><span id="cur">0:00.0</span> / <span id="dur">0:00.0</span></div>
    <div class="now" id="now">点句子播放；空格播放/暂停，↑↓ 切换句子</div>
    <select id="speed" title="播放速度">
      <option value="0.75">0.75×</option>
      <option value="1" selected>1.0×</option>
      <option value="1.25">1.25×</option>
      <option value="1.5">1.5×</option>
    </select>
  </div>

  <div id="list"></div>

  <footer>
    点句子选中并播放；选中后可微调起点/终点，或用「重打点」把起点设成当前播放位置。
    改完点「导出 episode.json」，用导出的文件覆盖 out/episode.json 再进 App。<br>
    低置信度 = 文稿里匹配上的词少于 60%，通常是 ASR 误差、说话人重叠或文稿漏句。
  </footer>
</div>

<script>
const DATA = __DATA__;
const $ = (s) => document.querySelector(s);
const audio = $('#audio');
let data = DATA;
let selected = -1;
let stopAt = null;
let wantPlay = false;

function fmt(t){
  if (!isFinite(t) || t < 0) t = 0;
  const m = Math.floor(t / 60);
  const s = t - m * 60;
  return m + ':' + s.toFixed(2).padStart(5, '0');
}
function esc(s){
  return String(s == null ? '' : s)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;');
}
function confClass(c){ return c >= 0.8 ? 'ok' : c >= 0.6 ? 'mid' : 'bad'; }

function stats(){
  const n = data.sentences.length;
  const low = data.sentences.filter(s => s.needs_review).length;
  const mean = n ? data.sentences.reduce((a,s) => a + (s.confidence || 0), 0) / n : 0;
  return n + ' 句 · 平均置信度 ' + (mean * 100).toFixed(0) + '% · 待校对 ' + low + ' 句';
}

function render(){
  $('#stats').textContent = stats();
  const lowOnly = $('#lowOnly').checked;
  $('#list').innerHTML = data.sentences.map((s, i) => {
    const hide = lowOnly && !s.needs_review;
    const cls = ['row'];
    if (s.needs_review) cls.push('low');
    if (i === selected) cls.push('sel');
    if (hide) cls.push('hide');
    return `<div class="${cls.join(' ')}" data-i="${i}">
      <div class="idx"><b>${i + 1}</b><span>${esc(s.speaker || '')}</span></div>
      <div class="body">
        <p>${esc(s.text)}</p>
        <div class="edit">
          <button data-act="play" data-i="${i}">▶ 播</button>
          <button data-act="start-" data-i="${i}">起点 −0.1</button>
          <button data-act="start+" data-i="${i}">起点 +0.1</button>
          <button data-act="end-" data-i="${i}">终点 −0.1</button>
          <button data-act="end+" data-i="${i}">终点 +0.1</button>
          <button data-act="retap" data-i="${i}">重打点</button>
          <button data-act="delete" data-i="${i}">删除本句</button>
        </div>
      </div>
      <div class="meta">
        <span>${fmt(s.start)} – ${fmt(s.end)}</span>
        <span class="conf ${confClass(s.confidence || 0)}">${Math.round((s.confidence || 0) * 100)}%</span>
      </div>
    </div>`;
  }).join('');
}

function playAt(i){
  const s = data.sentences[i];
  if (!s) return;
  selected = i;
  stopAt = s.end;
  wantPlay = true;
  const go = () => {
    audio.currentTime = Math.max(0, s.start);
    audio.play().then(() => watchClip()).catch(err => {
      $('#now').textContent = '播放失败：' + err.message;
    });
  };
  if (audio.readyState >= 1) go();
  else audio.addEventListener('loadedmetadata', go, { once: true });
  $('#now').textContent = `第 ${i + 1} 句 · ${s.speaker || ''} ${fmt(s.start)}–${fmt(s.end)}`;
  render();
}

function watchClip(){
  if (audio.paused || stopAt == null) return;
  if (audio.currentTime >= stopAt - 0.01) {
    audio.pause();
    stopAt = null;
    return;
  }
  requestAnimationFrame(watchClip);
}

function nudge(i, field, delta){
  const s = data.sentences[i];
  if (!s) return;
  s[field] = Math.max(0, (s[field] || 0) + delta);
  if (s.end <= s.start + 0.15) s.end = s.start + 0.15;
  s.edited = true;
  if (selected === i) {
    if (field === 'end') stopAt = s.end;
    $('#now').textContent = `第 ${i + 1} 句 · ${s.speaker || ''} ${fmt(s.start)}–${fmt(s.end)}`;
  }
  render();
}

function retap(i){
  const s = data.sentences[i];
  if (!s) return;
  const now = audio.currentTime;
  const next = data.sentences[i + 1];
  s.start = now;
  if (next && next.start > now + 0.2) s.end = next.start - 0.05;
  else s.end = Math.min(audio.duration || (now + 3), now + 3);
  s.edited = true;
  stopAt = s.end;
  $('#now').textContent = `第 ${i + 1} 句重打点：${fmt(s.start)}–${fmt(s.end)}`;
  render();
}

$('#list').addEventListener('click', (e) => {
  const btn = e.target.closest('button[data-act]');
  if (btn) {
    e.stopPropagation();
    const i = Number(btn.dataset.i);
    const act = btn.dataset.act;
    if (act === 'play') playAt(i);
    else if (act === 'start-') nudge(i, 'start', -0.1);
    else if (act === 'start+') nudge(i, 'start', 0.1);
    else if (act === 'end-') nudge(i, 'end', -0.1);
    else if (act === 'end+') nudge(i, 'end', 0.1);
    else if (act === 'retap') retap(i);
    else if (act === 'delete') {
      if (confirm('删除这一句？')) {
        data.sentences.splice(i, 1);
        data.sentences.forEach((s, k) => { s.i = k; });
        selected = Math.min(selected, data.sentences.length - 1);
        render();
      }
    }
    return;
  }
  const row = e.target.closest('.row');
  if (row) playAt(Number(row.dataset.i));
});

$('#playBtn').addEventListener('click', () => {
  if (!audio.paused) { audio.pause(); return; }
  if (selected >= 0) playAt(selected);
  else playAt(0);
});

audio.addEventListener('timeupdate', () => {
  $('#cur').textContent = fmt(audio.currentTime);
  if (stopAt != null && audio.currentTime >= stopAt - 0.02) {
    audio.pause();
    stopAt = null;
  }
});
audio.addEventListener('loadedmetadata', () => {
  $('#dur').textContent = fmt(audio.duration);
});
audio.addEventListener('play', () => { $('#playBtn').textContent = '❚❚'; watchClip(); });
audio.addEventListener('pause', () => { $('#playBtn').textContent = '▶'; });
audio.addEventListener('error', () => {
  $('#now').textContent = '音频加载失败：确认 HTML 和 __AUDIO__ 的相对路径正确';
});

$('#speed').addEventListener('change', (e) => {
  audio.playbackRate = parseFloat(e.target.value);
});

$('#lowOnly').addEventListener('change', render);

$('#applyOffset').addEventListener('click', () => {
  const d = parseFloat($('#offset').value) || 0;
  if (!d) return;
  for (const s of data.sentences) {
    s.start = Math.max(0, s.start + d);
    s.end = Math.max(s.start + 0.15, s.end + d);
    s.edited = true;
  }
  $('#now').textContent = `已整体偏移 ${d > 0 ? '+' : ''}${d.toFixed(1)} 秒`;
  render();
});

$('#export').addEventListener('click', () => {
  data.generated_at = new Date().toISOString();
  data.stats = {
    sentences: data.sentences.length,
    low_confidence: data.sentences.filter(s => s.needs_review).length,
    mean_confidence: data.sentences.length
      ? Math.round(data.sentences.reduce((a,s) => a + (s.confidence || 0), 0) / data.sentences.length * 1000) / 1000
      : 0
  };
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'episode.json';
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 4000);
});

document.addEventListener('keydown', (e) => {
  const tag = (e.target && e.target.tagName || '').toLowerCase();
  if (tag === 'input' || tag === 'select' || tag === 'textarea') return;
  if (e.code === 'Space') {
    e.preventDefault();
    if (audio.paused) {
      if (selected >= 0) playAt(selected); else playAt(0);
    } else {
      audio.pause();
    }
  } else if (e.key === 'ArrowDown') {
    e.preventDefault();
    playAt(Math.min(data.sentences.length - 1, selected + 1));
  } else if (e.key === 'ArrowUp') {
    e.preventDefault();
    playAt(Math.max(0, selected - 1));
  } else if (e.key === 'r' || e.key === 'R') {
    if (selected >= 0) playAt(selected);
  }
});

render();
</script>
</body>
</html>
"""


def audio_references(audio: Path, out_dir: Path) -> tuple[str, str]:
    """返回 (JSON 里的音频路径, 校对页的 src)。

    同盘用相对路径；跨盘 relpath 会抛 ValueError，改用 file:/// 绝对 URL。
    """
    try:
        rel = os.path.relpath(audio, out_dir).replace("\\", "/")
        return rel, quote(rel, safe="/")
    except ValueError:
        posix = audio.as_posix()
        return posix, "file:///" + posix.lstrip("/")


def render_preview(data: dict, audio_href: str) -> str:
    payload = json.dumps(data, ensure_ascii=False, indent=2).replace("</", "<\\/")
    return (PREVIEW_TEMPLATE
            .replace("__TITLE__", html.escape(str(data.get("title", "episode"))))
            .replace("__AUDIO__", html.escape(audio_href, quote=True))
            .replace("__DATA__", payload))


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="把整段音频 + 文字稿对齐成逐句时间轴（BBC / 播客 / 讲座）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--audio", required=True, help="音频文件（mp3/m4a/wav）")
    parser.add_argument("--transcript", required=True, help="文字稿（txt / markdown，从页面复制即可）")
    parser.add_argument("--out", default="out", help="输出目录")
    parser.add_argument("--title", default="", help="标题，默认取文稿文件名")
    parser.add_argument("--model", default="small.en",
                        help="faster-whisper 模型名（tiny.en/base.en/small.en/medium.en）或本地模型目录")
    parser.add_argument("--device", default="cpu", help="cpu / cuda")
    parser.add_argument("--compute-type", default="int8", help="int8 / float16 / float32")
    parser.add_argument("--language", default="en", help="语言代码")
    parser.add_argument("--beam-size", type=int, default=5)
    parser.add_argument("--model-dir", default=str(Path.home() / ".cache" / "audio-align"),
                        help="模型缓存目录")
    parser.add_argument("--asr-json", default="", help="跳过 ASR，直接读词级时间戳 JSON")
    parser.add_argument("--pad-start", type=float, default=0.15, help="句首留白（秒）")
    parser.add_argument("--pad-end", type=float, default=0.25, help="句尾留白（秒）")
    parser.add_argument("--offset", type=float, default=0.0, help="整篇统一偏移（秒）")
    parser.add_argument("--min-confidence", type=float, default=0.6,
                        help="低于该匹配率标记 needs_review")
    parser.add_argument("--no-preview", action="store_true", help="不生成 preview.html")
    args = parser.parse_args(argv)

    audio = Path(args.audio).expanduser().resolve()
    transcript = Path(args.transcript).expanduser().resolve()
    out_dir = Path(args.out).expanduser().resolve()

    if not audio.exists():
        die(f"找不到音频：{audio}")
    if not transcript.exists():
        die(f"找不到文稿：{transcript}")
    out_dir.mkdir(parents=True, exist_ok=True)

    title = args.title.strip() or transcript.stem
    log(f"文稿：{transcript.name}")

    seeds = parse_transcript(transcript)
    if not seeds:
        die("文稿解析后是空的：检查文件编码，或文稿格式是否有变化")
    log(f"分句：{len(seeds)} 句")

    sentences = [{"speaker": s.speaker, "text": s.text} for s in seeds]
    tokens = build_transcript_tokens(sentences)
    log(f"文稿 token：{len(tokens)}")

    if args.asr_json:
        words = load_asr_json(Path(args.asr_json).expanduser().resolve())
        duration = probe_duration(audio)
        log(f"读取 ASR JSON：{len(words)} 个词")
    else:
        words, duration = transcribe(
            audio, args.model, args.device, args.compute_type,
            args.language, Path(args.model_dir), args.beam_size,
        )

    if not words:
        die("ASR 没有产出词级时间戳")

    if args.offset:
        for w in words:
            w.start = max(0.0, w.start + args.offset)
            w.end = max(0.0, w.end + args.offset)

    stats = align(
        sentences, tokens, words, duration,
        args.pad_start, args.pad_end, args.min_confidence,
    )

    audio_rel, audio_src = audio_references(audio, out_dir)
    data = {
        "version": 1,
        "title": title,
        "audio": audio_rel,
        "duration": round(float(duration), 3),
        "language": args.language,
        "model": args.model if not args.asr_json else "external-json",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "stats": stats,
        "sentences": [
            {
                "i": i,
                "speaker": s["speaker"],
                "text": s["text"],
                "start": s["start"],
                "end": s["end"],
                "confidence": s["confidence"],
                "needs_review": s["needs_review"],
            }
            for i, s in enumerate(sentences)
        ],
    }

    json_path = out_dir / "episode.json"
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    asr_path = out_dir / "asr_words.json"
    asr_path.write_text(
        json.dumps({"words": [{"word": w.word, "start": round(w.start, 3), "end": round(w.end, 3)}
                              for w in words]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if not args.no_preview:
        (out_dir / "preview.html").write_text(render_preview(data, audio_src), encoding="utf-8")

    log(f"完成：{stats['sentences']} 句，平均置信度 {stats['mean_confidence']:.2f}，"
        f"待校对 {stats['low_confidence']} 句")
    log(f"JSON：{json_path}")
    if not args.no_preview:
        log(f"校对页：{out_dir / 'preview.html'}（浏览器打开，file:// 即可）")
    return 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
    raise SystemExit(main())
