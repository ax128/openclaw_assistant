"""
Cursor AI 追踪数据库监控模块。
监控 .cursor/ai-tracking 下数据库的时间戳变化，用于感知 Cursor 侧活动。
仅在检测到 Cursor DB 时以后台线程运行，不阻塞主线程。
支持 Windows（用户主目录 .cursor）、macOS（.cursor 与 Application Support/Cursor）。
"""
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional

from .logger import logger
from .platform_adapter import is_macos

CURSOR_ACTIVITY_MESSAGE = "主人，检测到 Cursor 客户端干完活了，需要你去看一下噢？"

# 进程内只允许启动一个 Cursor 监控线程，避免重复启动
_cursor_monitor_started = False

TIME_CANDIDATES = [
    "created_at",
    "createdAt",
    "timestamp",
    "time",
    "ts",
    "updated_at",
    "updatedAt",
]


def _cursor_dir_candidates() -> List[Path]:
    """各平台下 Cursor 数据目录的候选路径（含 ai-tracking 的目录）。优先返回常见路径。"""
    home = Path.home()
    candidates = []
    # 通用：用户主目录下的 .cursor
    candidates.append(home / ".cursor")
    if is_macos():
        # macOS：Application Support 下 Cursor 也常见
        candidates.append(home / "Library" / "Application Support" / "Cursor")
    return candidates


def normalize_timestamp(value):
    """将时间戳值规范化为 (raw_ts, seconds, local_dt)，支持秒/毫秒。"""
    if value is None:
        return None
    try:
        ts = int(value)
    except (TypeError, ValueError):
        return None
    if ts > 10_000_000_000:
        seconds = ts / 1000
    else:
        seconds = ts
    local_dt = datetime.fromtimestamp(seconds, tz=timezone.utc).astimezone()
    return ts, seconds, local_dt


