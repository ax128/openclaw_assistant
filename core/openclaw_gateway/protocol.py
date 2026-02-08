"""
OpenClaw Gateway 协议常量与帧构建。
参考：Gateway-板块详细分析.md（协议版本、帧格式、ConnectParams）。
"""
import uuid

PROTOCOL_VERSION = 3

# 常用方法名，便于后续命令对接
METHOD_CONNECT = "connect"
METHOD_HEALTH = "health"
METHOD_STATUS = "status"
METHOD_AGENT = "agent"
METHOD_AGENT_WAIT = "agent.wait"
METHOD_CHAT_HISTORY = "chat.history"
METHOD_CHAT_SEND = "chat.send"
METHOD_CHAT_ABORT = "chat.abort"
METHOD_CONFIG_GET = "config.get"
METHOD_CONFIG_SET = "config.set"
METHOD_SESSIONS_LIST = "sessions.list"
METHOD_SESSIONS_PREVIEW = "sessions.preview"
METHOD_SESSIONS_PATCH = "sessions.patch"
METHOD_SESSIONS_DELETE = "sessions.delete"
METHOD_MODELS_LIST = "models.list"
METHOD_CRON_LIST = "cron.list"
METHOD_CRON_STATUS = "cron.status"
METHOD_CRON_ADD = "cron.add"
METHOD_CRON_UPDATE = "cron.update"
METHOD_CRON_REMOVE = "cron.remove"
METHOD_CRON_RUN = "cron.run"
METHOD_CRON_RUNS = "cron.runs"
METHOD_SKILLS_STATUS = "skills.status"
METHOD_LOGS_TAIL = "logs.tail"
METHOD_SEND = "send"
METHOD_WAKE = "wake"

# 客户端标识：使用 Gateway 协议允许的 cli（非浏览器客户端），避免 Control UI 的 origin 校验；mode 用 ui
DEFAULT_CLIENT_ID = "cli"
DEFAULT_CLIENT_MODE = "ui"


def build_connect_params(
    *,
    min_protocol: int = PROTOCOL_VERSION,
    max_protocol: int = PROTOCOL_VERSION,
    client_id: str = DEFAULT_CLIENT_ID,
    version: str = "1.0.0",
    platform: str = "windows",
    mode: str = DEFAULT_CLIENT_MODE,
    token: str = "",
    password: str = "",
    challenge_nonce: str = "",
) -> dict:
    """构建 connect 请求的 params。"""
    params = {
        "minProtocol": min_protocol,
        "maxProtocol": max_protocol,
        "client": {
            "id": client_id,
            "version": version,
            "platform": platform,
            "mode": mode,
        },
    }
    if token:
        params["auth"] = {"token": token}
    elif password:
        params["auth"] = {"password": password}
    if challenge_nonce:
        params.setdefault("auth", {})
        # 设备认证时 nonce 放 device；token 认证可不传
    return params


def build_request_frame(method: str, params: dict = None) -> tuple[str, dict]:
    """构建请求帧 (type=req, id, method, params)。返回 (req_id, frame_dict)。"""
    req_id = str(uuid.uuid4())
    frame = {
        "type": "req",
        "id": req_id,
        "method": method,
        "params": params if params is not None else {},
    }
    return req_id, frame


def parse_response_frame(data: dict) -> tuple[str | None, bool | None, dict | None, dict | None]:
    """解析响应帧。返回 (id, ok, payload, error)。非 res 帧返回 (None, None, None, None)。"""
    if not isinstance(data, dict) or data.get("type") != "res":
        return None, None, None, None
    return (
        data.get("id"),
        data.get("ok"),
        data.get("payload"),
        data.get("error"),
    )


def parse_event_frame(data: dict) -> tuple[str | None, dict | None]:
    """解析事件帧。返回 (event_name, payload)。非 event 帧返回 (None, None)。"""
    if not isinstance(data, dict) or data.get("type") != "event":
        return None, None
    return data.get("event"), data.get("payload")
