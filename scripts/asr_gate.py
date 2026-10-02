#!/usr/bin/env python3
"""2エンジン合議制の発音ゲート。音声・動画を2つの音声認識エンジンにかけ、結果を並べて見せる。

何を検査するか: 「その音声が台本どおりに聞こえるか」を、1つのエンジンの気まぐれに頼らず確かめる。
2つのエンジンの文字起こしが（表記ゆれを正規化したうえで）一致して初めて合格とする。
片方でも欠落・異常があれば不合格。数字・固有名詞など危険な語は --slow-window で個別に確かめる。

使い方（案件フォルダのルートで）:
  python3 scripts/asr_gate.py <音声/動画ファイル> [--slow-window 開始秒 長さ秒]

合格基準:
  - 2エンジンの文字起こしが正規化後に一致（✓ 表示）。不一致なら差分箇所を --slow-window で個別検証する
    （--slow-window は不一致のときも実行される。終了コードは 1 のまま）
  - 長尺（既定12秒超）は第2エンジン（小型の whisper モデル）が破綻するため、第1エンジン単独の「全文確認」に切り替わる。
    この場合は合否判定をしない。発音の合否は必ずチャンク単位（数秒のファイル）で本ゲートを通すこと

失敗時に見る場所: 表示された2つの文字起こしの差。表記ゆれ（同じ音・違う漢字）なら
  読み方の辞書（scripts/pronunciation_dict.json、案件の語は ai-ad.config.json の
  pronunciationDictExtra が指すファイル）の asr_variants に足す。音が違うなら台本の言い換えか再生成。

使うエンジンは ai-ad.config.json で決めます（`asrEngine` / `asrEngine2`）。既定は whisper 2本。
`"asrEngine": "whisper", "asrEngine2": "gemini"` で whisper＋Gemini、
`"asrEngine": "gemini", "asrEngine2": "none"` で Gemini だけ（Google 製品で完結させたいとき）になります。
2つ目が無ければ1エンジンで動きます（その場合は合否判定をしません）。
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _asr  # noqa: E402
from _config import load_config, resolve  # noqa: E402

# 第2エンジン（小型・日本語特化モデル）は長い音声を流すと反復・脱落・幻覚を起こす。
# チャンク単位（数秒）でのみ合議の相手として信頼できる。
DEFAULT_MAX_2ENGINE_SEC = 12.0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("audio", help="検査する音声または動画ファイル")
    ap.add_argument("--slow-window", nargs=2, metavar=("START", "DUR"),
                    help="この区間を0.7倍速にして両エンジンで再検証する（危険語の確認用）")
    ap.add_argument("--max-2engine-sec", type=float, default=DEFAULT_MAX_2ENGINE_SEC,
                    help=f"合議を使う上限秒（既定 {DEFAULT_MAX_2ENGINE_SEC:g}。超えたら第1エンジン単独）")
    a = ap.parse_args()

    src = Path(a.audio)
    if not src.exists():
        raise SystemExit(f"ファイルがありません: {src}")

    cfg = load_config()
    engines = _asr.build_engines(cfg, resolve, warn=print)
    e1 = engines[0]
    e2 = engines[1] if len(engines) > 1 else None
    lang = str(cfg["language"])

    kana = _asr.build_kana_map(_asr.load_dicts_from_config(cfg, resolve, warn=print))

    mismatch = False
    with tempfile.TemporaryDirectory() as td:
        wav = _asr.to_wav16k(src, Path(td) / "a.wav")
        total = _asr.probe_duration(wav)
        print(f"=== {src.name}  {total:.1f}s")

        if e2 is None:
            print(f"[mode] エンジンが1つ（{e1}）なので確認のみ（合否判定はしない）")
            print(f"[{e1}] {e1.transcribe(wav, lang)}")
        elif total > a.max_2engine_sec:
            print(f"[mode] {total:.1f}s = 長尺 → 第1エンジン単独で全文確認（合否判定はしない）")
            print("       ※発音の合否は必ずチャンク単位（数秒のファイル）で合議ゲートを通すこと")
            print(f"[{e1}] {e1.transcribe(wav, lang)}")
        else:
            t1 = e1.transcribe(wav, lang)
            t2 = e2.transcribe(wav, lang)
            print(f"[{e1}] {t1}")
            print(f"[{e2}] {t2}")
            if _asr.norm(t1, kana) == _asr.norm(t2, kana):
                print("✓ 両エンジン一致（表記ゆれ正規化後）")
            else:
                print("⚠ エンジン不一致 → 差分箇所を --slow-window で個別検証すること")
                mismatch = True

        # 不一致でも slow window は必ず出す（不一致のときにこそ使う道具のため）
        if a.slow_window:
            start, dur = a.slow_window
            cut = Path(td) / "slow.wav"
            _asr.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(wav),
                      "-ss", start, "-t", dur, "-af", "atempo=0.7", str(cut)])
            print(f"--- slow window {start}s +{dur}s @0.7x")
            print(f"[{e1}] {e1.transcribe(cut, lang)}")
            if e2 is not None:
                print(f"[{e2}] {e2.transcribe(cut, lang)}")
        elif mismatch:
            print("  ヒント: --slow-window <開始秒> <長さ秒> を付けて再実行すると、差分箇所を0.7倍速で並べます")
    return 1 if mismatch else 0


if __name__ == "__main__":
    sys.exit(main())
