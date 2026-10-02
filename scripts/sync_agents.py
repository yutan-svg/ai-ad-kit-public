#!/usr/bin/env python3
"""`.claude/` の手順書と検査役を `.agents/`（Antigravity 用）へ写す。

なぜ要るか: 同じキットを Claude デスクトップアプリ／ChatGPT（Codex）／Antigravity のどれでも開けるように
しています。手順書（スキル）と検査役（サブエージェント）の置き場所だけがアプリごとに違うので、
**正本を `.claude/` に1つだけ置き、こちらから機械で写します。** `.agents/` を手で編集しないでください
（次の同期で上書きされます）。

  正本                         写し
  .claude/skills/<名>/SKILL.md  →  .agents/skills/<名>/SKILL.md（そのまま。frontmatter の description が必須）
  .claude/agents/<名>.md        →  .agents/agents/<名>.md（frontmatter だけ Antigravity の書式に直す）

frontmatter の直し方（公式ドキュメントで確認できた項目だけを使う。2026-09-17 確認）:
  - tools: Claude 側の名前 → Antigravity 側の名前。公式に名前が確認できるのは
    `run_command` と `view_file` の2つだけなので、Glob / Grep は落とします
    （検査役は `run_command` から grep や find を呼べるので実務上は困りません）。
  - model: Antigravity は `inherit` / `flash` / `pro` の3段階。opus → pro、sonnet/haiku → flash。
  出典: https://antigravity.google/docs/subagents/ ／ https://antigravity.google/docs/ide/skills/

使い方（キットのルートで）:
  python3 scripts/sync_agents.py            # `.agents/` を作り直す
  python3 scripts/sync_agents.py --check    # 差分があるかだけ見る（変更しない。終了コード1で不一致）

`scripts/check_parity.py` がこの `--check` を呼びます。
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_SKILLS = ROOT / ".claude" / "skills"
SRC_AGENTS = ROOT / ".claude" / "agents"
DST_SKILLS = ROOT / ".agents" / "skills"
DST_AGENTS = ROOT / ".agents" / "agents"

TOOL_MAP = {"Bash": "run_command", "Read": "view_file"}
MODEL_MAP = {"opus": "pro", "sonnet": "flash", "haiku": "flash", "inherit": "inherit"}

NOTICE = ("<!-- このファイルは scripts/sync_agents.py が {src} から作った写しです。"
          "直接編集せず、元のファイルを直してから同期してください。 -->")


def split_frontmatter(text: str) -> tuple[list[str], str]:
    """(frontmatter の行, 本文) に分ける。frontmatter が無ければ ([], 全文)。"""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return [], text
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return lines[1:i], "\n".join(lines[i + 1:]).lstrip("\n")
    return [], text


def parse_frontmatter(fm_lines: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in fm_lines:
        if ":" in line and not line.startswith((" ", "\t", "#")):
            key, _, value = line.partition(":")
            out[key.strip()] = value.strip()
    return out


def yaml_value(value: str) -> str:
    """: や # を含む値は引用符でくくる（YAML として壊さないため）。"""
    if value.startswith(("[", "{", '"', "'")):
        return value
    if ": " in value or value.endswith(":") or value.startswith(("#", "&", "*", "!", "|", ">", "%", "@", "`")):
        return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'
    return value


def skill_text(src: Path) -> str:
    """スキルはそのまま写す（Antigravity も frontmatter の description を読む書式）。"""
    text = src.read_text(encoding="utf-8")
    fm_lines, body = split_frontmatter(text)
    if not fm_lines:
        raise SystemExit(f"{src}: frontmatter がありません（description が必須です）")
    if "description" not in parse_frontmatter(fm_lines):
        raise SystemExit(f"{src}: frontmatter に description がありません（Antigravity では必須）")
    head = "---\n" + "\n".join(fm_lines) + "\n---\n"
    return head + NOTICE.format(src=rel(src)) + "\n\n" + body.rstrip("\n") + "\n"


