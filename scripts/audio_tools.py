#!/usr/bin/env python3
"""音声の検品と、生成し直さずに直すための編集（無コスト救済）をまとめた道具。

サブコマンド:
  check       1セリフ＝1テイクの音声を、耳で聴く前に機械で落とす（突発音・残響・ピーク・読み違い）
  cut-gaps    語中の不自然な間（無音）だけを位置指定で詰める。映像と音声をまとめて切るので口の同期は保たれる
  scan-gates  書き出した動画のシーン境界に「プチッ」というノイズが出ていないか調べる

使い方（案件フォルダのルートで）:
  python3 scripts/audio_tools.py check <音声/動画> "キーワード1,キーワード2"
  python3 scripts/audio_tools.py cut-gaps 入力.mp4 出力.mp4 --gaps 3.18:3.39 4.10:4.22
  python3 scripts/audio_tools.py scan-gates out/ad-9x16.mp4 3.2,2.8,4.1

各サブコマンドの詳細は `--help` を付けると出ます。
音声が崩れたときは、作り直す前にこの cut-gaps と build_chunk.py を先に試します（RULES.md「無コスト救済先行」）。
"""
from __future__ import annotations

import argparse
import array
import math
import re
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _asr  # noqa: E402
from _config import load_config, resolve  # noqa: E402

SR = 16000            # 検品用に読み込むサンプリングレート
PCM_SR = 48000        # 境界クリック検査で読むサンプリングレート
CROSSFADE = 0.02      # 切り貼りのつなぎ目に入れるクロスフェード秒（プチッというノイズを防ぐ）


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def silences(path: Path, thr: str, mind: float) -> tuple[list[float], list[float], float]:
    out = run(["ffmpeg", "-i", str(path), "-af", f"silencedetect=n={thr}:d={mind}", "-f", "null", "-"]).stderr
    st = [float(x) for x in re.findall(r"silence_start: (-?[0-9.]+)", out)]
    en = [float(x) for x in re.findall(r"silence_end: (-?[0-9.]+)", out)]
    return st, en, _asr.probe_duration(path)


def seg_stat(path: Path, a: float, b: float, metric: str = "max") -> float:
    """区間 a〜b 秒の max_volume / mean_volume（dB）。短すぎる区間は測らない。"""
    if b - a < 0.03:
        return -99.0
    key = "max_volume" if metric == "max" else "mean_volume"
    out = run(["ffmpeg", "-ss", str(a), "-to", str(b), "-i", str(path), "-af", "volumedetect",
               "-f", "null", "-"]).stderr
    m = re.search(key + r": (-?[0-9.]+)", out)
    return float(m.group(1)) if m else -99.0


def min_window_rms(path: Path, dur: float, win: float = 0.1) -> float:
    vals = []
    t = 0.0
    while t + win <= dur:
        vals.append(seg_stat(path, t, t + win, "mean"))
        t += win
    return min(vals) if vals else 0.0


def samples(path: Path) -> array.array:
    """16kHzモノラルのサンプル列（numpy 不要）。"""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(SR),
                          "-f", "f32le", "-"], capture_output=True).stdout
    x = array.array("f")
    x.frombytes(raw)
    return x


def rms_profile(x: array.array, win: float = 0.01) -> list[float]:
    """10ms窓のRMS（dB）の列。"""
    w = int(SR * win)
    out = []
    for i in range(0, len(x) - w + 1, w):
        s = 0.0
        for v in x[i:i + w]:
            s += v * v
        out.append(20 * math.log10(math.sqrt(s / w) + 1e-9))
    return out


