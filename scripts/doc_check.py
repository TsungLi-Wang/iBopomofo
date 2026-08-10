#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""文件體檢 —— 抓「文件說的」跟「實際的」不一致。

為什麼有這支
------------
2026-08-10 派一個完全沒有前文的 AI 去讀交接文件，測「照文件能不能接手」。
結果是不能：現役版本在五個檔案裡有四種說法、交班檔指向不存在的檔、
Key Files 列了已刪除的程式檔、pbxproj 新 ID 起點差了兩百號。

那些全都是機器兩秒能抓到的東西。**不該靠派 AI 稽核才發現。**

設計原則
--------
版本號只能存在一個地方（plist ＋ CHANGELOG 最上面的已發布段落）。
說明文件一律不寫版本號，改成指向那裡。這樣就不可能不一致——
不是靠人記得同步，是靠「根本沒有第二份可以漂」。
"""

import os
import plistlib
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 這些檔案不准出現版本號（要寫就寫「見 CHANGELOG」）
NO_VERSION_DOCS = ["CLAUDE.md", "AGENTS.md", "AI_HANDOFF_PROMPT.md"]
# 這些檔案會提到歷史版本，只檢查路徑不檢查版本
PATH_ONLY_DOCS = ["README.md"]
# 這兩份本質是歷史紀錄 —— 提到當時存在的檔案是正常的，不檢查路徑：
#   CHANGELOG.md          每版當時的檔案
#   AI_HANDOFF_ARCHIVE.md 已封存的交班日誌

VERSION_RE = re.compile(r"\bv?(\d+)\.(\d+)\.(\d+)\b")
# 反引號裡、看起來像路徑的東西
PATH_RE = re.compile(r"`([~/][^`\s]+|[A-Za-z0-9_./-]+\.(?:swift|mm|h|cpp|py|sh|tsv|txt|md|plist|json|bin))`")

# 說明文字裡會刻意引用歷史上的錯誤值（例如解釋「以前寫成 v2.7.0」），
# 那不是漂移。在該行結尾加 <!-- doc-check-ignore --> 就會跳過。
IGNORE_MARK = "doc-check-ignore"

_repo_files = None


def repo_file_index():
    """全 repo 檔名索引 —— 文件常只寫檔名不寫目錄，不該誤判成不存在。"""
    global _repo_files
    if _repo_files is None:
        _repo_files = {}
        for dirpath, dirnames, filenames in os.walk(ROOT):
            dirnames[:] = [d for d in dirnames
                           if d not in {".git", "build", "dist", "DerivedData"}
                           and not d.startswith("dd-") and not d.startswith("build-")]
            for fn in filenames:
                _repo_files.setdefault(fn, os.path.join(dirpath, fn))
    return _repo_files


problems = []
checked = {"版本": 0, "路徑": 0, "其他": 0}


def fail(kind, where, msg):
    problems.append(f"  ✗ [{kind}] {where}\n      {msg}")


def read(path):
    try:
        with open(os.path.join(ROOT, path), encoding="utf-8") as fh:
            return fh.readlines()
    except OSError:
        return None


def current_version():
    """真源：plist。"""
    p = os.path.join(ROOT, "Source/McBopomofo-Info.plist")
    with open(p, "rb") as fh:
        d = plistlib.load(fh)
    return d["CFBundleShortVersionString"], d["CFBundleVersion"]


def check_two_plists(short, build):
    p = os.path.join(ROOT, "Source/Installer/Installer-Info.plist")
    with open(p, "rb") as fh:
        d = plistlib.load(fh)
    checked["其他"] += 1
    if (d["CFBundleShortVersionString"], d["CFBundleVersion"]) != (short, build):
        fail("版本", "Source/Installer/Installer-Info.plist",
             f"{d['CFBundleShortVersionString']}/{d['CFBundleVersion']} "
             f"≠ McBopomofo-Info.plist 的 {short}/{build}（發版時兩份都要 bump）")


def check_changelog_top(short, build):
    lines = read("CHANGELOG.md")
    if lines is None:
        fail("其他", "CHANGELOG.md", "檔案不存在")
        return
    checked["其他"] += 1
    for line in lines:
        m = re.match(r"##\s*\[(\d+\.\d+\.\d+)\]", line.strip())
        if m:
            if m.group(1) != short:
                fail("版本", "CHANGELOG.md",
                     f"最上面的已發布段落是 [{m.group(1)}]，但 plist 是 {short}")
            return
    fail("版本", "CHANGELOG.md", "找不到任何 ## [x.y.z] 已發布段落")


# 只抓「宣稱現在是哪一版」的句子。歷史引用（since v2.3.0、v2.13.0+ 的規則）
# 是有用的資訊，不該擋。會漂的只有「現況宣稱」這一種。
CURRENT_CLAIM = re.compile(
    r"(現役|目前版本|現在版本|Current line|Current version|Current release|最後更新)")


def check_no_versions_in_docs():
    for doc in NO_VERSION_DOCS:
        lines = read(doc)
        if lines is None:
            fail("其他", doc, "檔案不存在（但被列為必讀）")
            continue
        for i, line in enumerate(lines, 1):
            if IGNORE_MARK in line or not CURRENT_CLAIM.search(line):
                continue
            m = VERSION_RE.search(line)
            checked["版本"] += 1
            if m:
                fail("版本", f"{doc}:{i}",
                     f"這行宣稱現況並寫死了版本 `{m.group(0)}` —— 現況版本只能存在 "
                     f"plist 與 CHANGELOG。改寫成「現役版本見 CHANGELOG.md 最上面那段」，"
                     f"這樣就不會漂。\n      原文：{line.strip()[:90]}")


def check_paths():
    docs = NO_VERSION_DOCS + PATH_ONLY_DOCS
    for doc in docs:
        lines = read(doc)
        if lines is None:
            continue
        for i, line in enumerate(lines, 1):
            for m in PATH_RE.finditer(line):
                raw = m.group(1)
                if any(x in raw for x in ("<", ">", "*", "…")):
                    continue
                # HTTP 端點不是檔案路徑（/completion、/v1/audio/transcriptions）
                if raw.startswith("/") and "." not in os.path.basename(raw):
                    continue
                if IGNORE_MARK in line:
                    continue
                if "{" in raw:
                    raw = raw.split("{")[0] + "h"
                checked["路徑"] += 1
                if raw.startswith("~"):
                    ok = os.path.exists(os.path.expanduser(raw))
                elif "/" in raw:
                    ok = os.path.exists(os.path.join(ROOT, raw))
                else:
                    # 只寫檔名 → 全 repo 找得到就算數
                    ok = os.path.basename(raw) in repo_file_index()
                if not ok:
                    fail("路徑", f"{doc}:{i}", f"`{raw}` 不存在")


def check_pbxproj_ids():
    pbx = os.path.join(ROOT, "McBopomofo.xcodeproj/project.pbxproj")
    try:
        with open(pbx, encoding="utf-8") as fh:
            ids = sorted(set(re.findall(r"FACE0(\d{3})", fh.read())))
    except OSError:
        return
    if not ids:
        return
    actual_next = int(ids[-1]) + 1
    lines = read("AGENTS.md") or []
    checked["其他"] += 1
    for i, line in enumerate(lines, 1):
        if "FACE0" in line and ("下一個" in line or "start at" in line):
            m = re.search(r"FACE0(\d{3})\+", line)
            if m and int(m.group(1)) < actual_next:
                fail("其他", f"AGENTS.md:{i}",
                     f"新檔 ID 起點寫 FACE0{m.group(1)}+，但 pbxproj 已用到 "
                     f"FACE0{ids[-1]} —— 下一個應該是 FACE0{actual_next:03d}+（撞號會讓專案檔開不起來）")
            return


def check_git_clean_for_release():
    try:
        out = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                             capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return
    dirty = [l for l in out.splitlines() if "Source/Engine/build-test/" in l]
    if dirty:
        fail("其他", "Source/Engine/build-test/",
             "被 git 追蹤的建置產物髒了（跑過 ctest）。發版前要 `git restore` 它，"
             "否則 app 的 GitRevision 會被戳成 dirty。")


def main():
    short, build = current_version()
    print(f"真源版本（Source/McBopomofo-Info.plist）：{short} / build {build}\n")
    check_two_plists(short, build)
    check_changelog_top(short, build)
    check_no_versions_in_docs()
    check_paths()
    check_pbxproj_ids()
    check_git_clean_for_release()

    total = sum(checked.values())
    if problems:
        print(f"發現 {len(problems)} 個問題（檢查了 {total} 項）：\n")
        print("\n".join(problems))
        print("\n版本號請只留在 plist 與 CHANGELOG；文件寫「見 CHANGELOG」即可。")
        return 1
    print(f"✅ 全部通過（檢查了 {total} 項：版本、路徑、pbxproj ID、建置產物）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
