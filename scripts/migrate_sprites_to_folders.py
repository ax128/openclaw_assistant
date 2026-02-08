"""
将 sprites 下平铺的动作图片迁移到按动作分类的子文件夹。
用法: python scripts/migrate_sprites_to_folders.py [sprites目录]
默认: assistants/<助手名>/assets/sprites
若遇权限错误，请关闭占用该目录的程序后重试。
映射从同助手的 data.json 的 state_to_sprite_folder 读取，缺省用默认映射。
"""
import json
import os
import re
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core.assistant_data import DEFAULT_STATE_TO_SPRITE_FOLDER


def _prefix_to_folder(sprites_dir):
    """从 sprites_dir 推断助手目录下的 data.json，读取 state_to_sprite_folder，构建 前缀->文件夹 映射。"""
    # sprites_dir = .../<助手名>/assets/sprites -> assistant_dir = .../<助手名>
    assistant_dir = os.path.dirname(os.path.dirname(sprites_dir))
    data_path = os.path.join(assistant_dir, "data.json")
    mapping = DEFAULT_STATE_TO_SPRITE_FOLDER.copy()
    if os.path.isfile(data_path):
        try:
            with open(data_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data.get("state_to_sprite_folder"), dict):
                    mapping = data["state_to_sprite_folder"]
        except Exception:
            pass
    # 文件名前缀可能是状态名(walking)或文件夹名(walk)，都映射到文件夹名
    out = {}
    for state, folder in mapping.items():
        out[state] = folder
        out[folder] = folder
    return out


def migrate(sprites_dir):
    sprites_dir = os.path.abspath(sprites_dir)
    if not os.path.isdir(sprites_dir):
        print(f"目录不存在: {sprites_dir}")
        return 0
    prefix_to_folder = _prefix_to_folder(sprites_dir)
    moved = 0
    for name in os.listdir(sprites_dir):
        if not name.endswith(".png"):
            continue
        m = re.match(r"^(\w+)_(\d+)\.png$", name)
        if not m:
            continue
        prefix, num = m.group(1), m.group(2)
        folder_name = prefix_to_folder.get(prefix)
        if not folder_name:
            continue
        subdir = os.path.join(sprites_dir, folder_name)
        os.makedirs(subdir, exist_ok=True)
        src = os.path.join(sprites_dir, name)
        dst = os.path.join(subdir, f"{num}.png")
        if os.path.isfile(src) and src != dst:
            if os.path.exists(dst):
                os.remove(dst)
            try:
                os.rename(src, dst)
            except OSError:
                shutil.copy2(src, dst)
                os.remove(src)
            moved += 1
            print(f"  {name} -> {folder_name}/{num}.png")
    return moved


def main():
    default = os.path.join(ROOT, "assistants", "p_bot", "assets", "sprites")
    sprites_dir = sys.argv[1] if len(sys.argv) > 1 else default
    print(f"迁移目录: {sprites_dir}")
    n = migrate(sprites_dir)
    print(f"已迁移 {n} 个文件。")


if __name__ == "__main__":
    main()
