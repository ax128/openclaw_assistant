"""
聊天窗口 - 仅聊天 + 会话最小闭环；发送走 OpenClaw Gateway agent，本地保留会话与展示。
支持斜杠命令补全：输入 / 显示候选，输入 /m 等按前缀匹配（与 Telegram/官方 Slash Commands 一致）。
参考：https://docs.openclaw.ai/tools/slash-commands
"""
import json
import os
import uuid
from datetime import datetime, timezone

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QPushButton, QMenuBar, QMenu, QShortcut, QLabel,
    QFrame, QListWidget, QListWidgetItem,
    QMessageBox, QComboBox, QDialog, QDialogButtonBox,
    QApplication,
)
from PyQt5.QtCore import Qt, QTimer, QEvent, QPoint
from PyQt5.QtGui import QTextCursor, QIcon, QFont, QKeySequence

from utils.logger import logger
from utils.i18n import t
from utils.platform_adapter import ui_font_family, send_message_shortcut_for_qt, is_macos
from utils.async_runner import run_in_thread
from ui.ui_settings_loader import get_ui_setting, set_ui_setting_and_save, save_ui_settings_geometry
from core.openclaw_gateway import local_to_server as l2s
from core.openclaw_gateway.gateway_memory import gateway_memory
from utils.logger import gateway_logger

_UI_DIR = os.path.dirname(os.path.abspath(__file__))
def _svg(path): return os.path.join(_UI_DIR, "svg_file", path)


def _font_size_options():
    """从 ui_settings 读取聊天文字大小选项。"""
    opts = get_ui_setting("font.chat.options") or []
    return [(o.get("label", ""), int(o.get("pt", 15))) for o in opts]


def _default_font_pt():
    return int(get_ui_setting("font.chat.default_pt") or 15)


def _popup_dimensions():
    """从 ui_settings 读取弹窗尺寸 preset -> (min_width, max_height)。"""
    presets = get_ui_setting("chat_window_popup.size_presets") or {}
    return {
        k: (int(v.get("min_width_px", 220)), int(v.get("max_height_px", 200)))
        for k, v in presets.items()
        if isinstance(v, dict)
    }


def _clamp_geometry_to_screen(x, y, w, h):
    """将 (x,y,w,h) 限制在主屏可用区域内，保证窗口完全在屏内。返回 (x',y',w',h')。"""
    try:
        app = QApplication.instance()
        if not app:
            return x, y, w, h
        screen = app.primaryScreen()
        if not screen:
            return x, y, w, h
        geo = screen.availableGeometry()
        w = max(200, min(w, geo.width()))
        h = max(200, min(h, geo.height()))
        x = max(geo.x(), min(x, geo.x() + geo.width() - w))
        y = max(geo.y(), min(y, geo.y() + geo.height() - h))
        return int(x), int(y), int(w), int(h)
    except Exception:
        return x, y, w, h


# 斜杠命令列表（与官方 Slash Commands 一致，用于输入补全）
# 参考：https://docs.openclaw.ai/tools/slash-commands 与 使用说明,.log
SLASH_COMMANDS = [
    "/help", "/commands", "/skill", "/status", "/allowlist", "/approve", "/context",
    "/whoami", "/id", "/subagents", "/config", "/debug", "/usage", "/tts",
    "/stop", "/restart", "/dock-telegram", "/dock-discord", "/dock-slack",
    "/activation", "/send", "/reset", "/new", "/think", "/thinking", "/t",
    "/verbose", "/v", "/reasoning", "/reason", "/elevated", "/elev", "/exec",
    "/model", "/models", "/queue", "/bash", "/compact",
]


