"""
语音模块 - 使用 edge-tts（Microsoft Edge 在线神经语音）合成并播放文字，供气泡框等输出时同步朗读。
轻量、无需本地大模型，音质自然；输出 MP3，Windows 下用 MCI 播放，其它平台用 playsound。
"""
import asyncio
import os
import tempfile
import threading
import time
from utils.logger import logger

try:
    import edge_tts
    EDGE_TTS_AVAILABLE = True
except ImportError:
    EDGE_TTS_AVAILABLE = False
    logger.warning("edge-tts 未安装，语音功能不可用。可执行: pip install edge-tts")


def _play_mp3_win(path: str) -> bool:
    """仅 Windows：用 winmm.mciSendString 播放 mp3。play 不带 wait + 轮询，以便点关闭时同线程内 stop/close 可立即停声。"""
    if os.name != "nt":
        return False
    global _CURRENT_MCI_ALIAS, _STOP_FLAG
    alias = None
    try:
        import ctypes
        winmm = ctypes.windll.winmm
        alias = "pet_voice_" + str(time.time_ns() % 1000000)
        path_n = os.path.normpath(os.path.abspath(path))
        path_esc = path_n.replace("\\", "\\\\")
        winmm.mciSendStringW("close " + alias, None, 0, None)
        err = winmm.mciSendStringW(f'open "{path_esc}" type mpegvideo alias {alias}', None, 0, None)
        if err != 0:
            return False
        with _MCI_ALIAS_LOCK:
            _CURRENT_MCI_ALIAS = alias
        err = winmm.mciSendStringW("play " + alias, None, 0, None)
        if err != 0:
            return False
        buf = ctypes.create_unicode_buffer(64)
        while True:
            if _STOP_FLAG.is_set():
                try:
                    winmm.mciSendStringW("stop " + alias, None, 0, None)
                    winmm.mciSendStringW("close " + alias, None, 0, None)
                except Exception:
                    pass
                return True
            try:
                winmm.mciSendStringW("status " + alias + " mode", buf, 64, None)
                if (buf.value or "").strip().lower() in ("stopped", "not ready", ""):
                    break
            except Exception:
                break
            time.sleep(0.08)
        try:
            winmm.mciSendStringW("close " + alias, None, 0, None)
        except Exception:
            pass
        return True
    except Exception:
        return False
    finally:
        with _MCI_ALIAS_LOCK:
            if _CURRENT_MCI_ALIAS == alias:
                _CURRENT_MCI_ALIAS = None
        if alias and os.name == "nt":
            try:
                import ctypes as _ct
                _ct.windll.winmm.mciSendStringW("close " + alias, None, 0, None)
            except Exception:
                pass

try:
    from playsound import playsound
    PLAYSOUND_AVAILABLE = True
except ImportError:
    PLAYSOUND_AVAILABLE = False
    logger.warning("playsound 未安装，语音播放不可用。可执行: pip install playsound")


def _get_mp3_duration_seconds(path: str) -> float:
    """获取 mp3 时长（秒），失败时按默认估计返回。"""
    try:
        from mutagen.mp3 import MP3
        return MP3(path).info.length
    except Exception:
        pass
    return 15.0


DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"

# 备选音色：(voice_id, 菜单显示名)，Microsoft 神经语音，见 https://speech.microsoft.com/portal/voicegallery
VOICE_OPTIONS = [
    # 中文（普通话）
    ("zh-CN-XiaoxiaoNeural", "晓晓（女）"),
    ("zh-CN-XiaoyiNeural", "晓伊（女）"),
    ("zh-CN-YunxiNeural", "云希（男）"),
    ("zh-CN-YunyangNeural", "云扬（男）"),
    ("zh-CN-YunjianNeural", "云健（男）"),
    ("zh-CN-YunxiaNeural", "云夏（女）"),
    ("zh-CN-liaoning-XiaobeiNeural", "东北晓北（女）"),
    ("zh-CN-shaanxi-XiaoniNeural", "陕西晓妮（女）"),
    # 中文（台湾）
    ("zh-TW-HsiaoChenNeural", "晓臻（台，女）"),
    ("zh-TW-YunJheNeural", "云哲（台，男）"),
    # 英语（美）
    ("en-US-JennyNeural", "Jenny（美，女）"),
    ("en-US-GuyNeural", "Guy（美，男）"),
    ("en-US-AriaNeural", "Aria（美，女）"),
    ("en-US-ChristopherNeural", "Christopher（美，男）"),
    ("en-US-EmmaNeural", "Emma（美，女）"),
    ("en-US-AndrewNeural", "Andrew（美，男）"),
    # 英语（英）
    ("en-GB-SoniaNeural", "Sonia（英，女）"),
    ("en-GB-RyanNeural", "Ryan（英，男）"),
    ("en-GB-LibbyNeural", "Libby（英，女）"),
    ("en-GB-ThomasNeural", "Thomas（英，男）"),
    # 日语
    ("ja-JP-NanamiNeural", "七海（女）"),
    ("ja-JP-KeitaNeural", "庆太（男）"),
    # 韩语
    ("ko-KR-SunHiNeural", "SunHi（韩，女）"),
    ("ko-KR-InJoonNeural", "InJoon（韩，男）"),
    # 法语
    ("fr-FR-DeniseNeural", "Denise（法，女）"),
    ("fr-FR-HenriNeural", "Henri（法，男）"),
    # 德语
    ("de-DE-KatjaNeural", "Katja（德，女）"),
    ("de-DE-ConradNeural", "Conrad（德，男）"),
    # 西班牙语
    ("es-ES-ElviraNeural", "Elvira（西，女）"),
    ("es-ES-AlvaroNeural", "Alvaro（西，男）"),
]

