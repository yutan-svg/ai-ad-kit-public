#!/usr/bin/env python3
"""生テイク → 採用クリップ の標準加工パイプライン（頭トリム・ギャップ詰め・crossfade・尾フェード）。

  python3 scripts/build_chunk.py <入力mp4> --out <出力mp4> [--audio-out <出力m4a>]
        [--speed 1.0] [--precut SEC] [--gap 0.6] [--no-asr]

処理: （--speed≠1 なら速度の焼き込み）→ 頭トリム → --gap 秒超の無音ギャップカット → acrossfade 接続 → 尾フェード
      → 出力mp4（と音声だけの m4a）を書き出す。最後に silencedetect 実測の「発話ブロック」と ASR を表示する。

- 速度は既定で等速。再生速度は音声に焼かず、動画編集ツール（Remotion）側の playbackRate で指定する
  （二重に速度を焼くと音質が落ちる。速度の正本は Remotion 側に一本化する）
- シーン境界の配線はここで出る「speech blocks」の実測を使う（音声認識のトークン時刻は ±0.7秒ずれる）
- --gap は語間の不自然な間を詰める閾値。等速なら 0.6 前後（1.35倍速で焼く旧方式は 0.45）。0.25 未満にすると
  読点のブレスまで消えて早口に聞こえる
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _config import load_config, rel, whisper_model  # noqa: E402


def sh(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def dur(path):
    return float(sh(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                     "-of", "csv=p=0", str(path)]).stdout.strip())


def silences(path, noise="-33dB", d="0.28"):
    out = sh(["ffmpeg", "-hide_banner", "-i", str(path), "-af",
              f"silencedetect=noise={noise}:d={d}", "-f", "null", "-"]).stderr
    st = [float(x) for x in re.findall(r"silence_start: ([0-9.]+)", out)]
    en = [float(x) for x in re.findall(r"silence_end: ([0-9.]+)", out)]
    return list(zip(st, en + [None] * (len(st) - len(en))))


def build(raw: Path, out: Path, audio_out: Path | None, speed: float = 1.0, precut: float | None = None,
          gap: float = 0.6, asr_model: Path | None = None, language: str = "ja"):
    assert raw.exists(), raw
    tmp = Path(tempfile.mkdtemp(prefix="build_chunk-"))
    src = raw
    if precut:
        pre = tmp / "pre.mp4"
        sh(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(raw), "-ss", str(precut),
            "-c:v", "libx264", "-crf", "18", "-c:a", "aac", "-b:a", "192k", str(pre)])
        src = pre

    sp = tmp / "sp.mp4"
    if abs(speed - 1.0) > 1e-6:
        # 速度は atempo（ピッチ維持）で一度に焼く。二重に atempo をかけると音質が落ちる
        sh(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(src), "-filter_complex",
            f"[0:v]setpts=PTS/{speed}[v];[0:a]atempo={speed}[a]", "-map", "[v]", "-map", "[a]",
            "-r", "30", "-c:v", "libx264", "-crf", "18", "-c:a", "aac", "-b:a", "192k", str(sp)])
    else:
        sh(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(src),
            "-r", "30", "-c:v", "libx264", "-crf", "18", "-c:a", "aac", "-b:a", "192k", str(sp)])

    sil = silences(sp)
    D = dur(sp)
    head = sil[0][1] - 0.22 if sil and sil[0][0] <= 0.05 and sil[0][1] else 0.0
    keep, t = [], head
    for a, b in sil:
        if b is None:
            b = D
        if a <= head:
            continue
        if b - a > gap and b < D - 0.2:
            keep.append((t, a + 0.12))
            t = b - 0.03
    keep.append((t, D))

    fc, xf = [], 0.02
    for i, (a, b) in enumerate(keep):
        fc.append(f"[0:v]trim={a + xf * i:.3f}:{b:.3f},setpts=PTS-STARTPTS[v{i}]")
        fc.append(f"[0:a]atrim={a:.3f}:{b:.3f},asetpts=PTS-STARTPTS[a{i}]")
    fc.append("".join(f"[v{i}]" for i in range(len(keep))) + f"concat=n={len(keep)}:v=1:a=0[vc]")
    prev = "a0"
    for i in range(1, len(keep)):
        fc.append(f"[{prev}][a{i}]acrossfade=d={xf}[ax{i}]")
        prev = f"ax{i}"
    tot = sum(b - a for a, b in keep) - xf * (len(keep) - 1)
    fc.append(f"[{prev}]afade=t=out:st={tot - 0.13:.3f}:d=0.13,afade=t=in:st=0:d=0.05[ac]")

    out.parent.mkdir(parents=True, exist_ok=True)
    r = sh(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(sp),
            "-filter_complex", ";".join(fc), "-map", "[vc]", "-map", "[ac]",
            "-r", "30", "-c:v", "libx264", "-crf", "18", "-c:a", "aac", "-b:a", "192k", str(out)])
    assert r.returncode == 0, r.stderr[-300:]
    m4a = audio_out or (tmp / "audio.m4a")
    Path(m4a).parent.mkdir(parents=True, exist_ok=True)
    sh(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(out),
        "-vn", "-c:a", "aac", "-b:a", "192k", str(m4a)])

    # 発話ブロック実測（配線はこの値を使う）
    fine = silences(m4a, noise="-35dB", d="0.1")
    DD = dur(m4a)
    blocks, last = [], 0.0
    for a, b in fine:
        if b is None:
            b = DD
        if a > last + 0.02:
            blocks.append((round(last, 2), round(a, 2)))
        last = b
    if last < DD - 0.02:
        blocks.append((round(last, 2), round(DD, 2)))

    print(f"{out.name} {round(DD, 3)}s (speed x{speed}, gap {gap}s)")
    if asr_model:
        wav = tmp / "asr.wav"
        sh(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(m4a), "-ar", "16000", "-ac", "1", str(wav)])
        r = sh(["whisper-cli", "-m", str(asr_model), "-l", language, "-nt", "-np", str(wav)])
        print(f"  ASR: {r.stdout.strip().replace(chr(10), ' ')}")
    print(f"  speech blocks: {blocks}")
    return DD, blocks


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", help="生テイクの mp4")
    ap.add_argument("--out", required=True, help="出力 mp4")
    ap.add_argument("--audio-out", default=None, help="音声だけの m4a の出力先（省略可）")
    ap.add_argument("--speed", type=float, default=1.0, help="焼き込む再生速度（既定 1.0 = 等速。速度は Remotion 側で指定するのが標準）")
    ap.add_argument("--precut", type=float, default=None, help="頭から捨てる秒数（誤発話の救済）")
    ap.add_argument("--gap", type=float, default=0.6, help="この秒数を超える無音を詰める")
    ap.add_argument("--no-asr", action="store_true", help="最後の ASR 表示を省く")
    a = ap.parse_args()
    cfg = load_config()
    model = None if a.no_asr else whisper_model(cfg, required=False)
    if not a.no_asr and model is None:
        print("NOTE whisper モデルが無いので ASR 表示は省きます")
    build(Path(a.input), Path(a.out), Path(a.audio_out) if a.audio_out else None, a.speed, a.precut, a.gap,
          model, cfg["language"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
