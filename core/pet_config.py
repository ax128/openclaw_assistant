"""
已迁移至 assistant_config。本模块仅作兼容转发，请使用 core.assistant_config。
"""
from core.assistant_config import AssistantConfig

# 兼容旧调用：PetConfig(pet_data) 与 AssistantConfig(assistant_data) 接口一致
PetConfig = AssistantConfig

__all__ = ["PetConfig"]
