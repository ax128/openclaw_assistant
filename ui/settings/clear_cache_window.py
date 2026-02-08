"""
清除缓存窗口 - 移除本地日志、Gateway 日志、远程日志
"""
from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QDialog, QVBoxLayout, QPushButton, QLabel, QMessageBox
from utils.logger import logger
from utils.i18n import t
from utils.async_runner import run_in_thread
from utils.platform_adapter import ui_font_family, ui_font_size_body, ui_window_bg


def _logs_dir():
    """项目 logs 目录（与 log_tail_window 一致：desktop_pet/logs）。"""
    return Path(__file__).resolve().parent.parent.parent / "logs"


def _clear_local_logs():
    """删除 logs 目录下主程序日志 assistant_*.log。"""
    log_dir = _logs_dir()
    if not log_dir.is_dir():
        return 0
    n = 0
    for p in log_dir.glob("assistant_*.log"):
        try:
            p.unlink()
            n += 1
        except OSError as e:
            logger.warning(f"删除本地日志失败 {p}: {e}")
    return n


def _clear_gateway_logs():
    """删除 logs 目录下 Gateway 日志 gateway.*.log。"""
    log_dir = _logs_dir()
    if not log_dir.is_dir():
        return 0
    n = 0
    for p in log_dir.glob("gateway.*.log"):
        try:
            p.unlink()
            n += 1
        except OSError as e:
            logger.warning(f"删除 Gateway 日志失败 {p}: {e}")
    return n


def _clear_remote_logs():
    """删除 logs 目录下远程订阅落盘日志 remote_gateway_*.log。"""
    log_dir = _logs_dir()
    if not log_dir.is_dir():
        return 0
    n = 0
    for p in log_dir.glob("remote_gateway_*.log"):
        try:
            p.unlink()
            n += 1
        except OSError as e:
            logger.warning(f"删除远程日志失败 {p}: {e}")
    return n


class ClearCacheWindow(QDialog):
    """清除缓存 - 移除本地日志 / Gateway 日志 / 远程日志"""

    def __init__(self, bot_id, assistant_window=None):
        super().__init__()
        self.bot_id = bot_id or "bot00001"
        self.assistant_window = assistant_window
        self.setWindowTitle(t("clear_cache_title"))
        self.setGeometry(400, 300, 380, 200)
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        ff, fs, bg = ui_font_family(), ui_font_size_body(), ui_window_bg()
        self.setStyleSheet(f"QDialog {{ font-family: '{ff}'; font-size: {fs}px; background: {bg}; }}")

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(t("clear_cache_prompt")))
        btn_local = QPushButton(t("remove_local_logs"))
        btn_local.setToolTip(t("remove_local_logs"))
        btn_local.clicked.connect(self._on_clear_local_logs)
        layout.addWidget(btn_local)
        btn_gateway = QPushButton(t("remove_gateway_logs"))
        btn_gateway.setToolTip(t("remove_gateway_logs"))
        btn_gateway.clicked.connect(self._on_clear_gateway_logs)
        layout.addWidget(btn_gateway)
        btn_remote = QPushButton(t("remove_remote_logs"))
        btn_remote.setToolTip(t("remove_remote_logs"))
        btn_remote.clicked.connect(self._on_clear_remote_logs)
        layout.addWidget(btn_remote)
        layout.addStretch()

    def _on_clear_local_logs(self):
        def worker():
            return _clear_local_logs()

        def done(n):
            QMessageBox.information(self, t("done_title"), t("clear_local_done_fmt") % n)

        def err(e):
            logger.exception(f"{e}")
            QMessageBox.warning(self, t("fail_title"), str(e))

        run_in_thread(worker, on_done=done, on_error=err)

    def _on_clear_remote_logs(self):
        def worker():
            return _clear_remote_logs()

        def done(n):
            QMessageBox.information(self, t("done_title"), t("clear_remote_done_fmt") % n)

        def err(e):
            logger.exception(f"{e}")
            QMessageBox.warning(self, t("fail_title"), str(e))

        run_in_thread(worker, on_done=done, on_error=err)

    def _on_clear_gateway_logs(self):
        def worker():
            return _clear_gateway_logs()

        def done(n):
            QMessageBox.information(self, t("done_title"), t("clear_gateway_done_fmt") % n)

        def err(e):
            logger.exception(f"{e}")
            QMessageBox.warning(self, t("fail_title"), str(e))

        run_in_thread(worker, on_done=done, on_error=err)
