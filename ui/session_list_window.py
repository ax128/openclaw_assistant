"""
会话列表窗口
支持 Gateway（选择 Agent + Session）与本地会话；双击打开聊天。
新建 Gateway 会话使用渠道标识 claw_pet_<时间戳>，sessionKey=agent:<当前agent>:claw_pet_<时间戳>。
提供模型列表、技能状态、定时任务（Gateway 请求）展示。
"""
import json
import os
import time
from datetime import datetime
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QListWidget, QListWidgetItem, QLabel,
    QMenuBar, QMenu, QMessageBox, QCheckBox, QComboBox,
    QTabWidget, QDialog, QTextEdit, QDialogButtonBox,
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QIcon, QFont
from PyQt5.QtWidgets import QApplication, QMenu
from utils.logger import logger, gateway_logger
from utils.i18n import t
from ui.settings.add_model_dialog import AddModelDialog
from ui.configsetting.config_setting_window import ConfigViewDialog, ConfigEditDialog
from utils.platform_adapter import ui_font_family, is_macos
from utils.async_runner import run_in_thread
from ui.ui_settings_loader import get_ui_setting, save_ui_settings_geometry
from core.openclaw_gateway import local_to_server as l2s
from core.openclaw_gateway.gateway_memory import gateway_memory
from core.openclaw_gateway.protocol import METHOD_SKILLS_STATUS, METHOD_CRON_LIST

_UI_DIR = os.path.dirname(os.path.abspath(__file__))
def _svg(path): return os.path.join(_UI_DIR, "svg_file", path)


def _chat_font_pt_default():
    return int(get_ui_setting("font.chat.default_pt") or 15)


CHAT_FONT_PT_DEFAULT = 15  # 仅作 _get_chat_font_pt 回退，实际默认从 ui_settings 读
# 桌面助手新建会话渠道前缀，完整 channel = claw_pet_<时间戳>，sessionKey = agent:<agentId>:claw_pet_<时间戳>
CHANNEL_CLAW_PET_PREFIX = "claw_pet"
# Gateway 会话列表定时刷新间隔（毫秒），与 Gateway 保持同步
GATEWAY_SESSION_REFRESH_MS = 25000
# 全局固定 Agent：关闭会话管理后再次打开时恢复上次选中的 Agent
_GLOBAL_PINNED_AGENT_ID = None


