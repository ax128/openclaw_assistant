"""
助手外观管理
"""
import json
import os
import re
import time
import tkinter as tk
from utils.logger import logger
from core.pet_data import DEFAULT_STATE_TO_SPRITE_FOLDER

try:
    from PIL import Image, ImageTk, ImageDraw, ImageFont, ImageFilter
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    logger.warning(f"PIL/Pillow未安装，将使用文本显示")

class PetAppearance:
    """助手外观管理类"""
    
    def __init__(self, pet_name, pets_dir="pets", size=(150, 150)):
        self.pet_name = pet_name
        self.pets_dir = pets_dir
        self.size = size
        self.assets_path = os.path.join(pets_dir, pet_name, "assets")
        self.sprites_path = os.path.join(self.assets_path, "sprites")
        data_path = os.path.join(pets_dir, pet_name, "data.json")
        self._state_to_sprite_folder = DEFAULT_STATE_TO_SPRITE_FOLDER.copy()
        if os.path.isfile(data_path):
            try:
                with open(data_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data.get("state_to_sprite_folder"), dict):
                        self._state_to_sprite_folder.update(data["state_to_sprite_folder"])
            except Exception as e:
                logger.debug(f"读取 state_to_sprite_folder 失败 {data_path}: {e}")
        self.images = {}  # 存储PhotoImage对象 {state: [frame1, frame2, ...]}
        self.pil_images = {}  # 存储PIL Image对象 {state: [frame1, frame2, ...]}
        self.original_pil_images = {}  # 存储原始尺寸的PIL Image对象（用于重新缩放）
        self.current_image = None
        self.current_state = "happy"  # 默认状态为happy
        # 动画相关
        self.animation_frames = {}  # {state: frame_count}
        self.current_frame = {}  # {state: current_frame_index}
        self.last_frame_time = {}  # {state: last_update_time}
        self.frame_delays = {  # 每帧延迟（秒）
            "idle": 1,
            "walking": 0.5,
            "dragging": 0.3,
            "paused": 1.0,
            "happy": 0.5,
            "sad": 0.5,
            "thinking": 0.5
        }
        self.load_images()
    
    def _resize_for_display(self, img):
        """高质量缩放：多步下采样减少模糊，明显缩小时轻微锐化"""
        if img.size == self.size:
            return img.copy()
        # 缩放比例大时增大 reducing_gap，多步下采样更清晰（PIL 会分步缩小）
        ratio = max(img.size) / max(self.size)
        reducing_gap = min(8, max(2.0, ratio / 2))
        resized = img.resize(self.size, Image.Resampling.LANCZOS, reducing_gap=reducing_gap)
        # 明显缩小后做轻微锐化，提升观感
        if ratio > 2:
            try:
                resized = resized.filter(ImageFilter.UnsharpMask(radius=1, percent=120, threshold=3))
            except Exception:
                pass
        return resized
    
    def load_images(self):
        """加载所有图片"""
        if not PIL_AVAILABLE:
            logger.warning(f"PIL不可用，无法加载图片")
            self._create_placeholder()
            return
        
        logger.info(f"加载助手外观资源: {self.pet_name}")
        
        # 优先从sprites目录加载
        if os.path.exists(self.sprites_path):
            image_dir = self.sprites_path
        elif os.path.exists(self.assets_path):
            image_dir = self.assets_path
        else:
            logger.warning(f"助手资源目录不存在: {self.assets_path}")
            self._create_placeholder()
            return
        
        # 定义所有支持的状态
        states = ["idle", "walking", "dragging", "paused", "happy", "sad", "thinking"]
        
        # 加载每个状态的图片（支持多帧动画）
        for state in states:
            frames, original_frames = self._load_animation_frames(image_dir, state)
            if frames:
                self.pil_images[state] = frames
                # 保存原始尺寸的图片（用于重新缩放）
                if original_frames:
                    self.original_pil_images[state] = original_frames
                self.animation_frames[state] = len(frames)
                self.current_frame[state] = 0
                self.last_frame_time[state] = time.time()
                logger.debug(f"加载状态 {state}: {len(frames)} 帧")
            else:
                # 如果没有找到动画帧，尝试加载单帧图片
                fallback_files = {
                    "idle": ["idle.png", "default.png"],
                    "walking": ["walk_1.png", "walk.png", "idle.png"],
                    "dragging": ["drag_1.png", "drag.png", "idle.png"],
                    "paused": ["paused_1.png", "paused.png", "idle.png"],
                    "happy": ["happy.png", "idle.png"],
                    "sad": ["sad.png", "idle.png"],
                    "thinking": ["thinking.png", "idle.png"]
                }
                for filename in fallback_files.get(state, []):
                    filepath = os.path.join(image_dir, filename)
                    if os.path.exists(filepath):
                        try:
                            # 使用高质量加载方式：保持原始格式
                            img = Image.open(filepath)
                            
                            # 对于PNG，智能处理透明度（优化macOS兼容性）
                            if img.mode == 'P':
                                # 调色板模式，检查是否有透明信息
                                if 'transparency' in img.info:
                                    # 有透明信息，转换为RGBA
                                    img = img.convert('RGBA')
                                else:
                                    # 无透明信息，先转RGB再转RGBA（避免白色背景）
                                    # 对于macOS，确保透明区域被正确处理
                                    img = img.convert('RGBA')
                            elif img.mode == 'RGB':
                                # RGB模式，转换为RGBA（macOS需要alpha通道）
                                # 对于macOS，如果图片是白色背景，可能需要特殊处理
                                img = img.convert('RGBA')
                            elif img.mode != 'RGBA':
                                # 其他模式，先转RGB再转RGBA
                                img = img.convert('RGB').convert('RGBA')
                            # 如果已经是RGBA，直接使用，不进行转换
                            
                            # macOS特殊处理：如果图片有白色背景，尝试检测并处理
                            # 使用PIL内置方法处理，不依赖numpy
                            if img.mode == 'RGBA':
                                try:
                                    # 使用PIL的ImageOps和ImageChops来处理白色背景
                                    from PIL import ImageOps, ImageChops
                                    
                                    # 创建白色背景图片
                                    white_bg = Image.new('RGBA', img.size, (255, 255, 255, 255))
                                    # 计算差异（找出白色区域）
                                    diff = ImageChops.difference(img, white_bg)
                                    
                                    # 如果差异很小（说明是白色背景），尝试处理
                                    # 这里使用一个简单的阈值：如果图片主要是白色，则可能是白色背景
                                    # 注意：这个方法可能不够精确，但可以处理大部分情况
                                    
                                    # 对于macOS，如果原图是RGB模式且没有透明通道，
                                    # 我们已经在上面转换为RGBA了，这里主要是确保透明度正确
                                    # 如果图片本身就有透明通道，就不需要特殊处理
                                    
                                except Exception as e:
                                    # 处理失败，使用原图（已经有RGBA通道）
                                    logger.debug(f"处理PNG透明度时出错（可忽略）: {e}")
                                    pass
                            
                            # 保存原始图片（用于后续重新缩放）
                            self.original_pil_images[state] = [img.copy()]
                            
                            # 使用高质量缩放（如果尺寸不同才缩放）
                            resized_img = self._resize_for_display(img)
                            
                            self.pil_images[state] = [resized_img]  # 单帧也作为列表
                            self.animation_frames[state] = 1
                            self.current_frame[state] = 0
                            self.last_frame_time[state] = time.time()
                            logger.debug(f"加载单帧图片: {state} -> {filepath}")
                            break
                        except Exception as e:
                            logger.warning(f"加载图片失败 {filepath}: {e}")
    
    def _load_animation_frames(self, image_dir, state):
        """加载动画帧序列。状态名映射到 sprites 子文件夹（来自 data.state_to_sprite_folder）。"""
        frames = []
        original_frames = []
        folder = self._state_to_sprite_folder.get(state, state)
        action_dir = os.path.join(image_dir, folder)
        filepaths = []
        if os.path.isdir(action_dir):
            # 新结构：sprites/walking/1.png, 2.png, ...
            names = [f for f in os.listdir(action_dir) if f.endswith(".png")]
            def order(n):
                m = re.search(r"(\d+)\.png$", n)
                return (int(m.group(1)), n) if m else (0, n)
            names.sort(key=order)
            filepaths = [os.path.join(action_dir, n) for n in names]
        if not filepaths:
            # 旧结构：sprites/walk_1.png, walk_2.png, ...
            frame_index = 1
            while True:
                filename = f"{folder}_{frame_index}.png"
                filepath = os.path.join(image_dir, filename)
                if os.path.exists(filepath):
                    filepaths.append(filepath)
                    frame_index += 1
                else:
                    break
        for filepath in filepaths:
            try:
                img = Image.open(filepath)
                if img.mode == 'P':
                    img = img.convert('RGBA')
                elif img.mode == 'RGB':
                    img = img.convert('RGBA')
                elif img.mode != 'RGBA':
                    img = img.convert('RGB').convert('RGBA')
                original_img = img.copy()
                original_frames.append(original_img)
                resized_img = self._resize_for_display(original_img)
                frames.append(resized_img)
            except Exception as e:
                logger.warning(f"加载动画帧失败 {filepath}: {e}")
        return frames, original_frames
        
        # 如果没有加载到任何图片，创建占位符
        if not self.pil_images:
            logger.warning(f"未找到任何图片资源，使用占位符")
            self._create_placeholder()
    
    def _create_placeholder(self):
        """创建占位符图片"""
        if not PIL_AVAILABLE:
            logger.warning(f"PIL不可用，无法创建占位符图片")
            return
        
        try:
            # 创建一个简单的占位符图片
            img = Image.new('RGBA', self.size, (200, 200, 200, 255))
            draw = ImageDraw.Draw(img)
            
            # 绘制文字
            try:
                font = ImageFont.truetype("arial.ttf", 20)
            except (OSError, IOError):
                try:
                    font = ImageFont.load_default()
                except (OSError, IOError):
                    font = None
            
            text = self.pet_name[:4]  # 只显示前4个字符
            if font:
                bbox = draw.textbbox((0, 0), text, font=font)
                text_width = bbox[2] - bbox[0]
                text_height = bbox[3] - bbox[1]
                position = ((self.size[0] - text_width) // 2, (self.size[1] - text_height) // 2)
                draw.text(position, text, fill=(0, 0, 0, 255), font=font)
            
            # 保存PIL Image对象，窗口创建后再转换为PhotoImage
            self.pil_images["idle"] = img
            logger.info(f"创建占位符图片: {self.pet_name}")
        except Exception as e:
            logger.error(f"创建占位符失败: {e}")
            # 最后的备选方案：纯色图片
            try:
                img = Image.new('RGB', self.size, (150, 150, 150))
                self.pil_images["idle"] = img
            except Exception as e:
                logger.error(f"无法创建任何图片: {e}")
    
    def convert_to_photoimage(self):
        """将PIL Image转换为PhotoImage（需要在窗口创建后调用）"""
        if not PIL_AVAILABLE:
            return
        
        for state, pil_frames in self.pil_images.items():
            try:
                # 转换所有帧
                photo_frames = []
                for pil_img in pil_frames:
                    # 确保图片是RGBA模式（加载时已处理，这里只是保险）
                    if pil_img.mode != 'RGBA':
                        if pil_img.mode == 'RGB':
                            pil_img = pil_img.convert('RGBA')
                        else:
                            pil_img = pil_img.convert('RGB').convert('RGBA')
                    
                    # 直接转换为PhotoImage，PIL会自动处理透明度
                    # 对于PNG，ImageTk.PhotoImage会自动处理alpha通道
                    photo_img = ImageTk.PhotoImage(pil_img)
                    photo_frames.append(photo_img)
                self.images[state] = photo_frames
                logger.debug(f"转换动画为PhotoImage: {state} ({len(photo_frames)} 帧)")
            except Exception as e:
                logger.warning(f"转换图片失败 {state}: {e}")
        
        # 设置默认图片（优先使用happy状态）
        if self.images:
            if "happy" in self.images and self.images["happy"]:
                self.current_image = self.images["happy"][0]
            elif "idle" in self.images and self.images["idle"]:
                self.current_image = self.images["idle"][0]
            else:
                # 获取第一个可用状态的第一个帧
                for frames in self.images.values():
                    if frames:
                        self.current_image = frames[0]
                        break
    
    def get_image(self, state=None):
        """获取指定状态的当前帧图片（PhotoImage对象）"""
        if state is None:
            state = self.current_state
        
        # 优先返回指定状态的当前帧
        if state in self.images and self.images[state]:
            frames = self.images[state]
            frame_index = self.current_frame.get(state, 0)
            if frame_index < len(frames):
                return frames[frame_index]
            elif frames:
                return frames[0]  # 如果索引超出，返回第一帧
        
        # 如果没有，优先返回happy图片，其次idle图片
        if "happy" in self.images and self.images["happy"]:
            return self.images["happy"][0]
        if "idle" in self.images and self.images["idle"]:
            return self.images["idle"][0]
        
        # 如果都没有，返回第一个可用的图片
        for frames in self.images.values():
            if frames:
                return frames[0]
        
        return None
    
    def get_pil_image(self, state=None):
        """获取指定状态的PIL Image对象（用于获取尺寸等）"""
        if state is None:
            state = self.current_state
        
        if state in self.pil_images and self.pil_images[state]:
            # 返回当前帧的PIL Image
            frame_index = self.current_frame.get(state, 0)
            frames = self.pil_images[state]
            if frame_index < len(frames):
                return frames[frame_index]
            elif frames:
                return frames[0]
        
        if "happy" in self.pil_images and self.pil_images["happy"]:
            return self.pil_images["happy"][0]
        if "idle" in self.pil_images and self.pil_images["idle"]:
            return self.pil_images["idle"][0]
        
        if self.pil_images:
            for frames in self.pil_images.values():
                if frames:
                    return frames[0]
        
        return None
    
    def set_state(self, state):
        """设置助手状态"""
        # 即使状态相同，也更新图片（确保动画继续播放）
        if state != self.current_state:
            self.current_state = state
            # 重置当前帧索引（切换状态时重置）
            if state not in self.current_frame:
                self.current_frame[state] = 0
            if state not in self.last_frame_time:
                self.last_frame_time[state] = time.time()
            logger.debug(f"切换状态: {state}")
        
        # 总是更新当前图片（确保状态切换时立即显示）
        image = self.get_image(state)
        if image:
            self.current_image = image
    
    def update_animation(self):
        """更新动画帧（需要在主循环中定期调用）"""
        # 如果PhotoImage未转换，但窗口已创建，尝试转换
        if not self.images and self.pil_images:
            # 可能是在set_size后，需要重新转换
            try:
                self.convert_to_photoimage()
            except Exception as e:
                logger.warning(f"update_animation: 转换PhotoImage失败: {e}")
                return
        
        if not self.images:
            return
        
        state = self.current_state
        if state not in self.images or not self.images[state]:
            return
        
        frames = self.images[state]
        frame_count = len(frames)
        
        # 如果只有1帧，不需要更新
        if frame_count <= 1:
            return
        
        # 检查是否需要切换到下一帧
        current_time = time.time()
        last_time = self.last_frame_time.get(state, current_time)
        frame_delay = self.frame_delays.get(state, 0.3)
        
        if current_time - last_time >= frame_delay:
            # 切换到下一帧
            current_frame_index = self.current_frame.get(state, 0)
            next_frame_index = (current_frame_index + 1) % frame_count
            self.current_frame[state] = next_frame_index
            self.last_frame_time[state] = current_time
            
            # 更新当前图片
            if next_frame_index < len(frames):
                self.current_image = frames[next_frame_index]
    
    def get_current_image(self):
        """获取当前图片"""
        return self.current_image or self.get_image()
    
    def set_size(self, size):
        """设置助手大小（1=小100x100，2=中150x150，3=大200x200）"""
        size_map = {1: (100, 100), 2: (150, 150), 3: (200, 200)}
        new_size = size_map.get(size, (150, 150))
        
        if new_size != self.size:
            self.size = new_size
            logger.info(f"重新缩放图片，新大小: {new_size}")
            
            # 检查窗口是否已创建（通过检查是否曾经转换过PhotoImage）
            window_created = len(self.images) > 0
            
            # 从原始图片重新缩放（避免重新加载文件，提高性能）
            self.pil_images = {}
            self.images = {}  # 清空PhotoImage缓存，需要重新转换
            self.current_image = None  # 清空当前图片引用
            
            # 从原始图片重新缩放
            for state, original_frames in self.original_pil_images.items():
                if isinstance(original_frames, list):
                    resized_frames = []
                    for original_img in original_frames:
                        # 确保是RGBA模式（原始图片应该已经是RGBA，这里只是保险）
                        if original_img.mode != 'RGBA':
                            if original_img.mode == 'RGB':
                                original_img = original_img.convert('RGBA')
                            else:
                                original_img = original_img.convert('RGB').convert('RGBA')
                        
                        # 从原始尺寸重新缩放（保证质量）
                        resized = self._resize_for_display(original_img)
                        resized_frames.append(resized)
                    self.pil_images[state] = resized_frames
                else:
                    # 单帧（向后兼容）
                    original_img = original_frames
                    if original_img.mode != 'RGBA':
                        if original_img.mode == 'RGB':
                            original_img = original_img.convert('RGBA')
                        else:
                            original_img = original_img.convert('RGB').convert('RGBA')
                    resized = self._resize_for_display(original_img)
                    self.pil_images[state] = [resized]
            
            # 如果窗口已创建，重新转换为PhotoImage
            if window_created:
                self.convert_to_photoimage()
                # 更新当前图片（使用当前状态）
                self.current_image = self.get_image(self.current_state)
                logger.debug(f"图片大小已更新，当前状态: {self.current_state}, PhotoImage已重新转换")
    
    def get_size(self):
        """获取当前大小等级（1=小，2=中，3=大）"""
        size_map = {(100, 100): 1, (150, 150): 2, (200, 200): 3}
        return size_map.get(self.size, 2)
