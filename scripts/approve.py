#!/usr/bin/env python3
"""承諾を「人に聞いて、記録に残してから」でないと進めないようにする門。

決まりは2つ（RULES.md 第1部5節）。どちらもこのスクリプトが記録を作り、記録が無ければ先へ進めません。

  1. 書き出し（mp4 を作る）   → out/approval.json
  2. 費用のかかる生成         → out/generation-approval.json

使い方（案件フォルダのルートで）:

  # 書き出しの承諾を取る（何を書き出すかを表示して y/N を聞く）
  python3 scripts/approve.py --composition ad-9x16 --out out/ad-9x16.mp4

  # 書き出してよいかの確認だけ（remotion.config.ts と npm run render が自動で呼ぶ）
  python3 scripts/approve.py --check --composition ad-9x16 --out out/ad-9x16.mp4

  # 生成の承諾を取る（何を・何本・どのサービスで作るかを表示して y/N を聞く）
  python3 scripts/approve.py --generation --ids s1,s2 --takes 1 --service seedance

**AI がこのスクリプトの代わりに記録を書いてはいけません。** 対話（tty）でなければ承諾は取れません
（自動実行の中で承諾が「取れてしまう」ことを防ぐため、非 tty では失敗します）。
書き出しの承諾は、承諾したあとに `src/scenes.ts` を書き換えると自動的に無効になります（別の成果物になるため）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _gates  # noqa: E402
from _config import caption_rows, load_config, parse_scenes, rel, resolve, scene_files  # noqa: E402


CHAT_QUOTE: str | None = None  # --chat で渡された依頼主の返答（クラウド環境など tty が無いとき）
AFFIRMATIVE = ("y", "yes", "はい", "ok", "OK", "承諾", "お願い", "進めて", "よい", "良い", "大丈夫")


def ask(question: str) -> bool:
    """対話で y/N を聞く。tty でなければ、--chat で渡された依頼主の返答の原文だけを承諾として扱う。

    クラウドの作業環境（AI Studio など）には端末が無いので、AI がチャットで内容を示し、依頼主が返した
    文言をそのまま --chat に渡す。記録には channel=chat と原文が残る（端末の対話より弱い経路なので区別する）。
    AI が自分で肯定の文を作って渡すことは禁止（RULES.md 第1部0節）。"""
    if sys.stdin.isatty():
        answer = input(question).strip().lower()
        return answer in ("y", "yes")
    if not CHAT_QUOTE:
        raise SystemExit(
            "✗ 承諾は対話でしか記録できません（いまは対話ではありません）。\n"
            "  端末が無い環境では、内容をチャットで依頼主に示し、返ってきた文言をそのまま\n"
            "    --chat \"<依頼主の返答の原文>\"\n"
            "  に渡してください。AI が肯定の文を作って渡してはいけません。")
    print(question + f"（チャット経由: 「{CHAT_QUOTE}」）")
    return any(w.lower() in CHAT_QUOTE.lower() for w in AFFIRMATIVE)


def consent_meta() -> dict[str, Any]:
    return {"channel": "chat", "quote": CHAT_QUOTE} if CHAT_QUOTE else {"channel": "tty"}


def scene_summary(cfg: dict[str, Any]) -> tuple[int, float, list[str]]:
    total = 0.0
    count = 0
    captions: list[str] = []
    for f in scene_files(cfg):
        for sc in parse_scenes(f.read_text(encoding="utf-8")):
            count += 1
            total += sc.get("durationSeconds") or 0.0
            cap = sc.get("caption")
            if cap:
                captions.append(f"{sc['id_str']}: " + " / ".join(caption_rows(cap)))
    return count, total, captions


def newest_scene_mtime(cfg: dict[str, Any]) -> tuple[float, str]:
    newest = 0.0
    name = ""
    for f in scene_files(cfg):
        m = f.stat().st_mtime
        if m > newest:
            newest, name = m, rel(cfg, f)
    return newest, name


def norm_out(cfg: dict[str, Any], value: str | None) -> str:
    return rel(cfg, resolve(cfg, value)) if value else ""


# ---------------------------------------------------------------------------
# 書き出しの承諾
# ---------------------------------------------------------------------------
def cmd_render_approval(a: argparse.Namespace, cfg: dict[str, Any]) -> int:
    out = norm_out(cfg, a.out)
    comp = a.composition or ""
    if not out and not comp:
        raise SystemExit("--composition か --out のどちらかは指定してください")
    count, total, captions = scene_summary(cfg)
    if count == 0:
        raise SystemExit("シーンが1つもありません（src/scenes.ts が空です）。書き出すものがありません")
    _gates.check_preflight_passed(cfg)
    print("=== 書き出しの承諾 ===")
    print(f"  コンポジション: {comp or '(未指定)'}")
    print(f"  書き出し先    : {out or '(未指定)'}")
    print(f"  シーン数      : {count}   合計 {total:.2f} 秒")
    for line in captions[:12]:
        print(f"    - {line}")
    if len(captions) > 12:
        print(f"    …ほか {len(captions) - 12} シーン")
    print("  ※ここから動画ファイルを作ります。確認だけなら Studio と静止画で足ります")
    if not ask("  この内容で書き出してよいですか？ [y/N]: "):
        print("中止しました（承諾は記録しません）")
        return 1
    path = _gates.resolve(cfg, _gates.RENDER_APPROVAL)
    data = _gates.read_json(path, {})
    artifacts = [x for x in data.get("artifacts", []) if x.get("out") != out or x.get("composition") != comp]
    artifacts.append({
        "composition": comp, "out": out, "scenes": count, "total_seconds": round(total, 2),
        "approved_at": _gates.now(), "approved_at_epoch": _gates.now_epoch(), **consent_meta(),
    })
    data["artifacts"] = artifacts
    _gates.write_json(path, data)
    print(f"✓ 承諾を記録しました -> {_gates.RENDER_APPROVAL}")
    return 0


def cmd_check(a: argparse.Namespace, cfg: dict[str, Any]) -> int:
    _gates.check_project(cfg, "generate")
    _gates.check_preflight_passed(cfg)
    out = norm_out(cfg, a.out)
    comp = a.composition or ""
    path = _gates.resolve(cfg, _gates.RENDER_APPROVAL)
    how = ("  承諾の取り方（人に見せて y/N を聞きます）:\n"
           f"    python3 scripts/approve.py"
           + (f" --composition {comp}" if comp else "")
           + (f" --out {out}" if out else "") + "\n")
    if not path.exists():
        print("✗ 書き出しの承諾がありません（out/approval.json が無い）。")
        print(how, end="")
        return 1
    data = _gates.read_json(path, {})
    hit = None
    for rec in data.get("artifacts", []):
        if out and rec.get("out") == out:
            hit = rec
            break
        if not out and comp and rec.get("composition") == comp:
            hit = rec
            break
    if hit is None:
        print(f"✗ この成果物の承諾がありません: {out or comp}")
        approved = ", ".join(f"{r.get('out') or r.get('composition')}" for r in data.get("artifacts", []))
        print(f"  承諾済み: {approved or '（なし）'}")
        print("  一度得た承諾は、その成果物にだけ有効です（別の比率・別の版は別の成果物）。")
        print(how, end="")
        return 1
    newest, name = newest_scene_mtime(cfg)
    if float(hit.get("approved_at_epoch", 0)) < newest:
        print(f"✗ 承諾のあとで {name} が更新されています（承諾 {hit.get('approved_at')}）。")
        print("  中身が変わったものは別の成果物です。もう一度見てもらって承諾を取り直してください。")
        print(how, end="")
        return 1
    print(f"✓ 書き出しの承諾あり: {out or comp}（{hit.get('approved_at')}）")
    return 0


# ---------------------------------------------------------------------------
# 生成の承諾
# ---------------------------------------------------------------------------
def line_texts(cfg: dict[str, Any], lines_file: str | None) -> dict[str, str]:
    """`lines.json` があれば id → セリフ の対応を読む（無ければ空の辞書）。"""
    if not lines_file:
        return {}
    path = resolve(cfg, lines_file)
    if not path.exists():
        return {}
    try:
        spec = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return {str(ln.get("id")): str(ln.get("text", "")) for ln in spec.get("lines", []) if ln.get("id")}


def cmd_generation(a: argparse.Namespace, cfg: dict[str, Any]) -> int:
    ids = [i.strip() for i in (a.ids or "").split(",") if i.strip()]
    if not ids:
        raise SystemExit("--ids に生成するセリフの id をカンマ区切りで指定してください")
    texts = line_texts(cfg, a.lines)
    print("=== 費用のかかる生成の承諾 ===")
    print("  作るもの:")
    for line_id in ids:
        text = texts.get(line_id, "")
        print(f"    - {line_id}" + (f"「{text}」" if text else ""))
    if a.note:
        print(f"    内容: {a.note}")
    print(f"  本数    : 1つあたり {a.takes} 本（合計 {len(ids) * a.takes} 本）")
    print(f"  サービス: {a.service}")
    if not ask("  この内容で生成してよいですか？ [y/N]: "):
        print("中止しました（承諾は記録しません）")
        return 1
    path = _gates.generation_approval_path(cfg)
    _gates.write_json(path, {
        "ids": ids, "takes": a.takes, "service": a.service,
        "at": _gates.now(), "at_epoch": _gates.now_epoch(), **consent_meta(),
    })
    print(f"✓ 承諾を記録しました -> {_gates.GENERATION_APPROVAL}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="書き出してよいかの確認だけ（記録は作らない）")
    ap.add_argument("--generation", action="store_true", help="費用のかかる生成の承諾を取る")
    ap.add_argument("--composition", default=None, help="コンポジション名（ad-9x16 など）")
    ap.add_argument("--out", default=None, help="書き出し先のファイル（out/ad-9x16.mp4 など）")
    ap.add_argument("--ids", default=None, help="--generation のとき: 生成するセリフの id（カンマ区切り）")
    ap.add_argument("--takes", type=int, default=1, help="--generation のとき: 1つあたりのテイク数")
    ap.add_argument("--service", "--model", dest="service", default="seedance",
                    help="--generation のとき: どのサービスで作るか（seedance／veo／omni／nano-banana など）")
    ap.add_argument("--lines", default="lines.json",
                    help="--generation のとき: セリフを読む lines.json（無ければ id だけを表示する）")
    ap.add_argument("--chat", default=None, metavar="依頼主の返答の原文",
                    help="端末が無い環境（クラウド）で、チャットで得た依頼主の返答をそのまま渡す。記録に channel=chat と原文が残る")
    ap.add_argument("--note", default=None,
                    help="--generation のとき: lines.json に無いものの内容を1行で書く（トーキングヘッドの台本など）")
    a = ap.parse_args()
    global CHAT_QUOTE
    CHAT_QUOTE = a.chat

    cfg = load_config()
    if a.generation:
        return cmd_generation(a, cfg)
    if a.check:
        return cmd_check(a, cfg)
    return cmd_render_approval(a, cfg)


if __name__ == "__main__":
    sys.exit(main())
