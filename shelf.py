#!/usr/bin/env python3
"""书架 Dashboard — 只读本地书架数据的可视化面板。

起一个仅监听 127.0.0.1 的 HTTP 服务 (默认 8766), 数据实时来自本地文件:
  GET /                     → index.html
  GET /api/shelf-data.json  → 书架汇总 (扫描 notes/ + profile.md + memory.md)
  GET /api/note?book=X&author=Y&type=mindmap|outline → 笔记原文 (markdown)

铁律: 每次请求都实时读取, 不缓存、不建数据库 — Dashboard 不是第二套真相源。
用户聊完新书 → 刷新页面 → 自动出现新卡片。

Usage:
    python shelf.py             # http://127.0.0.1:8766
    python shelf.py 9000        # 端口被占用时换一个
    python shelf.py --selftest  # 文件名解析规则自检
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

HOST = "127.0.0.1"          # 只绑本机回环, 绝不 0.0.0.0
DEFAULT_PORT = 8766
BASE_DIR = Path(__file__).resolve().parent
NOTES_DIR = BASE_DIR / "notes"
PROFILE_FILE = BASE_DIR / "profile.md"
MEMORY_FILE = BASE_DIR / "memory.md"
INDEX_FILE = BASE_DIR / "index.html"

# 与 agent.py 的 notes 命名一致: <书名>__by__<作者>_类型.md (无作者时省略 __by__ 段)
TYPE_BY_SUFFIX = {
    "_可视化脑图.md": "mindmap",
    "_幕布导入版.md": "outline",
}

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 数据解析
# ---------------------------------------------------------------------------
def parse_note_filename(name: str):
    """notes 文件名 → (书名, 作者, 类型); 无法解析返回 None (调用方跳过, 不抛异常)。"""
    for suffix, ntype in TYPE_BY_SUFFIX.items():
        if name.endswith(suffix):
            key = name[: -len(suffix)]
            break
    else:
        return None
    if "__by__" in key:
        book, author = key.split("__by__", 1)
    else:
        book, author = key, ""
    return (book, author, ntype) if book.strip() else None


def read_text(path: Path) -> str:
    """utf-8 读取; 失败返回空串 (等同无数据, 页面显示占位提示)。"""
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def scan_books() -> list[dict]:
    """实时扫描 notes/, 按 (书名, 作者) 把脑图/大纲配对成书, mtime 最新者为更新时间。"""
    books: dict[tuple[str, str], dict] = {}
    try:
        files = sorted(NOTES_DIR.glob("*.md"), key=lambda p: p.name)
    except OSError:
        files = []
    for p in files:
        parsed = parse_note_filename(p.name)
        if not parsed:
            continue
        book, author, ntype = parsed
        rec = books.setdefault((book, author), {
            "book": book, "author": author,
            "mindmap": False, "outline": False, "note_count": 0, "_mtime": 0.0,
        })
        rec[ntype] = True
        rec["note_count"] += 1
        try:
            rec["_mtime"] = max(rec["_mtime"], p.stat().st_mtime)
        except OSError:
            pass
    result = sorted(books.values(), key=lambda r: r["_mtime"], reverse=True)
    for r in result:
        mtime = r.pop("_mtime")
        r["updated_at"] = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M") if mtime else ""
    return result


def build_shelf_data() -> dict:
    books = scan_books()
    return {
        "stats": {
            "books": len(books),
            "notes": sum(b["note_count"] for b in books),
            "last_active": max((b["updated_at"] for b in books), default=""),
        },
        "books": books,
        "profile": read_text(PROFILE_FILE).strip(),
        "memory": read_text(MEMORY_FILE).strip(),
    }


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
class ShelfHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/api/shelf-data.json":
            try:
                payload = build_shelf_data()
            except Exception as e:
                self._send_json({"error": f"汇总书架数据失败: {e}"}, 500)
                return
            self._send_json(payload)
        elif url.path == "/api/note":
            self._handle_note(parse_qs(url.query))
        elif url.path in ("/", "/index.html"):
            self._send_file(INDEX_FILE, "text/html; charset=utf-8")
        else:
            self._send_json({"error": "not found"}, 404)

    # --- 笔记原文 ---
    def _handle_note(self, q):
        book = (q.get("book", [""])[0] or "").strip()
        author = (q.get("author", [""])[0] or "").strip()
        ntype = (q.get("type", [""])[0] or "").strip()
        if not book or ntype not in TYPE_BY_SUFFIX.values():
            self._send_json({"error": "参数不对: book 必填, type 为 mindmap|outline"}, 400)
            return
        # 只在实时扫描结果里按文件名匹配, 不用请求参数拼路径 → 无目录穿越可能
        target = None
        try:
            for p in NOTES_DIR.glob("*.md"):
                if parse_note_filename(p.name) == (book, author, ntype):
                    target = p
                    break
        except OSError:
            pass
        if target is None:
            label = "脑图" if ntype == "mindmap" else "大纲"
            self._send_json({"error": f"没有找到《{book}》的{label}笔记"}, 404)
            return
        try:
            text = target.read_text(encoding="utf-8")
        except Exception as e:
            self._send_json({"error": f"读取笔记失败: {e}"}, 500)
            return
        self._send(text.encode("utf-8"), "text/plain; charset=utf-8")

    # --- 响应工具 (统一带 Content-Length, 配合 HTTP/1.1 keep-alive) ---
    def _send(self, body: bytes, content_type: str, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, obj, status: int = 200):
        self._send(json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8", status)

    def _send_file(self, path: Path, content_type: str):
        try:
            body = path.read_bytes()
        except OSError as e:
            self._send_json({"error": f"{path.name} 读取失败: {e}"}, 500)
            return
        self._send(body, content_type)


def selftest() -> None:
    """文件名解析规则自检: python shelf.py --selftest"""
    assert parse_note_filename("1984__by__乔治·奥威尔_可视化脑图.md") == ("1984", "乔治·奥威尔", "mindmap")
    assert parse_note_filename("我与地坛__by__史铁生_幕布导入版.md") == ("我与地坛", "史铁生", "outline")
    assert parse_note_filename("红楼梦_可视化脑图.md") == ("红楼梦", "", "mindmap")
    assert parse_note_filename("杂项文件.md") is None
    assert parse_note_filename("README.txt") is None
    assert parse_note_filename("_可视化脑图.md") is None
    print("[OK] 解析规则自检通过")


def main():
    args = sys.argv[1:]
    if "--selftest" in args:
        selftest()
        return
    port = DEFAULT_PORT
    if args:
        try:
            port = int(args[0])
        except ValueError:
            print(f"[!] 无效端口: {args[0]}")
            sys.exit(1)
    try:
        server = ThreadingHTTPServer((HOST, port), ShelfHandler)
    except OSError as e:
        print(f"[!] 无法监听 {HOST}:{port} (端口可能被占用): {e}")
        print(f"    换个端口: python shelf.py {port + 1}")
        sys.exit(1)
    print(f"📖 书架已开张: http://{HOST}:{port}   (Ctrl+C 关闭)")
    print("   数据实时来自 notes/ · profile.md · memory.md, 刷新页面即可看到最新")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n书架打烊, 下次再见~")


if __name__ == "__main__":
    main()
