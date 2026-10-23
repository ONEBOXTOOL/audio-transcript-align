# -*- coding: utf-8 -*-
"""窗口配色与 QSS。"""

PAPER = "#F3F0E6"
SURFACE = "#FCFAF4"
SURFACE2 = "#F8F5EC"
INK = "#1F241F"
MUTED = "#6E6657"
FAINT = "#9A917F"
LINE = "#E1D6C1"
LINE2 = "#D3C6AC"
GREEN = "#2F5D50"
GREEN2 = "#3F7A68"
MINT = "#DCE8E2"
MINT2 = "#EDF4F0"
AMBER = "#C6863C"
RED = "#B3352B"

SPEAKER_COLORS = {
    "Georgie": "#2F5D50",
    "Phil": "#3E6E8E",
    "Catherine Schenk": "#A2653C",
    "John Reade": "#6A5A8E",
    "Suki Cooper": "#8A7A3B",
}


def speaker_color(name: str) -> str:
    return SPEAKER_COLORS.get(name or "", "#6B6355")


APP_QSS = """
QWidget {
    color: #1F241F;
    font-size: 13px;
}
QMainWindow, QWidget#Root {
    background: #F3F0E6;
}
QWidget#TopBar {
    background: #FCFAF4;
    border-bottom: 1px solid #E1D6C1;
}
QLabel#BrandMark {
    background: #2F5D50;
    color: #FFFFFF;
    border-radius: 5px;
    font-size: 10px;
    font-weight: 700;
    min-width: 20px;
    max-width: 20px;
    min-height: 20px;
    max-height: 20px;
}
QLabel#BrandName {
    color: #2F5D50;
    font-size: 11px;
    font-weight: 700;
}
QLabel#BrandSub {
    color: #6E6657;
    font-size: 11px;
}
QLabel#TopContext {
    color: #1F241F;
    font-size: 13px;
    font-weight: 600;
}
QLabel#Chip {
    background: #F8F5EC;
    border: 1px solid #E1D6C1;
    border-radius: 10px;
    color: #6E6657;
    font-size: 10px;
    padding: 3px 9px;
}
QLabel#ChipOk {
    background: #DCE8E2;
    border: 1px solid #C8DED3;
    border-radius: 10px;
    color: #1E4A3D;
    font-size: 10px;
    padding: 3px 9px;
}
QFrame#Card {
    background: #FCFAF4;
    border: 1px solid #E1D6C1;
    border-radius: 14px;
}
QFrame#DropZone {
    background: #F8F5EC;
    border: 1px dashed #CDBEA3;
    border-radius: 12px;
}
QFrame#DropZone[drag="true"] {
    background: #EDF4F0;
    border: 1px solid #3F7A68;
}
QLabel#Hero {
    color: #1F241F;
    font-family: Georgia, "Times New Roman", serif;
    font-size: 27px;
}
QLabel#HeroSub {
    color: #6E6657;
    font-size: 11px;
}
QLabel#Section {
    color: #9A917F;
    font-size: 10px;
    font-weight: 700;
}
QLabel#FieldLabel {
    color: #6E6657;
    font-size: 11px;
}
QLabel#Hint {
    color: #9A917F;
    font-size: 10px;
}
QLabel#Error {
    color: #B3352B;
    font-size: 11px;
}
QLabel#StatValue {
    color: #1F241F;
    font-family: Consolas, "Courier New", monospace;
    font-size: 22px;
}
QLabel#StatLabel {
    color: #9A917F;
    font-size: 10px;
}
QLabel#Check {
    background: #DCE8E2;
    color: #2F5D50;
    border-radius: 28px;
    font-size: 26px;
    font-weight: 700;
    min-width: 56px;
    max-width: 56px;
    min-height: 56px;
    max-height: 56px;
}
QLabel#SentenceIndex {
    color: #2F5D50;
    font-family: Consolas, "Courier New", monospace;
    font-size: 11px;
}
QLabel#SpeakerPill {
    background: #F8F5EC;
    border: 1px solid #E1D6C1;
    border-radius: 10px;
    color: #6E6657;
    font-size: 10px;
    padding: 2px 8px;
}
QLabel#ConfPill {
    background: #DCE8E2;
    border-radius: 10px;
    color: #1E4A3D;
    font-family: Consolas, "Courier New", monospace;
    font-size: 10px;
    padding: 2px 8px;
}
QLabel#TimeMono {
    color: #6E6657;
    font-family: Consolas, "Courier New", monospace;
    font-size: 11px;
}
QLineEdit, QComboBox, QDoubleSpinBox {
    background: #F8F5EC;
    border: 1px solid #E1D6C1;
    border-radius: 7px;
    padding: 7px 9px;
    selection-background-color: #DCE8E2;
}
QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus {
    border: 1px solid #3F7A68;
    background: #FFFFFF;
}
QLineEdit[readOnly="true"] {
    color: #6E6657;
}
QComboBox::drop-down {
    border: none;
    width: 18px;
}
QComboBox QAbstractItemView {
    background: #FFFFFF;
    border: 1px solid #E1D6C1;
    selection-background-color: #DCE8E2;
    selection-color: #1F241F;
}
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
    width: 14px;
    border: none;
    background: transparent;
}
QPushButton {
    background: #FCFAF4;
    border: 1px solid #D3C6AC;
    border-radius: 8px;
    color: #1F241F;
    padding: 7px 14px;
}
QPushButton:hover {
    border-color: #2F5D50;
    color: #2F5D50;
}
QPushButton:pressed {
    background: #EDF4F0;
}
QPushButton:disabled {
    color: #B7AE9D;
    border-color: #E1D6C1;
}
QPushButton#Primary {
    background: #2F5D50;
    border: 1px solid #2F5D50;
    color: #FFFFFF;
    font-weight: 600;
    padding: 10px 20px;
}
QPushButton#Primary:hover {
    background: #254B40;
    border-color: #254B40;
}
QPushButton#Primary:disabled {
    background: #A9B7AF;
    border-color: #A9B7AF;
    color: #F3F0E6;
}
QPushButton#Ghost {
    background: transparent;
    border: 1px solid #D3C6AC;
    color: #6E6657;
}
QPushButton#Ghost:hover {
    border-color: #2F5D50;
    color: #2F5D50;
}
QPushButton#Danger {
    background: transparent;
    border: 1px solid #E3C4BE;
    color: #B3352B;
}
QPushButton#Danger:hover {
    background: #FBF0EE;
    border-color: #D9A9A1;
}
QPushButton#Play {
    background: #2F5D50;
    border: none;
    border-radius: 19px;
    color: #FFFFFF;
    font-size: 13px;
    min-width: 38px;
    max-width: 38px;
    min-height: 38px;
    max-height: 38px;
    padding: 0;
}
QPushButton#Play:hover {
    background: #254B40;
}
QPushButton#Small {
    padding: 4px 9px;
    font-size: 10px;
    font-family: Consolas, "Courier New", monospace;
}
QProgressBar {
    background: #E7DECC;
    border: none;
    border-radius: 4px;
    height: 8px;
    text-align: center;
}
QProgressBar::chunk {
    background: #2F5D50;
    border-radius: 4px;
}
QPlainTextEdit, QTextEdit {
    background: #F8F5EC;
    border: 1px solid #E1D6C1;
    border-radius: 8px;
    padding: 8px;
    selection-background-color: #DCE8E2;
}
QTextEdit#SentenceEdit {
    font-family: Georgia, "Times New Roman", serif;
    font-size: 17px;
    line-height: 150%;
}
QTableWidget {
    background: #FCFAF4;
    border: 1px solid #E1D6C1;
    border-radius: 9px;
    gridline-color: transparent;
    outline: none;
}
QTableWidget::item {
    border-bottom: 1px solid #F0E8D8;
    padding: 6px;
}
QTableWidget::item:selected {
    background: #E4EFE9;
    color: #1F241F;
}
QHeaderView::section {
    background: #F8F5EC;
    border: none;
    border-bottom: 1px solid #E1D6C1;
    color: #9A917F;
    font-size: 10px;
    padding: 6px;
}
QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: #D8CDB8;
    border-radius: 4px;
    min-height: 30px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar:horizontal {
    background: transparent;
    height: 10px;
    margin: 2px;
}
QScrollBar::handle:horizontal {
    background: #D8CDB8;
    border-radius: 4px;
    min-width: 30px;
}
QSlider::groove:horizontal {
    background: #E6DDCB;
    height: 4px;
    border-radius: 2px;
}
QSlider::sub-page:horizontal {
    background: #2F5D50;
    height: 4px;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background: #2F5D50;
    border: 2px solid #FFFFFF;
    width: 10px;
    height: 10px;
    margin: -5px 0;
    border-radius: 7px;
}
QCheckBox {
    color: #6E6657;
    font-size: 11px;
    spacing: 5px;
}
QCheckBox::indicator {
    width: 14px;
    height: 14px;
    border: 1px solid #D3C6AC;
    border-radius: 3px;
    background: #FCFAF4;
}
QCheckBox::indicator:checked {
    background: #2F5D50;
    border-color: #2F5D50;
}
QSplitter::handle {
    background: #E1D6C1;
    width: 1px;
}
QToolTip {
    background: #1F241F;
    color: #FCFAF4;
    border: none;
    padding: 5px 7px;
    font-size: 10px;
}
QMessageBox {
    background: #FCFAF4;
}
"""
