#!/usr/bin/env python3
"""聞き取りの記録（knowledge/project.md）が埋まっているかを機械で確かめる門。

AI が聞き取った内容をチャットに残したままファイルに書かないと、次のチャット・別の AI・
別の担当者に何も引き継がれません。実際に、聞き取りを終えて台本まで進んだのに
`knowledge/project.md` が雛形のままだったことがありました。この門は、その状態で
リサーチ・生成・検査・書き出しに進むのを止めます。

使い方:
  python3 scripts/check_project.py --for research   # 商材と届ける相手が書けているか
  python3 scripts/check_project.py --for script     # 上に加えて、台本前の3つと着地
  python3 scripts/check_project.py --for generate   # script と同じ（生成・検査・書き出しの前）

止まったら、依頼主に聞いた答えを `knowledge/project.md` の該当欄に書いてから、もう一度実行します。
「たぶんこうだろう」で埋めてはいけません（RULES.md 第2部）。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PROJECT_MD = "knowledge/project.md"

# 段階ごとに、埋まっていなければ止める欄（見出し番号, 欄の名前の先頭）
REQUIRED: dict[str, list[tuple[int, str]]] = {
    "research": [
        (1, "サービス・商品の名前"), (1, "何をするものか"), (1, "提供している会社"), (1, "情報の出どころ"),
        (2, "どんな人か"), (2, "いま困っていること"),
    ],
}
REQUIRED["script"] = REQUIRED["research"] + [
    (2, "いま信じていること"), (2, "行動しない言い訳"),
    (3, "画面に出るのは誰か"), (3, "冒頭は"), (3, "最後にしてほしい行動"),
    (3, "着地"), (3, "伝えたいこと 1"),
]
REQUIRED["generate"] = REQUIRED["script"]

_HEAD = re.compile(r"^## (\d+)\. ")
_ROW = re.compile(r"^\|\s*(.+?)\s*\|\s*(.*?)\s*\|\s*$")


def parse(text: str) -> dict[int, dict[str, str]]:
    """見出し番号 → {欄の名前: 値} を返す。値は空なら ''。"""
    out: dict[int, dict[str, str]] = {}
    sec = 0
    for line in text.splitlines():
        m = _HEAD.match(line)
        if m:
            sec = int(m.group(1))
            out.setdefault(sec, {})
            continue
        if sec == 0:
            continue
        fields = out[sec]
        m = _ROW.match(line)
        if m and not set(m.group(1)) <= set("-: ") and m.group(1) not in ("項目", "決めること"):
            fields[m.group(1)] = m.group(2)
            continue
        m = re.match(r"^(\d)\.\s*\|?\s*(.*)$", line)
        if m and sec == 3:
            fields[f"伝えたいこと {m.group(1)}"] = m.group(2).strip()
            continue
        m = re.match(r"^着地（[^）]*）\s*[:：]\s*(.*)$", line)
        if m and sec == 3:
            fields["着地"] = m.group(1).strip()
    return out


def missing(text: str, stage: str) -> list[str]:
    fields = parse(text)
    gaps: list[str] = []
    for sec, prefix in REQUIRED[stage]:
        rows = fields.get(sec, {})
        hit = [k for k in rows if k.startswith(prefix)]
        if not hit:
            gaps.append(f"§{sec} 「{prefix}」の欄が見つかりません（雛形が壊れています）")
        elif not rows[hit[0]].strip():
            gaps.append(f"§{sec} {hit[0]}")
    return gaps


def check(root: Path, stage: str, quiet: bool = False) -> int:
    path = root / PROJECT_MD
    if not path.exists():
        print(f"✗ {PROJECT_MD} がありません")
        return 1
    gaps = missing(path.read_text(encoding="utf-8"), stage)
    if not gaps:
        if not quiet:
            print(f"✓ {PROJECT_MD} は「{stage}」に必要な欄が埋まっています")
        return 0
    print(f"✗ 聞き取りの記録が足りないので止めます（{PROJECT_MD}、段階: {stage}）。空欄:")
    for g in gaps:
        print(f"  - {g}")
    print("  依頼主に聞いた答えをファイルに書いてから、もう一度実行してください。推測で埋めてはいけません。")
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--for", dest="stage", choices=sorted(REQUIRED), default="script")
    ap.add_argument("--root", default=".", help="キットのフォルダ（既定: カレント）")
    a = ap.parse_args()
    return check(Path(a.root).resolve(), a.stage)


if __name__ == "__main__":
    sys.exit(main())
