"""
UI 配置加载与保存：从 config/ui_settings.json 读取窗口/弹窗/字体等参数，变更时写回文件。
所有 UI 相关硬编码应改为通过 get_ui_setting / set_ui_setting_and_save 读写。
"""
import json
import os
import copy
from typing import Any, Optional

from utils.logger import logger

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_UI_SETTINGS_FILE = os.path.join(_ROOT, "config", "ui_settings.json")
_cache: Optional[dict] = None


def _default_ui_settings() -> dict:
    """内置默认结构，文件缺失或损坏时使用。"""
    return {
        "_version": "1.0",
        "font": {
            "chat": {
                "default_pt": 15,
                "min_pt": 10,
                "max_pt": 28,
                "options": [
                    {"label": "小", "pt": 10},
                    {"label": "中", "pt": 15},
                    {"label": "大", "pt": 20},
                    {"label": "超大", "pt": 26},
                ],
            },
            "body_pt": {"macos": 11, "windows": 10},
            "title_pt": {"macos": 12, "windows": 11},
            "menu_pt": {"macos": 12, "windows": 10},
            "small_pt": {"macos": 10, "windows": 9},
            "bubble_default_pt": {"macos": 15, "windows": 14},
        },
        "chat_window": {
            "geometry": {"x": 350, "y": 150, "width": 500, "height": 600},
            "session_label": {"font_size_px": 12, "color": "#6b7280"},
            "input_edit": {"max_height_px": 84},
            "max_display_messages": 200,
            "message_display": {
                "msg_time_font_size_px": 11,
                "msg_time_color": "#888",
                "user_msg": {
                    "background": "#90EE90",
                    "padding": "8px 12px",
                    "border_radius_px": 8,
                    "max_width_pct": 80,
                },
                "system_msg_color": "#666",
                "body_padding_px": 4,
            },
        },
        "chat_window_popup": {
            "size_presets": {
                "small": {"min_width_px": 220, "max_height_px": 200},
                "medium": {"min_width_px": 280, "max_height_px": 280},
                "large": {"min_width_px": 360, "max_height_px": 360},
            },
            "default_size": "small",
            "list_row_height_px": 24,
            "list_padding_px": 2,
            "style": {
                "background": "#fff",
                "border": "1px solid #e5e7eb",
                "border_radius_px": 6,
            },
        },
        "settings_window": {
            "geometry": {"x": 400, "y": 200, "width": 480, "height": 560},
            "title": {"font_size_px": 20, "font_weight": 600, "color": "#111827"},
            "card": {
                "border": "1px solid #e5e7eb",
                "border_radius_px": 10,
                "margin_top_px": 12,
                "padding": "16px 14px 10px 14px",
                "title_font_size_px": 13,
                "title_color": "#374151",
            },
            "desc": {"font_size_px": 12, "color": "#6b7280"},
            "button": {
                "min_height_px": 40,
                "primary": {"background": "#2563eb", "border_radius_px": 8},
                "secondary": {
                    "background": "#f3f4f6",
                    "border": "1px solid #e5e7eb",
                    "border_radius_px": 8,
                },
            },
            "form_control": {
                "padding": "6px 10px",
                "border": "1px solid #e5e7eb",
                "border_radius_px": 6,
                "min_height_px": 20,
            },
        },
        "gateway_settings_window": {
            "title": {"font_size_px": 18, "font_weight": 600, "color": "#111827"},
            "status_text": {"font_size_px": 13, "color": "#6b7280"},
            "desc": {"font_size_px": 12, "color": "#6b7280"},
        },
        "session_list_window": {
            "geometry": {"x": 300, "y": 200, "width": 520, "height": 560},
            "list": {"max_height_px": 160, "font_size_px": 11},
            "menubar_style": "QMenuBar::item { padding: 6px 14px; border-radius: 4px; }",
        },
        "task_manager_window": {
            "geometry": {"x": 320, "y": 200, "width": 640, "height": 420},
            "banner": {"font_size_px": 12, "color": "#6b7280", "padding_px": 8},
        },
        "config_setting_window": {
            "geometry": {"x": 200, "y": 150, "width": 420, "height": 200},
            "status_label": {"font_size_px": 12, "color": "#6b7280"},
            "read_only_dialog": {"padding_px": 8, "border": "1px solid #e5e7eb", "border_radius_px": 6},
            "edit_dialog": {"padding_px": 8, "border_radius_px": 6},
        },
        "log_tail_window": {
            "geometry": {"x": 200, "y": 150, "width": 800, "height": 500},
            "path_label": {"font_size_px": 11, "color": "#6b7280"},
        },
        "startup_dialog": {
            "geometry": {"width": 520, "height": 480},
            "min_size": {"width": 480, "height": 460},
            "host_edit_min_width_px": 280,
            "port_edit_max_width_px": 100,
            "token_edit_min_width_px": 280,
        },
        "speech_bubble": {
            "default_duration_ms": 15000,
            "gap_above_pet_px": 2,
            "tail": {"width_px": 14, "height_px": 12},
            "border_px": 2,
            "radius_px": 8,
            "chars_per_line": 22,
            "lines_height": 10,
            "close_button_size_px": 20,
            "max_width_px": 400,
        },
        "colors": {
            "window_bg": {"macos": "#f5f5f7", "windows": "#f0f0f0"},
            "button_bg": {"macos": "#e8e8ed", "windows": "#e0e0e0"},
            "card_border": "#e5e7eb",
            "text_muted": "#6b7280",
            "text_primary": "#111827",
        },
    }


