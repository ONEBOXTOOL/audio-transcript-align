# -*- coding: utf-8 -*-
"""四个页面：首页、运行中、完成、校对。"""
from __future__ import annotations

import html
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QSettings, QStandardPaths, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSlider,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from audio_align import audio_references, render_preview

from .pipeline import model_ready
from .theme import GREEN, RED, speaker_color
from .widgets import AUDIO_SUFFIXES, TEXT_SUFFIXES, DropZone, PathRow, WaveformWidget, fmt_time

ORG = "AudioAlign"
APP = "AudioAlign"


def _settings() -> QSettings:
    return QSettings(ORG, APP)


def _documents() -> Path:
    p = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)
    return Path(p) / "AudioAlign"


class HomePage(QWidget):
    startRequested = Signal(dict)

    def __init__(self, model_path: Path | None, parent=None):
        super().__init__(parent)
        self.model_path = model_path
        self._build()
        self._restore()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(44, 26, 44, 30)
        outer.setSpacing(14)
        outer.addStretch(1)

        hero = QLabel("音频 + 文稿 = 逐句时间轴")
        hero.setObjectName("Hero")
        sub = QLabel("本地运行 · 音频不上传 · 输出 episode.json / preview.html / asr_words.json")
        sub.setObjectName("HeroSub")
        outer.addWidget(hero)
        outer.addWidget(sub)

        card = QFrame()
        card.setObjectName("Card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(12)

        self.drop = DropZone()
        self.drop.filesDropped.connect(self._on_drop)
        lay.addWidget(self.drop)

        self.audio_row = PathRow("音频", "file", "音频 (*.mp3 *.m4a *.wav *.flac *.ogg *.aac)")
        self.transcript_row = PathRow("文稿", "file", "文稿 (*.txt *.md *.markdown)")
        self.out_row = PathRow("输出目录", "dir")
        lay.addWidget(self.audio_row)
        lay.addWidget(self.transcript_row)
        lay.addWidget(self.out_row)

        info = QHBoxLayout()
        info.setSpacing(8)
        self.model_chip = QLabel()
        self.model_chip.setObjectName("ChipOk" if self.model_path else "Chip")
        self.lang_chip = QLabel("英文 en")
        self.lang_chip.setObjectName("Chip")
        self.hint = QLabel("6 分钟音频约 1–2 分钟 · 无需联网")
        self.hint.setObjectName("Hint")
        info.addWidget(self.model_chip)
        info.addWidget(self.lang_chip)
        info.addSpacing(6)
        info.addWidget(self.hint, 1)
        lay.addLayout(info)

        bottom = QHBoxLayout()
        self.error = QLabel("")
        self.error.setObjectName("Error")
        self.error.setWordWrap(True)
        self.start_btn = QPushButton("开始对齐")
        self.start_btn.setObjectName("Primary")
        self.start_btn.setMinimumWidth(128)
        self.start_btn.clicked.connect(self._start)
        bottom.addWidget(self.error, 1)
        bottom.addWidget(self.start_btn)
        lay.addLayout(bottom)

        outer.addWidget(card, 0)
        outer.addStretch(1)
        self._refresh_model()

        self.transcript_row.pathChanged.connect(self._maybe_set_output)
        self.audio_row.pathChanged.connect(self._update_start_state)
        self.transcript_row.pathChanged.connect(self._update_start_state)
        self._update_start_state()

    def _refresh_model(self):
        if model_ready(self.model_path):
            self.model_chip.setText("Whisper small.en（内置）")
            self.model_chip.setToolTip(str(self.model_path))
        else:
            self.model_chip.setText("缺少 small.en 模型")
            self.model_chip.setObjectName("Chip")
            self.model_chip.style().unpolish(self.model_chip)
            self.model_chip.style().polish(self.model_chip)
            self.error.setText("找不到 models/small.en；安装版会随程序附带。")
        self._update_start_state()

    def _update_start_state(self):
        ok = model_ready(self.model_path)
        ok = ok and bool(self.audio_row.path()) and bool(self.transcript_row.path())
        self.start_btn.setEnabled(ok)

    def _restore(self):
        s = _settings()
        for row, key in ((self.audio_row, "last_audio"), (self.transcript_row, "last_transcript"),
                         (self.out_row, "last_out")):
            v = s.value(key, "", type=str)
            if v:
                row.set_path(v)
        if not self.out_row.path():
            self.out_row.set_path(str(_documents()))

    def _save(self):
        s = _settings()
        s.setValue("last_audio", self.audio_row.path())
        s.setValue("last_transcript", self.transcript_row.path())
        s.setValue("last_out", self.out_row.path())

    def _maybe_set_output(self, path: str):
        if not path:
            return
        current = self.out_row.path().strip()
        default_root = str(_documents())
        if not current or current == default_root:
            self.out_row.set_path(str(_documents() / Path(path).stem))

    def _on_drop(self, paths: list[str]):
        self.error.setText("")
        for p in paths:
            suffix = Path(p).suffix.lower()
            if suffix in AUDIO_SUFFIXES:
                self.audio_row.set_path(p)
            elif suffix in TEXT_SUFFIXES:
                self.transcript_row.set_path(p)
            else:
                self.error.setText(f"不支持的格式：{Path(p).name}（音频 mp3/m4a/wav，文稿 txt/md）")

    def _start(self):
        self.error.setText("")
        audio = self.audio_row.path()
        transcript = self.transcript_row.path()
        out_dir = self.out_row.path()
        if not audio or not Path(audio).exists():
            self.error.setText("请选择音频文件。")
            return
        if not transcript or not Path(transcript).exists():
            self.error.setText("请选择文稿文件（txt / md）。")
            return
        if not out_dir:
            self.error.setText("请选择输出目录。")
            return
        if not model_ready(self.model_path):
            self.error.setText("缺少 small.en 模型，无法开始。")
            return
        self._save()
        self.startRequested.emit({
            "audio": Path(audio),
            "transcript": Path(transcript),
            "out_dir": Path(out_dir),
            "title": Path(transcript).stem,
        })


class RunPage(QWidget):
    cancelRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._started = time.monotonic()
        self._build()
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 28)
        outer.addStretch(1)
        card = QFrame()
        card.setObjectName("Card")
        card.setMaximumWidth(820)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(26, 24, 26, 24)
        lay.setSpacing(12)

        self.title = QLabel("正在对齐…")
        self.title.setStyleSheet("font-family: Georgia; font-size: 22px; font-weight: 600;")
        self.status = QLabel("准备中")
        self.status.setObjectName("Hint")
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(8)
        meta = QHBoxLayout()
        self.percent = QLabel("0%")
        self.percent.setObjectName("TimeMono")
        self.elapsed = QLabel("已用 0:00")
        self.elapsed.setObjectName("TimeMono")
        self.elapsed.setAlignment(Qt.AlignRight)
        meta.addWidget(self.percent)
        meta.addStretch(1)
        meta.addWidget(self.elapsed)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(230)
        self.log.setFont(QFont("Consolas", 9))
        self.cancel = QPushButton("取消")
        self.cancel.setObjectName("Danger")
        self.cancel.clicked.connect(self._cancel)

        lay.addWidget(self.title)
        lay.addWidget(self.status)
        lay.addWidget(self.progress)
        lay.addLayout(meta)
        lay.addWidget(self.log, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.cancel)
        lay.addLayout(row)

        outer.addWidget(card, 0, Qt.AlignHCenter)
        outer.addStretch(1)

    def begin(self):
        self._started = time.monotonic()
        self.progress.setValue(0)
        self.percent.setText("0%")
        self.status.setText("准备中…")
        self.elapsed.setText("已用 0:00")
        self.log.clear()
        self.cancel.setEnabled(True)
        self.title.setText("正在对齐…")
        self._timer.start()

    def set_progress(self, value: int, msg: str):
        self.progress.setValue(max(0, min(1000, value)))
        self.percent.setText(f"{max(0, min(1000, value)) / 10:.1f}%")
        if msg:
            self.status.setText(msg)

    def append_log(self, msg: str):
        self.log.appendPlainText(msg)
        sb = self.log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _tick(self):
        sec = int(time.monotonic() - self._started)
        self.elapsed.setText(f"已用 {sec // 60}:{sec % 60:02d}")

    def _cancel(self):
        self.cancel.setEnabled(False)
        self.status.setText("正在取消…")
        self.cancelRequested.emit()

    def finish(self):
        self._timer.stop()


