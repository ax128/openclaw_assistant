"""
助手管理器
"""
import os
from utils.logger import logger
from .assistant_data import AssistantData
from .assistant_config import AssistantConfig


class AssistantManager:
    """助手管理器"""

    def __init__(self, assistants_dir="assistants"):
        self.assistants_dir = assistants_dir
        self.assistants = {}
        self.assistant_configs = {}
        self.current_assistant_name = None
        self.load_all_assistants()

    def load_all_assistants(self):
        """加载所有助手（会清空后重扫，删除的助手会从列表中移除）。"""
        logger.info(f"扫描助手目录: {self.assistants_dir}")
        self.assistants = {}
        self.assistant_configs = {}
        if not os.path.exists(self.assistants_dir):
            logger.warning(f"助手目录不存在: {self.assistants_dir}")
            return
        for item in os.listdir(self.assistants_dir):
            assistant_path = os.path.join(self.assistants_dir, item)
            if os.path.isdir(assistant_path):
                data_file = os.path.join(assistant_path, "data.json")
                if os.path.exists(data_file):
                    logger.info(f"发现助手: {item}")
                    self.assistants[item] = AssistantData(item, self.assistants_dir)
                    self.assistant_configs[item] = AssistantConfig(self.assistants[item])
                else:
                    logger.debug(f"跳过目录（不是有效助手）: {item}")
        if self.current_assistant_name and self.current_assistant_name not in self.assistants:
            self.current_assistant_name = None
        if self.assistants and not self.current_assistant_name:
            self.current_assistant_name = list(self.assistants.keys())[0]
            logger.info(f"设置默认助手: {self.current_assistant_name}")

    def get_current_assistant(self):
        """获取当前助手数据"""
        if self.current_assistant_name and self.current_assistant_name in self.assistants:
            return self.assistants[self.current_assistant_name]
        return None

    def get_current_assistant_config(self):
        """获取当前助手配置"""
        if self.current_assistant_name and self.current_assistant_name in self.assistant_configs:
            return self.assistant_configs[self.current_assistant_name]
        return None

    def switch_assistant(self, assistant_name):
        """切换助手"""
        if assistant_name in self.assistants:
            old_name = self.current_assistant_name
            self.current_assistant_name = assistant_name
            logger.info(f"切换助手: {old_name} -> {assistant_name}")
            return True
        else:
            logger.warning(f"切换助手失败，助手不存在: {assistant_name}")
            return False

    def list_assistants(self):
        """列出所有助手"""
        return list(self.assistants.keys())