# 防止并发播放冲突
_PLAY_LOCK = threading.Lock()
_STOP_FLAG = threading.Event()
_CURRENT_VOICE_THREAD = None
_CURRENT_MCI_ALIAS = None
_MCI_ALIAS_LOCK = threading.Lock()


def _run_async_speak(text: str, voice: str = DEFAULT_VOICE, on_duration_ready=None, on_playback_finished=None) -> None:
    """在独立事件循环中执行 edge-tts 合成 + 播放（供子线程调用）。"""
    if not text or not text.strip():
        return
    if not EDGE_TTS_AVAILABLE:
        return
    if not _PLAY_LOCK.acquire(blocking=False):
        logger.debug("语音正在播放中，跳过本次 speak")
        return
    _STOP_FLAG.clear()
    out_path = None

    async def _do():
        nonlocal out_path
        try:
            tmp = tempfile.NamedTemporaryFile(prefix="claw_voice_", suffix=".mp3", delete=False)
            out_path = tmp.name
            try:
                tmp.close()
            except Exception:
                pass
            communicate = edge_tts.Communicate(text=text.strip(), voice=voice)
            await communicate.save(out_path)
            duration_sec = _get_mp3_duration_seconds(out_path)
            if callable(on_duration_ready):
                try:
                    on_duration_ready(duration_sec)
                except Exception:
                    pass
            if _STOP_FLAG.is_set():
                return
            played = False
            if os.name == "nt" and not _STOP_FLAG.is_set():
                played = _play_mp3_win(out_path)
            if not played and PLAYSOUND_AVAILABLE and not _STOP_FLAG.is_set():
                play_path = out_path.replace("\\", "/") if os.name == "nt" else out_path
                playsound(play_path, block=True)
        except Exception as e:
            err_text = str(e).strip()
            if not err_text or "277" in err_text or "263" in err_text or "MCI" in err_text or "初始化" in err_text or "未打开" in err_text or "设备" in err_text:
                logger.info("未检测到声音或声音已关闭，跳过播放")
            else:
                logger.debug(f"语音播放跳过: {e}")
        finally:
            if out_path:
                try:
                    if os.path.exists(out_path):
                        os.remove(out_path)
                except OSError:
                    pass
            if callable(on_playback_finished):
                try:
                    on_playback_finished()
                except Exception:
                    pass
            try:
                _PLAY_LOCK.release()
            except Exception:
                pass

    try:
        asyncio.run(_do())
    except Exception as e:
        err_text = str(e).strip()
        if "277" in err_text or "263" in err_text or "MCI" in err_text or "初始化" in err_text or "未打开" in err_text or "设备" in err_text:
            logger.info("未检测到声音或声音已关闭，跳过播放")
        else:
            logger.debug(f"语音模块执行跳过: {e}")
        if callable(on_playback_finished):
            try:
                on_playback_finished()
            except Exception:
                pass
        try:
            _PLAY_LOCK.release()
        except Exception:
            pass


def speak(text: str, voice: str = DEFAULT_VOICE, on_duration_ready=None, on_playback_finished=None) -> None:
    """
    异步播放文字语音（不阻塞调用线程）。
    在后台线程中执行 edge-tts 合成；Windows 优先用 MCI 播放 mp3，否则用 playsound。
    on_duration_ready(duration_seconds): 合成完成、播放前回调。
    on_playback_finished(): 播放结束后回调，用于在播毕后再关闭气泡。
    """
    if not EDGE_TTS_AVAILABLE:
        return
    if not PLAYSOUND_AVAILABLE and os.name != "nt":
        return
    global _CURRENT_VOICE_THREAD
    t = threading.Thread(
        target=_run_async_speak,
        args=(text, voice),
        kwargs={"on_duration_ready": on_duration_ready, "on_playback_finished": on_playback_finished},
        daemon=True,
    )
    _CURRENT_VOICE_THREAD = t
    t.start()


def stop_speech():
    """停止当前语音播放：设置停止标志并关闭当前 MCI 别名。"""
    global _STOP_FLAG
    _STOP_FLAG.set()
    if os.name == "nt":
        try:
            with _MCI_ALIAS_LOCK:
                alias = _CURRENT_MCI_ALIAS
                if alias:
                    _CURRENT_MCI_ALIAS = None
            if alias:
                import ctypes
                winmm = ctypes.windll.winmm
                winmm.mciSendStringW("stop " + alias + " wait", None, 0, None)
                winmm.mciSendStringW("close " + alias + " wait", None, 0, None)
        except Exception:
            pass


def get_current_voice_process():
    """获取当前语音播放线程（用于停止）。"""
    return _CURRENT_VOICE_THREAD


def is_available() -> bool:
    """是否具备语音合成与播放条件（需 edge-tts，Windows 可用 MCI，其它需 playsound）。"""
    return bool(EDGE_TTS_AVAILABLE and (PLAYSOUND_AVAILABLE or os.name == "nt"))
