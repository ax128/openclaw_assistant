"""
设置窗口 - 主设置入口
信息架构：API 与模型（独立界面入口）、行为与优化、数据与缓存
界面风格：简洁专业、卡片式分组、统一按钮样式
"""
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QScrollArea, QFormLayout,
    QPushButton, QGroupBox, QCheckBox, QSpinBox, QDoubleSpinBox,
    QLineEdit, QLabel, QFrame, QMessageBox, QDialog,
)
from PyQt5.QtCore import Qt, QTimer
from config.settings import Settings
from utils.logger import logger
from core.openclaw_gateway.gateway_memory import gateway_memory
from utils.platform_adapter import ui_font_family, ui_font_size_body, ui_window_bg, is_macos
from utils.async_runner import run_in_thread
from ui.settings.chat_settings import create_chat_card
from ui.settings.form_controls import ManualOnlySpinBox, ManualOnlyDoubleSpinBox, NoWheelComboBox
from ui.ui_settings_loader import get_ui_setting, set_ui_setting_and_save, save_ui_settings_geometry
from utils.i18n import t, get_locale, invalidate_locale_cache


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
            min-height: 20px;
        }
        QPushButton:hover { background: #1d4ed8; }
        QPushButton:pressed { background: #1e40af; }
    """ % (b.get("background", "#2563eb"), int(b.get("border_radius_px", 8)))


def _secondary_btn():
    b = get_ui_setting("settings_window.button.secondary") or {}
    return """
        QPushButton {
            background: %s;
            color: #374151;
            border: %s;
            border-radius: %dpx;
            padding: 10px 20px;
            font-weight: 500;
            min-height: 20px;
        }
        QPushButton:hover { background: #e5e7eb; }
        QPushButton:pressed { background: #d1d5db; }
    """ % (b.get("background", "#f3f4f6"), b.get("border", "1px solid #e5e7eb"), int(b.get("border_radius_px", 8)))


class SettingsWindow(QMainWindow):
    """设置主窗口 - 卡片式布局，API/模型入口 + 行为与优化 + 清除缓存"""

    def __init__(self, assistant_window=None, gateway_client=None):
        super().__init__()
        self.assistant_window = assistant_window
        self.gateway_client = gateway_client if gateway_client is not None else (getattr(assistant_window, "gateway_client", None) if assistant_window else None)
        # 使用主窗口传入的 Settings 实例，保证与主进程同一份配置并正确持久化；无则新建
        self.settings = getattr(assistant_window, "settings", None) if assistant_window else None
        if self.settings is None:
            self.settings = Settings()
        self.setWindowTitle(t("settings_title"))
        geom = get_ui_setting("settings_window.geometry") or {}
        self.setGeometry(
            int(geom.get("x", 400)),
            int(geom.get("y", 200)),
            int(geom.get("width", 480)),
            int(geom.get("height", 560)),
        )
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self._geometry_save_timer = None
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
            QSpinBox, QDoubleSpinBox, QLineEdit, QComboBox {{
                padding: {get_ui_setting("settings_window.form_control.padding") or "6px 10px"};
                border: {get_ui_setting("settings_window.form_control.border") or "1px solid #e5e7eb"};
                border-radius: {int(get_ui_setting("settings_window.form_control.border_radius_px") or 6)}px;
                background: #fafafa;
                min-height: {int(get_ui_setting("settings_window.form_control.min_height_px") or 20)}px;
            }}
        """)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setSpacing(20)
        main_layout.setContentsMargins(24, 24, 24, 24)

        # 标题
        title = QLabel(t("settings_title"))
        tt = get_ui_setting("settings_window.title") or {}
        title.setStyleSheet(
            "font-size: %dpx; font-weight: %d; color: %s;"
            % (int(tt.get("font_size_px", 20)), int(tt.get("font_weight", 600)), tt.get("color", "#111827"))
        )
        main_layout.addWidget(title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        scroll.viewport().setFocusPolicy(Qt.NoFocus)  # 避免 viewport 抢焦点，保证内部按钮可点击
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setSpacing(16)

        # ---------- 卡片：通用（语言） ----------
        g_lang = QGroupBox(t("general_card"))
        lang_layout = QVBoxLayout(g_lang)
        fl_lang = QFormLayout()
        self.locale_combo = NoWheelComboBox()
        self.locale_combo.addItem(t("language_zh"), "zh")
        self.locale_combo.addItem(t("language_en"), "en")
        loc = (self.settings.get("locale") or "zh").strip().lower()
        idx = self.locale_combo.findData("en" if loc == "en" else "zh")
        self.locale_combo.setCurrentIndex(max(0, idx))
        self.locale_combo.setToolTip(t("locale_tooltip"))
        fl_lang.addRow(t("language_label"), self.locale_combo)
        lang_layout.addLayout(fl_lang)
        content_layout.addWidget(g_lang)

        # ---------- 卡片：Gateway 设置（入口按钮，进入独立页面） ----------
        g_gateway = QGroupBox(t("connection_card"))
        gateway_layout = QVBoxLayout(g_gateway)
        gateway_desc = QLabel(t("gateway_card_desc"))
        gateway_desc.setStyleSheet("color: #6b7280; font-size: 12px; margin-bottom: 12px;")
        gateway_desc.setWordWrap(True)
        gateway_layout.addWidget(gateway_desc)
        self.btn_gateway_settings = QPushButton(t("gateway_settings_btn"))
        self.btn_gateway_settings.setCursor(Qt.PointingHandCursor)
        self.btn_gateway_settings.setFocusPolicy(Qt.StrongFocus)
        self.btn_gateway_settings.setMinimumHeight(40)
        self.btn_gateway_settings.setStyleSheet(_secondary_btn())
        self.btn_gateway_settings.setToolTip(t("gateway_settings_tooltip"))
        self.btn_gateway_settings.clicked.connect(self._on_click_gateway_settings)
        gateway_layout.addWidget(self.btn_gateway_settings)
        content_layout.addWidget(g_gateway)

        # ---------- 卡片：聊天（仅文字大小） ----------
        self._chat_card, self._get_chat_values = create_chat_card()
        content_layout.addWidget(self._chat_card)

        # ---------- 卡片：行为与优化 ----------
        g_other = QGroupBox(t("behavior_card"))
        fl_other = QFormLayout(g_other)
        fl_other.setSpacing(10)
        self.auto_interaction_checkbox = QCheckBox(t("auto_interaction"))
        self.auto_interaction_checkbox.setChecked(self.settings.get("auto_interaction_enabled", True))
        self.auto_interaction_checkbox.setToolTip(t("auto_interaction_tooltip"))
        fl_other.addRow(self.auto_interaction_checkbox)
        self.auto_interaction_interval = ManualOnlySpinBox()
        self.auto_interaction_interval.setMinimum(1)
        self.auto_interaction_interval.setButtonSymbols(QSpinBox.NoButtons)  # 取消右侧上下箭头
        self.auto_interaction_interval.setSuffix(t("interval_minutes_suffix"))
        self.auto_interaction_interval.setValue(self.settings.get("auto_interaction_interval_minutes", 10))
        self.auto_interaction_interval.setToolTip(t("interval_tooltip"))
        fl_other.addRow(t("interaction_interval"), self.auto_interaction_interval)
        _cooldown_sec = self.settings.get("auto_interaction_cooldown_sec", 180)
        _cooldown_min = max(1, int(_cooldown_sec) // 60)
        self.auto_interaction_cooldown = ManualOnlySpinBox()
        self.auto_interaction_cooldown.setMinimum(1)
        self.auto_interaction_cooldown.setButtonSymbols(QSpinBox.NoButtons)
        self.auto_interaction_cooldown.setSuffix(t("interval_minutes_suffix"))
        self.auto_interaction_cooldown.setValue(_cooldown_min)
        self.auto_interaction_cooldown.setToolTip(t("cooldown_tooltip"))
        fl_other.addRow(t("cooldown_window"), self.auto_interaction_cooldown)
        self.auto_interaction_session_edit = QLineEdit()
        self.auto_interaction_session_edit.setPlaceholderText(t("session_key_placeholder"))
        self.auto_interaction_session_edit.setText(self.settings.get("auto_interaction_session") or "")
        self.auto_interaction_session_edit.setToolTip(t("session_key_tooltip"))
        fl_other.addRow(t("session_key_label"), self.auto_interaction_session_edit)
        content_layout.addWidget(g_other)

        # ---------- 卡片：添加助手 ----------
        g_add_pet = QGroupBox(t("add_character_btn"))
        add_pet_layout = QVBoxLayout(g_add_pet)
        add_pet_desc = QLabel(t("add_character_tooltip"))
        add_pet_desc.setStyleSheet("color: #6b7280; font-size: 12px; margin-bottom: 12px;")
        add_pet_desc.setWordWrap(True)
        add_pet_layout.addWidget(add_pet_desc)
        self.btn_add_character = QPushButton(t("add_character_btn"))
        self.btn_add_character.setCursor(Qt.PointingHandCursor)
        self.btn_add_character.setFocusPolicy(Qt.StrongFocus)
        self.btn_add_character.setMinimumHeight(40)
        self.btn_add_character.setStyleSheet(_secondary_btn())
        self.btn_add_character.setToolTip(t("add_character_tooltip"))
        self.btn_add_character.clicked.connect(self._on_click_add_character)
        add_pet_layout.addWidget(self.btn_add_character)
        self.btn_edit_pet = QPushButton(t("edit_pet_btn"))
        self.btn_edit_pet.setCursor(Qt.PointingHandCursor)
        self.btn_edit_pet.setFocusPolicy(Qt.StrongFocus)
        self.btn_edit_pet.setMinimumHeight(40)
        self.btn_edit_pet.setStyleSheet(_secondary_btn())
        self.btn_edit_pet.setToolTip(t("edit_pet_tooltip"))
        self.btn_edit_pet.clicked.connect(self._on_click_edit_pet)
        add_pet_layout.addWidget(self.btn_edit_pet)
        content_layout.addWidget(g_add_pet)

        # ---------- 卡片：任务管理 ----------
        g_task = QGroupBox(t("task_manager_menu"))
        task_layout = QVBoxLayout(g_task)
        task_desc = QLabel(t("task_manager_card_desc"))
        task_desc.setStyleSheet("color: #6b7280; font-size: 12px; margin-bottom: 12px;")
        task_desc.setWordWrap(True)
        task_layout.addWidget(task_desc)
        self.btn_task_manager = QPushButton(t("task_manager_open_btn"))
        self.btn_task_manager.setCursor(Qt.PointingHandCursor)
        self.btn_task_manager.setFocusPolicy(Qt.StrongFocus)
        self.btn_task_manager.setMinimumHeight(40)
        self.btn_task_manager.setStyleSheet(_secondary_btn())
        self.btn_task_manager.setToolTip(t("task_manager_title"))
        self.btn_task_manager.clicked.connect(self._on_click_task_manager)
        task_layout.addWidget(self.btn_task_manager)
        content_layout.addWidget(g_task)

        # ---------- 卡片：助手基础 ----------
        pet = assistant_window.assistant_manager.get_current_assistant() if (assistant_window and getattr(assistant_window, "assistant_manager", None)) else None
        cfg = assistant_window.assistant_manager.get_current_assistant_config() if (assistant_window and getattr(assistant_window, "assistant_manager", None)) else None
        g_pet = QGroupBox(t("pet_card"))
        fl_pet = QFormLayout(g_pet)
        fl_pet.setSpacing(10)
        self.pet_name_edit = QLineEdit()
        self.pet_name_edit.setPlaceholderText(t("pet_name_placeholder"))
        self.pet_name_edit.setText((pet.data.get("name", "") or "") if pet and getattr(pet, "data", None) else "")
        self.pet_name_edit.setToolTip(t("pet_name_tooltip"))
        fl_pet.addRow(t("pet_name_label"), self.pet_name_edit)
        self.pet_size_combo = NoWheelComboBox()
        self.pet_size_combo.addItems([t("pet_size_1"), t("pet_size_2"), t("pet_size_3")])
        pet_size_val = int(cfg.get_pet_size()) if cfg else 2
        self.pet_size_combo.setCurrentIndex(max(0, min(2, pet_size_val - 1)))
        self.pet_size_combo.setToolTip(t("pet_size_tooltip"))
        fl_pet.addRow(t("pet_size_label"), self.pet_size_combo)
        content_layout.addWidget(g_pet)

        # ---------- 卡片：气泡 ----------
        g_bubble = QGroupBox(t("bubble_card"))
        fl_bubble = QFormLayout(g_bubble)
        fl_bubble.setSpacing(10)
        self.bubble_enabled_checkbox = QCheckBox(t("bubble_enabled"))
        self.bubble_enabled_checkbox.setChecked(bool(cfg.get_bubble_enabled()) if cfg else True)
        self.bubble_enabled_checkbox.setToolTip(t("bubble_tooltip"))
        fl_bubble.addRow(self.bubble_enabled_checkbox)
        content_layout.addWidget(g_bubble)

        # ---------- 卡片：状态与动画 ----------
        _t = cfg.get_timing if cfg else lambda k, d: d
        g_anim = QGroupBox(t("anim_card"))
        fl_anim = QFormLayout(g_anim)
        fl_anim.setSpacing(10)
        self.anim_interval_ms = ManualOnlySpinBox()
        self.anim_interval_ms.setMinimum(50)
        self.anim_interval_ms.setMaximum(2000)
        self.anim_interval_ms.setSingleStep(50)
        self.anim_interval_ms.setSuffix(t("ms_suffix"))
        self.anim_interval_ms.setValue(int(cfg.get_anim_interval_ms()) if cfg else 100)
        self.anim_interval_ms.setToolTip(t("anim_interval_tooltip"))
        fl_anim.addRow(t("anim_interval_label"), self.anim_interval_ms)
        self.pause_resume_delay = ManualOnlyDoubleSpinBox()
        self.pause_resume_delay.setMinimum(1.0)
        self.pause_resume_delay.setMaximum(60.0)
        self.pause_resume_delay.setSingleStep(1.0)
        self.pause_resume_delay.setSuffix(t("seconds_suffix"))
        self.pause_resume_delay.setValue(float(cfg.get_pause_resume_delay()) if cfg else 10.0)
        self.pause_resume_delay.setToolTip(t("pause_resume_tooltip"))
        fl_anim.addRow(t("pause_resume_label"), self.pause_resume_delay)
        self.move_interval = ManualOnlyDoubleSpinBox()
        self.move_interval.setMinimum(0.5)
        self.move_interval.setMaximum(30.0)
        self.move_interval.setSingleStep(0.5)
        self.move_interval.setSuffix(t("seconds_suffix"))
        self.move_interval.setValue(float(cfg.get_move_interval()) if cfg else 2.0)
        self.move_interval.setToolTip(t("move_interval_tooltip"))
        fl_anim.addRow(t("move_interval_label"), self.move_interval)
        self.state_hold_sec = ManualOnlySpinBox()
        self.state_hold_sec.setMinimum(5)
        self.state_hold_sec.setMaximum(300)
        self.state_hold_sec.setValue(int(_t("state_hold_sec", 30)))
        self.state_hold_sec.setSuffix(t("seconds_suffix"))
        self.state_hold_sec.setToolTip(t("state_hold_tooltip"))
        fl_anim.addRow(t("state_hold_label"), self.state_hold_sec)
        self.happy_after_action_sec = ManualOnlySpinBox()
        self.happy_after_action_sec.setMinimum(10)
        self.happy_after_action_sec.setMaximum(600)
        self.happy_after_action_sec.setValue(int(_t("happy_after_action_sec", 60)))
        self.happy_after_action_sec.setSuffix(t("seconds_suffix"))
        self.happy_after_action_sec.setToolTip(t("happy_hold_tooltip"))
        fl_anim.addRow(t("happy_hold_label"), self.happy_after_action_sec)
        content_layout.addWidget(g_anim)

        # ---------- 卡片：日志 ----------
        g_logs = QGroupBox(t("logs_card"))
        logs_layout = QVBoxLayout(g_logs)
        logs_desc = QLabel(t("logs_card_desc"))
        logs_desc.setStyleSheet("color: #6b7280; font-size: 12px; margin-bottom: 12px;")
        logs_desc.setWordWrap(True)
        logs_layout.addWidget(logs_desc)
        self.btn_log_tail = QPushButton(t("logs_tail_btn"))
        self.btn_log_tail.setCursor(Qt.PointingHandCursor)
        self.btn_log_tail.setFocusPolicy(Qt.StrongFocus)
        self.btn_log_tail.setMinimumHeight(40)
        self.btn_log_tail.setStyleSheet(_secondary_btn())
        self.btn_log_tail.setToolTip(t("log_tail_tooltip"))
        self.btn_log_tail.clicked.connect(self._on_click_log_tail)
        logs_layout.addWidget(self.btn_log_tail)
        content_layout.addWidget(g_logs)

        # ---------- 卡片：数据与缓存 ----------
        g_cache = QGroupBox(t("cache_card"))
        cache_layout = QVBoxLayout(g_cache)
        cache_desc = QLabel(t("cache_card_desc"))
        cache_desc.setStyleSheet("color: #6b7280; font-size: 12px; margin-bottom: 12px;")
        cache_desc.setWordWrap(True)
        cache_layout.addWidget(cache_desc)
        self.btn_clear_cache = QPushButton(t("clear_cache_btn"))
        self.btn_clear_cache.setCursor(Qt.PointingHandCursor)
        self.btn_clear_cache.setFocusPolicy(Qt.StrongFocus)
        self.btn_clear_cache.setMinimumHeight(40)
        self.btn_clear_cache.setStyleSheet(_secondary_btn())
        self.btn_clear_cache.setToolTip(t("clear_cache_tooltip_btn"))
        self.btn_clear_cache.clicked.connect(self._on_click_clear_cache)
        cache_layout.addWidget(self.btn_clear_cache)
        content_layout.addWidget(g_cache)

        content_layout.addStretch()
        scroll.setWidget(content)
        main_layout.addWidget(scroll)

        # 底部保存
        self._save_btn = QPushButton(t("save"))
        self._save_btn.setCursor(Qt.PointingHandCursor)
        self._save_btn.setStyleSheet(_primary_btn())
        self._save_btn.clicked.connect(self._save)
        main_layout.addWidget(self._save_btn)

    def _schedule_save_geometry(self):
        if getattr(self, "_geometry_save_timer", None):
            self._geometry_save_timer.stop()
        self._geometry_save_timer = QTimer(self)
        self._geometry_save_timer.setSingleShot(True)
        self._geometry_save_timer.timeout.connect(self._save_geometry)
        self._geometry_save_timer.start(400)

    def _save_geometry(self):
        g = self.geometry()
        save_ui_settings_geometry("settings_window", g.x(), g.y(), g.width(), g.height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._schedule_save_geometry()

    def moveEvent(self, event):
        super().moveEvent(event)
        self._schedule_save_geometry()

    def _get_gateway_session_keys(self):
        """从 gateway_memory 的 health 结果中收集当前会话列表中的所有 sessionKey。"""
        ok, payload, _ = gateway_memory.get_health()
        keys = set()
        if not ok or not payload:
            return keys
        agents = payload.get("agents") or []
        for a in agents:
            sessions = (a.get("sessions") or {}).get("recent") or []
            for r in sessions:
                k = (r.get("key") or "").strip()
                if k:
                    keys.add(k)
        if not agents and isinstance(payload.get("sessions"), dict):
            for r in (payload["sessions"].get("recent") or []):
                k = (r.get("key") or "").strip()
                if k:
                    keys.add(k)
        return keys

    def _refresh_assistant_form(self):
        """从当前助手与配置刷新「助手基础」「气泡」「状态与动画」表单，编辑/删除助手后调用。"""
        if not self.assistant_window or not getattr(self.assistant_window, "assistant_manager", None):
            return
        pet = self.assistant_window.assistant_manager.get_current_assistant()
        cfg = self.assistant_window.assistant_manager.get_current_assistant_config()
        if pet and getattr(pet, "data", None):
            self.pet_name_edit.setText((pet.data.get("name", "") or "").strip())
        if cfg:
            self.pet_size_combo.setCurrentIndex(max(0, min(2, int(cfg.get_pet_size()) - 1)))
            self.bubble_enabled_checkbox.setChecked(bool(cfg.get_bubble_enabled()))
            self.anim_interval_ms.setValue(int(cfg.get_anim_interval_ms()))
            self.pause_resume_delay.setValue(float(cfg.get_pause_resume_delay()))
            self.move_interval.setValue(float(cfg.get_move_interval()))
            _t = cfg.get_timing if hasattr(cfg, "get_timing") else lambda k, d: d
            self.state_hold_sec.setValue(int(_t("state_hold_sec", 30)))
            self.happy_after_action_sec.setValue(int(_t("happy_after_action_sec", 60)))

    def _save(self):
        try:
            self.settings.load()  # 先拉取最新配置，避免覆盖在 API 窗口中保存的 API/模型
        except Exception as e:
            logger.exception(f"设置加载失败: {e}")
            QMessageBox.warning(self, t("save_failed"), t("load_failed_message"))
            return
        want_auto = self.auto_interaction_checkbox.isChecked()
        session_key = (self.auto_interaction_session_edit.text() or "").strip()
        # 勾选自动交互时：必须有 sessionKey 且该 key 在 Gateway 会话列表中，否则不启用
        if want_auto:
            if not session_key:
                QMessageBox.warning(
                    self, t("auto_interaction"),
                    t("auto_interaction_session_warn"),
                )
                want_auto = False
                self.auto_interaction_checkbox.setChecked(False)
            else:
                valid_keys = self._get_gateway_session_keys()
                if session_key not in valid_keys:
                    QMessageBox.warning(
                        self, t("auto_interaction"),
                        t("auto_interaction_session_invalid"),
                    )
                    want_auto = False
                    self.auto_interaction_checkbox.setChecked(False)
        self.settings.set("auto_interaction_enabled", want_auto)
        self.settings.set("auto_interaction_interval_minutes", self.auto_interaction_interval.value())
        self.settings.set("auto_interaction_cooldown_sec", max(60, self.auto_interaction_cooldown.value() * 60))
        self.settings.set("auto_interaction_session", session_key)
        loc = (self.locale_combo.currentData() or "zh") if getattr(self, "locale_combo", None) else self.settings.get("locale") or "zh"
        self.settings.set("locale", loc)
        if hasattr(self, "_get_chat_values") and callable(self._get_chat_values):
            for k, v in self._get_chat_values().items():
                self.settings.set(k, v)
        pet = self.assistant_window.assistant_manager.get_current_assistant() if (self.assistant_window and getattr(self.assistant_window, "assistant_manager", None)) else None
        if pet and getattr(pet, "data", None):
            # 助手基础（系统级参数已迁至 config/system_settings.json，不再写回 data.json app_settings）
            name_text = (self.pet_name_edit.text() or "").strip()
            pet.data["name"] = name_text if name_text else pet.data.get("name", "")
            cfg = pet.data.setdefault("config", {})
            cfg["pet_size"] = self.pet_size_combo.currentIndex() + 1
            # 气泡
            cfg["bubble_enabled"] = self.bubble_enabled_checkbox.isChecked()
            # 状态与动画
            timings = cfg.setdefault("timings", {})
            cfg["anim_interval_ms"] = self.anim_interval_ms.value()
            cfg["pause_resume_delay"] = self.pause_resume_delay.value()
            cfg["move_interval"] = self.move_interval.value()
            timings["state_hold_sec"] = self.state_hold_sec.value()
            timings["happy_after_action_sec"] = self.happy_after_action_sec.value()
        try:
            if getattr(self, "_save_btn", None):
                self._save_btn.setEnabled(False)
                self._save_btn.setText(t("saving"))
            run_in_thread(
                self._save_worker,
                on_done=lambda _: self._on_save_done(),
                on_error=lambda e: self._on_save_error(e),
            )
        except Exception as e:
            logger.exception(f"保存启动失败: {e}")
            self._restore_save_btn()
            QMessageBox.warning(self, t("save_failed"), t("save_failed"))

    def _save_worker(self):
        """后台执行：助手 data 落盘 + 系统设置落盘；任一步失败则抛异常，由 on_error 弹窗。"""
        pet = self.assistant_window.assistant_manager.get_current_assistant() if (self.assistant_window and getattr(self.assistant_window, "assistant_manager", None)) else None
        if pet and getattr(pet, "data", None):
            pet.save()
        self.settings.save()

    def _restore_save_btn(self):
        if getattr(self, "_save_btn", None):
            self._save_btn.setEnabled(True)
            self._save_btn.setText(t("save"))

    def _on_save_done(self):
        try:
            invalidate_locale_cache()
            self._restore_save_btn()
            if self.assistant_window:
                pt = self.settings.get("chat_font_pt")
                if pt is not None:
                    try:
                        self.assistant_window.chat_font_pt = int(pt)
                    except (TypeError, ValueError):
                        self.assistant_window.chat_font_pt = 15
                popup_size = (self.settings.get("popup_size") or "small").strip().lower()
                if popup_size in ("small", "medium", "large"):
                    self.assistant_window.popup_size = popup_size
            pt = self.settings.get("chat_font_pt")
            if pt is not None:
                set_ui_setting_and_save("font.chat.default_pt", int(pt))
            popup_size = (self.settings.get("popup_size") or "small").strip().lower()
            if popup_size in ("small", "medium", "large"):
                set_ui_setting_and_save("chat_window_popup.default_size", popup_size)
            if self.assistant_window and hasattr(self.assistant_window, "task_manager"):
                tm = getattr(self.assistant_window, "task_manager", None)
                if tm and hasattr(tm, "apply_auto_interaction_settings"):
                    tm.apply_auto_interaction_settings(
                        enabled=self.auto_interaction_checkbox.isChecked(),
                        interval_minutes=self.auto_interaction_interval.value(),
                    )
            # 成功提示：优先气泡；无 assistant_window 或气泡被关闭时用弹窗兜底，确保用户看到
            if self.assistant_window and hasattr(self.assistant_window, "show_bubble_requested"):
                self.assistant_window.show_bubble_requested.emit(t("settings_saved_message"), 2)
            else:
                self._show_save_success_message()
        except Exception as e:
            logger.exception(f"保存成功回调异常: {e}")
            self._restore_save_btn()
            self._show_save_success_message()
        logger.info(f"设置已保存")

    def _show_save_success_message(self):
        """显示保存成功提示（弹窗，保证可见）。"""
        box = QMessageBox(self)
        box.setWindowTitle(t("settings_saved_title"))
        box.setText(t("settings_saved_message"))
        box.setIcon(QMessageBox.Information)
        box.setStandardButtons(QMessageBox.Ok)
        box.setWindowModality(Qt.ApplicationModal)
        box.raise_()
        box.activateWindow()
        box.exec_()

    def _on_save_error(self, exc):
        logger.exception(f"设置保存失败: {exc}")
        self._restore_save_btn()
        QMessageBox.warning(None, t("save_failed"), t("save_failed"))

    def _on_click_gateway_settings(self):
        """打开 Gateway 设置独立页面"""
        QTimer.singleShot(0, self._open_gateway_settings)

    def _open_gateway_settings(self):
        try:
            from ui.settings.gateway_settings_window import GatewaySettingsWindow
            w = GatewaySettingsWindow(parent=self, assistant_window=self.assistant_window, gateway_client=self.gateway_client)
            w.setWindowModality(Qt.NonModal)
            w.show()
            w.raise_()
            w.activateWindow()
        except Exception as e:
            logger.exception(f"打开 Gateway 设置失败: {e}")

    def _on_click_log_tail(self):
        """打开日志 tail 窗口"""
        QTimer.singleShot(0, self._open_log_tail)

    def _open_log_tail(self):
        try:
            from ui.settings.log_tail_window import LogTailWindow
            w = LogTailWindow(self, gateway_client=self.gateway_client)
            w.setWindowModality(Qt.NonModal)
            w.show()
            w.raise_()
            w.activateWindow()
        except Exception as e:
            logger.exception(f"打开日志 tail 失败: {e}")

    def _on_click_add_character(self):
        """打开添加助手弹窗；成功后刷新助手列表。"""
        QTimer.singleShot(0, self._open_add_character)

    def _open_add_character(self):
        try:
            import os
            assistants_dir = os.path.normpath(os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                self.settings.get("assistants_dir", "assistants"),
            ))
            from ui.settings.add_assistant_dialog import AddAssistantDialog
            dlg = AddAssistantDialog(assistants_dir, parent=self)
            dlg.setWindowModality(Qt.ApplicationModal)
            if dlg.exec_() == QDialog.Accepted:
                if self.assistant_window and getattr(self.assistant_window, "assistant_manager", None):
                    self.assistant_window.assistant_manager.load_all_assistants()
                    logger.info("添加助手后已刷新助手列表")
        except Exception as e:
            logger.exception(f"打开添加助手弹窗失败: {e}")
            QMessageBox.warning(self, t("add_pet_failed"), str(e))

    def _on_click_edit_pet(self):
        QTimer.singleShot(0, self._open_edit_pet)

    def _open_edit_pet(self):
        try:
            import os
            assistants_dir = os.path.normpath(os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                self.settings.get("assistants_dir", "assistants"),
            ))
            from ui.settings.edit_assistant_dialog import EditAssistantDialog, _list_assistant_folders
            if not _list_assistant_folders(assistants_dir):
                QMessageBox.information(self, t("tip_title"), t("edit_pet_no_pets"))
                return
            dlg = EditAssistantDialog(assistants_dir, parent=self)
            dlg.setWindowModality(Qt.ApplicationModal)
            if dlg.exec_() == QDialog.Accepted:
                if self.assistant_window and getattr(self.assistant_window, "assistant_manager", None):
                    pm = self.assistant_window.assistant_manager
                    pm.load_all_assistants()
                    pet = pm.get_current_assistant()
                    if pet and hasattr(pet, "load"):
                        pet.load()
                    if hasattr(self.assistant_window, "_reload_for_current_assistant"):
                        self.assistant_window._reload_for_current_assistant()
                    self._refresh_assistant_form()
                    logger.info("编辑/删除助手后已刷新助手列表")
        except Exception as e:
            logger.exception(f"打开编辑助手弹窗失败: {e}")
            QMessageBox.warning(self, t("add_pet_failed"), str(e))

    def _on_click_task_manager(self):
        QTimer.singleShot(0, self._open_task_manager)

    def _open_task_manager(self):
        try:
            if self.assistant_window and hasattr(self.assistant_window, "open_task_manager"):
                self.assistant_window.open_task_manager()
            else:
                QMessageBox.warning(self, t("tip_title"), t("task_no_manager_short"))
        except Exception as e:
            logger.exception(f"打开任务管理失败: {e}")
            QMessageBox.warning(self, t("add_pet_failed"), str(e))

    def _on_click_clear_cache(self):
        """延迟一帧打开，避免在滚动区内点击被吞掉"""
        QTimer.singleShot(0, self._open_clear_cache)

    def _open_clear_cache(self):
        try:
            from ui.settings.clear_cache_window import ClearCacheWindow
            bot_id = "bot00001"
            if self.assistant_window and getattr(self.assistant_window, "assistant_manager", None):
                pet = self.assistant_window.assistant_manager.get_current_assistant()
                if pet:
                    bot_id = (pet.get("bot_id") if hasattr(pet, "get") else getattr(pet, "assistant_name", None)) or bot_id
            self._clear_cache_window = ClearCacheWindow(bot_id, self.assistant_window)
            w = self._clear_cache_window
            w.setWindowModality(Qt.NonModal)
            w.show()
            w.raise_()
            w.activateWindow()
        except Exception as e:
            logger.exception(f"打开清除缓存失败: {e}")
