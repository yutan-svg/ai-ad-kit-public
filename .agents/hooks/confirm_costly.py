#!/usr/bin/env python3
"""Antigravity の PreToolUse フック: お金と成果物が動くコマンドの前に、必ず人へ確認を出す。

何をするか: エージェントがターミナルで走らせようとしているコマンドを見て、
生成（映像・読み上げ・参照画像）と書き出しに当たるものなら `force_ask` を返します。
`force_ask` は「以前に『常に許可』を押していても、毎回必ず聞く」という意味です。
それ以外のコマンドは `ask`（Antigravity の通常の確認。許可の記憶が効く）を返すだけで、邪魔をしません。
`--dry-run` / `--check-only` / `--check` が付いた実行はお金が動かないので通常どおりにします。

入出力（公式仕様 https://antigravity.google/docs/ide/hooks/ ）:
  標準入力  {"toolCall": {"name": "run_command", "args": {...}}, "stepIdx": …, "conversationId": …}
  標準出力  {"decision": "force_ask" | "ask" | "allow" | "deny", "reason": "…"}

このフックは「止める」ためのものではありません。**人が内容を見て決める場面を必ず作る**ためのものです。
キット側の承諾ゲート（scripts/approve.py と out/ の記録）と二重になりますが、二重で構いません。
"""
from __future__ import annotations

import json
import sys

# この語がコマンドに含まれていたら、毎回必ず人に聞く。
WATCH = {
    "remotion render": "動画ファイル（mp4）の書き出し",
    "npm run render": "動画ファイル（mp4）の書き出し",
    "generate_lines.py": "セリフつきクリップの生成（費用がかかります）",
    "generate_talking_head.py": "トーキングヘッドの生成（費用がかかります）",
    "generate_tts.py": "読み上げ音声の生成（費用がかかります）",
    "generate_google.py": "Google（Veo／Omni／Nano Banana）での生成（費用がかかります）",
}
# これが付いていればお金は動かない（送る内容の確認だけ）。
SAFE_FLAGS = ("--dry-run", "--check-only", "--check ", "--check\n", "--help")


def strings(obj) -> list[str]:
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, dict):
        return [s for v in obj.values() for s in strings(v)]
    if isinstance(obj, list):
        return [s for v in obj for s in strings(v)]
    return []


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:  # 読めないときは通常の確認に任せる（フックで作業を止めない）
        print(json.dumps({"decision": "ask"}))
        return 0
    args = (payload.get("toolCall") or {}).get("args") or {}
    text = " ".join(strings(args))
    lowered = text.lower()
    if any(flag.strip() in lowered for flag in SAFE_FLAGS):
        print(json.dumps({"decision": "ask", "reason": "内容の確認だけ（費用は発生しません）"}, ensure_ascii=False))
        return 0
    for needle, why in WATCH.items():
        if needle in text:
            print(json.dumps({
                "decision": "force_ask",
                "reason": f"{why}。何を・何本・いくらかかるかを確かめてから許可してください。",
            }, ensure_ascii=False))
            return 0
    print(json.dumps({"decision": "ask"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
