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

## Design rationale

Most note-taking tools ask you to fill in fields. This one deliberately does not, and the reasoning is worth stating:

1. **Conversational interaction over forms.** Reading notes are an act of interpretation, not data entry. Free-form dialogue lets the user keep the interpretive work — associations, doubts, half-formed reactions — and defers structuring until later. The system externalizes the exchange into artifacts (Mermaid mind maps, outline exports) instead of demanding structure up front.

2. **A deliberate division of labour.** The user makes meaning; the agent handles structuring, recall, and format generation. Persistent session memory keeps that division stable across long-horizon interactions — an agent that forgets degrades back into a tool.

3. **Model choice as a variable, not a setting.** The agent supports runtime switching between Claude and DeepSeek. Switching mid-session is partly a cost decision, partly an experiment: different backends produce noticeably different output structure, which is useful evidence when thinking about how model capability shapes the artifacts people end up keeping.

4. **A two-layer memory, not a log.** The agent keeps an append-only episodic store of reading preferences across books, and separately maintains a synthesized reader profile that gets rewritten as evidence accumulates. Raw observations and the consolidated model are deliberately kept apart: consolidation is a judgement call, and keeping both makes it auditable. Extraction is deduplicated (no new signal, no new entry) and retried at next launch if a session ended abnormally, so the agent's model of its reader is not silently lost. Personal data files stay local and are git-ignored.

## Features

- 💬 Conversational reading experience: multi-turn dialogue, not one-shot Q&A
- 🧠 Session save & memory recovery: it remembers where you left off
- 📝 Auto-generated dual-format notes: Mermaid mindmap + Mubu outline after each session
- 📚 **Shelf dashboard**: a local web page showing every book you've noted, your reader profile, and cross-book memory (`python shelf.py`)
- 🔌 **Distributable as an Agent Skill**: follows the open [Agent Skills](https://agentskills.io) spec — auto-discovered by Cursor / Claude Code / Copilot / Codex and 40+ other agents
- 🤖 Multi-model backend: any OpenAI-compatible service (DeepSeek / GLM / Kimi / Qwen / local Ollama …) or Anthropic native — switch via `/model` and `/config` at runtime
- 📖 Book title + author dual-field input: avoids same-title mix-ups, smart author background lookup
- ⚙️ Flexible key config: env vars / `config.json` (template: `config.example.json`) / `--api-key` argument

## Install as an Agent Skill

This repo follows the open **Agent Skills** format: a folder containing a `SKILL.md`.
Once installed, your agent discovers the skill automatically and invokes it when the
user wants to work on reading notes — no need to remember commands.

```bash
git clone https://github.com/WallE-29/reading-notes-agent.git

# Cursor / Claude Code — project level
mkdir -p .claude/skills
cp -r reading-notes-agent .claude/skills/book-notes-buddy

# Cursor / Claude Code — global
cp -r reading-notes-agent ~/.claude/skills/book-notes-buddy

# Or just use it as a plain CLI tool
cd reading-notes-agent && pip install openai && python agent.py
```

Compatible agents load `SKILL.md` from `.claude/skills/`, `.cursor/skills/`, `.agents/skills/`
and their global equivalents.

## Examples

`examples/` contains a sample note pair (`活着` / *To Live*, Yu Hua) showing the exact
output format — a Mermaid mindmap and a Mubu-importable outline. Copy them into `notes/`
to preview the shelf dashboard, or just run the agent on a book of your own.

| Sample | Format |
|--------|--------|
| `examples/示例_可视化脑图.md` | Mermaid mindmap |
| `examples/示例_幕布导入版.md` | Mubu / Xmind outline |

Generated notes land in `notes/`, which is git-ignored — your reading data stays local.

## Quick Start

```bash
# 1. Read and chat (the agent)
python agent.py                                   # config from env vars / config.json
python agent.py --protocol anthropic              # force Anthropic native protocol
python agent.py --api-key sk-xxx --base-url https://api.deepseek.com --model deepseek-chat
python agent.py --reset-config
python agent.py --list-sessions                   # list saved sessions

# 2. View your shelf (local web page, 127.0.0.1 only)
python shelf.py                                   # → http://127.0.0.1:8766
```

The key lives in local `config.json` — copy `config.example.json` and fill in `api_key` / `base_url` / `model` (excluded by `.gitignore`, never uploaded). Env vars (`OPENAI_API_KEY` etc.) take priority when set.

## Tech Stack

- Python 3 (standard library)
- Any OpenAI-compatible API (DeepSeek / GLM / Kimi / Qwen / Ollama …) or Anthropic native
- Mermaid mindmap syntax

## Development

Built with **Claude Code assistance**: the author owns the product vision (the "reading buddy" conversational experience) and logic framework; Claude Code handles code generation and debugging; the author reviews and integrates every section. A hands-on "AI-assisted programming" project.
