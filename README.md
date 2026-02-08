# Claw Assistant

基于 **PyQt5** 的桌面助手客户端，通过 **OpenClaw Gateway** 与 AI 对话。支持多助手、会话管理、语音气泡与跨平台（Windows / macOS / Linux），可作为桌面助手与聊天入口使用。

---

## 功能概览

| 功能 | 说明 |
|------|------|
| **桌面助手** | 透明无边框窗口、PNG 精灵动画（待机/走路/开心/思考等）、可拖拽移动、右键菜单 |
| **AI 聊天** | 双击助手打开聊天窗口，与 OpenClaw 后端对话；支持流式回复、思考过程展示 |
| **会话列表** | 多会话管理、新建/切换/删除会话，会话与 Gateway 同步 |
| **Gateway 连接** | WebSocket 连接 OpenClaw Gateway，Token/密码认证，支持自动登录与断线重连 |
| **SSH 隧道** | 可选 SSH 隧道转发，便于远程或内网 Gateway 访问 |
| **多助手** | 多个助手配置（名称、体型、精灵资源），运行时切换当前助手 |
| **语音气泡** | 助手气泡提示（如连接成功/断开）；可选 TTS 朗读（edge-tts） |
| **设置** | 全局设置（主题、字体、聊天选项、自动互动）、Gateway 设置、助手/模型管理 |
| **国际化** | 界面中/英切换（在设置中修改「界面语言」或 `config/system_settings.json` 的 `locale`） |

---

## 环境要求

- **Python**：3.8+（建议 3.10+）
- **系统**：Windows / macOS / Linux（UI 与快捷键已按平台适配）
- **OpenClaw Gateway**：需已部署或可访问的 OpenClaw Gateway 服务（如本地 `ws://127.0.0.1:18789`）

---

## 安装与首次运行

详细步骤见 **[INSTALL.md](INSTALL.md)**，此处为简要流程：

1. **克隆或下载项目**
   ```bash
   git clone <你的仓库地址>
   cd claw_assistant
   ```

2. **安装依赖**
   ```bash
   pip install -r requirements.txt
   ```
   主要依赖：PyQt5、Pillow、requests、websockets、paramiko、cryptography。  
   若需语音朗读，需额外安装：`edge-tts`、`playsound`、`mutagen`（见 INSTALL.md）。

3. **配置 Gateway（首次运行前必做）**
   - 将 `config/gateway.json.example` 复制为 `config/gateway.json`。
   - 在 `config/gateway.json` 中填写：
     - `gateway_ws_url`：Gateway WebSocket 地址（例如 `ws://127.0.0.1:18789`）。
     - `gateway_token` 或 `gateway_password`：按你使用的 OpenClaw 认证方式填写。
   - **注意**：`config/gateway.json` 含敏感信息，已列入 `.gitignore`，请勿提交；敏感项会经 `config/.gateway_key` 加密后落盘，密钥也勿提交。

4. **启动程序**
   ```bash
   python main.py
   ```

---

## 使用说明

### 启动后

- 会同时打开 **助手窗口**（桌面助手）和 **连接/登录窗口**（Gateway 配置）。
- 在连接窗口中填写 Gateway 地址与认证信息，点击连接；连接成功后助手会通过气泡提示，可关闭连接窗口。
- 之后可在 **设置 → Gateway 设置** 中修改地址或重连。

### 助手窗口操作

- **双击助手**：打开当前助手的聊天窗口，与 AI 对话。
- **右键助手**：打开菜单，可进入「设置」「会话列表」「新建聊天」等。
- **拖拽助手**：可把助手拖到屏幕任意位置，位置会自动保存。

### 聊天窗口

- 支持多会话：在会话列表中新建、切换、删除会话。
- 发送消息：输入内容后按 **Ctrl+Enter**（Windows/Linux）或 **Cmd+Enter**（macOS）发送。
- 流式回复与思考过程：若后端支持，会实时显示思考与回复内容。

### 设置入口

- 右键助手 → **设置**，可配置：
  - **通用**：界面语言、主题等。
  - **聊天**：文字大小、弹窗大小、是否显示思考过程等。
  - **Gateway 设置**：WebSocket 地址、Token/密码、自动登录、SSH 隧道。
  - **助手/模型**：添加、编辑助手与模型。
  - **日志**：查看主程序与 Gateway 日志、清除缓存等。

