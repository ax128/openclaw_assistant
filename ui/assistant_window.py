"""
助手主窗口
透明无边框 + QLabel 显示 PNG + QTimer 播放帧 + 右键菜单 + 移动/技能/任务
"""
import os
import re
import time

from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QPoint
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (
    QWidget, QLabel, QApplication, QMenu,
)

from utils.logger import logger
from utils.platform_adapter import is_macos
from utils.i18n import t, get_locale
from ui.ui_settings_loader import get_ui_setting
from core.movement import MovementController
from core.assistant_data import DEFAULT_STATE_TO_SPRITE_FOLDER
from utils.skill_extract import extract_random_skill
from core.openclaw_gateway import local_to_server as l2s


def load_frames(sprites_path, action="idle", scale_size=None, state_to_folder=None):
    """按状态加载 PNG 帧。action 为状态名；state_to_folder 来自 data.state_to_sprite_folder，缺省用默认映射。"""
    if not sprites_path or not os.path.isdir(sprites_path):
        return []
    mapping = state_to_folder if state_to_folder else DEFAULT_STATE_TO_SPRITE_FOLDER
    folder = mapping.get(action, "idle")
    action_dir = os.path.join(sprites_path, folder)
    files = []
    if os.path.isdir(action_dir):
        # 新结构：sprites/idle/1.png, 2.png, ...
        files = [f for f in os.listdir(action_dir) if f.endswith(".png")]
        def order(name):
            m = re.search(r"(\d+)\.png$", name)
            return (int(m.group(1)), name) if m else (0, name)
        files.sort(key=order)
        base_path = action_dir
    if not files:
        # 旧结构：sprites/idle_1.png, idle_2.png, ...
        files = [f for f in os.listdir(sprites_path)
                 if f.startswith(folder + "_") and f.endswith(".png")]
        def order_flat(name):
            m = re.search(r"_(\d+)\.png$", name)
            return (int(m.group(1)), name) if m else (0, name)
        files.sort(key=order_flat)
        base_path = sprites_path
    pixmaps = []
    for f in files:
        path = os.path.join(base_path, f)
        px = QPixmap(path)
        if scale_size and px.width() and px.height() and (px.width() != scale_size[0] or px.height() != scale_size[1]):
            px = px.scaled(scale_size[0], scale_size[1],
                           Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        pixmaps.append(px)
    return pixmaps


class AssistantWindow(QWidget):
    """助手主窗口：透明、无边框、动画、移动、右键菜单、气泡"""
    show_bubble_requested = pyqtSignal(str, int)  # (消息文本, 重要度 1/2/3，数字越小越重要)；高级会顶掉低级，未传默认 2
    bubble_close_after_voice_ms = pyqtSignal(int)  # 语音结束后在主线程设置气泡 N 秒后关闭

    def __init__(self, assistant_manager, update_interval=50, settings=None, gateway_client=None):
        super().__init__()
        self.assistant_manager = assistant_manager
        self.update_interval = update_interval
        self.settings = settings
        self.gateway_client = gateway_client  # OpenClaw Gateway 客户端，供聊天/会话对接
        self._drag_start = None
        self._did_drag = False  # 本次手势是否发生过拖动，用于区分「拖动」与「双击」
        self._last_click_was_clean = False  # 上一笔左键释放时是否为「按下→释放、未移动」；只有上一笔干净时，双击才打开聊天
        self._bubble_update_pending = False  # 拖动时是否已排队延迟更新气泡位置
        self.is_dragging = False
        self.is_paused_by_interaction = False
        self.last_interaction_time = 0.0
        self.pause_resume_delay = 10.0  # 下面从 config 覆盖
        self.last_speed_level = None
        self.is_thinking = False
        self.speech_bubble = None
        self._bubble_done_walk_timer = None  # 气泡关闭后 20 秒切回 walk
        self.movement_controller = None
        self.chat_window = None
        self.settings_window = None
        self.session_list_window = None
        self.clear_cache_window = None
        # 聊天/会话列表共用文字大小、弹窗大小，优先从 Settings，无则从 ui_settings 读取
        try:
            from config.settings import Settings
            from ui.ui_settings_loader import get_ui_setting
            s = Settings()
            s.load()
            self.chat_font_pt = int(s.get("chat_font_pt") or get_ui_setting("font.chat.default_pt") or 15)
            _ps = (s.get("popup_size") or get_ui_setting("chat_window_popup.default_size") or "small").strip().lower()
            self.popup_size = _ps if _ps in ("small", "medium", "large") else "small"
        except (OSError, ValueError, TypeError):
            try:
                from ui.ui_settings_loader import get_ui_setting
                self.chat_font_pt = int(get_ui_setting("font.chat.default_pt") or 15)
                _ps = (get_ui_setting("chat_window_popup.default_size") or "small").strip().lower()
                self.popup_size = _ps if _ps in ("small", "medium", "large") else "small"
            except Exception:
                self.chat_font_pt = 15
                self.popup_size = "small"

        self._state_frames = {}
        self._available_states = set()  # 有精灵图的状态，仅这些状态可切换
        self._current_state = "happy"
        self._frame_index = 0
        self._display_size = (150, 150)
        self._forced_state = None       # 用户自定义强制状态
        self._forced_state_until = 0.0   # 强制截止时间戳，1 小时后解除
        self._last_position_flush = 0.0  # 上次位置落盘时间，用于节流（约 2s 落盘一次）
        self._last_bubble_show_time = 0.0  # 气泡最小间隔（约 400ms），避免频繁闪动
        self._current_bubble_importance = 0  # 当前气泡重要度（1 最高）；0 表示无气泡，关闭时清零
        self._bubble_queue = []  # [(text, importance), ...]，按重要度升序（高级在前）、同级别 FIFO
        self._drag_ended_ts = None  # 松开鼠标结束拖拽的时间戳，3 秒内保持 drag 再切 happy
        # 状态机：任何状态切换至少保持 30 秒；30 秒无操作或默认 1 分钟后切 walk
        self._state_hold_until = 0.0     # 状态最少保持到此时间戳
        self._last_user_action_ts = time.time()  # 最后一次用户操作；启动时视为“刚操作”，默认 happy 1 分钟
        self._last_applied_state = None  # 已写入 pet 的状态，仅当变化时写盘
        self._drag_position_flush_ts = 0.0  # 拖拽时上次写位置的时刻，用于节流（约 100ms）

        _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        pet = assistant_manager.get_current_assistant()
        if not pet:
            raise RuntimeError("无当前助手，无法初始化 AssistantWindow")
        pet_config = assistant_manager.get_current_assistant_config()
        if pet_config:
            size_level = pet_config.get_pet_size()
            size_map = {1: (100, 100), 2: (150, 150), 3: (200, 200)}
            self._display_size = size_map.get(size_level, (150, 150))
            self.pause_resume_delay = pet_config.get_pause_resume_delay()
        if not pet_config:
            self.pause_resume_delay = 10.0
        sprites_path = os.path.join(_root, assistant_manager.assistants_dir, pet.assistant_name, "assets", "sprites")
        self._sprites_path = sprites_path if os.path.isdir(sprites_path) else None
        self._load_all_frames()

        # 无边框 + 置顶 + Tool：保证助手实时展示、不被其他窗口遮挡（含 macOS）
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        # macOS：Tool 窗口在应用失焦时会自动隐藏；设置此属性后助手窗口一直停留在桌面上，不被遮挡
        if is_macos():
            self.setAttribute(Qt.WA_MacAlwaysShowToolWindow, True)
        self.setAttribute(Qt.WA_TranslucentBackground)

        self.label = QLabel(self)
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setStyleSheet("background: transparent;")
        self.label.setScaledContents(False)
        self._apply_frame()

        # 初始位置与固定尺寸（多显示器下避免 setGeometry 被 Qt 改写）；位置限制在当前/主屏幕内（避免 MAC 等“outside any known screen”）
        self.setFixedSize(self._display_size[0], self._display_size[1])
        need_reposition = get_ui_setting("reposition_windows")
        if need_reposition:
            # 换设备后：用主屏左上角附近定位，确保在屏内
            try:
                screen = QApplication.primaryScreen()
                if screen:
                    geo = screen.availableGeometry()
                    x0, y0 = geo.x() + 50, geo.y() + 50
                    x, y = self._clamp_position_to_screen(x0, y0)
                else:
                    x, y = self._clamp_position_to_screen(100, 100)
            except Exception as e:
                logger.debug(f"主屏定位失败: {e}")
                x, y = self._clamp_position_to_screen(100, 100)
        else:
            pos = pet.get_position() if pet else {"x": 100, "y": 100}
            x, y = self._clamp_position_to_screen(pos.get("x", 100), pos.get("y", 100))
        self.move(x, y)
        if pet:
            if need_reposition:
                pet.set_position(x, y)
            else:
                pos = pet.get_position()
                if x != pos.get("x", 100) or y != pos.get("y", 100):
                    pet.set_position(x, y)
        self.label.setGeometry(0, 0, self._display_size[0], self._display_size[1])

        # 动画定时器（间隔按当前动作从 data.config.anim_frame_delays_ms 读取，缺省用 anim_interval_ms）
        self._anim_timer = QTimer(self)
        self._anim_timer.timeout.connect(self._next_frame)
        anim_ms = pet_config.get_anim_interval_ms_for_state(self._current_state) if pet_config else 100
        self._anim_timer.start(anim_ms)

        # 主更新循环（移动、状态、位置同步）
        self._update_timer = QTimer(self)
        self._update_timer.timeout.connect(self._update_loop)
        self._update_timer.start(update_interval)

        self._setup_movement()
        self.show_bubble_requested.connect(self._on_show_bubble_requested, Qt.QueuedConnection)
        self.bubble_close_after_voice_ms.connect(self._set_bubble_duration_if_current, Qt.QueuedConnection)
        self._start_cursor_monitor_if_available()
        self._auto_interaction_timer = QTimer(self)
        self._auto_interaction_timer.timeout.connect(self._on_auto_interaction_tick)
        self._last_auto_run_ts = 0.0  # 上次自动交互执行时间；每次程序启动从间隔后首次执行
        self._auto_interaction_start_ts = 0.0  # 自动交互计时起点（程序启动或启用时）；用于「从启动开始计时」
        self._apply_auto_interaction_from_settings()
        logger.info(f"AssistantWindow 初始化完成")

    def _load_all_frames(self):
        """加载各状态精灵帧；仅记录实际有图的状态为可用，不将空状态用其他状态图替代。"""
        pet = self.assistant_manager.get_current_assistant()
        mapping = pet.data.get("state_to_sprite_folder", DEFAULT_STATE_TO_SPRITE_FOLDER) if pet else DEFAULT_STATE_TO_SPRITE_FOLDER
        states = ["idle", "walking", "dragging", "happy", "sad", "thinking", "paused"]
        for s in states:
            self._state_frames[s] = load_frames(self._sprites_path, s, self._display_size, state_to_folder=mapping)
        self._available_states = {s for s in states if self._state_frames[s]}
        if self._current_state not in self._available_states:
            self._current_state = self._fallback_state()
        if not hasattr(self, "_last_applied_state"):
            self._last_applied_state = None
        if self._last_applied_state is not None and self._last_applied_state not in self._available_states:
            self._last_applied_state = self._current_state
        if self._forced_state is not None and self._forced_state not in self._available_states:
            self._forced_state = None
            self._forced_state_until = 0.0

    def _fallback_state(self):
        """返回当前可用的展示状态（优先 happy -> idle -> walking -> 任意可用）。"""
        avail = getattr(self, "_available_states", set())
        for s in ("happy", "idle", "walking", "dragging", "thinking", "sad", "paused"):
            if s in avail:
                return s
        return next(iter(avail), "happy")

    def _apply_frame(self):
        arr = self._state_frames.get(self._current_state) or self._state_frames.get("happy") or []
        if arr:
            i = self._frame_index % len(arr)
            self.label.setPixmap(arr[i])

    def _clamp_position_to_screen(self, x, y, w=None, h=None):
        """将窗口坐标限制在当前/主屏幕可用区域内，避免 MAC 等出现 outside any known screen。
        优先使用包含 (x,y) 的屏幕；若不在任何屏幕内则用主屏。"""
        w = w if w is not None else getattr(self, "_display_size", (200, 200))[0]
        h = h if h is not None else getattr(self, "_display_size", (200, 200))[1]
        try:
            screen = None
            if hasattr(QApplication, "screenAt"):
                screen = QApplication.screenAt(QPoint(int(x), int(y)))
            if screen is None:
                screen = QApplication.primaryScreen()
            if screen:
                geo = screen.availableGeometry()
                x = max(geo.x(), min(x, geo.x() + geo.width() - w))
                y = max(geo.y(), min(y, geo.y() + geo.height() - h))
        except Exception as e:
            logger.debug(f"限制窗口位置时使用主屏失败: {e}")
            x = max(0, min(x, 1920 - w))
            y = max(0, min(y, 1080 - h))
        return int(x), int(y)

    def _mac_ensure_position_in_screen(self):
        """仅 Mac：启动后再次检查并校正助手窗口位置，确保完全在当前屏幕内，并写回数据。"""
        if not is_macos():
            return
        try:
            x, y = self.x(), self.y()
            w, h = self._display_size[0], self._display_size[1]
            x2, y2 = self._clamp_position_to_screen(x, y, w, h)
            if (x2, y2) != (x, y):
                self.move(x2, y2)
                pet = self.assistant_manager.get_current_assistant()
                if pet:
                    pet.set_position(x2, y2)
                    pet.save()
                logger.debug(f"Mac 校正助手窗口位置: ({x},{y}) -> ({x2},{y2})")
        except Exception as e:
            logger.debug(f"Mac 校正助手位置失败: {e}")

    def showEvent(self, event):
        super().showEvent(event)
        # macOS：首次显示后延迟校正位置，确保在屏内；并置顶一次以便实时展示、不被遮挡
        if is_macos() and not getattr(self, "_mac_position_checked", False):
            self._mac_position_checked = True
            QTimer.singleShot(150, self._mac_ensure_position_in_screen)
            QTimer.singleShot(200, self._mac_raise_once)

    def _mac_raise_once(self):
        """macOS：首次显示后置顶一次，确保助手在最前、不被遮挡。仅执行一次。"""
        if not is_macos() or getattr(self, "_mac_raised_once", False):
            return
        self._mac_raised_once = True
        try:
            self.raise_()
            self.activateWindow()
        except Exception:
            pass

    def _next_frame(self):
        arr = self._state_frames.get(self._current_state) or self._state_frames.get("happy") or []
        if not arr:
            return
        self._frame_index = (self._frame_index + 1) % len(arr)
        self._apply_frame()

    def _setup_movement(self):
        pet = self.assistant_manager.get_current_assistant()
        pet_config = self.assistant_manager.get_current_assistant_config()
        if pet and pet_config:
            self.movement_controller = MovementController(pet, pet_config)
            self.last_speed_level = pet_config.get_speed_level()
            if self.last_speed_level is None:
                self.last_speed_level = 1
            self.movement_controller.start()

    def _state_priority(self, s):
        """状态优先级，数值越小越高。用于 30 秒保持期内是否允许被更高优先级覆盖。"""
        if self._forced_state and s == self._forced_state:
            return 0
        if s == "dragging":
            return 1
        if s == "thinking":
            return 2
        if s == "happy":
            return 3
        return 4  # walking 及其他

    def on_user_activity(self):
        """统一入口：任何人工/交互事件（拖拽结束、气泡、聊天发送、取消强制、任务提醒等）调用，刷新用户操作时间与 30 秒 hold。"""
        t = time.time()
        self._last_user_action_ts = t
        cfg = self.assistant_manager.get_current_assistant_config()
        state_hold_sec = float(cfg.get_timing("state_hold_sec", 30)) if cfg else 30
        self._state_hold_until = t + state_hold_sec

    def _apply_state_target(self, target, apply_anim=True):
        """统一状态切换入口：更新 _current_state、hold、动画；仅在状态变化时写 pet.set('state')。仅支持有精灵图的状态。"""
        avail = getattr(self, "_available_states", set())
        if target not in avail:
            target = self._fallback_state()
        if target == self._current_state and not apply_anim:
            return
        t = time.time()
        cfg = self.assistant_manager.get_current_assistant_config()
        state_hold_sec = float(cfg.get_timing("state_hold_sec", 30)) if cfg else 30
        self._state_hold_until = t + state_hold_sec
        self._current_state = target
        self._frame_index = 0
        if apply_anim and cfg:
            ms = cfg.get_anim_interval_ms_for_state(target)
            if self._anim_timer:
                self._anim_timer.setInterval(ms)
        if apply_anim:
            self._apply_frame()
        pet = self.assistant_manager.get_current_assistant()
        if pet and target != self._last_applied_state:
            pet.set("state", target)
            self._last_applied_state = target

    def _update_loop(self):
        t = time.time()
        pet = self.assistant_manager.get_current_assistant()
        # 解除交互暂停
        if self.is_paused_by_interaction and (t - self.last_interaction_time) >= self.pause_resume_delay:
            self.is_paused_by_interaction = False
            if self.last_speed_level is not None:
                cfg = self.assistant_manager.get_current_assistant_config()
                if cfg and self.last_speed_level != 0:
                    cfg.set_wander_speed(self.last_speed_level)
                    if self.movement_controller:
                        self.movement_controller.set_speed(self.last_speed_level)
        # 强制状态超时则解除
        if self._forced_state_until and t >= self._forced_state_until:
            self._forced_state = None
            self._forced_state_until = 0.0
        # 状态机：优先级 拖拽 > 松开后 3 秒内仍保持 drag > 手动强制 > 思考 > ... > walk
        cfg = self.assistant_manager.get_current_assistant_config()
        drag_release_sec = float(cfg.get_timing("drag_release_to_happy_sec", 3)) if cfg else 3
        if self.is_dragging:
            target = "dragging"
        elif self._drag_ended_ts is not None and (t - self._drag_ended_ts) < drag_release_sec:
            target = "dragging"  # 松开鼠标后 3 秒内保持 drag，再切 happy
        else:
            if self._drag_ended_ts is not None and (t - self._drag_ended_ts) >= drag_release_sec:
                self._drag_ended_ts = None
                self._state_hold_until = 0  # 允许立即从 drag 切到 happy，否则 30 秒 hold 会长时间卡在 drag
            if self._forced_state and t < self._forced_state_until:
                target = self._forced_state
            elif self.is_thinking:
                target = "thinking"
            elif self.is_paused_by_interaction:
                target = "happy"
            else:
                happy_sec = float(cfg.get_timing("happy_after_action_sec", 60)) if cfg else 60
                if (t - self._last_user_action_ts) < happy_sec:
                    target = "happy"
                else:
                    target = "walking"
        avail = getattr(self, "_available_states", set())
        if target not in avail:
            target = self._fallback_state()
        state_hold_sec = float(cfg.get_timing("state_hold_sec", 30)) if cfg else 30
        may_change = (target != self._current_state) and (
            t >= self._state_hold_until or self._state_priority(target) < self._state_priority(self._current_state)
        )
        if may_change:
            self._apply_state_target(target)
        # 非拖拽时：更新移动（只改位置）、同步窗口位置
        if not self.is_dragging:
            if self.movement_controller:
                self.movement_controller.update()
            if pet:
                pos = pet.get_position()
                x, y = pos.get("x", self.x()), pos.get("y", self.y())
                if self.x() != x or self.y() != y:
                    self.move(x, y)
        if self.speech_bubble and getattr(self.speech_bubble, "is_showing", False):
            self.speech_bubble.update_position()
        flush_interval = float(cfg.get_timing("position_flush_interval_sec", 2.0)) if cfg else 2.0
        if pet and (t - self._last_position_flush) >= flush_interval:
            self._last_position_flush = t
            if callable(getattr(pet, "flush_if_dirty", None)):
                pet.flush_if_dirty()
            if callable(getattr(pet, "flush_state_if_dirty", None)):
                pet.flush_state_if_dirty(flush_interval)

    def pause_movement(self):
        if self.movement_controller and self.movement_controller.enabled:
            cfg = self.assistant_manager.get_current_assistant_config()
            if cfg:
                self.last_speed_level = cfg.get_speed_level()
            self.movement_controller.stop()
            self.is_paused_by_interaction = True
            self.last_interaction_time = time.time()
        self._last_user_action_ts = time.time()

    def resume_movement(self):
        """恢复移动（用于打开设置等窗口时让助手继续走动，不因之前打开会话列表而一直暂停）。"""
        self.is_paused_by_interaction = False
        if self.movement_controller:
            cfg = self.assistant_manager.get_current_assistant_config()
            speed = cfg.get_speed_level() if cfg else 2
            if speed > 0:
                self.movement_controller.start()

    def _show_window(self, attr_name, window_class, *args, on_create=None, error_msg="打开窗口失败"):
        """通用窗口显示方法"""
        try:
            window = getattr(self, attr_name, None)
            if window is None or not getattr(window, "isVisible", lambda: False)():
                window = window_class(*args)
                setattr(self, attr_name, window)
                if on_create:
                    on_create(window)
            window.show()
            window.raise_()
            window.activateWindow()
            return window
        except Exception as e:
            logger.exception(f"{error_msg}: {e}")
            return None

    def open_chat(self):
        self.pause_movement()
        from ui.session_list_window import SessionListWindow
        pet = self.assistant_manager.get_current_assistant()
        cfg = self.assistant_manager.get_current_assistant_config()
        name = (pet.get("name") or pet.assistant_name) if pet else t("pet_default_name")
        personality = cfg.get("personality", "") if cfg else ""
        self._show_window("session_list_window", SessionListWindow, name, personality, self, self.gateway_client,
                          error_msg=t("error_open_failed"))

    def open_settings(self):
        self.resume_movement()
        from ui.settings.settings_window import SettingsWindow
        self._show_window("settings_window", SettingsWindow, self, self.gateway_client, error_msg=t("error_open_failed"))

    def _add_voice_settings_submenu(self, menu):
        """在菜单中加入「语音设置」二级菜单：语音开关 + 音色列表（当前项带「当前」标记），写入助手 data.json"""
        from utils.voice_tts import VOICE_OPTIONS
        vm = menu.addMenu(t("voice_settings_menu"))
        cfg = self.assistant_manager.get_current_assistant_config()
        if not cfg:
            return
        on = cfg.get_voice_enabled()
        vm.addAction(t("voice_on") if on else t("voice_off"), lambda: cfg.set_voice_enabled(not cfg.get_voice_enabled()))
        vm.addSeparator()
        cur_id = cfg.get_voice_id()
        for voice_id, display_name in VOICE_OPTIONS:
            label = display_name + t("current_suffix") if voice_id == cur_id else display_name
            vm.addAction(label, lambda vid=voice_id: cfg.set_voice_id(vid))

    def open_config_setting(self):
        """打开配置文件设置窗口，通过 config.get 展示 openclaw 配置。"""
        self.resume_movement()
        from ui.configsetting import ConfigSettingWindow
        self._show_window("config_setting_window", ConfigSettingWindow, self, self.gateway_client, error_msg=t("error_open_failed"))

    def open_task_manager(self):
        """打开任务管理窗口；数据源为 Gateway cron.*（若已连接且支持）或本地 task_manager。"""
        self.resume_movement()
        from ui.task_manager_window import TaskManagerWindow
        self._show_window("task_manager_window", TaskManagerWindow, self, error_msg=t("error_open_failed"))

    def open_clear_cache(self):
        from ui.settings.clear_cache_window import ClearCacheWindow
        pet = self.assistant_manager.get_current_assistant()
        bot_id = (pet.get("bot_id") or getattr(pet, "assistant_name", None) or "bot00001") if pet else "bot00001"
        def on_create(w):
            w.bot_id = bot_id
        self._show_window("clear_cache_window", ClearCacheWindow, bot_id, self,
                          on_create=on_create, error_msg=t("error_open_failed"))

    BUBBLE_IMPORTANCE_DEFAULT = 2  # 未传重要度时默认 2 级

    def _apply_auto_interaction_from_settings(self):
        """根据当前 settings 启动或停止自动交互定时器。启动时重置计时起点，从本次启动开始计时。"""
        if not self.settings:
            self._auto_interaction_timer.stop()
            return
        enabled = bool(self.settings.get("auto_interaction_enabled", False))
        session_key = (self.settings.get("auto_interaction_session") or "").strip()
        interval_minutes = max(1, int(self.settings.get("auto_interaction_interval_minutes") or 10))
        if not enabled or not session_key:
            self._auto_interaction_timer.stop()
            return
        self._auto_interaction_start_ts = time.time()
        self._last_auto_run_ts = 0.0
        self._auto_interaction_timer.setInterval(60 * 1000)
        self._auto_interaction_timer.start()

    def apply_auto_interaction_settings(self, enabled, interval_minutes):
        """设置窗口保存后调用，更新自动交互开关与间隔并重启定时器。"""
        if self.settings:
            self.settings.set("auto_interaction_enabled", enabled)
            self.settings.set("auto_interaction_interval_minutes", max(1, int(interval_minutes or 10)))
        self._apply_auto_interaction_from_settings()

    def _on_auto_interaction_tick(self):
        """自动交互定时检查：到点则 skill_extract 取 prompt -> gateway 发到绑定 session -> 回复后气泡展示。"""
        if not self.settings or not self.gateway_client:
            return
        enabled = bool(self.settings.get("auto_interaction_enabled", False))
        session_key = (self.settings.get("auto_interaction_session") or "").strip()
        interval_minutes = max(1, int(self.settings.get("auto_interaction_interval_minutes") or 10))
        cooldown_sec = max(60, int(self.settings.get("auto_interaction_cooldown_sec") or 180))
        if not enabled or not session_key:
            return
        if not getattr(self.gateway_client, "is_connected", lambda: False)():
            return
        now = time.time()
        if (now - self.last_interaction_time) < cooldown_sec:
            return
        interval_sec = interval_minutes * 60
        if self._last_auto_run_ts > 0:
            if (now - self._last_auto_run_ts) < interval_sec:
                return
        else:
            if self._auto_interaction_start_ts <= 0 or (now - self._auto_interaction_start_ts) < interval_sec:
                return
        prompt = extract_random_skill(self.assistant_manager.get_current_assistant())
        if not prompt:
            return

        def _on_agent_reply(ok, result, error):
            if not ok or not result:
                return
            msg = self._agent_result_to_text(result)
            if msg and hasattr(self, "show_bubble_requested"):
                self.show_bubble_requested.emit(msg, 2)
            self._last_auto_run_ts = time.time()

        l2s.send_agent(self.gateway_client, session_key, prompt, callback=_on_agent_reply)

    @staticmethod
    def _agent_result_to_text(result):
        """从 agent 回调的 result 中提取展示文本（与 ChatWindow 解析逻辑一致）。"""
        if isinstance(result, str):
            return (result or "").strip() or None
        if not isinstance(result, dict):
            return None
        payloads = result.get("payloads")
        if isinstance(payloads, list) and payloads:
            first = payloads[0]
            if isinstance(first, dict) and first.get("text"):
                return (first.get("text") or "").strip() or None
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
        return msg or None

    def _on_show_bubble_requested(self, text, importance=None):
        """信号槽：归一化重要度后入队，同级别排队、高级在前；队列里有高于当前级别的则顶替。"""
        pri = self.BUBBLE_IMPORTANCE_DEFAULT if importance is None else max(1, min(3, int(importance)))
        self._enqueue_bubble(text or "", pri)

    def _enqueue_bubble(self, text, pri):
        """入队：同级别 FIFO，高级别排在前面（插入到首个更低优先级之前）。入队后若队首高于当前气泡则顶替。气泡关闭时用弹窗兜底。"""
        cfg = self.assistant_manager.get_current_assistant_config()
        if cfg and not cfg.get_bubble_enabled():
            if (text or "").strip():
                from PyQt5.QtWidgets import QMessageBox
                QMessageBox.information(self, t("tip_title"), (text or "").strip())
            return
        # 插入到首个「优先级低于当前」的项之前，保证同级别 FIFO、高级在前
        for i, (_, p) in enumerate(self._bubble_queue):
            if p > pri:
                self._bubble_queue.insert(i, (text, pri))
                break
        else:
            self._bubble_queue.append((text, pri))
        self._process_bubble_queue()

    def _process_bubble_queue(self):
        """无当前气泡时播队首；有当前气泡且队首重要度高于当前则顶替（播队首）。"""
        if not self._bubble_queue:
            return
        head_text, head_pri = self._bubble_queue[0]
        if self._current_bubble_importance > 0:
            if head_pri >= self._current_bubble_importance:
                logger.debug("气泡正在使用，消息在排队")
                return  # 队首不高于当前，不顶替
            self._bubble_queue.pop(0)
            self._do_show_bubble(head_text, head_pri)
        else:
            self._bubble_queue.pop(0)
            self._do_show_bubble(head_text, head_pri)

    def show_speech_bubble(self, text="", importance=None):
        """直接展示一条气泡（不经过队列）。重要度未传默认 2。供外部直接调用；信号走队列。"""
        pri = self.BUBBLE_IMPORTANCE_DEFAULT if importance is None else max(1, min(3, int(importance)))
        self._enqueue_bubble(text or "", pri)

    def _do_show_bubble(self, text, pri):
        """实际展示一条气泡，设置当前重要度；默认 15 秒关闭，开语音则 TTS。若因节流/关闭未展示则塞回队首。"""
        try:
            cfg = self.assistant_manager.get_current_assistant_config()
            if cfg and not cfg.get_bubble_enabled():
                self._bubble_queue.insert(0, (text, pri))
                logger.debug("消息在排队")
                return
            now = time.time()
            throttle = float(cfg.get_timing("bubble_show_throttle_sec", 0.4)) if cfg else 0.4
            if self._current_bubble_importance == 0 and (now - self._last_bubble_show_time) < throttle:
                self._bubble_queue.insert(0, (text, pri))
                logger.debug("消息在排队")
                return
            self._last_bubble_show_time = now
            self.on_user_activity()
            from ui.speech_bubble import SpeechBubble, _filter_bubble_text
            filtered_text = _filter_bubble_text(text or "")
            if self._bubble_done_walk_timer:
                self._bubble_done_walk_timer.stop()
                self._bubble_done_walk_timer = None
            if self.speech_bubble and getattr(self.speech_bubble, "is_showing", False):
                self.speech_bubble.on_hide = None
                self.speech_bubble._do_hide()
            self._current_bubble_importance = pri
            self.is_thinking = False
            self._apply_state_target("happy")
            voice_enabled = cfg and cfg.get_voice_enabled() and (filtered_text or "").strip()
            duration_ms = int(cfg.get_timing("bubble_duration_with_voice_max_ms", 120000)) if voice_enabled else int(cfg.get_timing("bubble_duration_ms", 15000)) if cfg else 15000
            self.speech_bubble = SpeechBubble(
                self, text=filtered_text, duration_ms=duration_ms, on_hide=self._on_bubble_hide
            )
            self.speech_bubble.show_bubble(filtered_text)
            if (filtered_text or "").strip() and voice_enabled:
                try:
                    from utils.voice_tts import speak, get_current_voice_process
                    close_ms = int(cfg.get_timing("bubble_close_after_voice_ms", 3000))
                    def on_playback_finished():
                        self.bubble_close_after_voice_ms.emit(close_ms)
                    speak((filtered_text or "").strip(), voice=cfg.get_voice_id(), on_playback_finished=on_playback_finished)
                    if self.speech_bubble:
                        voice_process = get_current_voice_process()
                        if voice_process:
                            self.speech_bubble.set_voice_process(voice_process)
                except Exception as ev:
                    logger.debug(f"语音播放跳过或失败: {ev}")
        except Exception as e:
            logger.error(f"显示气泡失败: {e}")


    def _set_bubble_duration_if_current(self, ms: int):
        """若当前展示的气泡仍是 self.speech_bubble，则将其关闭时长设为 ms（语音播毕后设为 3 秒再关）。"""
        if self.speech_bubble and getattr(self.speech_bubble, "is_showing", False):
            self.speech_bubble.set_duration_ms(ms)

    def _on_bubble_hide(self):
        """气泡关闭后：清零当前重要度，若队列有下一条则播放，否则启动 20 秒切回 walk。"""
        self._current_bubble_importance = 0
        self._process_bubble_queue()
        if self._current_bubble_importance == 0:
            if self._bubble_done_walk_timer:
                self._bubble_done_walk_timer.stop()
            cfg = self.assistant_manager.get_current_assistant_config()
            ms = int(cfg.get_timing("bubble_hide_to_walk_ms", 20000)) if cfg else 20000
            self._bubble_done_walk_timer = QTimer(self)
            self._bubble_done_walk_timer.setSingleShot(True)
            self._bubble_done_walk_timer.timeout.connect(self._switch_to_walk)
            self._bubble_done_walk_timer.start(ms)

    def _switch_to_walk(self):
        """气泡关闭后 20 秒：允许状态机切回 walk（通过将“最后操作”视为已过 60 秒）。"""
        if self._bubble_done_walk_timer:
            self._bubble_done_walk_timer.stop()
            self._bubble_done_walk_timer = None
        happy_sec = float(self.assistant_manager.get_current_assistant_config().get_timing("happy_after_action_sec", 60)) if self.assistant_manager.get_current_assistant_config() else 60
        self._last_user_action_ts = time.time() - (happy_sec + 1)

    def _start_cursor_monitor_if_available(self):
        """若检测到 Cursor DB，在后台启动监控；检测到时间戳变化时通过气泡+语音提醒。"""
        try:
            from utils.monitor_agent import CursorDbMonitor
            def on_cursor_activity(msg):
                self.show_bubble_requested.emit(msg, 2)
            monitor = CursorDbMonitor(poll_interval=3, on_activity=on_cursor_activity)
            monitor.start_in_thread()
        except Exception as e:
            logger.debug(f"Cursor 监控未启动: {e}")

    def set_forced_state(self, state):
        """用户自定义助手状态，config.timings.forced_state_duration_sec 内强制生效，之后恢复代码逻辑。None 表示取消强制。仅支持有精灵图的状态。"""
        if state is not None:
            avail = getattr(self, "_available_states", set())
            if state not in avail:
                self.show_bubble_requested.emit(t("state_no_sprites"), 2)
                return
        cfg = self.assistant_manager.get_current_assistant_config()
        forced_sec = float(cfg.get_timing("forced_state_duration_sec", 3600)) if cfg else 3600
        self._forced_state = state if state else None
        self._forced_state_until = (time.time() + forced_sec) if state else 0.0
        if state is not None:
            self.on_user_activity()
        else:
            self.on_user_activity()

    def set_speed(self, level):
        self.last_speed_level = level
        self.is_paused_by_interaction = False
        if self.movement_controller:
            self.movement_controller.set_speed(level)
        else:
            cfg = self.assistant_manager.get_current_assistant_config()
            if cfg:
                cfg.set_wander_speed(level)

    def set_size(self, size):
        cfg = self.assistant_manager.get_current_assistant_config()
        if cfg:
            cfg.set_pet_size(size)
        size_map = {1: (100, 100), 2: (150, 150), 3: (200, 200)}
        self._display_size = size_map.get(size, (150, 150))
        self._load_all_frames()
        self.setFixedSize(self._display_size[0], self._display_size[1])
        self.label.setGeometry(0, 0, self._display_size[0], self._display_size[1])
        self._apply_frame()

    def _switch_robot(self, pet_id):
        """切换机器人并重载窗口状态；同步将当前助手的 bot_id 写入 assistants/current.json"""
        if pet_id == self.assistant_manager.current_assistant_name:
            return
        if not self.assistant_manager.switch_assistant(pet_id):
            return
        if self.settings is not None:
            pet = self.assistant_manager.get_current_assistant()
            bot_id = pet.get("bot_id", "bot00001") if pet else "bot00001"
            self.settings.set("current_assistant", bot_id)
            self.settings.load()
            self.settings.save()
        self._reload_for_current_assistant()

    def _reload_for_current_assistant(self):
        """按当前助手重载：关闭依赖子窗口，停止任务/移动，刷新尺寸与帧，重新建立移动与技能/任务"""
        if self.session_list_window and getattr(self.session_list_window, "isVisible", lambda: False)():
            self.session_list_window.close()
        self.session_list_window = None
        if self.chat_window and getattr(self.chat_window, "isVisible", lambda: False)():
            self.chat_window.close()
        self.chat_window = None
        if self.movement_controller:
            self.movement_controller.stop()
        self.movement_controller = None
        pet = self.assistant_manager.get_current_assistant()
        if not pet:
            return
        pet_config = self.assistant_manager.get_current_assistant_config()
        _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if pet_config:
            size_map = {1: (100, 100), 2: (150, 150), 3: (200, 200)}
            self._display_size = size_map.get(pet_config.get_pet_size(), (150, 150))
        sprites_path = os.path.join(_root, self.assistant_manager.assistants_dir, pet.assistant_name, "assets", "sprites")
        self._sprites_path = sprites_path if os.path.isdir(sprites_path) else None
        self._load_all_frames()
        pos = pet.get_position()
        self.setFixedSize(self._display_size[0], self._display_size[1])
        x, y = self._clamp_position_to_screen(pos.get("x", 100), pos.get("y", 100))
        self.move(x, y)
        if x != pos.get("x", 100) or y != pos.get("y", 100):
            pet.set_position(x, y)
        self.label.setGeometry(0, 0, self._display_size[0], self._display_size[1])
        self._apply_frame()
        self._setup_movement()
        self._last_applied_state = None  # 切换助手后下一帧由状态机同步 state 到新 pet
        logger.info(f"已切换机器人并重载: {pet.assistant_name}")

    def _restart_app(self):
        """重启应用：启动新进程后退出当前进程，实现全部重新加载。Gateway 会断开，新进程会显示连接窗口。"""
        import subprocess
        import sys
        _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        main_py = os.path.join(_root, "main.py")
        if not os.path.isfile(main_py):
            logger.warning("未找到 main.py，无法重启")
            return
        try:
            subprocess.Popen([sys.executable, main_py], cwd=_root)
        except Exception as e:
            logger.exception(f"启动新进程失败: {e}")
            return
        self.quit_app()

    def quit_app(self):
        if self.speech_bubble and getattr(self.speech_bubble, "is_showing", False):
            self.speech_bubble._do_hide()
        if self.movement_controller:
            self.movement_controller.stop()
        pet = self.assistant_manager.get_current_assistant()
        if pet:
            if callable(getattr(pet, "flush_if_dirty", None)):
                pet.flush_if_dirty()
            if callable(getattr(pet, "flush_state_if_dirty", None)):
                pet.flush_state_if_dirty(0)
        if self.chat_window and getattr(self.chat_window, "isVisible", lambda: False)():
            self.chat_window.close()
        QApplication.quit()

    def _set_locale(self, locale: str):
        """切换界面语言（zh / en）并保存，气泡提示生效方式。"""
        if locale not in ("zh", "en"):
            return
        try:
            s = self.settings
            if s is None:
                from config.settings import Settings
                s = Settings()
                s.load()
            s.set("locale", locale)
            s.save()
        except Exception as e:
            logger.debug(f"保存语言设置失败: {e}")
        msg = t("locale_switched_en") if locale == "en" else t("locale_switched_zh")
        if hasattr(self, "show_bubble_requested"):
            self.show_bubble_requested.emit(msg, 2)

    def build_assistant_context_menu(self, menu):
        """向给定 QMenu 填充与右键菜单一致的项，供助手右键与双击后的会话列表窗口共用。"""
        menu.clear()
        cur_speed = self.last_speed_level if self.last_speed_level is not None else 1
        cfg = self.assistant_manager.get_current_assistant_config()
        cur_size = cfg.get_pet_size() if cfg else 2
        sm = menu.addMenu(t("speed_menu"))
        _speed_items = [(0, t("speed_0")), (1, t("speed_1")), (2, t("speed_2")), (3, t("speed_3"))]
        for i, lbl in _speed_items:
            label = lbl + t("current_suffix") if i == cur_speed else lbl
            sm.addAction(label, lambda checked=False, l=i: self.set_speed(l))
        zm = menu.addMenu(t("size_menu"))
        _size_items = [(1, t("size_small")), (2, t("size_medium")), (3, t("size_large"))]
        for i, lbl in _size_items:
            label = lbl + t("current_suffix") if i == cur_size else lbl
            zm.addAction(label, lambda checked=False, s=i: self.set_size(s))
        stm = menu.addMenu(t("state_menu"))
        _state_items = [
            ("idle", t("state_idle")), ("walking", t("state_walking")), ("happy", t("state_happy")),
            ("sad", t("state_sad")), ("thinking", t("state_thinking")), ("paused", t("state_paused")),
        ]
        avail = getattr(self, "_available_states", set())
        for state_id, label in _state_items:
            if state_id in avail:
                stm.addAction(label, lambda checked=False, s=state_id: self.set_forced_state(s))
        stm.addSeparator()
        stm.addAction(t("cancel_force"), lambda: self.set_forced_state(None))
        rm = menu.addMenu(t("select_robot_menu"))
        for pid in self.assistant_manager.list_assistants():
            pd = self.assistant_manager.assistants.get(pid)
            display_name = (pd.get("name") or pid) if pd else pid
            label = display_name + t("current_suffix") if pid == self.assistant_manager.current_assistant_name else display_name
            rm.addAction(label, lambda checked=False, p=pid: self._switch_robot(p))
        menu.addSeparator()
        cur_loc = get_locale()
        lang_menu = menu.addMenu(t("language_label"))
        lang_menu.addAction(
            t("language_zh") + (t("current_suffix") if cur_loc == "zh" else ""),
            lambda: self._set_locale("zh"),
        )
        lang_menu.addAction(
            t("language_en") + (t("current_suffix") if cur_loc == "en" else ""),
            lambda: self._set_locale("en"),
        )
        menu.addSeparator()
        menu.addAction(t("chat_menu"), self.open_chat)
        self._add_voice_settings_submenu(menu)
        menu.addSeparator()
        menu.addAction(t("settings_menu"), self.open_settings)
        menu.addAction(t("config_setting_menu"), self.open_config_setting)
        menu.addSeparator()
        menu.addAction(t("restart_menu"), self._restart_app)
        menu.addAction(t("quit_menu"), self.quit_app)

    def _show_context_menu(self, global_pos):
        """统一弹出右键菜单，供 contextMenuEvent 与 macOS Ctrl+左键 调用。"""
        menu = QMenu(self)
        self.build_assistant_context_menu(menu)
        menu.exec_(global_pos)

    def contextMenuEvent(self, event):
        self._show_context_menu(event.globalPos())
        event.accept()

    def mousePressEvent(self, event):
        # macOS：右键或 Ctrl+左键 均触发上下文菜单（与系统“辅助点按”一致）
        if event.button() == Qt.RightButton:
            self._show_context_menu(event.globalPos())
            event.accept()
            return
        if is_macos() and event.button() == Qt.LeftButton and (event.modifiers() & Qt.ControlModifier):
            self._show_context_menu(event.globalPos())
            event.accept()
            return
        if event.button() == Qt.LeftButton:
            self._did_drag = False
            self._drag_start = event.globalPos() - self.frameGeometry().topLeft()
            self._drag_ended_ts = None  # 新一轮拖拽，清除「松开 3 秒」计时
            self.is_dragging = True
            self.pause_movement()
        event.accept()

    def _deferred_bubble_update(self):
        """主线程中延迟更新气泡位置（拖动时合并多次 move 为一次更新，避免死机）"""
        self._bubble_update_pending = False
        if self.speech_bubble and getattr(self.speech_bubble, "is_showing", False):
            self.speech_bubble.update_position()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton and self._drag_start is not None:
            self._did_drag = True  # 发生过移动，视为拖动，后续双击不打开聊天
            self.move(event.globalPos() - self._drag_start)
            pet = self.assistant_manager.get_current_assistant()
            if pet:
                now = time.time()
                if (now - self._drag_position_flush_ts) >= 0.1:  # 拖拽时位置写盘/内存节流约 100ms
                    self._drag_position_flush_ts = now
                    pet.set_position(self.x(), self.y())
            # 拖动时每次移动都更新气泡位置，保证跨屏时气泡跟到新屏幕
            if self.speech_bubble and getattr(self.speech_bubble, "is_showing", False):
                self.speech_bubble.update_position()
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._last_click_was_clean = not self._did_drag  # 本次未移动则视为「干净点击」，下次双击才可打开聊天
            self._drag_start = None
            if self.is_dragging:
                self._drag_ended_ts = time.time()  # 松开后 3 秒再切 happy
            self.is_dragging = False
            pet = self.assistant_manager.get_current_assistant()
            if pet:
                pet.set_position(self.x(), self.y())
            self.on_user_activity()
        event.accept()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            if getattr(self, "_did_drag", False):
                return
            # 只有上一笔是「按下→释放、未移动」时才当作真双击；首次拖动时尚未有过释放，上一笔干净为假，不打开聊天
            if not getattr(self, "_last_click_was_clean", False):
                return
            self.open_chat()
        event.accept()
