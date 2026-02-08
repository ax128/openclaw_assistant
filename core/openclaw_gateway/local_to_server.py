"""
本地 -> 服务端：统一封装与 Gateway 的请求发送。
- 聊天发送、参数发送、参数修改等均由本模块对外提供，便于维护与日志追踪。
"""
import uuid
from typing import Callable, Any, Optional

from .protocol import (
    METHOD_HEALTH,
    METHOD_STATUS,
    METHOD_AGENT,
    METHOD_CHAT_ABORT,
    METHOD_CHAT_HISTORY,
    METHOD_CONFIG_GET,
    METHOD_CONFIG_SET,
    METHOD_SESSIONS_LIST,
    METHOD_SESSIONS_PATCH,
    METHOD_SESSIONS_DELETE,
    METHOD_SKILLS_STATUS,
    METHOD_CRON_LIST,
    METHOD_CRON_STATUS,
    METHOD_CRON_ADD,
    METHOD_CRON_UPDATE,
    METHOD_CRON_REMOVE,
    METHOD_CRON_RUN,
    METHOD_CRON_RUNS,
)
from utils.logger import gateway_logger


def send_health(client, callback: Callable[[bool, Any, Optional[dict]], None]) -> Optional[str]:
    """
    向服务端请求 health（Agent 列表、会话等）。
    用途：会话列表拉取「选择 Agent」与最近会话。
    回调：callback(ok, payload, error)；payload 含 agents[].agentId/name/sessions.recent。
    """
    if not client or not getattr(client, "call", None):
        if callback:
            callback(False, None, {"message": "Gateway 客户端不可用"})
        return None
    req_id = client.call(METHOD_HEALTH, {}, callback=callback)
    if req_id:
        gateway_logger.debug(f"local_to_server: 已发送 health，req_id={req_id}")
    return req_id


def send_config_get(
    client,
    callback: Callable[[bool, Any, Optional[dict]], None],
) -> Optional[str]:
    """
    向服务端请求 config.get（openclaw 配置快照）。
    用途：配置文件设置窗口展示；payload 含 path、exists、raw（原始文件文本）、config、hash、valid 等。
    """
    if not client or not getattr(client, "call", None):
        if callback:
            callback(False, None, {"message": "Gateway 客户端不可用"})
        return None
    req_id = client.call(METHOD_CONFIG_GET, {}, callback=callback)
    if req_id:
        gateway_logger.info(f"local_to_server: 已发送 config.get，req_id={req_id}")
    return req_id


def send_config_set(
    client,
    raw: str,
    base_hash: str,
    callback: Callable[[bool, Any, Optional[dict]], None],
) -> Optional[str]:
    """
    向服务端请求 config.set（用 raw 全文覆盖 openclaw 配置）。
    服务端要求：当配置已存在时须传 baseHash（来自最近一次 config.get 的 payload.hash），否则拒绝。
    """
    if not client or not getattr(client, "call", None):
        if callback:
            callback(False, None, {"message": "Gateway 客户端不可用"})
        return None
    raw_str = (raw or "").strip()
    if not raw_str:
        if callback:
            callback(False, None, {"message": "config.set 需要非空 raw"})
        return None
    params = {"raw": raw_str}
    if base_hash and isinstance(base_hash, str) and base_hash.strip():
        params["baseHash"] = base_hash.strip()
    req_id = client.call(METHOD_CONFIG_SET, params, callback=callback)
    if req_id:
        gateway_logger.info(f"local_to_server: 已发送 config.set，req_id={req_id}")
    return req_id