class ChatWindow(QMainWindow):
    """聊天窗口 - 消息列表 + 输入 + 发送，AI 线程回复"""

    def __init__(self, assistant_name, assistant_personality="", assistant_window=None, session_id=None, session_key=None, agent_name=None, gateway_client=None):
        super().__init__()
        self.assistant_name = assistant_name
        self.assistant_personality = assistant_personality
        self.assistant_window = assistant_window
        self.gateway_client = gateway_client if gateway_client is not None else getattr(assistant_window, "gateway_client", None)
        # 仅 Gateway 会话持久化；本地历史已移除，非 Gateway 为仅内存会话
        self._gateway_mode = bool(session_key and str(session_key).strip().startswith("agent:"))
        if self._gateway_mode:
            self.session_id = (session_key or "").strip()
            self.chat_history = None
            display_name = (agent_name or assistant_name or "Agent").strip() or assistant_name
        else:
            self.session_id = session_id or str(uuid.uuid4())
            self.chat_history = None
            display_name = assistant_name
        cfg = assistant_window.assistant_manager.get_current_assistant_config() if (assistant_window and getattr(assistant_window, "assistant_manager", None)) else None
        _max_msg = get_ui_setting("chat_window.max_display_messages", 200)
        self._max_display_messages = int(cfg.get_timing("chat_max_display_messages", _max_msg)) if cfg else _max_msg
        self._display_blocks = []
        self._loading_timer = None
        self._loading_dots = 0
        self._loading_message_id = None
        self._chat_sending = False  # 与 Web UI canAbort 一致：发送中时可中止
        self._slash_replace_start = -1  # 斜杠补全：待替换区间起点（字符偏移）

        self.setWindowTitle(t("chat_window_title") + display_name)
        geom = get_ui_setting("chat_window.geometry") or {}
        default_x, default_y = 350, 150
        default_w, default_h = 500, 600
        if get_ui_setting("reposition_windows"):
            try:
                app = QApplication.instance()
                if app and app.primaryScreen():
                    geo = app.primaryScreen().availableGeometry()
                    default_x = geo.x() + 80
                    default_y = geo.y() + 80
            except Exception:
                pass
            x, y, w, h = default_x, default_y, default_w, default_h
        else:
            x = int(geom.get("x", default_x))
            y = int(geom.get("y", default_y))
            w = int(geom.get("width", default_w))
            h = int(geom.get("height", default_h))
        x, y, w, h = _clamp_geometry_to_screen(x, y, w, h)
        self.setGeometry(x, y, w, h)
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        if is_macos():
            self.setUnifiedTitleAndToolBarOnMac(True)
        self._font_pt = getattr(assistant_window, "chat_font_pt", _default_font_pt()) if assistant_window else _default_font_pt()
        if os.path.exists(_svg("chat_windows_bot.svg")):
            self.setWindowIcon(QIcon(_svg("chat_windows_bot.svg")))

        self._setup_chat_menu_bar()

        c = QWidget()
        self.setCentralWidget(c)
        layout = QVBoxLayout(c)
        # 与 Web UI 一致：当前会话展示；Gateway 模式显示「切换模型」针对本会话发 sessions.patch
        session_row = QHBoxLayout()
        session_label_text = self.session_id if self._gateway_mode else ("本地 " + (self.session_id or ""))
        self._session_label = QLabel(t("session_label_fmt") % (session_label_text or "-"))
        sl = get_ui_setting("chat_window.session_label") or {}
        self._session_label.setStyleSheet(
            "color: %s; font-size: %spx;" % (sl.get("color", "#6b7280"), int(sl.get("font_size_px", 12)))
        )
        session_row.addWidget(self._session_label)
        session_row.addStretch()
        self._switch_model_btn = QPushButton(t("switch_model_btn"))
        self._switch_model_btn.setToolTip(t("switch_model_tooltip"))
        self._switch_model_btn.clicked.connect(self._on_switch_model)
        self._switch_model_btn.setVisible(self._gateway_mode)
        session_row.addWidget(self._switch_model_btn)
        layout.addLayout(session_row)
        self.msg_edit = QTextEdit()
        self.msg_edit.setReadOnly(True)
        self._apply_font_size()
        layout.addWidget(self.msg_edit)
        row = QHBoxLayout()
        self.input_edit = QTextEdit()
        self.input_edit.setPlaceholderText(t("input_placeholder"))
        self.input_edit.setMaximumHeight(int(get_ui_setting("chat_window.input_edit.max_height_px") or 84))
        self.input_edit.setTabChangesFocus(True)
        self.input_edit.installEventFilter(self)
        self.input_edit.textChanged.connect(self._update_slash_popup)
        self.input_edit.cursorPositionChanged.connect(self._update_slash_popup)
        row.addWidget(self.input_edit)
        # 斜杠命令补全弹窗（输入 / 或 /m 时显示候选）
        self._slash_popup = QFrame(self, Qt.Popup)
        self._slash_popup.setFrameShape(QFrame.StyledPanel)
        popup_style = get_ui_setting("chat_window_popup.style") or {}
        bg = popup_style.get("background", "#fff")
        bd = popup_style.get("border", "1px solid #e5e7eb")
        br = int(popup_style.get("border_radius_px", 6))
        self._slash_popup.setStyleSheet(
            "QFrame { background: %s; border: %s; border-radius: %dpx; } QListWidget { outline: none; }" % (bg, bd, br)
        )
        self._slash_list = QListWidget(self._slash_popup)
        self._slash_list.setMaximumHeight(int(get_ui_setting("chat_window_popup.size_presets.small.max_height_px") or 200))
        self._slash_list.itemClicked.connect(self._on_slash_item_clicked)
        popup_layout = QVBoxLayout(self._slash_popup)
        popup_layout.setContentsMargins(2, 2, 2, 2)
        popup_layout.addWidget(self._slash_list)
        self._abort_btn = QPushButton(t("abort_btn"))
        self._abort_btn.setToolTip(t("abort_tooltip"))
        self._abort_btn.setEnabled(False)
        self._abort_btn.clicked.connect(self._on_abort)
        row.addWidget(self._abort_btn)
        send_btn = QPushButton(t("send_btn"))
        if os.path.exists(_svg("chat_windows_send_msg.svg")):
            send_btn.setIcon(QIcon(_svg("chat_windows_send_msg.svg")))
        send_btn.clicked.connect(self._send)
        row.addWidget(send_btn)
        layout.addLayout(row)
        self._apply_font_size()
        QShortcut(QKeySequence(send_message_shortcut_for_qt()), self).activated.connect(self._send)

        self._load_history()
        if self.assistant_window:
            self.assistant_window.is_thinking = False
        self._geometry_save_timer = None

    def _schedule_save_geometry(self):
        """防抖：延迟保存窗口几何到 config/ui_settings.json。"""
        if getattr(self, "_geometry_save_timer", None):
            self._geometry_save_timer.stop()
        self._geometry_save_timer = QTimer(self)
        self._geometry_save_timer.setSingleShot(True)
        self._geometry_save_timer.timeout.connect(self._save_geometry)
        self._geometry_save_timer.start(400)

    def _save_geometry(self):
        g = self.geometry()
        save_ui_settings_geometry("chat_window", g.x(), g.y(), g.width(), g.height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._schedule_save_geometry()

    def moveEvent(self, event):
        super().moveEvent(event)
        self._schedule_save_geometry()

    def eventFilter(self, obj, event):
        """输入框：Enter 发送，Shift+Enter 换行；斜杠补全弹窗显示时上下键/Enter/Tab/Escape 处理。"""
        if obj is self.input_edit and event.type() == QEvent.KeyPress:
            if self._slash_popup.isVisible():
                if event.key() == Qt.Key_Escape:
                    self._slash_popup.hide()
                    return True
                if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                    self._apply_slash_selection()
                    return True
                if event.key() == Qt.Key_Tab:
                    self._apply_slash_selection()
                    return True
                if event.key() == Qt.Key_Down:
                    self._slash_list.setCurrentRow(min(self._slash_list.currentRow() + 1, self._slash_list.count() - 1))
                    return True
                if event.key() == Qt.Key_Up:
                    self._slash_list.setCurrentRow(max(self._slash_list.currentRow() - 1, 0))
                    return True
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                if event.modifiers() != Qt.ShiftModifier:
                    self._send()
                    return True
        return super().eventFilter(obj, event)

    def _get_slash_prefix_and_start(self):
        """从输入框光标前文本解析斜杠前缀与替换起点；返回 (prefix_after_slash, start_pos) 或 (None, -1)。"""
        cursor = self.input_edit.textCursor()
        pos = cursor.position()
        text = self.input_edit.toPlainText()
        if pos <= 0 or pos > len(text):
            return None, -1
        text_before = text[:pos]
        last_slash = text_before.rfind("/")
        if last_slash < 0:
            return None, -1
        # 斜杠前不能是字母数字（避免匹配到 URL 中的 /）
        if last_slash > 0 and text_before[last_slash - 1].isalnum():
            return None, -1
        prefix_after = text_before[last_slash + 1:]
        if " " in prefix_after or "\n" in prefix_after:
            return None, -1
        return prefix_after, last_slash

    def _update_slash_popup(self):
        """根据当前输入更新斜杠命令补全弹窗：输入 / 显示全部，/m 匹配 m 开头。"""
        prefix_after, start_pos = self._get_slash_prefix_and_start()
        if prefix_after is None:
            self._slash_popup.hide()
            return
        key = ("/" + prefix_after).lower()
        filtered = [c for c in SLASH_COMMANDS if c.lower().startswith(key)]
        if not filtered:
            self._slash_popup.hide()
            return
        self._slash_replace_start = start_pos
        self._slash_list.clear()
        for c in filtered:
            self._slash_list.addItem(QListWidgetItem(c))
        self._slash_list.setCurrentRow(0)
        popup_size = getattr(self.assistant_window, "popup_size", None) or get_ui_setting("chat_window_popup.default_size") or "small"
        dims = _popup_dimensions()
        min_width, max_height = dims.get(popup_size, dims.get("small", (220, 200)))
        row_h = int(get_ui_setting("chat_window_popup.list_row_height_px") or 24)
        pad = int(get_ui_setting("chat_window_popup.list_padding_px") or 2)
        self._slash_list.setMaximumHeight(max_height)
        width = max(min_width, self._slash_list.sizeHintForColumn(0) + pad * 2)
        height = min(max_height, len(filtered) * row_h + pad * 2)
        g = self.input_edit.mapToGlobal(QPoint(0, self.input_edit.height()))
        self._slash_popup.move(g.x(), g.y() + 2)
        self._slash_popup.resize(width, height)
        self._slash_popup.show()

    def _on_slash_item_clicked(self, item):
        if item:
            self._apply_slash_completion(item.text())

    def _apply_slash_selection(self):
        """用当前选中的斜杠命令替换输入框中的斜杠前缀并关闭弹窗。"""
        row = self._slash_list.currentRow()
        if row >= 0 and row < self._slash_list.count():
            item = self._slash_list.item(row)
            if item:
                self._apply_slash_completion(item.text())
        self._slash_popup.hide()

    def _apply_slash_completion(self, command):
        """将输入框中从 _slash_replace_start 到光标的内容替换为 command。"""
        if self._slash_replace_start < 0:
            return
        cursor = self.input_edit.textCursor()
        end_pos = cursor.position()
        cursor.setPosition(self._slash_replace_start, QTextCursor.MoveAnchor)
        cursor.setPosition(end_pos, QTextCursor.KeepAnchor)
        cursor.insertText(command)
        self._slash_popup.hide()
        self._slash_replace_start = -1

    def _setup_chat_menu_bar(self):
        """聊天窗口菜单：文字大小 小/中/大/超大，默认中；菜单字体随用户设置。"""
        menubar = self.menuBar()
        if is_macos():
            menubar.setNativeMenuBar(True)
        self._menu_top = menubar.addMenu(t("menu_label"))
        self._font_menu = self._menu_top.addMenu(t("font_size_menu"))
        self._font_menu.aboutToShow.connect(self._rebuild_font_menu)
        self._rebuild_font_menu()
        self._apply_font_size()

    def _rebuild_font_menu(self):
        self._font_menu.clear()
        for label, pt in _font_size_options():
            a = self._font_menu.addAction(f"{label} ({pt}pt)" + (t("current_suffix") if pt == self._font_pt else ""))
            a.triggered.connect(lambda checked=False, p=pt: self._set_font_size(p))

    def _set_font_size(self, pt):
        self._font_pt = pt
        if self.assistant_window:
            self.assistant_window.chat_font_pt = pt
        try:
            from config.settings import Settings
            s = Settings()
            s.load()
            s.set("chat_font_pt", pt)
            s.save()
        except Exception:
            pass
        set_ui_setting_and_save("font.chat.default_pt", pt)
        self._apply_font_size()

    def _apply_font_size(self):
        """消息区、输入框、菜单栏及所有菜单项字体均随用户设置的文字大小；字体按平台适配。"""
        f = QFont(ui_font_family(), self._font_pt)
        if hasattr(self, "msg_edit") and self.msg_edit:
            self.msg_edit.setFont(f)
        if hasattr(self, "input_edit") and self.input_edit:
            self.input_edit.setFont(f)
        mb = self.menuBar()
        if mb:
            mb.setFont(f)
        if hasattr(self, "_menu_top") and self._menu_top:
            self._menu_top.setFont(f)
        if hasattr(self, "_font_menu") and self._font_menu:
            self._font_menu.setFont(f)

    def _get_assistant_description(self):
        """从当前助手 data.config.description 取设定描述，用于第一条消息与提示词"""
        if not self.assistant_window or not getattr(self.assistant_window, "assistant_manager", None):
            return ""
        assistant = self.assistant_window.assistant_manager.get_current_assistant()
        if not assistant:
            return ""
        cfg = assistant.data.get("config", {}) if getattr(assistant, "data", None) else (assistant.get("config") if hasattr(assistant, "get") else {})
        if not isinstance(cfg, dict):
            cfg = {}
        return (cfg.get("description") or "").strip()

    def _extract_content_text(self, content):
        """从 Gateway 消息 content 提取文本（支持 string 或 content 数组，与 Gateway 协议一致）。"""
        if content is None:
            return ""
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list) and content:
            for part in content:
                if isinstance(part, dict) and "text" in part:
                    t = part.get("text")
                    if isinstance(t, str):
                        return t.strip()
            if content and isinstance(content[0], dict):
                return str(content[0].get("text", "") or "").strip()
        return ""

    def _on_gateway_history_loaded(self, ok, payload, error):
        """Gateway chat.history 回调（主线程）：只展示聊天消息（user/assistant），不展示 system/developer 等系统公告。"""
        if not ok or not payload:
            self._refresh_display(preserve_scroll=False)
            return
        messages = payload.get("messages") if isinstance(payload, dict) else []
        if not isinstance(messages, list):
            messages = []
        for m in messages:
            if not isinstance(m, dict):
                continue
            role = (m.get("role") or "").strip().lower()
            # 与 Gateway 协议一致：只显示聊天消息（user / assistant），不显示 system、developer 等系统公告
            # 如 "System: [2026-02-04 ...] Model switched to ..."、"[Telegram ...]" 等均不展示
            if role not in ("user", "assistant"):
                continue
            text = self._extract_content_text(m.get("content"))
            if not text:
                continue
            ts = m.get("timestamp") or m.get("created_at") or m.get("createdAt")
            if role == "user":
                self._display_blocks.append({"type": "user", "content": text, "id": None, "ts": ts})
            else:
                self._display_blocks.append({"type": "ai", "content": text, "ts": ts})
        if len(self._display_blocks) > self._max_display_messages:
            self._display_blocks = self._display_blocks[-self._max_display_messages:]
        self._refresh_display(preserve_scroll=False)

    def _load_history(self):
        self._display_blocks = []
        self.msg_edit.clear()
        self._remove_loading_message()
        if self._gateway_mode:
            # 与 Gateway 文档一致：拉取该 session 最近 20 条消息，不足则展示全部
            gateway_client = self.gateway_client
            if gateway_client and gateway_client.is_connected():
                l2s.send_chat_history(
                    gateway_client,
                    self.session_id,
                    limit=20,
                    callback=self._on_gateway_history_loaded,
                )
            self._refresh_display(preserve_scroll=False)
            return
        # 非 Gateway：仅内存，无本地持久化
        desc = self._get_assistant_description()
        if desc:
            self._display_blocks.append(f"{self.assistant_name}: {desc}")
        self._refresh_display(preserve_scroll=False)

    def _append_display(self, sender, msg, message_id=None):
        """添加或更新显示消息。sender: 你/AI/系统；message_id 非空时更新已有块。助手消息用助手名显示。"""
        now_iso = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S") + "Z"
        if sender == "你":
            line = {"type": "user", "content": msg, "id": message_id, "ts": now_iso}
        elif sender == "系统":
            line = {"id": message_id, "content": msg, "ts": now_iso} if message_id else {"id": None, "content": "系统: " + msg, "ts": now_iso}
        else:
            line = {"type": "ai", "content": msg, "ts": now_iso}

        if message_id:
            for i, block in enumerate(self._display_blocks):
                if isinstance(block, dict) and block.get("id") == message_id:
                    self._display_blocks[i] = line
                    self._refresh_display(preserve_scroll=False)
                    return
            self._display_blocks.append(line)
        else:
            self._display_blocks.append(line)
        if len(self._display_blocks) > self._max_display_messages:
            self._display_blocks = self._display_blocks[-self._max_display_messages:]
        self._refresh_display(preserve_scroll=False)
    
    def _format_msg_time(self, ts_value):
        """将时间戳格式化为「月-日 时:分:秒」本地时间。支持 ISO 字符串或 Unix 秒/毫秒。"""
        if ts_value is None:
            return ""
        try:
            if isinstance(ts_value, (int, float)):
                sec = float(ts_value)
                if sec >= 1e12:
                    sec = sec / 1000.0
                dt = datetime.utcfromtimestamp(sec)
                dt = dt.replace(tzinfo=timezone.utc).astimezone()
            elif isinstance(ts_value, str):
                s = (ts_value or "").strip().replace("Z", "+00:00")
                if not s:
                    return ""
                dt = datetime.fromisoformat(s)
                if dt.tzinfo is not None:
                    dt = dt.astimezone()
            else:
                return ""
            m, d = dt.month, dt.day
            t = dt.strftime("%H:%M:%S")
            return f"{m}-{d} {t}"
        except (ValueError, TypeError, OSError):
            return ""

    def _block_to_html(self, block):
        """单条显示块转 HTML 片段；若有 ts 则在消息正上方显示灰色小字时间（月-日 时:分:秒）。用户消息时间右对齐，AI/系统消息时间左对齐。"""
        def esc(s):
            return str(s).replace("<", "&lt;").replace(">", "&gt;").replace("&", "&amp;")
        time_line = ""
        if isinstance(block, dict) and "ts" in block:
            time_line = self._format_msg_time(block.get("ts"))
            if time_line:
                is_user = block.get("type") == "user"
                time_class = "msg-time msg-time-right" if is_user else "msg-time msg-time-left"
                time_line = f'<div class="{time_class}">{esc(time_line)}</div>'
        if isinstance(block, dict):
            content = esc(block.get("content", ""))
            if block.get("type") == "user":
                return time_line + f'<div class="user-msg">{content}</div>'
            if block.get("type") == "ai":
                display_content = f"{self.assistant_name}: {content}" if content else str(self.assistant_name)
                return time_line + f'<div class="ai-msg">{esc(display_content)}</div>'
            return time_line + f'<div class="system-msg">{content}</div>'
        return time_line + f'<div class="ai-msg">{esc(block)}</div>'

    def _refresh_display(self, preserve_scroll=True):
        """刷新显示区域（HTML）。preserve_scroll 为 True 时保持滚动位置。"""
        md = get_ui_setting("chat_window.message_display") or {}
        t_fs = int(md.get("msg_time_font_size_px", 11))
        t_cl = md.get("msg_time_color", "#888")
        um = md.get("user_msg") or {}
        um_bg = um.get("background", "#90EE90")
        um_pad = um.get("padding", "8px 12px")
        um_br = int(um.get("border_radius_px", 8))
        um_mw = int(um.get("max_width_pct", 80))
        sys_cl = md.get("system_msg_color", "#666")
        body_pad = int(md.get("body_padding_px", 4))
        css = (
            "<style>\n"
            ".msg-time { font-size: %dpx; color: %s; margin-bottom: 2px; }\n"
            ".msg-time-left { clear: both; text-align: left; }\n"
            ".msg-time-right { clear: both; text-align: right; float: right; }\n"
            ".user-msg { background-color: %s; padding: %s; border-radius: %dpx; margin: 4px 0; text-align: right; display: inline-block; float: right; clear: both; max-width: %d%%; word-wrap: break-word; margin-left: auto; margin-right: 0; }\n"
            ".ai-msg { margin: 4px 0; clear: both; }\n"
            ".system-msg { margin: 4px 0; color: %s; clear: both; }\n"
            "body { margin: 0; padding: %dpx; }\n"
            "</style>"
            % (t_fs, t_cl, um_bg, um_pad, um_br, um_mw, sys_cl, body_pad)
        )
        html_parts = [css] + [self._block_to_html(b) for b in self._display_blocks]
        scrollbar = self.msg_edit.verticalScrollBar()
        scroll_pos = scrollbar.value()
        was_at_bottom = scrollbar.maximum() - scrollbar.value() <= 10
        self.msg_edit.setHtml("".join(html_parts))
        if preserve_scroll and not was_at_bottom:
            QTimer.singleShot(10, lambda: scrollbar.setValue(scroll_pos) if scrollbar else None)
        else:
            self.msg_edit.moveCursor(QTextCursor.End)
    
    def _remove_loading_message(self):
        """移除加载提示消息"""
        if self._loading_message_id:
            self._display_blocks = [
                block for block in self._display_blocks
                if not (isinstance(block, dict) and block.get("id") == self._loading_message_id)
            ]
            self._loading_message_id = None
            if self._loading_timer:
                self._loading_timer.stop()
                self._loading_timer = None
            # 移除加载提示时，保持当前滚动位置
            self._refresh_display(preserve_scroll=True)
    
    def _update_loading_message(self):
        """更新加载提示的省略号（保持当前滚动位置，不强制滚动到底部）"""
        if not self._loading_message_id:
            return
        self._loading_dots = (self._loading_dots + 1) % 4  # 0, 1, 2, 3 循环
        dots = "." * self._loading_dots
        assistant_name = self.assistant_name or t("assistant_default_name")
        # 使用较小的字体显示（通过空格缩进模拟居中效果）
        loading_text = f"  {assistant_name}{t('assistant_working')}{dots}"
        
        # 更新显示块
        for i, block in enumerate(self._display_blocks):
            if isinstance(block, dict) and block.get("id") == self._loading_message_id:
                self._display_blocks[i] = {"id": self._loading_message_id, "content": loading_text}
                break
        
        # 刷新显示（preserve_scroll=True 保持当前滚动位置）
        self._refresh_display(preserve_scroll=True)

    def _on_abort(self):
        """与 Web UI 一致：中止当前聊天运行。"""
        if not self._chat_sending:
            return
        gateway_client = self.gateway_client
        if not gateway_client or not gateway_client.is_connected():
            return
        l2s.send_abort(gateway_client, self.session_id)

    def _on_switch_model(self):
        """对本会话发送 sessions.patch 切换模型；仅 Gateway 模式可用。"""
        if not self._gateway_mode:
            return
        gc = self.gateway_client
        if not gc or not gc.is_connected():
            QMessageBox.warning(self, t("switch_model_btn"), t("no_gateway_switch"))
            return
        ok, payload, _ = gateway_memory.get_config()
        if not ok or not isinstance(payload, dict):
            QMessageBox.warning(self, t("switch_model_btn"), t("no_config_switch"))
            return
        config = payload.get("config") or payload
        agents = (config or {}).get("agents") or {}
        defaults = agents.get("defaults") or {}
        models_dict = defaults.get("models") or {}
        if not isinstance(models_dict, dict) or not models_dict:
            QMessageBox.warning(self, t("switch_model_btn"), t("no_model_config"))
            return
        dlg = QDialog(self)
        dlg.setWindowTitle(t("switch_model_dialog_title"))
        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel(t("switch_model_dialog_label")))
        combo = QComboBox()
        for key in sorted(models_dict.keys()):
            alias = models_dict.get(key) or {}
            if isinstance(alias, dict):
                alias = (alias.get("alias") or "").strip()
            else:
                alias = ""
            combo.addItem((alias or key), key)
        layout.addWidget(combo)
        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(dlg.accept)
        btn_box.rejected.connect(dlg.reject)
        layout.addWidget(btn_box)
        if dlg.exec_() != QDialog.Accepted:
            return
        model_key = combo.currentData()
        if not model_key:
            return

        def on_done(ok_res, _payload, error):
            if ok_res:
                QMessageBox.information(self, t("switch_model_btn"), t("switch_model_success") % model_key)
            else:
                msg = (error or {}).get("message", str(error)) if isinstance(error, dict) else str(error)
                QMessageBox.warning(self, t("switch_model_failed"), msg or t("unknown_error"))

        l2s.send_sessions_patch(gc, self.session_id, {"model": model_key}, callback=on_done)

    def _on_gateway_agent_response(self, ok, payload, error):
        """Gateway agent 请求回调（主线程）：写入内存、移除加载态、展示回复或错误、保存、气泡。"""
        self._chat_sending = False
        if hasattr(self, "_abort_btn") and self._abort_btn:
            self._abort_btn.setEnabled(False)
        gateway_logger.info(
            f"Gateway agent 回调收到 ok={ok} payload_is_none={payload is None} payload_type={type(payload).__name__ if payload is not None else 'N/A'}"
        )
        gateway_memory.set_agent_result(self.session_id, ok, payload, error)
        self._remove_loading_message()
        if self.assistant_window:
            self.assistant_window.is_thinking = False
        if ok and payload is not None:
            # 打印 AI 回复详情到 gateway 日志，不压缩、完整输出便于排查
            try:
                if isinstance(payload, dict):
                    detail = json.dumps(payload, ensure_ascii=False, indent=2)
                    gateway_logger.info(f"Gateway agent AI 回复详情 payload_keys={list(payload.keys()) if payload else []}\npayload={detail}")
                else:
                    gateway_logger.info(f"Gateway agent AI 回复详情 payload_type={type(payload).__name__}\npayload={str(payload)}")
            except Exception as e:
                gateway_logger.warning(f"Gateway agent 打印回复详情失败: {e}")
            logger.info(f"Gateway agent 收到响应: ok={ok} payload_type={type(payload).__name__}")
            # 协议：agent status=ok 时 callback 收到的是 payload.result
            # 实际结构：{ "payloads": [{"text": "...", "mediaUrl": ...}], "meta": {...} }
            # 正文在 payloads[0].text；兼容其它结构（message/text/reply/content/output/response）
            if isinstance(payload, str):
                msg = payload.strip()
            else:
                result = payload if isinstance(payload, dict) else {}
                msg = None
                # 优先从 payloads[0].text 取（OpenClaw Gateway 的实际返回格式）
                payloads = result.get("payloads")
                if isinstance(payloads, list) and payloads:
                    first = payloads[0]
                    if isinstance(first, dict):
                        msg = first.get("text")
                # 兼容其它结构
                if not msg:
                    msg = (
                        result.get("message")
                        or result.get("text")
                        or result.get("reply")
                        or result.get("content")
                        or result.get("output")
                        or result.get("response")
                    )
                if isinstance(msg, dict):
                    msg = (msg.get("message") or msg.get("text") or "").strip()
                else:
                    msg = (msg or "").strip() if msg is not None else ""
            if msg:
                gateway_logger.info(f"Gateway agent 解析出的 msg（完整不压缩）:\n{msg}")
                self._append_display("AI", msg)
                if not self._gateway_mode:
                    run_in_thread(lambda: self._save_message("AI", msg), on_done=None)
                if self.assistant_window and hasattr(self.assistant_window, "show_speech_bubble"):
                    try:
                        self.assistant_window.show_speech_bubble(msg)
                    except Exception:
                        pass
            else:
                # ok 但无文字内容（如 result 为空或结构不同），不按错误展示；打印完整 payload 便于排查
                try:
                    full_payload = json.dumps(payload, ensure_ascii=False, indent=2) if isinstance(payload, dict) else str(payload)
                    gateway_logger.info(f"Gateway agent 解析后 msg 为空，展示「暂无文字回复」 payload_keys={list(payload.keys()) if isinstance(payload, dict) else type(payload).__name__}\npayload={full_payload}")
                except Exception:
                    gateway_logger.info(f"Gateway agent 解析后 msg 为空 payload_keys={list(payload.keys()) if isinstance(payload, dict) else type(payload).__name__}")
                self._append_display("AI", t("no_text_reply"))
            return
        err_msg = (error or {}).get("message", t("no_gateway_reply")) if isinstance(error, dict) else (str(error) or t("no_gateway_reply"))
        gateway_logger.warning(f"Gateway agent 失败或空回复: ok={ok} error={err_msg} payload_is_none={payload is None}")
        logger.warning(f"Gateway agent 失败或空回复: ok={ok} error={err_msg}")
        self._append_display("AI", t("reply_error_fmt") % err_msg)

    def _send(self):
        text = self.input_edit.toPlainText().strip()
        if not text:
            return
        if hasattr(self.input_edit, "setPlainText"):
            self.input_edit.setPlainText("")
        else:
            self.input_edit.clear()
        self._append_display("你", text)
        if not self._gateway_mode:
            self._save_message("你", text)
        self._remove_loading_message()

        if self.assistant_window and hasattr(self.assistant_window, "on_user_activity"):
            self.assistant_window.on_user_activity()

        gateway_client = self.gateway_client
        if not gateway_client or not gateway_client.is_connected():
            self._append_display("AI", t("no_gateway_configure"))
            return

        if self.assistant_window:
            self.assistant_window.is_thinking = True
        self._chat_sending = True
        if hasattr(self, "_abort_btn") and self._abort_btn:
            self._abort_btn.setEnabled(True)
        self._show_loading_message()
        l2s.send_agent(
            gateway_client,
            self.session_id,
            text,
            callback=self._on_gateway_agent_response,
        )

    def _save_message(self, sender, content):
        if self._gateway_mode or not self.chat_history:
            return
        try:
            self.chat_history.add_message(self.session_id, sender, content)
        except Exception as e:
            logger.debug(f"保存聊天历史失败: {e}")

    def _show_loading_message(self):
        """显示加载提示消息"""
        # 移除之前的加载提示（如果有）
        self._remove_loading_message()
        
        # 生成唯一的消息ID
        import time
        self._loading_message_id = f"loading_{int(time.time() * 1000)}"
        self._loading_dots = 1
        
        # 显示初始加载提示（使用特殊格式，不显示"系统:"前缀）
        assistant_name = self.assistant_name or t("assistant_default_name")
        loading_text = f"  {assistant_name}{t('assistant_working')}."
        # 直接添加到显示块，不使用"系统:"前缀
        self._display_blocks.append({"id": self._loading_message_id, "content": loading_text})
        self._refresh_display()
        self.msg_edit.moveCursor(QTextCursor.End)
        
        # 启动定时器动态更新省略号（每500ms更新一次）
        if not self._loading_timer:
            self._loading_timer = QTimer(self)
            self._loading_timer.timeout.connect(self._update_loading_message)
        self._loading_timer.start(500)

    def closeEvent(self, event):
        self._chat_sending = False
        if self.assistant_window:
            self.assistant_window.is_thinking = False
        # 不在此处删除空会话；空会话的删除在「打开/关闭会话列表窗口」时执行
        # 关闭后延迟刷新会话列表，使列表显示最新记录（Gateway 用 health 刷新，本地用 _refresh_list）
        if self.assistant_window and getattr(self.assistant_window, "session_list_window", None):
            slw = self.assistant_window.session_list_window
            if slw:
                from PyQt5.QtCore import QTimer
                def refresh_after_close():
                    if getattr(slw, "_source", None) == "gateway":
                        if hasattr(slw, "_fetch_gateway_health"):
                            slw._fetch_gateway_health()
                    elif hasattr(slw, "_refresh_list"):
                        slw._refresh_list()
                QTimer.singleShot(150, refresh_after_close)
        event.accept()

