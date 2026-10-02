#!/usr/bin/env python3
"""指示書と手順書が、どのアプリで開いても同じ内容かを確かめる。

このキットは3つのアプリで開けます。読まれるファイルの名前だけが違い、中身は同じでなければいけません。

  Claude デスクトップアプリ  → CLAUDE.md ／ .claude/skills ／ .claude/agents
  ChatGPT（Codex）           → AGENTS.md
  Antigravity                → GEMINI.md ／ .agents/rules ／ .agents/skills ／ .agents/agents

確かめること:
  1. CLAUDE.md ・ AGENTS.md ・ GEMINI.md の中身が1バイトも違わないこと
  2. `.agents/` が `.claude/` の写しとして最新であること（scripts/sync_agents.py --check）
  3. Antigravity 側に必要なファイル（.agents/rules/00-confirm.md、.agents/hooks.json）があること

使い方（キットのルートで）:
  python3 scripts/check_parity.py          # 確かめるだけ（不一致なら終了コード 1）
  python3 scripts/check_parity.py --fix    # CLAUDE.md を正本にして他を揃え、.agents/ を作り直す

**正本は CLAUDE.md と `.claude/` です。** AGENTS.md / GEMINI.md / `.agents/` を手で編集しないでください。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[0]

PRIMARY = ROOT / "CLAUDE.md"
MIRRORS = [ROOT / "AGENTS.md", ROOT / "GEMINI.md"]
REQUIRED = [
    ROOT / ".agents" / "rules" / "00-confirm.md",
    ROOT / ".agents" / "hooks.json",
]


def check_docs() -> list[str]:
    problems: list[str] = []
    if not PRIMARY.exists():
        return [f"{PRIMARY.name} がありません（指示書の正本です）"]
    base = PRIMARY.read_text(encoding="utf-8")
    for m in MIRRORS:
        if not m.exists():
            problems.append(f"{m.name} がありません（{PRIMARY.name} と同じ内容で置きます）")
        elif m.read_text(encoding="utf-8") != base:
            problems.append(f"{m.name} が {PRIMARY.name} と違います")
    return problems


def check_required() -> list[str]:
    problems: list[str] = []
    for p in REQUIRED:
        if not p.exists():
            problems.append(f"{p.relative_to(ROOT)} がありません")
    hooks = ROOT / ".agents" / "hooks.json"
    if hooks.exists():
        try:
            json.loads(hooks.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            problems.append(f".agents/hooks.json が JSON として読めません: {exc}")
    return problems


def check_mirror() -> tuple[list[str], str]:
    r = subprocess.run([sys.executable, str(HERE / "sync_agents.py"), "--check"],
                       capture_output=True, text=True)
    body = (r.stdout or "") + (r.stderr or "")
    return ([] if r.returncode == 0 else [body.strip()]), body.strip()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fix", action="store_true", help="CLAUDE.md を正本にして揃える（.agents/ も作り直す）")
    a = ap.parse_args()

    if a.fix:
        base = PRIMARY.read_text(encoding="utf-8")
        for m in MIRRORS:
            if not m.exists() or m.read_text(encoding="utf-8") != base:
                m.write_text(base, encoding="utf-8")
                print(f"✓ {m.name} を {PRIMARY.name} に合わせました")
        r = subprocess.run([sys.executable, str(HERE / "sync_agents.py")])
        if r.returncode != 0:
            return r.returncode

    problems = check_docs()
    mirror_problems, mirror_out = check_mirror()
    problems += mirror_problems
    problems += check_required()

    if problems:
        print("✗ 指示書・手順書が揃っていません:")
        for p in problems:
            for line in str(p).splitlines():
                print("   " + line)
        print("\n  直し方: python3 scripts/check_parity.py --fix")
        return 1
    print("✓ CLAUDE.md / AGENTS.md / GEMINI.md は同じ内容です")
    print("✓ " + mirror_out.lstrip("✓ "))
    print("✓ .agents/rules/00-confirm.md と .agents/hooks.json があります")
    return 0


if __name__ == "__main__":
    sys.exit(main())
