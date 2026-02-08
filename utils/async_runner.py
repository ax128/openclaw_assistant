"""
简单线程执行器：把阻塞任务放到后台线程，回调在主线程触发（如可用）。
注意：从工作线程调用 QTimer.singleShot 会绑定到工作线程，因无事件循环回调永不执行，
故使用主线程 QObject 的信号槽（QueuedConnection）将回调投递到主线程执行。
"""
import threading
from utils.logger import logger

# 主线程中的 QObject，用于接收工作线程发来的回调并在主线程执行
_main_thread_receiver = None


def _get_main_thread_receiver():
    """在调用 run_in_thread 的线程（通常为主线程）中创建并返回 receiver，确保其属于主线程。"""
    global _main_thread_receiver
    if _main_thread_receiver is None:
        try:
            from PyQt5.QtCore import QObject, pyqtSignal

            class _CallbackReceiver(QObject):
                run = pyqtSignal(object)  # 参数为可调用对象

                def __init__(self):
                    super().__init__()
                    from PyQt5.QtCore import Qt
                    self.run.connect(self._run, Qt.QueuedConnection)

                def _run(self, fn):
                    if callable(fn):
                        fn()
            _main_thread_receiver = _CallbackReceiver()
        except Exception:
            pass
    return _main_thread_receiver


def _invoke_on_main_thread(fn):
    """将 fn 投递到主线程执行。若在工作线程中调用，必须通过主线程 QObject 的信号，否则回调不会执行。"""
    try:
        rec = _get_main_thread_receiver()
        if rec is not None:
            rec.run.emit(fn)
        else:
            fn()
    except Exception:
        fn()


def run_in_thread(func, on_done=None, on_error=None):
    """
    在后台线程执行 func，并在主线程触发回调。
    - on_done(result)
    - on_error(exc)
    """
    # 在启动线程前于当前线程（通常为主线程）创建 receiver，保证其属于主线程
    _get_main_thread_receiver()

    def _worker():
        try:
            result = func()
        except Exception as exc:
            if on_error:
                _invoke_on_main_thread(lambda: on_error(exc))
            else:
                logger.exception(f"后台任务失败: {exc}")
            return
        if on_done:
            _invoke_on_main_thread(lambda: on_done(result))

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    return t
