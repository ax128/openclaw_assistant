"""
助手配置管理 - 从 AssistantData.data["config"] 读写
"""
from utils.logger import logger
from core.assistant_data import DEFAULT_CONFIG


class AssistantConfig:
    """助手配置：包装 AssistantData.data['config']，读写统一走 data.json"""

    def __init__(self, assistant_data):
        self.assistant_data = assistant_data
        self.config = assistant_data.data.setdefault("config", dict(DEFAULT_CONFIG))
        if not isinstance(self.config, dict):
            assistant_data.data["config"] = dict(DEFAULT_CONFIG)
            self.config = assistant_data.data["config"]
        default_timings = DEFAULT_CONFIG.get("timings") or {}
        timings = self.config.setdefault("timings", {})
        if isinstance(timings, dict):
            for k, v in default_timings.items():
                timings.setdefault(k, v)

    def get(self, key, default=None):
        return self.config.get(key, default)

    def get_wander_enabled(self):
        return self.config.get("wander_enabled", True)

    def get_wander_boundary(self):
        return self.config.get("wander_boundary", {"x": 0, "y": 0, "width": 1920, "height": 1080})

    def get_wander_speed(self):
        return self.config.get("wander_speed", 2)

    def set_wander_speed(self, speed):
        speed_map = {0: 0, 1: 1, 2: 3, 3: 6}
        actual_speed = speed_map.get(speed, 2)
        self.config["wander_speed"] = actual_speed
        self.config["speed_level"] = speed
        if speed == 0:
            self.config["wander_enabled"] = False
        else:
            self.config["wander_enabled"] = True
        self.assistant_data.save()
        logger.info(f"设置游走速度等级: {speed} (实际速度值: {actual_speed})")

    def get_speed_level(self):
        if "speed_level" in self.config:
            return self.config["speed_level"]
        actual_speed = self.config.get("wander_speed", 2)
        if actual_speed == 0:
            return 0
        elif actual_speed == 1:
            return 1
        elif actual_speed == 2:
            return 2
        return 3

    def get_assistant_size(self):
        return self.config.get("assistant_size", 2)

    def set_assistant_size(self, size):
        self.config["assistant_size"] = size
        self.assistant_data.save()
        logger.info(f"设置助手大小: {size}")

    def get_move_interval(self):
        return float(self.config.get("move_interval", 2.0))

    def get_anim_interval_ms(self):
        return int(self.config.get("anim_interval_ms", 100))

    def get_anim_interval_ms_for_state(self, state):
        delays = self.config.get("anim_frame_delays_ms")
        if isinstance(delays, dict) and state in delays:
            return int(delays[state])
        return int(self.config.get("anim_interval_ms", 100))

    def get_pause_resume_delay(self):
        return float(self.config.get("pause_resume_delay", 10.0))

    def get_update_interval_ms(self):
        v = self.config.get("update_interval_ms")
        return int(v) if v is not None else None

    def get_voice_enabled(self):
        return bool(self.config.get("voice_enabled", False))

    def set_voice_enabled(self, enabled):
        self.config["voice_enabled"] = bool(enabled)
        self.assistant_data.save()
        logger.info(f"语音开关: {'开' if enabled else '关'}")

    def get_voice_id(self):
        return str(self.config.get("voice_id") or "zh-CN-XiaoxiaoNeural")

    def set_voice_id(self, voice_id):
        self.config["voice_id"] = str(voice_id)
        self.assistant_data.save()
        logger.info(f"音色已切换: {voice_id}")

    def get_bubble_enabled(self):
        return bool(self.config.get("bubble_enabled", True))

    def set_bubble_enabled(self, enabled):
        self.config["bubble_enabled"] = bool(enabled)
        self.assistant_data.save()
        logger.info(f"气泡开关: {'开' if enabled else '关'}")

    def get_timing(self, key, default=None):
        timings = self.config.get("timings") or {}
        if key in timings:
            v = timings[key]
            if isinstance(v, (int, float)):
                return v
        return default if default is not None else (DEFAULT_CONFIG.get("timings") or {}).get(key)
