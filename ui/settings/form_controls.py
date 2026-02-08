"""
设置内表单控件：禁用滚轮/上下键/加减钮，仅支持手动输入，避免误触改值。
供 settings_window、chat_settings 等复用。
"""
from PyQt5.QtWidgets import QSpinBox, QDoubleSpinBox, QComboBox
from PyQt5.QtCore import Qt


class ManualOnlySpinBox(QSpinBox):
    """仅支持手动输入数字，禁用上下键、滚轮、加减钮。"""

    def stepBy(self, steps):
        pass

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Up, Qt.Key_Down):
            e.ignore()
            return
        super().keyPressEvent(e)

    def wheelEvent(self, e):
        e.ignore()


class ManualOnlyDoubleSpinBox(QDoubleSpinBox):
    """仅支持手动输入数字，禁用上下键、滚轮、加减钮。"""

    def stepBy(self, steps):
        pass

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Up, Qt.Key_Down):
            e.ignore()
            return
        super().keyPressEvent(e)

    def wheelEvent(self, e):
        e.ignore()


class NoWheelComboBox(QComboBox):
    """禁用滚轮切换选项，避免误触。"""

    def wheelEvent(self, e):
        e.ignore()
