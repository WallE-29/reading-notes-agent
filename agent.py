#!/usr/bin/env python3
"""
读书笔记总结 Agent — 你博学、细腻、没有爹味的读书搭子。

每次对话后,后台自动生成两份笔记:
  - notes/<书名>_可视化脑图.md   → Mermaid mindmap,可在 GitHub/Markdown 渲染器中查看
  - notes/<书名>_幕布导入版.md   → Tab 缩进层级大纲,可直接导入幕布/Xmind 一键生成脑图

功能:
  - 通用模型接入: 任何 OpenAI 兼容服务 (DeepSeek / OpenAI / 智谱GLM / Kimi / 通义 / 本地Ollama 等),
    另支持 Anthropic 原生协议
  - API Key 本地持久化
  - 书名 + 作者双字段录入,防同名书混淆
  - 智能作者背景检索
  - 会话存档 & 记忆恢复
  - 运行时切换模型 (/model 命令) 与切换服务 (/config 命令: base_url / api_key / 模型)
  - 跨书记忆 memory.md: 会话结束时提炼读书偏好,追加写入,所有书共享
    (Ctrl+C / 关窗口 / 崩溃等异常退出后,下次启动自动补做提炼,记忆不丢)
  - 读者画像 profile.md: 首次启动问答建档,之后以文艺笔触持续更新

配置优先级: 环境变量 > config.json > .reading_buddy_config.json (老版本兼容)

Usage:
    python agent.py                                    # 配置来自环境变量 / config.json
    python agent.py --protocol anthropic               # 强制 Anthropic 原生协议
    python agent.py --api-key sk-xxx --base-url https://api.deepseek.com --model deepseek-chat
    python agent.py --reset-config
    python agent.py --list-sessions

环境变量 (最高优先级):
    OPENAI_API_KEY    (+可选 OPENAI_BASE_URL / OPENAI_MODEL)  → 任何 OpenAI 兼容服务
    DEEPSEEK_API_KEY                                  → DeepSeek (base_url 自动填)
    ANTHROPIC_API_KEY (+可选 ANTHROPIC_MODEL)          → Anthropic 原生
"""

from __future__ import annotations

import os
import re
import sys
import json
import time
import argparse
import textwrap
import getpass
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urlparse
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
CONFIG_FILE        = PROJECT_DIR / "config.json"                    # 现行配置文件
LEGACY_CONFIG_FILE = PROJECT_DIR / ".reading_buddy_config.json"     # 老配置, 兼容只读
KNOWN_FLAG     = "KNOWN"
UNKNOWN_FLAG   = "UNKNOWN"

# ---------------------------------------------------------------------------
# 协议与常见服务注册表
# ---------------------------------------------------------------------------
# 协议分两类:
#   openai_compatible — 走 openai 库, 传 base_url + model, 通吃绝大多数服务
#   anthropic         — Claude 原生 SDK (官方格式特殊, 单独保留)
PROTOCOL_LABELS = {
    "openai_compatible": "OpenAI 兼容",
    "anthropic":         "Anthropic 原生",
}

# 常见 OpenAI 兼容服务: 用于无配置引导、默认模型与 /model 建议;
# 表外的服务只要填 api_key + base_url + model 三要素即可接入
KNOWN_SERVICES = {
    "deepseek": {
        "name": "DeepSeek",
        "protocol": "openai_compatible",
        "base_url": "https://api.deepseek.com",
        "default_model": "deepseek-chat",
        "hosts": ["api.deepseek.com"],
        "models": [
            ("deepseek-chat",     "DeepSeek-V3 — 推荐, 综合能力强"),
            ("deepseek-reasoner", "DeepSeek-R1 — 推理增强"),
        ],
    },
    "openai": {
        "name": "OpenAI",
        "protocol": "openai_compatible",
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o",
        "hosts": ["api.openai.com"],
        "models": [
            ("gpt-4o",      "GPT-4o — 均衡之选"),
            ("gpt-4o-mini", "GPT-4o mini — 更快更便宜"),
        ],
    },
    "zhipu": {
        "name": "智谱 GLM",
        "protocol": "openai_compatible",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "default_model": None,   # 模型名迭代快, 请按官方文档填写
        "hosts": ["open.bigmodel.cn"],
        "models": [
            ("glm-4.5",     "GLM-4.5 — 旗舰"),
            ("glm-4.5-air", "GLM-4.5-Air — 轻量"),
            ("glm-4-flash", "GLM-4-Flash — 免费"),
        ],
    },
    "kimi": {
        "name": "Kimi",
        "protocol": "openai_compatible",
        "base_url": "https://api.moonshot.cn/v1",
        "default_model": None,
        "hosts": ["api.moonshot.cn"],
        "models": [
            ("kimi-k2-0905-preview", "Kimi K2 — 旗舰"),
            ("moonshot-v1-128k",     "Moonshot V1 — 长上下文"),
        ],
    },
    "qwen": {
        "name": "通义千问",
        "protocol": "openai_compatible",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "default_model": None,
        "hosts": ["dashscope.aliyuncs.com"],
        "models": [
            ("qwen-plus",  "Qwen-Plus — 推荐, 均衡"),
            ("qwen-max",   "Qwen-Max — 能力最强"),
            ("qwen-turbo", "Qwen-Turbo — 更快更便宜"),
        ],
    },
    "ollama": {
        "name": "本地 Ollama",
        "protocol": "openai_compatible",
        "base_url": "http://localhost:11434/v1",
        "default_model": None,   # 视本地已拉取的模型而定, 如 qwen2.5:7b
        "hosts": ["localhost", "127.0.0.1"],
        "models": [],
    },
    "anthropic": {
        "name": "Anthropic Claude",
        "protocol": "anthropic",
        "base_url": None,       # 用 SDK 默认
        "default_model": "claude-sonnet-5",
        "hosts": ["api.anthropic.com"],
        "models": [
            ("claude-sonnet-5",  "Sonnet 5 — 推荐, 均衡"),
            ("claude-opus-5",    "Opus 5 — 最强推理"),
            ("claude-haiku-4-5", "Haiku 4.5 — 更快更便宜"),
        ],
    },
}

# /config 服务选择菜单的顺序 (anthropic 走原生协议, 不在此菜单; 可经 [7] 自定义接入)
CONFIG_SERVICE_KEYS = ("deepseek", "openai", "zhipu", "kimi", "qwen", "ollama")


def detect_protocol(api_key: str) -> str:
    """根据 API Key 前缀判断协议。sk-ant- → anthropic; 其他 → openai_compatible。"""
    if api_key.startswith("sk-ant-"):
        return "anthropic"
    return "openai_compatible"


