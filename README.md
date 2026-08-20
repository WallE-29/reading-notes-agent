# 读书搭子（AI Reading Buddy）

> 你博学、细腻、没有爹味的**读书搭子**。不是"输入书名 → 吐一份笔记"的工具，而是一个像朋友一样陪你一轮轮聊书的 AI —— 聊你的思考、感受、共鸣，后台已经悄悄把读书笔记建好了。

## 核心体验：聊着聊着，笔记就成型了

读书不是填表。这个搭子的逻辑是：

1. **像朋友一样聊天** —— 你想到哪说到哪，聊情节、聊人物、聊你的理解，它接着你的话往下聊；
2. **它记得你聊到哪** —— 每次对话自动存档，下次接着上次继续（记忆恢复，续读不断档）；
3. **聊着聊着，笔记自己长出来** —— 每轮对话结束后，后台自动把你们的交流沉淀成两份结构化笔记：
   - `notes/<书名>_可视化脑图.md` → Mermaid mindmap，GitHub / Markdown 直接渲染
   - `notes/<书名>_幕布导入版.md` → Tab 缩进大纲，导入幕布 / Xmind 一键生成脑图

你负责畅所欲言，它负责把聊天变成笔记。

## 功能特性

- 💬 **对话式读书体验**：多轮交流推进，不是一次性问答
- 🧠 **会话存档 & 记忆恢复**：它记得你们上次聊到哪，续读不断档
- 📝 **双格式笔记自动生成**：Mermaid 脑图 + 幕布大纲，每轮对话后沉淀
- 🤖 **多模型后端**：Anthropic Claude / DeepSeek（OpenAI 兼容），运行时 `/model` 切换
- 📖 **书名 + 作者双字段录入**：防同名书混淆，支持智能作者背景检索
- ⚙️ **灵活的 Key 配置**：`--api-key` 参数或本地 config 文件持久化

## 效果示例

`notes/` 目录包含两本书的真实生成笔记：

| 书名 | 作者 | 笔记 |
|------|------|------|
| 妻妾成群 | 苏童 | 可视化脑图 + 幕布导入版 |
| 涛动周期论 | 周金涛 | 可视化脑图 + 幕布导入版 |

## 快速开始

```bash
# 1. 准备一个 API Key（Anthropic 或 DeepSeek）

# 2. 直接运行，自动检测 Key 类型
python agent.py

# 或显式指定后端 / Key
python agent.py --provider deepseek
python agent.py --provider anthropic
python agent.py --api-key sk-xxx --model deepseek-chat

# 重置本地配置
python agent.py --reset-config
```

首次运行后，Key 会保存在本地 `.reading_buddy_config.json`（已被 `.gitignore` 排除，不会上传）。

## 技术栈

- Python 3（标准库）
- Anthropic Claude API / DeepSeek API（OpenAI 兼容）
- Mermaid mindmap 语法

## 开发方式

本项目由 **Claude Code 辅助开发**：作者负责产品定位（"读书搭子"的对话体验）与逻辑框架，Claude Code 负责代码生成与调试协作，最终由作者逐段 review 与整合。这是一个「AI 协作编程」的实践项目。

---

## English

# AI Reading Buddy

> Your erudite, thoughtful, non-condescending **reading buddy**. Not a "type a book title → get notes" tool, but an AI that chats with you about books like a friend — while your thinking, feelings, and reflections are quietly turned into structured notes in the background.

## Core Experience: notes take shape as you chat

Reading isn't a form to fill out. The buddy's logic is:

1. **Chat like a friend** — you say whatever comes to mind (plot, characters, your take), and it carries the conversation forward;
2. **It remembers where you left off** — every session is auto-saved and resumed later (memory recovery, no lost context);
3. **Notes grow out of the conversation** — after each session, your exchange is distilled into two structured notes:
   - `notes/<book>_mindmap.md` → Mermaid mindmap, rendered directly on GitHub/Markdown
   - `notes/<book>_mubu.md` → tab-indented outline, one-click import into Mubu/Xmind

You do the talking; it turns the chat into notes.

## Features

- 💬 Conversational reading experience: multi-turn dialogue, not one-shot Q&A
- 🧠 Session save & memory recovery: it remembers where you left off
- 📝 Auto-generated dual-format notes: Mermaid mindmap + Mubu outline after each session
- 🤖 Multi-model backend: Anthropic Claude / DeepSeek (OpenAI-compatible), switch via `/model` at runtime
- 📖 Book title + author dual-field input: avoids same-title mix-ups, smart author background lookup
- ⚙️ Flexible key config: `--api-key` argument or local config file

## Examples

The `notes/` directory contains real generated notes for two books:

| Book | Author | Notes |
|------|--------|-------|
| Wives and Concubines (妻妾成群) | Su Tong | mindmap + Mubu import |
| The Roaring Cycles (涛动周期论) | Zhou Jintao | mindmap + Mubu import |

## Quick Start

```bash
python agent.py                                   # auto-detect key type
python agent.py --provider deepseek               # force DeepSeek
python agent.py --provider anthropic              # force Anthropic
python agent.py --api-key sk-xxx --model deepseek-chat
python agent.py --reset-config
```

After first run, the key is stored locally in `.reading_buddy_config.json` (excluded by `.gitignore`, never uploaded).

## Tech Stack

- Python 3 (standard library)
- Anthropic Claude API / DeepSeek API (OpenAI-compatible)
- Mermaid mindmap syntax

## Development

Built with **Claude Code assistance**: the author owns the product vision (the "reading buddy" conversational experience) and logic framework; Claude Code handles code generation and debugging; the author reviews and integrates every section. A hands-on "AI-assisted programming" project.
