#!/usr/bin/env python3
"""危険語（数字・固有名詞・辞書に登録した語）を、人の耳で確かめてもらう。

なぜ要るか: 音声認識が一致しても、拗音・清濁・母音の違いは通ってしまいます
（機械が同じ間違いを2回すれば合格になります）。数字と固有名詞は、そこを間違えると広告として成立しません。
だから **機械の一致だけでは合格にしない** ——このスクリプトが、その決まりを人の操作なしでは通れなくします。

やること:
  1. 対象の語が鳴っている前後だけを切り出す（全編は聴かせない）
  2. 切り出した音を並べて、人に「A / B / どちらも不可」を答えてもらう
  3. 答えだけを out/ear-check.json に記録する（preflight.py がこの記録を見る）

使い方（案件フォルダのルートで。**対話でしか使えません**）:

  # 1本を確かめる（採用予定のテイク／配線した音声）
  python3 scripts/ear_check.py assets/audio/s1.m4a --text "1分の入力で完了します"

  # 2本を聴き比べる（A と B のどちらを採用するか）
  python3 scripts/ear_check.py assets/videos/takes/s1-t1.mp4 assets/videos/takes/s1-t2.mp4 --id s1

  python3 scripts/ear_check.py --list        # いまの記録を表示する

引数:
  --id     記録につける名前（既定: ファイル名から。シーン番号 `3` でも、音声の名前 `s1` でもよい）
  --text   その音声で話している台本。危険語をここから自動で拾う
  --words  危険語を自分で指定する（カンマ区切り。--text から拾えないとき）

**この記録を手で書いてはいけません。** preflight.py は、記録に残った音声のハッシュと
実際のファイルを突き合わせます。音声を差し替えれば記録は無効になり、もう一度聴くことになります。
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _asr  # noqa: E402
import _gates  # noqa: E402
from _config import load_config, rel, resolve, whisper_model  # noqa: E402

PAD = 0.45  # 語の前後に足す秒数（前後の文脈が無いと聴き分けられないため）


def say(msg: str) -> None:
    print(msg, flush=True)


def locate(path: Path, words: list[str], cfg: dict[str, Any]) -> list[tuple[str, float, float]]:
    """各語が鳴っている区間 [(語, 開始, 終了)] を音声認識のトークン時刻から求める。

    見つからない語は (語, -1, -1) を返す（呼び出し側で全体を切り出す）。
    """
    dur = _asr.probe_duration(path)
    model = whisper_model(cfg, required=False)
    if not model:
        say("NOTE 音声認識モデルが無いので、語の位置を特定せず全体を切り出します")
        return [(w, 0.0, dur) for w in words]
    try:
        tokens = _asr.transcribe_tokens(path, model, cfg["language"])
    except Exception as exc:  # noqa: BLE001
        say(f"NOTE 位置の特定に失敗したので全体を切り出します（{type(exc).__name__}）")
        return [(w, 0.0, dur) for w in words]
    text = ""
    ends: list[float] = []
    for tk, end in tokens:
        text += tk
        ends += [end] * len(tk)
    spans: list[tuple[str, float, float]] = []
    for w in words:
        idx = text.find(w)
        if idx < 0:
            idx = _asr.kata_to_hira(text).find(_asr.kata_to_hira(w))
        if idx < 0 or not ends:
            spans.append((w, 0.0, dur))
            continue
        last = min(idx + len(w) - 1, len(ends) - 1)
        end = ends[last]
        start = ends[idx - 1] if idx > 0 else max(0.0, end - 1.2)
        spans.append((w, max(0.0, start - PAD), min(dur, end + PAD)))
    return spans


def cut(src: Path, start: float, end: float, out: Path) -> bool:
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{start:.2f}", "-t", f"{max(0.3, end - start):.2f}",
           "-i", str(src), "-vn", "-c:a", "aac", "-b:a", "128k", str(out)]
    return subprocess.run(cmd).returncode == 0


def open_folder(path: Path) -> None:
    opener = "open" if sys.platform == "darwin" else ("xdg-open" if shutil.which("xdg-open") else None)
    if opener:
        subprocess.run([opener, str(path)], capture_output=True)


def cmd_list(cfg: dict[str, Any]) -> int:
    recs = _gates.load_ear_checks(cfg)
    if not recs:
        say("耳での確認の記録はまだありません")
        return 0
    say(f"{'id':<10}{'判定':<8}{'日時':<22}語")
    for r in recs:
        verdict = "合格" if r.get("passed") else "不可"
        say(f"{str(r.get('id')):<10}{verdict:<8}{str(r.get('at')):<22}{'、'.join(r.get('words', []))}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", help="確かめる音声・動画（1本、または聴き比べる2本）")
    ap.add_argument("--id", default=None, help="記録につける名前（既定: 1本目のファイル名）")
    ap.add_argument("--text", default="", help="その音声で話している台本（危険語をここから拾う）")
    ap.add_argument("--words", default="", help="危険語を自分で指定する（カンマ区切り）")
    ap.add_argument("--list", action="store_true", help="いまの記録を表示して終わる")
    ap.add_argument("--chat-verdict", default=None, choices=["A", "B", "x", "a", "b", "X"],
                    help="端末が無い環境で、依頼主がチャットで返した判定（A / B / x）")
    ap.add_argument("--chat", default=None, metavar="依頼主の返答の原文", help="その判定を含む依頼主の返答をそのまま渡す")
    a = ap.parse_args()

    cfg = load_config()
    if a.list:
        return cmd_list(cfg)
    if not a.files:
        ap.error("確かめる音声・動画のパスを指定してください")
    chat_mode = not sys.stdin.isatty()
    if chat_mode and not (a.chat_verdict and a.chat):
        raise SystemExit(
            "✗ 耳での確認は対話でしか記録できません（いまは対話ではありません）。\n"
            "  端末が無い環境では、切り出した音を依頼主にダウンロードして聴いてもらい、返ってきた判定と原文を\n"
            "    --chat-verdict A|B|x --chat \"<依頼主の返答の原文>\"\n"
            "  に渡してください。AI が判定を作ってはいけません。")

    paths = [resolve(cfg, f) for f in a.files[:2]]
    for p in paths:
        if not p.exists():
            raise SystemExit(f"ファイルがありません: {p}")
    check_id = a.id or paths[0].stem.split("-t")[0]

    pd = _asr.load_dicts_from_config(cfg, resolve, warn=say)
    extra, ignore = _gates.ear_check_words_config(cfg)
    if a.words:
        words = [w.strip() for w in a.words.split(",") if w.strip()]
    else:
        words = _gates.danger_words(a.text, pd, extra, ignore)
    if not words:
        say("危険語（数字・固有名詞・辞書登録語）が見つかりませんでした。")
        say("  --text に台本を渡すか、--words で語を指定してください。")
        say("  ここで確かめるのは、数字・固有名詞・読み方の辞書に載せた語だけです。")
        return 1

    say(f"=== 耳で確かめる: {check_id} ===")
    say(f"  対象の語: {'、'.join(words)}")
    outdir = resolve(cfg, f"out/ear-check/{check_id}")
    if outdir.exists():
        shutil.rmtree(outdir)
    clips: list[str] = []
    for label, p in zip("AB", paths):
        say(f"  [{label}] {rel(cfg, p)}")
        for i, (w, s, e) in enumerate(locate(p, words, cfg), 1):
            dest = outdir / f"{i:02d}-{w[:12]}-{label}.m4a"
            if cut(p, s, e, dest):
                clips.append(rel(cfg, dest))
                say(f"      「{w}」 {s:.2f}〜{e:.2f}s -> {rel(cfg, dest)}")
    if not clips:
        raise SystemExit("✗ 切り出しに失敗しました（ffmpeg が入っているか確かめてください）")

    open_folder(outdir)
    say("")
    say(f"  切り出した音を {rel(cfg, outdir)} に置きました（フォルダを開きました）。")
    say("  上から順に再生して、対象の語が台本どおりに聞こえるか確かめてください。")
    say("  ※全編は聴かなくて構いません。この短い音だけで判定します。")
    say("")
    choices = "A / B / x（どちらも不可）" if len(paths) == 2 else "A（このまま使える） / x（不可）"
    verdict = ""
    if chat_mode:
        verdict = a.chat_verdict.lower()
        say(f"  判定（チャット経由）: {verdict.upper()} 「{a.chat}」")
    while verdict not in (["a", "x"] + (["b"] if len(paths) == 2 else [])):
        verdict = input(f"  どれを採用しますか？ {choices}: ").strip().lower()
    chosen = None if verdict == "x" else paths[0 if verdict == "a" else 1]
    note = a.chat if chat_mode else input("  気づいたこと（任意・そのまま Enter でも可）: ").strip()

    rec = {
        "id": check_id,
        "listened_by_human": True,
        "passed": chosen is not None,
        "verdict": verdict.upper(), "channel": "chat" if chat_mode else "tty",
        "words": words,
        "files": [rel(cfg, p) for p in paths],
        "chosen": rel(cfg, chosen) if chosen else None,
        "audio_sha1": _gates.sha1_of(chosen) if chosen else None,
        "clips": clips,
        "note": note,
        "at": _gates.now(),
        "at_epoch": _gates.now_epoch(),
    }
    path = _gates.ear_check_path(cfg)
    recs = [r for r in _gates.load_ear_checks(cfg) if str(r.get("id")) != str(check_id)]
    recs.append(rec)
    _gates.write_json(path, recs)

    if chosen:
        say(f"✓ 記録しました（採用 {verdict.upper()}: {rel(cfg, chosen)}） -> {_gates.EAR_CHECK}")
        say("  この音声を配線してください。差し替えたら、もう一度聴き直しになります")
        return 0
    say(f"✓ 記録しました（どちらも不可） -> {_gates.EAR_CHECK}")
    say("  作り直す前に、読み方の辞書に実際の誤読を `never 〜` として足してください（RULES.md 決まり16）")
    return 1


if __name__ == "__main__":
    sys.exit(main())
