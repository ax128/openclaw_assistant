"""
配置文件设置窗口：读取当前配置、编辑当前配置（可编辑弹窗，JSON 高亮，保存前先格式化再校验，通过后 config.set）。
"""
import json
import re
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QTextEdit, QPlainTextEdit, QLabel, QPushButton,
    QDialog, QDialogButtonBox, QMessageBox, QHBoxLayout, QStackedWidget,
    QTreeWidget, QTreeWidgetItem, QHeaderView,
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QSyntaxHighlighter, QTextCharFormat, QFont
from utils.logger import logger
from utils.i18n import t
from utils.platform_adapter import ui_font_family, ui_font_size_body, ui_window_bg, is_macos
from core.openclaw_gateway import local_to_server as l2s
from core.openclaw_gateway.gateway_memory import gateway_memory


def _validate_config_json(text: str):
    """校验文本是否为合法 JSON；返回 (True, None) 或 (False, 错误信息含片段)。"""
    text = (text or "").strip()
    if not text:
        return False, "配置内容为空"
    try:
        json.loads(text)
        return True, None
    except json.JSONDecodeError as e:
        lines = text.splitlines()
        snippet = ""
        if e.lineno and 1 <= e.lineno <= len(lines):
            start = max(0, e.lineno - 2)
            end = min(len(lines), e.lineno + 1)
            snippet = "\n".join("%d: %s" % (i + 1, lines[i]) for i in range(start, end))
        msg = "第 %s 行附近: %s" % (e.lineno or "?", e.msg or str(e))
        if snippet:
            msg += "\n\n错误片段:\n%s" % snippet
        return False, msg


def _format_config_json(text: str):
    """
    解析 JSON 并格式化为标准缩进（indent=2）；仅当语法正确时返回格式化后的字符串。
    返回 (formatted_string, None) 或 (None, error_message)。
    """
    text = (text or "").strip()
    if not text:
        return None, "配置内容为空"
    try:
        obj = json.loads(text)
        return json.dumps(obj, ensure_ascii=False, indent=2), None
    except json.JSONDecodeError as e:
        lines = text.splitlines()
        snippet = ""
        if e.lineno and 1 <= e.lineno <= len(lines):
            start = max(0, e.lineno - 2)
            end = min(len(lines), e.lineno + 1)
            snippet = "\n".join("%d: %s" % (i + 1, lines[i]) for i in range(start, end))
        msg = "第 %s 行附近: %s" % (e.lineno or "?", e.msg or str(e))
        if snippet:
            msg += "\n\n错误片段:\n%s" % snippet
        return None, msg


