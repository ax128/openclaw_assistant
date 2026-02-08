"""
移动逻辑模块
"""
import random
import time
from utils.logger import logger

class MovementController:
    """移动控制器"""
    
    def __init__(self, assistant_data, assistant_config):
        self.assistant_data = assistant_data
        self.assistant_config = assistant_config
        self.enabled = False
        self.target_x = 0
        self.target_y = 0
        self.last_move_time = 0
        self.move_interval = assistant_config.get_move_interval()  # 从 data.config.move_interval 读取（秒）
    
    def start(self):
        """开始游走"""
        self.enabled = self.assistant_config.get_wander_enabled()
        if self.enabled:
            logger.info(f"启动助手游走: {(getattr(self.assistant_data, "assistant_name", None) or getattr(self.assistant_data, "pet_name", ""))}")
            self._set_new_target()
        else:
            logger.info(f"助手游走已禁用: {(getattr(self.assistant_data, "assistant_name", None) or getattr(self.assistant_data, "pet_name", ""))}")
    
    def set_speed(self, speed):
        """设置移动速度（0=禁止，1=慢，2=中，3=快）"""
        self.assistant_config.set_wander_speed(speed)
        if speed == 0:
            self.stop()
            logger.info(f"移动已禁止")
        else:
            if not self.enabled:
                self.start()
            logger.info(f"移动速度已更新")
    
    def stop(self):
        """停止游走"""
        if self.enabled:
            logger.debug(f"停止助手游走: {(getattr(self.assistant_data, "assistant_name", None) or getattr(self.assistant_data, "pet_name", ""))}")
        self.enabled = False
    
    def _set_new_target(self):
        """设置新的目标位置"""
        boundary = self.assistant_config.get_wander_boundary()
        speed = self.assistant_config.get_wander_speed()
        
        # 获取当前位置
        pos = self.assistant_data.get_position()
        current_x = pos.get("x", boundary["x"])
        current_y = pos.get("y", boundary["y"])
        
        # 随机生成目标位置（在边界内）
        max_delta = speed * 50  # 每次移动的最大距离
        self.target_x = current_x + random.randint(-max_delta, max_delta)
        self.target_y = current_y + random.randint(-max_delta, max_delta)
        
        # 限制在边界内
        self.target_x = max(boundary["x"], min(self.target_x, boundary["x"] + boundary["width"] - 100))
        self.target_y = max(boundary["y"], min(self.target_y, boundary["y"] + boundary["height"] - 100))
    
    def update(self):
        """更新移动"""
        if not self.enabled:
            return
        
        current_time = time.time()
        if current_time - self.last_move_time < self.move_interval:
            return
        
        self.last_move_time = current_time
        
        # 获取当前位置
        pos = self.assistant_data.get_position()
        current_x = pos.get("x", 100)
        current_y = pos.get("y", 100)
        
        # 移动到目标位置
        speed = self.assistant_config.get_wander_speed()
        dx = self.target_x - current_x
        dy = self.target_y - current_y
        distance = (dx**2 + dy**2)**0.5
        
        if distance < speed:
            # 到达目标，设置新目标
            self.assistant_data.set_position(int(self.target_x), int(self.target_y))
            logger.debug(f"到达目标位置，设置新目标: ({self.target_x}, {self.target_y})")
            self._set_new_target()
        else:
            # 向目标移动（只更新位置，状态由 AssistantWindow 状态机统一决定）
            move_x = current_x + (dx / distance) * speed
            move_y = current_y + (dy / distance) * speed
            self.assistant_data.set_position(int(move_x), int(move_y))
