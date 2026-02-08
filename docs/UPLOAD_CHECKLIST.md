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
| **遗留/打包** | `pets/`、`build/`、`dist/`、`*.egg-info/` 等 | 见 .gitignore 全文 |

**若曾误提交过 `config/gateway.json` 或 `config/.gateway_key`**：需从历史中删除并轮换 token/密钥（如 `git filter-repo` 或 BFG），详见 GitHub 文档。

---

## 二、已修正的表述

- **pet_window.py**：文档字符串中 `pets/current.json` 已改为 `assistants/current.json`，与当前数据目录一致。
- **.gitignore**：已增加 `assistants/next_bot_seq.json`，避免提交自动生成的序号文件。

---

## 三、可选优化（命名与示例）

- **i18n「选择机器人」**：若希望与项目名「助手」完全一致，可将「选择机器人」改为「选择助手」、英文 "Select robot" 改为 "Select assistant"（`utils/i18n.py` 中 `select_robot_menu`）。
- **sessionKey 示例 `claw_pet`**：当前新建会话渠道前缀为 `claw_pet_<时间戳>`（`session_list_window.py` 中 `CHANNEL_CLAW_PET_PREFIX`），i18n 占位符为 `agent:work:claw_pet`。若 Gateway/后端已统一为 `claw_assistant`，可改为 `claw_assistant` 并同步文档与占位符；否则保持 `claw_pet` 以兼容现有会话。

---

## 四、其他注意事项

1. **config/gateway.json.example**：应提交；不含真实 token，仅作模板。README/INSTALL 已说明「复制为 gateway.json 后填写」。
2. **assistants/**：可提交示例助手（如 `girl_1`）的 `data.json` 与资源；若某助手的 `data.json` 含个人位置或不想公开的信息，可仅不提交该目录或该文件。
3. **日志与路径**：`utils/logger.py` 与 `utils/monitor_agent.py` 使用相对路径或 `Path.home()`，不会在源码中写入本机绝对路径；运行时生成的 `logs/` 已在 .gitignore 中。
4. **测试**：`tests/test.log` 已忽略；测试代码（如 `tests/__init__.py`）可正常提交。
5. **脚本中的 print**：`scripts/migrate_sprites_to_folders.py`、`utils/md_skill_to_json.py` 中的 `print` 为脚本/CLI 输出，可保留。

上传前建议执行：`git status` 确认无上述敏感或生成文件被纳入提交。
