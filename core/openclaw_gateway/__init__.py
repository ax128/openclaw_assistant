"""
OpenClaw Gateway 客户端模块。
通过 WebSocket 对接 OpenClaw 服务端，提供 call(method, params, callback) 与事件回调。
本地->服务端：local_to_server（聊天发送、参数发送/修改）。
服务端->本地：server_to_local（收消息处理、分类、路由说明）。
"""
from .client import GatewayClient
from . import local_to_server
from . import server_to_local
from .gateway_memory import gateway_memory
from .protocol import (
    PROTOCOL_VERSION,
    METHOD_AGENT,
    METHOD_CHAT_HISTORY,
    METHOD_CHAT_SEND,
    METHOD_SESSIONS_LIST,
    METHOD_SESSIONS_PREVIEW,
    METHOD_HEALTH,
    METHOD_STATUS,
    build_connect_params,
    build_request_frame,
)

__all__ = [
    "GatewayClient",
    "local_to_server",
    "server_to_local",
    "gateway_memory",
    "PROTOCOL_VERSION",
    "METHOD_AGENT",
    "METHOD_CHAT_HISTORY",
    "METHOD_CHAT_SEND",
    "METHOD_SESSIONS_LIST",
    "METHOD_SESSIONS_PREVIEW",
    "METHOD_HEALTH",
    "METHOD_STATUS",
    "build_connect_params",
    "build_request_frame",
]
