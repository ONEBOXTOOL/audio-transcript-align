# -*- coding: utf-8 -*-
"""AudioAlign 桌面入口。"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .icon import icon_pixmap
from .pages import DonePage, HomePage, ReviewPage, RunPage
from .pipeline import model_ready
from .theme import APP_QSS
from .worker import AlignWorker


def find_model_path() -> Path | None:
    roots: list[Path] = []
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        roots.append(exe_dir)
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            roots.append(Path(meipass))
    roots.append(Path(__file__).resolve().parents[1])
    for root in roots:
        for p in (root / "models" / "small.en", root / "models"):
            if model_ready(p):
                return p
    return None


class TopBar(QWidget):
    backClicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("TopBar")
        self.setFixedHeight(54)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(18, 0, 18, 0)
        lay.setSpacing(9)

        mark = QLabel("AA")
        mark.setObjectName("BrandMark")
        mark.setAlignment(Qt.AlignCenter)
        name = QLabel("AUDIO ALIGN")
        name.setObjectName("BrandName")
        sep = QLabel("/")
        sep.setStyleSheet("color:#9A917F;")
        self.context = QLabel("本地校对工具")
        self.context.setObjectName("TopContext")
        self.back = QPushButton("← 返回")
        self.back.setObjectName("Ghost")
        self.back.clicked.connect(self.backClicked)
        self.back.setVisible(False)
        self.model = QLabel("Whisper small.en（离线）")
        self.model.setObjectName("ChipOk")

        lay.addWidget(mark)
        lay.addWidget(name)
        lay.addWidget(sep)
        lay.addWidget(self.back)
        lay.addWidget(self.context)
        lay.addStretch(1)
        lay.addWidget(QLabel("音频不上传"))
        lay.addWidget(self.model)

    def set_context(self, text: str, back: bool = False):
        self.context.setText(text)
        self.back.setVisible(back)

    def set_model(self, path: Path | None):
        if model_ready(path):
            self.model.setText("Whisper small.en（离线）")
            self.model.setObjectName("ChipOk")
        else:
            self.model.setText("缺少模型")
            self.model.setObjectName("Chip")
        self.model.style().unpolish(self.model)
        self.model.style().polish(self.model)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AudioAlign · 音频文稿对齐")
        self.resize(1200, 800)
        self.setMinimumSize(1040, 700)

        self.model_path = find_model_path()
        self.worker: AlignWorker | None = None
        self.result: dict | None = None

        self.top = TopBar()
        self.top.set_model(self.model_path)
        self.top.backClicked.connect(self._go_back)

        self.home = HomePage(self.model_path)
        self.run_page = RunPage()
        self.done = DonePage()
        self.review = ReviewPage()

        self.stack = QStackedWidget()
        for w in (self.home, self.run_page, self.done, self.review):
            self.stack.addWidget(w)

        root = QWidget()
        root.setObjectName("Root")
        lay = QVBoxLayout(root)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.top)
        lay.addWidget(self.stack, 1)
        self.setCentralWidget(root)

        self.home.startRequested.connect(self.start_job)
        self.run_page.cancelRequested.connect(self.cancel_job)
        self.done.reviewRequested.connect(self.show_review)
        self.done.openFolderRequested.connect(self.open_output)
        self.done.againRequested.connect(self.show_home)

        self._show(self.home, "本地校对工具")

    def _show(self, page: QWidget, context: str, back: bool = False):
        self.stack.setCurrentWidget(page)
        self.top.set_context(context, back)

    def show_home(self):
        self._show(self.home, "本地校对工具")
        self.top.set_model(self.model_path)

    def show_review(self):
        if not self.result:
            return
        self.review.load(self.result)
        self._show(self.review, "校对", back=True)

    def _go_back(self):
        if self.stack.currentWidget() is self.review and self.result:
            self.done.set_result(self.result)
            self._show(self.done, "对齐结果")
        else:
            self.show_home()

    def start_job(self, job: dict):
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, "正在运行", "当前任务还没结束。")
            return
        if not self.model_path:
            QMessageBox.critical(self, "缺少模型", "找不到 models/small.en，无法开始。")
            return
        self.run_page.begin()
        self._show(self.run_page, "正在对齐…")
        self.worker = AlignWorker(
            job["audio"], job["transcript"], job["out_dir"], self.model_path,
            language="en", parent=self,
        )
        self.worker.progress.connect(self.run_page.set_progress)
        self.worker.logLine.connect(self.run_page.append_log)
        self.worker.finishedOk.connect(self._job_done)
        self.worker.failed.connect(self._job_failed)
        self.worker.cancelled.connect(self._job_cancelled)
        self.worker.finished.connect(self._worker_finished)
        self.worker.start()

    def _job_done(self, result: dict):
        self.result = result
        self.run_page.finish()
        self.done.set_result(result)
        self._show(self.done, "对齐结果")

    def _job_failed(self, msg: str):
        self.run_page.finish()
        self._show(self.home, "本地校对工具")
        QMessageBox.critical(self, "对齐失败", msg or "未知错误")

    def _job_cancelled(self):
        self.run_page.finish()
        self._show(self.home, "本地校对工具")

    def _worker_finished(self):
        if self.worker:
            self.worker.deleteLater()
            self.worker = None

    def cancel_job(self):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()

    def open_output(self):
        if self.result:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.result["out_dir"])))


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    if "--run" in argv:
        i = argv.index("--run")
        if i + 3 >= len(argv):
            print("用法: AudioAlign --run <audio> <transcript> <out_dir>", file=sys.stderr)
            return 2
        from .pipeline import run_alignment
        model = find_model_path()
        if not model:
            print("找不到 models/small.en", file=sys.stderr)
            return 2
        res = run_alignment(Path(argv[i + 1]), Path(argv[i + 2]), Path(argv[i + 3]),
                            model_path=model, language="en")
        print(res["json_path"])
        return 0

    smoke = None
    if "--smoke-test" in argv:
        i = argv.index("--smoke-test")
        if i + 1 < len(argv):
            smoke = argv[i + 1]
            del argv[i:i + 2]
    app = QApplication(argv)
    app.setApplicationName("AudioAlign")
    app.setOrganizationName("AudioAlign")
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 9))
    app.setStyleSheet(APP_QSS)
    app.setWindowIcon(QIcon(icon_pixmap()))
    win = MainWindow()
    win.show()
    if smoke:
        def _shot():
            Path(smoke).parent.mkdir(parents=True, exist_ok=True)
            win.grab().save(smoke)
            app.quit()
        QTimer.singleShot(1200, _shot)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
