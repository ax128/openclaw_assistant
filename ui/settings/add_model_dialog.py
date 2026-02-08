"""
增加模型弹窗：表单/Raw 模式编辑模型配置；当前保存仅提示暂不支持。
"""
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QMessageBox,
)
from PyQt5.QtCore import Qt
from utils.i18n import t
from utils.platform_adapter import ui_font_family, ui_font_size_body, ui_window_bg


class AddModelDialog(QDialog):
    """增加模型：当前仅展示说明，保存时提示暂不支持。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("add_model_dialog_title"))
        self.setMinimumSize(360, 160)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        ff, fs, bg = ui_font_family(), ui_font_size_body(), ui_window_bg()
        self.setStyleSheet(
            "QDialog { font-family: '%s'; font-size: %dpx; background: %s; }"
            % (ff, fs, bg)
        )
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        hint = QLabel(t("add_model_hint"))
        hint.setWordWrap(True)
        layout.addWidget(hint)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        save_btn = QPushButton(t("save"))
        save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

    def _on_save(self):
        """暂不支持保存：仅提示。"""
        QMessageBox.information(
            self,
            t("tip_title"),
            t("add_model_save_not_supported"),
        )
