"""
Gateway 专用内存：WS 回调数据统一写入此处，本地助手/UI 从此读取。
- 文档要求：WS 通信在独立线程，信息回调放入专门内存，本地从内存取数。
- 线程安全：WS 线程写入、主线程/UI 读取，用锁保护。
"""
import json
import threading
import time
from typing import Any, Optional

from utils.logger import gateway_logger

# 健康快照（health 响应或 connect hello-ok 的 snapshot.health）
_HEALTH_KEY = "health"
# 配置快照（config.get 响应，含 agents.list 解析结果）
_CONFIG_KEY = "config"
# 各 session 最新 agent 结果（session_key -> {ok, result, error, updated_at}）
_AGENT_RESULTS_KEY = "agent_results"
# agent_results 最大保留会话数，超出时按 updated_at 淘汰最旧（优化建议：避免无限增长）
_AGENT_RESULTS_MAX_ENTRIES = 50
# agent_results 单条 TTL 秒数，超过则读取时视为不存在（可选淘汰）
_AGENT_RESULTS_TTL_SEC = 3600


class GatewayMemory:
    """Gateway 数据内存：health、agent 结果等，供会话列表与聊天窗口读取。"""

    _instance: Optional["GatewayMemory"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "GatewayMemory":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        self._lock = threading.Lock()
        self._store: dict = {
            _HEALTH_KEY: {"ok": None, "payload": None, "error": None, "updated_at": 0},
            _CONFIG_KEY: {"ok": None, "payload": None, "error": None, "updated_at": 0, "agents_list": []},
            _AGENT_RESULTS_KEY: {},
        }
        self._initialized = True

    def set_health(self, ok: bool, payload: Any, error: Optional[dict]) -> None:
        """写入最新 health 结果（由 WS 线程在收到 health 响应或 connect snapshot 后调用）。"""
        with self._lock:
            self._store[_HEALTH_KEY] = {
                "ok": ok,
                "payload": payload,
                "error": error,
                "updated_at": time.time(),
            }
        gateway_logger.debug(f"gateway_memory: set_health ok={ok}")

    def get_health(self) -> tuple[Optional[bool], Any, Optional[dict]]:
        """读取最新 health；返回 (ok, payload, error)，未写过则 (None, None, None)。"""
        with self._lock:
            h = self._store.get(_HEALTH_KEY) or {}
            return (h.get("ok"), h.get("payload"), h.get("error"))

    def set_config(self, ok: bool, payload: Any, error: Optional[dict]) -> None:
        """写入 config.get 结果；解析 payload.config.agents.list 存为 agents_list。
        若服务端已提供 payload.config（对象），则直接使用；否则校验 payload.raw 为合法 JSON。"""
        agents_list: list = []
        if ok and payload and isinstance(payload, dict):
            config = payload.get("config")
            has_config_dict = isinstance(config, dict)
            # 仅当没有现成 config 对象时，才要求 raw 为合法 JSON（服务端可能返回单引号等非标准 JSON）
            if not has_config_dict:
                raw = payload.get("raw")
                if isinstance(raw, str) and raw.strip():
                    try:
                        parsed = json.loads(raw)
                        if isinstance(parsed, dict):
                            config = parsed
                            has_config_dict = True
                    except json.JSONDecodeError as e:
                        ok = False
                        error = {"message": "本地 JSON 格式校验失败: %s" % (e.msg or str(e))}
                        gateway_logger.warning(f"gateway_memory: set_config 本地 JSON 校验失败 raw: {e.msg or str(e)}")
            if ok and config is not None and not isinstance(config, dict):
                ok = False
                error = {"message": "本地 JSON 格式校验失败: config 非对象"}
                gateway_logger.warning(f"gateway_memory: set_config 本地 JSON 校验失败: config 非对象")
            if ok:
                # 优先使用已解析的 config（来自 payload.config 或上面从 raw 解析的结果）
                if not isinstance(config, dict):
                    config = payload.get("config") or payload
                if isinstance(config, dict):
                    agents = config.get("agents") or {}
                    if isinstance(agents, dict):
                        raw_list = agents.get("list")
                        if isinstance(raw_list, list):
                            for a in raw_list:
                                if isinstance(a, dict) and (a.get("id") or a.get("agentId")):
                                    agents_list.append({
                                        "id": a.get("id") or a.get("agentId"),
                                        "agentId": a.get("id") or a.get("agentId"),
                                        "name": a.get("name") or a.get("id") or a.get("agentId"),
                                    })
        with self._lock:
            self._store[_CONFIG_KEY] = {
                "ok": ok,
                "payload": payload,
                "error": error,
                "updated_at": time.time(),
                "agents_list": agents_list,
            }
        gateway_logger.debug(f"gateway_memory: set_config ok={ok} agents={len(agents_list)}")

    def get_config(self) -> tuple[Optional[bool], Any, Optional[dict]]:
        """读取最新 config.get 结果；返回 (ok, payload, error)。"""
        with self._lock:
            c = self._store.get(_CONFIG_KEY) or {}
            return (c.get("ok"), c.get("payload"), c.get("error"))

    def get_agents_list(self) -> list:
        """从已缓存的 config 中返回 agents.list（含 id/agentId/name）；无则返回 []。"""
        with self._lock:
            c = self._store.get(_CONFIG_KEY) or {}
            return list(c.get("agents_list") or [])

    def clear_config(self) -> None:
        """清空 config 缓存（如断开连接时）。"""
        with self._lock:
            self._store[_CONFIG_KEY] = {
                "ok": None, "payload": None, "error": None, "updated_at": 0, "agents_list": []
            }

    def set_agent_result(
        self,
        session_key: str,
        ok: bool,
        result: Any,
        error: Optional[dict],
    ) -> None:
        """写入某会话最新 agent 结果（由聊天回调或 WS 派发处调用）。超出容量时按 updated_at 淘汰最旧。"""
        key = (session_key or "").strip() or "default"
        now = time.time()
        with self._lock:
            store = self._store.get(_AGENT_RESULTS_KEY) or {}
            store[key] = {
                "ok": ok,
                "result": result,
                "error": error,
                "updated_at": now,
            }
            if len(store) > _AGENT_RESULTS_MAX_ENTRIES:
                by_time = sorted(store.items(), key=lambda x: x[1].get("updated_at", 0))
                for k, _ in by_time[: len(store) - _AGENT_RESULTS_MAX_ENTRIES]:
                    store.pop(k, None)
            self._store[_AGENT_RESULTS_KEY] = store
        gateway_logger.debug(f"gateway_memory: set_agent_result session_key={key} ok={ok}")

    def get_agent_result(self, session_key: str) -> Optional[tuple[bool, Any, Optional[dict]]]:
        """读取某会话最新 agent 结果；未写过或已过期（超过 TTL）返回 None。"""
        key = (session_key or "").strip() or "default"
        now = time.time()
        with self._lock:
            entry = (self._store.get(_AGENT_RESULTS_KEY) or {}).get(key)
            if not entry:
                return None
            if (now - (entry.get("updated_at") or 0)) > _AGENT_RESULTS_TTL_SEC:
                return None
            return (entry.get("ok"), entry.get("result"), entry.get("error"))

    def clear_health(self) -> None:
        """清空 health 缓存（如断开连接时）。"""
        with self._lock:
            self._store[_HEALTH_KEY] = {"ok": None, "payload": None, "error": None, "updated_at": 0}

    def clear_agent_result(self, session_key: Optional[str] = None) -> None:
        """清空 agent 结果；session_key 为 None 时清空全部。"""
        with self._lock:
            if session_key is None:
                self._store[_AGENT_RESULTS_KEY] = {}
            else:
                key = (session_key or "").strip() or "default"
                self._store[_AGENT_RESULTS_KEY].pop(key, None)


# 单例，供 client、server_to_local、会话列表、聊天窗口使用
gateway_memory = GatewayMemory()
