#!/usr/bin/env python3
"""書き出した動画そのものを1件ずつ検証する。

最終 mp4 から (1) 全編 ASR を取り、各シーンのテロップ文が音声に含まれるか（台本カバレッジ）を確認し、
(2) --frames 指定時は各シーン中央のフレームを PNG で抽出する。ソースやスチルではなく **成果物側** を確認するためのツール。

入力は **書き出した mp4 だけ**です（実行役が用意した静止画やログは受け取りません）。
フレームもこのスクリプトが自分で抽出します。「直したはずです」という報告ではなく、成果物そのものを見るためです。

使い方（案件フォルダのルートで）:
  python3 scripts/verify_render.py <mp4> [--scenes src/scenes.ts] [--frames] [--out out/verify-<名前>]
  --scenes 無指定なら ai-ad.config.json の sceneFiles の先頭（複数あるときは警告するので明示すること）。
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _asr  # noqa: E402
from _config import load_config, parse_scenes, rel, resolve, scene_files  # noqa: E402

COVERAGE_ERR_MAX = 0.2  # 全編ASRは文脈補正が入るため、テイク検品（0.08）より緩い閾値で「要確認」を出す


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mp4")
    ap.add_argument("--scenes", default=None, help="シーン定義ファイル")
    ap.add_argument("--frames", action="store_true", help="各シーン中央のフレームを抽出する")
    ap.add_argument("--out", default=None, help="フレームの出力先（既定: out/verify-<mp4名>）")
    a = ap.parse_args()

    cfg = load_config()
    mp4 = resolve(cfg, a.mp4)
    if not mp4.exists():
        raise SystemExit(f"ファイルがありません: {mp4}")
    files = scene_files(cfg, [a.scenes] if a.scenes else None)
    if len(files) > 1:
        print(f"WARN シーン定義が複数あります。先頭 {rel(cfg, files[0])} を使います（--scenes で明示可）")
    scene_file = files[0]
    scenes = [s for s in parse_scenes(scene_file.read_text(encoding="utf-8")) if s["durationSeconds"] is not None]
    engine = _asr.build_engines(cfg, resolve, warn=print)[0]
    pd = _asr.load_pronunciation_dict(resolve(cfg, cfg["pronunciationDict"]) if cfg.get("pronunciationDict") else None)
    kana = _asr.build_kana_map(pd)

    # (1) 全編ASR
    asr = engine.transcribe(_asr.to_wav16k(mp4, Path(tempfile.mkdtemp()) / "a.wav"), cfg["language"])
    print("=== 全編ASR ===")
    print(asr[:1200])
    asr_norm = _asr.norm(asr, kana)

    # 尺の整合
    total = sum(s["durationSeconds"] for s in scenes)
    actual = _asr.probe_duration(mp4)
    flag = "" if abs(total - actual) <= 0.5 else "  <- WARN シーン合計と成果物の尺がずれています"
    print(f"=== 尺 === scenes合計 {total:.2f}s / mp4 {actual:.2f}s{flag}")

    # (2) 台本カバレッジ（シーンごとのテロップ文が音声に含まれるか）
    print("=== 台本カバレッジ（テロップ文 vs 全編ASR） ===")
    ok = checked = 0
    for s in scenes:
        cap = s.get("caption")
        exp = _asr.norm(cap, kana) if cap else ""
        if not exp:
            continue
        checked += 1
        err = _asr.window_err(exp, asr_norm)
        mark = "OK   " if err <= COVERAGE_ERR_MAX else "CHECK"
        ok += err <= COVERAGE_ERR_MAX
        print(f"  {mark} sc{s['id_str']:<5} err={err:.2f}  {cap.replace(chr(92)+'n', '/')[:40]}")
    print(f"coverage: {ok}/{checked} OK（CHECK は該当シーンの音声を耳で確認する）")

    # (3) フレーム抽出
    if a.frames:
        outdir = resolve(cfg, a.out) if a.out else cfg["_cwd"] / "out" / f"verify-{mp4.stem}"
        outdir.mkdir(parents=True, exist_ok=True)
        acc = 0.0
        for s in scenes:
            t = acc + s["durationSeconds"] * 0.5
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", str(mp4),
                            "-frames:v", "1", str(outdir / f"sc{s['id_str']}.png")])
            acc += s["durationSeconds"]
        print(f"frames -> {rel(cfg, outdir)}")
    else:
        print("ASR only（--frames で各シーン中央のフレームも抽出）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
