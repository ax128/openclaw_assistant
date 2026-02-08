"""
启动前连接页：输入服务器地址、端口、Token，连接成功后再进入主窗口。
默认：本地 127.0.0.1，端口 18789。
"""
import re
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QMessageBox, QFormLayout, QCheckBox, QFrame,
)
from PyQt5.QtCore import Qt, QTimer
from utils.logger import logger
from utils.i18n import t
from utils.platform_adapter import ui_font_family, ui_font_size_body, ui_window_bg
from core.openclaw_gateway import local_to_server as l2s
from core.openclaw_gateway.gateway_memory import gateway_memory
from utils.ssh_tunnel import start_ssh_tunnel


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 18789


def parse_ws_url(url: str) -> tuple[str, int]:
    """从 ws://host:port 或 wss://host:port 解析出 (host, port)。解析失败返回 (DEFAULT_HOST, DEFAULT_PORT)。"""
    url = (url or "").strip()
    if not url:
        return DEFAULT_HOST, DEFAULT_PORT
    m = re.match(r"^wss?://([^:/]+)(?::(\d+))?/?$", url, re.IGNORECASE)
    if m:
        host = m.group(1).strip() or DEFAULT_HOST
        port_str = m.group(2)
        port = int(port_str) if port_str else DEFAULT_PORT
        return host, port
    return DEFAULT_HOST, DEFAULT_PORT


def build_ws_url(host: str, port: int, use_ssl: bool = False) -> str:
    """根据 host、port 构建 WebSocket URL。"""
    host = (host or "").strip() or DEFAULT_HOST
    try:
        p = int(port) if port is not None else DEFAULT_PORT
    except (TypeError, ValueError):
        p = DEFAULT_PORT
    scheme = "wss" if use_ssl else "ws"
    return f"{scheme}://{host}:{p}"


