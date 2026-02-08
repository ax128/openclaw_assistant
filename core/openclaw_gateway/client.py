"""
OpenClaw Gateway WebSocket 客户端。
在后台线程运行 asyncio + websockets，对外提供同步风格 call(method, params, callback) 与事件回调。
主线程调度通过 set_main_thread_runner(runner) 注入，便于 UI 安全更新。
"""
import json
import threading
import asyncio
from typing import Callable, Any, Optional
from utils.logger import logger, gateway_logger
from utils.platform_adapter import platform_name
from .protocol import (
    PROTOCOL_VERSION,
    METHOD_CONNECT,
    METHOD_AGENT,
    build_connect_params,
    build_request_frame,
    parse_response_frame,
    parse_event_frame,
)
from . import server_to_local as stl
from . import gateway_memory as gmem

try:
    import websockets
    from websockets.exceptions import InvalidMessage
except ImportError:
    websockets = None
    InvalidMessage = None  # type: ignore[misc, assignment]


def _connection_error_message(exc: BaseException) -> str:
    """将连接异常转为用户可读提示（首次连接失败时返回给 UI）。"""
    if isinstance(exc, ConnectionResetError):
        return (
            "连接被重置：请确认 OpenClaw Gateway 已启动，且地址正确（如 ws://127.0.0.1:18789）。"
            "若为远程地址，请检查网络与防火墙。"
        )
    if InvalidMessage is not None and isinstance(exc, InvalidMessage):
        return (
            "未收到有效 HTTP 响应：目标地址可能不是 WebSocket 服务或服务未启动。"
            "请确认 Gateway 已启动且 URL 为 WebSocket 地址（如 ws://127.0.0.1:18789）。"
        )
    if isinstance(exc, ConnectionRefusedError):
        return "连接被拒绝：请确认 OpenClaw Gateway 已启动且端口正确（如 18789）。"
    if isinstance(exc, OSError) and getattr(exc, "winerror", None) == 64:
        # WinError 64: 指定的网络名不再可用
        return (
            "网络名不可用：请确认 Gateway 地址正确且服务已启动（如 ws://127.0.0.1:18789）。"
            "若使用远程地址，请检查网络与 VPN。"
        )
    return str(exc)