class SessionListWindow(QMainWindow):
    """会话列表 - 新建/打开会话 -> ChatWindow"""

    def __init__(self, pet_name, pet_personality="", assistant_window=None, gateway_client=None):
        super().__init__()
        self.pet_name = pet_name
        self.pet_personality = pet_personality
        self.assistant_window = assistant_window
        self.gateway_client = gateway_client if gateway_client is not None else getattr(assistant_window, "gateway_client", None)
        self.chat_windows = {}
        self._session_ids = []
        self._gateway_agents = []   # [{"agentId","name","recent":[...]}]
        self._gateway_session_rows = []  # [(session_key, agent_name, updatedAt, is_agent_to_agent)]
        self._gateway_refresh_timer = QTimer(self)
        self._gateway_refresh_timer.setSingleShot(False)
        self._gateway_refresh_timer.timeout.connect(self._on_gateway_refresh_tick)
        # 用户选中的 Agent 固定值：从全局恢复，刷新/事件更新后也先恢复此项；用户切换时写回全局
        self._pinned_agent_id = _GLOBAL_PINNED_AGENT_ID

        self.setWindowTitle(t("session_list_title_prefix") + pet_name)
        geom = get_ui_setting("session_list_window.geometry") or {}
        self.setGeometry(
            int(geom.get("x", 300)),
            int(geom.get("y", 200)),
            int(geom.get("width", 520)),
            int(geom.get("height", 560)),
        )
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self._geometry_save_timer = None
        if is_macos():
            self.setUnifiedTitleAndToolBarOnMac(True)
        if os.path.exists(_svg("chat_windows_bot.svg")):
            self.setWindowIcon(QIcon(_svg("chat_windows_bot.svg")))

        self._setup_menu_bar()

        c = QWidget()
        self.setCentralWidget(c)
        layout = QVBoxLayout(c)
        self._title_label = QLabel(t("session_list_menu"))
        layout.addWidget(self._title_label)
        self._apply_session_font()
        # 仅 Gateway 会话；本地历史已移除
        # 选择 Agent
        agent_row = QHBoxLayout()
        agent_row.addWidget(QLabel(t("select_agent_label")))
        self._agent_combo = QComboBox()
        self._agent_combo.currentIndexChanged.connect(self._on_agent_changed)
        agent_row.addWidget(self._agent_combo)
        agent_row.addStretch()
        self._agent_row_widget = QWidget()
        self._agent_row_widget.setLayout(agent_row)
        layout.addWidget(self._agent_row_widget)
        self._show_agent_to_agent_cb = QCheckBox(t("show_agent_to_agent"))
        self._show_agent_to_agent_cb.setChecked(False)
        self._show_agent_to_agent_cb.setToolTip(t("show_agent_to_agent_tooltip"))
        self._show_agent_to_agent_cb.stateChanged.connect(self._on_show_agent_to_agent_changed)
        self._show_agent_to_agent_row = QWidget()
        show_a2a_layout = QHBoxLayout(self._show_agent_to_agent_row)
        show_a2a_layout.addWidget(self._show_agent_to_agent_cb)
        show_a2a_layout.addStretch()
        layout.addWidget(self._show_agent_to_agent_row)
        self._select_all_cb = QCheckBox(t("select_all"))
        self._select_all_cb.stateChanged.connect(self._on_select_all_changed)
        layout.addWidget(self._select_all_cb)
        self.list_widget = QListWidget()
        self.list_widget.itemDoubleClicked.connect(self._on_item_double_click)
        self.list_widget.itemChanged.connect(self._on_item_check_changed)
        self.list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self._on_session_list_context_menu)
        layout.addWidget(self.list_widget)
        btn_layout = QHBoxLayout()
        new_btn = QPushButton(t("new_session_btn"))
        if os.path.exists(_svg("chat_windows_new_chat.svg")):
            new_btn.setIcon(QIcon(_svg("chat_windows_new_chat.svg")))
        new_btn.clicked.connect(self._new_session)
        open_btn = QPushButton(t("open_selected_btn"))
        open_btn.clicked.connect(self._open_selected)
        self._del_btn = QPushButton(t("task_btn_del"))
        self._del_btn.setToolTip(t("del_sessions_tooltip"))
        if os.path.exists(_svg("chat_windows_delete_chat.svg")):
            self._del_btn.setIcon(QIcon(_svg("chat_windows_delete_chat.svg")))
        self._del_btn.clicked.connect(self._delete_selected)
        btn_layout.addWidget(new_btn)
        btn_layout.addWidget(open_btn)
        btn_layout.addWidget(self._del_btn)
        layout.addLayout(btn_layout)

        # 模型 | 技能 | 定时任务（Tab + 列表）
        self._gw_tabs = QTabWidget()
        # 模型：从内存 config.agents.defaults.models 取 key 展示，列尾标「可用」/「当前」；支持增加/删除（切换模型在聊天窗口）
        list_cfg = get_ui_setting("session_list_window.list") or {}
        _list_max_h = int(list_cfg.get("max_height_px", 160))
        _list_fs = int(list_cfg.get("font_size_px", 11))
        self._models_list = QListWidget()
        self._models_list.setMaximumHeight(_list_max_h)
        self._models_list.setStyleSheet("QListWidget { font-size: %dpx; }" % _list_fs)
        self._models_list.itemDoubleClicked.connect(self._on_model_double_clicked)
        self._models_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self._models_list.customContextMenuRequested.connect(self._on_models_list_context_menu)
        models_tab = QWidget()
        models_layout = QVBoxLayout(models_tab)
        models_layout.addWidget(QLabel(t("from_config_models")))
        models_layout.addWidget(self._models_list)
        models_btn_row = QHBoxLayout()
        btn_add_model = QPushButton(t("add_model_btn"))
        btn_add_model.setToolTip(t("add_model_tooltip"))
        btn_add_model.clicked.connect(self._on_add_model)
        btn_del_model = QPushButton(t("delete_model_btn"))
        btn_del_model.setToolTip(t("delete_model_tooltip"))
        btn_del_model.clicked.connect(self._on_delete_model)
        models_btn_row.addWidget(btn_add_model)
        models_btn_row.addWidget(btn_del_model)
        btn_read_config = QPushButton(t("config_read_btn"))
        btn_read_config.setToolTip(t("config_read_btn_tooltip_session"))
        btn_read_config.clicked.connect(self._on_read_config)
        btn_edit_config = QPushButton(t("config_edit_btn"))
        btn_edit_config.setToolTip(t("config_edit_btn_tooltip_session"))
        btn_edit_config.clicked.connect(self._on_edit_config)
        models_btn_row.addWidget(btn_read_config)
        models_btn_row.addWidget(btn_edit_config)
        models_btn_row.addStretch()
        models_layout.addLayout(models_btn_row)
        self._gw_tabs.addTab(models_tab, t("tab_models"))
        # 技能：刷新按钮 + 列表，eligible 在前，列内容 name，不可用则列尾标「不可用」，点击弹出详情
        self._skills_list = QListWidget()
        self._skills_list.setMaximumHeight(_list_max_h)
        self._skills_list.setStyleSheet("QListWidget { font-size: %dpx; }" % _list_fs)
        self._skills_list.itemClicked.connect(self._on_skill_item_clicked)
        skills_tab = QWidget()
        skills_layout = QVBoxLayout(skills_tab)
        btn_skills = QPushButton(t("refresh_skills_btn"))
        btn_skills.clicked.connect(self._fetch_skills_status)
        skills_layout.addWidget(btn_skills)
        skills_layout.addWidget(self._skills_list)
        self._gw_tabs.addTab(skills_tab, t("tab_skills"))
        # 定时任务：刷新按钮 + 列表，enabled 在前，列内容 agentId - name，点击弹出详情
        self._cron_list = QListWidget()
        self._cron_list.setMaximumHeight(_list_max_h)
        self._cron_list.setStyleSheet("QListWidget { font-size: %dpx; }" % _list_fs)
        self._cron_list.itemClicked.connect(self._on_cron_item_clicked)
        cron_tab = QWidget()
        cron_layout = QVBoxLayout(cron_tab)
        btn_cron = QPushButton(t("refresh_cron_btn"))
        btn_cron.clicked.connect(self._fetch_cron_list)
        cron_layout.addWidget(btn_cron)
        cron_layout.addWidget(self._cron_list)
        self._gw_tabs.addTab(cron_tab, t("tab_cron"))
        layout.addWidget(self._gw_tabs)
        self._refresh_models_from_config()

    def _setup_menu_bar(self):
        """顶部一级菜单「菜单」，与助手右键菜单共用同一套项；上边界线 + 按钮样式。"""
        menubar = self.menuBar()
        if is_macos():
            menubar.setNativeMenuBar(True)
        else:
            menubar_style = get_ui_setting("session_list_window.menubar_style") or "QMenuBar::item { padding: 6px 14px; border-radius: 4px; }"
            menubar.setStyleSheet(
                "QMenuBar { border-top: 1px solid #ccc; background: #fafafa; }\n%s\nQMenuBar::item:selected { background: #e0e0e0; }" % menubar_style
            )
        self._menu_top = menubar.addMenu(t("menu_label"))
        self._menu_top.aboutToShow.connect(self._on_menu_about_to_show)
        self._on_menu_about_to_show()

    def _schedule_save_geometry(self):
        if getattr(self, "_geometry_save_timer", None):
            self._geometry_save_timer.stop()
        self._geometry_save_timer = QTimer(self)
        self._geometry_save_timer.setSingleShot(True)
        self._geometry_save_timer.timeout.connect(self._save_geometry)
        self._geometry_save_timer.start(400)

    def _save_geometry(self):
        g = self.geometry()
        save_ui_settings_geometry("session_list_window", g.x(), g.y(), g.width(), g.height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._schedule_save_geometry()

    def moveEvent(self, event):
        super().moveEvent(event)
        self._schedule_save_geometry()

    def _get_chat_font_pt(self):
        """与 ChatWindow 文字大小同步：从 assistant_window.chat_font_pt 读取。"""
        default_pt = _chat_font_pt_default()
        return getattr(self.assistant_window, "chat_font_pt", default_pt) if self.assistant_window else default_pt

    def _apply_session_font(self):
        """「会话管理」标题、菜单栏及菜单项字体均与用户设置的文字大小同步；字体按平台适配。"""
        pt = self._get_chat_font_pt()
        f = QFont(ui_font_family(), pt)
        if hasattr(self, "_title_label") and self._title_label:
            self._title_label.setFont(f)
        mb = self.menuBar()
        if mb:
            mb.setFont(f)
        if hasattr(self, "_menu_top") and self._menu_top:
            self._menu_top.setFont(f)

    def _on_config_for_models(self, ok, payload, error):
        """config.get 回调：写入内存并刷新模型列表。"""
        gateway_memory.set_config(ok, payload, error)
        self._refresh_models_from_config()

    def _on_agent_changed(self):
        global _GLOBAL_PINNED_AGENT_ID
        aid = self._agent_combo.currentData()
        if aid is not None:
            self._pinned_agent_id = aid
            _GLOBAL_PINNED_AGENT_ID = aid
        self._refresh_models_from_config()
        self._refresh_gateway_sessions()

    def _on_gateway_refresh_tick(self):
        """定时刷新：窗口可见时拉取 health，保持与 Gateway 同步。"""
        if self.isVisible():
            self._fetch_gateway_health()

    def _start_gateway_refresh_timer(self):
        if not self._gateway_refresh_timer.isActive():
            self._gateway_refresh_timer.start(GATEWAY_SESSION_REFRESH_MS)
            logger.debug(f"会话列表 Gateway 定时刷新已启动，间隔 {GATEWAY_SESSION_REFRESH_MS} ms")

    def _stop_gateway_refresh_timer(self):
        if self._gateway_refresh_timer.isActive():
            self._gateway_refresh_timer.stop()
            logger.debug(f"会话列表 Gateway 定时刷新已停止")

    def _on_show_agent_to_agent_changed(self, state):
        """切换「显示 Agent 对 Agent 会话」时重新过滤并刷新列表。"""
        self._refresh_gateway_sessions()

    def _refresh_models_from_config(self):
        """从内存 config 取 agents.defaults.models 的 key 填充模型列表；当前选中 agent 的 model 标「当前」。"""
        self._models_list.clear()
        ok, payload, _ = gateway_memory.get_config()
        if not ok or not payload or not isinstance(payload, dict):
            self._models_list.addItem(t("no_config_fetch"))
            return
        config = payload.get("config") or payload
        if not isinstance(config, dict):
            self._models_list.addItem(t("no_config"))
            return
        agents = config.get("agents") or {}
        if not isinstance(agents, dict):
            self._models_list.addItem(t("no_config"))
            return
        defaults = agents.get("defaults") or {}
        models_dict = defaults.get("models") or {}
        if not isinstance(models_dict, dict):
            self._models_list.addItem(t("no_model_config"))
            return
        agent_list = agents.get("list") or []
        current_agent_id = self._agent_combo.currentData()
        current_model = None
        for a in agent_list:
            if not isinstance(a, dict):
                continue
            aid = a.get("id") or a.get("agentId") or ""
            if str(aid) == str(current_agent_id):
                current_model = (a.get("model") or "").strip()
                break
        for key in sorted(models_dict.keys()):
            alias = (models_dict.get(key) or {})
            if isinstance(alias, dict):
                alias = (alias.get("alias") or "").strip()
            else:
                alias = ""
            label = (alias or key) + t("available_suffix")
            if current_model and key == current_model:
                label += t("current_suffix")
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, key)
            self._models_list.addItem(item)

    def _get_provider_config_for_model_key(self, model_key):
        """根据 agents.defaults.models 的 key 解析 provider_key（key 中第一个 / 前的部分），从 config.models.providers 取对应配置。返回 (provider_config_dict, provider_key) 或 (None, None)。"""
        if not model_key or not isinstance(model_key, str):
            return None, None
        ok, payload, _ = gateway_memory.get_config()
        if not ok or not payload or not isinstance(payload, dict):
            return None, None
        config = payload.get("config") or payload
        if not isinstance(config, dict):
            return None, None
        models_block = config.get("models") or {}
        if not isinstance(models_block, dict):
            return None, None
        providers = models_block.get("providers") or {}
        if not isinstance(providers, dict):
            return None, None
        provider_key = model_key.split("/")[0].strip() if "/" in model_key else model_key.strip()
        provider_config = providers.get(provider_key)
        if provider_config is None or not isinstance(provider_config, dict):
            return None, provider_key
        return provider_config, provider_key

    def _on_model_double_clicked(self, item):
        """双击模型：根据 key 找到 models.providers[provider_key]，以表单/ Raw 形式展示（与添加模型一样的窗口风格）。"""
        if not item:
            return
        model_key = item.data(Qt.UserRole)
        provider_config, provider_key = self._get_provider_config_for_model_key(model_key)
        if provider_config is None:
            QMessageBox.information(
                self,
                t("model_config_title"),
                t("model_provider_not_found"),
            )
            return
        content = json.dumps(provider_config, ensure_ascii=False, indent=2)
        title = "%s - %s" % (t("model_config_title"), provider_key)
        dialog = ConfigViewDialog(content, title=title, parent=self, parsed_config=provider_config)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _on_models_list_context_menu(self, pos):
        """模型列表右键：复制配置。"""
        item = self._models_list.itemAt(pos)
        if not item:
            return
        menu = QMenu(self)
        menu.addAction(t("copy_config"), lambda: self._copy_model_config(item))
        menu.exec_(self._models_list.mapToGlobal(pos))

    def _copy_model_config(self, item):
        """将当前模型对应的 provider 配置复制到剪贴板。"""
        if not item:
            return
        model_key = item.data(Qt.UserRole)
        provider_config, provider_key = self._get_provider_config_for_model_key(model_key)
        if provider_config is None:
            QMessageBox.information(
                self,
                t("model_config_title"),
                t("model_provider_not_found"),
            )
            return
        text = json.dumps(provider_config, ensure_ascii=False, indent=2)
        QApplication.clipboard().setText(text)
        if self.assistant_window and hasattr(self.assistant_window, "show_bubble_requested"):
            self.assistant_window.show_bubble_requested.emit(t("config_copied"), 1)
        else:
            QMessageBox.information(self, t("tip_title"), t("config_copied"))

    def _on_add_model(self):
        """增加模型：弹出对话框，支持表单模式与 Raw 模式切换；保存时提示暂不支持、去配置文件修改。"""
        dlg = AddModelDialog(self)
        dlg.exec_()

    def _on_delete_model(self):
        """删除模型：暂时不支持，提示去配置文件修改。"""
        QMessageBox.information(
            self, t("delete_model_title"),
            t("delete_model_not_supported"),
        )

    def _on_read_config(self):
        """读取配置：与配置设置里的「读取当前配置」相同，调用 config.get 后弹出只读配置窗口。"""
        gc = self.gateway_client
        if not gc or not gc.is_connected():
            QMessageBox.information(self, t("config_fetch_failed_title"), t("config_not_connected"))
            return
        l2s.send_config_get(gc, callback=self._on_config_get_for_session)

    def _on_config_get_for_session(self, ok, payload, error):
        """config.get 回调：弹出只读配置窗口展示内容（与配置设置窗口逻辑一致）。"""
        if not ok:
            err = (error or {}).get("message", t("unknown_error")) if isinstance(error, dict) else str(error or t("unknown_error"))
            QMessageBox.warning(self, t("config_fetch_failed_title"), t("config_fetch_failed") + "\n" + err)
            return
        if not payload or not isinstance(payload, dict):
            QMessageBox.warning(self, t("config_no_data"), t("config_no_snapshot"))
            return
        gateway_memory.set_config(ok, payload, error)
        raw = payload.get("raw")
        path = payload.get("path") or ""
        exists = payload.get("exists", False)
        valid = payload.get("valid", False)
        content = ""
        if isinstance(raw, str) and raw:
            content = raw
        else:
            config = payload.get("config")
            if config is not None:
                try:
                    content = ("# path: %s\n# exists: %s, valid: %s\n\n" % (path, exists, valid)) + json.dumps(
                        config, ensure_ascii=False, indent=2
                    )
                except Exception as e:
                    content = "config 序列化失败: %s" % e
            else:
                content = "# 无 raw 与 config\n# path: %s\n# exists: %s, valid: %s\n\n%s" % (
                    path, exists, valid, json.dumps(payload, ensure_ascii=False, indent=2)
                )
        parsed = payload.get("config") if isinstance(payload.get("config"), (dict, list)) else None
        dialog = ConfigViewDialog(content, title=t("config_view_title"), parent=self, parsed_config=parsed)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _on_edit_config(self):
        """编辑配置：与配置设置里的「编辑当前配置」相同。当前仅提示暂不展示编辑弹窗。"""
        QMessageBox.information(
            self,
            t("config_edit_dialog_title"),
            t("config_edit_not_supported"),
        )
        return
        # --------- 以下逻辑保留，恢复展示时删掉上面 4 行即可 ---------
        gc = self.gateway_client
        if not gc or not gc.is_connected():
            QMessageBox.information(self, t("config_edit_dialog_title"), t("config_not_connected"))
            return
        ok, payload, _ = gateway_memory.get_config()
        if not ok or not payload or not isinstance(payload, dict):
            QMessageBox.information(
                self, t("config_edit_confirm_title"),
                t("config_please_fetch_then_edit"),
            )
            return
        box = QMessageBox(self)
        box.setWindowTitle(t("config_edit_confirm_title"))
        box.setIcon(QMessageBox.Warning)
        box.setText(t("config_edit_confirm_text"))
        box.setInformativeText(t("config_edit_confirm_info"))
        box.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
        box.setDefaultButton(QMessageBox.Cancel)
        if box.exec_() != QMessageBox.Ok:
            return
        raw = payload.get("raw")
        if isinstance(raw, str) and raw.strip():
            content = raw
        else:
            config = payload.get("config")
            if config is not None:
                try:
                    content = json.dumps(config, ensure_ascii=False, indent=2)
                except Exception:
                    content = json.dumps(payload, ensure_ascii=False, indent=2)
            else:
                content = json.dumps(payload, ensure_ascii=False, indent=2)
        base_hash = payload.get("hash") if isinstance(payload.get("hash"), str) else ""
        edit_dialog = ConfigEditDialog(
            content=content,
            base_hash=base_hash,
            parent=self,
            gateway_client=gc,
            on_save_success=lambda: self._refresh_models_from_config(),
        )
        edit_dialog.show()
        edit_dialog.raise_()
        edit_dialog.activateWindow()

    def _fetch_skills_status(self):
        """请求 skills.status 并填充技能列表（eligible 在前，不可用标出，点击见详情）。"""
        gc = self.gateway_client
        if not gc or not gc.is_connected():
            QMessageBox.information(self, t("skills_status_title"), t("please_connect_gateway"))
            return
        self._skills_list.clear()
        self._skills_list.addItem(t("loading_dots"))
        gc.call(METHOD_SKILLS_STATUS, {}, callback=self._on_skills_status_result)

    def _on_skills_status_result(self, ok, payload, error):
        if not ok:
            self._skills_list.clear()
            msg = (error or {}).get("message", t("request_failed")) if isinstance(error, dict) else str(error or t("request_failed"))
            self._skills_list.addItem(t("fail_item_fmt") % msg)
            return
        self._skills_list.clear()
        skills = (payload or {}).get("skills") if isinstance(payload, dict) else []
        if not isinstance(skills, list):
            self._skills_list.addItem(t("no_skills_data"))
            return
        eligible_first = sorted(skills, key=lambda s: (0 if (isinstance(s, dict) and s.get("eligible")) else 1, (s.get("name") or "")))
        for s in eligible_first:
            if not isinstance(s, dict):
                continue
            name = (s.get("name") or "").strip() or t("unnamed_short")
            eligible = s.get("eligible") is True
            text = name if eligible else name + t("unavailable_suffix")
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, s)
            self._skills_list.addItem(item)

    def _on_skill_item_clicked(self, item):
        if not item:
            return
        data = item.data(Qt.UserRole)
        if not data:
            return
        try:
            content = json.dumps(data, ensure_ascii=False, indent=2)
        except (TypeError, ValueError):
            content = str(data)
        self._show_detail_dialog(t("skill_detail_title"), content)

    def _fetch_cron_list(self):
        """请求 cron.list 并填充定时任务列表（enabled 在前，点击见详情）。"""
        gc = self.gateway_client
        if not gc or not gc.is_connected():
            QMessageBox.information(self, t("cron_title"), t("please_connect_gateway"))
            return
        self._cron_list.clear()
        self._cron_list.addItem(t("loading_dots"))
        gc.call(METHOD_CRON_LIST, {"includeDisabled": True}, callback=self._on_cron_list_result)

    def _on_cron_list_result(self, ok, payload, error):
        if not ok:
            self._cron_list.clear()
            msg = (error or {}).get("message", t("request_failed")) if isinstance(error, dict) else str(error or t("request_failed"))
            self._cron_list.addItem(t("fail_item_fmt") % msg)
            return
        self._cron_list.clear()
        jobs = (payload or {}).get("jobs") if isinstance(payload, dict) else []
        if not isinstance(jobs, list):
            self._cron_list.addItem(t("no_cron_tasks"))
            return
        enabled_first = sorted(jobs, key=lambda j: (0 if (isinstance(j, dict) and j.get("enabled")) else 1, (j.get("name") or "")))
        for j in enabled_first:
            if not isinstance(j, dict):
                continue
            agent_id = (j.get("agentId") or j.get("id") or "").strip() or "-"
            name = (j.get("name") or "").strip() or t("unnamed_short")
            text = "%s - %s" % (agent_id, name)
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, j)
            self._cron_list.addItem(item)

    def _on_cron_item_clicked(self, item):
        if not item:
            return
        data = item.data(Qt.UserRole)
        if not data:
            return
        try:
            content = json.dumps(data, ensure_ascii=False, indent=2)
        except (TypeError, ValueError):
            content = str(data)
        self._show_detail_dialog(t("cron_detail_title"), content)

    def _show_detail_dialog(self, title, content):
        d = QDialog(self)
        d.setWindowTitle(title)
        d.setMinimumSize(400, 300)
        layout = QVBoxLayout(d)
        te = QTextEdit(d)
        te.setReadOnly(True)
        te.setPlainText(content)
        layout.addWidget(te)
        btn = QDialogButtonBox(QDialogButtonBox.Ok)
        btn.accepted.connect(d.accept)
        layout.addWidget(btn)
        d.exec_()

    @staticmethod
    def _parse_session_key(key):
        """解析 sessionKey：agent:A:B -> (agent_id, channel)。非 agent: 前缀返回 (None, None)。"""
        key = (key or "").strip()
        if not key.startswith("agent:"):
            return None, None
        parts = key.split(":", 2)
        if len(parts) < 3:
            return None, None
        return parts[1].strip() or None, parts[2].strip() or None

    @staticmethod
    def _is_agent_to_agent(session_key, agent_ids):
        """sessionKey 形如 agent:main:main 时，若 channel 部分在 agent_ids 中则为 Agent 对 Agent。"""
        agent_id, channel = SessionListWindow._parse_session_key(session_key)
        if not agent_id or not channel:
            return False
        return channel in (agent_ids or set())

    @staticmethod
    def _format_session_key_label(key, is_agent_to_agent):
        """展示用：agent:work:telegram -> work · telegram；agent-to-agent 时追加 (Agent 对 Agent)。"""
        agent_id, channel = SessionListWindow._parse_session_key(key)
        if agent_id is None:
            return key
        seg = "%s · %s" % (agent_id, channel)
        if is_agent_to_agent:
            seg += t("agent_to_agent_suffix")
        return seg

    def _fetch_gateway_health(self):
        gc = self.gateway_client
        if not gc or not gc.is_connected():
            self._gateway_agents = []
            self._agent_combo.blockSignals(True)
            self._agent_combo.clear()
            self._agent_combo.addItem(t("no_gateway_startup"), None)
            self._agent_combo.blockSignals(False)
            self._gateway_session_rows = []
            self._refresh_gateway_list_ui()
            return
        # 文档：先从专用内存取数，再发 health 请求；回调写入由 client 完成，此处只刷新 UI
        mem_ok, mem_payload, mem_err = gateway_memory.get_health()
        if mem_ok and mem_payload:
            self._apply_health_from_payload(mem_ok, mem_payload, mem_err)
        def done(ok, payload, err):
            self._apply_health_from_payload(ok, payload, err)
        l2s.send_health(gc, callback=done)

    def _apply_health_from_payload(self, ok, payload, err):
        """根据 health 结果（内存或回调）解析 agents 并刷新「选择 Agent」与会话列表；优先用内存中 config 的 agent 列表合并 health 的会话。"""
        if not ok or not payload:
            self._gateway_agents = []
            err_msg = (err or {}).get("message", "") if isinstance(err, dict) else str(err or "")
            logger.warning(f"Gateway health 请求失败或无 payload: ok={ok} err={err_msg}")
        else:
            health_agents = payload.get("agents") or []
            health_by_id = {str((a.get("agentId") or a.get("id") or "")).strip(): a for a in health_agents if (a.get("agentId") or a.get("id"))}
            if not health_agents and isinstance(payload.get("sessions"), dict):
                health_by_id["main"] = {"agentId": "main", "name": t("default_main"), "sessions": {"recent": payload["sessions"].get("recent") or []}}
            config_agents = gateway_memory.get_agents_list()
            self._gateway_agents = []
            if config_agents:
                for a in config_agents:
                    aid = (a.get("agentId") or a.get("id") or "").strip()
                    name = (a.get("name") or aid) or t("default_main")
                    h = health_by_id.get(aid) or health_by_id.get("main")
                    sessions = (h or {}).get("sessions") or {}
                    recent = sessions.get("recent") or []
                    self._gateway_agents.append({"agentId": aid or "main", "name": name or t("default_main"), "recent": recent})
            for a in health_agents:
                aid = (a.get("agentId") or a.get("id") or "").strip() or "main"
                if not any(ag.get("agentId") == aid for ag in self._gateway_agents):
                    name = a.get("name") or aid
                    sessions = a.get("sessions") or {}
                    recent = sessions.get("recent") or []
                    self._gateway_agents.append({"agentId": aid, "name": name, "recent": recent})
            if not self._gateway_agents:
                self._gateway_agents.append({"agentId": "main", "name": t("default_main"), "recent": (health_by_id.get("main") or {}).get("sessions", {}).get("recent") or []})
            gateway_logger.debug(f"Gateway health 返回 {len(self._gateway_agents)} 个 Agent")
        self._agent_combo.blockSignals(True)
        self._agent_combo.clear()
        for a in self._gateway_agents:
            self._agent_combo.addItem(f"{a['name']} ({a['agentId']})", a["agentId"])
        pinned = getattr(self, "_pinned_agent_id", None)
        if pinned is not None:
            for i in range(self._agent_combo.count()):
                if self._agent_combo.itemData(i) == pinned:
                    self._agent_combo.setCurrentIndex(i)
                    break
        # 无固定选中时确保有默认选中项，避免 currentIndex() 为 -1 导致「新会话」失败
        if self._agent_combo.currentIndex() < 0 and self._agent_combo.count() > 0:
            self._agent_combo.setCurrentIndex(0)
        self._agent_combo.blockSignals(False)
        self._refresh_models_from_config()
        self._refresh_gateway_sessions()

    def _refresh_gateway_sessions(self):
        self._gateway_session_rows = []
        idx = self._agent_combo.currentIndex()
        if idx < 0 or idx >= len(self._gateway_agents):
            self._refresh_gateway_list_ui()
            return
        agent = self._gateway_agents[idx]
        name = agent.get("name") or agent.get("agentId") or ""
        agent_ids = {ag.get("agentId") or ag.get("id") for ag in self._gateway_agents if (ag.get("agentId") or ag.get("id"))}
        show_a2a = self._show_agent_to_agent_cb.isChecked() if hasattr(self, "_show_agent_to_agent_cb") and self._show_agent_to_agent_cb else False
        for r in agent.get("recent") or []:
            key = (r.get("key") or "").strip()
            if not key:
                continue
            is_a2a = self._is_agent_to_agent(key, agent_ids)
            if not show_a2a and is_a2a:
                continue
            ts = r.get("updatedAt") or 0
            self._gateway_session_rows.append((key, name, ts, is_a2a))
        self._refresh_gateway_list_ui()

    def _refresh_gateway_list_ui(self):
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        self._session_ids = []
        for row in self._gateway_session_rows:
            key = row[0]
            agent_name = row[1] if len(row) > 1 else ""
            ts = row[2] if len(row) > 2 else 0
            is_a2a = row[3] if len(row) > 3 else False
            self._session_ids.append({"key": key, "agent_name": agent_name})
            label = self._format_session_key_label(key, is_a2a)
            if ts:
                try:
                    dt = datetime.utcfromtimestamp(ts / 1000.0)
                    label = "%s  %s" % (label, dt.strftime("%m/%d %H:%M"))
                except Exception:
                    pass
            item = QListWidgetItem(label)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            self.list_widget.addItem(item)
        self.list_widget.blockSignals(False)

    def showEvent(self, event):
        self._apply_session_font()
        self._agent_row_widget.setVisible(True)
        if hasattr(self, "_show_agent_to_agent_row"):
            self._show_agent_to_agent_row.setVisible(True)
        self._select_all_cb.setVisible(True)
        self._fetch_gateway_health()
        self._start_gateway_refresh_timer()
        gc = self.gateway_client
        if gc and gc.is_connected():
            l2s.send_config_get(gc, callback=self._on_config_for_models)
        super().showEvent(event)

    def closeEvent(self, event):
        """关闭会话列表窗口时停止 Gateway 定时刷新。"""
        self._stop_gateway_refresh_timer()
        super().closeEvent(event)

    def _on_menu_about_to_show(self):
        """展开前用助手窗口的统一菜单逻辑刷新「菜单」内容。"""
        self._menu_top.clear()
        if self.assistant_window and hasattr(self.assistant_window, "build_assistant_context_menu"):
            self.assistant_window.build_assistant_context_menu(self._menu_top)

    def _on_open_chat(self):
        if self.assistant_window:
            self.assistant_window.open_chat()
        self.show()
        self.raise_()
        self.activateWindow()

    def _on_clear_cache(self):
        if self.assistant_window:
            self.assistant_window.open_clear_cache()

    def _on_settings(self):
        if self.assistant_window:
            self.assistant_window.open_settings()

    def _on_quit(self):
        if self.assistant_window:
            self.assistant_window.quit_app()

    def _on_select_all_changed(self, state):
        """全选勾选/取消时，同步所有列表项的勾选状态。"""
        self.list_widget.blockSignals(True)
        check = Qt.Checked if state == Qt.Checked else Qt.Unchecked
        for i in range(self.list_widget.count()):
            self.list_widget.item(i).setCheckState(check)
        self.list_widget.blockSignals(False)

    def _on_item_check_changed(self, item):
        """列表项勾选变化时，若全部勾选则全选打勾，否则全选取消。"""
        if not hasattr(self, "_select_all_cb") or not self._select_all_cb:
            return
        all_checked = all(
            self.list_widget.item(i).checkState() == Qt.Checked
            for i in range(self.list_widget.count())
        )
        self._select_all_cb.blockSignals(True)
        self._select_all_cb.setChecked(all_checked)
        self._select_all_cb.blockSignals(False)

    def _new_session(self):
        idx = self._agent_combo.currentIndex()
        if not self._gateway_agents:
            QMessageBox.information(
                self, t("tip_title"),
                t("please_select_agent"),
            )
            return
        if idx < 0 or idx >= len(self._gateway_agents):
            idx = 0
            self._agent_combo.setCurrentIndex(0)
        agent = self._gateway_agents[idx]
        agent_id = agent.get("agentId") or "main"
        agent_name = agent.get("name") or agent_id
        channel = "%s_%s" % (CHANNEL_CLAW_PET_PREFIX, int(time.time()))
        session_key = "agent:%s:%s" % (agent_id, channel)
        self._open_chat(session_key=session_key, agent_name=agent_name)
        self._fetch_gateway_health()

    def _open_selected(self):
        row = self.list_widget.currentRow()
        if row < 0 or row >= len(getattr(self, "_session_ids", [])):
            return
        item = self._session_ids[row]
        if isinstance(item, dict):
            self._open_chat(session_key=item.get("key"), agent_name=item.get("agent_name"))
        # 仅 Gateway 会话，item 恒为 dict

    def _get_checked_session_ids(self):
        """返回当前勾选的所有会话 id（按行序）；仅本地时有意义。"""
        ids = []
        for i in range(min(self.list_widget.count(), len(self._session_ids))):
            if self.list_widget.item(i).checkState() == Qt.Checked:
                x = self._session_ids[i]
                ids.append(x if isinstance(x, str) else x.get("key"))
        return ids

    def _delete_one_session(self, sid):
        """删除一个会话并关闭其窗口、清理引用。仅 Gateway 会话（仅关闭窗口，不删服务器）。"""
        if not isinstance(sid, str) or not sid.startswith("agent:"):
            return False
        if sid in self.chat_windows and self.chat_windows[sid].isVisible():
            self.chat_windows[sid].close()
        if sid in self.chat_windows:
            del self.chat_windows[sid]
        if self.assistant_window and getattr(self.assistant_window, "chat_window", None):
            if self.assistant_window.chat_window and getattr(self.assistant_window.chat_window, "session_id", None) == sid:
                self.assistant_window.chat_window = None
        return True

    def _delete_selected(self):
        """删除勾选的会话；未勾选时删除当前选中行。向服务端发送 sessions.delete 后关闭窗口并刷新列表。"""
        sids = self._get_checked_session_ids()
        if not sids:
            row = self.list_widget.currentRow()
            if row >= 0 and row < len(getattr(self, "_session_ids", [])):
                item = self._session_ids[row]
                sids = [item.get("key") if isinstance(item, dict) else item]
            if not sids:
                QMessageBox.information(self, t("tip_title"), t("please_select_sessions_to_delete"))
                return
        self._delete_gateway_sessions(sids)

    def _delete_gateway_sessions(self, keys):
        """向 Gateway 发送 sessions.delete 删除选中会话；按顺序逐个请求，全部完成后刷新列表并提示。"""
        if QMessageBox.question(
            self, t("confirm_delete_title"),
            t("confirm_delete_sessions_server") % len(keys),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        ) != QMessageBox.Yes:
            return
        gc = self.gateway_client
        if not gc or not gc.is_connected():
            QMessageBox.warning(self, t("tip_title"), t("cannot_delete_server_sessions"))
            return
        failed_list = []
        idx = [0]

        def on_done(ok, payload, error):
            key = keys[idx[0]]
            if not ok:
                msg = (error or {}).get("message", str(error)) if isinstance(error, dict) else str(error)
                failed_list.append((key, msg))
            else:
                self._delete_one_session(key)
            idx[0] += 1
            if idx[0] < len(keys):
                l2s.send_sessions_delete(gc, keys[idx[0]], callback=on_done)
            else:
                self._fetch_gateway_health()
                if failed_list:
                    details = "; ".join("%s: %s" % (k, m) for k, m in failed_list[:3])
                    if len(failed_list) > 3:
                        details += t("etc_suffix")
                    QMessageBox.warning(
                        self, t("delete_done_title"),
                        t("delete_done_partial_fmt") % (len(keys), len(failed_list), details)
                    )
                else:
                    QMessageBox.information(self, t("done_title"), t("sessions_deleted_fmt") % len(keys))

        l2s.send_sessions_delete(gc, keys[0], callback=on_done)

    def _on_session_list_context_menu(self, pos):
        """会话列表右键菜单：复制 sessionKey。"""
        item = self.list_widget.itemAt(pos)
        if not item:
            return
        row = self.list_widget.row(item)
        if row < 0 or row >= len(getattr(self, "_session_ids", [])):
            return
        x = self._session_ids[row]
        key = x.get("key") if isinstance(x, dict) else (x if isinstance(x, str) else "")
        if not key:
            return
        menu = QMenu(self)
        copy_act = menu.addAction(t("copy_session_key"))
        copy_act.triggered.connect(lambda: QApplication.clipboard().setText(key))
        menu.exec_(self.list_widget.mapToGlobal(pos))

    def _on_item_double_click(self, item):
        row = self.list_widget.row(item)
        if row < 0 or row >= len(getattr(self, "_session_ids", [])):
            return
        x = self._session_ids[row]
        if isinstance(x, dict):
            self._open_chat(session_key=x.get("key"), agent_name=x.get("agent_name"))

    def _open_chat(self, session_id=None, session_key=None, agent_name=None):
        from ui.chat_window import ChatWindow
        key = session_key or session_id
        if not key:
            return
        try:
            if key not in self.chat_windows or not self.chat_windows[key].isVisible():
                w = ChatWindow(
                    self.pet_name, self.pet_personality,
                    self.assistant_window,
                    session_id=session_id,
                    session_key=session_key,
                    agent_name=agent_name,
                    gateway_client=self.gateway_client,
                )
                if self.assistant_window:
                    self.assistant_window.chat_window = w
                self.chat_windows[key] = w
            w = self.chat_windows[key]
            w.show()
            w.raise_()
            w.activateWindow()
        except Exception as e:
            logger.exception(f"打开聊天窗口失败: {e}")
            QMessageBox.warning(self, t("tip_title"), t("open_chat_failed_fmt") % e)