def send_agent(
    client,
    session_key: str,
    message: str,
    callback: Callable[[bool, Any, Optional[dict]], None],
    idempotency_key: Optional[str] = None,
) -> Optional[str]:
    """
    向服务端发送聊天消息（agent 方法）。
    用途：聊天窗口发送用户输入，等待 agent 多段响应（accepted -> ok/error）后回调。
    回调：callback(ok, result, error)；status=ok 时 result 为 payload.result（最终回复内容）。
    """
    if not client or not getattr(client, "call", None):
        if callback:
            callback(False, None, {"message": "Gateway 客户端不可用"})
        return None
    params = {
        "sessionKey": (session_key or "").strip() or "agent:main:main",
        "message": (message or "").strip(),
        "idempotencyKey": idempotency_key or str(uuid.uuid4()),
    }
    req_id = client.call(METHOD_AGENT, params, callback=callback)
    if req_id:
        gateway_logger.info(
            f"local_to_server: 已发送 agent sessionKey={session_key} req_id={req_id}"
        )
    return req_id


def send_abort(
    client,
    session_key: str,
    run_id: Optional[str] = None,
    callback: Optional[Callable[[bool, Any, Optional[dict]], None]] = None,
) -> Optional[str]:
    """
    中止当前聊天运行（与 Web UI chat.abort 一致）。
    用途：用户点击「中止」时调用；run_id 可选，无则仅传 sessionKey。
    """
    if not client or not getattr(client, "call", None):
        if callback:
            callback(False, None, {"message": "Gateway 客户端不可用"})
        return None
    params = {"sessionKey": (session_key or "").strip() or "agent:main:main"}
    if run_id:
        params["runId"] = run_id
    req_id = client.call(METHOD_CHAT_ABORT, params, callback=callback)
    if req_id:
        gateway_logger.info(f"local_to_server: 已发送 chat.abort sessionKey={session_key}")
    return req_id


def send_chat_history(
    client,
    session_key: str,
    limit: int = 20,
    callback: Optional[Callable[[bool, Any, Optional[dict]], None]] = None,
) -> Optional[str]:
    """
    拉取该会话最近若干条聊天历史（与 Gateway chat.history 一致）。
    用途：用户选择某个 session 打开聊天时，展示最近 limit 条消息，不足则展示全部。
    """
    if not client or not getattr(client, "call", None):
        if callback:
            callback(False, None, {"message": "Gateway 客户端不可用"})
        return None
    params = {
        "sessionKey": (session_key or "").strip() or "agent:main:main",
        "limit": max(1, min(1000, limit)),
    }
    req_id = client.call(METHOD_CHAT_HISTORY, params, callback=callback)
    if req_id:
        gateway_logger.info(
            f"local_to_server: 已发送 chat.history sessionKey={session_key} limit={params['limit']} req_id={req_id}"
        )
    return req_id


def send_status(client, callback: Callable[[bool, Any, Optional[dict]], None]) -> Optional[str]:
    """
    向服务端请求 status。
    用途：状态/能力查询。
    """
    if not client or not getattr(client, "call", None):
        if callback:
            callback(False, None, {"message": "Gateway 客户端不可用"})
        return None
    return client.call(METHOD_STATUS, {}, callback=callback)


def send_sessions_list(
    client,
    params: Optional[dict] = None,
    callback: Optional[Callable[[bool, Any, Optional[dict]], None]] = None,
) -> Optional[str]:
    """
    向服务端请求 sessions.list（可选，用于会话列表补充）。
    用途：拉取会话列表；可与 health 配合使用。
    """
    if not client or not getattr(client, "call", None):
        if callback:
            callback(False, None, {"message": "Gateway 客户端不可用"})
        return None
    return client.call(METHOD_SESSIONS_LIST, params or {"limit": 10}, callback=callback)


def send_sessions_patch(
    client,
    key: str,
    patch_params: dict,
    callback: Callable[[bool, Any, Optional[dict]], None],
) -> Optional[str]:
    """
    向服务端请求 sessions.patch（修改会话属性，如 model）。
    用途：切换模型时对当前 agent 的 main 会话设置 model。
    参数：key 为会话 key（如 agent:main:main）；patch_params 可含 model、thinkingLevel 等。
    回调：callback(ok, payload, error)；ok 时 payload 含 key 等。
    """
    if not client or not getattr(client, "call", None):
        if callback:
            callback(False, None, {"message": "Gateway 客户端不可用"})
        return None
    k = (key or "").strip()
    if not k:
        if callback:
            callback(False, None, {"message": "sessions.patch 需要非空 key"})
        return None
    params = {"key": k, **patch_params}
    req_id = client.call(METHOD_SESSIONS_PATCH, params, callback=callback)
    if req_id:
        gateway_logger.info(f"local_to_server: 已发送 sessions.patch key={k} req_id={req_id}")
    return req_id