def _deep_merge(base: dict, override: dict) -> dict:
    """递归合并 override 到 base，override 优先。不修改 base。"""
    result = copy.deepcopy(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = copy.deepcopy(v)
    return result


def _get_by_path(data: dict, path: str) -> Any:
    """按点分路径取值，如 'chat_window.geometry.width'。"""
    keys = path.strip().split(".")
    cur = data
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return None
        cur = cur[k]
    return cur


def _set_by_path(data: dict, path: str, value: Any) -> None:
    """按点分路径设值，缺失的中间层会建为 dict。"""
    keys = path.strip().split(".")
    cur = data
    for k in keys[:-1]:
        if k not in cur or not isinstance(cur.get(k), dict):
            cur[k] = {}
        cur = cur[k]
    cur[keys[-1]] = value


def load_ui_settings(reload_from_disk: bool = False) -> dict:
    """加载 UI 配置：先与默认合并，再返回。默认使用缓存；reload_from_disk=True 时强制从文件重读。"""
    global _cache
    if _cache is not None and not reload_from_disk:
        return _cache
    default = _default_ui_settings()
    if not os.path.isfile(_UI_SETTINGS_FILE):
        _cache = default
        return _cache
    try:
        with open(_UI_SETTINGS_FILE, "r", encoding="utf-8") as f:
            file_data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(f"加载 config/ui_settings.json 失败，使用默认: {e}")
        _cache = default
        return _cache
    # 去掉注释类键再合并，避免写入时带注释
    file_data = {k: v for k, v in file_data.items() if not k.startswith("_") and k != "comment"}
    _cache = _deep_merge(default, file_data)
    return _cache


def get_ui_setting(path: str, default: Any = None) -> Any:
    """按路径读取一项，如 get_ui_setting('chat_window.geometry.width')。"""
    data = load_ui_settings()
    val = _get_by_path(data, path)
    return val if val is not None else default


def set_ui_setting_and_save(path: str, value: Any) -> None:
    """设置一项并立即写回 config/ui_settings.json。"""
    global _cache
    data = load_ui_settings()
    _set_by_path(data, path, value)
    _cache = data
    try:
        # 写入时排除纯注释键
        to_write = {k: v for k, v in data.items() if not k.startswith("_") and k != "comment"}
        with open(_UI_SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(to_write, f, indent=2, ensure_ascii=False)
    except OSError as e:
        logger.warning(f"保存 config/ui_settings.json 失败: {e}")


def save_ui_settings_geometry(section: str, x: int, y: int, width: int, height: int) -> None:
    """保存某窗口的 geometry 到 ui_settings（section 如 'chat_window'、'settings_window'）。"""
    path = f"{section}.geometry"
    data = load_ui_settings()
    geom = _get_by_path(data, path)
    if isinstance(geom, dict):
        geom = dict(geom)
    else:
        geom = {}
    geom["x"] = x
    geom["y"] = y
    geom["width"] = width
    geom["height"] = height
    set_ui_setting_and_save(path, geom)
