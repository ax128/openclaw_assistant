"""
SSH 本地端口转发隧道：在后台线程执行 ssh -N -L {port}:127.0.0.1:{port} user@server，
不阻塞主线程；等待隧道就绪（本地端口可连）后再返回，供 Gateway 连接使用。
程序退出时通过 atexit 自动断开隧道（subprocess 终止、paramiko 连接关闭）。
"""
import atexit
import socket
import threading
import time
from typing import Optional, Tuple

from utils.logger import logger

_ssh_process = None
_ssh_process_lock = threading.Lock()

# paramiko 隧道引用，供退出时关闭
_paramiko_client = None
_paramiko_server_sock = None
_paramiko_lock = threading.Lock()


def _wait_port_ready(host: str, port: int, timeout_sec: float = 15.0, interval_sec: float = 0.3) -> bool:
    """等待本地端口可连接，返回是否就绪。"""
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1.0)
            s.connect((host, port))
            s.close()
            return True
        except (socket.error, OSError):
            time.sleep(interval_sec)
    return False


def start_ssh_tunnel(
    port: int,
    username: str,
    server: str,
    password: Optional[str] = None,
) -> Tuple[bool, str]:
    """
    在后台线程启动 SSH 隧道：ssh -N -L {port}:127.0.0.1:{port} {username}@{server}。
    不阻塞；等待本地 port 可连后返回。password 可选（为空则依赖密钥/agent）。
    返回 (success, error_message)。
    """
    username = (username or "").strip()
    server = (server or "").strip()
    if not username or not server:
        return False, "SSH 用户名与服务器地址必填"
    try:
        port = int(port)
    except (TypeError, ValueError):
        return False, "端口必须为数字"

    # 优先尝试 paramiko（支持密码）；否则用 subprocess ssh（无密码或密钥）
    if password:
        try:
            return _start_tunnel_paramiko(port, username, server, password)
        except ImportError:
            logger.warning(f"未安装 paramiko，SSH 密码将不可用；请使用密钥或安装: pip install paramiko")
            return False, "使用 SSH 密码需要安装 paramiko: pip install paramiko"

    return _start_tunnel_subprocess(port, username, server)


def _start_tunnel_subprocess(port: int, username: str, server: str) -> Tuple[bool, str]:
    """使用 subprocess 执行 ssh -N -L，后台线程挂机。"""
    import subprocess
    global _ssh_process
    cmd = [
        "ssh", "-N", "-L", f"{port}:127.0.0.1:{port}",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "ConnectTimeout=10",
        f"{username}@{server}",
    ]
    logger.info(f"SSH 隧道启动: {' '.join(cmd)}")

    def run():
        global _ssh_process
        try:
            with _ssh_process_lock:
                _ssh_process = subprocess.Popen(
                    cmd,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                )
            _ssh_process.wait()
        except Exception as e:
            logger.debug(f"SSH 隧道进程结束: {e}")
        finally:
            with _ssh_process_lock:
                _ssh_process = None

    t = threading.Thread(target=run, daemon=True)
    t.start()
    if not _wait_port_ready("127.0.0.1", port, timeout_sec=15.0):
        with _ssh_process_lock:
            p = _ssh_process
        if p:
            try:
                p.terminate()
            except Exception:
                pass
        return False, "SSH 隧道端口就绪超时，请检查用户名、服务器与密钥"
    return True, ""


def _relay_sock_to_channel(sock, channel) -> None:
    """单向：socket -> channel。"""
    try:
        while True:
            data = sock.recv(4096)
            if not data:
                break
            channel.send(data)
    except Exception:
        pass
    try:
        channel.close()
        sock.close()
    except Exception:
        pass


def _relay_channel_to_sock(channel, sock) -> None:
    """单向：channel -> socket。"""
    try:
        while True:
            data = channel.recv(4096)
            if not data:
                break
            sock.sendall(data)
    except Exception:
        pass
    try:
        channel.close()
        sock.close()
    except Exception:
        pass


def _start_tunnel_paramiko(port: int, username: str, server: str, password: str) -> Tuple[bool, str]:
    """使用 paramiko 建立本地端口转发（-L，支持密码）：本地监听 port，转发到远程 127.0.0.1:port。"""
    import paramiko
    global _paramiko_client, _paramiko_server_sock
    logger.info(f"SSH 隧道启动(paramiko): {username}@{server} -> 127.0.0.1:{port}")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            hostname=server,
            port=22,
            username=username,
            password=password or None,
            timeout=10,
            allow_agent=False,
            look_for_keys=False,
        )
    except Exception as e:
        return False, f"SSH 连接失败: {e}"

    transport = client.get_transport()
    if not transport:
        client.close()
        return False, "SSH 连接无 transport"

    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server_sock.bind(("", port))
        server_sock.listen(5)
        server_sock.settimeout(1.0)
    except Exception as e:
        client.close()
        return False, f"本地端口 {port} 绑定失败: {e}"

    def accept_loop():
        try:
            while True:
                try:
                    conn, addr = server_sock.accept()
                except socket.timeout:
                    continue
                except Exception:
                    break
                try:
                    channel = transport.open_channel(
                        "direct-tcpip", ("127.0.0.1", port), addr
                    )
                except Exception:
                    conn.close()
                    continue
                t1 = threading.Thread(target=_relay_sock_to_channel, args=(conn, channel), daemon=True)
                t2 = threading.Thread(target=_relay_channel_to_sock, args=(channel, conn), daemon=True)
                t1.start()
                t2.start()
        finally:
            try:
                server_sock.close()
                client.close()
            except Exception:
                pass

    t = threading.Thread(target=accept_loop, daemon=True)
    t.start()
    if not _wait_port_ready("127.0.0.1", port, timeout_sec=5.0):
        try:
            server_sock.close()
            client.close()
        except Exception:
            pass
        return False, "SSH 隧道端口就绪超时"
    # 保存引用，供程序退出时 stop_ssh_tunnel 关闭
    with _paramiko_lock:
        _paramiko_client = client
        _paramiko_server_sock = server_sock
    return True, ""


def stop_ssh_tunnel() -> None:
    """停止当前 SSH 隧道：终止 subprocess 或关闭 paramiko 连接。程序退出时由 atexit 自动调用。"""
    global _ssh_process, _paramiko_client, _paramiko_server_sock

    # 终止 subprocess 隧道
    with _ssh_process_lock:
        p = _ssh_process
        _ssh_process = None
    if p is not None and getattr(p, "terminate", None):
        try:
            p.terminate()
        except Exception:
            pass

    # 关闭 paramiko 隧道（先关 server_sock 让 accept_loop 退出，再关 client）
    with _paramiko_lock:
        sock = _paramiko_server_sock
        client = _paramiko_client
        _paramiko_server_sock = None
        _paramiko_client = None
    if sock is not None:
        try:
            sock.close()
        except Exception:
            pass
    if client is not None:
        try:
            client.close()
        except Exception:
            pass


# 程序退出时自动断开隧道，避免遗留 ssh 子进程或未关闭连接
atexit.register(stop_ssh_tunnel)
