"""
添加助手弹窗：填写文件夹名、助手名、介绍，自动生成 bot_id，可选配置各表情图集（1.png～30.png 连续）。
"""
import json
import os
import re
import shutil
from datetime import datetime
from copy import deepcopy

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QLineEdit, QLabel, QTextEdit, QPushButton, QMessageBox, QScrollArea,
    QWidget, QFrame, QFileDialog,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont

from utils.logger import logger
from utils.i18n import t
from utils.platform_adapter import ui_font_family, ui_font_size_body, ui_window_bg
from core.assistant_data import DEFAULT_CONFIG, DEFAULT_STATE_TO_SPRITE_FOLDER
from ui.ui_settings_loader import get_ui_setting

# 状态 -> (sprites 子文件夹名, i18n 显示名 key)
SPRITE_STATE_KEYS = [
    ("idle", "state_idle"),
    ("walking", "state_walking"),
    ("dragging", "state_dragging"),
    ("paused", "state_paused"),
    ("happy", "state_happy"),
    ("sad", "state_sad"),
    ("thinking", "state_thinking"),
]
MAX_SPRITES_PER_STATE = 30


NEXT_BOT_SEQ_FILE = "next_bot_seq.json"


def _read_next_bot_seq(assistants_dir: str) -> int:
    """读取 next_bot_seq.json 中的 next 值；文件不存在时根据现有助手取 max+1 并写入。空缺不补。"""
    path = os.path.join(assistants_dir, NEXT_BOT_SEQ_FILE)
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            n = data.get("next")
            if isinstance(n, int) and n >= 1:
                return n
        except (json.JSONDecodeError, OSError, ValueError):
            pass
    max_num = 0
    if os.path.isdir(assistants_dir):
        for name in os.listdir(assistants_dir):
            if name == NEXT_BOT_SEQ_FILE:
                continue
            data_file = os.path.join(assistants_dir, name, "data.json")
            if not os.path.isfile(data_file):
                continue
            try:
                with open(data_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                bid = (data.get("bot_id") or "").strip()
                if re.match(r"^bot\d+$", bid, re.IGNORECASE):
                    num = int(re.sub(r"^bot", "", bid, flags=re.IGNORECASE))
                    max_num = max(max_num, num)
            except (json.JSONDecodeError, OSError, ValueError):
                continue
    next_val = max_num + 1
    os.makedirs(assistants_dir, exist_ok=True)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"next": next_val}, f, indent=2)
    except OSError:
        pass
    return next_val


def get_next_bot_id(assistants_dir: str) -> str:
    """返回下一个将使用的 bot_id（格式 bot00001），不递增。用于预览。"""
    return "bot%05d" % _read_next_bot_seq(assistants_dir)


def consume_next_bot_id(assistants_dir: str) -> None:
    """新增助手成功后调用：将 next_bot_seq 递增，保证空缺不补。"""
    path = os.path.join(assistants_dir, NEXT_BOT_SEQ_FILE)
    n = _read_next_bot_seq(assistants_dir)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"next": n + 1}, f, indent=2)
    except OSError:
        pass


def _next_bot_id(assistants_dir: str) -> str:
    """返回下一个将使用的 bot_id（同 get_next_bot_id，兼容旧调用）。"""
    return get_next_bot_id(assistants_dir)


def _validate_english_first_no_chinese(value: str) -> bool:
    """校验：非空、无汉字、以英文字母开头；允许字母数字下划线。"""
    if not value or not value.strip():
        return False
    s = value.strip()
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9_]*$", s):
        return False
    if re.search(r"[\u4e00-\u9fff]", s):
        return False
    return True


