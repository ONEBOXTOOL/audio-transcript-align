# -*- coding: utf-8 -*-
"""后台对齐线程：把 Python 回调转成 Qt 信号。"""
from __future__ import annotations

import threading
import traceback
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from audio_align import AlignCancelled

from .pipeline import run_alignment


class AlignWorker(QThread):
    progress = Signal(int, str)      # 0..1000, message
    logLine = Signal(str)
    finishedOk = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, audio: Path, transcript: Path, out_dir: Path, model_path: Path,
                 language: str = "en", parent=None):
        super().__init__(parent)
        self.audio = audio
        self.transcript = transcript
        self.out_dir = out_dir
        self.model_path = model_path
        self.language = language
        self._cancel = threading.Event()
        self._logs: list[str] = []

    def cancel(self):
        self._cancel.set()

    def _hook(self, msg: str):
        self._logs.append(msg)
        if len(self._logs) > 300:
            self._logs = self._logs[-200:]
        self.logLine.emit(msg)

    def run(self):
        import audio_align
        old_hook = audio_align.LOG_HOOK
        audio_align.LOG_HOOK = self._hook
        try:
            result = run_alignment(
                self.audio,
                self.transcript,
                self.out_dir,
                model_path=self.model_path,
                language=self.language,
                progress=lambda f, m: self.progress.emit(int(round(f * 1000)), m),
                cancel=self._cancel.is_set,
            )
            self.finishedOk.emit(result)
        except AlignCancelled:
            self.cancelled.emit()
        except SystemExit:
            msg = next((x for x in reversed(self._logs) if "ERROR:" in x), "对齐失败")
            self.failed.emit(msg.split("ERROR:", 1)[-1].strip())
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(f"{exc}\n\n{traceback.format_exc(limit=6)}")
        finally:
            audio_align.LOG_HOOK = old_hook
