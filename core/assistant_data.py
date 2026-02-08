"""
助手数据管理
"""
import json
import os
import time
from datetime import datetime
from utils.logger import logger


# 默认配置常量，供 assistant_data 和 assistant_config 共用
DEFAULT_CONFIG = {
    "wander_enabled": True,
    "wander_boundary": {"x": 0, "y": 0, "width": 1920, "height": 1080},
    "wander_speed": 2,
    "speed_level": 1,
    "pet_size": 2,
    "personality": "",
    "default_position": {"x": 100, "y": 100},
    "description": "",
    "move_interval": 2.0,
    "anim_interval_ms": 100,
    "pause_resume_delay": 10.0,
    "update_interval_ms": 50,
    "anim_frame_delays_ms": {
        "idle": 1000, "walking": 500, "dragging": 300, "paused": 1000,
        "happy": 500, "sad": 500, "thinking": 500,
    },
    "voice_enabled": False,
    "voice_id": "zh-CN-XiaoxiaoNeural",
    "bubble_enabled": True,
    "timings": {
        "bubble_show_throttle_sec": 0.4,
        "bubble_duration_ms": 15000,
        "bubble_duration_with_voice_max_ms": 120000,
        "bubble_close_after_voice_ms": 3000,
        "bubble_hide_to_walk_ms": 20000,
        "state_hold_sec": 30,
        "happy_after_action_sec": 60,
        "forced_state_duration_sec": 3600,
        "position_flush_interval_sec": 2.0,
        "chat_reply_poll_ms": 200,
        "chat_max_display_messages": 200,
    },
}

# 状态名 -> sprites 子文件夹名
DEFAULT_STATE_TO_SPRITE_FOLDER = {
    "idle": "idle", "walking": "walk", "dragging": "drag",
    "paused": "paused", "happy": "happy", "sad": "sad", "thinking": "think",
}


def _ensure_defaults(data_dict, defaults):
    """确保字典包含所有默认键值"""
    for k, v in defaults.items():
        data_dict.setdefault(k, v)


class AssistantData:
    """助手数据管理类。位置更新采用内存+定时落盘，避免每次移动都写盘。"""

    def __init__(self, assistant_name, assistants_dir="assistants"):
        self.assistant_name = assistant_name
        self.data_path = os.path.join(assistants_dir, assistant_name, "data.json")
        self.data = self._load_default()
        self._position_dirty = False
        self._state_dirty = False
        self._last_state_flush = 0.0
        self.load()

    def _load_default(self):
        """默认数据"""
        return {
            "name": self.assistant_name,
            "level": 1,
            "experience": 0,
            "state": "happy",
            "position": {"x": 100, "y": 100},
            "interaction_history": [],
            "created_at": datetime.now().isoformat(),
            "last_active": datetime.now().isoformat()
        }

    def load(self):
        """加载数据"""
        if not os.path.exists(self.data_path):
            logger.info(f"助手数据文件不存在，使用默认数据: {self.data_path}")
            return
        try:
            with open(self.data_path, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
            if "skills" in loaded and isinstance(loaded["skills"], list):
                logger.info(f"检测到旧格式的 skills 数组，已弃用: {self.assistant_name}")
                loaded.pop("skills", None)
            if "skills" in loaded and not isinstance(loaded["skills"], dict):
                loaded.pop("skills", None)
            self.data.update(loaded)
            self.data.setdefault("bot_id", "")
            self.data.pop("ai_config", None)
            cfg = self.data.get("config")
            if not isinstance(cfg, dict):
                self.data["config"] = dict(DEFAULT_CONFIG)
            else:
                _ensure_defaults(cfg, DEFAULT_CONFIG)
            logger.debug(f"加载助手数据: {self.assistant_name} from {self.data_path}")
        except Exception as e:
            logger.error(f"加载助手数据失败 [{self.assistant_name}]: {e}")

    def save(self):
        """保存数据"""
        os.makedirs(os.path.dirname(self.data_path), exist_ok=True)
        self.data["last_active"] = datetime.now().isoformat()
        self._position_dirty = False
        self._state_dirty = False
        try:
            with open(self.data_path, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"保存助手数据失败 [{self.assistant_name}]: {e}")

    def get(self, key, default=None):
        return self.data.get(key, default)

    def get_skills(self):
        return dict(self.data.get("skills") or {})

    def get_skill(self, skill_id):
        skills = self.get_skills()
        return skills.get(skill_id)

    def is_skill_enabled(self, skill_id):
        skill = self.get_skill(skill_id)
        if skill:
            return skill.get("enabled", False)
        return False

    def enable_skill(self, skill_id):
        if skill_id not in self.data.get("skills", {}):
            return
        self.data.setdefault("skills", {})[skill_id] = dict(self.data.get("skills", {}).get(skill_id, {}))
        self.data["skills"][skill_id]["enabled"] = True
        self.save()

    def disable_skill(self, skill_id):
        if skill_id not in self.data.get("skills", {}):
            return
        self.data.setdefault("skills", {})[skill_id] = dict(self.data.get("skills", {}).get(skill_id, {}))
        self.data["skills"][skill_id]["enabled"] = False
        self.save()

    def add_skill(self, skill_id, name, description, call_method, enabled=True, prompt="", keywords=None):
        self.data.setdefault("skills", {})[skill_id] = {
            "name": name,
            "description": description,
            "call_method": call_method,
            "enabled": enabled,
            "prompt": prompt or "",
            "keywords": list(keywords) if keywords is not None else []
        }
        self.save()

    def remove_skill(self, skill_id):
        if skill_id in self.data.get("skills", {}):
            del self.data["skills"][skill_id]
            self.save()

    def set(self, key, value):
        self.data[key] = value
        if key == "position":
            self._position_dirty = True
            return
        if key == "state":
            self._state_dirty = True
            return
        self.save()

    def flush_if_dirty(self):
        if self._position_dirty:
            self._position_dirty = False
            self.save()

    def flush_state_if_dirty(self, interval_sec=1.5):
        now = time.time()
        if self._state_dirty and (interval_sec <= 0 or (now - self._last_state_flush) >= interval_sec):
            self._state_dirty = False
            self._last_state_flush = now
            self.save()

    def get_position(self):
        return self.data.get("position", {"x": 100, "y": 100})

    def set_position(self, x, y):
        self.data["position"] = {"x": x, "y": y}
        self._position_dirty = True