class JsonHighlighter(QSyntaxHighlighter):
    """JSON 语法高亮：键名（蓝）、字符串值（绿）、数字（紫）、true/false/null（红）、括号逗号（灰）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rules = []
        fmt_key = QTextCharFormat()
        fmt_key.setForeground(Qt.darkBlue)
        fmt_key.setFontWeight(QFont.Bold)
        self._rules.append((re.compile(r'"(?:[^"\\]|\\.)*"(?=\s*:)'), fmt_key))
        fmt_str = QTextCharFormat()
        fmt_str.setForeground(Qt.darkGreen)
        self._rules.append((re.compile(r'"(?:[^"\\]|\\.)*"(?!\s*:)'), fmt_str))
        fmt_num = QTextCharFormat()
        fmt_num.setForeground(Qt.darkMagenta)
        self._rules.append((re.compile(r'\b-?\d+\.?\d*([eE][+-]?\d+)?\b'), fmt_num))
        fmt_kw = QTextCharFormat()
        fmt_kw.setForeground(Qt.darkRed)
        self._rules.append((re.compile(r'\b(true|false|null)\b'), fmt_kw))
        fmt_punct = QTextCharFormat()
        fmt_punct.setForeground(Qt.darkGray)
        self._rules.append((re.compile(r'[{}\[\],:]'), fmt_punct))

    def highlightBlock(self, text):
        for pattern, fmt in self._rules:
            for m in pattern.finditer(text):
                self.setFormat(m.start(), m.end() - m.start(), fmt)


def _extract_json_from_content(content: str):
    """从可能带注释的 content 中解析 JSON；返回 (obj, None) 或 (None, error_msg)。"""
    text = (content or "").strip()
    if not text:
        return None, "内容为空"
    try:
        return json.loads(text), None
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    if start == -1:
        start = text.find("[")
    if start != -1:
        try:
            return json.loads(text[start:]), None
        except json.JSONDecodeError as e:
            return None, str(e.msg or e)
    return None, "未找到可解析的 JSON"


def _get_at_path(obj, path):
    """按路径 (键或下标元组) 取嵌套值；任一中间步骤缺失则返回 None。"""
    for key in path:
        try:
            if isinstance(obj, dict):
                obj = obj[key]
            elif isinstance(obj, list) and isinstance(key, int) and 0 <= key < len(obj):
                obj = obj[key]
            else:
                return None
        except (KeyError, TypeError, IndexError):
            return None
    return obj


def _format_primitive_value(value):
    """将原始值格式化为短字符串，便于树节点展示。"""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return value if len(value) <= 80 else (value[:77] + "...")
    return str(value)[:80]


class ConfigViewDialog(QDialog):
    """配置文件只读展示：支持 Raw 模式（JSON 文本）与表单模式（层级树，点击展开，只读）。"""

    def __init__(self, content: str, title: str = None, parent=None, parsed_config=None):
        super().__init__(parent)
        self.setWindowTitle(title if title else t("config_view_title"))
        self.setMinimumSize(720, 520)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self._content = content or ""
        self._parsed_config = parsed_config if isinstance(parsed_config, (dict, list)) else None
        self._raw_parsed_fallback = None  # 从 raw 解析出的结构，用于脱敏键的结构回退
        ff, fs, bg = ui_font_family(), ui_font_size_body(), ui_window_bg()
        self.setStyleSheet("""
            QDialog { font-family: '%s'; font-size: %spx; background: %s; }
            QTextEdit { padding: 8px; border: 1px solid #e5e7eb; border-radius: 6px; background: #fafafa; }
            QTreeWidget { padding: 6px; border: 1px solid #e5e7eb; border-radius: 6px; background: #fafafa; }
        """ % (ff, fs, bg))
        if is_macos():
            pass

        layout = QVBoxLayout(self)
        mode_row = QHBoxLayout()
        self._btn_raw = QPushButton(t("config_view_mode_raw"))
        self._btn_form = QPushButton(t("config_view_mode_form"))
        self._btn_raw.setCheckable(True)
        self._btn_form.setCheckable(True)
        self._btn_raw.setChecked(True)
        self._btn_raw.clicked.connect(self._switch_to_raw)
        self._btn_form.clicked.connect(self._switch_to_form)
        mode_row.addWidget(self._btn_raw)
        mode_row.addWidget(self._btn_form)
        mode_row.addStretch()
        layout.addLayout(mode_row)

        self._stack = QStackedWidget()
        self._text = QTextEdit()
        self._text.setReadOnly(True)
        self._text.setPlainText(self._content)
        self._stack.addWidget(self._text)

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels([t("config_view_tree_key"), t("config_view_tree_value")])
        self._tree.setColumnWidth(0, 220)
        self._tree.setAlternatingRowColors(True)
        self._tree.setAnimated(True)
        self._tree.setEditTriggers(QTreeWidget.NoEditTriggers)
        self._tree.setRootIsDecorated(True)
        self._tree.header().setStretchLastSection(True)
        self._stack.addWidget(self._tree)
        self._stack.setCurrentIndex(0)

        layout.addWidget(self._stack)
        btns = QDialogButtonBox(QDialogButtonBox.Close)
        btns.clicked.connect(lambda: self.accept())
        layout.addWidget(btns)

        self._rebuild_tree_if_needed()

    def _rebuild_tree_if_needed(self):
        """若当前为表单页且树为空，则用已解析的 config 或从 content 解析 JSON 并填充树。"""
        if self._stack.currentIndex() != 1:
            return
        if self._tree.topLevelItemCount() > 0:
            return
        obj = self._parsed_config
        if obj is None:
            obj, err = _extract_json_from_content(self._content)
            if err or obj is None:
                QTreeWidgetItem(self._tree, [t("config_view_parse_error"), err or ""])
                return
        # 当使用服务端 parsed_config 时，用 raw 解析结果作为脱敏键的结构回退（api_key_info 等）
        if self._parsed_config is not None and self._content:
            raw_obj, _ = _extract_json_from_content(self._content)
            self._raw_parsed_fallback = raw_obj if isinstance(raw_obj, (dict, list)) else None
        else:
            self._raw_parsed_fallback = None
        self._build_tree_from_value(self._tree.invisibleRootItem(), "", obj, is_root=True)

    def _build_tree_from_value(self, parent_item, key_display, value, is_root=False):
        """用显式栈迭代建树，支持任意深度；对象/数组可折叠，点击展开。子节点用 addChild 显式挂到父节点。
        当服务端将某键整块脱敏为字符串 __OPENCLAW_REDACTED__ 时，用 raw 解析结果中同路径的结构建树。"""
        stack = [(parent_item, key_display, value, is_root, ())]
        top_level_count = 0
        while stack:
            parent_item, key_display, value, is_root, path = stack.pop()
            # 服务端整块脱敏时 value 为字符串 __OPENCLAW_REDACTED__，用 raw 同路径结构回退
            if (
                not is_root
                and value == "__OPENCLAW_REDACTED__"
                and getattr(self, "_raw_parsed_fallback", None) is not None
            ):
                fallback = _get_at_path(self._raw_parsed_fallback, path)
                if isinstance(fallback, (dict, list)):
                    value = fallback
            if isinstance(value, dict):
                if is_root:
                    for k, v in reversed(list(value.items())):
                        stack.append((parent_item, k, v, False, (k,)))
                    top_level_count = len(value)
                else:
                    node = QTreeWidgetItem()
                    node.setText(0, key_display)
                    node.setText(1, "{}")
                    node.setExpanded(False)
                    parent_item.addChild(node)
                    for k, v in reversed(list(value.items())):
                        stack.append((node, k, v, False, path + (k,)))
                continue
            if isinstance(value, list):
                if is_root:
                    for i in reversed(range(len(value))):
                        stack.append((parent_item, "[%d]" % i, value[i], False, (i,)))
                    top_level_count = len(value)
                else:
                    node = QTreeWidgetItem()
                    node.setText(0, key_display + " [%d]" % len(value))
                    node.setText(1, "")
                    node.setExpanded(False)
                    parent_item.addChild(node)
                    for i in reversed(range(len(value))):
                        stack.append((node, "[%d]" % i, value[i], False, path + (i,)))
                continue
            if is_root:
                leaf = QTreeWidgetItem()
                leaf.setText(0, "")
                leaf.setText(1, _format_primitive_value(value))
                parent_item.addChild(leaf)
            else:
                leaf = QTreeWidgetItem()
                leaf.setText(0, key_display)
                leaf.setText(1, _format_primitive_value(value))
                parent_item.addChild(leaf)
        root = self._tree.invisibleRootItem()
        for i in range(min(top_level_count, root.childCount())):
            root.child(i).setExpanded(True)

    def _switch_to_raw(self):
        self._stack.setCurrentIndex(0)
        self._btn_raw.setChecked(True)
        self._btn_form.setChecked(False)

    def _switch_to_form(self):
        self._stack.setCurrentIndex(1)
        self._btn_raw.setChecked(False)
        self._btn_form.setChecked(True)
        self._rebuild_tree_if_needed()

    def set_content(self, content: str, parsed_config=None):
        self._content = content or ""
        self._parsed_config = parsed_config if isinstance(parsed_config, (dict, list)) else None
        self._text.setPlainText(self._content)
        self._tree.clear()
        self._rebuild_tree_if_needed()


class ConfigEditDialog(QDialog):
    """编辑配置弹窗：可编辑文本框（JSON 高亮），保存前先自动格式化再校验，仅语法错误才报错，通过后 config.set。"""

    def __init__(self, content: str, base_hash: str, parent=None, gateway_client=None, on_save_success=None):
        super().__init__(parent)
        self.setWindowTitle(t("config_edit_dialog_title"))
        self.setMinimumSize(720, 520)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self._base_hash = (base_hash or "").strip()
        self._client = gateway_client
        self._on_save_success = on_save_success
        ff, fs, bg = ui_font_family(), ui_font_size_body(), ui_window_bg()
        self.setStyleSheet("""
            QDialog { font-family: '%s'; font-size: %spx; background: %s; }
            QPlainTextEdit { padding: 8px; border: 1px solid #e5e7eb; border-radius: 6px; background: #fff; }
            QPushButton { min-width: 80px; }
        """ % (ff, fs, bg))
        layout = QVBoxLayout(self)
        self._text = QPlainTextEdit()
        self._text.setPlaceholderText(t("config_edit_placeholder"))
        font = self._text.font()
        try:
            from PyQt5.QtGui import QFontDatabase
            for name in ("Consolas", "Monaco", "Courier New"):
                if QFontDatabase().hasFamily(name):
                    font.setFamily(name)
                    break
        except Exception:
            font.setFamily("Courier New")
        self._text.setFont(font)
        self._text.setPlainText(content or "")
        JsonHighlighter(self._text.document())
        layout.addWidget(self._text)
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self._save_btn = QPushButton(t("save"))
        self._save_btn.setCursor(Qt.PointingHandCursor)
        self._save_btn.clicked.connect(self._do_save)
        self._cancel_btn = QPushButton(t("cancel_btn"))
        self._cancel_btn.setCursor(Qt.PointingHandCursor)
        self._cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self._save_btn)
        btn_layout.addWidget(self._cancel_btn)
        layout.addLayout(btn_layout)

    def _do_save(self):
        raw = self._text.toPlainText().strip()
        formatted, err_msg = _format_config_json(raw)
        if formatted is None:
            box = QMessageBox(self)
            box.setWindowTitle(t("config_format_error_title"))
            box.setIcon(QMessageBox.Warning)
            box.setText(t("config_format_error_text"))
            box.setInformativeText(err_msg or t("unknown_error"))
            box.setStandardButtons(QMessageBox.Ok)
            box.exec_()
            return
        self._text.setPlainText(formatted)
        if not self._client or not getattr(self._client, "is_connected", lambda: False)():
            box = QMessageBox(self)
            box.setWindowTitle(t("config_save_failed_title"))
            box.setIcon(QMessageBox.Warning)
            box.setText(t("config_not_connected_save"))
            box.setStandardButtons(QMessageBox.Ok)
            box.exec_()
            return
        self._save_btn.setEnabled(False)
        self._cancel_btn.setEnabled(False)
        l2s.send_config_set(
            self._client,
            raw=formatted,
            base_hash=self._base_hash,
            callback=self._on_config_set_done,
        )

    def _on_config_set_done(self, ok, payload, error):
        self._save_btn.setEnabled(True)
        self._cancel_btn.setEnabled(True)
        if ok:
            if self._on_save_success:
                self._on_save_success()
            self.accept()
            return
        err_dict = error if isinstance(error, dict) else {}
        err = err_dict.get("message", t("unknown_error")) or t("unknown_error")
        details = err_dict.get("details") or {}
        issues = details.get("issues") if isinstance(details, dict) else None
        if issues and isinstance(issues, list):
            lines = []
            for i, item in enumerate(issues[:10]):
                if isinstance(item, dict):
                    path = item.get("path", "")
                    msg = item.get("message", "")
                    lines.append("%s: %s" % (path or "(位置)", msg or "无效"))
                else:
                    lines.append(str(item))
            if len(issues) > 10:
                lines.append("… 共 %s 条" % len(issues))
            err = err + "\n\n" + "\n".join(lines)
        box = QMessageBox(self)
        box.setWindowTitle(t("config_save_failed_title"))
        box.setIcon(QMessageBox.Warning)
        box.setText(t("config_server_reject"))
        box.setInformativeText(err)
        box.setStandardButtons(QMessageBox.Ok)
        box.exec_()


class ConfigSettingWindow(QMainWindow):
    """配置文件设置入口：读取当前配置、编辑当前配置（可编辑弹窗，保存前 JSON 校验，通过后 config.set）。"""

    def __init__(self, assistant_window=None, gateway_client=None):
        super().__init__()
        self.assistant_window = assistant_window
        self._gateway_client = gateway_client if gateway_client is not None else getattr(assistant_window, "gateway_client", None)
        self.setWindowTitle(t("config_setting_title"))
        try:
            from ui.ui_settings_loader import get_ui_setting, save_ui_settings_geometry
            geom = get_ui_setting("config_setting_window.geometry") or {}
            self.setGeometry(
                int(geom.get("x", 200)),
                int(geom.get("y", 150)),
                int(geom.get("width", 420)),
                int(geom.get("height", 200)),
            )
            self._geometry_save_timer = None
        except Exception:
            self.setGeometry(200, 150, 420, 200)
            self._geometry_save_timer = None
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        ff, fs, bg = ui_font_family(), ui_font_size_body(), ui_window_bg()
        self.setStyleSheet("""
            QMainWindow { font-family: '%s'; font-size: %spx; background: %s; }
            QPushButton { padding: 10px 20px; min-width: 120px; }
        """ % (ff, fs, bg))
        if is_macos():
            self.setUnifiedTitleAndToolBarOnMac(True)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        self._status_label = QLabel(t("config_status_hint"))
        try:
            from ui.ui_settings_loader import get_ui_setting
            sl = get_ui_setting("config_setting_window.status_label") or {}
            self._status_label.setStyleSheet(
                "color: %s; font-size: %dpx;" % (sl.get("color", "#6b7280"), int(sl.get("font_size_px", 12)))
            )
        except Exception:
            self._status_label.setStyleSheet("color: #6b7280; font-size: 12px;")
        layout.addWidget(self._status_label)

        self._read_btn = QPushButton(t("config_read_btn"))
        self._read_btn.setCursor(Qt.PointingHandCursor)
        self._read_btn.clicked.connect(self._fetch_config)
        layout.addWidget(self._read_btn)

        self._edit_btn = QPushButton(t("config_edit_btn"))
        self._edit_btn.setCursor(Qt.PointingHandCursor)
        self._edit_btn.clicked.connect(self._open_edit_config)
        layout.addWidget(self._edit_btn)
        layout.addStretch()

    def _schedule_save_geometry(self):
        if getattr(self, "_geometry_save_timer", None):
            self._geometry_save_timer.stop()
        self._geometry_save_timer = QTimer(self)
        self._geometry_save_timer.setSingleShot(True)
        self._geometry_save_timer.timeout.connect(self._save_geometry)
        self._geometry_save_timer.start(400)

    def _save_geometry(self):
        try:
            from ui.ui_settings_loader import save_ui_settings_geometry
            g = self.geometry()
            save_ui_settings_geometry("config_setting_window", g.x(), g.y(), g.width(), g.height())
        except Exception:
            pass

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._schedule_save_geometry()

    def moveEvent(self, event):
        super().moveEvent(event)
        self._schedule_save_geometry()

    def _fetch_config(self):
        """调用 config.get，成功后在弹出窗口中展示只读配置。"""
        client = self._gateway_client
        if not client or not client.is_connected():
            self._status_label.setText(t("config_not_connected"))
            logger.warning(f"配置文件设置：未连接 Gateway")
            return
        self._status_label.setText(t("config_fetching"))
        self._read_btn.setEnabled(False)
        l2s.send_config_get(client, callback=self._on_config_get)

    def _on_config_get(self, ok, payload, error):
        """config.get 回调（主线程）：弹出只读配置窗口展示内容。"""
        self._read_btn.setEnabled(True)
        if not ok:
            err = (error or {}).get("message", t("unknown_error")) if isinstance(error, dict) else str(error or t("unknown_error"))
            self._status_label.setText(t("config_fetch_failed"))
            logger.warning(f"config.get 失败: {err}")
            _dialog = ConfigViewDialog("拉取失败：%s" % err, title=t("config_fetch_failed_title"), parent=self)
            _dialog.exec_()
            return
        if not payload or not isinstance(payload, dict):
            self._status_label.setText(t("config_no_data"))
            _dialog = ConfigViewDialog(t("config_no_snapshot"), title=t("config_no_data"), parent=self)
            _dialog.exec_()
            return
        gateway_memory.set_config(ok, payload, error)
        self._status_label.setText(t("config_fetched_open"))

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

    def _open_edit_config(self):
        """使用已拉取的配置打开编辑弹窗：先提示备份，确认后展示可编辑框，保存时校验 JSON 并 config.set。当前仅提示暂不展示。"""
        QMessageBox.information(
            self,
            t("config_edit_dialog_title"),
            t("config_edit_not_supported"),
        )
        return
        # --------- 以下逻辑保留，恢复展示时删掉上面 4 行即可 ---------
        client = self._gateway_client
        if not client or not client.is_connected():
            self._status_label.setText(t("config_not_connected"))
            return
        ok, payload, _ = gateway_memory.get_config()
        if not ok or not payload or not isinstance(payload, dict):
            self._status_label.setText(t("config_please_fetch_first"))
            box = QMessageBox(self)
            box.setWindowTitle(t("config_edit_confirm_title"))
            box.setIcon(QMessageBox.Information)
            box.setText(t("config_please_fetch_then_edit"))
            box.setStandardButtons(QMessageBox.Ok)
            box.exec_()
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
            gateway_client=client,
            on_save_success=lambda: self._status_label.setText(t("config_saved")),
        )
        edit_dialog.show()
        edit_dialog.raise_()
        edit_dialog.activateWindow()
