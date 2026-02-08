"""
日志 tail 窗口 - 实时显示主程序日志、本地 Gateway 日志、远程 Gateway 日志（logs.tail）
"""
import os
from datetime import datetime
from pathlib import Path

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton,
    QLabel, QComboBox, QWidget,
)
from PyQt5.QtGui import QFont

from utils.logger import logger
from utils.i18n import t
from utils.platform_adapter import ui_font_family, ui_font_size_body, ui_window_bg
from core.openclaw_gateway.protocol import METHOD_LOGS_TAIL

# 远程日志：Gateway logs.tail 参数（与服务端默认一致）
REMOTE_LOG_LIMIT = 500
REMOTE_LOG_MAX_BYTES = 250000
REMOTE_LOG_POLL_MS = 2000


def _today_str():
    return datetime.now().strftime("%Y%m%d")


def _main_log_dir():
    """主程序日志目录：与 utils/logger 一致，为 cwd 下的 logs。"""
    return Path.cwd() / "logs"


def _gateway_log_dir():
    """Gateway 日志目录：与 utils/logger 一致，为项目根下的 logs。"""
    return Path(__file__).resolve().parent.parent.parent / "logs"


def _main_log_path():
    """主程序日志路径，与 utils/logger 一致：assistant_YYYYMMDD.log"""
    return _main_log_dir() / ("assistant_%s.log" % _today_str())


def _gateway_log_path():
    return _gateway_log_dir() / ("gateway.%s.log" % _today_str())


def _remote_log_path():
    """远程订阅落盘路径：logs/remote_gateway_YYYYMMDD.log，与清除缓存一致。"""
    d = _gateway_log_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d / ("remote_gateway_%s.log" % _today_str())


