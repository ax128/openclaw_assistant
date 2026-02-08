"""
编辑助手弹窗：选择助手后修改资料（名称、介绍、表情图集）或删除助手。bot_id 不可改；删除后 ID 空缺不补。
"""
import json
import os
import re
import shutil

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QLineEdit, QLabel, QTextEdit, QPushButton, QMessageBox, QComboBox,
    QFileDialog,
)
from PyQt5.QtCore import Qt

from utils.logger import logger
from utils.i18n import t
from utils.platform_adapter import ui_font_family, ui_font_size_body, ui_window_bg
from core.assistant_data import DEFAULT_STATE_TO_SPRITE_FOLDER
from ui.ui_settings_loader import get_ui_setting
from ui.settings.add_assistant_dialog import (
    SPRITE_STATE_KEYS,
    _validate_english_first_no_chinese,
    _validate_sprite_files,
    _secondary_btn,
    _primary_btn,
)


def _list_assistant_folders(assistants_dir: str) -> list:
    """返回包含 data.json 的助手文件夹名列表。"""
    if not os.path.isdir(assistants_dir):
        return []
    out = []
    for name in os.listdir(assistants_dir):
        if name.startswith(".") or name == "next_bot_seq.json":
            continue
        path = os.path.join(assistants_dir, name)
        if os.path.isdir(path) and os.path.isfile(os.path.join(path, "data.json")):
            out.append(name)
    return sorted(out)


