[简体中文](README.zh-CN.md) | English

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
