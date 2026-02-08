"""
已迁移至 assistant_manager。本模块仅作兼容转发，请使用 core.assistant_manager。
"""
from core.assistant_manager import AssistantManager as _AssistantManager

class PetManager(_AssistantManager):
    """兼容旧调用：pets_dir / current_pet_name / get_current_pet / switch_pet / list_pets"""
    def __init__(self, pets_dir="pets"):
        super().__init__(assistants_dir=pets_dir)

    @property
    def pets_dir(self):
        return self.assistants_dir

    def get_current_pet(self):
        return self.get_current_assistant()

    def get_current_pet_config(self):
        return self.get_current_assistant_config()

    def switch_pet(self, pet_name):
        return self.switch_assistant(pet_name)

    def list_pets(self):
        return self.list_assistants()

    def load_all_pets(self):
        return self.load_all_assistants()

    @property
    def pets(self):
        return self.assistants

    @property
    def pet_configs(self):
        return self.assistant_configs

    @property
    def current_pet_name(self):
        return self.current_assistant_name

    @current_pet_name.setter
    def current_pet_name(self, value):
        self.current_assistant_name = value

__all__ = ["PetManager"]
