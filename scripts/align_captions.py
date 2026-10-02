#!/usr/bin/env python3
"""テロップとセリフの同期を、音声認識のタイムスタンプで機械的に合わせる。

1つの音声トラックが複数シーンにまたがる場合、各シーンのテロップ文が実際に話し終わる時刻を
whisper のトークンタイムスタンプから求め、シーンの durationSeconds を書き換える（かな比などの推定分割はしない）。

使い方（案件フォルダのルートで）:
  python3 scripts/align_captions.py [src/scenes.ts ...] [--dry-run] [--max-err 0.35]
  無指定なら ai-ad.config.json の sceneFiles を全て処理する。--dry-run は書き換えずに変更予定だけ表示。

整列する単位（グループ）は2種類:
- 音声トラック（tracks の行）: atSceneId から「次の境界」（次のトラックの atSceneId、または audioSrc を
  持つシーン）の手前までを1グループにする
- 人物クリップに含まれる音声（nativeAudio: true）: 同じ src を続けて使い、自前の audioSrc を持たない
  連続シーンを1グループにする。トーキングヘッドは1本のクリップをテロップごとに割る形が普通で、
  この形には tracks の行が無いため、これを見ないと整列が何もしないまま素通りしてしまう

どちらのグループも、シーン1つだけなら何もしない。整列できるグループが1つも無ければその旨を表示する。
src は publicDir（既定 assets/）からの相対パス。
出力: 変更したシーン尺の一覧。マッチ信頼度が低い（err > --max-err）場合は WARN を出して現状維持。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _asr  # noqa: E402
from _config import load_config, parse_scenes, parse_tracks, rel, resolve, scene_files, whisper_model  # noqa: E402


def align_boundaries(expected_parts: list[str], toks: list[tuple[str, float]]):
    """期待テキスト（シーン別）と ASR トークン列を DP 整列し、各パート終端の時刻を返す。"""
    exp_full = "".join(_asr.norm(p) for p in expected_parts)
    ends = []
    acc = 0
    for p in expected_parts[:-1]:
        acc += len(_asr.norm(p))
        ends.append(acc)
    asr_chars = []  # (char, token_idx)
    for i, (txt, _) in enumerate(toks):
        for ch in _asr.norm(txt):
            asr_chars.append((ch, i))
    a = exp_full
    b = "".join(c for c, _ in asr_chars)
    n, m = len(a), len(b)
    if n == 0 or m == 0:
        return None, 1.0
    # 編集距離DP＋バックトレースで exp位置→asr位置 の対応を得る
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        dp[i][0] = i
    for j in range(m + 1):
        dp[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            dp[i][j] = min(dp[i - 1][j] + 1, dp[i][j - 1] + 1, dp[i - 1][j - 1] + (a[i - 1] != b[j - 1]))
    err = dp[n][m] / max(1, n)
    map_exp_to_asr: list[int | None] = [None] * (n + 1)
    i, j = n, m
    map_exp_to_asr[n] = m
    while i > 0 and j > 0:
        if dp[i][j] == dp[i - 1][j - 1] + (a[i - 1] != b[j - 1]):
            i, j = i - 1, j - 1
        elif dp[i][j] == dp[i - 1][j] + 1:
            i -= 1
        else:
            j -= 1
        map_exp_to_asr[i] = j
    for k in range(n + 1):
        if map_exp_to_asr[k] is None:
            map_exp_to_asr[k] = map_exp_to_asr[k - 1] if k else 0
    times = []
    for e in ends:
        aj = map_exp_to_asr[e]
        if aj <= 0:
            times.append(None)
            continue
        tok_idx = asr_chars[min(aj, m) - 1][1]
        times.append(toks[tok_idx][1])
    return times, err


def track_groups(scenes: list, tracks: list, name: str) -> list[tuple[str, list, float, str, float]]:
    """音声トラック（tracks の行）が担当するシーン群。返り値: (音声パス, シーン群, 総尺, 見出し, 音声内の開始秒)"""
    boundaries = {t["atSceneId"] for t in tracks} | {s["id"] for s in scenes if s.get("audioSrc")}
    out = []
    for tr in tracks:
        idx = [i for i, s in enumerate(scenes) if s["id"] == tr["atSceneId"]]
        if not idx:
            print(f"  WARN {name}: atSceneId {tr['atSceneId']:g} のシーンが見つかりません（{tr['src']}）")
            continue
        i0 = idx[0]
        i1 = len(scenes)
        for j in range(i0 + 1, len(scenes)):
            if scenes[j]["id"] in boundaries:
                i1 = j
                break
        group = scenes[i0:i1]
        if len(group) < 2:
            continue
        if tr["durationSeconds"] is None:
            print(f"  WARN {name} sc{tr['atSceneId']:g}: トラックの durationSeconds が読めない → keep")
            continue
        out.append((tr["src"], group, float(tr["durationSeconds"]), f"sc{tr['atSceneId']:g}",
                    float(tr.get("startSeconds") or 0.0)))
    return out


def native_audio_groups(scenes: list) -> list[tuple[str, list, float, str, float]]:
    """1本の人物クリップを複数シーンに割り、クリップに入っている音声をそのまま鳴らす形（nativeAudio）。

    tracks の行が無いのでトラック側の仕組みでは拾えない。同じ src を続けて使い、
    自前の audioSrc を持たない連続シーンを1グループとして扱う。
    グループの総尺は今の durationSeconds の合計（クリップは連続しているので全体の長さは変えず、
    中の境界だけを動かす）。開始位置は先頭シーンの videoStartSeconds。
    """
    out = []
    i = 0
    while i < len(scenes):
        s = scenes[i]
        src = s.get("src")
        native = "nativeAudio" in (s.get("raw") or "")
        if not src or s.get("audioSrc") or not native:
            i += 1
            continue
        j = i + 1
        while (j < len(scenes) and scenes[j].get("src") == src
               and not scenes[j].get("audioSrc")):
            j += 1
        group = scenes[i:j]
        if len(group) >= 2 and all(s2.get("durationSeconds") is not None for s2 in group):
            total = sum(float(s2["durationSeconds"]) for s2 in group)
            out.append((src, group, total, f"sc{group[0]['id_str']}(nativeAudio)",
                        float(group[0].get("videoStartSeconds") or 0.0)))
        i = max(j, i + 1)
    return out


def process(path: Path, cfg, model: Path, max_err: float, dry_run: bool) -> None:
    name = rel(cfg, path)
    text = path.read_text(encoding="utf-8")
    scenes = parse_scenes(text)
    tracks = parse_tracks(text)
    public = resolve(cfg, cfg["publicDir"])
    groups = track_groups(scenes, tracks, name) + native_audio_groups(scenes)
    if not groups:
        print(f"  {name}: 整列できるまとまりがありません"
              f"（1本の音声を複数シーンに割っている箇所が無い）。テロップはシーンの尺のままです")
        return
    changes = []
    for src, group, total, label, offset in groups:
        if any(s["caption"] is None or s["durationSeconds"] is None for s in group):
            print(f"  WARN {name} {label}: caption / durationSeconds が読めないシーンがある → keep")
            continue
        audio = public / src
        if not audio.exists():
            print(f"  WARN {name} {src}: missing")
            continue
        toks = _asr.transcribe_tokens(audio, model, cfg["language"])
        times, err = align_boundaries([s["caption"] for s in group], toks)
        if times is None or err > max_err or any(t is None for t in times):
            print(f"  WARN {name} {label} ({audio.name}): low confidence (err={err:.2f}) -> keep")
            continue
        prev = offset
        durs = []
        for t in times:
            durs.append(max(0.3, round(t - prev, 3)))
            prev = prev + durs[-1]
        durs.append(max(0.3, round(offset + total - prev, 3)))
        for s, nd in zip(group, durs):
            if abs(nd - s["durationSeconds"]) > 0.05:
                changes.append((s["dur_span"], f"{nd:.3f}", s["id_str"], s["durationSeconds"], nd))
    for (a, b), txt, _, _, _ in sorted(changes, key=lambda x: -x[0][0]):
        text = text[:a] + txt + text[b:]
    if changes and not dry_run:
        path.write_text(text, encoding="utf-8")
    for _, _, sid, old, nd in sorted(changes, key=lambda x: float(x[2])):
        print(f"  {name} sc{sid}: {old:.2f} -> {nd:.2f}" + ("  (dry-run)" if dry_run else ""))
    if not changes:
        print(f"  {name}: aligned (no drift)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", help="シーン定義ファイル（無指定なら config の sceneFiles）")
    ap.add_argument("--dry-run", action="store_true", help="書き換えずに変更予定だけ表示")
    ap.add_argument("--max-err", type=float, default=0.35, help="この編集距離率を超えたら低信頼として現状維持")
    a = ap.parse_args()
    cfg = load_config()
    model = whisper_model(cfg)
    for f in scene_files(cfg, a.files):
        print(f"== {rel(cfg, f)}")
        process(f, cfg, model, a.max_err, a.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
