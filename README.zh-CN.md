简体中文 | [English](README.md)

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

## 设计考量

大多数笔记工具要求你填表。这个项目刻意不那么做，理由值得写清楚：

1. **用对话，而不是表单。** 读书笔记是理解的过程，不是数据录入。自由对话让用户保留"做理解"这件事本身——联想到什么、哪里存疑、半成型的反应——把结构化推迟到后面。系统负责把交流沉淀成产物（Mermaid 脑图、大纲导出），而不是一上来就要求结构。

2. **刻意的分工。** 用户负责意义建构，Agent 负责结构化、回忆和格式生成。持久化的会话记忆让这个分工在长周期交互中保持稳定——一个会遗忘的 Agent 会退化成工具。

3. **把模型选择当作变量，而不是设置项。** 支持在 Claude 和 DeepSeek 之间运行时切换。中途切换一半是成本考虑，一半是实验：不同后端产出的结构差别明显，这对思考"模型能力如何塑造人最终留下的产物"是有用的证据。

4. **两层记忆，而不是一份日志。** Agent 维护一份只增不删的跨书偏好记忆，另外单独维护一份"读者画像"，随证据积累被重写。原始观察和综合出来的模型刻意分开存放：综合是一次判断，两者都保留才审计得动。提炼会去重（没有新信号就不写新条目），且会话异常结束时会在下次启动补做，Agent 对读者的模型不会悄悄丢掉。个人数据文件留在本地并被 gitignore。

## 功能特性

- 💬 **对话式读书体验**：多轮交流推进，不是一次性问答
- 🧠 **会话存档 & 记忆恢复**：它记得你们上次聊到哪，续读不断档
- 📝 **双格式笔记自动生成**：Mermaid 脑图 + 幕布大纲，每轮对话后沉淀
- 📚 **书架 Dashboard**：本地网页展示读过的书、读者画像、跨书记忆（`python shelf.py`）
- 🔌 **可作为 Agent Skill 分发**：遵循开放的 [Agent Skills](https://agentskills.io) 规范，可被 Cursor / Claude Code / Copilot / Codex 等 40+ Agent 自动发现调用
- 🤖 **多模型后端**：任意 OpenAI 兼容服务（DeepSeek / GLM / Kimi / 通义 / 本地 Ollama…）或 Anthropic 原生，运行时 `/model`、`/config` 切换
- 📖 **书名 + 作者双字段录入**：防同名书混淆，支持智能作者背景检索
- ⚙️ **灵活的 Key 配置**：环境变量 / `config.json`（模板 `config.example.json`）/ `--api-key` 参数

## 作为 Agent Skill 安装

本仓库遵循开放的 **Agent Skills** 规范（一个包含 `SKILL.md` 的文件夹）。
安装后，你的 Agent 会自动发现本技能，并在你提到读书笔记相关需求时自动调用，
不用记命令。

```bash
git clone https://github.com/WallE-29/reading-notes-agent.git

# Cursor / Claude Code —— 项目级
mkdir -p .claude/skills
cp -r reading-notes-agent .claude/skills/book-notes-buddy

# Cursor / Claude Code —— 全局
cp -r reading-notes-agent ~/.claude/skills/book-notes-buddy

# 或者直接当命令行工具用
cd reading-notes-agent && pip install openai && python agent.py
```

兼容的 Agent 会从 `.claude/skills/`、`.cursor/skills/`、`.agents/skills/`
及其全局目录加载 `SKILL.md`。

## 效果示例

`examples/` 里有一份示例笔记（《活着》/ 余华），展示真实产出的格式：

| 示例文件 | 格式 |
|----------|------|
| `examples/示例_可视化脑图.md` | Mermaid 思维导图 |
| `examples/示例_幕布导入版.md` | 幕布 / Xmind 大纲 |

把它复制进 `notes/` 就能预览书架效果，或直接对你自己想读的书跑一遍。
你生成的笔记会落在 `notes/`，该目录已被 gitignore——阅读数据只留在本地。

## 快速开始

```bash
# 1. 准备一个 API Key（任一 OpenAI 兼容服务，或 Anthropic）

# 2. 开始聊书（Agent）
python agent.py

# 或复制 config.example.json 为 config.json，填入 api_key / base_url / model
# 或命令行显式指定
python agent.py --protocol anthropic
python agent.py --api-key sk-xxx --base-url https://api.deepseek.com --model deepseek-chat

# 其他常用
python agent.py --reset-config      # 重置本地配置
python agent.py --list-sessions     # 列出所有存档会话

# 3. 查看书架（本地网页，仅 127.0.0.1）
python shelf.py                     # → http://127.0.0.1:8766
```

Key 保存在本地 `config.json`（复制 `config.example.json` 填写即可；已被 `.gitignore` 排除，不会上传）。设置了 `OPENAI_API_KEY` 等环境变量时以环境变量优先。

## 技术栈

- Python 3（标准库）
- 任意 OpenAI 兼容 API（DeepSeek / GLM / Kimi / 通义 / Ollama…）或 Anthropic 原生
- Mermaid mindmap 语法

## 开发方式

本项目由 **Claude Code 辅助开发**：作者负责产品定位（"读书搭子"的对话体验）与逻辑框架，Claude Code 负责代码生成与调试协作，最终由作者逐段 review 与整合。这是一个「AI 协作编程」的实践项目。
