# 上传 GitHub 前检查清单

本文档汇总「不能上传/需忽略」的文件、已修正的表述，以及上传前需注意的事项。

---

## 一、不能上传或已忽略的文件（.gitignore）

以下内容已列入 `.gitignore`，**请勿提交**：

| 类型 | 路径/规则 | 说明 |
|------|-----------|------|
| **敏感配置** | `config/gateway.json` | 含 Gateway token/password，必忽略 |
| | `config/.gateway_key` | 加密密钥，必忽略 |
| | `config/settings.json` | 旧版/敏感配置 |
| **用户本地配置** | `config/system_settings.json` | 主题、字体等个人偏好 |
| | `config/ui_settings.json` | 窗口位置等 UI 状态 |
| **运行时状态** | `assistants/current.json` | 当前选中的助手 |
| | `assistants/next_bot_seq.json` | 助手 ID 序号（自动生成） |
| **敏感文件** | `gateway_token.txt`、`.gateway_token` | 根目录或脚本目录下的 token 文件 |
| **环境变量** | `.env`、`.env.local`、`.env.*.local` | 若使用 |
| **日志** | `logs/`、`tests/test.log` | 日志与测试输出 |
| **遗留/打包** | `pets/`（遗留目录名）、`build/`、`dist/`、`*.egg-info/` 等 | 见 .gitignore 全文 |

**若曾误提交过 `config/gateway.json` 或 `config/.gateway_key`**：需从历史中删除并轮换 token/密钥（如 `git filter-repo` 或 BFG），详见 GitHub 文档。

---

## 二、已修正的表述

- **assistant 相关（已移除 pet）**：已删除原 pet 相关 UI/core 文件；i18n 与界面文案统一为「助手」相关键（如 `select_assistant_menu`、`add_assistant_*`、`edit_assistant_*`）；会话渠道前缀为 `claw_assistant_<时间戳>`（`CHANNEL_CLAW_ASSISTANT_PREFIX`）；配置键为 `assistant_size`、`gap_above_assistant_px` 等。
- **.gitignore**：已增加 `assistants/next_bot_seq.json`，避免提交自动生成的序号文件。

---

## 四、其他注意事项

1. **config/gateway.json.example**：应提交；不含真实 token，仅作模板。README/INSTALL 已说明「复制为 gateway.json 后填写」。
2. **assistants/**：可提交示例助手（如 `girl_1`）的 `data.json` 与资源；若某助手的 `data.json` 含个人位置或不想公开的信息，可仅不提交该目录或该文件。
3. **日志与路径**：`utils/logger.py` 与 `utils/monitor_agent.py` 使用相对路径或 `Path.home()`，不会在源码中写入本机绝对路径；运行时生成的 `logs/` 已在 .gitignore 中。
4. **测试**：`tests/test.log` 已忽略；测试代码（如 `tests/__init__.py`）可正常提交。
5. **脚本中的 print**：`scripts/migrate_sprites_to_folders.py`、`utils/md_skill_to_json.py` 中的 `print` 为脚本/CLI 输出，可保留。

上传前建议执行：`git status` 确认无上述敏感或生成文件被纳入提交。

---

## 五、如何更新到 GitHub

### 首次推送（仓库尚未有本地 Git）

1. 在项目根目录打开终端（PowerShell 或 CMD）。
2. 依次执行（将 `ax128/openclaw_assistant` 换成你的用户名/仓库名）：

```powershell
cd D:\openclaw-main\claw_assistant
git init
git remote add origin https://github.com/ax128/openclaw_assistant.git
git add .
git status
git commit -m "Initial commit: Claw Assistant desktop client"
git branch -M main
git push -u origin main
```

3. 按提示登录 GitHub（浏览器或凭证管理器）；推送完成后代码会出现在 `https://github.com/ax128/openclaw_assistant`。

### 之后每次更新（已有 Git 且已关联远程）

1. 在项目根目录打开终端。
2. 执行：

```powershell
cd D:\openclaw-main\claw_assistant
git add .
git status
git commit -m "你的提交说明，例如：统一为 assistant"
git push
```

3. 若远程有其他人或其它分支的提交，先执行 `git pull --rebase` 再 `git push`。

### 注意

- 推送前务必确认 `git status` 里**没有** `config/gateway.json`、`config/.gateway_key`、`logs/`、`assistants/current.json`、`assistants/next_bot_seq.json` 等（这些应在 .gitignore 中）。
- 若使用 SSH：`git remote add origin git@github.com:ax128/openclaw_assistant.git`，并确保本机已配置 SSH 密钥。