class CursorDbMonitor:
    """监控 Cursor ai-tracking 数据库，在时间戳发生较大变化时通过 logger 输出。"""

    def __init__(
        self,
        search_roots=None,
        initial_timestamp=None,
        poll_interval=3,
        min_delta_seconds=60,
        on_activity: Optional[Callable[[str], None]] = None,
    ):
        self.search_roots = search_roots or [Path.home()]
        self.initial_timestamp = initial_timestamp
        self.poll_interval = poll_interval
        self.min_delta_seconds = min_delta_seconds
        self.on_activity = on_activity
        self.base_seconds = None

    def find_cursor_dir(self):
        """查找 Cursor 数据目录（含 ai-tracking）。优先平台候选路径，再 search_roots 下 .cursor，避免 os.walk 主目录导致卡顿。"""
        # 1）先检查平台候选：~/.cursor，macOS 下还有 ~/Library/Application Support/Cursor
        for candidate in _cursor_dir_candidates():
            if candidate.exists() and (candidate / "ai-tracking").exists():
                return candidate
        # 2）再检查 search_roots 下的 .cursor
        target = ".cursor"
        for root in self.search_roots:
            root = Path(root)
            direct = root / target
            if direct.exists() and (direct / "ai-tracking").exists():
                return direct
        candidates = []
        for root in self.search_roots:
            root = Path(root)
            direct = root / target
            if direct.exists():
                candidates.append(direct)
        if not candidates:
            # 直接路径都没有，再尝试递归（较慢，可能卡顿）
            for root in self.search_roots:
                root = Path(root)
                for current_root, dirs, _ in os.walk(root):
                    if target in dirs:
                        c = Path(current_root) / target
                        if (c / "ai-tracking").exists():
                            return c
                        candidates.append(c)
        if not candidates:
            return None
        for c in candidates:
            if (c / "ai-tracking").exists():
                return c
        return candidates[0]

    def find_db_path(self, cursor_dir):
        """返回 ai-code-tracking.db 路径，不存在则 None。"""
        db_path = cursor_dir / "ai-tracking" / "ai-code-tracking.db"
        return db_path if db_path.exists() else None

    def get_latest_row(self, db_path):
        """从数据库中按时间戳字段取最新一行，返回字典或 None。"""
        db_uri = db_path.as_uri() + "?mode=ro"
        best_seconds = None
        best_table = None
        best_col = None
        best_cols = None
        best_row = None
        best_raw_ts = None
        best_local_dt = None
        try:
            with sqlite3.connect(db_uri, uri=True, timeout=2) as conn:
                cur = conn.cursor()
                tables = [
                    t[0]
                    for t in cur.execute(
                        "SELECT name FROM sqlite_master WHERE type='table';"
                    ).fetchall()
                ]
                for table in tables:
                    cols = cur.execute(f"PRAGMA table_info({table});").fetchall()
                    col_names = [c[1] for c in cols]
                    for col in TIME_CANDIDATES:
                        if col not in col_names:
                            continue
                        row = cur.execute(
                            f"SELECT * FROM {table} ORDER BY {col} DESC LIMIT 1;"
                        ).fetchone()
                        if not row:
                            continue
                        value = row[col_names.index(col)]
                        parsed = normalize_timestamp(value)
                        if not parsed:
                            continue
                        raw_ts, seconds, local_dt = parsed
                        if best_seconds is None or seconds > best_seconds:
                            best_seconds = seconds
                            best_table = table
                            best_col = col
                            best_cols = col_names
                            best_row = row
                            best_raw_ts = raw_ts
                            best_local_dt = local_dt
        except sqlite3.Error as e:
            logger.debug(f"数据库操作失败: {e}")
            return None
        if best_seconds is None:
            return None
        return {
            "timestamp": best_raw_ts,
            "seconds": best_seconds,
            "local_dt": best_local_dt,
            "table": best_table,
            "column": best_col,
            "columns": best_cols,
            "row": best_row,
        }

    def set_base_timestamp(self, latest):
        """根据 initial_timestamp 或 latest 设置基准时间。"""
        if self.initial_timestamp is None:
            self.base_seconds = latest["seconds"]
            return
        parsed = normalize_timestamp(self.initial_timestamp)
        if parsed:
            _, seconds, _ = parsed
            self.base_seconds = seconds
        else:
            self.base_seconds = latest["seconds"]

    def _log_row(self, prefix, latest):
        """将最新行信息写入 logger。"""

        for k, v in zip(latest["columns"], latest["row"]):
            logger.debug(f"{k}: {v}")

    def _run_loop(self, db_path):
        """轮询循环（在后台线程中调用）。"""
        last_message_time = time.time()
        is_first_update = True
        while True:
            time.sleep(self.poll_interval)
            latest = self.get_latest_row(db_path)
            if not latest:
                continue
            self.base_seconds = latest["seconds"]
            delta = time.time() - self.base_seconds
            if delta > self.min_delta_seconds and self.base_seconds != last_message_time:
                last_message_time = self.base_seconds
                if is_first_update:
                    is_first_update = False
                    continue
                if self.on_activity :
                    try:
                        self.on_activity(CURSOR_ACTIVITY_MESSAGE)
                    except Exception as e:
                        logger.debug(f"on_activity 回调异常: {e}")
                

    def start(self):
        """同步轮询（阻塞）；一般用 start_in_thread 在后台运行。"""
        cursor_dir = self.find_cursor_dir()
        if not cursor_dir:
            logger.warning(f"未找到 .cursor 目录")
            return
        db_path = self.find_db_path(cursor_dir)
        if not db_path:
            logger.warning(f"找到 .cursor 目录，但未找到数据库: {cursor_dir}")
            return
        logger.info(f"找到数据库: {db_path}")
        latest = self.get_latest_row(db_path)
        if not latest:
            logger.warning(f"未找到可用的时间戳字段（已检查常见字段名）")
            return
        self.set_base_timestamp(latest)
        self._run_loop(db_path)

    def start_in_thread(self) -> Optional[threading.Thread]:
        """
        仅在检测到 Cursor DB 时启动后台线程轮询，不阻塞主线程。
        进程内只启动一次，重复调用直接返回 None。
        返回已启动的线程，未检测到 DB 时返回 None。
        """
        global _cursor_monitor_started
        if _cursor_monitor_started:
            logger.debug(f"Cursor 监控已在运行，跳过重复启动")
            return None
        cursor_dir = self.find_cursor_dir()
        if not cursor_dir:
            logger.debug(f"未找到 .cursor 目录，跳过 Cursor 监控")
            return None
        db_path = self.find_db_path(cursor_dir)
        if not db_path:
            logger.debug(f"未找到 Cursor 数据库，跳过监控")
            return None
        _cursor_monitor_started = True

        def _thread_entry():
            latest = self.get_latest_row(db_path)
            if not latest:
                logger.warning(f"未找到可用的时间戳字段，监控退出")
                return
            self.set_base_timestamp(latest)
            logger.info(f"Cursor 监控已启动（数据库: {db_path}，轮询 {self.poll_interval} 秒）")
            self._run_loop(db_path)

        t = threading.Thread(target=_thread_entry, daemon=True)
        t.start()
        return t


def main():
    monitor = CursorDbMonitor()
    monitor.start()


if __name__ == "__main__":
    main()