def find_service(base_url: str) -> Optional[str]:
    """按 base_url 域名识别已知服务; 返回 KNOWN_SERVICES 的 key 或 None。"""
    if not base_url:
        return None
    try:
        host = (urlparse(base_url).hostname or "").lower()
    except Exception:
        return None
    if not host:
        return None
    for key, info in KNOWN_SERVICES.items():
        if any(host == h or host.endswith("." + h) for h in info["hosts"]):
            return key
    return None


def is_local_url(base_url: Optional[str]) -> bool:
    """base_url 是否指向本机 (本地 Ollama 等无需真实 Key)。"""
    if not base_url:
        return False
    try:
        host = (urlparse(base_url).hostname or "").lower()
    except Exception:
        return False
    return host in ("localhost", "127.0.0.1", "::1", "0.0.0.0")


# ---------------------------------------------------------------------------
# 配置: 环境变量 > config.json > .reading_buddy_config.json (老版本)
# ---------------------------------------------------------------------------
DEFAULT_CONFIG = {
    "api_key": "",
    "protocol": "auto",      # "auto" | "openai_compatible" | "anthropic"
    "model": "",             # 空 = 使用对应已知服务的默认模型
    "mindmap_model": None,
    "base_url": None,
}


def read_config_file() -> tuple[Optional[dict], str]:
    """读取配置文件 (config.json 优先, 老文件兼容); 返回 (原始dict或None, 文件名)。"""
    for path in (CONFIG_FILE, LEGACY_CONFIG_FILE):
        if not path.exists():
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return raw, path.name
            print(f"  {Style.YELLOW}[!] {path.name} 内容格式异常, 已跳过{Style.RESET}")
        except Exception as e:
            print(f"  {Style.YELLOW}[!] 读取 {path.name} 失败 ({e}){Style.RESET}")
    return None, ""


def normalize_config(raw: dict) -> dict:
    """把任意版本的配置统一成新 schema; 老版 provider 字段兼容映射。"""
    cfg = {**DEFAULT_CONFIG, **{k: raw[k] for k in DEFAULT_CONFIG if k in raw}}
    if "protocol" not in raw and raw.get("provider"):
        provider = str(raw["provider"]).lower()
        if provider == "anthropic":
            cfg["protocol"] = "anthropic"
        elif provider == "deepseek":
            cfg["protocol"] = "openai_compatible"
            cfg["base_url"] = cfg.get("base_url") or KNOWN_SERVICES["deepseek"]["base_url"]
        # "auto" 保持 "auto", 之后再按 Key 前缀判断
    return cfg


def load_config() -> dict:
    """读取并归一化配置文件 (无文件时返回默认值)。"""
    raw, _ = read_config_file()
    return normalize_config(raw) if raw else dict(DEFAULT_CONFIG)


def save_config(config: dict) -> None:
    """保存配置到 config.json (老文件不再写入, 仅兼容读取)。"""
    try:
        CONFIG_FILE.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"  {Style.RED}[!] 保存配置失败: {e}{Style.RESET}")


def config_from_env() -> tuple[Optional[dict], str]:
    """从环境变量提取配置; 返回 (配置片段, 来源说明) 或 (None, "")。

    优先级 OPENAI_API_KEY > DEEPSEEK_API_KEY > ANTHROPIC_API_KEY;
    片段自带完整默认值, 不与文件配置逐字段合并。
    """
    def env(name: str) -> str:
        return os.environ.get(name, "").strip()

    if env("OPENAI_API_KEY"):
        base_url = env("OPENAI_BASE_URL") or "https://api.openai.com/v1"
        model = env("OPENAI_MODEL")
        if not model:
            # base_url 指向其他已知服务 → 借用该服务的默认模型
            svc = KNOWN_SERVICES.get(find_service(base_url))
            model = (svc or {}).get("default_model") or ""
        return {
            "api_key": env("OPENAI_API_KEY"),
            "protocol": "openai_compatible",
            "base_url": base_url,
            "model": model,
        }, "环境变量 OPENAI_API_KEY"

    if env("DEEPSEEK_API_KEY"):
        return {
            "api_key": env("DEEPSEEK_API_KEY"),
            "protocol": "openai_compatible",
            "base_url": KNOWN_SERVICES["deepseek"]["base_url"],
            "model": "deepseek-chat",
        }, "环境变量 DEEPSEEK_API_KEY"

    if env("ANTHROPIC_API_KEY"):
        return {
            "api_key": env("ANTHROPIC_API_KEY"),
            "protocol": "anthropic",
            "base_url": None,
            "model": env("ANTHROPIC_MODEL") or "claude-sonnet-5",
        }, "环境变量 ANTHROPIC_API_KEY"

    return None, ""


def _display_width(s: str) -> int:
    """近似终端显示宽度 (中文算两列), 用于引导表格对齐。"""
    return sum(2 if ord(c) > 0x2E80 else 1 for c in s)


def print_setup_guide(reason: str) -> None:
    """没有配置时: 打印友好的中文指引后直接退出, 不抛异常堆栈。(不返回)"""
    print()
    print(f"  {Style.YELLOW}[!] {reason}{Style.RESET}")
    print()
    print(f"  {Style.BOLD}两种配置方式, 任选其一:{Style.RESET}")
    print()
    print(f"  {Style.CYAN}方式一 · 设置环境变量{Style.RESET}")
    print(f"     {Style.DIM}Windows PowerShell:{Style.RESET}")
    print( "       $env:OPENAI_API_KEY=\"sk-xxx\"; python agent.py")
    print(f"     {Style.DIM}macOS / Linux:{Style.RESET}")
    print( "       export OPENAI_API_KEY=sk-xxx && python agent.py")
    print(f"     {Style.DIM}可选: OPENAI_BASE_URL / OPENAI_MODEL; 也支持 DEEPSEEK_API_KEY、ANTHROPIC_API_KEY{Style.RESET}")
    print()
    print(f"  {Style.CYAN}方式二 · 使用配置文件{Style.RESET}")
    print(f"     复制 config.example.json 为 config.json, 填入三要素:")
    print(f"       api_key    你的 API Key")
    print(f"       base_url   服务地址 (见下表)")
    print(f"       model      模型名")
    print()
    print(f"  {Style.BOLD}常见服务 base_url 对照表:{Style.RESET}")
    for svc in KNOWN_SERVICES.values():
        if svc["protocol"] != "openai_compatible" or not svc["base_url"]:
            continue
        pad = " " * max(2, 16 - _display_width(svc["name"]))
        print(f"     {svc['name']}{pad}{svc['base_url']}")
    print(f"     {Style.DIM}(Anthropic 用户把 protocol 填为 anthropic; 本地 Ollama 无需真实 Key, api_key 随便填){Style.RESET}")
    print()
    sys.exit(1)


