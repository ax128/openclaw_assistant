"""
Gateway 设置独立页面。
入口：设置主窗口中的「Gateway 设置」按钮。
配置来源/保存：config/gateway.json（经 Settings 读写），含 gateway_ws_url、gateway_token、gateway_password、auto_login。
"""
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit,
    QPushButton, QCheckBox, QLabel, QGroupBox, QMessageBox,
)
from PyQt5.QtCore import Qt
from config.settings import Settings, GATEWAY_KEYS
from utils.logger import logger
from utils.i18n import t
from utils.platform_adapter import ui_font_family, ui_font_size_body, ui_window_bg, is_macos
from utils.ssh_tunnel import start_ssh_tunnel


def _card_style():
    return """
        QGroupBox {
            font-weight: 500;
            border: 1px solid #e5e7eb;
            border-radius: 10px;
            margin-top: 12px;
            padding: 16px 14px 10px 14px;
            background: #ffffff;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            subcontrol-position: top left;
            left: 14px;
            padding: 0 8px;
            background: transparent;
            color: #374151;
            font-size: 13px;
        }
    """


def _primary_btn():
    return """
        QPushButton {
            background: #2563eb;
            color: white;
            border: none;
            border-radius: 8px;
            padding: 10px 20px;
            font-weight: 500;
            min-height: 20px;
        }
        QPushButton:hover { background: #1d4ed8; }
        QPushButton:pressed { background: #1e40af; }
    """


def _secondary_btn():
    return """
        QPushButton {
            background: #f3f4f6;
            color: #374151;
            border: 1px solid #e5e7eb;
            border-radius: 8px;
            padding: 10px 20px;
            font-weight: 500;
            min-height: 20px;
        }
        QPushButton:hover { background: #e5e7eb; }
        QPushButton:pressed { background: #d1d5db; }
    """


