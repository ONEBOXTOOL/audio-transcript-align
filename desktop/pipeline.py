# -*- coding: utf-8 -*-
"""桌面版的对齐管线：复用 audio_align 的解析/对齐/校对页，补上进度与取消。"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from audio_align import (
    AlignCancelled,
    align,
    audio_references,
    build_transcript_tokens,
    log,
    parse_transcript,
    render_preview,
    transcribe,
)

Progress = Callable[[float, str], None]
Cancel = Callable[[], bool]


class PipelineError(RuntimeError):
    pass


def _check(cancel: Cancel | None) -> None:
    if cancel and cancel():
        raise AlignCancelled


def compute_peaks(audio: Path, cancel: Cancel | None = None) -> tuple[list[float], list[float]]:
    """解码一次音频，返回全片 2400 点与高分辨率 12000 点的 RMS 波形。"""
    import av
    import numpy as np

    values: list[float] = []
    with av.open(str(audio)) as container:
        stream = container.streams.audio[0]
        for frame in container.decode(stream):
            _check(cancel)
            arr = frame.to_ndarray()
            if arr.ndim > 1:
                arr = arr.mean(axis=0)
            arr = arr.astype(np.float32)
            step = max(1, int(frame.sample_rate * 0.01))
            for i in range(0, len(arr), step):
                chunk = arr[i:i + step]
                if len(chunk):
                    values.append(float(np.sqrt(np.mean(chunk * chunk))))

    if not values:
        return [], []

    arr = np.asarray(values, dtype=np.float32)

    def resample(n: int) -> list[float]:
        idx = np.linspace(0, len(arr), n + 1).astype(int)
        out = np.zeros(n, dtype=np.float32)
        for i in range(n):
            a, b = idx[i], idx[i + 1]
            if b > a:
                out[i] = float(arr[a:b].mean())
        cap = float(np.percentile(out, 98.5)) or 1.0
        out = np.clip(out / cap, 0.0, 1.0) ** 0.8
        return [round(float(x), 3) for x in out]

    return resample(2400), resample(12000)


def model_ready(path: Path | None) -> bool:
    if not path:
        return False
    p = Path(path)
    return all((p / name).exists() for name in ("model.bin", "tokenizer.json", "vocabulary.txt"))


def run_alignment(
    audio: Path,
    transcript: Path,
    out_dir: Path,
    *,
    model_path: Path,
    title: str = "",
    language: str = "en",
    device: str = "cpu",
    compute_type: str = "int8",
    beam_size: int = 5,
    pad_start: float = 0.15,
    pad_end: float = 0.25,
    min_confidence: float = 0.6,
    progress: Progress | None = None,
    cancel: Cancel | None = None,
) -> dict:
    audio = Path(audio).expanduser().resolve()
    transcript = Path(transcript).expanduser().resolve()
    out_dir = Path(out_dir).expanduser().resolve()
    model_path = Path(model_path).expanduser().resolve()

    if not audio.exists():
        raise PipelineError(f"找不到音频：{audio}")
    if not transcript.exists():
        raise PipelineError(f"找不到文稿：{transcript}")
    if not model_path.exists():
        raise PipelineError(
            f"找不到模型目录：{model_path}\n\n"
            "开发环境请把 small.en 放到 models/small.en；安装版应随程序附带 models/small.en。"
        )
    out_dir.mkdir(parents=True, exist_ok=True)

    def emit(frac: float, msg: str) -> None:
        if progress:
            progress(max(0.0, min(1.0, frac)), msg)

    _check(cancel)
    emit(0.01, "读取文稿…")
    seeds = parse_transcript(transcript)
    if not seeds:
        raise PipelineError("文稿解析后是空的：检查编码/格式，或换一个 txt/md 文件。")
    log(f"分句：{len(seeds)} 句")

    sentences = [{"speaker": s.speaker, "text": s.text} for s in seeds]
    tokens = build_transcript_tokens(sentences)
    log(f"文稿 token：{len(tokens)}")
    _check(cancel)

    words, duration = transcribe(
        audio,
        str(model_path),
        device,
        compute_type,
        language,
        Path(),  # 本地模型目录不需要下载缓存
        beam_size,
        progress=lambda f, m: emit(0.02 + 0.86 * f, m),
        cancel=cancel,
    )
    if not words:
        raise PipelineError("ASR 没有产出词级时间戳。")
    _check(cancel)

    emit(0.9, "对齐句子…")
    stats = align(
        sentences, tokens, words, duration,
        pad_start, pad_end, min_confidence,
    )
    _check(cancel)

    audio_rel, audio_src = audio_references(audio, out_dir)
    data = {
        "version": 1,
        "title": (title or "").strip() or transcript.stem,
        "audio": audio_rel,
        "duration": round(float(duration), 3),
        "language": language,
        "model": "small.en",
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
        json.dumps(
            {"words": [{"word": w.word, "start": round(w.start, 3), "end": round(w.end, 3)}
                       for w in words]},
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )

    preview_path = out_dir / "preview.html"
    preview_path.write_text(render_preview(data, audio_src), encoding="utf-8")

    _check(cancel)
    emit(0.95, "计算波形…")
    try:
        peaks, peaks_hi = compute_peaks(audio, cancel)
    except Exception as exc:  # noqa: BLE001
        log(f"warning: 波形计算失败：{exc}")
        peaks, peaks_hi = [], []

    emit(1.0, "完成")
    return {
        "data": data,
        "json_path": json_path,
        "preview_path": preview_path,
        "asr_path": asr_path,
        "audio_path": audio,
        "out_dir": out_dir,
        "peaks": peaks,
        "peaks_hi": peaks_hi,
    }