class StartupDialog(QDialog):
    """启动前连接页：服务器地址、端口、Token，连接并启动。"""

    def __init__(self, settings, gateway_client, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.gateway_client = gateway_client
        self.setWindowTitle(t("startup_title"))
        try:
            from ui.ui_settings_loader import get_ui_setting
            geom = get_ui_setting("startup_dialog.geometry") or {}
            min_sz = get_ui_setting("startup_dialog.min_size") or {}
            self.setMinimumWidth(int(min_sz.get("width", 480)))
            self.setMinimumHeight(int(min_sz.get("height", 460)))
            self.resize(int(geom.get("width", 520)), int(geom.get("height", 480)))
            self._host_edit_min_w = int(get_ui_setting("startup_dialog.host_edit_min_width_px") or 280)
            self._port_edit_max_w = int(get_ui_setting("startup_dialog.port_edit_max_width_px") or 100)
            self._token_edit_min_w = int(get_ui_setting("startup_dialog.token_edit_min_width_px") or 280)
        except Exception:
            self.setMinimumWidth(480)
            self.setMinimumHeight(460)
            self.resize(520, 480)
            self._host_edit_min_w = 280
            self._port_edit_max_w = 100
            self._token_edit_min_w = 280
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        ff, fs, bg = ui_font_family(), ui_font_size_body(), ui_window_bg()
        self.setStyleSheet(f"QDialog {{ font-family: '{ff}'; font-size: {fs}px; background: {bg}; }}")

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self._host_edit = QLineEdit()
        self._host_edit.setPlaceholderText(t("startup_host_placeholder"))
        self._host_edit.setMinimumWidth(getattr(self, "_host_edit_min_w", 280))
        self._port_edit = QLineEdit()
        self._port_edit.setPlaceholderText(t("startup_port_placeholder"))
        self._port_edit.setMaximumWidth(getattr(self, "_port_edit_max_w", 100))
        self._token_edit = QLineEdit()
        self._token_edit.setPlaceholderText(t("gateway_token_placeholder"))
        self._token_edit.setEchoMode(QLineEdit.Password)
        self._token_edit.setMinimumWidth(getattr(self, "_token_edit_min_w", 280))

        form.addRow(t("startup_server_addr"), self._host_edit)
        form.addRow(t("startup_port"), self._port_edit)
        form.addRow(t("gateway_token_label"), self._token_edit)

        self._auto_login_cb = QCheckBox(t("gateway_auto_login"))
        self._auto_login_cb.setToolTip(t("gateway_auto_login_tooltip"))
        form.addRow("", self._auto_login_cb)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("QFrame { border: 1px dashed #d1d5db; max-height: 1px; }")

        form2 = QFormLayout()
        self._ssh_enabled_cb = QCheckBox("是否需要 SSH 远程链接")
        self._ssh_enabled_cb.setToolTip("勾选后，连接前先建立 SSH 隧道：ssh -N -L {端口}:127.0.0.1:{端口} 用户名@服务器")
        form2.addRow("", self._ssh_enabled_cb)
        self._ssh_user_edit = QLineEdit()
        self._ssh_user_edit.setPlaceholderText("必填（勾选 SSH 时）")
        self._ssh_user_edit.setMinimumWidth(280)
        form2.addRow("SSH 用户名：", self._ssh_user_edit)
        self._ssh_server_edit = QLineEdit()
        self._ssh_server_edit.setPlaceholderText("必填（勾选 SSH 时），默认可为 Gateway 服务器地址")
        self._ssh_server_edit.setMinimumWidth(280)
        form2.addRow("SSH 服务器地址：", self._ssh_server_edit)
        self._ssh_password_edit = QLineEdit()
        self._ssh_password_edit.setPlaceholderText("可选，不填则使用密钥或 ssh-agent")
        self._ssh_password_edit.setEchoMode(QLineEdit.Password)
        self._ssh_password_edit.setMinimumWidth(280)
        form2.addRow("SSH 密码：", self._ssh_password_edit)

        self._connect_btn = QPushButton(t("connect_and_start"))
        self._connect_btn.setDefault(True)
        self._connect_btn.clicked.connect(self._on_connect)
        self._cancel_btn = QPushButton(t("cancel_btn"))
        self._cancel_btn.clicked.connect(self.reject)

        layout.addLayout(form)
        layout.addWidget(QLabel(t("startup_default_hint")))
        layout.addWidget(sep)
        layout.addLayout(form2)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(self._connect_btn)
        btn_row.addWidget(self._cancel_btn)
        layout.addLayout(btn_row)

        # 从 config/gateway.json 加载上次保存的配置并填入表单
        self._fill_from_settings()
        # 若已勾选自动登录且已有地址，启动后尝试自动连接
        QTimer.singleShot(100, self._try_auto_login)

    def _fill_from_settings(self):
        """从 config/gateway.json（经 Settings 加载）预填：Gateway 与 SSH 相关。"""
        self.settings.load()
        url = (self.settings.get("gateway_ws_url") or "").strip() or build_ws_url(DEFAULT_HOST, DEFAULT_PORT)
        host, port = parse_ws_url(url)
        self._host_edit.setText(host)
        self._port_edit.setText(str(port))
        self._token_edit.setText((self.settings.get("gateway_token") or "").strip())
        self._auto_login_cb.setChecked(bool(self.settings.get("auto_login")))
        self._ssh_enabled_cb.setChecked(bool(self.settings.get("ssh_enabled")))
        ssh_user = (self.settings.get("ssh_username") or "").strip()
        ssh_server = (self.settings.get("ssh_server") or "").strip()
        self._ssh_user_edit.setText(ssh_user)
        self._ssh_server_edit.setText(ssh_server or host)
        self._ssh_password_edit.setText((self.settings.get("ssh_password") or "").strip())

    def _do_connect(self):
        """执行连接：若勾选 SSH 则先起隧道再连 Gateway；返回 (ok, err)。"""
        host = (self._host_edit.text() or "").strip() or DEFAULT_HOST
        port_str = (self._port_edit.text() or "").strip()
        try:
            port = int(port_str) if port_str else DEFAULT_PORT
        except ValueError:
            return False, "端口请输入数字"
        token = (self._token_edit.text() or "").strip()
        password = (self.settings.get("gateway_password") or "").strip()
        ssh_enabled = self._ssh_enabled_cb.isChecked()
        ssh_user = (self._ssh_user_edit.text() or "").strip()
        ssh_server = (self._ssh_server_edit.text() or "").strip()
        ssh_password = (self._ssh_password_edit.text() or "").strip()
        self.settings.load()
        self.settings.set("ssh_enabled", ssh_enabled)
        self.settings.set("ssh_username", ssh_user)
        self.settings.set("ssh_server", ssh_server)
        self.settings.set("ssh_password", ssh_password)
        self.settings.save()
        if ssh_enabled:
            if not ssh_user or not ssh_server:
                return False, "勾选 SSH 时，用户名与服务器地址必填"
            ok_tunnel, err_tunnel = start_ssh_tunnel(port, ssh_user, ssh_server, ssh_password or None)
            if not ok_tunnel:
                return False, err_tunnel or "SSH 隧道启动失败"
        ws_url = build_ws_url("127.0.0.1" if ssh_enabled else host, port)
        return self.gateway_client.connect(ws_url, token, password)

    def _try_auto_login(self):
        """若 gateway.json 中 auto_login 为 true 且已有地址，则自动连接；成功/失败均不修改 auto_login（仅用户显式勾选/保存时才改）。"""
        if not bool(self.settings.get("auto_login")):
            return
        url = (self.settings.get("gateway_ws_url") or "").strip()
        if not url:
            return
        self._connect_btn.setEnabled(False)
        self._connect_btn.setText(t("auto_login_connecting"))
        ok, err = self._do_connect()
        self._connect_btn.setEnabled(True)
        self._connect_btn.setText(t("connect_and_start"))
        if ok:
            logger.info(f"Gateway 自动登录成功")
            # 接通后拉取一次 config 并存内存，供会话列表等使用
            l2s.send_config_get(self.gateway_client, callback=lambda o, p, e: gateway_memory.set_config(o, p, e))
            self.close()
        else:
            # 不修改 auto_login，仅提示；用户可重试或到 Gateway 设置中取消勾选
            QMessageBox.warning(
                self,
                t("auto_login_failed"),
                err or t("connect_failed_msg"),
            )

    def _on_connect(self):
        """用户点击「连接并启动」：成功则保存并关闭窗口，失败则提示错误可重试。"""
        self._connect_btn.setEnabled(False)
        self._connect_btn.setText(t("connecting"))
        ok, err = self._do_connect()
        self._connect_btn.setEnabled(True)
        self._connect_btn.setText(t("connect_and_start"))

        if ok:
            ws_url = build_ws_url(
                (self._host_edit.text() or "").strip() or DEFAULT_HOST,
                int((self._port_edit.text() or "").strip() or DEFAULT_PORT),
            )
            token = (self._token_edit.text() or "").strip()
            password = (self.settings.get("gateway_password") or "").strip()
            self.settings.set("gateway_ws_url", ws_url)
            self.settings.set("gateway_token", token)
            if password:
                self.settings.set("gateway_password", password)
            # 仅在此处按用户勾选写入 auto_login（用户点击连接并成功时）
            self.settings.set("auto_login", self._auto_login_cb.isChecked())
            self.settings.save()
            logger.info(f"Gateway 已连接: {ws_url}，配置已保存")
            # 接通后拉取一次 config 并存内存，供会话列表等使用
            l2s.send_config_get(self.gateway_client, callback=lambda o, p, e: gateway_memory.set_config(o, p, e))
            self.close()
        else:
            # 不修改 auto_login，仅提示错误（用户可重试或到 Gateway 设置中修改勾选）
            msg = err or t("connect_failed_msg")
            QMessageBox.critical(self, t("connect_failed"), msg)