def voicing(x: array.array, a: float, b: float, fmin: int = 70, fmax: int = 350) -> float | None:
    """区間 a〜b 秒の周期性（正規化自己相関のピーク）の中央値。
    母音など有声音は高く、生成ノイズの『ポッ』は低い。"""
    w = int(SR * 0.03)
    h = int(SR * 0.01)
    lo, hi = int(SR / fmax), int(SR / fmin)
    i0, i1 = int(a * SR), int(b * SR)
    vals = []
    for i in range(i0, max(i0 + 1, i1 - w), h):
        seg = x[i:i + w]
        if len(seg) < w:
            break
        m = sum(seg) / w
        seg = [v - m for v in seg]
        e0 = sum(v * v for v in seg)
        if e0 <= 1e-12:
            continue
        best = 0.0
        for lag in range(lo, min(hi, w - 1)):
            acc = 0.0
            for k in range(w - lag):
                acc += seg[k] * seg[k + lag]
            r = acc / e0
            if r > best:
                best = r
        vals.append(best)
    if not vals:
        return None
    vals.sort()
    return vals[len(vals) // 2]


def blips(path: Path, on: float, off: float, quiet: float, max_len: float = 0.15,
          long_guard: float = 0.15, short_guard: float = 0.04,
          voiced_min: float = 0.5) -> list[tuple[float, float, float, float | None]]:
    """孤立した突発音（ポッ・プツ）を返す。

    条件: 島（on を超えて始まり off 以下に落ちるまで）の長さが max_len 以下で、
      片側に long_guard 秒以上の静寂（quiet 以下）があり、反対側にも short_guard 秒の静寂がある。

    なぜこの形か:
      - 両側 0.04 秒だけの判定では、破裂音の前後の短い谷を挟んだ音節まで突発音と誤検出した
      - 逆に両側 0.15 秒を要求すると、直後に次の語が来る本物のブリップを見逃した。
        本物は『片側に長い無音』が必ずある
      - それでも『長い間のあとの音節＋破裂音の閉鎖』は同じ形になるので、
        最後に周期性（有声かどうか）で振り分ける
    """
    x = samples(path)
    p = rms_profile(x)
    n = len(p)
    lg, sg = int(long_guard / 0.01), int(short_guard / 0.01)
    res = []
    i = 0
    while i < n:
        if p[i] > on:
            j = i
            while j < n and p[j] > off:
                j += 1
            length = (j - i) * 0.01
            pre_l, post_l = p[max(0, i - lg):i], p[j:j + lg]
            pre_s, post_s = p[max(0, i - sg):i], p[j:j + sg]
            ok_pre_l = len(pre_l) == lg and max(pre_l) <= quiet
            ok_post_l = len(post_l) == lg and max(post_l) <= quiet
            ok_pre_s = len(pre_s) == sg and max(pre_s) <= quiet
            ok_post_s = len(post_s) == sg and max(post_s) <= quiet
            isolated = (ok_pre_l and ok_post_s) or (ok_post_l and ok_pre_s)
            if length <= max_len and isolated:
                v = voicing(x, i * 0.01, j * 0.01)
                if v is None or v < voiced_min:
                    res.append((i * 0.01, j * 0.01, max(p[i:j]), v))
            i = j
        else:
            i += 1
    return res


def peak_dbfs(path: Path) -> float:
    out = run(["ffmpeg", "-i", str(path), "-af", "volumedetect", "-f", "null", "-"]).stderr
    m = re.search(r"max_volume: (-?[0-9.]+)", out)
    return float(m.group(1)) if m else -99.0


# ---------------------------------------------------------------------------
# check: 生成した1テイクを、耳で聴く前に機械で落とすゲート
# ---------------------------------------------------------------------------
def cmd_check(a: argparse.Namespace) -> int:
    """検査する6項目（1つでも引っかかれば FAIL）:
      1. 期待キーワードが文字起こしに全部含まれるか（言い間違い・脱落）
      2. 語と語の間に突発音が無いか（ギャップ内の最大音量 ≤ --gap-max dB）
      3. どこかに本当の静けさがあるか（常時ノイズ・残響ウォッシュの検出）
      4. 最終発話の直後に残響の尾が残っていないか
      5. 単発音（「ポッ」「プツ」）が無いか（前後が静かで周期性の無い短い音）
      6. ピークが振り切れていないか
    閾値の既定値はクローン音声で安定した水準。声質・収録条件が違えば合わないので、
    最初の数本を耳で確かめながら --gap-max / --floor / --tail を調整する。
    """
    path = Path(a.audio)
    if not path.exists():
        raise SystemExit(f"ファイルがありません: {path}")

    cfg = load_config()
    engine = _asr.build_engines(cfg, resolve, warn=print)[0]
    fails: list[str] = []

    with tempfile.TemporaryDirectory() as td:
        wav = _asr.to_wav16k(path, Path(td) / "a.wav")
        text = engine.transcribe(wav, str(cfg["language"]))
    for k in [k.strip() for k in a.keywords.split(",") if k.strip()]:
        if k not in text:
            fails.append(f"ASR不一致: '{k}' が無い (ASR: {text})")

    st, en, dur = silences(path, a.silence_thr, a.silence_min)
    speech_end = st[-1] if st and (not en or st[-1] > en[-1] - 1e-6) else dur

    for s, e in zip(st, en):
        if s > 0.05 and e < speech_end - 0.05 and e - s >= a.silence_min:
            v = seg_stat(path, s + 0.03, e - 0.03, "max")
            if v > a.gap_max:
                fails.append(f"ギャップ{s:.2f}-{e:.2f}sに突発音 max={v}dB")

    floor = min_window_rms(path, dur)
    if floor > a.floor:
        fails.append(f"真の静寂なし: 最小100ms RMS={floor:.1f}dB（常時ノイズ／残響の疑い）")

    tail = seg_stat(path, min(speech_end + 0.06, dur), min(speech_end + 0.30, dur), "mean")
    if tail > a.tail:
        fails.append(f"残響尾: 発話後+0.06〜0.30s RMS={tail:.1f}dB")

    for s, e, lvl, v in blips(path, a.blip_on, a.blip_off, a.gap_max):
        vt = "不明" if v is None else f"{v:.2f}"
        fails.append(f"単発音(ブリップ) {s:.2f}-{e:.2f}s RMS={lvl:.1f}dB 周期性={vt}"
                     f"（前後が静寂・非有声の突発音）")

    pk = peak_dbfs(path)
    if pk > a.peak:
        fails.append(f"ピーク {pk:.1f}dBFS（振り切れ。-1dBFS 程度に正規化する）")

    print(f"ASR: {text}")
    if fails:
        print("FAIL:\n  " + "\n  ".join(fails))
        return 1
    print(f"PASS (floor={floor:.1f}dB, tail={tail:.1f}dB, peak={pk:.1f}dBFS)")
    return 0


# ---------------------------------------------------------------------------
# cut-gaps: 指定した「間」だけを外科的に詰める
# ---------------------------------------------------------------------------
def parse_gap(text: str) -> tuple[float, float]:
    try:
        s0, s1 = text.split(":")
        return float(s0), float(s1)
    except ValueError:
        raise argparse.ArgumentTypeError(f"--gaps は 開始秒:終了秒 の形式で指定してください: {text}")


def cmd_cut_gaps(a: argparse.Namespace) -> int:
    """build_chunk.py の一律しきい値では消せない語中の間（0.1〜0.25秒）を位置指定で詰める。

    合格基準: 実行後に出る blocks（発話のかたまり）と gaps（その間隔）を見て、
      狙った間だけが消え、ほかの間が不自然に詰まっていないこと。耳でも一度確認する。
    間の位置は `ffmpeg -i 入力.mp4 -af silencedetect=noise=-35dB:d=0.08 -f null -` で測れる。
    """
    src, dst = Path(a.src), Path(a.dst)
    if not src.exists():
        raise SystemExit(f"ファイルがありません: {src}")
    total = _asr.probe_duration(src)

    segs: list[tuple[float, float]] = []
    t = 0.0
    for s0, s1 in sorted(a.gaps):
        segs.append((t, s0 + a.keep))
        t = s1
    segs.append((t, total))

    fc: list[str] = []
    for i, (s0, s1) in enumerate(segs):
        fc.append(f"[0:v]trim={s0 + CROSSFADE * i:.3f}:{s1:.3f},setpts=PTS-STARTPTS[v{i}]")
        fc.append(f"[0:a]atrim={s0:.3f}:{s1:.3f},asetpts=PTS-STARTPTS[a{i}]")
    fc.append("".join(f"[v{i}]" for i in range(len(segs))) + f"concat=n={len(segs)}:v=1:a=0[vc]")
    prev = "a0"
    for i in range(1, len(segs)):
        fc.append(f"[{prev}][a{i}]acrossfade=d={CROSSFADE}[ax{i}]")
        prev = f"ax{i}"
    fc.append(f"[{prev}]anull[ac]")

    r = run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(src),
             "-filter_complex", ";".join(fc), "-map", "[vc]", "-map", "[ac]",
             "-r", str(a.fps), "-c:v", "libx264", "-crf", "18", "-c:a", "aac", "-b:a", "192k", str(dst)])
    if r.returncode != 0:
        print("ffmpeg 失敗:\n" + r.stderr.strip()[-600:])
        return 1

    after = _asr.probe_duration(dst)
    st, en, _ = silences(dst, "-35dB", 0.08)
    blocks: list[tuple[float, float]] = []
    last = 0.0
    for s0, s1 in zip(st, en + [after] * (len(st) - len(en))):
        if s0 > last + 0.01:
            blocks.append((round(last, 2), round(s0, 2)))
        last = s1
    if last < after - 0.01:
        blocks.append((round(last, 2), round(after, 2)))
    gaps_after = [round(blocks[i + 1][0] - blocks[i][1], 2) for i in range(len(blocks) - 1)]
    print(f"{total:.3f}s → {after:.3f}s")
    print(f"  blocks: {blocks}")
    print(f"  gaps  : {gaps_after}")
    return 0


