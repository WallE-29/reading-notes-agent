# 读书笔记助手（AI Reading-Notes Agent）

> 一个多模型 AI 读书笔记工具：每次阅读对话后，自动生成**可视化脑图**与**幕布大纲**两份结构化笔记。

## 功能特性

- 🤖 **多模型后端**：支持 Anthropic Claude / DeepSeek（OpenAI 兼容接口），运行时 `/model` 命令切换
- 🧠 **会话存档 & 记忆恢复**：每次对话自动存档，续读不断档
- 📝 **双格式笔记**：每次对话后自动生成两份笔记
  - `notes/<书名>_可视化脑图.md` → Mermaid mindmap，GitHub / Markdown 渲染器直接查看
  - `notes/<书名>_幕布导入版.md` → Tab 缩进层级大纲，可直接导入幕布 / Xmind 一键生成脑图
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
# 1. 克隆后，准备一个 API Key（Anthropic 或 DeepSeek）

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

- Python 3（标准库 + requests）
- Anthropic Claude API / DeepSeek API（OpenAI 兼容）
- Mermaid mindmap 语法

## 开发方式

本项目由 **Claude Code 辅助开发**：作者负责产品设计与逻辑框架，Claude Code 负责代码生成与调试协作，最终由作者逐段 review 与整合。这是一个「AI 协作编程」的实践项目。