def agent_text(src: Path) -> str:
    """検査役は frontmatter を Antigravity の書式に直して写す。"""
    fm_lines, body = split_frontmatter(src.read_text(encoding="utf-8"))
    fm = parse_frontmatter(fm_lines)
    if not fm.get("description"):
        raise SystemExit(f"{src}: frontmatter に description がありません（Antigravity では必須）")
    name = fm.get("name") or src.stem
    tools_in = [t.strip() for t in fm.get("tools", "").split(",") if t.strip()]
    tools = [TOOL_MAP[t] for t in tools_in if t in TOOL_MAP]
    dropped = [t for t in tools_in if t not in TOOL_MAP]
    model = MODEL_MAP.get(fm.get("model", "").lower(), "inherit")
    out = ["---", f"name: {name}", f"description: {yaml_value(fm['description'])}"]
    if tools:
        out.append("tools: [" + ", ".join(tools) + "]")
    out.append(f"model: {model}")
    out.append("---")
    out.append(NOTICE.format(src=rel(src)))
    if dropped:
        out.append(f"<!-- Claude 側の {', '.join(dropped)} は Antigravity の公式ドキュメントに"
                   "対応する名前が無いため落としました。run_command から grep / find を使ってください。 -->")
    out.append("")
    out.append(body.rstrip("\n"))
    return "\n".join(out) + "\n"


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def planned() -> dict[Path, str]:
    """`.agents/` に置くべきファイルの中身（パス → テキスト）。"""
    plan: dict[Path, str] = {}
    for skill_dir in sorted(p for p in SRC_SKILLS.iterdir() if p.is_dir()) if SRC_SKILLS.is_dir() else []:
        src = skill_dir / "SKILL.md"
        if not src.exists():
            continue
        plan[DST_SKILLS / skill_dir.name / "SKILL.md"] = skill_text(src)
        for extra in sorted(skill_dir.rglob("*")):
            if extra.is_file() and extra != src:
                plan[DST_SKILLS / skill_dir.name / extra.relative_to(skill_dir)] = extra.read_text(encoding="utf-8")
    for src in sorted(SRC_AGENTS.glob("*.md")) if SRC_AGENTS.is_dir() else []:
        plan[DST_AGENTS / src.name] = agent_text(src)
    if not plan:
        raise SystemExit(".claude/skills と .claude/agents が見つかりません（キットのルートで実行してください）")
    return plan


def current() -> dict[Path, str]:
    out: dict[Path, str] = {}
    for base in (DST_SKILLS, DST_AGENTS):
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            if p.is_file() and p.name != ".DS_Store":
                out[p] = p.read_text(encoding="utf-8")
    return out


def diff() -> list[str]:
    plan, now = planned(), current()
    problems: list[str] = []
    for path, text in plan.items():
        if path not in now:
            problems.append(f"足りない: {rel(path)}")
        elif now[path] != text:
            problems.append(f"中身が違う: {rel(path)}")
    for path in now:
        if path not in plan:
            problems.append(f"余分: {rel(path)}（元の .claude 側にありません）")
    return problems


def write() -> int:
    plan = planned()
    for base in (DST_SKILLS, DST_AGENTS):
        if base.exists():
            shutil.rmtree(base)
    for path, text in plan.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    print(f"✓ .agents/ に {len(plan)} ファイルを写しました（元は .claude/）")
    for path in sorted(plan, key=rel):
        print("   " + rel(path))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="差分があるかだけ見る（書き換えない）")
    a = ap.parse_args()
    if not a.check:
        return write()
    problems = diff()
    if problems:
        print("✗ .claude/ と .agents/ が一致していません:")
        for p in problems:
            print("   " + p)
        print("  直し方: python3 scripts/sync_agents.py")
        return 1
    print("✓ .claude/ と .agents/ は一致しています")
    return 0


if __name__ == "__main__":
    sys.exit(main())