def send_sessions_delete(
    client,
    session_key: str,
    callback: Callable[[bool, Any, Optional[dict]], None],
) -> Optional[str]:
    """
    向服务端请求 sessions.delete（删除指定会话）。
    用途：用户在会话管理中点击删除选中会话时调用。
    参数：session_key 即会话 key（如 agent:main:claw_pet）；服务端禁止删除 main 会话。
    回调：callback(ok, payload, error)；ok 时 payload 含 deleted: bool。
    """
    if not client or not getattr(client, "call", None):
        if callback:
            callback(False, None, {"message": "Gateway 客户端不可用"})
        return None
    key = (session_key or "").strip()
    if not key:
        if callback:
            callback(False, None, {"message": "sessions.delete 需要非空 key"})
        return None
    params = {"key": key}
    req_id = client.call(METHOD_SESSIONS_DELETE, params, callback=callback)
    if req_id:
        gateway_logger.info(f"local_to_server: 已发送 sessions.delete key={key} req_id={req_id}")
    return req_id


def send_cron_list(
    client,
    include_disabled: bool = True,
    callback: Optional[Callable[[bool, Any, Optional[dict]], None]] = None,
) -> Optional[str]:
    """向服务端请求 cron.list（定时任务列表）。payload 含 jobs 数组。"""
    if not client or not getattr(client, "call", None):
        if callback:
            callback(False, None, {"message": "Gateway 客户端不可用"})
        return None
    params = {"includeDisabled": include_disabled}
    req_id = client.call(METHOD_CRON_LIST, params, callback=callback)
    if req_id:
        gateway_logger.debug(f"local_to_server: 已发送 cron.list req_id={req_id}")
    return req_id


def send_cron_status(
    client,
    callback: Optional[Callable[[bool, Any, Optional[dict]], None]] = None,
) -> Optional[str]:
    """向服务端请求 cron.status（定时任务服务状态）。"""
    if not client or not getattr(client, "call", None):
        if callback:
            callback(False, None, {"message": "Gateway 客户端不可用"})
        return None
    req_id = client.call(METHOD_CRON_STATUS, {}, callback=callback)
    if req_id:
        gateway_logger.debug(f"local_to_server: 已发送 cron.status req_id={req_id}")
    return req_id


def send_cron_add(
    client,
    name: str,
    enabled: bool,
    schedule: dict,
    payload: dict,
    callback: Optional[Callable[[bool, Any, Optional[dict]], None]] = None,
) -> Optional[str]:
    """向服务端请求 cron.add。schedule 如 {kind: "every", everyMs: 60000} 或 {kind: "at", atMs: ts}。payload 如 {kind: "systemEvent", text: "提醒"}。"""
    if not client or not getattr(client, "call", None):
        if callback:
            callback(False, None, {"message": "Gateway 客户端不可用"})
        return None
    params = {"name": (name or "").strip() or "任务", "enabled": bool(enabled), "schedule": schedule or {}, "payload": payload or {}}
    req_id = client.call(METHOD_CRON_ADD, params, callback=callback)
    if req_id:
        gateway_logger.info(f"local_to_server: 已发送 cron.add name={params['name']} req_id={req_id}")
    return req_id


def send_cron_update(
    client,
    job_id: str,
    patch: dict,
    callback: Optional[Callable[[bool, Any, Optional[dict]], None]] = None,
) -> Optional[str]:
    """向服务端请求 cron.update。patch 可含 enabled、name、schedule、payload 等。"""
    if not client or not getattr(client, "call", None):
        if callback:
            callback(False, None, {"message": "Gateway 客户端不可用"})
        return None
    job_id = (job_id or "").strip()
    if not job_id:
        if callback:
            callback(False, None, {"message": "cron.update 需要非空 id"})
        return None
    params = {"id": job_id, "patch": patch or {}}
    req_id = client.call(METHOD_CRON_UPDATE, params, callback=callback)
    if req_id:
        gateway_logger.info(f"local_to_server: 已发送 cron.update id={job_id} req_id={req_id}")
    return req_id