class LogTailWindow(QDialog):
    """实时显示日志文件内容（tail），支持切换主日志 / Gateway 日志。"""

    def __init__(self, parent=None, gateway_client=None):
        super().__init__(parent)
        self._gateway_client_param = gateway_client
        self.setWindowTitle(t("log_tail_title"))
        try:
            from ui.ui_settings_loader import get_ui_setting, save_ui_settings_geometry
            geom = get_ui_setting("log_tail_window.geometry") or {}
            self.setGeometry(
                int(geom.get("x", 200)),
                int(geom.get("y", 150)),
                int(geom.get("width", 800)),
                int(geom.get("height", 500)),
            )
            self._geometry_save_timer = None
        except Exception:
            self.setGeometry(200, 150, 800, 500)
            self._geometry_save_timer = None
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        ff, fs, bg = ui_font_family(), ui_font_size_body(), ui_window_bg()
        self.setStyleSheet(
            f"QDialog {{ font-family: '{ff}'; font-size: {fs}px; background: {bg}; }} "
            "QTextEdit { background: #1e1e1e; color: #d4d4d4; border: 1px solid #333; }"
        )

        self._current_path = None
        self._last_size = 0
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll)
        self._remote_mode = False
        self._remote_cursor = None
        self._remote_timer = QTimer(self)
        self._remote_timer.setSingleShot(False)
        self._remote_timer.timeout.connect(self._poll_remote)
        self._remote_pending = False

        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        row.addWidget(QLabel(t("log_source_label")))
        self._combo = QComboBox()
        self._combo.addItem(t("log_main"), str(_main_log_path()))
        self._combo.addItem(t("log_gateway_local"), str(_gateway_log_path()))
        self._combo.addItem(t("log_gateway_remote"), "remote")
        self._combo.currentIndexChanged.connect(self._on_log_switch)
        row.addWidget(self._combo)
        self._path_label = QLabel("")
        try:
            from ui.ui_settings_loader import get_ui_setting
            pl = get_ui_setting("log_tail_window.path_label") or {}
            self._path_label.setStyleSheet(
                "color: %s; font-size: %dpx;" % (pl.get("color", "#6b7280"), int(pl.get("font_size_px", 11)))
            )
        except Exception:
            self._path_label.setStyleSheet("color: #6b7280; font-size: 11px;")
        row.addWidget(self._path_label)
        row.addStretch()
        layout.addLayout(row)

        self._text = QTextEdit()
        self._text.setReadOnly(True)
        self._text.setFont(QFont("Consolas" if os.name == "nt" else "Monaco", 10))
        layout.addWidget(self._text)

        btn_row = QHBoxLayout()
        self._btn_pause = QPushButton(t("pause_btn"))
        self._btn_pause.setCheckable(True)
        self._btn_pause.toggled.connect(self._on_pause_toggled)
        btn_row.addWidget(self._btn_pause)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self._on_log_switch()
        self._poll_timer.start(1000)

    def _current_data(self):
        """当前选项：文件路径字符串或 'remote'。"""
        idx = self._combo.currentIndex()
        if idx < 0:
            return None
        return self._combo.itemData(idx)

    def _gateway_client(self):
        """优先使用构造时传入的 gateway_client，否则从父窗口（设置窗口）获取。"""
        if self._gateway_client_param is not None:
            return self._gateway_client_param
        parent = self.parent()
        if parent is None:
            return None
        assistant_window = getattr(parent, "assistant_window", None)
        if assistant_window is None:
            return None
        return getattr(assistant_window, "gateway_client", None)

    def _schedule_save_geometry(self):
        if getattr(self, "_geometry_save_timer", None):
            self._geometry_save_timer.stop()
        self._geometry_save_timer = QTimer(self)
        self._geometry_save_timer.setSingleShot(True)
        self._geometry_save_timer.timeout.connect(self._save_geometry)
        self._geometry_save_timer.start(400)

    def _save_geometry(self):
        try:
            from ui.ui_settings_loader import save_ui_settings_geometry
            g = self.geometry()
            save_ui_settings_geometry("log_tail_window", g.x(), g.y(), g.width(), g.height())
        except Exception:
            pass

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._schedule_save_geometry()

    def moveEvent(self, event):
        super().moveEvent(event)
        self._schedule_save_geometry()

    def _on_log_switch(self):
        data = self._current_data()
        if data is None:
            return
        if data == "remote":
            self._remote_mode = True
            self._remote_cursor = None
            # 远程：落盘到 logs/remote_gateway_YYYYMMDD.log，tail 从本地文件读取
            self._current_path = _remote_log_path()
            if not self._current_path.parent.is_dir():
                self._current_path.parent.mkdir(parents=True, exist_ok=True)
            if not self._current_path.exists():
                try:
                    self._current_path.touch()
                except OSError:
                    pass
            self._path_label.setText(t("log_remote_saved_fmt") % self._current_path.name)
            self._last_size = 0
            gc = self._gateway_client()
            if not gc or not gc.is_connected():
                self._text.setPlainText("[ 未连接 Gateway，请先在设置中连接；连接后选择本项即开始订阅并落盘 ]")
            else:
                self._load_initial()
                if not self._btn_pause.isChecked():
                    self._poll_timer.start(1000)
                    self._remote_timer.start(REMOTE_LOG_POLL_MS)
        else:
            self._remote_mode = False
            self._remote_timer.stop()
            self._remote_cursor = None
            self._current_path = Path(data) if isinstance(data, str) else None
            self._path_label.setText(str(self._current_path or ""))
            self._last_size = 0
            self._load_initial()
            if not self._btn_pause.isChecked():
                self._poll_timer.start(1000)

    def _on_pause_toggled(self, checked):
        if checked:
            self._poll_timer.stop()
            self._remote_timer.stop()
        else:
            if self._remote_mode:
                self._poll_timer.start(1000)
                self._remote_timer.start(REMOTE_LOG_POLL_MS)
            else:
                self._poll_timer.start(1000)

    def _on_remote_logs_result(self, ok, payload, error):
        """logs.tail 回调（主线程）：将收到的行追加到本地文件，tail 由 _poll 从文件读取。"""
        if not self._remote_mode:
            return
        self._remote_pending = False
        if not ok:
            logger.warning(f"远程日志订阅失败: {(error or {}).get('message', '') if isinstance(error, dict) else str(error)}")
            return
        if not isinstance(payload, dict):
            return
        lines = payload.get("lines")
        if not isinstance(lines, list):
            return
        path = self._current_path
        if not path:
            return
        try:
            with open(path, "a", encoding="utf-8") as f:
                for line in lines:
                    if line is not None:
                        f.write(str(line).rstrip("\n") + "\n")
        except OSError as e:
            logger.warning(f"写入远程日志文件失败: {e}")
        if isinstance(payload.get("cursor"), (int, float)):
            self._remote_cursor = int(payload["cursor"])

    def _poll_remote(self):
        """定时拉取远程日志（cursor 续传），结果追加到本地文件。"""
        if self._remote_pending or not self._remote_mode or self._btn_pause.isChecked():
            return
        gc = self._gateway_client()
        if not gc or not gc.is_connected():
            return
        self._remote_pending = True
        params = {"limit": REMOTE_LOG_LIMIT, "maxBytes": REMOTE_LOG_MAX_BYTES}
        if self._remote_cursor is not None:
            params["cursor"] = self._remote_cursor
        gc.call(METHOD_LOGS_TAIL, params, callback=self._on_remote_logs_result)

    def _load_initial(self):
        """首次打开或切换文件时：读取末尾约 50KB 内容。"""
        path = self._current_path
        if not path or not path.exists():
            self._text.setPlainText("[ 文件不存在: %s ]" % path)
            self._last_size = 0
            return
        try:
            size = path.stat().st_size
            self._last_size = size
            want = min(50 * 1024, size)
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                if want < size:
                    f.seek(size - want)
                    f.readline()
                text = f.read()
            self._text.setPlainText(text)
            self._text.moveCursor(self._text.textCursor().End)
        except Exception as e:
            logger.debug(f"log tail 读取失败: {e}")
            self._text.setPlainText("[ 读取失败: %s ]" % e)

    def _poll(self):
        """定时追加新内容。"""
        if self._btn_pause.isChecked():
            return
        path = self._current_path
        if not path or not path.exists():
            return
        try:
            size = path.stat().st_size
            if size < self._last_size:
                self._last_size = 0
            if size <= self._last_size:
                return
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                f.seek(self._last_size)
                new_text = f.read()
            self._last_size = size
            if new_text:
                cursor = self._text.textCursor()
                cursor.movePosition(cursor.End)
                self._text.setTextCursor(cursor)
                self._text.insertPlainText(new_text)
                self._text.moveCursor(self._text.textCursor().End)
        except Exception as e:
            logger.debug(f"log tail 轮询失败: {e}")

    def closeEvent(self, event):
        """关闭窗口时停止本地与远程日志轮询，停止日志订阅。"""
        self._poll_timer.stop()
        self._remote_timer.stop()
        super().closeEvent(event)