class EditAssistantDialog(QDialog):
    """编辑助手：选择助手 -> 修改名称/介绍/表情图集 或 删除。"""

    def __init__(self, assistants_dir: str, parent=None):
        super().__init__(parent)
        self.assistants_dir = os.path.normpath(assistants_dir)
        self._state_files = {}
        self._current_folder = None
        self.setWindowTitle(t("edit_assistant_title"))
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        ff, fs, bg = ui_font_family(), ui_font_size_body(), ui_window_bg()
        self.setStyleSheet(f"""
            QDialog {{ font-family: '{ff}'; font-size: {fs}px; background: {bg}; }}
            QLineEdit, QTextEdit {{
                padding: 6px 10px;
                border: 1px solid #e5e7eb;
                border-radius: 6px;
                background: #fafafa;
            }}
        """)
        self.setMinimumWidth(480)
        self.setMinimumHeight(560)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        form = QFormLayout()
        self.assistant_combo = QComboBox()
        self.assistant_combo.setMinimumWidth(200)
        folders = _list_assistant_folders(self.assistants_dir)
        for f in folders:
            self.assistant_combo.addItem(f, f)
        self.assistant_combo.currentIndexChanged.connect(self._on_assistant_selected)
        form.addRow(t("edit_assistant_select_label"), self.assistant_combo)

        self.folder_label = QLabel("")
        self.folder_label.setStyleSheet("color: #6b7280;")
        form.addRow(t("edit_assistant_folder_readonly"), self.folder_label)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText(t("add_assistant_name_placeholder"))
        self.name_edit.setToolTip(t("add_assistant_folder_tooltip"))
        form.addRow(t("add_assistant_name_label"), self.name_edit)

        self.bot_id_label = QLabel("")
        self.bot_id_label.setStyleSheet("color: #6b7280;")
        form.addRow(t("add_assistant_bot_id_label"), self.bot_id_label)

        self.desc_edit = QTextEdit()
        self.desc_edit.setPlaceholderText(t("add_assistant_description_placeholder"))
        self.desc_edit.setMaximumHeight(80)
        form.addRow(t("add_assistant_description_label"), self.desc_edit)

        layout.addLayout(form)

        g_sprites = QGroupBox(t("add_assistant_sprites_card"))
        sprites_layout = QVBoxLayout(g_sprites)
        hint = QLabel(t("add_assistant_sprites_hint"))
        hint.setStyleSheet("color: #6b7280; font-size: 12px;")
        hint.setWordWrap(True)
        sprites_layout.addWidget(hint)

        self._sprite_buttons = {}
        self._sprite_labels = {}
        for state_key, i18n_key in SPRITE_STATE_KEYS:
            row = QHBoxLayout()
            folder_name = DEFAULT_STATE_TO_SPRITE_FOLDER.get(state_key, state_key)
            lbl = QLabel(t(i18n_key) + " (" + folder_name + "):")
            lbl.setMinimumWidth(120)
            row.addWidget(lbl)
            btn = QPushButton(t("add_assistant_select_images"))
            btn.setStyleSheet(_secondary_btn())
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda checked=False, s=state_key: self._on_select_sprites(s))
            row.addWidget(btn)
            count_lbl = QLabel(t("add_assistant_selected_fmt") % 0)
            count_lbl.setStyleSheet("color: #6b7280;")
            row.addWidget(count_lbl)
            row.addStretch()
            sprites_layout.addLayout(row)
            self._sprite_buttons[state_key] = btn
            self._sprite_labels[state_key] = count_lbl
            self._state_files[state_key] = []

        layout.addWidget(g_sprites)

        btns = QHBoxLayout()
        self.delete_btn = QPushButton(t("edit_assistant_delete"))
        self.delete_btn.setStyleSheet("QPushButton { background: #dc2626; color: white; border: none; border-radius: 8px; padding: 10px 16px; } QPushButton:hover { background: #b91c1c; }")
        self.delete_btn.setCursor(Qt.PointingHandCursor)
        self.delete_btn.clicked.connect(self._on_delete)
        btns.addWidget(self.delete_btn)
        btns.addStretch()
        cancel_btn = QPushButton(t("cancel_btn"))
        cancel_btn.setStyleSheet(_secondary_btn())
        cancel_btn.setCursor(Qt.PointingHandCursor)
        cancel_btn.clicked.connect(self.reject)
        self.save_btn = QPushButton(t("edit_assistant_save"))
        self.save_btn.setStyleSheet(_primary_btn())
        self.save_btn.setCursor(Qt.PointingHandCursor)
        self.save_btn.clicked.connect(self._on_save)
        btns.addWidget(cancel_btn)
        btns.addWidget(self.save_btn)
        layout.addLayout(btns)

        if self.assistant_combo.count() > 0:
            self.assistant_combo.setCurrentIndex(0)
            self._on_assistant_selected()
        else:
            self.folder_label.setText("")
            self.save_btn.setEnabled(False)
            self.delete_btn.setEnabled(False)

    def _on_assistant_selected(self):
        idx = self.assistant_combo.currentIndex()
        if idx < 0:
            self._current_folder = None
            return
        self._current_folder = self.assistant_combo.currentData()
        if not self._current_folder:
            return
        data_path = os.path.join(self.assistants_dir, self._current_folder, "data.json")
        if not os.path.isfile(data_path):
            return
        try:
            with open(data_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.exception(f"加载助手数据失败: {e}")
            return
        self.folder_label.setText(self._current_folder)
        self.name_edit.setText((data.get("name") or "").strip())
        self.bot_id_label.setText((data.get("bot_id") or "").strip())
        cfg = data.get("config") or {}
        self.desc_edit.setPlainText((cfg.get("description") or data.get("description") or "").strip())
        for state_key in self._state_files:
            self._state_files[state_key] = []
            self._sprite_labels[state_key].setText(t("add_assistant_selected_fmt") % 0)

    def _on_select_sprites(self, state_key: str):
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            t("add_assistant_select_images") + " - " + DEFAULT_STATE_TO_SPRITE_FOLDER.get(state_key, state_key),
            "",
            "PNG (*.png)",
        )
        if not paths:
            return
        ok, err = _validate_sprite_files(paths)
        if not ok:
            QMessageBox.warning(self, t("tip_title"), err)
            return
        numbers = []
        for p in paths:
            base = os.path.basename(p)
            num = int(re.match(r"^(\d+)", base).group(1))
            numbers.append((num, p))
        numbers.sort(key=lambda x: x[0])
        self._state_files[state_key] = [(p, "%d.png" % n) for n, p in numbers]
        self._sprite_labels[state_key].setText(t("add_assistant_selected_fmt") % len(self._state_files[state_key]))

    def _validate_form(self) -> str:
        name = (self.name_edit.text() or "").strip()
        if not name:
            return t("add_assistant_validation_name_empty")
        if not _validate_english_first_no_chinese(name):
            return t("add_assistant_validation_name_no_chinese")
        return ""

    def _on_save(self):
        if not self._current_folder:
            QMessageBox.warning(self, t("tip_title"), t("edit_assistant_no_assistant"))
            return
        err = self._validate_form()
        if err:
            QMessageBox.warning(self, t("tip_title"), err)
            return
        name = (self.name_edit.text() or "").strip()
        description = (self.desc_edit.toPlainText() or "").strip()
        assistant_root = os.path.join(self.assistants_dir, self._current_folder)
        data_path = os.path.join(assistant_root, "data.json")
        assets = os.path.join(assistant_root, "assets")
        sprites = os.path.join(assets, "sprites")

        try:
            with open(data_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            data["name"] = name
            cfg = data.setdefault("config", {})
            cfg["description"] = description
            cfg["personality"] = description
            data["config"] = cfg

            overwrite_folders = []
            for state_key, _ in SPRITE_STATE_KEYS:
                files = self._state_files.get(state_key, [])
                if not files:
                    continue
                folder_name = DEFAULT_STATE_TO_SPRITE_FOLDER.get(state_key, state_key)
                state_dir = os.path.join(sprites, folder_name)
                if os.path.isdir(state_dir):
                    existing = [f for f in os.listdir(state_dir) if f.lower().endswith(".png")]
                    if existing:
                        overwrite_folders.append(folder_name)
            if overwrite_folders:
                msg = t("edit_assistant_overwrite_confirm") % "、".join(overwrite_folders)
                if QMessageBox.question(
                    self, t("tip_title"), msg,
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                ) != QMessageBox.Yes:
                    return

            for state_key, _ in SPRITE_STATE_KEYS:
                folder_name = DEFAULT_STATE_TO_SPRITE_FOLDER.get(state_key, state_key)
                state_dir = os.path.join(sprites, folder_name)
                files = self._state_files.get(state_key, [])
                if files:
                    os.makedirs(state_dir, exist_ok=True)
                    for src_path, target_name in files:
                        dst = os.path.join(state_dir, target_name)
                        shutil.copy2(src_path, dst)
                    logger.debug(f"更新表情: {state_key} -> {len(files)} 张")

            with open(data_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.flush()
                if hasattr(os, "fsync"):
                    try:
                        os.fsync(f.fileno())
                    except (OSError, AttributeError):
                        pass
            logger.info(f"编辑助手成功: {self._current_folder}")
            QMessageBox.information(self, t("done_title"), t("edit_assistant_saved"))
            self.accept()
        except Exception as e:
            logger.exception(f"编辑助手失败: {e}")
            QMessageBox.warning(self, t("add_assistant_failed"), str(e))

    def _on_delete(self):
        if not self._current_folder:
            QMessageBox.warning(self, t("tip_title"), t("edit_assistant_no_assistant"))
            return
        ok = QMessageBox.question(
            self,
            t("tip_title"),
            t("edit_assistant_delete_confirm"),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if ok != QMessageBox.Yes:
            return
        assistant_root = os.path.join(self.assistants_dir, self._current_folder)
        try:
            shutil.rmtree(assistant_root)
            logger.info(f"已删除助手: {self._current_folder}")
            QMessageBox.information(self, t("done_title"), t("edit_assistant_deleted"))
            self.accept()
        except Exception as e:
            logger.exception(f"删除助手失败: {e}")
            QMessageBox.warning(self, t("add_assistant_failed"), str(e))
