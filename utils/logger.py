"""
日志工具模块
提供统一的日志格式化和管理。

注意：本模块的 Logger 仅接受单参数字符串（与标准库 logging 多参数形式不同）。
请统一使用 f-string 传参，例如：logger.info(f"msg: {x}")，
不要使用 logger.info("msg %s", x) 或 logger.info("msg", x)。
"""
import logging
import sys
from datetime import datetime
from pathlib import Path

class Logger:
    """日志管理器"""
    
    _instance = None
    _logger = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Logger, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        if self._logger is None:
            self._setup_logger()
    
    def _setup_logger(self):
        """设置日志器"""
        self._logger = logging.getLogger("ClawAssistant")
        self._logger.setLevel(logging.DEBUG)
        
        # 避免重复添加处理器
        if self._logger.handlers:
            return
        
        # 创建格式器
        formatter = logging.Formatter(
            '[%(asctime)s] [%(levelname)-8s] [%(name)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        # 控制台处理器
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.DEBUG)
        console_handler.setFormatter(formatter)
        self._logger.addHandler(console_handler)
        
        # 文件处理器
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        log_file = log_dir / f"assistant_{datetime.now().strftime('%Y%m%d')}.log"
        
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        self._logger.addHandler(file_handler)

        # Gateway 专用日志：写入 claw_assistant/logs/gateway.YYYYMMDD.log（与主日志目录一致）
        gateway_log_dir = Path(__file__).resolve().parent.parent / "logs"
        gateway_log_dir.mkdir(parents=True, exist_ok=True)
        gateway_log_file = gateway_log_dir / ("gateway.%s.log" % datetime.now().strftime("%Y%m%d"))
        gateway_file_handler = logging.FileHandler(gateway_log_file, encoding='utf-8')
        gateway_file_handler.setLevel(logging.DEBUG)
        gateway_file_handler.setFormatter(formatter)
        _gateway_logger = logging.getLogger("ClawAssistant.Gateway")
        _gateway_logger.setLevel(logging.DEBUG)
        if not _gateway_logger.handlers:
            _gateway_logger.addHandler(gateway_file_handler)
            _gateway_logger.addHandler(console_handler)  # 控制台可见，不 propagate 到主 log 避免与 assistant_*.log 重复
        # 不向父 logger ClawAssistant 传播，避免 gateway 日志重复写入 assistant_*.log
        _gateway_logger.propagate = False

    def set_level(self, level_name: str):
        """根据 config/system_settings 的 log_level 设置主 logger 与各 handler 等级。level_name: DEBUG/INFO/WARNING/ERROR。"""
        level_map = {
            "DEBUG": logging.DEBUG,
            "INFO": logging.INFO,
            "WARNING": logging.WARNING,
            "ERROR": logging.ERROR,
        }
        level = level_map.get((level_name or "").strip().upper(), logging.INFO)
        self._logger.setLevel(level)
        for h in self._logger.handlers:
            h.setLevel(level)
        # Gateway 子 logger 同步
        gw = logging.getLogger("ClawAssistant.Gateway")
        gw.setLevel(level)
        for h in gw.handlers:
            h.setLevel(level)
    
    def debug(self, message):
        """调试日志。message 须为单参字符串，建议使用 f-string。"""
        self._logger.debug(message)

    def info(self, message):
        """信息日志。message 须为单参字符串，建议使用 f-string。"""
        self._logger.info(message)

    def warning(self, message):
        """警告日志。message 须为单参字符串，建议使用 f-string。"""
        self._logger.warning(message)

    def error(self, message):
        """错误日志。message 须为单参字符串，建议使用 f-string。"""
        self._logger.error(message)

    def critical(self, message):
        """严重错误日志。message 须为单参字符串，建议使用 f-string。"""
        self._logger.critical(message)

    def exception(self, message):
        """异常日志（带堆栈）。message 须为单参字符串，建议使用 f-string。"""
        self._logger.exception(message)

# 创建全局日志实例（首次使用时会在 _setup_logger 中为 ClawAssistant.Gateway 添加 logs/gateway.YYYYMMDD.log）
logger = Logger()
# Gateway 专用 logger，写入 logs/gateway.YYYYMMDD.log，propagate 到主 log
gateway_logger = logging.getLogger("ClawAssistant.Gateway")
