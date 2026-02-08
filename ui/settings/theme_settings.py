"""
主题设置卡片（与 Web UI 的 theme: system / dark / light 对齐）
"""
from PyQt5.QtWidgets import QGroupBox, QVBoxLayout, QFormLayout, QComboBox, QLabel
from config.settings import Settings
from utils.i18n import t


def _theme_options():
    return [(t("theme_follow_system"), "system"), (t("theme_light"), "light"), (t("theme_dark"), "dark")]


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


def create_theme_card():
    """
    创建「主题」设置卡片。
    返回 (QGroupBox, get_theme_func, set_theme_func)。
    """
    settings = Settings()
    settings.load()

    g = QGroupBox(t("theme_card"))
    g.setStyleSheet(_card_style())
    layout = QVBoxLayout(g)
    desc = QLabel(t("theme_desc"))
    desc.setStyleSheet("color: #6b7280; font-size: 12px; margin-bottom: 12px;")
    desc.setWordWrap(True)
    layout.addWidget(desc)

    fl = QFormLayout()
    combo = QComboBox()
    for label, value in _theme_options():
        combo.addItem(label, value)
    current = (settings.get("theme") or "system").strip().lower()
    if current not in ("system", "light", "dark"):
        current = "system"
    idx = next((i for i in range(combo.count()) if combo.itemData(i) == current), 0)
    combo.setCurrentIndex(idx)
    combo.setToolTip(t("theme_tooltip"))
    fl.addRow(t("theme_label"), combo)
    layout.addLayout(fl)

    def get_theme():
        return combo.itemData(combo.currentIndex()) or "system"

    def set_theme(value):
        value = (value or "system").strip().lower()
        if value not in ("system", "light", "dark"):
            value = "system"
        idx = next((i for i in range(combo.count()) if combo.itemData(i) == value), 0)
        combo.setCurrentIndex(idx)

    return g, get_theme, set_theme
