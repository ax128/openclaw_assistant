# 工具模块说明

## logger.py - 日志工具

统一的日志管理工具，提供格式化的日志输出。

### 功能特性

- **统一格式**: 所有日志使用统一的格式输出
- **多输出**: 同时输出到控制台和文件
- **日志级别**: 支持 DEBUG, INFO, WARNING, ERROR, CRITICAL
- **自动文件**: 按日期自动创建日志文件

### 使用方法

```python
from utils.logger import logger

# 不同级别的日志
logger.debug("调试信息")
logger.info("一般信息")
logger.warning("警告信息")
logger.error("错误信息")
logger.critical("严重错误")
logger.exception("异常信息（带堆栈）")
```

### 日志格式

```
[2026-01-25 20:00:00] [INFO    ] [ClawPet] 程序启动
```

### 日志文件位置

日志文件保存在 `logs/` 目录下，文件名格式：`assistant_YYYYMMDD.log`

### 日志级别说明

- **DEBUG**: 详细的调试信息
- **INFO**: 一般信息，程序运行状态
- **WARNING**: 警告信息，不影响运行
- **ERROR**: 错误信息，需要关注
- **CRITICAL**: 严重错误，可能导致程序崩溃
