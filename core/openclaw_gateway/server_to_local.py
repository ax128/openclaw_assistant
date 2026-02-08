"""
服务端 -> 本地：收到消息后的处理、分类与路由说明。

日志含义：
- 「响应 method=agent ok=True -> 聊天窗口」：该条 agent 响应将交给聊天窗口展示 AI 回复。
- 「Gateway 响应: req_id=... agent ok」：WS 收到 agent 成功响应，已派发回调。
- 「事件 event=tick/health/agent」：心跳、健康检查、agent 流式推送均不打印以免刷屏。
"""
from typing import Callable, Any, Optional

from utils.logger import gateway_logger

# 响应分类与传递目标（仅文档与日志，实际回调由 client 的 _pending 派发）
ROUTING = {
    "health": "会话列表（SessionListWindow）：填充「选择 Agent」与最近会话",
    "status": "状态/能力展示",
    "agent": "聊天窗口（ChatWindow）：展示 AI 回复；失败时展示错误信息",
    "sessions.list": "会话列表：可选补充会话列表",
    "skills.status": "技能状态展示",
}


def on_response(
    method: str,
    ok: bool,
    payload: Any,
    error: Optional[dict],
) -> None:
    """
    服务端返回响应（type=res）时调用，用于日志与分类。
    不替代 client 的 callback 派发，仅在 client 派发前记录「该响应将传递给哪里」。
    """
    target = ROUTING.get(method, "未知")
    if ok:
        if method != "health":
            gateway_logger.debug(
                f"server_to_local: 响应 method={method} ok=True -> {target}"
            )
    else:
        err_msg = (error or {}).get("message", "") if isinstance(error, dict) else str(error)
        gateway_logger.info(
            f"server_to_local: 响应 method={method} ok=False error={err_msg[:80]} -> {target}"
        )


def on_event(event_name: str, payload: Any) -> None:
    """
    服务端推送事件（type=event）时调用，用于日志与分类。
    事件不绑定请求 id，由 client 的 on_event 监听器派发到各 UI。
    """
    # tick 为网关心跳（约 30s 一次），health 为健康检查，agent 为聊天流式推送，均不记日志以免刷屏
    if event_name in ("tick", "health", "agent"):
        return
    gateway_logger.debug(f"server_to_local: 事件 event={event_name}")
