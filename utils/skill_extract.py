"""
从当前助手的已启用技能中随机抽取一条，返回其 prompt 文本。
供自动交互定时任务使用：取 prompt 后发往 Gateway agent，回复以气泡展示。
"""
import random
from typing import Optional, Any


def extract_random_skill(assistant_data: Optional[Any] = None) -> Optional[str]:
    """
    从助手的已启用技能中随机选一条，返回其 prompt；无助手或无启用技能则返回 None。

    assistant_data: 助手数据对象，需有 get_skills() 且每项有 enabled、prompt 字段。
    """
    if assistant_data is None:
        return None
    skills = getattr(assistant_data, "get_skills", None)
    if not callable(skills):
        return None
    raw = skills()
    if not isinstance(raw, dict):
        return None
    enabled = {k: v for k, v in raw.items() if isinstance(v, dict) and v.get("enabled", False)}
    if not enabled:
        return None
    skill = random.choice(list(enabled.values()))
    prompt = (skill.get("prompt") or "").strip()
    return prompt if prompt else None