# ---------------------------------------------------------------------------
# scan-gates: シーン境界のクリック音（「プチッ」）を探す
# ---------------------------------------------------------------------------
WINDOW_SEC = 0.30      # 境界の前後を見る窓
LEAD_SEC = 0.15        # 窓の開始を境界の何秒前に置くか


def pcm(path: Path, start: float, dur: float = WINDOW_SEC, sr: int = PCM_SR) -> tuple[int, ...]:
    """指定位置のモノラル16bit PCM を読む（numpy 不要）。"""
    r = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", str(start), "-t", str(dur),
         "-i", str(path), "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"],
        capture_output=True)
    n = len(r.stdout) // 2
    return struct.unpack(f"<{n}h", r.stdout[:n * 2])


def cmd_scan_gates(a: argparse.Namespace) -> int:
    """シーンのつなぎ目では波形が急に飛ぶことがあり、それが小さなクリック音になる。
    各境界の前後 0.3 秒を読み、隣り合うサンプルの振幅の最大跳躍量（jump）と、
    その区間の音量に対する比（ratio）を出す。跳躍が大きいほどクリックの疑いが濃い。

    合格基準: どの境界も「CLICK?」が付かないこと。
    直し方: build_chunk.py のクロスフェードを入れるか、該当シーンの音声の頭・尾をゼロ交差で切り直す。
    """
    path = Path(a.video)
    if not path.exists():
        raise SystemExit(f"ファイルがありません: {path}")
    durs = [float(x) for x in a.durations.split(",") if x.strip()]
    if not durs:
        raise SystemExit("尺をカンマ区切りで1つ以上指定してください")

    rows: list[tuple[int, float, int, float]] = []
    t = 0.0
    for i, d in enumerate(durs, 1):
        t += d
        s = pcm(path, max(0.0, t - LEAD_SEC))
        if len(s) < 100:
            continue
        mj = max(abs(s[j] - s[j - 1]) for j in range(1, len(s)))
        rms = math.sqrt(sum(x * x for x in s) / len(s)) or 1.0
        rows.append((i, round(t, 2), mj, round(mj / (rms + 1), 1)))

    rows.sort(key=lambda r: -r[2])
    ng = 0
    for r in rows[:a.top]:
        flag = "CLICK?" if r[2] > a.jump and r[3] > a.ratio else ""
        if flag:
            ng += 1
        print(f"boundary#{r[0]:2d} t={r[1]:7.2f} jump={r[2]:5d} ratio={r[3]:4.1f} {flag}")
    if ng:
        print(f"\n✗ クリック疑い {ng}件（jump > {a.jump} かつ ratio > {a.ratio}）")
        return 1
    print(f"\n✓ 境界 {len(rows)}箇所にクリックの疑いなし")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("check", help="1テイクの音声を機械で検品する",
                       description=cmd_check.__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("audio", help="検査する音声または動画ファイル")
    p.add_argument("keywords", nargs="?", default="", help="文字起こしに含まれるべき語（カンマ区切り）")
    p.add_argument("--gap-max", type=float, default=-36.0, help="語間ギャップに許す最大音量dB（既定 -36）")
    p.add_argument("--floor", type=float, default=-55.0, help="真の静寂とみなす最小100ms RMS dB（既定 -55）")
    p.add_argument("--tail", type=float, default=-38.0, help="発話直後の残響の許容RMS dB（既定 -38）")
    p.add_argument("--peak", type=float, default=-0.5, help="許容ピークdBFS（既定 -0.5）")
    p.add_argument("--blip-on", type=float, default=-30.0, help="突発音とみなす立ち上がりdB（既定 -30）")
    p.add_argument("--blip-off", type=float, default=-40.0, help="突発音の終わりとみなすdB（既定 -40）")
    p.add_argument("--silence-thr", default="-38dB", help="無音検出のしきい値（既定 -38dB）")
    p.add_argument("--silence-min", type=float, default=0.12, help="無音とみなす最短秒（既定 0.12）")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("cut-gaps", help="指定した無音区間だけを詰める",
                       description=cmd_cut_gaps.__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("src", help="入力の動画ファイル")
    p.add_argument("dst", help="出力の動画ファイル")
    p.add_argument("--gaps", nargs="+", required=True, type=parse_gap, metavar="開始:終了",
                   help="詰める無音区間（秒）。複数指定できる")
    p.add_argument("--keep", type=float, default=0.06, help="各カット位置に残す無音秒（既定 0.06）")
    p.add_argument("--fps", type=int, default=30, help="出力のフレームレート（既定 30）")
    p.set_defaults(func=cmd_cut_gaps)

    p = sub.add_parser("scan-gates", help="シーン境界のクリック音を探す",
                       description=cmd_scan_gates.__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("video", help="書き出した mp4")
    p.add_argument("durations", help="各シーンの尺（秒）をカンマ区切りで")
    p.add_argument("--jump", type=int, default=2500, help="クリック疑いとする振幅跳躍（既定 2500）")
    p.add_argument("--ratio", type=float, default=1.0, help="跳躍/音量 の比の閾値（既定 1.0）")
    p.add_argument("--top", type=int, default=10, help="表示件数（既定 10）")
    p.set_defaults(func=cmd_scan_gates)

    a = ap.parse_args()
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
