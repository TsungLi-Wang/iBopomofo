#!/usr/bin/env python3
"""Scrape real PTT article bodies from ptt.cc (no AI generation).

Designed for Johnny's local machine if the agent environment cannot reach ptt.cc.
Requires only Python 3 stdlib (+ optional bs4 if available; falls back to regex).

Usage:
  python3 scrape_ptt_boards.py \\
    --boards Stock,PC_Shopping,Tech_Job,WomenTalk,movie,Food,Lifeismoney,Soft_Job \\
    --pages-per-board 8 \\
    --out-dir /tmp/tw386-ptt-raw \\
    --sleep 0.4

Output:
  <out-dir>/<board>.jsonl   one article per line:
    {board, url, title, article_id, body}
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from html import unescape
from pathlib import Path

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
BASE = "https://www.ptt.cc"


class PttClient:
    def __init__(self, sleep: float = 0.4):
        self.sleep = sleep
        self.cookie = "over18=1"
        self.opener = urllib.request.build_opener()

    def get(self, path_or_url: str) -> str:
        if path_or_url.startswith("http"):
            url = path_or_url
        else:
            url = BASE + path_or_url
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": UA,
                "Cookie": self.cookie,
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        time.sleep(self.sleep)
        with self.opener.open(req, timeout=30) as resp:
            return resp.read().decode("utf-8", errors="replace")


def strip_tags(html: str) -> str:
    html = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", html)
    html = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", html)
    html = re.sub(r"(?is)<!--.*?-->", " ", html)
    html = re.sub(r"(?is)<br\s*/?>", "\n", html)
    html = re.sub(r"(?is)</div>", "\n", html)
    html = re.sub(r"(?is)<[^>]+>", " ", html)
    html = unescape(html)
    html = re.sub(r"[ \t\f\v]+", " ", html)
    html = re.sub(r"\n\s*\n+", "\n", html)
    return html.strip()


def list_index_articles(html: str, board: str) -> list[tuple[str, str]]:
    """Return list of (article_id_path, title). Skip 刪除/本文被刪除."""
    out: list[tuple[str, str]] = []
    # Each entry roughly: <div class="r-ent"> ... <div class="title"> <a href="/bbs/Board/M....html">title</a>
    for m in re.finditer(
        rf'href="(/bbs/{re.escape(board)}/M\.[^"]+\.html)"[^>]*>([^<]*)</a>',
        html,
    ):
        path, title = m.group(1), m.group(2).strip()
        if not title or "刪除" in title:
            continue
        out.append((path, title))
    return out


def prev_page_href(html: str) -> str | None:
    # <a class="btn wide" href="/bbs/Stock/index3934.html">‹ 上頁</a>
    m = re.search(r'href="(/bbs/[^"]+/index\d+\.html)"[^>]*>\s*‹\s*上頁', html)
    if m:
        return m.group(1)
    m = re.search(r'href="(/bbs/[^"]+/index\d+\.html)"[^>]*>[^<]*上頁', html)
    return m.group(1) if m else None


def extract_body(html: str) -> str:
    """Extract article main text only (no pushes)."""
    # Isolate main-content
    m = re.search(r'id="main-content"[^>]*>(.*)', html, re.S)
    if not m:
        return ""
    chunk = m.group(1)
    # Cut at first push
    chunk = re.split(r'<div class="push">', chunk, maxsplit=1)[0]
    # Remove metaline spans (作者/看板/標題/時間)
    chunk = re.sub(
        r'(?is)<div class="article-metaline[^"]*">.*?</div>', "\n", chunk
    )
    chunk = re.sub(
        r'(?is)<span class="article-meta-(?:tag|value)">.*?</span>', " ", chunk
    )
    # Remove richcontent (embedded images captions sometimes)
    chunk = re.sub(r'(?is)<div class="richcontent">.*?</div>', "\n", chunk)
    text = strip_tags(chunk)
    # Drop signature / footer noise
    lines = []
    for ln in text.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        if ln.startswith("※") or ln.startswith("--"):
            break
        if ln.startswith("https://www.ptt.cc/bbs/"):
            continue
        lines.append(ln)
    return "\n".join(lines)


def scrape_board(
    client: PttClient, board: str, pages: int, out_path: Path
) -> dict:
    stats = {
        "board": board,
        "pages_ok": 0,
        "pages_fail": 0,
        "articles_ok": 0,
        "articles_fail": 0,
        "body_chars": 0,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    seen_ids: set[str] = set()
    index_path = f"/bbs/{board}/index.html"
    with out_path.open("w", encoding="utf-8") as fout:
        for page_i in range(pages):
            try:
                html = client.get(index_path)
                stats["pages_ok"] += 1
            except Exception as e:
                stats["pages_fail"] += 1
                print(f"  [fail] index {board} page{page_i}: {e}", flush=True)
                break
            arts = list_index_articles(html, board)
            print(
                f"  [{board}] page {page_i+1}/{pages} index={index_path} articles={len(arts)}",
                flush=True,
            )
            for path, title in arts:
                aid = path.rsplit("/", 1)[-1]
                if aid in seen_ids:
                    continue
                seen_ids.add(aid)
                try:
                    ahtml = client.get(path)
                    body = extract_body(ahtml)
                    if not body or len(body) < 10:
                        stats["articles_fail"] += 1
                        continue
                    rec = {
                        "board": board,
                        "url": BASE + path,
                        "article_id": aid,
                        "title": title,
                        "body": body,
                    }
                    fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    stats["articles_ok"] += 1
                    stats["body_chars"] += len(body)
                except Exception as e:
                    stats["articles_fail"] += 1
                    print(f"  [fail] article {path}: {e}", flush=True)
            prev = prev_page_href(html)
            if not prev:
                print(f"  [{board}] no prev page, stop", flush=True)
                break
            index_path = prev
    return stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--boards",
        type=str,
        default="Stock,PC_Shopping,Tech_Job,WomenTalk,movie,Food,Lifeismoney,Soft_Job,MobileComm,car",
    )
    ap.add_argument("--pages-per-board", type=int, default=6)
    ap.add_argument("--out-dir", type=Path, default=Path("/tmp/tw386-ptt-raw"))
    ap.add_argument("--sleep", type=float, default=0.35)
    args = ap.parse_args()

    boards = [b.strip() for b in args.boards.split(",") if b.strip()]
    banned = {"Gossiping", "C_Chat", "gossiping", "c_chat"}
    boards = [b for b in boards if b not in banned]
    print(f"boards={boards}", flush=True)
    print(f"pages_per_board={args.pages_per_board}", flush=True)
    print(f"out_dir={args.out_dir}", flush=True)

    # connectivity probe
    client = PttClient(sleep=args.sleep)
    try:
        probe = client.get("/bbs/Stock/index.html")
        if "Stock" not in probe and "看板" not in probe:
            print("ERROR: unexpected response from ptt.cc", flush=True)
            return 2
        print("connectivity=OK ptt.cc reachable", flush=True)
    except Exception as e:
        print(f"connectivity=FAIL cannot reach ptt.cc: {e}", flush=True)
        print(
            "ACTION: run this script on a machine that can access ptt.cc "
            "(Johnny local). Do NOT substitute dumps or AI text.",
            flush=True,
        )
        return 3

    all_stats = []
    for board in boards:
        print(f"=== scrape board {board} ===", flush=True)
        outp = args.out_dir / f"{board}.jsonl"
        st = scrape_board(client, board, args.pages_per_board, outp)
        all_stats.append(st)
        print(
            f"  RESULT board={board} articles_ok={st['articles_ok']} "
            f"articles_fail={st['articles_fail']} pages_ok={st['pages_ok']} "
            f"body_chars={st['body_chars']}",
            flush=True,
        )

    summary_path = args.out_dir / "scrape_summary.json"
    summary_path.write_text(
        json.dumps(all_stats, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("=== TOTALS ===", flush=True)
    print(
        f"articles_ok={sum(s['articles_ok'] for s in all_stats)} "
        f"articles_fail={sum(s['articles_fail'] for s in all_stats)}",
        flush=True,
    )
    print(f"summary={summary_path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
