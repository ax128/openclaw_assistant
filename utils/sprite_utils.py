"""
精灵图工具 - 批量替换等。支持 sprites/ 下平铺或按动作子文件夹（idle/、walk/ 等）结构。
"""
import os
import shutil


# 默认源图：assistants 下某助手的 paused/1.png（子文件夹结构）或 paused_1.png（平铺）
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULT_PAUSED = os.path.join(_ROOT, "assistants", "p_bot", "assets", "sprites")
DEFAULT_SOURCE = os.path.join(_DEFAULT_PAUSED, "paused", "1.png")
if not os.path.isfile(DEFAULT_SOURCE):
    DEFAULT_SOURCE = os.path.join(_DEFAULT_PAUSED, "paused_1.png")


def replace_all_sprites_with(source_path=None, target_dir=None):
    """
    将目标目录下所有 png 替换为同一张源图的内容，文件名不变。
    若 target_dir 为 sprites 根目录，会递归处理各动作子文件夹。

    Args:
        source_path: 源图路径
        target_dir: 目标目录，默认为源图所在目录

    Returns:
        list[str]: 被覆盖的文件路径列表
    """
    source_path = source_path or DEFAULT_SOURCE
    target_dir = target_dir or os.path.dirname(source_path)
    if not os.path.isfile(source_path):
        return []
    source_name = os.path.basename(source_path)
    replaced = []
    for name in os.listdir(target_dir):
        path = os.path.join(target_dir, name)
        if os.path.isdir(path):
            for sub in os.listdir(path):
                if sub.lower().endswith(".png"):
                    dst = os.path.join(path, sub)
                    if dst != source_path:
                        shutil.copy2(source_path, dst)
                        replaced.append(dst)
            continue
        if not name.lower().endswith(".png"):
            continue
        if name == source_name:
            continue
        if os.path.isfile(path):
            shutil.copy2(source_path, path)
            replaced.append(path)
    return replaced
