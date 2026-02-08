"""
跨平台适配层
抽象 Windows / macOS / Linux 差异，供 UI 与窗口逻辑统一调用
"""
import sys
import platform
from utils.logger import logger


def get_device_name() -> str:
    """当前设备/机器标识，用于检测换设备后重新定位窗口。优先 hostname，失败则 platform.node()。"""
    try:
        import socket
        return (socket.gethostname() or "").strip() or (platform.node() or "").strip()
    except Exception:
        pass
    try:
        return (platform.node() or "").strip()
    except Exception:
        pass
    return "unknown"

# 平台标识
_PLATFORM = sys.platform
IS_WINDOWS = _PLATFORM == "win32"
IS_MACOS = _PLATFORM == "darwin"
IS_LINUX = _PLATFORM.startswith("linux")


def is_windows():
    """是否 Windows"""
    return IS_WINDOWS


def is_macos():
    """是否 macOS"""
    return IS_MACOS


def is_linux():
    """是否 Linux"""
    return IS_LINUX


def platform_name():
    """当前平台名称"""
    if IS_WINDOWS:
        return "windows"
    if IS_MACOS:
        return "macos"
    if IS_LINUX:
        return "linux"
    return _PLATFORM


def send_message_key_sequence():
    """
    发送消息的快捷键序列（Tk 用）
    Windows/Linux: Ctrl+Enter -> "<Control-Return>"
    macOS: Command+Enter -> "<Command-Return>"
    """
    if IS_MACOS:
        return "<Command-Return>"
    return "<Control-Return>"


def send_message_shortcut_for_qt():
    """PyQt5 用：发送消息快捷键。macOS 为 Cmd+Return，其它为 Ctrl+Return。"""
    return "Meta+Return" if IS_MACOS else "Ctrl+Return"


def right_click_events():
    """
    右键菜单绑定的事件序列
    Windows/Linux: Button-3
    macOS: Button-2 或 Ctrl+Click(Button-3)，部分环境仅 Button-2 生效
    """
    if IS_MACOS:
        # macOS 上通常 Button-2 为辅助键点击，Button-3 为 Ctrl+Click
        return ["<Button-2>", "<Control-Button-1>"]
    return ["<Button-3>"]


def apply_assistant_window_transparency(window):
    """
    为助手主窗口应用透明/无边框效果
    - Windows: transparentcolor + white 背景
    - macOS: 优先 transparentcolor，不支持则仅设背景（避免白屏异常）
    - Linux: 同 Windows 尝试方式
    """
    try:
        window.attributes("-topmost", True)
    except Exception as e:
        logger.debug(f"设置 topmost 失败: {e}")

    if IS_MACOS:
        try:
            # macOS 上 Tk 对 transparentcolor 支持因版本而异
            window.attributes("-transparentcolor", "white")
            window.configure(bg="white")
        except Exception as e:
            logger.debug(f"macOS transparentcolor 不可用: {e}")
            window.configure(bg="white")
    else:
        try:
            window.attributes("-transparentcolor", "white")
            window.configure(bg="white")
        except Exception:
            window.configure(bg="white")


def apply_bubble_transparency(toplevel, canvas, transparent_color="gray"):
    """
    为聊天气泡窗口应用透明效果
    """
    try:
        toplevel.attributes("-transparentcolor", transparent_color)
        toplevel.configure(bg=transparent_color)
        if canvas:
            canvas.configure(bg=transparent_color)
    except Exception as e:
        logger.debug(f"气泡透明属性设置失败: {e}")
        toplevel.configure(bg=transparent_color)
        if canvas:
            canvas.configure(bg=transparent_color)


def mousewheel_bindings():
    """
    返回滚轮绑定的事件名列表
    - Windows/Mac: "<MouseWheel>", "<Button-4>", "<Button-5>"
    - Linux: "<Button-4>", "<Button-5>"
    """
    if IS_LINUX:
        return ["<Button-4>", "<Button-5>"]
    return ["<MouseWheel>", "<Button-4>", "<Button-5>"]


def bind_mousewheel(canvas, scroll_unit=3, add_to_children=True):
    """
    为 canvas 绑定跨平台滚轮事件，并可递归绑定到子组件
    """
    handler = None

    def on_mousewheel(event):
        if hasattr(event, "delta") and event.delta:
            delta = int(-1 * (event.delta / 120))
            canvas.yview_scroll(delta * scroll_unit, "units")
        elif hasattr(event, "num"):
            if event.num == 4:
                canvas.yview_scroll(-scroll_unit, "units")
            elif event.num == 5:
                canvas.yview_scroll(scroll_unit, "units")
        return "break"

    for ev in mousewheel_bindings():
        canvas.bind(ev, on_mousewheel, add="+")

    def bind_recursive(widget):
        for ev in mousewheel_bindings():
            widget.bind(ev, on_mousewheel, add="+")
        for child in widget.winfo_children():
            bind_recursive(child)

    if add_to_children:
        bind_recursive(canvas)


