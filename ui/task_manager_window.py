"""
任务管理窗口：查询、增加、修改、删除任务；搜索框按关键字过滤；列表表头为任务类型、描述。
支持 Gateway cron.*：连接且 Gateway 支持 cron.list 时使用服务端定时任务；否则显示「当前 Gateway 未开放定时任务，或未连接」并禁用操作。
"""
import os
import time
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTableWidget, QTableWidgetItem, QLineEdit, QPushButton, QLabel, QCheckBox,
    QMessageBox, QHeaderView, QDialog, QFormLayout, QComboBox, QSpinBox, QDateTimeEdit,
    QDialogButtonBox,
)
from PyQt5.QtCore import Qt, QDateTime, QTimer
from PyQt5.QtGui import QFont, QIcon
from utils.logger import logger
from utils.i18n import t
from utils.platform_adapter import ui_font_family, ui_font_size_body, ui_window_bg, is_macos
from utils.async_runner import run_in_thread
from core.openclaw_gateway import local_to_server as l2s

_UI_DIR = os.path.dirname(os.path.abspath(__file__))
def _svg(path): return os.path.join(_UI_DIR, "svg_file", path)


class TaskEditDialog(QDialog):
    """增加/修改任务对话框。task 可为本地任务 dict 或 Gateway cron job dict（含 id/name/schedule/payload）。task_manager 可为 None（仅 Gateway 模式）。支持 Gateway schedule.kind 为 at/every/cron（expr+tz）。"""
    def __init__(self, task_manager, parent=None, task=None):
        super().__init__(parent)
        self.task_manager = task_manager
        self.task = task  # 修改时传入，增加时为 None；Gateway job 含 id/name/schedule/payload
        self._is_gateway_job = isinstance(task, dict) and "id" in task and "schedule" in task
        self._gateway_mode = task_manager is None
        self.setWindowTitle(t("task_edit_title") if task else t("task_add_title"))
        self.setMinimumWidth(400)
        self._form_layout = QFormLayout(self)
        layout = self._form_layout
        self.type_combo = QComboBox()
        self.type_combo.addItems([t("task_type_timed"), t("task_type_recurring")])
        if self._gateway_mode:
            self.type_combo.addItem(t("task_type_cron"))
        self.type_combo.currentIndexChanged.connect(lambda _: self._on_type_changed())
        layout.addRow(t("task_type_label"), self.type_combo)
        self.desc_edit = QLineEdit()
        self.desc_edit.setPlaceholderText(t("task_desc_placeholder"))
        layout.addRow(t("task_desc_label"), self.desc_edit)
        self.dt_edit = QDateTimeEdit()
        self.dt_edit.setCalendarPopup(True)
        self.dt_edit.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.dt_edit.setDateTime(QDateTime.currentDateTime().addSecs(3600))
        layout.addRow(t("task_target_time_label"), self.dt_edit)
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(1, 99999)
        self.interval_spin.setSuffix(t("interval_minutes_suffix"))
        self.interval_spin.setValue(60)
        layout.addRow(t("task_interval_label"), self.interval_spin)
        self.cron_expr_edit = QLineEdit()
        self.cron_expr_edit.setPlaceholderText(t("task_cron_expr_placeholder"))
        layout.addRow(t("task_cron_expr_label"), self.cron_expr_edit)
        self.cron_tz_edit = QLineEdit()
        self.cron_tz_edit.setPlaceholderText(t("task_cron_tz_placeholder"))
        self.cron_tz_edit.setText("UTC")
        layout.addRow(t("task_cron_tz_label"), self.cron_tz_edit)
        self.priority_combo = QComboBox()
        self.priority_combo.addItems([t("task_priority_1"), t("task_priority_2"), t("task_priority_3")])
        self.priority_combo.setToolTip(t("task_priority_tooltip"))
        layout.addRow(t("task_priority_label"), self.priority_combo)
        if task:
            if self._is_gateway_job:
                self.desc_edit.setText(task.get("name", ""))
                payload = task.get("payload") or {}
                if isinstance(payload, dict) and payload.get("kind") == "systemEvent" and payload.get("text"):
                    self.desc_edit.setText(task.get("name", "") or payload.get("text", ""))
                sched = task.get("schedule") or {}
                kind = (sched.get("kind") or "").strip()
                if kind == "at":
                    ts_ms = sched.get("atMs")
                    if ts_ms is not None:
                        self.dt_edit.setDateTime(QDateTime.fromMSecsSinceEpoch(int(ts_ms)))
                    self.type_combo.setCurrentIndex(0)  # timed
                elif kind == "cron" and self._gateway_mode:
                    self.type_combo.setCurrentIndex(2)  # cron
                    self.cron_expr_edit.setText((sched.get("expr") or "").strip())
                    self.cron_tz_edit.setText((sched.get("tz") or "UTC").strip())
                else:
                    every_ms = sched.get("everyMs") or 3600000
                    self.interval_spin.setValue(max(1, int(every_ms) // 60000))
                    self.type_combo.setCurrentIndex(1)  # recurring
                self.priority_combo.setCurrentIndex(1)
            else:
                self.desc_edit.setText(task.get("description", ""))
                if task.get("type") == "timed":
                    self.type_combo.setCurrentIndex(0)
                    ts = task.get("target_timestamp")
                    if ts:
                        self.dt_edit.setDateTime(QDateTime.fromSecsSinceEpoch(int(ts)))
                else:
                    self.type_combo.setCurrentIndex(1)
                    sec = task.get("interval_seconds", 3600)
                    self.interval_spin.setValue(max(1, sec // 60))
                pri = max(1, min(3, int(task.get("priority", 2))))
                self.priority_combo.setCurrentIndex(pri - 1)
        else:
            self.priority_combo.setCurrentIndex(1)  # 新增任务默认 2 级
        if task_manager is None:
            self.priority_combo.setVisible(False)
            try:
                lbl = layout.labelForField(self.priority_combo)
                if lbl is not None:
                    lbl.setVisible(False)
            except Exception:
                pass
        self._on_type_changed()
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addRow(btns)

    def _on_type_changed(self):
        idx = self.type_combo.currentIndex()
        is_timed = idx == 0
        is_recurring = idx == 1
        is_cron = self._gateway_mode and idx == 2
        self.dt_edit.setVisible(is_timed)
        self.interval_spin.setVisible(is_recurring)
        self.cron_expr_edit.setVisible(is_cron)
        self.cron_tz_edit.setVisible(is_cron)
        try:
            for w in (self.dt_edit, self.interval_spin, self.cron_expr_edit, self.cron_tz_edit):
                lbl = self._form_layout.labelForField(w)
                if lbl is not None:
                    lbl.setVisible(w.isVisible())
        except Exception:
            pass

    def get_type(self):
        idx = self.type_combo.currentIndex()
        if self._gateway_mode and idx == 2:
            return "cron"
        return "timed" if idx == 0 else "recurring"

    def get_description(self):
        return self.desc_edit.text().strip() or t("task_default_desc")

    def get_target_timestamp(self):
        return self.dt_edit.dateTime().toSecsSinceEpoch()

    def get_interval_seconds(self):
        return self.interval_spin.value() * 60

    def get_cron_expr(self):
        return (self.cron_expr_edit.text() or "").strip() or "0 0 * * *"

    def get_cron_tz(self):
        return (self.cron_tz_edit.text() or "").strip() or "UTC"

    def get_priority(self):
        """重要级别 1/2/3，数字越小越高。"""
        return self.priority_combo.currentIndex() + 1


class TaskManagerWindow(QMainWindow):
    """任务管理窗口：搜索、列表（任务类型、描述）、查询/增加/修改/删除。支持 Gateway cron.*。"""

    def __init__(self, assistant_window=None):
        super().__init__()
        self.assistant_window = assistant_window
        self.gateway_client = getattr(assistant_window, "gateway_client", None) if assistant_window else None
        self.task_manager = getattr(assistant_window, "task_manager", None) if assistant_window else None
        self._gateway_jobs = []  # Gateway cron.list 返回的 jobs 列表
        self.setWindowTitle(t("task_manager_title"))
        try:
            from ui.ui_settings_loader import get_ui_setting, save_ui_settings_geometry
            geom = get_ui_setting("task_manager_window.geometry") or {}
            self.setGeometry(
                int(geom.get("x", 320)),
                int(geom.get("y", 200)),
                int(geom.get("width", 640)),
                int(geom.get("height", 420)),
            )
            self._geometry_save_timer = None
        except Exception:
            self.setGeometry(320, 200, 640, 420)
            self._geometry_save_timer = None
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        if is_macos():
            self.setUnifiedTitleAndToolBarOnMac(True)
        ff, fs, bg = ui_font_family(), ui_font_size_body(), ui_window_bg()
        self.setStyleSheet(f"QMainWindow {{ font-family: '{ff}'; font-size: {fs}px; background: {bg}; }}")
        if os.path.exists(_svg("task_windows_task.svg")):
            self.setWindowIcon(QIcon(_svg("task_windows_task.svg")))

        c = QWidget()
        self.setCentralWidget(c)
        layout = QVBoxLayout(c)

        # 降级提示：未连接或 Gateway 未开放 cron 时显示
        self._banner_label = QLabel("")
        try:
            from ui.ui_settings_loader import get_ui_setting
            bn = get_ui_setting("task_manager_window.banner") or {}
            self._banner_label.setStyleSheet(
                "color: %s; font-size: %dpx; padding: %dpx;"
                % (bn.get("color", "#6b7280"), int(bn.get("font_size_px", 12)), int(bn.get("padding_px", 8)))
            )
        except Exception:
            self._banner_label.setStyleSheet("color: #6b7280; font-size: 12px; padding: 8px;")
        self._banner_label.setWordWrap(True)
        layout.addWidget(self._banner_label)

        # 搜索栏
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel(t("task_search_label")))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(t("task_search_placeholder"))
        self.search_edit.textChanged.connect(self._refresh_table)
        search_layout.addWidget(self.search_edit)
        layout.addLayout(search_layout)

        # 表格：勾选、级别、任务类型、描述（本地）或 勾选、启用、类型、描述、最后状态（Gateway）
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels([t("task_header_check"), t("task_header_level"), t("task_header_type"), t("task_header_desc"), t("task_header_status")])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.cellDoubleClicked.connect(self._on_cell_double_clicked)
        layout.addWidget(self.table)

        # 按钮：查询、增加、修改、删除、批量删除、运行一次
        btn_layout = QHBoxLayout()
        query_btn = QPushButton(t("task_btn_query"))
        query_btn.clicked.connect(self._refresh_table)
        add_btn = QPushButton(t("task_btn_add"))
        add_btn.clicked.connect(self._on_add)
        edit_btn = QPushButton(t("task_btn_edit"))
        edit_btn.clicked.connect(self._on_edit)
        del_btn = QPushButton(t("task_btn_del"))
        del_btn.clicked.connect(self._on_delete)
        run_btn = QPushButton(t("task_btn_run_once"))
        run_btn.setToolTip(t("task_btn_run_tooltip"))
        run_btn.clicked.connect(self._on_run_once)
        batch_del_btn = QPushButton(t("task_btn_batch_del"))
        batch_del_btn.clicked.connect(self._on_batch_delete)
        btn_layout.addWidget(query_btn)
        btn_layout.addWidget(add_btn)
        btn_layout.addWidget(edit_btn)
        btn_layout.addWidget(run_btn)
        btn_layout.addWidget(del_btn)
        btn_layout.addWidget(batch_del_btn)
        layout.addLayout(btn_layout)
        self._run_btn = run_btn

        self._refresh_table()

    def showEvent(self, event):
        """窗口显示时同步 gateway_client / task_manager 引用并刷新列表"""
        super().showEvent(event)
        if getattr(self, "assistant_window", None):
            self.gateway_client = getattr(self.assistant_window, "gateway_client", None) or self.gateway_client
            self.task_manager = getattr(self.assistant_window, "task_manager", None) or self.task_manager
        self._refresh_table()
        if getattr(self, "table", None) and self.table.viewport():
            self.table.viewport().update()

    def _use_gateway_cron(self):
        """当前是否使用 Gateway cron（已连接且支持 cron.list）。"""
        gc = getattr(self, "gateway_client", None)
        if not gc or not getattr(gc, "is_connected", lambda: False)():
            return False
        return getattr(gc, "supports_method", lambda _: False)("cron.list")

    def _on_cron_list_loaded(self, ok, payload, error):
        """cron.list 回调：更新 _gateway_jobs 并刷新表格。"""
        if ok and isinstance(payload, dict):
            self._gateway_jobs = payload.get("jobs") if isinstance(payload.get("jobs"), list) else []
        else:
            self._gateway_jobs = []
        self._fill_table_from_gateway()

    def _fill_table_from_gateway(self):
        """根据 _gateway_jobs 填充表格（Gateway 模式）。"""
        keyword = (self.search_edit.text() or "").strip().lower()
        rows = []
        for job in self._gateway_jobs:
            if not isinstance(job, dict):
                continue
            name = (job.get("name") or "").strip() or t("task_unnamed")
            if keyword and keyword not in name.lower():
                continue
            sched = job.get("schedule") or {}
            kind = (sched.get("kind") or "").strip()
            if kind == "at":
                type_label = t("task_type_timed")
            elif kind == "cron":
                type_label = t("task_type_cron")
            else:
                type_label = t("task_type_recurring")
            enabled = job.get("enabled", True)
            state = job.get("state") or {}
            last_status = (state.get("lastStatus") or "").strip() or "-"
            rows.append((job, enabled, type_label, name, last_status))
        self.table.setRowCount(len(rows))
        for r, (job, enabled, type_label, name, last_status) in enumerate(rows):
            cb = QCheckBox()
            self.table.setCellWidget(r, 0, cb)
            self.table.setItem(r, 1, QTableWidgetItem(t("task_enabled") if enabled else t("task_disabled")))
            self.table.setItem(r, 2, QTableWidgetItem(type_label))
            self.table.setItem(r, 3, QTableWidgetItem(name))
            self.table.setItem(r, 4, QTableWidgetItem(last_status))
            self.table.item(r, 2).setData(Qt.UserRole, job.get("id"))
            self.table.item(r, 2).setData(Qt.UserRole + 1, job)
        if getattr(self, "_run_btn", None):
            self._run_btn.setEnabled(True)
        self._banner_label.setText("")
        self._banner_label.setVisible(False)

    def _pending_and_completed_lists(self):
        """未完成任务与已完成任务 [(type_label, desc, tid, task_dict), ...] 各一段。"""
        if not self.task_manager:
            return [], []
        pending = self.task_manager.get_pending_tasks()
        pending_rows = []
        for t in pending.get("timed", []):
            pending_rows.append((t("task_type_timed"), t.get("description", ""), t.get("id"), t))
        for t in pending.get("recurring", []):
            pending_rows.append((t("task_type_recurring"), t.get("description", ""), t.get("id"), t))
        completed_rows = []
        for t in self.task_manager.get_completed_tasks():
            label = t("task_type_timed") if t.get("type") == "timed" else t("task_type_recurring")
            completed_rows.append((label, t.get("description", ""), t.get("id"), t))
        return pending_rows, completed_rows

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
            save_ui_settings_geometry("task_manager_window", g.x(), g.y(), g.width(), g.height())
        except Exception:
            pass

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._schedule_save_geometry()

    def moveEvent(self, event):
        super().moveEvent(event)
        self._schedule_save_geometry()

    def _refresh_table(self):
        if self._use_gateway_cron():
            gc = self.gateway_client
            l2s.send_cron_list(gc, include_disabled=True, callback=self._on_cron_list_loaded)
            self._banner_label.setVisible(False)
            self._banner_label.setText("")
            return
        # 本地模式或无 Gateway
        if not self.task_manager:
            self._banner_label.setText(t("task_banner_no_cron"))
            self._banner_label.setVisible(True)
            self.table.setRowCount(0)
            if getattr(self, "_run_btn", None):
                self._run_btn.setEnabled(False)
            return
        self._banner_label.setVisible(False)
        self._banner_label.setText("")
        keyword = (self.search_edit.text() or "").strip().lower()
        pending_rows, completed_rows = self._pending_and_completed_lists()
        if keyword:
            pending_rows = [(a, b, c, d) for a, b, c, d in pending_rows if keyword in (b or "").lower()]
            completed_rows = [(a, b, c, d) for a, b, c, d in completed_rows if keyword in (b or "").lower()]
        rows = []
        for _, (a, b, c, task_dict) in enumerate(pending_rows):
            pri = max(1, min(3, int(task_dict.get("priority", 2))))
            rows.append((a, b, c, True, pri))
        sep_row_index = len(rows)
        for (a, b, c, task_dict) in completed_rows:
            pri = max(1, min(3, int(task_dict.get("priority", 2))))
            rows.append((a, b, c, False, pri))
        need_sep = len(completed_rows) > 0
        n = len(rows) + (1 if need_sep else 0)
        self.table.setRowCount(n)
        r = 0
        for type_label, desc, tid, is_pending, priority in rows:
            if need_sep and r == sep_row_index:
                self.table.setSpan(r, 0, 1, 5)
                sep = QLabel(t("task_section_done"))
                sep.setAlignment(Qt.AlignCenter)
                sep.setStyleSheet("background: #e5e7eb; color: #374151; font-weight: 600; padding: 8px;")
                self.table.setCellWidget(r, 0, sep)
                r += 1
            cb = QCheckBox()
            self.table.setCellWidget(r, 0, cb)
            self.table.setItem(r, 1, QTableWidgetItem(str(priority)))
            self.table.setItem(r, 2, QTableWidgetItem(type_label))
            self.table.setItem(r, 3, QTableWidgetItem(desc or ""))
            self.table.setItem(r, 4, QTableWidgetItem(""))
            self.table.item(r, 2).setData(Qt.UserRole, tid)
            self.table.item(r, 2).setData(Qt.UserRole + 1, is_pending)
            r += 1
        if getattr(self, "_run_btn", None):
            self._run_btn.setEnabled(False)
        if r > 0 and self.table.rowCount() > 0:
            self.table.selectRow(0)

    def _on_cell_double_clicked(self, row, column):
        """双击行打开任务详情（编辑）。"""
        self.table.setCurrentCell(row, 0)
        if self._use_gateway_cron():
            if self._selected_gateway_job():
                self._on_edit()
        else:
            tid = self._selected_task_id()
            if tid and self.table.item(row, 2) is not None:
                self._on_edit()

    def _selected_task_id(self):
        row = self.table.currentRow()
        if row < 0:
            return None
        it = self.table.item(row, 2)
        return it.data(Qt.UserRole) if it else None

    def _selected_gateway_job(self):
        """当前选中行的 Gateway job 对象（仅 Gateway 模式有效）。"""
        row = self.table.currentRow()
        if row < 0:
            return None
        it = self.table.item(row, 2)
        if not it:
            return None
        job = it.data(Qt.UserRole + 1)
        return job if isinstance(job, dict) and job.get("id") else None

    def _selected_is_pending(self):
        """当前选中行是否为未完成任务（分隔行或无 item 则为 False）"""
        row = self.table.currentRow()
        if row < 0:
            return False
        it = self.table.item(row, 2)
        if not it:
            return False
        return bool(it.data(Qt.UserRole + 1))

    def _get_checked_task_ids(self):
        """返回所有勾选行的 task_id 或 job_id 列表（不含分隔行）。本地为 task_id，Gateway 为 job.id。"""
        ids = []
        for row in range(self.table.rowCount()):
            it = self.table.item(row, 2)
            if not it:
                continue
            tid = it.data(Qt.UserRole)
            if not tid:
                continue
            w = self.table.cellWidget(row, 0)
            if isinstance(w, QCheckBox) and w.isChecked():
                ids.append(tid)
        return ids

    def _on_add(self):
        if self._use_gateway_cron():
            d = TaskEditDialog(None, self, task=None)
            if d.exec_() != QDialog.Accepted:
                return
            desc = d.get_description()
            task_type = d.get_type()
            if task_type == "timed":
                ts_sec = d.get_target_timestamp()
                schedule = {"kind": "at", "atMs": int(ts_sec) * 1000}
            elif task_type == "cron":
                schedule = {"kind": "cron", "expr": d.get_cron_expr(), "tz": d.get_cron_tz()}
            else:
                interval_sec = d.get_interval_seconds()
                schedule = {"kind": "every", "everyMs": int(interval_sec) * 1000}
            payload = {"kind": "systemEvent", "text": desc}

            def on_done(ok_res, _pl, err):
                if ok_res:
                    self._refresh_table()
                    QMessageBox.information(self, t("done_title"), t("task_done_added"))
                else:
                    msg = (err or {}).get("message", str(err)) if isinstance(err, dict) else str(err)
                    QMessageBox.warning(self, t("fail_title"), msg or t("task_fail_add_fmt"))

            l2s.send_cron_add(
                self.gateway_client,
                name=desc,
                enabled=True,
                schedule=schedule,
                payload=payload,
                callback=on_done,
            )
            return
        if not self.task_manager:
            QMessageBox.warning(self, t("tip_title"), t("task_no_manager"))
            return
        d = TaskEditDialog(self.task_manager, self, task=None)
        if d.exec_() != QDialog.Accepted:
            return
        desc = d.get_description()
        task_type = d.get_type()
        target_ts = d.get_target_timestamp()
        interval_seconds = d.get_interval_seconds()
        user_request = d.get_description()
        def worker():
            _desc = desc
            if hasattr(self.task_manager, "format_task_description_sync"):
                try:
                    formatted = self.task_manager.format_task_description_sync(_desc, task_type, _desc)
                    _desc = (formatted or _desc).strip() or _desc
                except Exception:
                    pass
            task_id = f"task_{int(time.time())}"
            if task_type == "timed":
                ok = self.task_manager.add_timed_task(
                    task_id=task_id,
                    description=_desc,
                    target_timestamp=float(target_ts),
                    user_request=user_request,
                    skip_ai_format=True,
                    priority=d.get_priority(),
                )
            else:
                ok = self.task_manager.add_recurring_task(
                    task_id=f"recurring_{int(time.time())}",
                    description=_desc,
                    interval_seconds=interval_seconds,
                    user_request=user_request,
                    skip_ai_format=True,
                    priority=d.get_priority(),
                )
            return ok
        def done(ok):
            if ok:
                self._refresh_table()
                QMessageBox.information(self, t("done_title"), t("task_done_added"))
            else:
                QMessageBox.warning(self, t("fail_title"), t("task_fail_add_id_conflict"))
        run_in_thread(worker, on_done=done)

    def _on_edit(self):
        if self._use_gateway_cron():
            job = self._selected_gateway_job()
            if not job:
                QMessageBox.information(self, t("tip_title"), t("task_please_select_to_edit"))
                return
            d = TaskEditDialog(None, self, task=job)
            if d.exec_() != QDialog.Accepted:
                return
            desc = d.get_description()
            task_type = d.get_type()
            if task_type == "timed":
                ts_sec = d.get_target_timestamp()
                schedule = {"kind": "at", "atMs": int(ts_sec) * 1000}
            elif task_type == "cron":
                schedule = {"kind": "cron", "expr": d.get_cron_expr(), "tz": d.get_cron_tz()}
            else:
                interval_sec = d.get_interval_seconds()
                schedule = {"kind": "every", "everyMs": int(interval_sec) * 1000}
            payload = {"kind": "systemEvent", "text": desc}

            def on_done(ok_res, _pl, err):
                if ok_res:
                    self._refresh_table()
                    QMessageBox.information(self, t("done_title"), t("task_done_updated"))
                else:
                    msg = (err or {}).get("message", str(err)) if isinstance(err, dict) else str(err)
                    QMessageBox.warning(self, t("fail_title"), msg or t("task_fail_update"))

            l2s.send_cron_update(
                self.gateway_client,
                job_id=job.get("id"),
                patch={"name": desc, "schedule": schedule, "payload": payload},
                callback=on_done,
            )
            return
        tid = self._selected_task_id()
        if not tid or not self.task_manager:
            QMessageBox.information(self, "提示", "请先选中一条待修改的任务")
            return
        if not self._selected_is_pending():
            QMessageBox.information(self, t("tip_title"), t("task_please_edit_pending_only"))
            return
        task = self.task_manager.get_task(tid)
        if not task:
            QMessageBox.warning(self, t("tip_title"), t("task_not_found"))
            return
        d = TaskEditDialog(self.task_manager, self, task=task)
        if d.exec_() != QDialog.Accepted:
            return
        desc = d.get_description()
        target_ts = d.get_target_timestamp()
        interval_seconds = d.get_interval_seconds()
        def worker():
            return self.task_manager.update_task(
                tid,
                description=desc,
                target_timestamp=target_ts if task.get("type") == "timed" else None,
                interval_seconds=interval_seconds if task.get("type") == "recurring" else None,
                priority=d.get_priority(),
            )
        def done(ok):
            if ok:
                self._refresh_table()
                QMessageBox.information(self, t("done_title"), t("task_done_updated"))
            else:
                QMessageBox.warning(self, t("fail_title"), t("task_fail_update"))
        run_in_thread(worker, on_done=done)

    def _on_delete(self):
        if self._use_gateway_cron():
            job = self._selected_gateway_job()
            if not job:
                QMessageBox.information(self, t("tip_title"), t("task_please_select_to_del"))
                return
            if QMessageBox.question(
                self, t("confirm_delete_title"),
                t("confirm_delete_task"),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            ) != QMessageBox.Yes:
                return

            def on_done(ok_res, _pl, err):
                if ok_res:
                    self._refresh_table()
                else:
                    msg = (err or {}).get("message", str(err)) if isinstance(err, dict) else str(err)
                    QMessageBox.warning(self, t("fail_title"), msg or t("task_fail_del"))

            l2s.send_cron_remove(self.gateway_client, job_id=job.get("id"), callback=on_done)
            return
        tid = self._selected_task_id()
        if not tid or not self.task_manager:
            QMessageBox.information(self, t("tip_title"), t("task_please_select_to_del"))
            return
        if QMessageBox.question(
            self, t("confirm_delete_title"),
            t("confirm_delete_task"),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        ok = self.task_manager.delete_task(tid)
        if ok:
            self._refresh_table()
            if getattr(self, "table", None) and self.table.viewport():
                self.table.viewport().update()
        else:
            QMessageBox.warning(self, t("fail_title"), t("task_fail_del"))

    def _on_run_once(self):
        """对选中任务执行 cron.run（仅 Gateway 模式）。"""
        if not self._use_gateway_cron():
            return
        job = self._selected_gateway_job()
        if not job:
            QMessageBox.information(self, t("tip_title"), t("task_please_select_to_run"))
            return

        def on_done(ok_res, _pl, err):
            if ok_res:
                self._refresh_table()
                QMessageBox.information(self, t("done_title"), t("task_done_run_once"))
            else:
                msg = (err or {}).get("message", str(err)) if isinstance(err, dict) else str(err)
                QMessageBox.warning(self, t("fail_title"), msg or t("task_fail_run"))

        l2s.send_cron_run(self.gateway_client, job_id=job.get("id"), mode="force", callback=on_done)

    def _on_batch_delete(self):
        ids = self._get_checked_task_ids()
        if not ids:
            QMessageBox.information(self, t("tip_title"), t("task_please_select_to_batch_del"))
            return
        if self._use_gateway_cron():
            if QMessageBox.question(
                self, t("confirm_batch_delete_title"),
                t("confirm_batch_delete_fmt") % len(ids),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            ) != QMessageBox.Yes:
                return
            remaining = len(ids)
            done = [0]

            def per_done(ok_res, _pl, err):
                done[0] += 1
                if done[0] >= remaining:
                    self._refresh_table()
                    QMessageBox.information(self, t("done_title"), t("task_done_deleted_fmt") % remaining)

            for jid in ids:
                l2s.send_cron_remove(self.gateway_client, job_id=jid, callback=per_done)
            return
        if not self.task_manager:
            QMessageBox.warning(self, t("tip_title"), t("task_no_manager_short"))
            return
        if QMessageBox.question(
            self, t("confirm_batch_delete_title"),
            t("confirm_batch_delete_fmt") % len(ids),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        ok_count = 0
        for tid in ids:
            if self.task_manager.delete_task(tid):
                ok_count += 1
        self._refresh_table()
        if getattr(self, "table", None) and self.table.viewport():
            self.table.viewport().update()
        QMessageBox.information(self, t("done_title"), t("task_done_deleted_fmt") % ok_count)
