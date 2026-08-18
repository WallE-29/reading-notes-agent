#!/usr/bin/env python3
"""
读书笔记总结 Agent — 你博学、细腻、没有爹味的读书搭子。

每次对话后,后台自动生成两份笔记:
  - notes/<书名>_可视化脑图.md   → Mermaid mindmap,可在 GitHub/Markdown 渲染器中查看
  - notes/<书名>_幕布导入版.md   → Tab 缩进层级大纲,可直接导入幕布/Xmind 一键生成脑图

功能:
  - 多模型后端支持: Anthropic Claude / DeepSeek (OpenAI 兼容接口)
  - API Key 本地持久化
  - 书名 + 作者双字段录入,防同名书混淆
  - 智能作者背景检索
  - 会话存档 & 记忆恢复
  - 运行时切换模型 (/model 命令)

Usage:
    python agent.py                                    # 自动检测 Key 类型
    python agent.py --provider deepseek                # 强制使用 DeepSeek
    python agent.py --provider anthropic               # 强制使用 Anthropic
    python agent.py --api-key sk-xxx --model deepseek-chat
    python agent.py --reset-config
"""

from __future__ import annotations

import os
import re
import sys
import json
import time
import argparse
import textwrap
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Literal

# --- Windows UTF-8 ---
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

# ---------------------------------------------------------------------------
# ANSI
# ---------------------------------------------------------------------------
class Style:
    RESET   = "\033[0m"
    BOLD    = "\033[1m"
    DIM     = "\033[2m"
    CYAN    = "\033[36m"
    GREEN   = "\033[32m"
    YELLOW  = "\033[33m"
    MAGENTA = "\033[35m"
    RED     = "\033[31m"
    BLUE    = "\033[34m"

    @staticmethod
    def supports_color() -> bool:
        if os.name == "nt":
            return "ANSICON" in os.environ or "WT_SESSION" in os.environ
        return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()

if not Style.supports_color():
    for _a in dir(Style):
        if _a.isupper() and not _a.startswith("_"):
            setattr(Style, _a, "")

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
PROJECT_DIR    = Path(__file__).resolve().parent
NOTES_DIR      = PROJECT_DIR / "notes"
SESSIONS_DIR   = PROJECT_DIR / "sessions"
CONFIG_FILE    = PROJECT_DIR / ".reading_buddy_config.json"
KNOWN_FLAG     = "KNOWN"
UNKNOWN_FLAG   = "UNKNOWN"

# ---------------------------------------------------------------------------
# 后端信息表
# ---------------------------------------------------------------------------
PROVIDER_INFO = {
    "anthropic": {
        "name": "Anthropic Claude",
        "default_model": "claude-sonnet-4-6-20250701",
        "default_base_url": None,  # 用 SDK 默认
        "models": [
            ("claude-sonnet-4-6-20250701", "Sonnet 4.6 — 推荐, 均衡"),
            ("claude-opus-4-8",             "Opus 4.8 — 最强推理"),
            ("claude-haiku-4-5-20251001",   "Haiku 4.5 — 更快更便宜"),
        ],
    },
    "deepseek": {
        "name": "DeepSeek",
        "default_model": "deepseek-chat",
        "default_base_url": "https://api.deepseek.com",
        "models": [
            ("deepseek-chat",     "DeepSeek-V3 — 推荐, 综合能力强"),
            ("deepseek-reasoner", "DeepSeek-R1 — 推理增强"),
        ],
    },
}


def detect_provider(api_key: str) -> str:
    """根据 API Key 前缀自动检测后端。sk-ant- → anthropic; 其他 → deepseek。"""
    if api_key.startswith("sk-ant-"):
        return "anthropic"
    return "deepseek"


# ---------------------------------------------------------------------------
# 配置文件
# ---------------------------------------------------------------------------
DEFAULT_CONFIG = {
    "api_key": "",
    "provider": "auto",      # "auto" | "anthropic" | "deepseek"
    "model": "",             # 空 = 使用 provider 默认
    "mindmap_model": None,
    "base_url": None,
}


def load_config() -> dict:
    try:
        if CONFIG_FILE.exists():
            cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            return {**DEFAULT_CONFIG, **cfg}
    except Exception as e:
        print(f"  {Style.YELLOW}[!] 读取配置失败 ({e}){Style.RESET}")
    return dict(DEFAULT_CONFIG)


def save_config(config: dict) -> None:
    try:
        CONFIG_FILE.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"  {Style.RED}[!] 保存配置失败: {e}{Style.RESET}")


def obfuscate_key(api_key: str) -> str:
    if len(api_key) <= 16:
        return api_key[:4] + "****" + api_key[-4:]
    return api_key[:6] + "****" + api_key[-6:]


# ---------------------------------------------------------------------------
# 会话存档
# ---------------------------------------------------------------------------
def sanitize_filename(name: str) -> str:
    s = re.sub(r'[<>:"/\\|?*]', '', name)
    s = re.sub(r'\s+', ' ', s).strip()
    return s if s else "未命名"


def get_session_key(book_name: str, author: str = "") -> str:
    if author:
        return sanitize_filename(f"{book_name}__by__{author}")
    return sanitize_filename(book_name)


def get_session_path(book_name: str, author: str = "") -> Path:
    key = get_session_key(book_name, author)
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    return SESSIONS_DIR / f"{key}.json"


def load_session(book_name: str, author: str = "") -> Optional[dict]:
    p = get_session_path(book_name, author)
    try:
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    return None


def save_session(book_name: str, data: dict, author: str = "") -> None:
    p = get_session_path(book_name, author)
    try:
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"  {Style.RED}[!] 存档失败: {e}{Style.RESET}")


