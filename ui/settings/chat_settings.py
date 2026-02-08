"""
聊天相关设置卡片：文字大小（作用于聊天与会话列表）、弹窗大小（斜杠补全等）。
"""
from PyQt5.QtWidgets import QGroupBox, QVBoxLayout, QFormLayout, QLabel
from config.settings import Settings
from ui.settings.form_controls import ManualOnlySpinBox, NoWheelComboBox
from ui.ui_settings_loader import get_ui_setting
from utils.i18n import t

# 弹窗大小：存储值 small/medium/large，界面显示由 t("popup_small") 等提供
POPUP_SIZE_VALUES = ("small", "medium", "large")


def _card_style():
    c = get_ui_setting("settings_window.card") or {}
    return """
        QGroupBox {
            font-weight: 500;
            border: %s;
            border-radius: %dpx;
            margin-top: %dpx;
            padding: %s;
            background: #ffffff;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            subcontrol-position: top left;
            left: 14px;
            padding: 0 8px;
            background: transparent;
            color: %s;
            font-size: %dpx;
        }
    """ % (
        c.get("border", "1px solid #e5e7eb"),
        int(c.get("border_radius_px", 10)),
        int(c.get("margin_top_px", 12)),
        c.get("padding", "16px 14px 10px 14px"),
        c.get("title_color", "#374151"),
        int(c.get("title_font_size_px", 13)),
    )


def create_chat_card():
    """
    创建「聊天」设置卡片（仅文字大小）。
    返回 (QGroupBox, get_values_func)。
    """
    settings = Settings()
    settings.load()

    g = QGroupBox(t("chat_card"))
    g.setStyleSheet(_card_style())
    layout = QVBoxLayout(g)
    desc = QLabel(t("chat_font_desc"))
    desc_style = get_ui_setting("settings_window.desc") or {}
    desc.setStyleSheet(
        "color: %s; font-size: %dpx; margin-bottom: 12px;"
        % (desc_style.get("color", "#6b7280"), int(desc_style.get("font_size_px", 12)))
    )
    desc.setWordWrap(True)
    layout.addWidget(desc)

    fl = QFormLayout()
    chat_font_pt = ManualOnlySpinBox()
    chat_min = int(get_ui_setting("font.chat.min_pt") or 10)
    chat_max = int(get_ui_setting("font.chat.max_pt") or 28)
    chat_font_pt.setMinimum(chat_min)
    chat_font_pt.setMaximum(chat_max)
    chat_font_pt.setValue(int(settings.get("chat_font_pt") or get_ui_setting("font.chat.default_pt") or 15))
    chat_font_pt.setSuffix(t("pt_suffix"))
    chat_font_pt.setToolTip(t("chat_font_tooltip"))
    fl.addRow(t("font_size_label"), chat_font_pt)

    popup_size_combo = NoWheelComboBox()
    popup_size_combo.addItems([t("popup_small"), t("popup_medium"), t("popup_large")])
    popup_size_val = (settings.get("popup_size") or get_ui_setting("chat_window_popup.default_size") or "small").strip().lower()
    try:
        idx = POPUP_SIZE_VALUES.index(popup_size_val)
    except ValueError:
        idx = 0
    popup_size_combo.setCurrentIndex(max(0, min(idx, 2)))
    popup_size_combo.setToolTip(t("popup_size_tooltip"))
    fl.addRow(t("popup_size_label"), popup_size_combo)
    layout.addLayout(fl)

    def get_values():
        return {
            "chat_font_pt": chat_font_pt.value(),
            "popup_size": POPUP_SIZE_VALUES[popup_size_combo.currentIndex()],
        }

    return g, get_values