---

## 配置说明

配置分散在多个文件中，由 `config/settings.py` 统一加载与保存：

| 文件 | 用途 | 说明 |
|------|------|------|
| `assistants/current.json` | 当前助手 | 记录当前选中的助手（如 `current_assistant`、`assistants_dir`），运行时写入，勿提交。 |
| `config/gateway.json` | Gateway 连接 | `gateway_ws_url`、`gateway_token`、`gateway_password`、`auto_login`、SSH 相关；敏感项可加密存储。 |
| `config/system_settings.json` | 系统设置 | 主题、字体、聊天选项、日志级别、自动互动、界面语言等。 |
| `config/ui_settings.json` | UI 状态 | 窗口位置、弹窗大小等，由程序自动写入。 |

更多键名与默认值见 `config/settings.py` 中的 `BOOTSTRAP_KEYS`、`GATEWAY_KEYS`、`SYSTEM_SETTINGS_KEYS` 及 `_load_default()`。

---

## 项目结构（简要）

```
claw_assistant/
├── main.py                 # 入口：加载配置、助手、启动 PyQt5 主窗口
├── config/
│   ├── gateway.json.example  # Gateway 配置示例（复制为 gateway.json 后填写）
│   ├── settings.py         # 全局配置加载（current.json + gateway.json + system_settings.json）
│   └── secret_cipher.py    # 敏感项加密（依赖 config/.gateway_key）
├── core/
│   ├── assistant_manager.py   # 助手列表与当前助手切换
│   ├── assistant_data.py     # 助手 data.json 与配置
│   ├── assistant_config.py    # 助手行为/动画配置
│   ├── openclaw_gateway/     # Gateway WebSocket 客户端、协议、本地-服务端桥接
│   └── movement.py           # 助手移动控制
├── ui/
│   ├── assistant_window.py   # 助手主窗口（精灵、气泡、右键菜单）
│   ├── chat_window.py        # 聊天窗口
│   ├── session_list_window.py  # 会话列表
│   ├── startup_dialog.py    # 启动时 Gateway 连接对话框
│   └── settings/            # 设置、Gateway 设置、主题、助手/模型编辑等
├── utils/                   # 日志、国际化、平台适配、TTS、SSH 隧道等
├── assistants/              # 助手资源（每助手一目录，含 data.json 与 assets/sprites）
├── docs/                    # 设计/平台/优化等文档（若有）
├── INSTALL.md               # 安装与资源详细说明
├── requirements.txt
└── README.md                # 本文件
```

---

## 助手资源

- 每个助手在 `assistants/<助手目录名>/` 下需有 `data.json`，并可包含 `assets/sprites/` 下的 PNG 精灵。
- 支持的精灵状态与命名、两种目录结构（新：按状态分子文件夹；旧：扁平命名）见 **[INSTALL.md](INSTALL.md)#图片资源**。
- 若无图片，程序会使用占位图。

---

## 文档

- **安装与资源**： [INSTALL.md](INSTALL.md)（依赖、虚拟环境、Gateway 配置、图片资源、语音、打包等）
- 若存在 **docs/**：可参阅 `docs/PLATFORM.md`（跨平台与打包）、`docs/PROJECT_DESIGN_REVIEW.md` 等设计与代码审查文档。

---

## 常见问题

- **连接失败**：确认 OpenClaw Gateway 已启动且地址、端口正确；若使用 Token/密码，请与 Gateway 配置一致；防火墙是否放行。
- **没有助手**：在「设置」中添加助手，或检查 `assistants/` 下是否有至少一个包含 `data.json` 的子目录。
- **助手不显示/透明异常**：不同系统对无边框透明窗口支持不一，可尝试调整主题或窗口设置；详见文档中的平台说明。

---

## 开发与测试

- 测试位于 `tests/`，可根据项目约定运行（如 `pytest tests/`）。
- 代码风格与架构建议见 `docs/` 中的审查与优化文档。

---

## 许可证与致谢

- 本项目为 OpenClaw 生态的桌面助手客户端，需与 [OpenClaw](https://github.com/openclaw/openclaw) Gateway 配合使用。
- 使用前请确保已部署或可访问 OpenClaw Gateway，并遵守相关服务的条款与许可。

如有问题或建议，欢迎提 Issue 或 Pull Request。