def print_model_guide(base_url: Optional[str]) -> None:
    """无法推断默认模型时: 提示填写模型名后退出。(不返回)"""
    print()
    print(f"  {Style.YELLOW}[!] 无法确定该服务的默认模型, 请显式指定模型名{Style.RESET}")
    print(f"  {Style.DIM}  当前 API 地址: {base_url or '默认'}{Style.RESET}")
    print()
    print(f"  两种方式任选其一:")
    print(f"    1. 在 config.json 中填写 model 字段 (查该服务官方文档; Ollama 填本地已拉取的模型名, 如 qwen2.5:7b)")
    print(f"    2. 设置环境变量 OPENAI_MODEL, 如 $env:OPENAI_MODEL=\"模型名\"")
    print()
    sys.exit(1)


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
                "backend": d.get("protocol") or d.get("provider", ""),
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


# ---------------------------------------------------------------------------
# 跨书记忆 & 读者画像 (memory.md / profile.md)
# ---------------------------------------------------------------------------
MEMORY_FILE  = PROJECT_DIR / "memory.md"
PROFILE_FILE = PROJECT_DIR / "profile.md"
PORTRAIT_MARKER = "## 画像速写"          # profile.md 中"初次相识"骨架与画像正文的分界线
MEMORY_PROMPT_CHAR_LIMIT = 6000         # 注入提示词的 memory.md 字数上限 (超长保尾部)
PROFILE_QUESTIONS = [
    ("偏爱",        "你偏爱中国文学还是外国文学,或都喜欢?"),
    ("最喜欢的作者", "你最喜欢的作者是谁?"),
    ("关注点",      "你读书时最关注什么 (人物 / 情节 / 思想 / 文笔)?"),
]


def atomic_write_text(path: Path, content: str) -> None:
    """安全写入: 先写临时文件再原子替换,避免写一半把原文件损坏。"""
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, path)
    except Exception as e:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        print(f"  {Style.RED}[!] 写入 {path.name} 失败: {e}{Style.RESET}")


def read_markdown(path: Path) -> str:
    """读取 utf-8 markdown 文件; 不存在或读取失败返回空串 (等同未建档)。"""
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def read_memory_for_prompt() -> str:
    """读取跨书记忆供提示词注入; 超长时截尾保留 (最新记录在文件末尾)。"""
    text = read_markdown(MEMORY_FILE).strip()
    if len(text) > MEMORY_PROMPT_CHAR_LIMIT:
        text = "(更早的记忆已省略)\n\n" + text[-MEMORY_PROMPT_CHAR_LIMIT:]
    return text


def append_memory_entries(book_label: str, entries: str) -> bool:
    """向 memory.md 追加一段新记忆 (追加式, 不改写历史); 返回是否实际写入。"""
    entries = entries.strip()
    if not entries:
        return False
    old = read_markdown(MEMORY_FILE)
    if not old.strip():
        old = ("# 跨书记忆\n\n"
               "> 读书搭子的跨书偏好记忆 — 记录读者在一次次共读中显露的品味与倾向。\n"
               "> 由 AI 在会话结束后提炼追加;只增不删,不与某本书绑定。\n")
    today = datetime.now().strftime("%Y-%m-%d")
    block = f"\n## {today} · {book_label}\n\n{entries}\n"
    atomic_write_text(MEMORY_FILE, old.rstrip("\n") + "\n" + block)
    return True


def init_profile_file(answers: list[tuple[str, str]]) -> None:
    """首次启动: 把基础问答写成读者画像的初始骨架。"""
    today = datetime.now().strftime("%Y-%m-%d")
    lines = ["# 读者画像", "", f"## 初次相识 ({today})", ""]
    for label, answer in answers:
        lines.append(f"- {label}: {answer}")
    lines += ["", PORTRAIT_MARKER, "", "(刚刚认识这位读者,画像还在慢慢成形……)", ""]
    atomic_write_text(PROFILE_FILE, "\n".join(lines))


def get_current_portrait() -> str:
    """取 profile.md 画像速写区的内容 (无则返回空串)。"""
    old = read_markdown(PROFILE_FILE)
    if PORTRAIT_MARKER in old:
        return old.split(PORTRAIT_MARKER, 1)[1].strip()
    return ""


def update_profile_portrait(portrait: str) -> None:
    """更新 profile.md 的画像速写区,程序化保留"初次相识"问答骨架。"""
    portrait = portrait.strip()
    if not portrait:
        return
    old = read_markdown(PROFILE_FILE)
    if PORTRAIT_MARKER in old:
        head = old.split(PORTRAIT_MARKER, 1)[0].rstrip("\n") + "\n\n"
        new_content = head + PORTRAIT_MARKER + "\n\n" + portrait + "\n"
    elif old.strip():
        new_content = old.rstrip("\n") + "\n\n" + PORTRAIT_MARKER + "\n\n" + portrait + "\n"
    else:
        new_content = "# 读者画像\n\n" + PORTRAIT_MARKER + "\n\n" + portrait + "\n"
    atomic_write_text(PROFILE_FILE, new_content)


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

    {memory_context}

    {cross_book_context}""")

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

    {memory_context}

    {cross_book_context}""")

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

