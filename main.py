"""
Claw Assistant（claw_assistant）主程序 - Qt 桌面助手
"""
import sys
import os
import json
import shutil

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from utils.logger import logger
from config.settings import Settings
from core.assistant_manager import AssistantManager


def _migrate_legacy_to_assistants_once(assistants_dir):
    """一次性迁移：若 assistants 为空且旧目录（pets）下有助手数据，则复制到 assistants 并写入 current.json。"""
    legacy_dir = os.path.normpath(os.path.join(ROOT, "pets"))
    if not os.path.isdir(legacy_dir):
        return False
    to_copy = []
    for name in os.listdir(legacy_dir):
        if name.startswith(".") or name in ("next_bot_seq.json", "README.md", "skills", "__pycache__"):
            continue
        path = os.path.join(legacy_dir, name)
        if os.path.isdir(path) and os.path.isfile(os.path.join(path, "data.json")):
            to_copy.append(name)
    if not to_copy:
        return False
    os.makedirs(assistants_dir, exist_ok=True)
    for name in to_copy:
        src = os.path.join(legacy_dir, name)
        dst = os.path.join(assistants_dir, name)
        if os.path.exists(dst):
            continue
        try:
            shutil.copytree(src, dst)
            logger.info(f"已迁移助手: {name}")
        except Exception as e:
            logger.warning(f"迁移助手 {name} 失败: {e}")
    legacy_current_path = os.path.join(legacy_dir, "current.json")
    if os.path.isfile(legacy_current_path):
        try:
            with open(legacy_current_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            bootstrap = {
                "current_assistant": data.get("current_assistant", "bot00001"),
                "assistants_dir": "assistants",
            }
            current_file = os.path.join(assistants_dir, "current.json")
            with open(current_file, "w", encoding="utf-8") as f:
                json.dump(bootstrap, f, indent=2, ensure_ascii=False)
            logger.info("已写入 assistants/current.json")
        except Exception as e:
            logger.debug(f"写入 current.json 失败: {e}")
    return True


def main():
    """主函数 - 使用 PyQt5 作为唯一 UI"""
    from utils.platform_adapter import platform_name
    logger.info(f"{'=' * 50}")
    logger.info(f"Claw Assistant 程序启动（Qt）")
    logger.info(f"当前平台: {platform_name()}")
    logger.info(f"{'=' * 50}")

    settings = None
    assistant_manager = None

    try:
        settings = Settings()
        logger.set_level(settings.get("log_level", "INFO"))
        logger.info(f"加载全局配置...")
        logger.info(f"配置加载完成: {settings.config}")

        assistants_dir_rel = settings.get("assistants_dir", "assistants")
        assistants_dir = os.path.normpath(os.path.join(ROOT, assistants_dir_rel))
        os.makedirs(assistants_dir, exist_ok=True)
        assistant_manager = AssistantManager(assistants_dir)
        # 若 assistants 为空且存在旧目录数据，执行一次性迁移到 assistants
        if not assistant_manager.list_assistants():
            if _migrate_legacy_to_assistants_once(assistants_dir):
                settings.load()
                assistant_manager = AssistantManager(assistants_dir)
        logger.info(f"发现 {len(assistant_manager.list_assistants())} 个助手: {assistant_manager.list_assistants()}")

        assistant_id = settings.resolve_bot_id_to_assistant_id()
        if not assistant_manager.switch_assistant(assistant_id):
            assistants = assistant_manager.list_assistants()
            if assistants:
                logger.warning(f"助手 {assistant_id} 不存在，使用: {assistants[0]}")
                assistant_manager.switch_assistant(assistants[0])
            else:
                logger.error(f"没有找到任何助手！请先在「设置」中添加助手。")
                return
        # 默认助手 data 已加载；聊天与技能走 OpenClaw Gateway，系统提示词与约束由服务端管理
        logger.info(f"当前助手: {assistant_manager.current_assistant_name}")

        from PyQt5.QtWidgets import QApplication
        from PyQt5.QtCore import Qt, QTimer, qInstallMessageHandler, QObject, pyqtSignal
        from ui.assistant_window import AssistantWindow
        from ui.startup_dialog import StartupDialog
        from ui.ui_settings_loader import get_ui_setting, set_ui_setting_and_save
        from utils.platform_adapter import get_device_name
        from core.openclaw_gateway.client import GatewayClient

        # 主线程桥：WS 线程通过信号把回调投递到主线程执行（QTimer.singleShot 在非主线程调用不会触发）
        class _MainThreadBridge(QObject):
            run = pyqtSignal(object)

            def __init__(self, parent=None):
                super().__init__(parent)
                self.run.connect(self._run)

            def _run(self, fn):
                if callable(fn):
                    fn()

        gateway_client = GatewayClient()
        app = QApplication(sys.argv)
        # 启动时检测设备：若与上次不同则设 reposition_windows，助手/聊天窗口将重新定位到主屏内
        current_device = get_device_name()
        last_device = (get_ui_setting("last_device") or "").strip()
        if current_device != last_device:
            set_ui_setting_and_save("last_device", current_device)
            set_ui_setting_and_save("reposition_windows", True)
            logger.info(f"设备变更: {last_device or '(无)'} -> {current_device}，将重新定位助手与聊天窗口")
        main_bridge = _MainThreadBridge()
        gateway_client.set_main_thread_runner(main_bridge.run.emit)

        def _qt_message_handler(msg_type, context, message):
            # 仅 Windows：屏蔽多显示器下 QWindowsWindow::setGeometry 的刷屏警告；macOS 为 QCocoaWindow
            if sys.platform == "win32" and "setGeometry" in message and "QWindowsWindow" in message:
                return
            sys.stderr.write(message + "\n")

        qInstallMessageHandler(_qt_message_handler)
        app.setQuitOnLastWindowClosed(False)

        def _on_quit():
            """退出时保存配置与助手数据，不依赖 finally + SystemExit。"""
            try:
                if assistant_manager and assistant_manager.current_assistant_name:
                    if settings:
                        assistant = assistant_manager.get_current_assistant()
                        bot_id = assistant.get("bot_id", "bot00001") if assistant else "bot00001"
                        settings.set("current_assistant", bot_id)
                        settings.save()
                        logger.info(f"配置保存完成")
                    assistant = assistant_manager.get_current_assistant()
                    if assistant:
                        assistant.set("state", "happy")
                        assistant.save()
                        logger.info(f"助手数据保存完成")
            except Exception as e:
                logger.exception(f"退出保存时出错: {e}")
        app.aboutToQuit.connect(_on_quit)

        cfg = assistant_manager.get_current_assistant_config()
        update_interval = cfg.get_update_interval_ms() if cfg else None
        if update_interval is None:
            update_interval = settings.get("update_interval", 50)
        window = AssistantWindow(assistant_manager, update_interval, settings=settings, gateway_client=gateway_client)
        # Gateway 连接/断开时助手气泡提示（重要度 1 更醒目）
        from utils.i18n import t
        gateway_client.register_on_connected(
            lambda: window.show_bubble_requested.emit(t("gateway_connected_ok"), 2)
        )
        gateway_client.register_on_disconnected(
            lambda: window.show_bubble_requested.emit(t("gateway_disconnected"), 1)
        )
        gateway_client.register_on_shutdown(
            lambda pl: window.show_bubble_requested.emit(
                t("gateway_restart_fmt") % (int(pl.get("restartExpectedMs") or 0) // 1000), 1
            )
        )
        logger.info(f"启动 Qt 主循环...")
        window.show()
        # 数秒后清除 reposition_windows，以便后续打开的聊天窗口不再强制主屏（已由助手/先打开的聊天应用过）
        QTimer.singleShot(3000, lambda: set_ui_setting_and_save("reposition_windows", False))
        # 登录窗口与助手窗口同时出现，互不干扰；登录窗非模态，可随时关闭，后续可在 设置 -> Gateway 设置 中重连
        startup = StartupDialog(settings, gateway_client)
        startup.setWindowModality(Qt.NonModal)
        startup.show()
        logger.info(f"助手窗口与连接窗口已同时显示，互不干扰")
        sys.exit(app.exec_())

    except KeyboardInterrupt:
        logger.info(f"用户中断程序")
    except Exception as e:
        logger.exception(f"程序运行出错: {e}")
    finally:
        logger.info(f"程序退出，保存数据...")
        try:
            if assistant_manager and assistant_manager.current_assistant_name:
                if settings:
                    assistant = assistant_manager.get_current_assistant()
                    bot_id = assistant.get("bot_id", "bot00001") if assistant else "bot00001"
                    settings.set("current_assistant", bot_id)
                    settings.save()
                    logger.info(f"配置保存完成")
                assistant = assistant_manager.get_current_assistant()
                if assistant:
                    assistant.set("state", "happy")
                    assistant.save()
                    logger.info(f"助手数据保存完成")
        except Exception as e:
            logger.exception(f"保存时出错: {e}")
        logger.info(f"程序退出")


if __name__ == "__main__":
    main()
