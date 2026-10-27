---
name: book-notes-buddy
description: 通过朋友式对话陪用户整理读书笔记，自动导出思维导图(mermaid)和幕布大纲，并跨书记住读者偏好、生成读书画像。当用户想为某本书整理笔记、想讨论刚读完的书、想回顾读过的书、或提到"读书搭子/读书笔记/书架"时使用。
---

# 读书搭子 · Book Notes Buddy

一个"博学、细腻、没有爹味的"读书伴侣。它不催你交作业，而是像朋友一样陪你聊，
在对话中把你的想法整理成结构化笔记，并慢慢记住你的阅读品味。

## 何时使用

- 用户想为某本书整理读书笔记
- 用户想聊聊刚读完的书、梳理感受
- 用户想看自己读过的书 / 自己的读书偏好画像
- 用户提到"读书搭子""读书笔记""书架""我的阅读画像"

## 前置依赖

1. **Python 3.10+**
2. **openai 库**：`pip install openai`
3. **API Key**（任何 OpenAI 兼容服务都支持，见下方配置）

## 配置 API Key（三选一）

### 方式一：环境变量（推荐）

```bash
# DeepSeek（最便宜，推荐入门）
export DEEPSEEK_API_KEY=sk-你的密钥        # macOS/Linux
$env:DEEPSEEK_API_KEY="sk-你的密钥"        # PowerShell

# 或任意 OpenAI 兼容服务
export OPENAI_API_KEY=你的密钥
export OPENAI_BASE_URL=https://api.openai.com/v1
export OPENAI_MODEL=gpt-4o

# Claude 原生
export ANTHROPIC_API_KEY=sk-ant-你的密钥
```

### 方式二：配置文件

复制 `config.example.json` 为 `config.json`，填入三要素：

```json
{
  "api_key": "你的密钥",
  "base_url": "https://api.deepseek.com",
  "model": "deepseek-chat",
  "provider": "openai_compatible"
}
```

### 常见服务 base_url 对照

| 服务 | base_url | model 示例 |
|------|----------|-----------|
| DeepSeek | `https://api.deepseek.com` | `deepseek-chat` |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o` |
| 智谱 GLM | `https://open.bigmodel.cn/api/paas/v4` | `glm-4.7` |
| Kimi | `https://api.moonshot.cn/v1` | `moonshot-v1-8k` |
| 通义千问 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus` |
| 本地 Ollama | `http://localhost:11434/v1` | `llama3` |

### 方式三：运行时临时指定

```bash
python agent.py --api-key sk-xxx --base-url https://api.deepseek.com --model deepseek-chat
```

## 怎么用

### 开始聊一本书

```bash
python agent.py
```

流程：
1. 输入书名 + 作者（有确认关卡，打错可按 `r` 重输）
2. AI 判断是否读过这本书 → 读过走"经典引导"，没读过走"盲盒盲读"（一起探索）
3. 像朋友聊天一样，每次只问一个问题
4. 对话结束后自动生成两份笔记到 `notes/`：
   - `<书名>__by__<作者>_可视化脑图.md`（mermaid mindmap）
   - `<书名>__by__<作者>_幕布导入版.md`（可导入幕布/Xmind）

### 查看书架（本地网页）

```bash
python shelf.py
# 打开 http://127.0.0.1:8766
```

书架页展示：读过的书（点击看笔记）、读者画像、跨书记忆、统计信息。
仅监听本机，数据不外发。

### 会话内命令

| 命令 | 作用 |
|------|------|
| `/config`（或 `/service`） | 交互式切换服务（改 api_key / base_url / model） |
| `/model <模型名>` | 同服务内切换模型 |
| `/profile`（或 `/me`） | 查看读者画像和跨书记忆 |
| `/save` | 手动存档当前会话 |
| `/history` | 查看历史会话 |
| `/author` | 查看作者背景信息 |
| `/help` | 帮助 |
| `/quit`（或 `/exit` `/q`） | 退出（会触发记忆提炼） |

### 常用启动参数

```bash
python agent.py --list-sessions    # 列出所有存档会话
python agent.py --reset-config     # 重置配置
```

## 核心规则（Agent 扮演读书搭子时必须遵守）

1. **每次只问一个问题**，像沙龙聊天，不像答辩
2. **不说教、不居高临下、不评判读者品味**——不用"你应该""这本书的核心思想是"这类句式
3. 用户贴了大段原文时，先真诚回应一两个细节，再自然引出下一个问题
4. **不假装读过没读过的书**——诚实承认，转为"好奇的共读者"姿态
5. 跨书记忆只在**同作者或题材相近**时自然提起，不硬扯
6. 不编造书中不存在的细节

## 数据文件说明（都在本地，不上传）

| 文件/目录 | 内容 |
|-----------|------|
| `sessions/*.json` | 每本书的对话存档 |
| `notes/*.md` | 生成的读书笔记 |
| `memory.md` | 跨书记忆：从对话中提炼的读者偏好（只增不删） |
| `profile.md` | 读者画像：文艺风格的画像速写 + 初次相识问答 |
| `config.json` | API 配置（含密钥，**已被 .gitignore 保护**） |

## 隐私说明

- 所有数据（对话、笔记、画像、密钥）都保存在本地
- `config.json`、`sessions/`、`notes/`、`memory.md`、`profile.md` 均在 `.gitignore` 中，不会上传
- 书架服务只绑定 `127.0.0.1`，不对局域网/公网开放

## 在各 Agent 平台安装

本仓库遵循 [Agent Skills](https://agentskills.io) 开放规范（`SKILL.md` + 说明），
可被 Cursor / Claude Code / GitHub Copilot / Codex 等 40+ 工具识别。

```bash
# 克隆仓库
git clone https://github.com/WallE-29/reading-notes-agent.git

# 方式一：项目级安装（Cursor / Claude Code）
mkdir -p .claude/skills
cp -r reading-notes-agent .claude/skills/book-notes-buddy

# 方式二：全局安装
cp -r reading-notes-agent ~/.claude/skills/book-notes-buddy

# 方式三：直接当命令行工具用
cd reading-notes-agent && pip install openai && python agent.py
```

安装后，Agent 会在相关场景自动发现并调用本技能。
