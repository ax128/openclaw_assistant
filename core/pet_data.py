"""
已迁移至 assistant_data。本模块仅作兼容转发，请使用 core.assistant_data。
"""
from core.assistant_data import (
    DEFAULT_CONFIG,
    DEFAULT_STATE_TO_SPRITE_FOLDER,
    AssistantData,
    _ensure_defaults,
)

# 兼容旧调用：PetData(pet_name, pets_dir) -> AssistantData(assistant_name, assistants_dir)
class PetData(AssistantData):
    def __init__(self, pet_name, pets_dir="pets"):
        super().__init__(assistant_name=pet_name, assistants_dir=pets_dir)

    @property
    def pet_name(self):
        return self.assistant_name

__all__ = ["DEFAULT_CONFIG", "DEFAULT_STATE_TO_SPRITE_FOLDER", "PetData", "_ensure_defaults"]