def _validate_sprite_files(file_paths: list) -> tuple:
    """校验选中的图片：必须为 1.png, 2.png, ... N.png 连续，N<=30。返回 (ok, error_message)。"""
    if not file_paths:
        return True, ""
    numbers = []
    for p in file_paths:
        base = os.path.basename(p)
        if not re.match(r"^\d+\.png$", base, re.IGNORECASE):
            return False, t("add_pet_validation_sprites_continuous")
        num = int(re.match(r"^(\d+)", base).group(1))
        if num < 1 or num > MAX_SPRITES_PER_STATE:
            return False, t("add_pet_validation_sprites_max")
        numbers.append((num, p))
    numbers.sort(key=lambda x: x[0])
    nums_only = [n for n, _ in numbers]
    if nums_only[0] != 1:
        return False, t("add_pet_validation_sprites_continuous")
    expected = list(range(1, len(nums_only) + 1))
    if nums_only != expected:
        return False, t("add_pet_validation_sprites_continuous")
    return True, ""


def _secondary_btn():
    b = get_ui_setting("settings_window.button.secondary") or {}
    return """
        QPushButton {
            background: %s;
            color: #374151;
            border: %s;
            border-radius: %dpx;
            padding: 8px 14px;
            font-weight: 500;
        }
        QPushButton:hover { background: #e5e7eb; }
    """ % (b.get("background", "#f3f4f6"), b.get("border", "1px solid #e5e7eb"), int(b.get("border_radius_px", 8)))


def _primary_btn():
    b = get_ui_setting("settings_window.button.primary") or {}
    return """
        QPushButton {
            background: %s;
            color: white;
            border: none;
            border-radius: %dpx;
            padding: 10px 20px;
            font-weight: 500;
        }
        QPushButton:hover { background: #1d4ed8; }
    """ % (b.get("background", "#2563eb"), int(b.get("border_radius_px", 8)))


