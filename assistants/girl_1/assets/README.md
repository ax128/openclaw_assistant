# p_bot 外观资源文件夹

## 目录说明

- **sprites/**: 精灵图资源（主要目录）
  - 放置所有状态和动画帧的图片

- **animations/**: 动画资源（可选，未来扩展）
  - 可以放置动画序列文件

- **icons/**: 图标资源（可选）
  - `icon.png`: 助手图标（用于选择窗口）

## 动画资源设置

### 支持的状态

1. **idle** - 待机状态
   - 图片命名: `idle_1.png`, `idle_2.png`, `idle_3.png`, ...
   - 或单帧: `idle.png`
   - 建议帧数: 2-4帧
   - 动画速度: 0.5秒/帧

2. **walking** - 游走状态
   - 图片命名: `walk_1.png`, `walk_2.png`, `walk_3.png`, `walk_4.png`, ...
   - 或单帧: `walk_1.png`, `walk.png`
   - 建议帧数: 4-8帧
   - 动画速度: 0.15秒/帧

3. **dragging** - 拖动状态
   - 图片命名: `drag_1.png`, `drag_2.png`, ...
   - 或单帧: `drag_1.png`, `drag.png`
   - 建议帧数: 2-4帧
   - 动画速度: 0.2秒/帧

4. **paused** - 暂停/禁止状态
   - 图片命名: `paused_1.png`, `paused_2.png`, ...
   - 或单帧: `paused_1.png`, `paused.png`
   - 建议帧数: 1-3帧
   - 动画速度: 1.0秒/帧

5. **happy** - 开心状态（可选）
   - 图片命名: `happy_1.png`, `happy_2.png`, ...
   - 或单帧: `happy.png`

6. **sad** - 难过状态（可选）
   - 图片命名: `sad_1.png`, `sad_2.png`, ...
   - 或单帧: `sad.png`

7. **thinking** - 思考状态（可选）
   - 图片命名: `thinking_1.png`, `thinking_2.png`, ...
   - 或单帧: `thinking.png`

## 资源规范

- **格式**: PNG（必须支持透明背景，RGBA模式）
- **建议尺寸**: 64x64 或 128x128 像素
- **命名规范**: `{状态名}_{帧序号}.png`（如 `walk_1.png`, `walk_2.png`）
- **帧序号**: 从1开始，连续编号，不要跳过数字
- **所有帧**: 必须相同尺寸

## 最小配置

只需要提供以下图片即可运行：
- `idle.png` 或 `idle_1.png` - 待机状态
- `walk_1.png` - 走路状态（至少1帧）

## 推荐配置

提供以下动画序列，让机器人更生动：
- `idle_1.png`, `idle_2.png` - 待机动画（2帧）
- `walk_1.png` ~ `walk_4.png` - 走路动画（4帧）
- `drag_1.png`, `drag_2.png` - 拖动动画（2帧）
- `paused_1.png` - 暂停状态（1帧）

## 详细说明

更多信息请查看项目根目录的 [ANIMATION_GUIDE.md](../../ANIMATION_GUIDE.md)
