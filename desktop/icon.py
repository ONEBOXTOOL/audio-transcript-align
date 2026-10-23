# -*- coding: utf-8 -*-
"""运行时/打包用的图标。"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPixmap


def icon_image(size: int = 256) -> QImage:
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)
    m = size * 0.055
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#2F5D50"))
    p.drawRoundedRect(QRectF(m, m, size - 2 * m, size - 2 * m), size * 0.22, size * 0.22)

    p.setPen(QColor("#FFFCF4"))
    f = QFont("Segoe UI", max(8, int(size * 0.36)), QFont.Bold)
    f.setLetterSpacing(QFont.AbsoluteSpacing, size * 0.05)
    p.setFont(f)
    p.drawText(QRectF(0, -size * 0.015, size, size), Qt.AlignCenter, "AA")
    p.end()
    return img


def icon_pixmap(size: int = 256) -> QPixmap:
    return QPixmap.fromImage(icon_image(size))