class DonePage(QWidget):
    reviewRequested = Signal()
    openFolderRequested = Signal()
    againRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.result = None
        self._build()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 30)
        outer.addStretch(1)
        card = QFrame()
        card.setObjectName("Card")
        card.setMaximumWidth(720)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(34, 28, 34, 26)
        lay.setSpacing(12)

        check = QLabel("✓")
        check.setObjectName("Check")
        check.setAlignment(Qt.AlignCenter)
        title = QLabel("对齐完成")
        title.setStyleSheet("font-family: Georgia; font-size: 24px; font-weight: 600;")
        self.episode = QLabel("")
        self.episode.setObjectName("Hint")
        self.episode.setWordWrap(True)
        self.episode.setMinimumWidth(480)
        self.episode.setAlignment(Qt.AlignCenter)

        stats = QHBoxLayout()
        stats.setSpacing(30)
        self.stat_n = self._stat("0", "句")
        self.stat_conf = self._stat("0%", "平均置信度")
        self.stat_low = self._stat("0", "待校对")
        for w in (self.stat_n, self.stat_conf, self.stat_low):
            stats.addWidget(w)
        stats.insertStretch(0, 1)
        stats.addStretch(1)

        self.path_label = QLabel("")
        self.path_label.setObjectName("Hint")
        self.path_label.setWordWrap(True)
        self.path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        buttons = QHBoxLayout()
        self.review_btn = QPushButton("进入校对")
        self.review_btn.setObjectName("Primary")
        self.folder_btn = QPushButton("打开输出目录")
        self.folder_btn.setObjectName("Ghost")
        self.again_btn = QPushButton("再处理一期")
        self.again_btn.setObjectName("Ghost")
        self.review_btn.clicked.connect(self.reviewRequested)
        self.folder_btn.clicked.connect(self.openFolderRequested)
        self.again_btn.clicked.connect(self.againRequested)
        buttons.addStretch(1)
        buttons.addWidget(self.review_btn)
        buttons.addWidget(self.folder_btn)
        buttons.addWidget(self.again_btn)
        buttons.addStretch(1)

        lay.addWidget(check, 0, Qt.AlignHCenter)
        lay.addWidget(title, 0, Qt.AlignHCenter)
        lay.addWidget(self.episode, 0, Qt.AlignHCenter)
        lay.addSpacing(6)
        lay.addLayout(stats)
        lay.addSpacing(4)
        lay.addWidget(self.path_label)
        lay.addSpacing(8)
        lay.addLayout(buttons)

        outer.addWidget(card, 0, Qt.AlignHCenter)
        outer.addStretch(1)

    def _stat(self, value: str, label: str) -> QWidget:
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        val = QLabel(value)
        val.setObjectName("StatValue")
        lab = QLabel(label)
        lab.setObjectName("StatLabel")
        v.addWidget(val)
        v.addWidget(lab)
        box._value = val  # type: ignore[attr-defined]
        return box

    def set_result(self, result: dict):
        self.result = result
        data = result["data"]
        stats = data.get("stats", {})
        self.episode.setText(f"{data.get('title', '')}  ·  {fmt_time(float(data.get('duration', 0)))}")
        self.stat_n._value.setText(str(stats.get("sentences", len(data.get("sentences", [])))))  # type: ignore[attr-defined]
        self.stat_conf._value.setText(f"{float(stats.get('mean_confidence', 0)) * 100:.1f}%")  # type: ignore[attr-defined]
        self.stat_low._value.setText(str(stats.get("low_confidence", 0)))  # type: ignore[attr-defined]
        self.path_label.setText(f"输出目录：{result['out_dir']}\nepisode.json · preview.html · asr_words.json")
        self.review_btn.setEnabled(bool(data.get("sentences")))


