"""
Gateway 连接设置卡片（与 Web UI 的 gatewayUrl / token 对齐）
可在设置界面编辑并保存到 config/gateway.json；保存后可选重连。
"""
from PyQt5.QtWidgets import (
    QGroupBox, QVBoxLayout, QFormLayout, QLineEdit, QPushButton, QLabel,
)
from PyQt5.QtCore import Qt
from config.settings import Settings
from utils.logger import logger


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


def create_gateway_card(save_callback=None, reconnect_callback=None):
    """
    创建「Gateway 连接」设置卡片。
    save_callback(gateway_ws_url, token, password) 保存后调用（可选）；
    reconnect_callback() 保存后若需重连则调用（可选）。
    返回 (QGroupBox, get_values_func)。
    """
    settings = Settings()
    settings.load()

    g = QGroupBox("Gateway 连接")
    g.setStyleSheet(_card_style())

    layout = QVBoxLayout(g)
    desc = QLabel(
        "与 Web 版一致：填写 Gateway 地址（如 ws://127.0.0.1:18789）与认证信息。"
        "保存后生效；若需立即连接请点击「保存并重连」。"
    )
    desc.setStyleSheet("color: #6b7280; font-size: 12px; margin-bottom: 12px;")
    desc.setWordWrap(True)
    layout.addWidget(desc)

    fl = QFormLayout()
    url_edit = QLineEdit()
    url_edit.setPlaceholderText("ws://127.0.0.1:18789 或 wss://host:port")
    url_edit.setMinimumWidth(280)
    url_edit.setText((settings.get("gateway_ws_url") or "").strip() or "ws://127.0.0.1:18789")
    fl.addRow("Gateway 地址：", url_edit)

    token_edit = QLineEdit()
    token_edit.setPlaceholderText("可选，网关启用认证时必填")
    token_edit.setEchoMode(QLineEdit.Password)
    token_edit.setText((settings.get("gateway_token") or "").strip())
    fl.addRow("Token：", token_edit)

    password_edit = QLineEdit()
    password_edit.setPlaceholderText("可选，部分网关使用密码")
    password_edit.setEchoMode(QLineEdit.Password)
    password_edit.setText((settings.get("gateway_password") or "").strip())
    fl.addRow("密码：", password_edit)

    layout.addLayout(fl)

    def get_values():
        url = (url_edit.text() or "").strip() or "ws://127.0.0.1:18789"
        token = (token_edit.text() or "").strip()
        password = (password_edit.text() or "").strip()
        return url, token, password

    def on_save():
        url, token, password = get_values()
        settings.load()
        settings.set("gateway_ws_url", url)
        settings.set("gateway_token", token)
        settings.set("gateway_password", password)
        settings.save()
        logger.info(f"Gateway 设置已保存: {url}")
        if save_callback:
            save_callback(url, token, password)
        if reconnect_callback:
            reconnect_callback()

    btn_row = QVBoxLayout()
    btn_save = QPushButton("保存")
    btn_save.setCursor(Qt.PointingHandCursor)
    btn_save.setStyleSheet(_primary_btn())
    btn_save.clicked.connect(on_save)
    btn_row.addWidget(btn_save)
    if reconnect_callback:
        btn_reconnect = QPushButton("保存并重连")
        btn_reconnect.setCursor(Qt.PointingHandCursor)
        btn_reconnect.setStyleSheet(_primary_btn())
        def on_save_and_reconnect():
            on_save()
            reconnect_callback()
        btn_reconnect.clicked.connect(on_save_and_reconnect)
        btn_row.addWidget(btn_reconnect)
    layout.addLayout(btn_row)

    return g, get_values