def send_cron_remove(
    client,
    job_id: str,
    callback: Optional[Callable[[bool, Any, Optional[dict]], None]] = None,
) -> Optional[str]:
    """向服务端请求 cron.remove（删除定时任务）。"""
    if not client or not getattr(client, "call", None):
        if callback:
            callback(False, None, {"message": "Gateway 客户端不可用"})
        return None
    job_id = (job_id or "").strip()
    if not job_id:
        if callback:
            callback(False, None, {"message": "cron.remove 需要非空 id"})
        return None
    params = {"id": job_id}
    req_id = client.call(METHOD_CRON_REMOVE, params, callback=callback)
    if req_id:
        gateway_logger.info(f"local_to_server: 已发送 cron.remove id={job_id} req_id={req_id}")
    return req_id


def send_cron_run(
    client,
    job_id: str,
    mode: str = "force",
    callback: Optional[Callable[[bool, Any, Optional[dict]], None]] = None,
) -> Optional[str]:
    """向服务端请求 cron.run（立即运行一次）。mode 如 "force"。"""
    if not client or not getattr(client, "call", None):
        if callback:
            callback(False, None, {"message": "Gateway 客户端不可用"})
        return None
    job_id = (job_id or "").strip()
    if not job_id:
        if callback:
            callback(False, None, {"message": "cron.run 需要非空 id"})
        return None
    params = {"id": job_id, "mode": (mode or "force").strip() or "force"}
    req_id = client.call(METHOD_CRON_RUN, params, callback=callback)
    if req_id:
        gateway_logger.info(f"local_to_server: 已发送 cron.run id={job_id} req_id={req_id}")
    return req_id


def send_cron_runs(
    client,
    job_id: str,
    limit: int = 50,
    callback: Optional[Callable[[bool, Any, Optional[dict]], None]] = None,
) -> Optional[str]:
    """向服务端请求 cron.runs（某任务的运行记录）。"""
    if not client or not getattr(client, "call", None):
        if callback:
            callback(False, None, {"message": "Gateway 客户端不可用"})
        return None
    job_id = (job_id or "").strip()
    if not job_id:
        if callback:
            callback(False, None, {"message": "cron.runs 需要非空 id"})
        return None
    params = {"id": job_id, "limit": max(1, min(200, limit))}
    req_id = client.call(METHOD_CRON_RUNS, params, callback=callback)
    if req_id:
        gateway_logger.debug(f"local_to_server: 已发送 cron.runs id={job_id} req_id={req_id}")
    return req_id


def send_params(
    client,
    params: dict,
    callback: Callable[[bool, Any, Optional[dict]], None],
) -> Optional[str]:
    """
    向服务端发送参数（占位，具体 method 按 Gateway 协议扩展）。
    用途：参数下发、配置同步等。
    """
    if not client or not getattr(client, "call", None):
        if callback:
            callback(False, None, {"message": "Gateway 客户端不可用"})
        return None
    # 占位：后续按协议定 method，如 config.set 等
    gateway_logger.debug(f"local_to_server: send_params 占位 params={list(params.keys())}")
    if callback:
        callback(False, None, {"message": "send_params 尚未实现具体 method"})
    return None


def modify_params(
    client,
    key: str,
    value: Any,
    callback: Callable[[bool, Any, Optional[dict]], None],
) -> Optional[str]:
    """
    向服务端修改单条参数（占位，具体 method 按 Gateway 协议扩展）。
    用途：单键配置修改。
    """
    if not client or not getattr(client, "call", None):
        if callback:
            callback(False, None, {"message": "Gateway 客户端不可用"})
        return None
    gateway_logger.debug(f"local_to_server: modify_params 占位 key={key}")
    if callback:
        callback(False, None, {"message": "modify_params 尚未实现具体 method"})
    return None