def focus_input(widget):
    """
    让输入类控件获得焦点（兼容 macOS 等）
    """
    try:
        widget.focus_set()
    except Exception:
        pass


def app_resources_dir():
    """
    应用资源/数据根目录（打包后适配）
    未打包时返回 None，由调用方用 os.getcwd() 或 __file__ 推断
    """
    return None


# ---------------------------------------------------------------------------
# UI 样式配置（Windows / macOS 分别优化）
# ---------------------------------------------------------------------------

def _get_font_settings():
    """延迟加载 Settings，避免循环导入"""
    try:
        from config.settings import Settings
        s = Settings()
        s.load()
        return s
    except Exception:
        return None


def ui_font_family():
    """正文/标题字体：优先读配置 font_family，空则按平台默认"""
    s = _get_font_settings()
    if s:
        v = s.get("font_family")
        if v is not None and str(v).strip():
            return str(v).strip()
    if IS_MACOS:
        return _pick_available_font(
            ["SF Pro Text", "SF Pro Display", "Helvetica Neue", "Helvetica", "Arial"],
            fallback="Helvetica Neue",
        )
    return "Microsoft YaHei UI" if IS_WINDOWS else "Arial"


def ui_font_family_fallback():
    """当主字体不可用时回退字体"""
    return "Arial"


def _pick_available_font(candidates, fallback):
    """仅在 Qt 环境中选择可用字体；无 Qt 时直接回退"""
    try:
        from PyQt5.QtGui import QFontDatabase
        families = set(QFontDatabase().families())
        for name in candidates:
            if name in families:
                return name
    except Exception:
        pass
    return fallback


def ui_font_size_body():
    """正文字号"""
    return 11 if IS_MACOS else 10


def ui_font_size_title():
    """标题/窗口标题字号"""
    return 12 if IS_MACOS else 11


def ui_font_size_menu():
    """右键菜单字号"""
    return 12 if IS_MACOS else 10


def ui_font_size_small():
    """小号字（按钮、提示）"""
    return 10 if IS_MACOS else 9


def ui_chat_title_height():
    """聊天窗口标题栏高度（px）"""
    return 36 if IS_MACOS else 30


def ui_chat_input_height():
    """聊天输入框行数（约等于高度）"""
    return 3


def ui_bubble_font_family():
    """气泡文字字体（与正文一致，受 font_family 配置影响）"""
    return ui_font_family()


def ui_bubble_font_size():
    """气泡文字字号：优先读配置 bubble_font_size，否则按平台默认"""
    s = _get_font_settings()
    if s:
        v = s.get("bubble_font_size")
        if v is not None and str(v).strip():
            try:
                return int(v)
            except (TypeError, ValueError):
                pass
    return 15 if IS_MACOS else 14


def ui_bubble_padding():
    """气泡内边距（px）"""
    return 18 if IS_MACOS else 16


def ui_bubble_corner_radius():
    """气泡圆角半径"""
    return 20 if IS_MACOS else 18


def ui_button_cursor():
    """按钮光标：macOS 上 arrow 更统一，Windows 用 hand2"""
    return "arrow" if IS_MACOS else "hand2"


def ui_window_bg():
    """窗口/面板背景色"""
    return "#f5f5f7" if IS_MACOS else "#f0f0f0"


def ui_button_bg():
    """普通按钮背景色"""
    return "#e8e8ed" if IS_MACOS else "#e0e0e0"


def ui_menu_active_bg():
    """菜单选中项背景色"""
    return "#007aff" if IS_MACOS else "#cccccc"


def ui_menu_fg():
    """菜单文字颜色"""
    return "#000000"


def ui_menu_active_fg():
    """菜单选中项文字颜色"""
    return "#ffffff" if IS_MACOS else "#000000"


def get_ui_config():
    """
    返回当前平台 UI 配置字典，供各界面按需读取
    """
    return {
        "font_family": ui_font_family(),
        "font_family_fallback": ui_font_family_fallback(),
        "font_size_body": ui_font_size_body(),
        "font_size_title": ui_font_size_title(),
        "font_size_menu": ui_font_size_menu(),
        "font_size_small": ui_font_size_small(),
        "chat_title_height": ui_chat_title_height(),
        "chat_input_height": ui_chat_input_height(),
        "bubble_font_family": ui_bubble_font_family(),
        "bubble_font_size": ui_bubble_font_size(),
        "bubble_padding": ui_bubble_padding(),
        "bubble_corner_radius": ui_bubble_corner_radius(),
        "button_cursor": ui_button_cursor(),
        "window_bg": ui_window_bg(),
        "button_bg": ui_button_bg(),
        "menu_active_bg": ui_menu_active_bg(),
        "menu_fg": ui_menu_fg(),
        "menu_active_fg": ui_menu_active_fg(),
    }
