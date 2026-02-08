# 安装说明

本文档说明 Claw Assistant 的依赖安装、Gateway 配置、助手图片资源、语音功能及可选打包方式。

---

## 一、依赖安装

### 1.1 环境要求

- **Python**：3.8+（建议 3.10+）
- **系统**：Windows / macOS / Linux

建议在虚拟环境中安装，避免与系统 Python 冲突：

```bash
# 创建虚拟环境（可选）
python -m venv venv

# 激活虚拟环境
# Windows (PowerShell):
.\venv\Scripts\Activate.ps1
# Windows (CMD):
.\venv\Scripts\activate.bat
# macOS/Linux:
source venv/bin/activate
```

### 1.2 必需依赖

一次性安装所有必需依赖：

```bash
pip install -r requirements.txt
```

或单独安装核心包：

```bash
pip install Pillow PyQt5 requests websockets paramiko cryptography
```

| 包 | 用途 |
|----|------|
| **Pillow** | 图像处理，用于助手精灵图片加载与占位图 |
| **PyQt5** | 桌面 UI（助手窗口、聊天、设置等） |
| **requests** | HTTP 请求（若需调用外部 API） |
| **websockets** | Gateway WebSocket 连接 |
| **paramiko** | SSH 隧道（可选，用于远程 Gateway 转发） |
| **cryptography** | Gateway 敏感项（token/password）本地加密存储 |

### 1.3 语音功能（可选）

