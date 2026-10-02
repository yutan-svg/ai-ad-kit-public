#!/usr/bin/env python3
"""生成の台帳。実際に投げたタスクを、**生成したあとに**記録して数える。

何に使うか: 「何を・何本・どのサービスで作ったか」と、サービスが返してきた使用量（トークン数・尺）を
案件ごとに残す。請求はアカウント単位でしか分かれないため、案件ごとの内訳はここで持ちます。
**このスクリプトは金額を出しません。** 実際の金額は各サービスの請求画面で確認してください。

使い方（案件フォルダのルートで）:
  記録: python3 scripts/cost_ledger.py log <task_id> [task_id...]
  集計: python3 scripts/cost_ledger.py report

生成スクリプト（generate_lines.py / generate_google.py / generate_talking_head.py）は、
投げたタスクを `out/takes-tasks.jsonl`・`out/google-tasks.jsonl` に1行ずつ残します。
その task_id を `log` に渡すと、返ってきた使用量つきで `costs/tasks.jsonl` に写します。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "lib"))
import seedance_api  # noqa: E402

LEDGER = Path("costs/tasks.jsonl")


def cmd_log(a: argparse.Namespace) -> int:
    seedance_api.load_project_env()
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    known: set[str] = set()
    if LEDGER.exists():
        known = {json.loads(l)["id"] for l in LEDGER.read_text(encoding="utf-8").splitlines() if l.strip()}
    with LEDGER.open("a", encoding="utf-8") as fh:
        for tid in a.task_ids:
            if tid in known:
                print(f"{tid}: 記録済み")
                continue
            r = seedance_api.get_task(None, tid)
            row = {
                "id": tid,
                "logged_at": time.strftime("%Y-%m-%d %H:%M"),
                "created_at": r.get("created_at"),
                "model": r.get("model"),
                "status": r.get("status"),
                "resolution": r.get("resolution", "720p"),
                "usage_tokens": (r.get("usage") or {}).get("total_tokens"),
                "duration_s": r.get("duration"),
            }
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            print(f'{tid}: 記録 model={row["model"]} tokens={row["usage_tokens"]}')
    return 0


def cmd_report(a: argparse.Namespace) -> int:
    if not LEDGER.exists():
        print(f"台帳がまだありません（{LEDGER}）")
        return 0
    rows = [json.loads(l) for l in LEDGER.read_text(encoding="utf-8").splitlines() if l.strip()]
    by_month: dict[str, dict] = {}
    for r in rows:
        month = time.strftime("%Y-%m", time.localtime(r["created_at"])) if r.get("created_at") else "不明"
        rec = by_month.setdefault(month, {"count": 0, "services": {}, "seconds": 0.0, "tokens": 0})
        rec["count"] += 1
        service = str(r.get("model") or "不明")
        rec["services"][service] = rec["services"].get(service, 0) + 1
        rec["seconds"] += float(r.get("duration_s") or 0)
        rec["tokens"] += int(r.get("usage_tokens") or 0)
    print(f"タスク数: {len(rows)}")
    for month, rec in sorted(by_month.items()):
        services = " / ".join(f"{k} {v}本" for k, v in sorted(rec["services"].items()))
        line = f"  {month}: {rec['count']}本  {services}"
        if rec["seconds"]:
            line += f"  合計 {rec['seconds']:g}秒"
        if rec["tokens"]:
            line += f"  トークン {rec['tokens']:,}"
        print(line)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("log", help="投げたタスクを台帳に記録する")
    p.add_argument("task_ids", nargs="+", help="記録するタスクID")
    p.set_defaults(func=cmd_log)

    p = sub.add_parser("report", help="台帳を集計する（何本・どのサービス・使用量）")
    p.set_defaults(func=cmd_report)

    a = ap.parse_args()
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
