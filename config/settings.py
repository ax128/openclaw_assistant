"""
全局配置管理：
- current_assistant / assistants_dir 存于 assistants/current.json
- Gateway 连接存于 config/gateway.json（gateway_ws_url、gateway_token 等，敏感项加密存储）
- 系统级设置存于 config/system_settings.json
"""
import json
import os
from utils.logger import logger
from config.secret_cipher import decrypt_if_encrypted, encrypt_if_available

# 存于 assistants/current.json 的键（current_assistant 为 data.json 中的 bot_id，如 bot00001）
BOOTSTRAP_KEYS = ("current_assistant", "assistants_dir")

# 存于 config/gateway.json 的键（OpenClaw Gateway 连接 + 自动登录 + SSH 隧道）
GATEWAY_KEYS = (
    "gateway_ws_url", "gateway_token", "gateway_password", "auto_login",
    "ssh_enabled", "ssh_username", "ssh_server", "ssh_password",
)
# 上述键中需加密存储的（写入文件时加密，读取时解密，不明文显示）
GATEWAY_SENSITIVE_KEYS = ("gateway_token", "gateway_password", "ssh_password")

# 存于 config/system_settings.json 的键（自动交互、主题、字体、聊天选项、日志等级等）
SYSTEM_SETTINGS_KEYS = (
    "auto_interaction_enabled", "auto_interaction_session",
    "auto_interaction_interval_minutes", "auto_interaction_cooldown_sec",
    "update_interval",
    "font_family", "chat_font_pt", "bubble_font_size", "popup_size",
    "response_validator_enabled", "prompt_optimization_enabled",
    "theme", "chat_show_thinking", "chat_focus_mode", "split_ratio",
    "locale",
    "log_level",
)


class Settings:
    """全局配置：current.json + config/gateway.json + config/system_settings.json。"""

    def __init__(self, bootstrap_file=None):
        _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self._root = _root
        self._config_dir = os.path.join(_root, "config")
        if bootstrap_file is None:
            bootstrap_file = os.path.join(_root, "assistants", "current.json")
        self.bootstrap_file = os.path.normpath(os.path.abspath(bootstrap_file))
        self.gateway_file = os.path.normpath(os.path.join(self._config_dir, "gateway.json"))
        self.system_settings_file = os.path.normpath(os.path.join(self._config_dir, "system_settings.json"))
        self.config = self._load_default()
        self.load()

    def _load_default(self):
        return {
            "current_assistant": "bot00001",
            "assistants_dir": "assistants",
            "gateway_ws_url": "ws://127.0.0.1:18789",
            "gateway_token": "",
            "gateway_password": "",
            "auto_login": False,
            "ssh_enabled": False,
            "ssh_username": "",
            "ssh_server": "",
            "ssh_password": "",
            "update_interval": 50,
            "auto_interaction_enabled": True,
            "auto_interaction_session": "",
            "auto_interaction_interval_minutes": 10,
            "auto_interaction_cooldown_sec": 180,
            "font_family": "",
            "chat_font_pt": 15,
            "bubble_font_size": 14,
            "popup_size": "small",
            "response_validator_enabled": True,
            "prompt_optimization_enabled": False,
            "theme": "system",
            "chat_show_thinking": True,
            "chat_focus_mode": False,
            "split_ratio": 0.6,
            "locale": "zh",
            "log_level": "INFO",
        }

    def resolve_bot_id_to_assistant_id(self):
        """根据 current_assistant（bot_id）解析出助手目录 id（文件夹名）。若已是目录名则直接返回。"""
        assistants_dir = self.config.get("assistants_dir", "assistants")
        value = self.config.get("current_assistant", "bot00001")
        assistants_path = os.path.join(self._root, assistants_dir)
        if not os.path.isdir(assistants_path):
            return value
        candidate = os.path.join(assistants_path, value)
        if os.path.isdir(candidate) and os.path.isfile(os.path.join(candidate, "data.json")):
            return value
        for name in os.listdir(assistants_path):
            path = os.path.join(assistants_path, name)
            if not os.path.isdir(path):
                continue
            data_file = os.path.join(path, "data.json")
            if not os.path.isfile(data_file):
                continue
            try:
                with open(data_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if data.get("bot_id") == value:
                        return name
            except (json.JSONDecodeError, IOError, OSError):
                continue
        return value

    def load(self):
        """加载：默认 -> current.json -> config/gateway.json -> config/system_settings.json。"""
        self.config.update(self._load_default())
        bootstrap_loaded = False
        if os.path.exists(self.bootstrap_file):
            try:
                with open(self.bootstrap_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for k in BOOTSTRAP_KEYS:
                        if k in data:
                            self.config[k] = data[k]
                bootstrap_loaded = True
            except (OSError, json.JSONDecodeError) as e:
                logger.error(f"加载 current_assistant 配置失败: {e}")
        if os.path.isfile(self.gateway_file):
            try:
                with open(self.gateway_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for k in GATEWAY_KEYS:
                        if k in data:
                            raw = data[k]
                            if k in GATEWAY_SENSITIVE_KEYS and isinstance(raw, str):
                                self.config[k] = decrypt_if_encrypted(raw, self._config_dir)
                            else:
                                self.config[k] = raw
            except (OSError, json.JSONDecodeError) as e:
                logger.debug(f"加载 config/gateway.json 失败: {e}")
        if os.path.isfile(self.system_settings_file):
            try:
                with open(self.system_settings_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for k in SYSTEM_SETTINGS_KEYS:
                        if k in data:
                            self.config[k] = data[k]
            except (OSError, json.JSONDecodeError) as e:
                logger.debug(f"加载 config/system_settings.json 失败: {e}")
        return bootstrap_loaded

    def save(self):
        """保存：current.json；config/gateway.json；config/system_settings.json。"""
        os.makedirs(os.path.dirname(self.bootstrap_file), exist_ok=True)
        bootstrap = {k: self.config.get(k) for k in BOOTSTRAP_KEYS if k in self.config}
        try:
            with open(self.bootstrap_file, "w", encoding="utf-8") as f:
                json.dump(bootstrap, f, indent=2, ensure_ascii=False)
        except OSError as e:
            logger.error(f"保存 current_assistant 配置失败: {e}")
            raise
        os.makedirs(self._config_dir, exist_ok=True)
        gateway = {}
        for k in GATEWAY_KEYS:
            if k not in self.config:
                continue
            v = self.config[k]
            if k in GATEWAY_SENSITIVE_KEYS and isinstance(v, str) and v:
                gateway[k] = encrypt_if_available(v, self._config_dir)
            else:
                gateway[k] = v
        try:
            with open(self.gateway_file, "w", encoding="utf-8") as f:
                json.dump(gateway, f, indent=2, ensure_ascii=False)
        except OSError as e:
            logger.error(f"保存 config/gateway.json 失败: {e}")
            raise
        system_settings = {k: self.config[k] for k in SYSTEM_SETTINGS_KEYS if k in self.config}
        try:
            with open(self.system_settings_file, "w", encoding="utf-8") as f:
                json.dump(system_settings, f, indent=2, ensure_ascii=False)
        except OSError as e:
            logger.error(f"保存 config/system_settings.json 失败: {e}")
            raise

    def get(self, key, default=None):
        return self.config.get(key, default)

    def set(self, key, value):
        self.config[key] = value