MEMORY_UPDATE_PROMPT = textwrap.dedent("""\
    你是读书搭子的"记忆管理员",负责维护两份关于读者的档案。根据用户提供的本次
    会话完整对话与现有档案,输出两部分内容:

    ## 第一部分: 新增记忆条目
    - 只记录这次对话中**新显露**的读书偏好: 喜欢的作者/类型、偏好的分析角度、
      情感倾向、聊书时的习惯等。
    - 每条一行,以 "- " 开头,写得具体 (不要"喜欢读书"这类空话)。
    - 不要与现有跨书记忆重复;没有新的偏好信号就只输出: NONE

    ## 第二部分: 画像速写 (全文重写)
    - 综合现有记忆、现有速写和这次对话,用第三人称重写这位读者的画像:
      ta 偏爱的文学版图、关注书的哪些维度、聊书时的神采与温度。
    - 150-250 字,文艺、细腻,像给老朋友写的一幅侧写,不要罗列标签。
    - 画像确实无需变化时,只输出: UNCHANGED

    ## 输出格式 (严格遵守)
    第一部分内容
    =======SPLIT=======
    第二部分内容
    除这两部分外不要输出任何其他内容。""")

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
        protocol: str = "openai_compatible",
        model: str = "",
        mindmap_model: Optional[str] = None,
        base_url: Optional[str] = None,
        config_from_env: bool = False,
    ):
        # --- 确定协议 ---
        if protocol not in PROTOCOL_LABELS:
            protocol = detect_protocol(api_key)
        self.protocol = protocol
        self.base_url = base_url
        self.model = model
        self.mindmap_model = mindmap_model or self.model
        self._config_from_env = config_from_env   # 配置来自环境变量时, /model 切换不落盘

        # 已知服务识别 (用于显示与 /model 建议)
        self.service_key = "anthropic" if protocol == "anthropic" else find_service(base_url or "")
        self.service_label = KNOWN_SERVICES[self.service_key]["name"] if self.service_key else "自定义服务"

        # --- 创建客户端 ---
        self._api_key = api_key
        self._client = self._create_client(api_key, protocol, base_url)

        # 会话状态
        self.book_name: str = ""
        self.author: str = ""
        self.author_info: str = ""
        self.mode: Literal["known", "unknown"] = "unknown"
        self.messages: list[dict] = []
        self.system_prompt: str = ""

    # ------------------------------------------------------------------
    # 客户端构建 (/config 切换服务后重建)
    # ------------------------------------------------------------------
    @staticmethod
    def _create_client(api_key: str, protocol: str, base_url: Optional[str]):
        if protocol == "anthropic":
            import anthropic
            kwargs = {"api_key": api_key}
            if base_url:
                kwargs["base_url"] = base_url
            return anthropic.Anthropic(**kwargs)
        # OpenAI 兼容: 传 base_url + model 通吃绝大多数服务
        import openai
        return openai.OpenAI(
            api_key=api_key,
            base_url=base_url or "https://api.deepseek.com",   # 兜底同老版本行为
        )

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

        if self.protocol == "anthropic":
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

        if self.protocol == "anthropic":
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

    def _build_cross_book_context(self) -> str:
        """把 profile.md + memory.md 拼成可注入系统提示词的跨书上下文。"""
        sections = []
        profile = read_markdown(PROFILE_FILE).strip()
        memory = read_memory_for_prompt()
        if profile:
            sections.append("### 读者画像 (profile.md)\n\n" + profile)
        if memory:
            sections.append("### 跨书记忆 (memory.md)\n\n" + memory)
        if not sections:
            return ""
        guidance = textwrap.dedent("""\
            以上是你和这位读者跨书相处的记录。请这样使用它：

            - **如果当前共读的书与记忆中的某本书属于同一作者，或题材/风格明显相近**：
              请在开场自然地提一句关联（例如"你上次读《XX》时特别关注……，这本在某些地方也有类似的质地"），
              让读者感到被记住。全程最多提一次，点到为止。

            - **如果当前的书是全新的作者、且题材与记忆中任何一本都相差很远**：
              不必强行关联，像第一次认识一样自然地进入这本书即可。宁可不说，也不要硬扯。

            - 无论哪种情况：不要机械复述记忆内容、不要罗列条目、不要对读者的品味评头论足。""")
        return (
            "## 关于这位读者 (跨书信息)\n\n"
            + "\n\n".join(sections)
            + "\n\n"
            + guidance
        )

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
            cross_ctx = self._build_cross_book_context()

            if self.mode == "known":
                self.system_prompt = SYSTEM_PROMPT_KNOWN.format(
                    book_name=self.book_name,
                    author_line=a_ctx["author_line"],
                    memory_context=memory_ctx,
                    cross_book_context=cross_ctx,
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
                    cross_book_context=cross_ctx,
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
            cross_ctx = self._build_cross_book_context()

            if mode == "known":
                self.mode = "known"
                self.system_prompt = SYSTEM_PROMPT_KNOWN.format(
                    book_name=self.book_name,
                    author_line=a_ctx["author_line"],
                    memory_context="",
                    cross_book_context=cross_ctx,
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
                    cross_book_context=cross_ctx,
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
        if s.lower() in ("/config", "/service"):
            self._cmd_config()
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
        if s.lower() in ("/profile", "/me"):
            self._cmd_profile()
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
                print(f"  {Style.DIM}  4. 当前服务: {self.service_label}, base_url: {self.base_url or '默认'}{Style.RESET}")
                print(f"  {Style.RED}原始错误: {e}{Style.RESET}\n")
            elif "401" in str(e):
                print(f"\n  {Style.RED}[!] API 鉴权失败 (401): Key 无效或已过期{Style.RESET}")
                print(f"  {Style.DIM}  当前服务: {self.service_label} · base_url: {self.base_url or '默认'}{Style.RESET}")
                print(f"  {Style.DIM}  → 用 /config 重新填写该服务的 API Key (注意粘贴一次即可, 长度约几十字符){Style.RESET}\n")
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
    # 跨书记忆 & 读者画像
    # ------------------------------------------------------------------
    def _maybe_init_profile(self) -> None:
        """首次启动: profile.md 不存在时,问 3 个基础问题建立画像骨架。"""
        if PROFILE_FILE.exists():
            return
        print(f"  {Style.BLUE}{Style.BOLD}[🪞] 第一次见面,先认识你一下——3 个小问题{Style.RESET}")
        print(f"  {Style.DIM}(每个问题直接回车可跳过,聊得多了画像自然会清晰){Style.RESET}")
        print()
        answers = []
        for label, question in PROFILE_QUESTIONS:
            a = input(f"  {Style.CYAN}{question}{Style.RESET} ").strip()
            answers.append((label, a if a else "(未透露)"))
        init_profile_file(answers)
        print()
        print(f"  {Style.GREEN}[OK] 已建档 -> {PROFILE_FILE.name},之后每次聊完都会补全它{Style.RESET}")
        print()

    def _update_user_memory(self) -> bool:
        """会话结束时一次性运行: 提炼本次对话的读者偏好追加到 memory.md,
        并基于记忆更新 profile.md 的画像速写。
        返回 True 表示提炼流程执行完成 (含"无新信号"); False 表示跳过或失败。
        成功后把会话存档标记为 memory_extracted=true,供下次启动判断是否补提炼。"""
        if len(self.messages) < 4:
            print_status("本次对话较短，未提炼跨书记忆（至少需要约 2 轮对话才能形成有效信号）", Style.DIM)
            self._mark_memory_extracted()  # 只有开场寒暄,无内容可提炼,同样标记完成
            return False
        label = format_book_label(self.book_name, self.author)
        history = self._build_history_summary()  # 复用脑图生成的对话摘要 (最近 20 轮)

        user_content = textwrap.dedent(f"""\
            ## 本次会话完整对话 (正在共读: {label})
            {history}

            ---
            ## 现有跨书记忆 (memory.md)
            {read_memory_for_prompt() or "(尚无记录)"}

            ---
            ## 现有画像速写 (profile.md)
            {get_current_portrait() or "(尚无画像)"}""")

        print_status("正在提炼跨书记忆……", Style.DIM)
        try:
            raw = self._api_create(
                system=MEMORY_UPDATE_PROMPT,
                messages=[{"role": "user", "content": user_content}],
                max_tokens=1000,
                temperature=0.3,
            )
            entry_part, portrait_part = self._parse_memory_output(raw)
            if entry_part:
                append_memory_entries(label, entry_part)
                print_status(f"[OK] 跨书记忆已更新 -> {MEMORY_FILE.name}", Style.GREEN)
            if portrait_part:
                update_profile_portrait(portrait_part)
                print_status(f"[OK] 读者画像已更新 -> {PROFILE_FILE.name}", Style.GREEN)
            if not entry_part and not portrait_part:
                print_status("这次没有新的偏好信号", Style.DIM)
            self._mark_memory_extracted()
            return True
        except Exception as e:
            if self._error_is_403(e):
                print_status("[!] 跨书记忆更新被拒 (403),这次跳过。", Style.YELLOW)
            else:
                print_status(f"[!] 跨书记忆更新失败 (不影响对话): {e}", Style.YELLOW)
            return False

    def _mark_memory_extracted(self) -> None:
        """把当前书的会话存档标记为"记忆已提炼",避免下次启动重复补提炼。"""
        data = load_session(self.book_name, self.author)
        if data:
            data["memory_extracted"] = True
            save_session(self.book_name, data, self.author)

    @staticmethod
    def _parse_memory_output(raw: str) -> tuple[str, str]:
        """拆解记忆管理员的输出 → (新增记忆条目, 新画像速写); 空串表示无需更新。"""
        raw = re.sub(r'^```[a-zA-Z]*\s*', '', raw.strip())
        raw = re.sub(r'\s*```$', '', raw).strip()
        parts = re.split(r'=+\s*SPLIT\s*=+', raw, maxsplit=1)

        def drop_headers(text: str) -> str:
            lines = [l for l in text.strip().splitlines() if not l.strip().startswith("#")]
            return "\n".join(lines).strip()

        entry = drop_headers(parts[0]) if parts else ""
        portrait = drop_headers(parts[1]) if len(parts) > 1 else ""
        if entry.upper().rstrip("。.!;；").replace(" ", "") in ("", "NONE", "无新增"):
            entry = ""
        if portrait.upper().rstrip("。.!;；").replace(" ", "") in ("", "UNCHANGED", "无变化"):
            portrait = ""
        return entry, portrait

    # ------------------------------------------------------------------
    # 命令
    # ------------------------------------------------------------------
    def _cmd_model(self, raw_input: str):
        service = KNOWN_SERVICES.get(self.service_key) if self.service_key else None
        parts = raw_input.strip().split(maxsplit=1)
        if len(parts) == 1:
            print()
            print(f"  {Style.BLUE}当前服务: {Style.BOLD}{self.service_label}{Style.RESET}")
            print(f"  {Style.BLUE}当前对话模型: {Style.BOLD}{self.model}{Style.RESET}")
            if self.mindmap_model and self.mindmap_model != self.model:
                print(f"  {Style.BLUE}当前脑图模型: {Style.BOLD}{self.mindmap_model}{Style.RESET}")
            else:
                print(f"  {Style.DIM}(脑图模型与对话模型相同){Style.RESET}")
            print()
            if service and service.get("models"):
                print(f"  {Style.DIM}该服务常见模型 (任意模型名也可直接输入):{Style.RESET}")
                for mid, desc in service["models"]:
                    marker = " ← 当前" if mid == self.model else ""
                    print(f"     {Style.DIM}{mid}  ({desc}){marker}{Style.RESET}")
                print()
                print(f"  {Style.DIM}切换示例: /model {service['models'][0][0]}{Style.RESET}")
            else:
                print(f"  {Style.DIM}该服务的模型名以其官方文档为准:{Style.RESET}")
                print(f"  {Style.DIM}切换示例: /model <模型名>{Style.RESET}")
            print()
        else:
            new_model = parts[1].strip()
            if not new_model:
                return
            old = self.model
            self.model = new_model
            print()
            print(f"  {Style.GREEN}[OK] 模型已切换:{Style.RESET}")
            print(f"  {Style.DIM}  {old}{Style.RESET}")
            print(f"  {Style.DIM}  → {Style.BOLD}{self.model}{Style.RESET}")
            if self._config_from_env:
                print(f"  {Style.YELLOW}[!] 当前配置来自环境变量, 此切换仅本次会话生效{Style.RESET}")
            else:
                cfg = load_config()
                cfg["model"] = self.model
                save_config(cfg)
            print()
            print(f"  {Style.DIM}提示: 如果切换到的是其他服务 (如从 DeepSeek 换到智谱), 请用 /config 同时更新 base_url 和 api_key。{Style.RESET}")
            print()
            self._do_save_session()

    def _cmd_config(self):
        """交互式重配连接三要素 (base_url / api_key / 模型), 保存到 config.json 并即时生效。"""
        print()
        print(f"  {Style.BLUE}{Style.BOLD}当前配置:{Style.RESET}")
        print(f"  {Style.DIM}  服务: {self.service_label}{Style.RESET}")
        print(f"  {Style.DIM}  base_url: {self.base_url or '(SDK 默认)'}{Style.RESET}")
        print(f"  {Style.DIM}  模型: {self.model}{Style.RESET}")
        print(f"  {Style.DIM}  API Key: {obfuscate_key(self._api_key) if self._api_key else '(未设置)'}{Style.RESET}")
        print()
        print(f"  {Style.BLUE}选择服务:{Style.RESET}")
        for i, key in enumerate(CONFIG_SERVICE_KEYS, 1):
            svc = KNOWN_SERVICES[key]
            pad = " " * max(2, 14 - _display_width(svc["name"]))
            print(f"  {Style.CYAN}[{i}]{Style.RESET} {svc['name']}{pad}{Style.DIM}{svc['base_url']}{Style.RESET}")
        print(f"  {Style.CYAN}[7]{Style.RESET} 自定义 base_url")
        print(f"  {Style.DIM}(回车 = 不切换服务, 只改 base_url / Key / 模型){Style.RESET}")
        choice = input(f"  {Style.CYAN}选择 (1-7):{Style.RESET} ").strip()
        print()

        protocol, base_url = self.protocol, self.base_url
        if choice.isdigit() and 1 <= int(choice) <= len(CONFIG_SERVICE_KEYS):
            svc = KNOWN_SERVICES[CONFIG_SERVICE_KEYS[int(choice) - 1]]
            protocol, base_url = svc["protocol"], svc["base_url"]
            new_url = input(f"  {Style.CYAN}base_url{Style.RESET} {Style.DIM}(回车 = {base_url}):{Style.RESET} ").strip()
            if new_url:
                base_url = new_url
        elif choice == "7":
            new_url = input(f"  {Style.CYAN}自定义 base_url (回车 = 保留当前):{Style.RESET} ").strip()
            if new_url:
                base_url = new_url

        api_key = self._api_key
        while True:
            new_key = getpass.getpass("  API Key (输入不回显, 回车 = 保留当前): ").strip()
            if not new_key:
                break
            # 显示长度供确认: 无回显下连续粘贴会把多份 Key 拼成一行, 长度一眼可辨
            print(f"  {Style.DIM}已收到: {obfuscate_key(new_key)} ({len(new_key)} 字符){Style.RESET}")
            if input("  回车确认 / r 重新粘贴: ").strip().lower() != "r":
                api_key = new_key
                break

        model = self.model
        new_service = KNOWN_SERVICES.get("anthropic" if protocol == "anthropic" else find_service(base_url or ""))
        if new_service and new_service.get("models"):
            suggestions = "  ".join(f"{mid} ({desc})" for mid, desc in new_service["models"])
            print(f"  {Style.DIM}该服务常见模型: {suggestions}{Style.RESET}")
        new_model = input(f"  {Style.CYAN}模型名 (回车 = 保留当前 {model}):{Style.RESET} ").strip()
        if new_model:
            model = new_model

        # 全部回车 = 只查看, 不落盘 (避免把环境变量快照意外写进 config.json)
        if (protocol, base_url, api_key, model) == (self.protocol, self.base_url, self._api_key, self.model):
            print()
            print(f"  {Style.DIM}配置未变化, 已保留 {CONFIG_FILE.name} 原内容{Style.RESET}")
            print()
            return

        # --- 保存 (mindmap_model 跟随主模型时一并切换) ---
        old_model = self.model
        cfg = load_config()
        cfg.update({"api_key": api_key, "protocol": protocol, "base_url": base_url, "model": model})
        if not cfg.get("mindmap_model") or cfg["mindmap_model"] == old_model:
            cfg["mindmap_model"] = model
        save_config(cfg)

        # --- 即时生效: 更新自身状态并重建客户端 ---
        self.protocol, self.base_url, self.model = protocol, base_url, model
        if not self.mindmap_model or self.mindmap_model == old_model:
            self.mindmap_model = model
        self._api_key = api_key
        self.service_key = "anthropic" if protocol == "anthropic" else find_service(base_url or "")
        self.service_label = KNOWN_SERVICES[self.service_key]["name"] if self.service_key else "自定义服务"
        self._client = self._create_client(api_key, protocol, base_url)

        print()
        print(f"  {Style.GREEN}[OK] 新配置已保存到 {CONFIG_FILE.name}, 并已即时生效:{Style.RESET}")
        print(f"  {Style.DIM}  服务: {self.service_label}{Style.RESET}")
        print(f"  {Style.DIM}  base_url: {self.base_url or '(SDK 默认)'}{Style.RESET}")
        print(f"  {Style.DIM}  模型: {self.model}{Style.RESET}")
        print(f"  {Style.DIM}  API Key: {obfuscate_key(api_key)}{Style.RESET}")
        if self._config_from_env:
            print(f"  {Style.YELLOW}[!] 当前运行配置来自环境变量, 环境变量优先 — 此修改会在未设置环境变量时生效{Style.RESET}")
        print()
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

    def _cmd_profile(self):
        print()
        profile = read_markdown(PROFILE_FILE).strip()
        memory = read_markdown(MEMORY_FILE).strip()
        if not profile and not memory:
            print(f"  {Style.DIM}还没有读者画像和跨书记忆{Style.RESET}")
            print()
            return
        if profile:
            print(f"  {Style.BLUE}{Style.BOLD}🪞 读者画像 ({PROFILE_FILE.name}):{Style.RESET}")
            print()
            for line in profile.splitlines():
                print(f"  {line}" if line.strip() else "")
        if memory:
            print()
            print(f"  {Style.BLUE}{Style.BOLD}📚 跨书记忆 ({MEMORY_FILE.name}):{Style.RESET}")
            print()
            for line in memory.splitlines():
                print(f"  {line}" if line.strip() else "")
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
            print(f"     {Style.DIM}{s['message_count']} 条 · {format_datetime(s['updated_at'])} · {s.get('backend','')} · {s['model']}{Style.RESET}")
        print()

    def _cmd_help(self):
        print()
        print(f"  {Style.BLUE}{Style.BOLD}可用命令 ({self.service_label} · {PROTOCOL_LABELS[self.protocol]}):{Style.RESET}")
        print()
        print(f"  {Style.CYAN}/model [模型名]{Style.RESET}  — 查看或切换模型")
        print(f"  {Style.CYAN}/config, /service{Style.RESET} — 切换服务 (base_url / API Key / 模型)")
        print(f"  {Style.CYAN}/author{Style.RESET}          — 查看作者背景信息")
        print(f"  {Style.CYAN}/profile, /me{Style.RESET}    — 查看读者画像 & 跨书记忆")
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
            "protocol": self.protocol,
            "service": self.service_label,
            "model": self.model,
            "mindmap_model": self.mindmap_model,
            "base_url": self.base_url,
            "created_at": getattr(self, "_session_created_at", datetime.now(timezone.utc).isoformat()),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "memory_extracted": False,   # 本份存档内容尚未提炼;提炼成功后由 _mark_memory_extracted 翻成 true
            "messages": self.messages,
        }
        if not hasattr(self, "_session_created_at"):
            self._session_created_at = data["created_at"]
        save_session(self.book_name, data, self.author)
        self._session_updated_at = data["updated_at"]

    # ------------------------------------------------------------------
    # 书名输入确认
    # ------------------------------------------------------------------
    def _confirm_book_input(self, book_name: str, author: str) -> Literal["confirm", "redo", "quit"]:
        """书名/作者确认关卡: 展示即将共读的书与存档提示,循环等待直到确认或退出。

        回车 → confirm;r/R → redo (重新输入);q/Q → quit (退出);其他输入提示后重试。
        """
        label = format_book_label(book_name, author)
        has_previous = load_session(book_name, author) is not None
        print()
        print(f"  {Style.CYAN}{Style.BOLD}即将开始共读：{label}{Style.RESET}")
        if has_previous:
            print(f"  {Style.DIM}（检测到之前聊过这本书，继续会话接上历史记录）{Style.RESET}")
        print()
        print(f"  {Style.GREEN}[回车]{Style.RESET} 确认开始   {Style.YELLOW}[r]{Style.RESET} 重新输入   {Style.DIM}[q]{Style.RESET} 退出")
        while True:
            choice = input(f"  {Style.CYAN}请确认:{Style.RESET} ").strip().lower()
            if choice == "":
                return "confirm"
            if choice == "r":
                return "redo"
            if choice == "q":
                return "quit"
            print(f"  {Style.YELLOW}请输入回车/r/q{Style.RESET}")

    # ------------------------------------------------------------------
    # 主循环
    # ------------------------------------------------------------------
    def run(self):
        print_banner()

        self._maybe_init_profile()
        if PROFILE_FILE.exists() or MEMORY_FILE.exists():
            print_status("读者画像 & 跨书记忆已就绪 (/profile 可查看)", Style.DIM)

        # 书名 + 作者录入,过确认关卡 (回车确认 / r 重新输入 / q 退出),循环直到确认或退出
        while True:
            book_name = input(f"  {Style.CYAN}请输入你在读的书名:{Style.RESET} ").strip()
            while not book_name:
                print(f"  {Style.YELLOW}书名不能为空,请输入书名~{Style.RESET}")
                book_name = input(f"  {Style.CYAN}请输入你在读的书名:{Style.RESET} ").strip()

            print()
            author = input(f"  {Style.CYAN}请输入作者名 (可选,按回车跳过):{Style.RESET} ").strip()
            if author:
                print(f"  {Style.DIM}(已记录作者: {author}){Style.RESET}")

            decision = self._confirm_book_input(book_name, author)
            if decision == "quit":
                print()
                print(f"  {Style.CYAN}好的,下次再一起读书~{Style.RESET}")
                print()
                return
            if decision == "redo":
                book_name, author = "", ""   # 清空上一次的录入,避免残留
                print()
                continue
            break

        previous = load_session(book_name, author)

        if previous:
            prev_msg = previous.get("messages", [])
            prev_mode = previous.get("mode", "unknown")
            prev_updated = previous.get("updated_at", "")
            prev_model = previous.get("model", self.model)
            prev_author = previous.get("author", "")
            prev_author_info = previous.get("author_info", "")
            prev_backend = previous.get("protocol") or previous.get("provider", "")
            prev_count = len(prev_msg)

            label = format_book_label(book_name, prev_author or author)

            print()
            print(f"  {Style.BLUE}[📖] 发现之前的会话存档!{Style.RESET}")
            print(f"  {Style.DIM}  书名: {label}{Style.RESET}")
            print(f"  {Style.DIM}  对话数: {prev_count} 条{Style.RESET}")
            print(f"  {Style.DIM}  上次更新: {format_datetime(prev_updated)}{Style.RESET}")
            print(f"  {Style.DIM}  模式: {'经典引导' if prev_mode == 'known' else '盲盒盲读'}{Style.RESET}")
            print(f"  {Style.DIM}  后端: {prev_backend} · 模型: {prev_model}{Style.RESET}")
            print()

            # 上次异常退出 (Ctrl+C / 关窗口 / 崩溃) 时,退出环节的提炼没跑成 → 先基于存档补做。
            # 放在选择菜单之前: 无论用户选"继续"还是"重新开始",旧对话的偏好都不丢。
            if previous.get("memory_extracted") is False:
                self.book_name = book_name
                self.author = prev_author or author
                self.messages = prev_msg
                print(f"  {Style.YELLOW}[!] 检测到上次会话未提炼,正在补做跨书记忆…{Style.RESET}")
                self._update_user_memory()
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
                # 模型与服务跟随当前配置 (旧存档只恢复对话内容),
                # 避免换服务后继续会话被旧存档带回老地址
                self.messages = prev_msg
                self._session_created_at = previous.get("created_at", datetime.now(timezone.utc).isoformat())
                self._session_updated_at = prev_updated
                self.start_session(book_name, self.author, resume=True)
        else:
            self.author = author
            self._session_created_at = datetime.now(timezone.utc).isoformat()
            self.start_session(book_name, self.author, resume=False)

        print()
        print(f"  {Style.DIM}━━━  服务: {self.service_label} | 每次回答后自动存档 & 更新脑图  ━━━{Style.RESET}")
        print(f"  {Style.DIM}  命令: /model 切换模型 | /config 切换服务 | /author 作者背景 | /profile 画像&记忆 | /save 手动存档 | /history 历史 | /quit 退出{Style.RESET}")
        print()

        turn_count = (len(self.messages) // 2) + 1
        interrupted = False
        try:
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
        except KeyboardInterrupt:
            interrupted = True
            print()
            print(f"  {Style.YELLOW}[!] 收到 Ctrl+C,正在收尾……{Style.RESET}")

        # 对话结束 (正常 /quit 或 Ctrl+C): 一次性提炼本次会话的偏好 → 跨书记忆 & 画像 (单次 API 调用)
        saved = self._update_user_memory()
        if interrupted and saved:
            print(f"  {Style.GREEN}[已保存] 跨书记忆{Style.RESET}")

        label = format_book_label(self.book_name, self.author)
        mp, mubu = get_mindmap_paths(self.book_name, self.author)
        sp = get_session_path(self.book_name, self.author)
        print(f"  {Style.DIM}本次会话总结:{Style.RESET}")
        print(f"     {Style.GREEN}[存档] 会话记录:{Style.RESET} {sp}")
        print(f"     {Style.GREEN}[脑图] 可视化脑图:{Style.RESET} {mp}")
        print(f"     {Style.GREEN}[大纲] 幕布导入版:{Style.RESET} {mubu}")
        print(f"     {Style.GREEN}[记忆] 跨书记忆:{Style.RESET} {MEMORY_FILE}")
        print(f"     {Style.GREEN}[画像] 读者画像:{Style.RESET} {PROFILE_FILE}")
        print()


# ===================================================================
# CLI 入口
# ===================================================================
def main():
    parser = argparse.ArgumentParser(
        description="读书笔记总结 Agent — 任何 OpenAI 兼容服务 / Anthropic 原生均可接入",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            示例:
              python agent.py                                    # 配置来自环境变量 / config.json
              python agent.py --protocol anthropic               # 强制 Anthropic 原生协议
              python agent.py --api-key sk-xxx --base-url https://api.deepseek.com --model deepseek-chat
              python agent.py --reset-config
              python agent.py --list-sessions

            配置优先级: 环境变量 > config.json > .reading_buddy_config.json (老版本兼容)
            环境变量: OPENAI_API_KEY (+可选 OPENAI_BASE_URL / OPENAI_MODEL),
            DEEPSEEK_API_KEY, ANTHROPIC_API_KEY (+可选 ANTHROPIC_MODEL)
        """),
    )
    parser.add_argument("--api-key", "-k", default=None, help="API Key")
    parser.add_argument("--protocol", "-p", default=None,
                        choices=["openai_compatible", "anthropic", "auto"],
                        help="协议 (默认: auto — 按配置文件 / Key 前缀判断)")
    parser.add_argument("--provider", default=None,
                        choices=["anthropic", "deepseek", "openai_compatible", "auto"],
                        help="(老版本兼容) 等价 --protocol, 将被弃用")
    parser.add_argument("--model", "-m", default=None, help="对话模型")
    parser.add_argument("--mindmap-model", default=None, help="脑图模型")
    parser.add_argument("--base-url", default=None, help="API 地址 (常见服务对照见 config.example.json)")
    parser.add_argument("--reset-config", action="store_true", help="重置配置文件")
    parser.add_argument("--list-sessions", action="store_true", help="列出存档会话")
    args = parser.parse_args()

    if args.reset_config:
        removed = False
        for path in (CONFIG_FILE, LEGACY_CONFIG_FILE):
            if path.exists():
                path.unlink()
                print(f"  {Style.GREEN}[OK] 已删除 {path.name}{Style.RESET}")
                removed = True
        if not removed:
            print(f"  {Style.DIM}没有发现配置文件{Style.RESET}")
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
                print(f"     {Style.DIM}{s['message_count']} 条 · {format_datetime(s['updated_at'])} · {s.get('backend','')} · {s['model']}{Style.RESET}")
            print()
        else:
            print(f"  {Style.DIM}暂无存档{Style.RESET}")
        return

    # --- 解析配置: CLI 参数 > 环境变量 > config.json > .reading_buddy_config.json ---
    raw_file, file_name = read_config_file()
    file_cfg = normalize_config(raw_file) if raw_file else None
    env_cfg, env_source = config_from_env()

    if env_cfg is not None:
        # 环境变量配置自带完整默认值, 仅借用配置文件里的 mindmap_model
        cfg = dict(DEFAULT_CONFIG)
        if file_cfg and file_cfg.get("mindmap_model"):
            cfg["mindmap_model"] = file_cfg["mindmap_model"]
        cfg.update(env_cfg)
        config_source = env_source
    elif file_cfg is not None:
        cfg = file_cfg
        config_source = file_name
    else:
        cfg = dict(DEFAULT_CONFIG)
        config_source = ""

    # CLI 参数覆盖 (老 --provider 参数映射为协议名)
    if args.provider and not args.protocol:
        args.protocol = {"anthropic": "anthropic", "deepseek": "openai_compatible",
                         "openai_compatible": "openai_compatible"}.get(args.provider, "auto")
        print(f"  {Style.YELLOW}[!] --provider 已由 --protocol 取代, 本次已自动映射{Style.RESET}")
    cli_overrode = False
    if args.api_key and args.api_key != cfg.get("api_key"):
        cfg["api_key"] = args.api_key
        cli_overrode = True
    if args.protocol and args.protocol != cfg.get("protocol"):
        cfg["protocol"] = args.protocol
        cli_overrode = True
    if args.model and args.model != cfg.get("model"):
        cfg["model"] = args.model
        cli_overrode = True
    if args.mindmap_model and args.mindmap_model != cfg.get("mindmap_model"):
        cfg["mindmap_model"] = args.mindmap_model
        cli_overrode = True
    if args.base_url and args.base_url != cfg.get("base_url"):
        cfg["base_url"] = args.base_url
        cli_overrode = True

    # API Key: 缺失 → 友好指引后退出 (本地 Ollama 无需真实 Key)
    api_key = (cfg.get("api_key") or "").strip()
    if not api_key:
        if is_local_url(cfg.get("base_url")):
            api_key = "ollama"
            cfg["api_key"] = api_key
        else:
            print_setup_guide("未找到 API Key 配置 — 请先完成配置再启动")

    # 协议: auto → 按 Key 前缀判断
    protocol = (cfg.get("protocol") or "auto").lower()
    if protocol == "auto":
        protocol = detect_protocol(api_key)
    if protocol not in PROTOCOL_LABELS:
        protocol = "openai_compatible"

    # base_url: OpenAI 兼容但未填地址 → 兜底 DeepSeek (同老版本行为;
    # 使用其他服务时请在 config.json 显式填写 base_url)
    base_url = cfg.get("base_url")
    if protocol == "openai_compatible" and not base_url:
        base_url = KNOWN_SERVICES["deepseek"]["base_url"]

    # 模型: 显式配置优先, 其次已知服务的默认模型; 仍为空 → 提示填写后退出
    service_key = "anthropic" if protocol == "anthropic" else find_service(base_url or "")
    service = KNOWN_SERVICES.get(service_key) if service_key else None
    model = (cfg.get("model") or "").strip() or (service or {}).get("default_model") or ""
    if not model:
        print_model_guide(base_url)

    mindmap_model = cfg.get("mindmap_model") or model

    # CLI 显式指定且配置并非来自环境变量 → 持久化到 config.json
    # (同老版行为: 首次 --api-key 启动即保存; 环境变量用户不写文件, 避免两套来源打架)
    if cli_overrode and env_cfg is None:
        save_config({
            "api_key": api_key,
            "protocol": protocol,
            "model": model,
            "mindmap_model": mindmap_model,
            "base_url": base_url,
        })
        print(f"  {Style.GREEN}[OK] 配置已保存到 {CONFIG_FILE.name}{Style.RESET}")

    # --- 显示配置 ---
    service_label = service["name"] if service else "自定义服务"
    print()
    print(f"  {Style.DIM}配置{f' (来源: {config_source})' if config_source else ''}:{Style.RESET}")
    print(f"  {Style.DIM}  协议: {PROTOCOL_LABELS[protocol]} · 服务: {service_label}{Style.RESET}")
    print(f"  {Style.DIM}  API Key: {obfuscate_key(api_key)}{Style.RESET}")
    print(f"  {Style.DIM}  对话模型: {model}{Style.RESET}")
    if mindmap_model != model:
        print(f"  {Style.DIM}  脑图模型: {mindmap_model}{Style.RESET}")
    if base_url:
        print(f"  {Style.DIM}  API: {base_url}{Style.RESET}")
    print()

    # --- 检查依赖 ---
    if protocol == "anthropic":
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
        protocol=protocol,
        model=model,
        mindmap_model=mindmap_model,
        base_url=base_url,
        config_from_env=env_cfg is not None,
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