class AddAssistantDialog(QDialog):
    """添加助手：文件夹名、助手名、介绍、自动 bot_id、各表情图集选择。"""

    def __init__(self, assistants_dir: str, parent=None):
        super().__init__(parent)
        self.assistants_dir = os.path.normpath(assistants_dir)
        self._state_files = {}
        self.setWindowTitle(t("add_character_title"))
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
        self.setMinimumHeight(520)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        form = QFormLayout()
        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText(t("add_pet_folder_placeholder"))
        self.folder_edit.setToolTip(t("add_pet_folder_tooltip"))
        self.folder_edit.textChanged.connect(self._on_folder_changed)
        form.addRow(t("add_pet_folder_label"), self.folder_edit)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText(t("add_pet_name_placeholder"))
        self.name_edit.setToolTip(t("add_pet_folder_tooltip"))
        form.addRow(t("add_pet_name_label"), self.name_edit)

        self.bot_id_label = QLabel("")
        self.bot_id_label.setStyleSheet("color: #6b7280;")
        form.addRow(t("add_pet_bot_id_label"), self.bot_id_label)

        self.desc_edit = QTextEdit()
        self.desc_edit.setPlaceholderText(t("add_pet_description_placeholder"))
        self.desc_edit.setMaximumHeight(80)
        form.addRow(t("add_pet_description_label"), self.desc_edit)

        layout.addLayout(form)
        self._update_bot_id_preview()

        g_sprites = QGroupBox(t("add_pet_sprites_card"))
        sprites_layout = QVBoxLayout(g_sprites)
        hint = QLabel(t("add_pet_sprites_hint"))
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
            btn = QPushButton(t("add_pet_select_images"))
            btn.setStyleSheet(_secondary_btn())
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda checked=False, s=state_key: self._on_select_sprites(s))
            row.addWidget(btn)
            count_lbl = QLabel(t("add_pet_selected_fmt") % 0)
            count_lbl.setStyleSheet("color: #6b7280;")
            row.addWidget(count_lbl)
            row.addStretch()
            sprites_layout.addLayout(row)
            self._sprite_buttons[state_key] = btn
            self._sprite_labels[state_key] = count_lbl
            self._state_files[state_key] = []

        layout.addWidget(g_sprites)

        btns = QHBoxLayout()
        btns.addStretch()
        self.ok_btn = QPushButton(t("add_pet_ok"))
        self.ok_btn.setStyleSheet(_primary_btn())
        self.ok_btn.setCursor(Qt.PointingHandCursor)
        self.ok_btn.clicked.connect(self._on_ok)
        cancel_btn = QPushButton(t("cancel_btn"))
        cancel_btn.setStyleSheet(_secondary_btn())
        cancel_btn.setCursor(Qt.PointingHandCursor)
        cancel_btn.clicked.connect(self.reject)
        btns.addWidget(cancel_btn)
        btns.addWidget(self.ok_btn)
        layout.addLayout(btns)

    def _on_folder_changed(self):
        self._update_bot_id_preview()

    def _update_bot_id_preview(self):
        self.bot_id_label.setText(_next_bot_id(self.assistants_dir))

    def _on_select_sprites(self, state_key: str):
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            t("add_pet_select_images") + " - " + DEFAULT_STATE_TO_SPRITE_FOLDER.get(state_key, state_key),
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
        self._sprite_labels[state_key].setText(t("add_pet_selected_fmt") % len(self._state_files[state_key]))

    def _validate_form(self) -> str:
        folder = (self.folder_edit.text() or "").strip()
        if not folder:
            return t("add_pet_validation_folder_empty")
        if not _validate_english_first_no_chinese(folder):
            return t("add_pet_validation_folder_no_chinese")
        name = (self.name_edit.text() or "").strip()
        if not name:
            return t("add_pet_validation_name_empty")
        if not _validate_english_first_no_chinese(name):
            return t("add_pet_validation_name_no_chinese")
        assistant_path = os.path.join(self.assistants_dir, folder)
        if os.path.isdir(assistant_path) and os.path.isfile(os.path.join(assistant_path, "data.json")):
            return t("add_pet_validation_folder_exists")
        return ""

    def _on_ok(self):
        err = self._validate_form()
        if err:
            QMessageBox.warning(self, t("tip_title"), err)
            return
        folder = (self.folder_edit.text() or "").strip()
        name = (self.name_edit.text() or "").strip()
        description = (self.desc_edit.toPlainText() or "").strip()
        bot_id = get_next_bot_id(self.assistants_dir)

        assistant_root = os.path.join(self.assistants_dir, folder)
        assets = os.path.join(assistant_root, "assets")
        sprites = os.path.join(assets, "sprites")

        try:
            os.makedirs(assistant_root, exist_ok=True)
            os.makedirs(assets, exist_ok=True)
            os.makedirs(sprites, exist_ok=True)
            for state_key, _ in SPRITE_STATE_KEYS:
                files = self._state_files.get(state_key, [])
                if not files:
                    continue
                folder_name = DEFAULT_STATE_TO_SPRITE_FOLDER.get(state_key, state_key)
                state_dir = os.path.join(sprites, folder_name)
                os.makedirs(state_dir, exist_ok=True)
                for src_path, target_name in files:
                    dst = os.path.join(state_dir, target_name)
                    shutil.copy2(src_path, dst)
                    logger.debug(f"复制表情: {src_path} -> {dst}")

            config = deepcopy(DEFAULT_CONFIG)
            config["description"] = description
            config["personality"] = description

            state_to_sprite_folder = dict(DEFAULT_STATE_TO_SPRITE_FOLDER)
            data = {
                "name": name,
                "level": 1,
                "experience": 0,
                "state": "happy",
                "position": {"x": 100, "y": 100},
                "interaction_history": [],
                "created_at": datetime.now().isoformat(),
                "last_active": datetime.now().isoformat(),
                "state_to_sprite_folder": state_to_sprite_folder,
                "bot_id": bot_id,
                "config": config,
            }
            data_path = os.path.join(assistant_root, "data.json")
            with open(data_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            consume_next_bot_id(self.assistants_dir)
            logger.info(f"添加助手成功: {folder}, bot_id={bot_id}")
            QMessageBox.information(self, t("done_title"), t("add_pet_success"))
            self.accept()
        except Exception as e:
            logger.exception(f"添加助手失败: {e}")
            QMessageBox.warning(self, t("add_pet_failed"), str(e))