def list_all_sessions() -> list[dict]:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    sessions = []
    for f in sorted(SESSIONS_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            sessions.append({
                "book_name": d.get("book_name", f.stem),
                "author": d.get("author", ""),
                "filename": f.name,
                "message_count": len(d.get("messages", [])),
                "mode": d.get("mode", "unknown"),
                "updated_at": d.get("updated_at", ""),
                "model": d.get("model", "unknown"),
                "provider": d.get("provider", ""),
            })
        except Exception:
            pass
    return sessions


def get_mindmap_paths(book_name: str, author: str = "") -> tuple[Path, Path]:
    key = get_session_key(book_name, author)
    NOTES_DIR.mkdir(parents=True, exist_ok=True)
    return NOTES_DIR / f"{key}_可视化脑图.md", NOTES_DIR / f"{key}_幕布导入版.md"


def read_existing_note(fp: Path) -> str:
    try:
        return fp.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def format_book_label(book_name: str, author: str = "") -> str:
    if author:
        return f"《{book_name}》— {author}"
    return f"《{book_name}》"


def format_datetime(iso_string: str) -> str:
    if not iso_string:
        return "未知时间"
    try:
        dt = datetime.fromisoformat(iso_string)
        return dt.astimezone().strftime("%Y-%m-%d %H:%M")
    except Exception:
        return iso_string[:19] if len(iso_string) >= 19 else iso_string


# ---------------------------------------------------------------------------
# 提示词
# ---------------------------------------------------------------------------
PERSONA = textwrap.dedent("""\
    你是一个博学、细腻、毫无爹味的读书搭子。你的风格像深夜咖啡馆里那位读过很多书
    但从不好为人师的朋友——你不好卖弄,不居高临下,不评判读者的品味。你真正热爱的是
    "一个人如何与一本书相遇"这个过程本身。

    你的对话原则:
    - 像沙龙聊天,不像答辩。每次只抛出一个相互关联的问题,让人想接着聊下去。
    - 如果对方贴了大段原文,先真诚地回应一两个你注意到的细节,再自然过渡到下一个问题。
    - 永远不要用"你应该……""你必须……""这本书的核心思想是……"这类爹味句式。
      换成"我读的时候感觉……""有个细节我一直很好奇……""你会不会也觉得……"
    - 适当使用文学、哲学、历史等跨学科视角,但前提是自然关联,不生搬硬套。
    - 用中文交流,偶尔可以保留精彩原文的英文表达。""")

SYSTEM_PROMPT_KNOWN = PERSONA + "\n\n" + textwrap.dedent("""\
    ## 当前模式: 经典引导

    你读过《{book_name}》{author_line},而且读得比较深。你对这本书的:
    - 核心论点/主旨 - 章节结构和叙事逻辑 - 关键人物/概念/转折
    - 写作风格和修辞特点 - 在作者作品谱系中的位置
    - 所属领域内的学术/文化对话关系
    都有比较清晰的把握。

    ### 你的引导方式
    1. **开场**: 用 2-3 句话说明你读过这本书,然后抛出一个既不太宽泛也不太技术性的
       切入点问题。避免直接问"你觉得这本书怎么样?"这种 open question。

    2. **推进**: 每次回应都包含对用户分享的真诚回应 + 一个自然引出的追问
       + 偶尔分享你自己的感受或困惑 (不是标准答案,是你的个人体验)。

    3. **深度引导策略** (顺着对话自然选择):
       - 文本细读 / 结构透视 / 对话延伸 / 个人联结 / 反向思考 / 时代回响 / 作者脉络

    4. **边界**: 你不是维基百科,不是老师在出题。不要列清单,不要做总结陈词,
       不要给出"正确解读"。你是在和一个活人聊一本你们都读过的书。

    {memory_context}""")

SYSTEM_PROMPT_UNKNOWN = PERSONA + "\n\n" + textwrap.dedent("""\
    ## 当前模式: 盲盒盲读

    你**没有**读过《{book_name}》{author_line}。诚实是你的第一原则——
    你绝不会假装读过一本书。
    {author_context}

    ### 你的姿态
    你的角色从"引导者"转变为**"好奇的共读者"**。你展现的不是"我懂我来教",
    而是"哇这个听起来好有意思,我们一起来摸索"。

    ### 你的对话方式
    1. **开场**: 诚实承认你没读过,但表达真实的兴趣。
       {author_opening_hint}

    2. **推进**: 每次回应包含对用户分享的真诚反应 + 一个帮对方整理思路的问题
       + {author_question_hint}

    3. **导航策略**:
       - 贴了目录: 帮ta梳理结构
       - 贴了大段原文: 先回应语言/意象/逻辑,再问关注点
       - 卡住了: 帮ta一起想"那我们从另一个角度试试?"
       - 书不好: 好奇地问"哪里让你觉得不对劲?"
       - 鼓励用户用自己的话重述和提炼
       {author_nav_hint}

    4. **边界**: 你不是在审稿,不是在假装你懂。你是在陪一个人慢慢把一本书"吃透"。
       你的无知是真诚的,你的好奇也是真诚的。{author_boundary_note}

    {memory_context}""")

MINDMAP_GENERATION_PROMPT = textwrap.dedent("""\
    你是一个专业的读书笔记整理助手。根据以下对话历史,为《{book_name}》{author_context}生成两份
    结构化的读书笔记。

    ## 输出格式要求
    两个部分之间用 `=======SPLIT=======` 分隔:

    ### 第一部分: Mermaid Mindmap
    放在 ```mermaid 代码块内。使用 mindmap 语法。根节点为书名+作者。
    一级分支为章/部/主题,二级三级为具体概念/人物/论点。
    每个节点文字精简(≤15字)。

    ### 第二部分: 幕布/Xmind 导入版
    用 Markdown 层级标题和 Tab 缩进的 - 列表。顶层 # 书名 - 作者,
    二级 ## 章/部/主题,三级及以下用 - 列表 + Tab 缩进。

    ## 重要提示
    - 只基于对话中实际出现的内容构建
    - 这是对现有笔记的**更新**,保留已有结构,补充新内容
    - 作者相关信息也纳入笔记""")

# ---------------------------------------------------------------------------
# CLI 界面
# ---------------------------------------------------------------------------
def print_banner():
    print()
    print(f"{Style.CYAN}{Style.BOLD}╔══════════════════════════════════════╗{Style.RESET}")
    print(f"{Style.CYAN}{Style.BOLD}║     读书搭子 · 笔记总结 Agent       ║{Style.RESET}")
    print(f"{Style.CYAN}{Style.BOLD}╚══════════════════════════════════════╝{Style.RESET}")
    print()
    print(f"  {Style.DIM}博学 · 细腻 · 没有爹味{Style.RESET}")
    print(f"  {Style.DIM}自动更新 notes/ 脑图  |  会话存档 & 记忆恢复{Style.RESET}")
    print()


def print_status(msg: str, color: str = Style.DIM):
    print(f"  {color}[{msg}]{Style.RESET}")


def get_multiline_input(prompt: str) -> str:
    print()
    print(f"{Style.GREEN}{prompt}{Style.RESET}")
    print(f"  {Style.DIM}(可粘贴大段原文。输入完成后按回车,再按一次回车提交){Style.RESET}")
    print()
    lines, empty_count = [], 0
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line.strip() == "":
            empty_count += 1
            if empty_count >= 2:
                while lines and lines[-1] == "":
                    lines.pop()
                break
        else:
            empty_count = 0
        lines.append(line)
    return "\n".join(lines)


# ===================================================================
# 核心: 读书搭子 Agent (多后端)
# ===================================================================
class ReadingBuddyAgent:

    def __init__(
        self,
        api_key: str,
        provider: str = "auto",
        model: Optional[str] = None,
        mindmap_model: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        # --- 确定后端 ---
        if provider == "auto":
            provider = detect_provider(api_key)
        self.provider = provider
        info = PROVIDER_INFO[provider]

        # 模型
        self.model = model or info["default_model"]
        self.mindmap_model = mindmap_model or self.model

        # base_url
        if base_url:
            self.base_url = base_url
        else:
            self.base_url = info["default_base_url"]

        # --- 创建客户端 ---
        if provider == "anthropic":
            import anthropic
            kwargs = {"api_key": api_key}
            if self.base_url:
                kwargs["base_url"] = self.base_url
            self._client = anthropic.Anthropic(**kwargs)
        else:
            # OpenAI 兼容 (DeepSeek / 其他)
            import openai
            self._client = openai.OpenAI(
                api_key=api_key,
                base_url=self.base_url or "https://api.deepseek.com",
            )

        # 会话状态
        self.book_name: str = ""
        self.author: str = ""
        self.author_info: str = ""
        self.mode: Literal["known", "unknown"] = "unknown"
        self.messages: list[dict] = []
        self.system_prompt: str = ""

    # ------------------------------------------------------------------
    # 后端无关的 API 封装
    # ------------------------------------------------------------------

    def _api_create(
        self,
        system: str,
        messages: list[dict],
        max_tokens: int = 1024,
        temperature: float = 0.0,
        model: Optional[str] = None,
    ) -> str:
        """非流式 API 调用,返回完整文本。"""
        model = model or self.model

        if self.provider == "anthropic":
            resp = self._client.messages.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system,
                messages=messages,
            )
            blocks = [b.text for b in resp.content if hasattr(b, "text")]
            return "".join(blocks)
        else:
            # OpenAI 兼容: system 作为第一条消息
            full_msgs = [{"role": "system", "content": system}] + messages
            resp = self._client.chat.completions.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=full_msgs,
            )
            return resp.choices[0].message.content or ""

    def _api_stream(
        self,
        system: str,
        messages: list[dict],
        max_tokens: int = 4096,
        temperature: float = 0.9,
        model: Optional[str] = None,
    ):
        """流式 API 调用,生成器产出文本增量。"""
        model = model or self.model

        if self.provider == "anthropic":
            with self._client.messages.stream(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system,
                messages=messages,
            ) as stream:
                for delta in stream.text_stream:
                    yield delta
        else:
            full_msgs = [{"role": "system", "content": system}] + messages
            stream = self._client.chat.completions.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=full_msgs,
                stream=True,
            )
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content

    def _error_is_403(self, e: Exception) -> bool:
        s = str(e)
        return any(k in s for k in ("403", "Forbidden", "forbidden"))

    # ------------------------------------------------------------------
    # Step 1a: 判断是否了解这本书
    # ------------------------------------------------------------------
    def judge_book_knowledge(self, book_name: str, author: str = "") -> tuple[str, str]:
        author_hint = f"作者是 {author}" if author else ""
        prompt = textwrap.dedent(f"""\
            你是一个诚实的文学爱好者。请判断你是否真正读过《{book_name}》这本书。
            {author_hint}

            判断标准:
            - 能准确说出主要内容/章节结构/核心论点/关键情节 → KNOWN
            - 只知道作者名字/听过书名/了解大致领域但没读过 → UNKNOWN
            - 完全没听过或只有模糊印象 → UNKNOWN

            请以 JSON 格式回答:
            {{"verdict": "KNOWN 或 UNKNOWN", "reason": "简短说明 (1-2句话)"}}
            只输出 JSON。""")

        print_status("正在了解这本书……", Style.YELLOW)

        try:
            text = self._api_create(
                system="你是一个诚实的文学爱好者。只输出 JSON。",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=200,
                temperature=0,
            )
            text = re.sub(r'^```(?:json)?\s*', '', text.strip())
            text = re.sub(r'\s*```$', '', text)
            data = json.loads(text)
            verdict = data.get("verdict", "").upper()
            reason = data.get("reason", "无法判断")
            return ("unknown", reason) if UNKNOWN_FLAG in verdict else ("known", reason)
        except Exception as e:
            if self._error_is_403(e):
                print_status("⚠️ API 访问被拒 (403) — 检查 Key 和模型权限。暂用盲读模式。", Style.YELLOW)
            else:
                print_status(f"判断出错 ({e}),默认进入盲盒盲读模式", Style.YELLOW)
            return "unknown", "AI 判断时遇到技术问题,先盲读吧"

    # ------------------------------------------------------------------
    # Step 1b: 了解作者背景
    # ------------------------------------------------------------------
    def judge_author_knowledge(self, author: str) -> str:
        if not author:
            return ""
        prompt = textwrap.dedent(f"""\
            你是一个诚实的文学爱好者。请判断你是否了解「{author}」这位作者。

            判断标准:
            - 能说出代表作/写作风格/所属流派/文学地位/创作脉络 → KNOWN
            - 只听说过名字但不了解 → UNKNOWN

            请以 JSON 格式回答:
            {{"verdict": "KNOWN 或 UNKNOWN", "author_info": "简要介绍 (2-4句话: 代表作、写作风格特色、文学地位)", "reason": "判断依据"}}
            只输出 JSON。""")

        print_status(f"正在了解 {author} 的背景……", Style.YELLOW)

        try:
            text = self._api_create(
                system="你是一个诚实的文学爱好者。只输出 JSON。",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=400,
                temperature=0,
            )
            text = re.sub(r'^```(?:json)?\s*', '', text.strip())
            text = re.sub(r'\s*```$', '', text)
            data = json.loads(text)
            if KNOWN_FLAG in data.get("verdict", "").upper():
                return data.get("author_info", "").strip()
            return ""
        except Exception as e:
            if self._error_is_403(e):
                print_status("⚠️ 作者背景查询被拒 (403),按普通盲读模式进行", Style.YELLOW)
            return ""

    # ------------------------------------------------------------------
    # 作者上下文构建
    # ------------------------------------------------------------------
    def _build_author_context_for_prompt(self) -> dict[str, str]:
        ctx: dict[str, str] = {
            "author_line": f"(作者: {self.author})" if self.author else "",
            "author_context": "",
            "author_opening_hint": "",
            "author_question_hint": "偶尔把你联想到的其他书/电影/思想说出来,但不要喧宾夺主。",
            "author_nav_hint": "",
            "author_boundary_note": (
                "如果用户问你对某段的理解,你可以说\"我没读过上下文,"
                "但从你贴的这段来看……\""
            ),
        }
        if self.author_info:
            ctx["author_context"] = textwrap.dedent(f"""
                ## 作者背景 (你的知识储备)
                虽然你没读过《{self.book_name}》,但你对「{self.author}」有相当的了解:
                {self.author_info}
                这层了解是你的宝贵资产——可以把读者分享的内容和作者的风格、
                创作脉络自然联系。但不要喧宾夺主地大段介绍作者,点到即止。
                作者背景是调味料,不是主菜。""")
            ctx["author_opening_hint"] = (
                f"由于你了解这位作者,开场时可以自然地提及你对{self.author}的了解。"
            )
            ctx["author_question_hint"] = (
                f"偶尔把读者分享的内容和{self.author}的创作风格、其他作品或所处"
                "文学传统联系起来,提出有纵深的问题。"
            )
            ctx["author_nav_hint"] = (
                f"- **作者视角**: 可以聊聊{self.author}的写作动机、创作背景、"
                "这本书在ta生涯中的位置等"
            )
            ctx["author_boundary_note"] = (
                f"你对{self.author}有所了解,但别把这当成炫耀知识的场合。"
                "作者背景只是帮你提出更好问题的工具。"
            )
        return ctx

    # ------------------------------------------------------------------
    # 记忆上下文
    # ------------------------------------------------------------------
    def _build_memory_context(self) -> str:
        if not self.messages:
            return ""
        lines = [
            "## 历史对话记忆", "",
            "以下是本次会话之前你和读者已经聊过的内容。请自然延续,不要当作全新对话从头开始。",
            "", "### 之前的对话记录:", "",
        ]
        for msg in self.messages[-60:]:
            role = "读者" if msg["role"] == "user" else "读书搭子(你)"
            c = msg["content"]
            if len(c) > 800:
                c = c[:800] + "…(省略)…"
            lines.append(f"【{role}】: {c}")
            lines.append("")
        lines.append("---")
        lines.append("以上就是之前的对话记录。请从现在开始继续聊。")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Step 2: 启动会话
    # ------------------------------------------------------------------
    def start_session(self, book_name: str, author: str = "", resume: bool = False):
        self.book_name = book_name.strip()
        self.author = author.strip()
        label = format_book_label(self.book_name, self.author)

        if resume:
            print()
            print(f"  {Style.BLUE}[📖] 恢复之前的会话: {label}{Style.RESET}")
            updated = format_datetime(getattr(self, '_session_updated_at', ''))
            print(f"  {Style.DIM}(已有 {len(self.messages)} 条对话,上次更新: {updated}){Style.RESET}")

            memory_ctx = self._build_memory_context()
            a_ctx = self._build_author_context_for_prompt()

            if self.mode == "known":
                self.system_prompt = SYSTEM_PROMPT_KNOWN.format(
                    book_name=self.book_name,
                    author_line=a_ctx["author_line"],
                    memory_context=memory_ctx,
                )
            else:
                self.system_prompt = SYSTEM_PROMPT_UNKNOWN.format(
                    book_name=self.book_name,
                    author_line=a_ctx["author_line"],
                    author_context=a_ctx["author_context"],
                    author_opening_hint=a_ctx["author_opening_hint"],
                    author_question_hint=a_ctx["author_question_hint"],
                    author_nav_hint=a_ctx["author_nav_hint"],
                    author_boundary_note=a_ctx["author_boundary_note"],
                    memory_context=memory_ctx,
                )

            print()
            print(f"{Style.MAGENTA}{Style.BOLD}[读书搭子]{Style.RESET}")
            print()
            cont = (
                f"我们正在继续聊{label}。上面是之前的对话记录。"
                "请自然地衔接,不需要重新自我介绍,直接接着聊就好。"
            )
            self._stream_and_collect(
                system=self.system_prompt,
                messages=self.messages + [{"role": "user", "content": cont}],
                save_to_history=True,
            )
        else:
            # 全新会话
            mode, reason = self.judge_book_knowledge(self.book_name, self.author)

            if mode == "unknown" and self.author:
                time.sleep(0.5)
                info = self.judge_author_knowledge(self.author)
                if info:
                    self.author_info = info
                    print()
                    print(f"  {Style.BLUE}[📝] 虽然没读过这本书,但我了解 {self.author} 的创作背景{Style.RESET}")
                    print(f"  {Style.DIM}({info[:100]}……){Style.RESET}")

            a_ctx = self._build_author_context_for_prompt()

            if mode == "known":
                self.mode = "known"
                self.system_prompt = SYSTEM_PROMPT_KNOWN.format(
                    book_name=self.book_name,
                    author_line=a_ctx["author_line"],
                    memory_context="",
                )
                print()
                print(f"  {Style.GREEN}[OK] 我读过这本书!{Style.RESET}")
                print(f"  {Style.DIM}({reason}){Style.RESET}")
            else:
                self.mode = "unknown"
                self.system_prompt = SYSTEM_PROMPT_UNKNOWN.format(
                    book_name=self.book_name,
                    author_line=a_ctx["author_line"],
                    author_context=a_ctx["author_context"],
                    author_opening_hint=a_ctx["author_opening_hint"],
                    author_question_hint=a_ctx["author_question_hint"],
                    author_nav_hint=a_ctx["author_nav_hint"],
                    author_boundary_note=a_ctx["author_boundary_note"],
                    memory_context="",
                )
                print()
                if self.author_info:
                    print(f"  {Style.YELLOW}[?] 这本书我没读过——但我知道 {self.author} 的创作脉络,可以帮上忙!{Style.RESET}")
                else:
                    print(f"  {Style.YELLOW}[?] 说实话我没读过这本——但正好,一起摸索吧!{Style.RESET}")
                print(f"  {Style.DIM}({reason}){Style.RESET}")

            print()
            print(f"{Style.MAGENTA}{Style.BOLD}[读书搭子]{Style.RESET}")
            print()
            opening = f"我最近在读{label}。请开始我们的对话吧。" if self.author else f"我最近在读《{self.book_name}》。请开始我们的对话吧。"
            self._stream_and_collect(
                system=self.system_prompt,
                messages=[{"role": "user", "content": opening}],
                save_to_history=True,
            )

        self._do_save_session()

    # ------------------------------------------------------------------
    # 对话循环
    # ------------------------------------------------------------------
    def chat_turn(self, user_input: str):
        s = user_input.strip()
        if s.lower() in ("/quit", "/exit", "/q", "退出"):
            return "quit"
        if s.lower().startswith("/model"):
            self._cmd_model(s)
            return "command_handled"
        if s.lower().startswith("/save"):
            self._cmd_save()
            return "command_handled"
        if s.lower() in ("/history", "/hist"):
            self._cmd_history()
            return "command_handled"
        if s.lower() in ("/author", "/author-info"):
            self._cmd_author_info()
            return "command_handled"
        if s.lower() == "/help":
            self._cmd_help()
            return "command_handled"

        self.messages.append({"role": "user", "content": user_input})
        print()
        print(f"{Style.MAGENTA}{Style.BOLD}[读书搭子]{Style.RESET}")
        print()
        ai_resp = self._stream_and_collect(
            system=self.system_prompt,
            messages=self.messages,
            save_to_history=True,
        )
        self._do_save_session()
        self._update_mindmaps(ai_resp)
        return "continue"

    # ------------------------------------------------------------------
    # 流式收集
    # ------------------------------------------------------------------
    def _stream_and_collect(self, system, messages, save_to_history=False) -> str:
        full = ""
        try:
            for delta in self._api_stream(system=system, messages=messages):
                print(delta, end="", flush=True)
                full += delta
        except Exception as e:
            if self._error_is_403(e):
                print(f"\n  {Style.RED}╔══════════════════════════════════════╗{Style.RESET}")
                print(f"  {Style.RED}║  API 访问被拒绝 (403 Forbidden)      ║{Style.RESET}")
                print(f"  {Style.RED}╚══════════════════════════════════════╝{Style.RESET}")
                print(f"  {Style.YELLOW}可能原因:{Style.RESET}")
                print(f"  {Style.DIM}  1. API Key 无效/过期 → python agent.py --reset-config{Style.RESET}")
                print(f"  {Style.DIM}  2. 模型权限不足 → /model 换一个模型试试{Style.RESET}")
                print(f"  {Style.DIM}  3. 余额/额度用尽{Style.RESET}")
                print(f"  {Style.DIM}  4. 当前后端: {PROVIDER_INFO[self.provider]['name']}, base_url: {self.base_url or '默认'}{Style.RESET}")
                print(f"  {Style.RED}原始错误: {e}{Style.RESET}\n")
            else:
                print(f"\n  {Style.RED}[!] 流式输出出错: {e}{Style.RESET}\n")
            full = f"(AI 回复生成失败: {e})"
        print()
        if save_to_history and full:
            self.messages.append({"role": "assistant", "content": full})
        return full

    # ------------------------------------------------------------------
    # 脑图更新
    # ------------------------------------------------------------------
    def _update_mindmaps(self, _latest_ai_response: str):
        mp, mubu = get_mindmap_paths(self.book_name, self.author)
        existing_mp = read_existing_note(mp)
        existing_mb = read_existing_note(mubu)
        history = self._build_history_summary(max_turns=20)
        author_ctx = f"作者: {self.author}" if self.author else ""

        user_content = textwrap.dedent(f"""\
            以下是关于{format_book_label(self.book_name, self.author)}的读书对话记录:
            {history}
            ---
            {"现有 Mermaid 脑图 (请在其基础上更新):" if existing_mp else "(尚无现有脑图,请从零构建)"}
            {existing_mp if existing_mp else ""}
            ---
            {"现有幕布大纲 (请在其基础上更新):" if existing_mb else "(尚无现有大纲,请从零构建)"}
            {existing_mb if existing_mb else ""}
            ---
            请根据以上对话,生成/更新两份结构化读书笔记。严格按格式输出。
            记住: 这是更新而非替换——保留已有的结构,补充新讨论中发现的内容。""")

        print_status("后台更新脑图文件中……", Style.DIM)
        try:
            full = self._api_create(
                system=MINDMAP_GENERATION_PROMPT.format(book_name=self.book_name, author_context=author_ctx),
                messages=[{"role": "user", "content": user_content}],
                max_tokens=8192,
                temperature=0.3,
                model=self.mindmap_model,
            )
            mc, mb = self._parse_mindmap_output(full)
            if mc:
                mp.write_text(mc, encoding="utf-8")
                print_status(f"[OK] 可视化脑图已更新 -> {mp}", Style.GREEN)
            if mb:
                mubu.write_text(mb, encoding="utf-8")
                print_status(f"[OK] 幕布导入版已更新 -> {mubu}", Style.GREEN)
        except Exception as e:
            if self._error_is_403(e):
                print_status("[!] 脑图更新被拒 (403)。试试 /model 切换模型后再聊一轮。", Style.YELLOW)
            else:
                print_status(f"[!] 脑图更新失败 (不影响对话): {e}", Style.RED)

    def _parse_mindmap_output(self, raw: str) -> tuple[str, str]:
        parts = re.split(r'=+\s*SPLIT\s*=+', raw, maxsplit=1)
        mc, mb = "", ""
        if len(parts) >= 1:
            m = re.search(r'```mermaid\s*\n(.*?)```', parts[0], re.DOTALL)
            if m:
                mc = "```mermaid\n" + m.group(1).strip() + "\n```"
            elif parts[0].strip():
                mc = "```mermaid\n" + parts[0].strip() + "\n```"
        if len(parts) >= 2:
            mb = parts[1].strip()
        return mc, mb

    def _build_history_summary(self, max_turns: int = 20) -> str:
        recent = self.messages[-(max_turns * 2):]
        lines = []
        for m in recent:
            role = "读者" if m["role"] == "user" else "读书搭子"
            c = m["content"]
            if len(c) > 1500:
                c = c[:1500] + "\n…(以下省略)…"
            lines.append(f"【{role}】: {c}")
            lines.append("")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 命令
    # ------------------------------------------------------------------
    def _cmd_model(self, raw_input: str):
        info = PROVIDER_INFO[self.provider]
        parts = raw_input.strip().split(maxsplit=1)
        if len(parts) == 1:
            print()
            print(f"  {Style.BLUE}当前后端: {Style.BOLD}{info['name']}{Style.RESET}")
            print(f"  {Style.BLUE}当前对话模型: {Style.BOLD}{self.model}{Style.RESET}")
            if self.mindmap_model:
                print(f"  {Style.BLUE}当前脑图模型: {Style.BOLD}{self.mindmap_model}{Style.RESET}")
            else:
                print(f"  {Style.DIM}(脑图模型与对话模型相同){Style.RESET}")
            print()
            print(f"  {Style.DIM}可用模型:{Style.RESET}")
            for mid, desc in info["models"]:
                marker = " ← 当前" if mid == self.model else ""
                print(f"     {Style.DIM}{mid}  ({desc}){marker}{Style.RESET}")
            print()
            print(f"  {Style.DIM}切换示例: /model {info['models'][0][0]}{Style.RESET}")
            print()
        else:
            new_model = parts[1].strip()
            valid_models = [m[0] for m in info["models"]]
            if new_model not in valid_models:
                print(f"  {Style.YELLOW}[!] 未知模型 '{new_model}', 可用: {', '.join(valid_models)}{Style.RESET}")
                print()
                return
            old = self.model
            self.model = new_model
            print()
            print(f"  {Style.GREEN}[OK] 模型已切换:{Style.RESET}")
            print(f"  {Style.DIM}  {old}{Style.RESET}")
            print(f"  {Style.DIM}  → {Style.BOLD}{self.model}{Style.RESET}")
            print()
            cfg = load_config()
            cfg["model"] = self.model
            save_config(cfg)
            self._do_save_session()

    def _cmd_save(self):
        self._do_save_session()
        label = format_book_label(self.book_name, self.author)
        mp, mubu = get_mindmap_paths(self.book_name, self.author)
        print()
        print(f"  {Style.GREEN}[OK] 会话已手动存档{Style.RESET}")
        print(f"  {Style.DIM}  书名: {label}{Style.RESET}")
        print(f"  {Style.DIM}  存档: {get_session_path(self.book_name, self.author)}{Style.RESET}")
        print(f"  {Style.DIM}  脑图: {mp}{Style.RESET}")
        print(f"  {Style.DIM}  幕布: {mubu}{Style.RESET}")
        print()

    def _cmd_author_info(self):
        print()
        if not self.author:
            print(f"  {Style.DIM}本次会话未录入作者信息{Style.RESET}")
        elif self.author_info:
            print(f"  {Style.BLUE}{Style.BOLD}关于 {self.author}:{Style.RESET}")
            print()
            for line in textwrap.wrap(self.author_info, width=60):
                print(f"  {Style.DIM}{line}{Style.RESET}")
        else:
            print(f"  {Style.DIM}关于 {self.author} 没有额外的背景信息{Style.RESET}")
        print()

    def _cmd_history(self):
        sessions = list_all_sessions()
        print()
        if not sessions:
            print(f"  {Style.DIM}暂无存档的会话记录{Style.RESET}")
            print()
            return
        print(f"  {Style.BLUE}{Style.BOLD}📚 存档的读书会话 ({len(sessions)} 本){Style.RESET}")
        print()
        for i, s in enumerate(sessions, 1):
            icon = "📖" if s["mode"] == "known" else "📦"
            label = format_book_label(s["book_name"], s.get("author", ""))
            cur_label = format_book_label(self.book_name, self.author)
            marker = " ← 当前" if label == cur_label else ""
            print(f"  {Style.CYAN}{i}.{Style.RESET} {icon} {Style.BOLD}{label}{Style.RESET}{marker}")
            print(f"     {Style.DIM}{s['message_count']} 条 · {format_datetime(s['updated_at'])} · {s.get('provider','')} · {s['model']}{Style.RESET}")
        print()

    def _cmd_help(self):
        info = PROVIDER_INFO[self.provider]
        print()
        print(f"  {Style.BLUE}{Style.BOLD}可用命令 ({info['name']} 后端):{Style.RESET}")
        print()
        print(f"  {Style.CYAN}/model [模型名]{Style.RESET}  — 查看或切换模型")
        print(f"  {Style.CYAN}/author{Style.RESET}          — 查看作者背景信息")
        print(f"  {Style.CYAN}/save{Style.RESET}            — 手动存档")
        print(f"  {Style.CYAN}/history{Style.RESET}        — 查看所有存档会话")
        print(f"  {Style.CYAN}/quit, /exit, /q{Style.RESET} — 退出")
        print(f"  {Style.CYAN}/help{Style.RESET}           — 帮助")
        print()

    # ------------------------------------------------------------------
    # 存档
    # ------------------------------------------------------------------
    def _do_save_session(self):
        data = {
            "book_name": self.book_name,
            "author": self.author,
            "author_info": self.author_info,
            "mode": self.mode,
            "provider": self.provider,
            "model": self.model,
            "mindmap_model": self.mindmap_model,
            "base_url": self.base_url,
            "created_at": getattr(self, "_session_created_at", datetime.now(timezone.utc).isoformat()),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "messages": self.messages,
        }
        if not hasattr(self, "_session_created_at"):
            self._session_created_at = data["created_at"]
        save_session(self.book_name, data, self.author)
        self._session_updated_at = data["updated_at"]

    # ------------------------------------------------------------------
    # 主循环
    # ------------------------------------------------------------------
    def run(self):
        print_banner()

        book_name = input(f"  {Style.CYAN}请输入你在读的书名:{Style.RESET} ").strip()
        while not book_name:
            print(f"  {Style.YELLOW}书名不能为空,请输入书名~{Style.RESET}")
            book_name = input(f"  {Style.CYAN}请输入你在读的书名:{Style.RESET} ").strip()

        print()
        author = input(f"  {Style.CYAN}请输入作者名 (可选,按回车跳过):{Style.RESET} ").strip()
        if author:
            print(f"  {Style.DIM}(已记录作者: {author}){Style.RESET}")

        previous = load_session(book_name, author)

        if previous:
            prev_msg = previous.get("messages", [])
            prev_mode = previous.get("mode", "unknown")
            prev_updated = previous.get("updated_at", "")
            prev_model = previous.get("model", self.model)
            prev_author = previous.get("author", "")
            prev_author_info = previous.get("author_info", "")
            prev_provider = previous.get("provider", "")
            prev_count = len(prev_msg)

            label = format_book_label(book_name, prev_author or author)

            print()
            print(f"  {Style.BLUE}[📖] 发现之前的会话存档!{Style.RESET}")
            print(f"  {Style.DIM}  书名: {label}{Style.RESET}")
            print(f"  {Style.DIM}  对话数: {prev_count} 条{Style.RESET}")
            print(f"  {Style.DIM}  上次更新: {format_datetime(prev_updated)}{Style.RESET}")
            print(f"  {Style.DIM}  模式: {'经典引导' if prev_mode == 'known' else '盲盒盲读'}{Style.RESET}")
            print(f"  {Style.DIM}  后端: {prev_provider} · 模型: {prev_model}{Style.RESET}")
            print()

            print(f"  {Style.CYAN}请选择:{Style.RESET}")
            print(f"  {Style.GREEN}[1]{Style.RESET} 继续之前的对话")
            print(f"  {Style.YELLOW}[2]{Style.RESET} 重新开始")
            print(f"  {Style.DIM}[3]{Style.RESET} 查看存档列表")
            print()
            choice = input(f"  {Style.CYAN}输入选项 (1/2/3, 默认 1):{Style.RESET} ").strip()

            if choice == "3":
                self._cmd_history()
                print()
                choice = input(f"  {Style.CYAN}输入选项 (1=继续 / 2=重新开始, 默认 1):{Style.RESET} ").strip() or "1"

            if choice == "2":
                print()
                print(f"  {Style.YELLOW}将开启全新会话{Style.RESET}")
                self.messages = []
                self.author = prev_author or author
                self._session_created_at = datetime.now(timezone.utc).isoformat()
                self.start_session(book_name, self.author, resume=False)
            else:
                self.book_name = book_name
                self.author = prev_author or author
                self.mode = prev_mode
                self.author_info = prev_author_info
                self.model = prev_model if prev_model else self.model
                self.mindmap_model = previous.get("mindmap_model") or self.model
                self.base_url = previous.get("base_url") or self.base_url
                self.messages = prev_msg
                self._session_created_at = previous.get("created_at", datetime.now(timezone.utc).isoformat())
                self._session_updated_at = prev_updated
                self.start_session(book_name, self.author, resume=True)
        else:
            self.author = author
            self._session_created_at = datetime.now(timezone.utc).isoformat()
            self.start_session(book_name, self.author, resume=False)

        print()
        info = PROVIDER_INFO[self.provider]
        print(f"  {Style.DIM}━━━  后端: {info['name']} | 每次回答后自动存档 & 更新脑图  ━━━{Style.RESET}")
        print(f"  {Style.DIM}  命令: /model 切换模型 | /author 作者背景 | /save 手动存档 | /history 历史 | /quit 退出{Style.RESET}")
        print()

        turn_count = (len(self.messages) // 2) + 1
        while True:
            user_input = get_multiline_input(f">> 第 {turn_count} 轮 - 你想分享/讨论什么?")
            if not user_input.strip():
                continue
            result = self.chat_turn(user_input)
            if result == "quit":
                label = format_book_label(self.book_name, self.author)
                print()
                print(f"  {Style.CYAN}今天就聊到这儿吧。notes/ 里有笔记,下次继续!{Style.RESET}")
                print(f"  {Style.DIM}会话已自动存档,下次打开{label}可以接着聊~{Style.RESET}")
                print()
                break
            elif result == "continue":
                turn_count += 1

        label = format_book_label(self.book_name, self.author)
        mp, mubu = get_mindmap_paths(self.book_name, self.author)
        sp = get_session_path(self.book_name, self.author)
        print(f"  {Style.DIM}本次会话总结:{Style.RESET}")
        print(f"     {Style.GREEN}[存档] 会话记录:{Style.RESET} {sp}")
        print(f"     {Style.GREEN}[脑图] 可视化脑图:{Style.RESET} {mp}")
        print(f"     {Style.GREEN}[大纲] 幕布导入版:{Style.RESET} {mubu}")
        print()


# ===================================================================
# CLI 入口
# ===================================================================
def main():
    parser = argparse.ArgumentParser(
        description="读书笔记总结 Agent — 多后端支持 (Anthropic / DeepSeek)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            示例:
              python agent.py                                    # 自动检测 Key 类型
              python agent.py --provider deepseek                # 使用 DeepSeek
              python agent.py --provider anthropic               # 使用 Anthropic
              python agent.py --api-key sk-xxx --model deepseek-chat
              python agent.py --reset-config
              python agent.py --list-sessions
        """),
    )
    parser.add_argument("--api-key", "-k", default=None, help="API Key")
    parser.add_argument("--provider", "-p", default=None, choices=["anthropic", "deepseek", "auto"], help="后端 (默认: auto 自动检测)")
    parser.add_argument("--model", "-m", default=None, help="对话模型")
    parser.add_argument("--mindmap-model", default=None, help="脑图模型")
    parser.add_argument("--base-url", default=None, help="API 地址 (默认根据后端自动设置)")
    parser.add_argument("--reset-config", action="store_true", help="重置配置文件")
    parser.add_argument("--list-sessions", action="store_true", help="列出存档会话")
    args = parser.parse_args()

    if args.reset_config:
        if CONFIG_FILE.exists():
            CONFIG_FILE.unlink()
            print(f"  {Style.GREEN}[OK] 配置文件已重置{Style.RESET}")
        else:
            print(f"  {Style.DIM}配置文件不存在{Style.RESET}")
        return

    if args.list_sessions:
        sessions = list_all_sessions()
        if sessions:
            print()
            print(f"  {Style.BLUE}{Style.BOLD}📚 存档的读书会话 ({len(sessions)} 本){Style.RESET}")
            print()
            for i, s in enumerate(sessions, 1):
                icon = "📖" if s["mode"] == "known" else "📦"
                label = format_book_label(s["book_name"], s.get("author", ""))
                print(f"  {Style.CYAN}{i}.{Style.RESET} {icon} {Style.BOLD}{label}{Style.RESET}")
                print(f"     {Style.DIM}{s['message_count']} 条 · {format_datetime(s['updated_at'])} · {s.get('provider','')} · {s['model']}{Style.RESET}")
            print()
        else:
            print(f"  {Style.DIM}暂无存档{Style.RESET}")
        return

    # --- 加载/合并配置 ---
    config = load_config()

    # API Key
    api_key = args.api_key or config.get("api_key") or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print()
        print(f"  {Style.YELLOW}[!] 首次使用需要设置 API Key{Style.RESET}")
        print(f"  {Style.DIM}  Anthropic: https://console.anthropic.com/{Style.RESET}")
        print(f"  {Style.DIM}  DeepSeek:  https://platform.deepseek.com/{Style.RESET}")
        print()
        api_key = input(f"  {Style.CYAN}请粘贴你的 API Key:{Style.RESET} ").strip()
        if not api_key:
            print(f"  {Style.RED}[ERROR] 需要 API Key{Style.RESET}")
            sys.exit(1)
        config["api_key"] = api_key
        save_config(config)
        print(f"  {Style.GREEN}[OK] API Key 已保存{Style.RESET}")

    if args.api_key and args.api_key != config.get("api_key"):
        config["api_key"] = args.api_key
        save_config(config)
        print(f"  {Style.GREEN}[OK] API Key 已更新{Style.RESET}")

    # Provider
    provider = args.provider or config.get("provider") or "auto"
    if provider == "auto":
        provider = detect_provider(api_key)
    if args.provider and args.provider != config.get("provider"):
        config["provider"] = args.provider
        save_config(config)

    pinfo = PROVIDER_INFO[provider]

    # Model
    model = args.model or config.get("model") or pinfo["default_model"]
    mindmap_model = args.mindmap_model or config.get("mindmap_model") or model

    # Base URL
    base_url = args.base_url or config.get("base_url") or pinfo["default_base_url"]

    if args.model and args.model != config.get("model"):
        config["model"] = args.model
        save_config(config)
    if args.base_url and args.base_url != config.get("base_url"):
        config["base_url"] = args.base_url
        save_config(config)
    if not config.get("provider") or config["provider"] == "auto":
        config["provider"] = provider
        save_config(config)

    # --- 显示配置 ---
    print()
    print(f"  {Style.DIM}配置:{Style.RESET}")
    print(f"  {Style.DIM}  后端: {pinfo['name']}{Style.RESET}")
    if config.get("api_key"):
        print(f"  {Style.DIM}  API Key: {obfuscate_key(config['api_key'])} (已保存){Style.RESET}")
    print(f"  {Style.DIM}  对话模型: {model}{Style.RESET}")
    if args.mindmap_model:
        print(f"  {Style.DIM}  脑图模型: {mindmap_model}{Style.RESET}")
    if base_url:
        print(f"  {Style.DIM}  API: {base_url}{Style.RESET}")
    print()

    # --- 检查依赖 ---
    if provider == "anthropic":
        try:
            import anthropic  # noqa
        except ImportError:
            print(f"  {Style.RED}[ERROR] 需要 anthropic SDK: pip install anthropic{Style.RESET}")
            sys.exit(1)
    else:
        try:
            import openai  # noqa
        except ImportError:
            print(f"  {Style.RED}[ERROR] 需要 openai SDK: pip install openai{Style.RESET}")
            sys.exit(1)

    # --- 启动 ---
    agent = ReadingBuddyAgent(
        api_key=api_key,
        provider=provider,
        model=model,
        mindmap_model=mindmap_model,
        base_url=base_url,
    )
    try:
        agent.run()
    except KeyboardInterrupt:
        print()
        print(f"  {Style.CYAN}已中断。会话已自动存档~{Style.RESET}")
        print()
    except Exception as e:
        print(f"  {Style.RED}[ERROR] 运行出错: {e}{Style.RESET}")
        raise


if __name__ == "__main__":
    main()
