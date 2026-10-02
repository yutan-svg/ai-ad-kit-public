#!/usr/bin/env python3
"""テロップと被写体の重なりを機械判定する（「目視でクリアしています」を禁止するための強制チェック）。

なぜ必要か: テロップの外接矩形だけ測って被写体側を目で見て判断すると、「被写体の上でクリア」と
誤って報告する事故が起きる（実際は耳や手に重なっていた、など）。以後、クリアランスの主張は
このスクリプトの出力を根拠にする。目視で「重なっていない」と断定してはいけない。

何を検査するか: 指定フレームを Remotion で静止画に書き出し、テロップの「実インク画素」を色で拾い、
その周囲のリング（＝実際に遮蔽している境界）に被写体クラスの画素がどれだけ入っているかを数える。

使い方（案件フォルダのルートで）:
  python3 scripts/check_overlap.py <コンポジション名> <フレーム番号> [フレーム番号...] \\
      [--ink yellow,white] [--halo 0,5] [--subjects skin,dark,warm] [--entry src/index.ts]

合格基準: 全フレームで接触率が 1.0% 未満（「クリア」表示）なら exit 0。1箇所でも重なれば exit 1。
  被写体クラスは色で近似検出するので完全ではない。「0%でなければ重なっている」という向きにのみ使う
  （重なりを見落とさないための道具であって、重なりが無いことの証明ではない）。

失敗時に見る場所: 表示される ink の x/y 範囲と接触クラス。テロップを動かすか、被写体側の構図を変える。

--ink: テロップの色。yellow / white / red / black / cyan から選ぶ（複数可）。
  縁取りのある文字では、既定のリングが縁の内側に入り、文字色と縁色の中間（アンチエイリアス）画素を
  被写体と誤分類することがある。そのときは --halo でリングを縁の外に置く。
  例: 白フチ19px（外側9px）の赤文字 → --ink red --halo 11,16
--subjects: 検出する被写体クラス。skin（肌）/ dark（髪・暗部）/ warm（暖色の被写体。動物の毛・木材など）
  例: 犬が写るカットで毛に重なっていないか見る → --subjects warm,skin
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

# テロップのインク色。「この色の画素はテロップの文字である」という近似。
INK_PRESETS = {
    "yellow": lambda r, g, b: r > 195 and g > 180 and b < 140,
    "red": lambda r, g, b: r > 150 and g < 90 and b < 110,
    "white": lambda r, g, b: r > 235 and g > 235 and b > 235,
    "black": lambda r, g, b: r < 45 and g < 45 and b < 45,
    "cyan": lambda r, g, b: b > 190 and g > 170 and r < 140,
}

# 被写体クラス。色域での近似検出。案件に合わせて必要なものだけ --subjects で選ぶ。
SUBJECT_PRESETS = {
    "warm": lambda r, g, b: r > 120 and r - b > 45 and r - g > 20,          # 暖色（動物の毛・木材・土など）
    "skin": lambda r, g, b: r > 150 and r - b > 20 and abs(r - g) < 50 and g > b,  # 肌（顔・手）
    "dark": lambda r, g, b: r < 70 and g < 70 and b < 70,                   # 髪・暗部
}

HIT_PERCENT = 1.0  # このパーセント以上の接触を「重なりあり」とする


def render_still(entry: str, comp: str, frame: str, out: Path, cwd: Path) -> None:
    subprocess.run(["npx", "remotion", "still", entry, comp, str(out), f"--frame={frame}", "--log=error"],
                   cwd=cwd, capture_output=True)


def read_rgb(path: Path) -> tuple[bytes, int, int]:
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height",
                            "-of", "csv=p=0", str(path)], capture_output=True, text=True).stdout.strip()
    parts = [p for p in probe.replace("\n", ",").split(",") if p.strip().isdigit()]
    if len(parts) < 2:
        raise SystemExit(f"静止画を読めません（remotion still に失敗した可能性）: {path}")
    w, h = int(parts[0]), int(parts[1])
    buf = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vf", "format=rgb24",
                          "-f", "rawvideo", "-"], capture_output=True).stdout
    return buf, w, h


def ink_mask(buf: bytes, w: int, h: int, kinds: list[str]) -> set[tuple[int, int]]:
    """指定色のテロップ実インク画素（外接矩形ではない）。
    色を取り違えると『検出なし＝クリア』の誤判定になるため、未検出は呼び出し側でエラー扱いにする。"""
    tests = [INK_PRESETS[k] for k in kinds]
    px: set[tuple[int, int]] = set()
    for y in range(h):
        row = y * w
        for x in range(w):
            i = (row + x) * 3
            r, g, b = buf[i], buf[i + 1], buf[i + 2]
            if any(t(r, g, b) for t in tests):
                px.add((x, y))
    return px


def dilate(px: set[tuple[int, int]], r: int) -> set[tuple[int, int]]:
    out: set[tuple[int, int]] = set()
    for (x, y) in px:
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                out.add((x + dx, y + dy))
    return out


def classify(buf: bytes, w: int, h: int, x: int, y: int, subjects: list[str]) -> str | None:
    if not (0 <= x < w and 0 <= y < h):
        return None
    i = (y * w + x) * 3
    r, g, b = buf[i], buf[i + 1], buf[i + 2]
    if r > 200 and g > 200 and b > 200:
        return None           # 白フチ・白のアンチエイリアス（被写体ではない）
    if r > 170 and r - g > 60 and b > g - 10 and b > 90:
        return None           # 文字色→白フチ のアンチエイリアス（中間色）
    for name in subjects:
        if SUBJECT_PRESETS[name](r, g, b):
            return name
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("comp", help="Remotion のコンポジション名")
    ap.add_argument("frames", nargs="+", help="検査するフレーム番号（複数可）")
    ap.add_argument("--ink", default="yellow,white", help="テロップの色（既定 yellow,white）")
    ap.add_argument("--halo", default="0,5",
                    help="接触を調べるリング「インクから IN px 外側〜OUT px 外側」（既定 0,5）")
    ap.add_argument("--subjects", default="skin,dark",
                    help="検出する被写体クラス（既定 skin,dark）")
    ap.add_argument("--entry", default="src/index.ts", help="Remotion のエントリ（既定 src/index.ts）")
    ap.add_argument("--hit-percent", type=float, default=HIT_PERCENT,
                    help=f"重なりと判定する接触率%%（既定 {HIT_PERCENT}）")
    a = ap.parse_args()

    kinds = [k.strip() for k in a.ink.split(",") if k.strip()]
    for k in kinds:
        if k not in INK_PRESETS:
            raise SystemExit(f"--ink に使えない色: {k}（{'/'.join(INK_PRESETS)}）")
    subjects = [s.strip() for s in a.subjects.split(",") if s.strip()]
    for s in subjects:
        if s not in SUBJECT_PRESETS:
            raise SystemExit(f"--subjects に使えないクラス: {s}（{'/'.join(SUBJECT_PRESETS)}）")
    try:
        halo_in, halo_out = [int(v) for v in a.halo.split(",")]
    except ValueError:
        raise SystemExit("--halo は IN,OUT の形式で指定してください（例: 0,5）")

    cwd = Path.cwd()
    ng = False
    with tempfile.TemporaryDirectory() as td:
        for f in a.frames:
            png = Path(td) / f"f{f}.png"
            render_still(a.entry, a.comp, f, png, cwd)
            if not png.exists():
                print(f"frame {f}: ★静止画を書き出せなかった（コンポジション名・エントリを確認）")
                ng = True
                continue
            buf, w, h = read_rgb(png)
            ink = ink_mask(buf, w, h, kinds)
            if not ink:
                print(f"frame {f}: ★テロップを検出できず（--ink の色指定を確認）。クリア判定は不可")
                ng = True
                continue
            xs = [p[0] for p in ink]
            ys = [p[1] for p in ink]
            halo = dilate(ink, halo_out) - (dilate(ink, halo_in) if halo_in > 0 else ink)
            counts: dict[str, int] = {}
            for (x, y) in halo:
                c = classify(buf, w, h, x, y, subjects)
                if c:
                    counts[c] = counts.get(c, 0) + 1
            total = max(1, len(halo))
            desc = " ".join(f"{k}={100 * v / total:.1f}%" for k, v in sorted(counts.items())) or "被写体なし"
            hit = [k for k, v in counts.items() if 100 * v / total >= a.hit_percent]
            print(f"frame {f}: ink x{min(xs)}-{max(xs)} y{min(ys)}-{max(ys)} halo[{halo_in},{halo_out}]"
                  f" | 接触: {desc}" + (f"  ← 重なりあり({','.join(hit)})" if hit else "  ← クリア"))
            if hit:
                ng = True

    print("\n結論: " + ("重なりを検出。『クリア』と報告してはいけない。" if ng else "全フレームでクリア。"))
    return 1 if ng else 0


if __name__ == "__main__":
    sys.exit(main())
