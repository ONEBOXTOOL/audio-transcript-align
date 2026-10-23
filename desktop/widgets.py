# -*- coding: utf-8 -*-
"""通用控件：拖放区、文件行、波形。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .theme import AMBER, FAINT, GREEN, speaker_color

AUDIO_SUFFIXES = {".mp3", ".m4a", ".wav", ".flac", ".ogg", ".aac"}
TEXT_SUFFIXES = {".txt", ".md", ".markdown"}


def fmt_time(t: float) -> str:
    if t is None or t != t or t < 0:
        t = 0.0
    m = int(t // 60)
    s = t - m * 60
    return f"{m}:{s:05.2f}"


class DropZone(QFrame):
    filesDropped = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DropZone")
        self.setProperty("drag", "false")
        self.setAcceptDrops(True)
        self.setMinimumHeight(104)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(4)
        title = QLabel("把音频和文稿拖到这里")
        title.setStyleSheet("font-size:14px; font-weight:600; color:#1F241F;")
        title.setAlignment(Qt.AlignCenter)
        sub = QLabel("mp3 / m4a / wav  +  txt / md；也可以点下面的「选择…」")
        sub.setObjectName("Hint")
        sub.setAlignment(Qt.AlignCenter)
        lay.addStretch(1)
        lay.addWidget(title)
        lay.addWidget(sub)
        lay.addStretch(1)

    def _urls(self, event):
        out = []
        for url in event.mimeData().urls():
            p = url.toLocalFile()
            if p:
                out.append(p)
        return out

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setProperty("drag", "true")
            self.style().unpolish(self)
            self.style().polish(self)

    def dragLeaveEvent(self, event):
        self.setProperty("drag", "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def dropEvent(self, event):
        self.setProperty("drag", "false")
        self.style().unpolish(self)
        self.style().polish(self)
        paths = self._urls(event)
        if paths:
            self.filesDropped.emit(paths)
            event.acceptProposedAction()


class PathRow(QWidget):
    pathChanged = Signal(str)

    def __init__(self, label: str, mode: str, file_filter: str = "", parent=None):
        super().__init__(parent)
        self.mode = mode
        self.file_filter = file_filter
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(9)
        self.label = QLabel(label)
        self.label.setObjectName("FieldLabel")
        self.label.setFixedWidth(64)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("未选择")
        self.edit.setClearButtonEnabled(True)
        self.btn = QPushButton("选择…")
        self.btn.setObjectName("Ghost")
        self.btn.setFixedWidth(72)
        lay.addWidget(self.label)
        lay.addWidget(self.edit, 1)
        lay.addWidget(self.btn)
        self.btn.clicked.connect(self.browse)
        self.edit.textChanged.connect(self.pathChanged.emit)

    def browse(self):
        start = str(Path(self.edit.text()).parent) if self.edit.text() else str(Path.home())
        if self.mode == "dir":
            path = QFileDialog.getExistingDirectory(self, f"选择{self.label.text()}", start)
        else:
            path, _ = QFileDialog.getOpenFileName(self, f"选择{self.label.text()}", start, self.file_filter)
        if path:
            self.set_path(path)

    def path(self) -> str:
        return self.edit.text().strip()

    def set_path(self, path: str):
        self.edit.setText(str(path))

    def set_read_only(self, ro: bool):
        self.edit.setReadOnly(ro)
        self.btn.setEnabled(not ro)


class WaveformWidget(QWidget):
    seekRequested = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.peaks: list[float] = []
        self.duration = 0.0
        self.sentences: list[dict] = []
        self.current = -1
        self.position = 0.0
        self.setMinimumHeight(104)
        self.setMaximumHeight(130)
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("单击波形定位到对应句子；拖动边界是 v2")

    def set_data(self, peaks: list[float], duration: float, sentences: list[dict]):
        self.peaks = peaks or []
        self.duration = float(duration or 0)
        self.sentences = sentences or []
        self.update()

    def set_current(self, index: int):
        self.current = index
        self.update()

    def set_position(self, seconds: float):
        self.position = max(0.0, float(seconds or 0))
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.duration > 0:
            x = max(0.0, min(1.0, event.position().x() / max(1, self.width())))
            self.seekRequested.emit(x * self.duration)
        super().mousePressEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#F8F5EC"))
        p.drawRoundedRect(rect, 9, 9)

        if not self.sentences or self.duration <= 0:
            p.setPen(QColor(FAINT))
            p.setFont(QFont("Segoe UI", 9))
            p.drawText(rect, Qt.AlignCenter, "对齐完成后显示波形")
            return

        w = self.width()
        top = 7.0
        bottom = self.height() - 19.0
        span = max(1.0, bottom - top)
        mid = top + span / 2

        # 句子色块
        for i, s in enumerate(self.sentences):
            x0 = s["start"] / self.duration * w
            x1 = s["end"] / self.duration * w
            if x1 < 0 or x0 > w:
                continue
            c = QColor(speaker_color(s.get("speaker", "")))
            c.setAlpha(80 if i == self.current else 28)
            p.fillRect(QRectF(x0, top, max(1.0, x1 - x0), span), c)

        # 中线 + 波形
        p.setPen(QPen(QColor("#E7DDCB"), 1))
        p.drawLine(QPointF(0, mid), QPointF(w, mid))
        if self.peaks:
            p.setPen(QPen(QColor(47, 93, 80, 185), 1))
            n = len(self.peaks)
            amp = span * 0.42
            step = max(1, n // max(1, w))
            for i in range(0, n, step):
                x = i / max(1, n - 1) * w
                a = max(0.015, self.peaks[i]) * amp
                p.drawLine(QPointF(x, mid - a), QPointF(x, mid + a))

        # 当前句外框
        if 0 <= self.current < len(self.sentences):
            s = self.sentences[self.current]
            x0 = s["start"] / self.duration * w
            x1 = s["end"] / self.duration * w
            p.setPen(QPen(QColor(GREEN), 1.5))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(QRectF(x0, top, max(5.0, x1 - x0), span), 3, 3)

        # 播放头
        if 0 <= self.position <= self.duration:
            x = self.position / self.duration * w
            p.setPen(QPen(QColor(AMBER), 1.2))
            p.drawLine(QPointF(x, top), QPointF(x, bottom))
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(AMBER))
            p.drawPolygon(QPolygonF([QPointF(x - 4, top), QPointF(x + 4, top), QPointF(x, top + 6)]))

        # 时间刻度
        p.setPen(QColor(FAINT))
        p.setFont(QFont("Consolas", 8))
        step_sec = 60
        for t in range(0, int(self.duration) + 1, step_sec):
            x = t / self.duration * w
            label = f"{t // 60}:{t % 60:02d}"
            p.drawText(QPointF(min(x + 3, w - 28), self.height() - 4), label)