class ReviewPage(QWidget):
    backRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.result: dict | None = None
        self.data: dict = {}
        self.sentences: list[dict] = []
        self.cur = 0
        self.duration = 0.0
        self._syncing = False
        self._stop_at_ms: int | None = None
        self._loop = False

        self.audio_out = QAudioOutput(self)
        self.audio_out.setVolume(0.85)
        self.asr_words: list[dict] = []
        self.player = QMediaPlayer(self)
        self.player.setAudioOutput(self.audio_out)
        self.player.positionChanged.connect(self._on_position)
        self.player.durationChanged.connect(self._on_duration)
        self.player.playbackStateChanged.connect(self._on_state)

        self.stop_timer = QTimer(self)
        self.stop_timer.setInterval(15)
        self.stop_timer.timeout.connect(self._check_clip_end)

        self._build()

    # ---------------- UI ----------------
    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 12, 18, 14)
        outer.setSpacing(9)

        head = QHBoxLayout()
        self.title = QLabel("")
        self.title.setStyleSheet("font-family: Georgia; font-size: 18px; font-weight: 600;")
        self.stats = QLabel("")
        self.stats.setObjectName("Hint")
        self.export_btn = QPushButton("导出 JSON")
        self.export_btn.setObjectName("Primary")
        self.export_btn.setShortcut("Ctrl+S")
        self.export_btn.setToolTip("写回 episode.json，并重写 preview.html（Ctrl+S）")
        self.export_btn.clicked.connect(self.export_json)
        head.addWidget(self.title)
        head.addSpacing(10)
        head.addWidget(self.stats)
        head.addStretch(1)
        head.addWidget(self.export_btn)
        outer.addLayout(head)

        player_card = QFrame()
        player_card.setObjectName("Card")
        pl = QHBoxLayout(player_card)
        pl.setContentsMargins(12, 9, 12, 9)
        pl.setSpacing(10)
        self.play_btn = QPushButton("▶")
        self.play_btn.setObjectName("Play")
        self.play_btn.setToolTip("播放当前句")
        self.play_btn.clicked.connect(self.toggle_play)
        self.time_label = QLabel("0:00.00 / 0:00.00")
        self.time_label.setObjectName("TimeMono")
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 0)
        self.slider.sliderMoved.connect(self._slider_moved)
        self.slider.sliderReleased.connect(self._slider_released)
        self.speed = QComboBox()
        for x in (0.75, 1.0, 1.25, 1.5):
            self.speed.addItem(f"{x:g}×", x)
        self.speed.setCurrentIndex(1)
        self.speed.currentIndexChanged.connect(self._speed_changed)
        self.loop_cb = QCheckBox("循环")
        self.loop_cb.toggled.connect(self._loop_changed)
        self.replay_btn = QPushButton("重播")
        self.replay_btn.setObjectName("Ghost")
        self.replay_btn.clicked.connect(self.play_clip)
        pl.addWidget(self.play_btn)
        pl.addWidget(self.time_label)
        pl.addWidget(self.slider, 1)
        pl.addWidget(self.speed)
        pl.addWidget(self.loop_cb)
        pl.addWidget(self.replay_btn)
        outer.addWidget(player_card)

        self.wave = WaveformWidget()
        self.wave.seekRequested.connect(self._wave_seek)
        outer.addWidget(self.wave)

        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["句", "说话人", "文本", "起点", "终点", "置信度"])
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setWordWrap(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        hh.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.table.verticalHeader().setDefaultSectionSize(38)
        self.table.itemSelectionChanged.connect(self._table_selected)
        split.addWidget(self.table)

        editor = QFrame()
        editor.setObjectName("Card")
        el = QVBoxLayout(editor)
        el.setContentsMargins(16, 13, 16, 13)
        el.setSpacing(9)

        meta = QHBoxLayout()
        self.idx_label = QLabel("第 1 句 / 1")
        self.idx_label.setObjectName("SentenceIndex")
        self.speaker = QLabel("")
        self.speaker.setObjectName("SpeakerPill")
        self.speaker.setFixedHeight(22)
        self.speaker.setMinimumWidth(70)
        self.conf = QLabel("")
        self.conf.setObjectName("ConfPill")
        self.conf.setFixedHeight(22)
        self.edited = QLabel("已改")
        self.edited.setObjectName("Chip")
        self.edited.setFixedHeight(22)
        self.edited.setVisible(False)
        meta.addWidget(self.idx_label)
        meta.addWidget(self.speaker)
        meta.addWidget(self.conf)
        meta.addWidget(self.edited)
        meta.addStretch(1)
        el.addLayout(meta)

        self.text = QTextEdit()
        self.text.setObjectName("SentenceEdit")
        self.text.setFixedHeight(94)
        self.text.textChanged.connect(self._text_changed)
        el.addWidget(self.text)

        times = QVBoxLayout()
        times.setSpacing(5)
        for field, text in (("start", "起点"), ("end", "终点")):
            row = QHBoxLayout()
            row.setSpacing(6)
            row.addWidget(self._time_label(text))
            spin = self._spin()
            if field == "start":
                self.start_spin = spin
            else:
                self.end_spin = spin
            spin.valueChanged.connect(lambda v, f=field: self._time_changed(f, v))
            row.addWidget(spin)
            row.addWidget(self._nudge("−0.1s", field, -0.1))
            row.addWidget(self._nudge("+0.1s", field, 0.1))
            row.addStretch(1)
            times.addLayout(row)
        el.addLayout(times)

        actions = QHBoxLayout()
        actions.setSpacing(6)
        self.play_sel = QPushButton("▶ 播放本句")
        self.play_sel.clicked.connect(self.play_clip)
        self.retap = QPushButton("重打点")
        self.retap.setObjectName("Ghost")
        self.retap.setToolTip("把起点设为当前播放位置；终点取下一句起点或 +3 秒")
        self.retap.clicked.connect(self.retap_sentence)
        self.delete = QPushButton("删除")
        self.delete.setObjectName("Danger")
        self.delete.clicked.connect(self.delete_sentence)
        self.prev = QPushButton("← 上一句")
        self.prev.setObjectName("Ghost")
        self.prev.clicked.connect(lambda: self.select_sentence(self.cur - 1, play=False))
        self.next = QPushButton("下一句 →")
        self.next.setObjectName("Ghost")
        self.next.clicked.connect(lambda: self.select_sentence(self.cur + 1, play=False))
        actions.addWidget(self.play_sel)
        actions.addWidget(self.retap)
        actions.addWidget(self.delete)
        actions.addStretch(1)
        actions.addWidget(self.prev)
        actions.addWidget(self.next)
        el.addLayout(actions)

        el.addSpacing(2)
        words_title = QLabel("ASR 词级时间戳")
        words_title.setObjectName("Section")
        self.words = QLabel("")
        self.words.setWordWrap(True)
        self.words.setTextFormat(Qt.RichText)
        self.words.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.words.setObjectName("Hint")
        el.addWidget(words_title)
        el.addWidget(self.words)
        el.addStretch(1)

        self.hint = QLabel("改动只在「导出 JSON」时写回；同时会重写 preview.html")
        self.hint.setObjectName("Hint")
        self.hint.setWordWrap(True)
        el.addWidget(self.hint)
        split.addWidget(editor)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        split.setSizes([680, 430])
        outer.addWidget(split, 1)

    def _time_label(self, text: str) -> QLabel:
        lab = QLabel(text)
        lab.setObjectName("FieldLabel")
        return lab

    def _spin(self) -> QDoubleSpinBox:
        box = QDoubleSpinBox()
        box.setDecimals(2)
        box.setSingleStep(0.1)
        box.setRange(0, 100000)
        box.setSuffix(" s")
        box.setKeyboardTracking(False)
        box.setFixedWidth(96)
        return box

    def _nudge(self, text: str, field: str, delta: float) -> QPushButton:
        b = QPushButton(text)
        b.setObjectName("Small")
        b.setFixedWidth(48)
        b.clicked.connect(lambda: self.nudge(field, delta))
        return b

    # ---------------- data ----------------
    def load(self, result: dict):
        self.result = result
        self.data = result["data"]
        self.sentences = self.data.get("sentences", [])
        self.duration = float(self.data.get("duration") or 0)
        self.title.setText(self.data.get("title", ""))
        self.wave.set_data(result.get("peaks", []), self.duration, self.sentences)
        self.player.setSource(QUrl.fromLocalFile(str(result["audio_path"])))
        self.asr_words = []
        try:
            asr_path = result.get("asr_path")
            if asr_path and Path(asr_path).exists():
                self.asr_words = json.loads(Path(asr_path).read_text(encoding="utf-8")).get("words", [])
        except Exception:
            self.asr_words = []
        self._refresh_table()
        self._refresh_stats()
        first = next((s["i"] for s in self.sentences if s.get("needs_review")), 0)
        self.select_sentence(first, play=False)

    def _refresh_stats(self):
        n = len(self.sentences)
        low = sum(1 for s in self.sentences if s.get("needs_review"))
        mean = sum(float(s.get("confidence", 0)) for s in self.sentences) / n if n else 0
        self.stats.setText(f"{n} 句 · 平均 {mean * 100:.1f}% · 待校对 {low}")

    def _refresh_table(self):
        self._syncing = True
        self.table.setRowCount(len(self.sentences))
        for row, s in enumerate(self.sentences):
            values = [str(row + 1), s.get("speaker", ""), s.get("text", ""),
                      f"{float(s.get('start', 0)):.2f}", f"{float(s.get('end', 0)):.2f}",
                      f"{float(s.get('confidence', 0)) * 100:.0f}%"]
            for col, val in enumerate(values):
                item = QTableWidgetItem(val)
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                if col == 1:
                    item.setForeground(QColor(speaker_color(s.get("speaker", ""))))
                if col == 5:
                    c = float(s.get("confidence", 0))
                    item.setForeground(QColor(RED if c < 0.6 else ("#A2653C" if c < 0.8 else GREEN)))
                if col in (3, 4):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                item.setToolTip(s.get("text", ""))
                self.table.setItem(row, col, item)
        self._syncing = False

    def _update_row(self, row: int):
        if not (0 <= row < len(self.sentences)) or not self.table.item(row, 0):
            return
        s = self.sentences[row]
        self.table.item(row, 1).setText(s.get("speaker", ""))
        self.table.item(row, 2).setText(s.get("text", ""))
        self.table.item(row, 3).setText(f"{float(s.get('start', 0)):.2f}")
        self.table.item(row, 4).setText(f"{float(s.get('end', 0)):.2f}")
        self.table.item(row, 5).setText(f"{float(s.get('confidence', 0)) * 100:.0f}%")
        self.table.item(row, 5).setForeground(QColor(GREEN if float(s.get("confidence", 0)) >= 0.8 else "#A2653C"))

    def select_sentence(self, index: int, play: bool = False):
        if not self.sentences:
            return
        index = max(0, min(len(self.sentences) - 1, index))
        self.cur = index
        self._syncing = True
        self.table.selectRow(index)
        self.table.scrollToItem(self.table.item(index, 0), QAbstractItemView.PositionAtCenter)
        self._syncing = False
        self._sync_editor()
        self.wave.set_current(index)
        if play:
            self.play_clip()

    def _table_selected(self):
        if self._syncing:
            return
        rows = self.table.selectionModel().selectedRows()
        if rows:
            self.select_sentence(rows[0].row(), play=False)

    def _sync_editor(self):
        if not self.sentences:
            return
        s = self.sentences[self.cur]
        self._syncing = True
        self.idx_label.setText(f"第 {self.cur + 1} 句 / {len(self.sentences)}")
        self.speaker.setText(s.get("speaker", "—"))
        c = float(s.get("confidence", 0))
        self.conf.setText(f"{c * 100:.0f}%")
        self.conf.setStyleSheet(
            "background:#F6E2DF;color:#B3352B;" if c < 0.6 else
            ("background:#F7EBD8;color:#7A5322;" if c < 0.8 else "")
        )
        self.edited.setVisible(bool(s.get("edited")))
        self.text.setPlainText(s.get("text", ""))
        self.start_spin.setRange(0, max(0.0, self.duration))
        self.end_spin.setRange(0, max(0.0, self.duration))
        self.start_spin.setValue(float(s.get("start", 0)))
        self.end_spin.setValue(float(s.get("end", 0)))
        self._syncing = False
        self.play_sel.setEnabled(True)
        self._render_words(s)

    def _render_words(self, s: dict):
        if not self.asr_words:
            self.words.setText("<span style='color:#9A917F'>暂无词级时间戳</span>")
            return
        start = float(s.get("start", 0))
        end = float(s.get("end", 0))
        ws = [w for w in self.asr_words
              if float(w.get("end", 0)) > start - 0.15 and float(w.get("start", 0)) < end + 0.02]
        if not ws:
            self.words.setText("<span style='color:#9A917F'>本句区间没有匹配到 ASR 词</span>")
            return
        parts = []
        for w in ws[:48]:
            parts.append(
                f"<span style='color:#1F241F'>{html.escape(str(w.get('word', '')))}</span> "
                f"<span style='color:#9A917F;font-family:Consolas'>{float(w.get('start', 0)):.2f}</span>"
            )
        text = " &nbsp;·&nbsp; ".join(parts)
        if len(ws) > 48:
            text += f" <span style='color:#9A917F'>… +{len(ws) - 48} 词</span>"
        self.words.setText(text)

    def _text_changed(self):
        if self._syncing or not self.sentences:
            return
        s = self.sentences[self.cur]
        new = self.text.toPlainText().strip()
        if new == s.get("text", ""):
            return
        s["text"] = new
        s["edited"] = True
        self.edited.setVisible(True)
        self._update_row(self.cur)

    def _time_changed(self, field: str, value: float):
        if self._syncing or not self.sentences:
            return
        s = self.sentences[self.cur]
        other = "end" if field == "start" else "start"
        if field == "start" and value > float(s.get("end", 0)) - 0.15:
            value = max(0.0, float(s.get("end", 0)) - 0.15)
        if field == "end" and value < float(s.get("start", 0)) + 0.15:
            value = float(s.get("start", 0)) + 0.15
        if abs(value - float(s.get(field, 0))) < 1e-9:
            return
        s[field] = round(value, 3)
        s["edited"] = True
        self.edited.setVisible(True)
        self._syncing = True
        self.start_spin.setValue(float(s.get("start", 0)))
        self.end_spin.setValue(float(s.get("end", 0)))
        self._syncing = False
        self._update_row(self.cur)
        self.wave.update()

    def nudge(self, field: str, delta: float):
        if not self.sentences:
            return
        box = self.start_spin if field == "start" else self.end_spin
        box.setValue(box.value() + delta)

    # ---------------- audio ----------------
    def _on_duration(self, ms: int):
        if ms > 0:
            self.duration = max(self.duration, ms / 1000.0)
        self.slider.setRange(0, max(0, int(self.duration * 1000)))
        self.time_label.setText(f"{fmt_time(self.player.position() / 1000)} / {fmt_time(self.duration)}")

    def _on_position(self, ms: int):
        if not self.slider.isSliderDown():
            self.slider.setValue(ms)
        self.time_label.setText(f"{fmt_time(ms / 1000)} / {fmt_time(self.duration)}")
        self.wave.set_position(ms / 1000)

    def _on_state(self, state):
        self.play_btn.setText("❚❚" if state == QMediaPlayer.PlayingState else "▶")
        if state != QMediaPlayer.PlayingState:
            self.stop_timer.stop()

    def _slider_moved(self, value: int):
        self.time_label.setText(f"{fmt_time(value / 1000)} / {fmt_time(self.duration)}")
        self.wave.set_position(value / 1000)

    def _slider_released(self):
        self.player.setPosition(self.slider.value())

    def _speed_changed(self):
        self.player.setPlaybackRate(float(self.speed.currentData()))

    def _loop_changed(self, checked: bool):
        self._loop = checked

    def play_clip(self):
        if not self.sentences:
            return
        s = self.sentences[self.cur]
        self._stop_at_ms = int(float(s.get("end", 0)) * 1000)
        self.player.setPosition(int(float(s.get("start", 0)) * 1000))
        self.player.play()
        self.stop_timer.start()

    def toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
            self.stop_timer.stop()
        else:
            self.play_clip()

    def _check_clip_end(self):
        if self._stop_at_ms is None:
            self.stop_timer.stop()
            return
        if self.player.position() >= self._stop_at_ms - 8:
            if self._loop and self.sentences:
                s = self.sentences[self.cur]
                self.player.setPosition(int(float(s.get("start", 0)) * 1000))
                self.player.play()
            else:
                self.player.pause()
                self._stop_at_ms = None
                self.stop_timer.stop()

    def _wave_seek(self, t: float):
        if not self.sentences:
            return
        idx = next((i for i, s in enumerate(self.sentences)
                    if float(s.get("start", 0)) <= t <= float(s.get("end", 0))), self.cur)
        self.select_sentence(idx, play=False)
        self.player.setPosition(int(t * 1000))

    # ---------------- edit ----------------
    def retap_sentence(self):
        if not self.sentences:
            return
        s = self.sentences[self.cur]
        now = self.player.position() / 1000.0
        if now <= 0 and float(s.get("start", 0)) > 0:
            now = float(s.get("start", 0))
        nxt = self.sentences[self.cur + 1] if self.cur + 1 < len(self.sentences) else None
        s["start"] = round(now, 3)
        if nxt and float(nxt.get("start", 0)) > now + 0.2:
            s["end"] = round(float(nxt["start"]) - 0.05, 3)
        else:
            s["end"] = round(min(self.duration or now + 3, now + 3), 3)
        s["edited"] = True
        self._sync_editor()
        self._update_row(self.cur)
        self.wave.update()

    def delete_sentence(self):
        if not self.sentences:
            return
        if QMessageBox.question(self, "删除句子", f"删除第 {self.cur + 1} 句？\n导出 JSON 时才会写回。") != QMessageBox.Yes:
            return
        del self.sentences[self.cur]
        for i, s in enumerate(self.sentences):
            s["i"] = i
        self._refresh_table()
        self._refresh_stats()
        self.select_sentence(min(self.cur, len(self.sentences) - 1))

    def export_json(self):
        if not self.result:
            return
        for i, s in enumerate(self.sentences):
            s["i"] = i
            if s.get("edited"):
                s["needs_review"] = False
        n = len(self.sentences)
        self.data["stats"] = {
            "sentences": n,
            "low_confidence": sum(1 for s in self.sentences if s.get("needs_review")),
            "mean_confidence": round(sum(float(s.get("confidence", 0)) for s in self.sentences) / n, 3) if n else 0,
        }
        self.data["sentences"] = self.sentences
        self.data["generated_at"] = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        json_path = Path(self.result["json_path"])
        json_path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            _rel, src = audio_references(Path(self.result["audio_path"]), Path(self.result["out_dir"]))
            Path(self.result["preview_path"]).write_text(render_preview(self.data, src), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "预览页未更新", f"episode.json 已写回，但 preview.html 更新失败：\n{exc}")
        self.result["data"] = self.data
        self._refresh_stats()
        QMessageBox.information(self, "已导出", f"已写回：\n{json_path}\n\n同时更新了 preview.html")