class GatewayClient:
    """
    OpenClaw Gateway WebSocket 客户端。
    - connect(url, token) 连接并握手。
    - call(method, params, callback=None) 发送请求，callback(ok, payload, error) 在主线程被调用。
    - on_event(callback) 注册事件回调，callback(event_name, payload) 在主线程被调用。
    - set_main_thread_runner(runner) 注入主线程执行器，runner(callable) 在主线程执行 callable。
    """

    def __init__(self):
        self._ws = None
        self._loop = None
        self._thread = None
        self._connected = False
        self._hello_payload = None
        # req_id -> (callback, method)；agent 需等多段响应（accepted -> ok/error）再回调
        self._pending: dict[str, tuple[Callable[[bool, Any, Optional[dict]], None], str]] = {}
        self._event_listeners: list[Callable[[str, Any], None]] = []
        self._on_connected_callbacks: list[Callable[[], None]] = []
        self._on_disconnected_callbacks: list[Callable[[], None]] = []
        self._main_thread_runner: Optional[Callable[[Callable[[], None]], None]] = None
        self._challenge_nonce: str = ""
        self._send_queue: Optional[asyncio.Queue] = None
        # 发送队列上限，超出时回调「请求繁忙」避免堆积（优化建议：背压）
        self._send_queue_max_size: int = 100
        self._on_shutdown_callbacks: list[Callable[[dict], None]] = []
        # 退避重连：连接关闭后 delay 秒重试，每次失败 +3 秒，无限累加
        self._connect_url: str = ""
        self._connect_token: str = ""
        self._connect_password: str = ""
        self._reconnect_delay_sec: float = 3.0
        self._user_requested_disconnect: bool = False

    def set_main_thread_runner(self, runner: Callable[[Callable[[], None]], None]) -> None:
        """设置主线程执行器（如 QTimer.singleShot(0, fn)），用于回调与事件派发。"""
        self._main_thread_runner = runner

    def _run_on_main(self, fn: Callable[[], None]) -> None:
        if self._main_thread_runner:
            self._main_thread_runner(fn)
        else:
            fn()

    def on_event(self, callback: Callable[[str, Any], None]) -> None:
        """注册事件回调，事件在主线程触发。"""
        self._event_listeners.append(callback)

    def register_on_connected(self, callback: Callable[[], None]) -> None:
        """注册连接成功回调（主线程调用），握手成功或退避重连成功时触发。"""
        self._on_connected_callbacks.append(callback)

    def register_on_disconnected(self, callback: Callable[[], None]) -> None:
        """注册连接断开回调（主线程调用），连接关闭或用户主动断开时触发。"""
        self._on_disconnected_callbacks.append(callback)

    def register_on_shutdown(self, callback: Callable[[dict], None]) -> None:
        """注册 shutdown 事件回调（主线程调用），payload 含 reason、restartExpectedMs 等。"""
        self._on_shutdown_callbacks.append(callback)

    def connect(self, url: str, token: str = "", password: str = "") -> tuple[bool, str]:
        """
        连接并握手。应在主线程或启动时调用；内部会在后台线程执行连接。
        连接关闭（含 1012 service restart）后自动退避重连：3 秒后重试，每次失败 +3 秒，无限累加。
        返回 (success, error_message)。success 为 True 时 error_message 为空。
        """
        if websockets is None:
            return False, "请安装 websockets: pip install websockets"
        self._user_requested_disconnect = True
        self._connect_url = (url or "").strip()
        self._connect_token = token or ""
        self._connect_password = password or ""
        self._reconnect_delay_sec = 3.0
        self._user_requested_disconnect = False
        gateway_logger.info(f"Gateway 开始连接: {self._connect_url}（独立线程 + asyncio）")
        ev = threading.Event()
        result: list[tuple[bool, str]] = []

        def do_connect():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            gateway_logger.info(f"Gateway 工作线程已启动（独立 asyncio 事件循环）")
            self._loop.run_until_complete(_run_connection_loop(ev, result))

        async def _run_connection_loop(ev: threading.Event, result: list):
            first_attempt = True
            delay = self._reconnect_delay_sec
            url = self._connect_url
            token = self._connect_token
            password = self._connect_password
            while True:
                if self._user_requested_disconnect:
                    break
                try:
                    ws = await websockets.connect(
                        url,
                        ping_interval=20,
                        ping_timeout=10,
                    )
                    # 收 connect.challenge
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
                        data = json.loads(msg)
                        if isinstance(data, dict) and data.get("type") == "event" and data.get("event") == "connect.challenge":
                            self._challenge_nonce = (data.get("payload") or {}).get("nonce") or ""
                    except asyncio.TimeoutError:
                        pass
                    params = build_connect_params(
                        token=token,
                        password=password,
                        challenge_nonce=self._challenge_nonce,
                        platform=platform_name(),
                    )
                    req_id, frame = build_request_frame(METHOD_CONNECT, params)
                    await ws.send(json.dumps(frame))
                    resp = await ws.recv()
                    res = json.loads(resp)
                    rid, ok, payload, err = parse_response_frame(res)
                    if rid != req_id:
                        if first_attempt:
                            result.append((False, "握手响应 id 不匹配"))
                            ev.set()
                            return
                        delay += 3
                        gateway_logger.info(f"Gateway 重连失败（握手 id 不匹配），{delay} 秒后重试")
                        await asyncio.sleep(delay)
                        continue
                    if not ok:
                        if first_attempt:
                            msg = (err or {}).get("message", "未知错误")
                            result.append((False, msg))
                            ev.set()
                            return
                        delay += 3
                        gateway_logger.info(f"Gateway 重连失败，{delay} 秒后重试")
                        await asyncio.sleep(delay)
                        continue
                    self._ws = ws
                    self._hello_payload = payload or {}
                    self._connected = True
                    self._send_queue = asyncio.Queue()
                    snapshot_health = (payload or {}).get("snapshot", {}).get("health")
                    if snapshot_health is not None:
                        gmem.gateway_memory.set_health(True, snapshot_health, None)
                        gateway_logger.info(f"Gateway 已写入 connect snapshot.health 到内存")
                    if first_attempt:
                        result.append((True, ""))
                        ev.set()
                    else:
                        gateway_logger.info(f"Gateway 退避重连成功")
                    first_attempt = False
                    delay = 3.0
                    gateway_logger.info(f"Gateway 握手成功，收发循环已启动")
                    for cb in self._on_connected_callbacks:
                        self._run_on_main(cb)

                    async def send_loop():
                        while self._ws and self._connected:
                            try:
                                frame = await asyncio.wait_for(self._send_queue.get(), timeout=1.0)
                                await ws.send(json.dumps(frame))
                            except asyncio.TimeoutError:
                                continue
                            except Exception as e:
                                gateway_logger.debug(f"Gateway send 结束: {e}")
                                break

                    async def recv_loop():
                        while self._ws and self._connected:
                            try:
                                raw = await ws.recv()
                            except Exception as e:
                                gateway_logger.debug(f"Gateway recv 结束: {e}")
                                return
                            try:
                                data = json.loads(raw)
                            except json.JSONDecodeError:
                                continue
                            frame_type = (data or {}).get("type", "")
                            rid, ok, payload, error = parse_response_frame(data)
                            if rid is not None:
                                entry = self._pending.get(rid)
                                if not entry:
                                    gateway_logger.debug(f"Gateway 响应无对应 callback: req_id={rid}")
                                    continue
                                cb, method = entry
                                if method == METHOD_AGENT:
                                    status = (payload or {}).get("status")
                                    if status == "accepted":
                                        gateway_logger.debug(f"Gateway agent 已接受，等待完成: req_id={rid}")
                                        continue
                                    if status == "ok":
                                        res = (payload or {}).get("result")
                                        if res is None:
                                            res = {}
                                        self._pending.pop(rid, None)
                                        stl.on_response(METHOD_AGENT, True, payload, None)
                                        gateway_logger.info(f"Gateway 响应: req_id={rid} agent ok")
                                        self._run_on_main(lambda c=cb, r=res: c(True, r, None))
                                        continue
                                    if status == "error":
                                        summary = (payload or {}).get("summary") or str(payload or "")
                                        self._pending.pop(rid, None)
                                        stl.on_response(METHOD_AGENT, False, None, {"message": summary})
                                        gateway_logger.info(f"Gateway 响应: req_id={rid} agent error")
                                        self._run_on_main(lambda c=cb, s=summary: c(False, None, {"message": s}))
                                        continue
                                    self._pending.pop(rid, None)
                                    stl.on_response(method, ok, payload, error)
                                    self._run_on_main(lambda c=cb, o=ok, p=payload, e=error: c(o, p, e))
                                    continue
                                self._pending.pop(rid, None)
                                stl.on_response(method, ok, payload, error)
                                if method == "health":
                                    gmem.gateway_memory.set_health(ok, payload, error)
                                if method != "health":
                                    gateway_logger.info(f"Gateway 响应: req_id={rid} ok={ok}")
                                else:
                                    gateway_logger.debug(f"Gateway 响应: req_id={rid} ok={ok}")
                                self._run_on_main(lambda c=cb, o=ok, p=payload, e=error: c(o, p, e))
                                continue
                            event_name, event_payload = parse_event_frame(data)
                            if event_name is not None:
                                stl.on_event(event_name, event_payload)
                                if event_name == "shutdown":
                                    payload = event_payload or {}
                                    for shutdown_cb in self._on_shutdown_callbacks:
                                        self._run_on_main(lambda cb=shutdown_cb, pl=payload: cb(pl))
                                if event_name not in ("tick", "health", "agent"):
                                    gateway_logger.debug(f"Gateway 事件: event={event_name}")
                                for listener in self._event_listeners:
                                    self._run_on_main(
                                        lambda l=listener, n=event_name, p=event_payload: l(n, p or {})
                                    )
                                continue
                            if frame_type:
                                gateway_logger.debug(f"Gateway 未处理帧: type={frame_type}")

                    await asyncio.gather(send_loop(), recv_loop())
                    for req_id, entry in list(self._pending.items()):
                        cb = entry[0] if isinstance(entry, tuple) else entry
                        self._run_on_main(lambda c=cb: c(False, None, {"message": "连接已关闭"}))
                    self._pending.clear()
                    self._connected = False
                    self._ws = None
                    self._send_queue = None
                    gateway_logger.debug(f"Gateway 收发循环已结束，连接已关闭")
                    for cb in self._on_disconnected_callbacks:
                        self._run_on_main(cb)
                    if self._user_requested_disconnect:
                        break
                    gateway_logger.info(f"Gateway 退避重连：{delay} 秒后重试")
                    await asyncio.sleep(delay)
                except Exception as e:
                    if first_attempt:
                        gateway_logger.exception(f"Gateway 连接失败: {e}")
                        result.append((False, _connection_error_message(e)))
                        ev.set()
                        return
                    delay += 3
                    gateway_logger.warning(f"Gateway 重连失败: {e}，{delay} 秒后重试")
                    await asyncio.sleep(delay)
        self._thread = threading.Thread(target=do_connect, daemon=True)
        self._thread.start()
        ev.wait(timeout=15.0)
        if not result:
            return False, "连接超时"
        return result[0][0], result[0][1]

    def disconnect(self, silent: bool = False) -> None:
        """断开连接；停止退避重连。silent=True 时不触发 on_disconnected 回调（用于重连前先断开，避免重复提示）。"""
        self._user_requested_disconnect = True
        self._connected = False
        gmem.gateway_memory.clear_health()
        gmem.gateway_memory.clear_config()
        if not silent:
            for cb in self._on_disconnected_callbacks:
                self._run_on_main(cb)
        ws = self._ws
        self._ws = None
        if ws and self._loop:
            try:
                self._loop.call_soon_threadsafe(ws.close)
            except Exception:
                pass
        for req_id, entry in list(self._pending.items()):
            cb = entry[0] if isinstance(entry, tuple) else entry
            self._run_on_main(lambda c=cb: c(False, None, {"message": "连接已关闭"}))
        self._pending.clear()

    def is_connected(self) -> bool:
        return bool(self._connected and self._ws)

    def get_hello_payload(self) -> dict:
        """握手成功后的 hello payload（含 features.methods、snapshot 等）。"""
        return self._hello_payload or {}

    def get_supported_methods(self) -> list:
        """握手成功后根据 hello-ok 的 features.methods 返回支持的方法列表；未连接或未握手返回 []。"""
        hello = self._hello_payload or {}
        features = hello.get("features") if isinstance(hello, dict) else None
        if not isinstance(features, dict):
            return []
        methods = features.get("methods")
        return list(methods) if isinstance(methods, list) else []

    def get_supported_events(self) -> list:
        """握手成功后根据 hello-ok 的 features.events 返回支持的事件列表；未连接或未握手返回 []。"""
        hello = self._hello_payload or {}
        features = hello.get("features") if isinstance(hello, dict) else None
        if not isinstance(features, dict):
            return []
        events = features.get("events")
        return list(events) if isinstance(events, list) else []

    def supports_method(self, method: str) -> bool:
        """当前 Gateway 是否支持指定方法（根据握手 hello-ok 的 features.methods）。"""
        return method in self.get_supported_methods()

    def call(
        self,
        method: str,
        params: Optional[dict] = None,
        callback: Optional[Callable[[bool, Any, Optional[dict]], None]] = None,
    ) -> Optional[str]:
        """
        发送请求。若提供 callback，则在主线程调用 callback(ok, payload, error)。
        返回请求 id；若未连接则返回 None。
        """
        if not self._ws or not self._connected or not self._loop:
            gateway_logger.warning(f"Gateway call 未连接，method={method}")
            if callback:
                self._run_on_main(lambda: callback(False, None, {"message": "未连接"}))
            return None
        q = getattr(self, "_send_queue", None)
        max_size = getattr(self, "_send_queue_max_size", 100)
        if q is not None and q.qsize() >= max_size:
            gateway_logger.warning(f"Gateway 发送队列已满 ({q.qsize()} >= {max_size})，method={method}")
            if callback:
                self._run_on_main(lambda: callback(False, None, {"message": "请求繁忙，请稍后再试"}))
            return None
        req_id, frame = build_request_frame(method, params or {})
        if callback:
            self._pending[req_id] = (callback, method)
        if method != "health":
            gateway_logger.info(f"Gateway 请求: method={method} req_id={req_id}")
        else:
            gateway_logger.debug(f"Gateway 请求: method={method} req_id={req_id}")
        try:
            if q:
                self._loop.call_soon_threadsafe(q.put_nowait, frame)
        except Exception as e:
            gateway_logger.exception(f"Gateway call 失败: {e}")
            if callback:
                self._pending.pop(req_id, None)
                self._run_on_main(lambda: callback(False, None, {"message": str(e)}))
            return None
        return req_id


def _read_first_line(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return (f.readline() or "").strip()
    except OSError:
        return ""


def resolve_gateway_token(settings_get: Callable[[str, str], str], script_dir: str = "") -> str:
    """从配置或同目录 gateway_token.txt 解析 token。"""
    token = (settings_get("gateway_token", "") or "").strip()
    if token:
        return token
    if script_dir:
        for name in ("gateway_token.txt", ".gateway_token"):
            token = _read_first_line(__import__("os").path.join(script_dir, name))
            if token:
                return token
    return ""