class GatewaySettingsWindow(QMainWindow):
    """
    Gateway 设置独立页面。
    表单：Gateway 地址、Token、密码、是否自动登录（勾选 true，不勾选 false）。
    状态来源于 config/gateway.json（经 Settings 加载），保存时写回配置文件。
    """

    def __init__(self, parent=None, assistant_window=None, gateway_client=None):
        super().__init__(parent)
        self.assistant_window = assistant_window
        self.gateway_client = gateway_client if gateway_client is not None else getattr(assistant_window, "gateway_client", None)
        self.settings = Settings()
        self.setWindowTitle(t("gateway_settings_title"))
        self.setMinimumSize(420, 380)
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        if is_macos():
            self.setUnifiedTitleAndToolBarOnMac(True)
        ff, fs, bg = ui_font_family(), ui_font_size_body(), ui_window_bg()
        self.setStyleSheet(f"""
            QMainWindow {{
                font-family: '{ff}';
                font-size: {fs}px;
                background: {bg};
            }}
            {_card_style()}
            QLineEdit {{
                padding: 6px 10px;
                border: 1px solid #e5e7eb;
                border-radius: 6px;
                background: #fafafa;
                min-height: 20px;
            }}
        """)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        title_row = QHBoxLayout()
        title_row.setSpacing(12)
        title = QLabel(t("gateway_settings_title"))
        try:
            from ui.ui_settings_loader import get_ui_setting
            tt = get_ui_setting("gateway_settings_window.title") or {}
            title.setStyleSheet(
                "font-size: %dpx; font-weight: %d; color: %s;"
                % (int(tt.get("font_size_px", 18)), int(tt.get("font_weight", 600)), tt.get("color", "#111827"))
            )
        except Exception:
            title.setStyleSheet("font-size: 18px; font-weight: 600; color: #111827;")
        title_row.addWidget(title)
        title_row.addSpacing(16)
        self._status_dot = QLabel()
        self._status_dot.setFixedSize(12, 12)
        self._status_dot.setStyleSheet("background-color: #9ca3af; border-radius: 6px;")
        self._status_text = QLabel(t("gateway_offline"))
        try:
            from ui.ui_settings_loader import get_ui_setting
            st = get_ui_setting("gateway_settings_window.status_text") or {}
            self._status_text.setStyleSheet(
                "font-size: %dpx; color: %s;" % (int(st.get("font_size_px", 13)), st.get("color", "#6b7280"))
            )
        except Exception:
            self._status_text.setStyleSheet("font-size: 13px; color: #6b7280;")
        title_row.addWidget(self._status_dot)
        title_row.addWidget(self._status_text)
        title_row.addStretch()
        layout.addLayout(title_row)

        desc = QLabel(t("gateway_desc"))
        try:
            from ui.ui_settings_loader import get_ui_setting
            dc = get_ui_setting("gateway_settings_window.desc") or {}
            desc.setStyleSheet(
                "color: %s; font-size: %dpx; margin-bottom: 8px;" % (dc.get("color", "#6b7280"), int(dc.get("font_size_px", 12)))
            )
        except Exception:
            desc.setStyleSheet("color: #6b7280; font-size: 12px; margin-bottom: 8px;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        g = QGroupBox(t("gateway_connect_group"))
        g.setStyleSheet(_card_style())
        fl = QFormLayout(g)

        self._url_edit = QLineEdit()
        self._url_edit.setPlaceholderText(t("gateway_url_placeholder"))
        self._url_edit.setMinimumWidth(320)
        fl.addRow(t("gateway_url_label"), self._url_edit)

        self._token_edit = QLineEdit()
        self._token_edit.setPlaceholderText(t("gateway_token_placeholder"))
        self._token_edit.setEchoMode(QLineEdit.Password)
        fl.addRow(t("gateway_token_label"), self._token_edit)

        self._password_edit = QLineEdit()
        self._password_edit.setPlaceholderText(t("gateway_password_placeholder"))
        self._password_edit.setEchoMode(QLineEdit.Password)
        fl.addRow(t("gateway_password_label"), self._password_edit)

        self._auto_login_cb = QCheckBox(t("gateway_auto_login"))
        self._auto_login_cb.setToolTip(t("gateway_auto_login_tooltip"))
        fl.addRow("", self._auto_login_cb)

        layout.addWidget(g)

        btn_row = QVBoxLayout()
        self._btn_save = QPushButton(t("save"))
        self._btn_save.setCursor(Qt.PointingHandCursor)
        self._btn_save.setStyleSheet(_primary_btn())
        self._btn_save.clicked.connect(self._on_save)
        btn_row.addWidget(self._btn_save)

        self._btn_save_and_reconnect = QPushButton(t("save_and_reconnect"))
        self._btn_save_and_reconnect.setCursor(Qt.PointingHandCursor)
        self._btn_save_and_reconnect.setStyleSheet(_primary_btn())
        self._btn_save_and_reconnect.setToolTip(t("save_and_reconnect_tooltip"))
        self._btn_save_and_reconnect.clicked.connect(self._on_save_and_reconnect)
        btn_row.addWidget(self._btn_save_and_reconnect)

        self._btn_reconnect = QPushButton(t("reconnect_btn"))
        self._btn_reconnect.setCursor(Qt.PointingHandCursor)
        self._btn_reconnect.setStyleSheet(_secondary_btn())
        self._btn_reconnect.setToolTip(t("reconnect_tooltip"))
        self._btn_reconnect.clicked.connect(self._on_reconnect)
        btn_row.addWidget(self._btn_reconnect)

        layout.addLayout(btn_row)
        layout.addStretch()

        self._load_from_config()
        self._update_status_indicator()

    def showEvent(self, event):
        """窗口显示时刷新连接状态。"""
        super().showEvent(event)
        self._update_status_indicator()

    def _update_status_indicator(self):
        """根据 gateway_client.is_connected() 更新标题旁状态：绿点+在线 / 红点+不在线。"""
        connected = False
        if self.gateway_client and getattr(self.gateway_client, "is_connected", None) and callable(self.gateway_client.is_connected):
            connected = self.gateway_client.is_connected()
        if connected:
            self._status_dot.setStyleSheet("background-color: #22c55e; border-radius: 6px;")
            self._status_text.setText(t("gateway_online"))
            self._status_text.setStyleSheet("font-size: 13px; color: #16a34a;")
        else:
            self._status_dot.setStyleSheet("background-color: #ef4444; border-radius: 6px;")
            self._status_text.setText(t("gateway_offline"))
            self._status_text.setStyleSheet("font-size: 13px; color: #6b7280;")

    def _load_from_config(self):
        """从配置文件（经 Settings）加载并填入表单。"""
        self.settings.load()
        self._url_edit.setText(
            (self.settings.get("gateway_ws_url") or "").strip() or "ws://127.0.0.1:18789"
        )
        self._token_edit.setText((self.settings.get("gateway_token") or "").strip())
        self._password_edit.setText((self.settings.get("gateway_password") or "").strip())
        self._auto_login_cb.setChecked(bool(self.settings.get("auto_login")))

    def _collect_and_save(self):
        """收集表单值，写入 Settings 并保存到 config/gateway.json；成功时通过助手气泡框提醒。"""
        url = (self._url_edit.text() or "").strip() or "ws://127.0.0.1:18789"
        token = (self._token_edit.text() or "").strip()
        password = (self._password_edit.text() or "").strip()
        auto_login = self._auto_login_cb.isChecked()

        try:
            self.settings.load()
            self.settings.set("gateway_ws_url", url)
            self.settings.set("gateway_token", token)
            self.settings.set("gateway_password", password)
            self.settings.set("auto_login", auto_login)
            self.settings.save()
            logger.info(f"Gateway 设置已保存: url={url}, auto_login={auto_login}")
            if self.assistant_window and hasattr(self.assistant_window, "show_bubble_requested"):
                self.assistant_window.show_bubble_requested.emit(t("gateway_saved_ok"), 2)
            else:
                QMessageBox.information(self, t("gateway_saved_title"), t("gateway_saved_ok"))
        except OSError as e:
            logger.exception(f"Gateway 设置保存失败: {e}")
            QMessageBox.warning(self, t("save_failed"), t("gateway_save_failed") + "\n" + str(e))
        except Exception as e:
            logger.exception(f"Gateway 设置保存失败: {e}")
            QMessageBox.warning(self, t("save_failed"), t("gateway_save_failed") + "\n" + str(e))

    def _on_save(self):
        self._collect_and_save()

    def _on_save_and_reconnect(self):
        """先保存表单到配置，再使用保存后的配置重连。"""
        self._collect_and_save()
        self._do_reconnect()

    def _on_reconnect(self):
        """使用已保存的配置立即重连（不修改当前表单）；启动时点取消后可在设置里点此按钮连接。"""
        self._do_reconnect()

    def _do_reconnect(self):
        """从配置读取 url/token/password；若启用 SSH 则先起隧道再连 127.0.0.1:port；否则直接连。"""
        if not self.gateway_client:
            return
        self.settings.load()
        gc = self.gateway_client
        was_connected = getattr(gc, "is_connected", None) and callable(gc.is_connected) and gc.is_connected()
        if was_connected and hasattr(gc, "disconnect"):
            gc.disconnect(silent=True)
        url = (self.settings.get("gateway_ws_url") or "").strip()
        if not url:
            logger.info(f"Gateway 重连：未配置地址或连接不可用")
            return
        token = self.settings.get("gateway_token") or ""
        password = self.settings.get("gateway_password") or ""
        ssh_enabled = bool(self.settings.get("ssh_enabled"))
        connect_url = url
        if ssh_enabled:
            import re
            m = re.match(r"^wss?://[^:/]+(?::(\d+))?/?$", url, re.IGNORECASE)
            port = int(m.group(1)) if m and m.group(1) else 18789
            ssh_user = (self.settings.get("ssh_username") or "").strip()
            ssh_server = (self.settings.get("ssh_server") or "").strip()
            ssh_password = (self.settings.get("ssh_password") or "").strip()
            if not ssh_user or not ssh_server:
                logger.info(f"Gateway 重连：已勾选 SSH 但未配置用户名或服务器地址")
                return
            ok_tunnel, err_tunnel = start_ssh_tunnel(port, ssh_user, ssh_server, ssh_password or None)
            if not ok_tunnel:
                logger.info(f"Gateway 重连：SSH 隧道失败 - {err_tunnel}")
                return
            scheme = "wss" if url.lower().startswith("wss") else "ws"
            connect_url = f"{scheme}://127.0.0.1:{port}"
        if hasattr(gc, "connect"):
            ok, _ = gc.connect(connect_url, token, password)
            if ok and hasattr(self.assistant_window, "show_bubble_requested"):
                self.assistant_window.show_bubble_requested.emit(t("gateway_connected_ok"), 2)
            self._update_status_indicator()
            logger.info(f"Gateway 已触发重连")
        else:
            logger.info(f"Gateway 重连：未配置地址或连接不可用")