语音合成使用 [edge-tts](https://github.com/microsoft/edge-tts)（Microsoft 在线神经语音），轻量、音质自然，支持中英日等多语言。若需在气泡中朗读回复，需安装：

```bash
pip install edge-tts playsound mutagen
```

| 包 | 用途 |
|----|------|
| **edge-tts** | 文本转语音（在线） |
| **playsound** | 播放音频 |
| **mutagen** | 音频元数据（部分格式处理） |

不安装上述包时，程序仍可正常运行，仅无语音朗读功能。

---

## 二、Gateway 配置（首次运行前必做）

### 2.1 创建配置文件

1. 将示例配置复制为实际配置（**不要**提交 `gateway.json` 到 Git）：

   ```bash
   cp config/gateway.json.example config/gateway.json
   ```

   Windows 下可手动复制并重命名。

2. 用文本编辑器打开 `config/gateway.json`，按下面说明填写。

### 2.2 配置项说明

| 键 | 说明 | 示例 |
|----|------|------|
| **gateway_ws_url** | Gateway WebSocket 地址 | `ws://127.0.0.1:18789` |
| **gateway_token** | 认证 Token（若 Gateway 启用 Token 认证） | 你的 token 字符串 |
| **gateway_password** | 认证密码（若 Gateway 使用密码认证） | 你的密码 |
| **auto_login** | 是否在启动时自动连接 | `true` / `false` |
| **ssh_enabled** | 是否通过 SSH 隧道连接 | `true` / `false` |
| **ssh_username** | SSH 用户名 | 如 `user` |
| **ssh_server** | SSH 服务器地址 | 如 `gateway.example.com` |
| **ssh_password** | SSH 密码（可选，也可用密钥） | 留空则依赖密钥或 ssh-agent |

- 本地 Gateway：通常只需填 `gateway_ws_url`（如 `ws://127.0.0.1:18789`），若启用认证再填 `gateway_token` 或 `gateway_password`。
- 远程/内网：可开启 `ssh_enabled`，填写 SSH 相关项，程序会先建立隧道再连 `127.0.0.1:端口`。

### 2.3 敏感信息加密

- Token、密码、SSH 密码在保存时可经 `config/.gateway_key` 加密后写入 `gateway.json`（带 `enc:` 前缀）。
- **切勿**将 `config/gateway.json` 和 `config/.gateway_key` 提交到版本库；`.gitignore` 已包含这两项。

---

## 三、快速开始

1. **安装依赖**（见上文）  
   ```bash
   pip install -r requirements.txt
   ```

2. **配置 Gateway**（见上文）  
   - 复制 `config/gateway.json.example` 为 `config/gateway.json` 并填写。

3. **运行程序**  
   ```bash
   python main.py
   ```

4. 启动后会打开 **助手窗口** 和 **连接窗口**；在连接窗口填写地址与认证信息并连接，连接成功后即可双击助手打开聊天。

---

## 四、助手图片资源

### 4.1 加载路径

程序按以下顺序查找助手图片：

1. `assistants/{助手目录名}/assets/sprites/`（**优先**）
2. `assistants/{助手目录名}/assets/`（备选）

助手目录名即 `assistants/` 下的子文件夹名；每个助手目录内需有 `data.json`。

### 4.2 支持的图片格式

- **PNG**（推荐，支持透明背景）
- JPG/JPEG
- GIF

### 4.3 两种目录结构

程序支持两种精灵目录结构，**新结构**优先。

**新结构（推荐）**：按状态分子文件夹，帧命名为 `1.png`、`2.png`、…：

```
assistants/{助手名}/assets/sprites/
├── idle/       # 待机
│   ├── 1.png
│   ├── 2.png
│   └── ...
├── walk/       # 走路
│   ├── 1.png
│   └── ...
├── happy/      # 开心
├── sad/        # 难过
├── think/      # 思考
├── drag/       # 拖拽中
└── paused/     # 暂停
```

**旧结构**：所有帧放在 `sprites/` 下，按「状态名_序号」命名：

```
assistants/{助手名}/assets/sprites/
├── idle_1.png
├── idle_2.png
├── walk_1.png
├── walk_2.png
├── happy.png
├── sad.png
├── thinking.png
└── ...
```

### 4.4 状态与文件夹对应关系

程序内部状态与 `sprites` 下子文件夹名（或旧结构中的前缀）的对应关系如下：

| 状态名 | 子文件夹名（新结构） | 说明 |
|--------|----------------------|------|
| idle | idle | 待机 |
| walking | walk | 走路 |
| dragging | drag | 拖拽中 |
| paused | paused | 暂停 |
| happy | happy | 开心 |
| sad | sad | 难过 |
| thinking | think | 思考 |

可在助手的 `data.json` 中通过 `state_to_sprite_folder` 覆盖上述映射（键为状态名，值为文件夹名）。

### 4.5 占位符

若某状态没有对应图片，程序会使用占位图，不会报错。

---

## 五、助手 data.json 简要说明

每个助手目录下需有 `data.json`，至少包含：

- **name**：显示名称  
- **state**：当前状态（如 `happy`、`idle`）  
- **position**：窗口位置 `{"x": 100, "y": 100}`  
- **bot_id**：与 Gateway 对应的 bot 标识（如 `bot00001`）  
- **config**：行为与动画配置（漫游、速度、体型、语音、气泡、帧率等）  
- **state_to_sprite_folder**（可选）：状态到精灵子文件夹的映射，不写则用程序默认映射  

可通过「设置 → 添加/编辑助手」在界面中维护，或参考已有助手（如 `assistants/girl_1/data.json`）手动编辑。

---

## 六、平台说明（简要）

- **Windows**：直接运行 `python main.py`；若打包，可使用 PyInstaller（见下文）。
- **macOS**：发送消息快捷键为 **Cmd+Return**；右键为双指轻点或 Ctrl+左键；字体与样式会按 macOS 调整。
- **Linux**：依赖 X11/Wayland 与 PyQt5 对应支持；滚轮等事件已做跨平台处理。

更详细的跨平台与打包说明见项目内 `docs/PLATFORM.md`（若存在）。

---

## 七、打包为可执行文件（可选）

### Windows

使用 PyInstaller 打包为单文件、无控制台窗口：

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name "ClawAssistant" --add-data "config;config" --add-data "core;core" --add-data "ui;ui" --add-data "utils;utils" --add-data "assistants;assistants" main.py
```

需根据实际目录结构调整 `--add-data`，确保 `config`、`core`、`ui`、`utils`、`assistants` 等资源被包含；打包后首次运行需在同一目录放置 `config/gateway.json`（或由用户自行配置）。

### macOS

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name "ClawAssistant" main.py
```

若提示「来自未认证开发者」，需在「系统偏好设置 → 安全性与隐私」中允许该应用。

---

## 八、故障排除

- **ModuleNotFoundError**：确认已激活虚拟环境并执行 `pip install -r requirements.txt`。
- **连接 Gateway 失败**：检查 Gateway 是否启动、地址与端口是否正确、Token/密码是否与 Gateway 配置一致、防火墙是否放行。
- **ConnectionResetError / WinError 64 / InvalidMessage（未收到有效 HTTP 响应）**：  
  通常表示客户端能连上目标地址，但对方未返回有效的 WebSocket 握手响应。请确认：  
  1）OpenClaw Gateway **已在本机或目标机启动**；  
  2）地址为 **WebSocket 协议**（`ws://` 或 `wss://`），例如 `ws://127.0.0.1:18789`；  
  3）端口与 Gateway 配置一致（默认 18789）；  
  4）若为远程地址，检查网络、VPN、防火墙是否阻断；  
  5）若本机有多个网卡或虚拟网卡，可优先用 `127.0.0.1` 测试本地 Gateway。
- **助手不显示/窗口透明异常**：多为显卡或窗口管理器差异，可尝试更换主题或关闭透明效果（若设置中有相关选项）。
- **语音不播放**：确认已安装 `edge-tts`、`playsound`、`mutagen`，并检查系统音频设备与权限。

更多问题可查阅项目 README 的「常见问题」或提交 Issue。
