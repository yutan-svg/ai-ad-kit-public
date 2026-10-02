#!/usr/bin/env python3
"""レンダー前の総合検査（preflight）。書き出し・レビュー依頼の前に必ず通す。

何を検査するか（シーン定義のテキストと素材ファイルだけを読む。レンダー不要なので数秒・低コスト）:
  1. テロップのはみ出し  1行の文字数 × fontSize が安全幅（画面幅 − 左右マージン×2）を超えないか
  2. テロップの行数      captionMaxRows（既定3行）を超えないか
  3. highlights の不整合 caption のどの行にも含まれない highlight（指定しても色が付かない）
  4. テロップの縦位置    図解シーン（graphicVisuals）でテロップが図と衝突する高さに無いか
  5. 素材の尺切れ        videoStartSeconds + 尺 × playbackRate ≦ 素材の実尺（超えると最後がフリーズする）
  6. 参照ファイルの実在  src / audioSrc / photoSrc（欠けるとレンダーが 404 で落ちる）
  7. 音声とシーンの尺整合 トラックの尺 vs そのトラックが担当するシーン群の合計尺
  8. 末尾無音・混入音素  音声末尾に長い無音、または次の語の頭が孤立して残っていないか
  9. 納品尺              合計尺が maxTotalSeconds（既定118秒）を超えないか
 10. 耳での確認          危険語（数字・固有名詞・辞書登録語）を含むセリフが、人の耳で確かめられているか
                        （out/ear-check.json。記録は scripts/ear_check.py が対話で作る。機械の一致だけでは合格にしない）

使い方（案件フォルダのルートで。引数なしなら ai-ad.config.json の sceneFiles を全部見る）:
  python3 scripts/preflight.py [src/scenes.ts ...]

合格基準: 指摘0件で exit 0。1件でもあれば一覧を表示して exit 1（この状態でレンダーしてはいけない）。
失敗時に見る場所: 表示される [シーンID] / [track シーンID] と、そのシーン定義ファイルの該当行。
  テロップ幅はフォント縮小より先に「行の割り直し」を検討する。音声の指摘は再生成の前に
  build_chunk.py / audio_tools.py cut-gaps の無コスト救済から試す。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _asr  # noqa: E402
import _gates  # noqa: E402
from _config import (  # noqa: E402
    caption_rows,
    load_config,
    parse_scenes,
    parse_tracks,
    rel,
    resolve,
    scene_files,
)

# 全角1文字あたりの実効幅は fontSize とほぼ等しい（日本語ゴシック・太字）。
# 影・縁取りを見込んだ係数で見積もる。フォントを変えると実測が変わるので、
# ai-ad.config.json の fontFamily / fontCharWidth / captionCharWidth で調整できる。
DEFAULT_CHAR_W = 1.02


def char_width(cfg: dict[str, Any]) -> float:
    if cfg.get("captionCharWidth"):
        return float(cfg["captionCharWidth"])
    table = cfg.get("fontCharWidth") or {}
    return float(table.get(str(cfg.get("fontFamily", "")), DEFAULT_CHAR_W))


def silence_ranges(path: Path, noise: str, min_silence: float) -> tuple[list[float], list[float]]:
    """silencedetect の silence_start / silence_end の一覧を返す。"""
    out = _asr.run(["ffmpeg", "-hide_banner", "-i", str(path), "-af",
                    f"silencedetect=noise={noise}:d={min_silence}", "-f", "null", "-"]).stderr
    starts = [float(x) for x in re.findall(r"silence_start: (-?[0-9.]+)", out)]
    ends = [float(x) for x in re.findall(r"silence_end: (-?[0-9.]+)", out)]
    return starts, ends


def check_caption(sc: dict[str, Any], cfg: dict[str, Any], issues: list[str]) -> None:
    cap = sc.get("caption")
    if not cap:
        return
    sid = sc["id_str"]
    fs = sc.get("fontSize") or int(cfg["defaultFontSize"])
    rows = caption_rows(cap)
    safe_w = int(cfg["videoWidth"]) - int(cfg["safeMarginPx"]) * 2
    cw = char_width(cfg)

    if len(rows) > int(cfg["captionMaxRows"]):
        issues.append(f"[{sid}] テロップ {len(rows)}行（{cfg['captionMaxRows']}行超は禁止）")
    for r in rows:
        if not r:
            continue
        est = len(r) * fs * cw
        if est > safe_w:
            issues.append(
                f"[{sid}] テロップはみ出し: 「{r}」{len(r)}字×{fs}px≒{int(est)}px > 許容{safe_w}px"
                f" → 改行するか fontSize を {int(safe_w / (len(r) * cw))}px 以下に")

    # 縦配置バンド: 図解・グラフィックシーンのみ適用。
    # 人物シーンは口元との関係が優先なので対象外（graphicVisuals に入れない）。
    # 注意: テロップは translateY(-50%) 前提＝captionY は「ブロック中心」。
    #       上端 = cy - h/2, 下端 = cy + h/2 で判定する。
    graphic = [str(v) for v in cfg.get("graphicVisuals") or []]
    if graphic:
        vis = re.search(r"\bvisual:\s*'([^']*)'", sc.get("raw", ""))
        cym = re.search(r"\bcaptionY:\s*(-?[0-9.]+)", sc.get("raw", ""))
        if vis and cym and vis.group(1) in graphic:
            cy = float(cym.group(1))
            block_h = len(rows) * fs * 1.42
            bottom, top_edge = cy + block_h / 2, cy - block_h / 2
            if bottom > float(cfg["captionBandBottom"]):
                issues.append(
                    f"[{sid}] テロップが下すぎ: 下端{bottom:.0f}px > {cfg['captionBandBottom']}px"
                    f" → captionY を {int(float(cfg['captionBandBottom']) - block_h / 2)} 以下に")
            if top_edge < float(cfg["captionBandTop"]):
                issues.append(
                    f"[{sid}] テロップ上端{top_edge:.0f}px < {cfg['captionBandTop']}px（図解と衝突の疑い）")

    hls = re.search(r"\bhighlights:\s*\[([^\]]*)\]", sc.get("raw", ""))
    if hls:
        for h in re.findall(r"'([^']*)'", hls.group(1)):
            # 行内の部分一致でも色は付くので、どの行にも含まれない場合だけ不合格
            if h and not any(h in r for r in rows):
                issues.append(
                    f"[{sid}] highlight「{h}」が caption のどの行にも含まれない（色が付かない）: 行は {rows}")


def check_assets(sc: dict[str, Any], cfg: dict[str, Any], public: Path, issues: list[str]) -> None:
    sid = sc["id_str"]
    for field in ("src", "audioSrc", "photoSrc"):
        ref = sc.get(field)
        if not ref or ref.startswith(("http://", "https://", "data:")):
            continue
        p = public / ref
        if not p.exists():
            issues.append(f"[{sid}] 参照ファイルが存在しない: {ref}")
            continue
        if field != "src":
            continue
        real = _asr.probe_duration(p)
        d = sc.get("durationSeconds") or 0.0
        vss = sc.get("videoStartSeconds") or 0.0
        rate = sc.get("playbackRate") or 1.0
        need = vss + d * rate
        if real and need > real + 0.01:
            issues.append(f"[{sid}] 尺切れ（末尾フリーズ事故）: 必要 {need:.2f}s > 素材 {real:.2f}s（{ref}）")


def check_audio_provenance(cfg: dict[str, Any], public: Path, issues: list[str]) -> None:
    """assets/audio/ の下で使われている音（BGM・効果音・ナレーション以外の読み込み音）は、
    knowledge/assets.md の「音」の表に出所と利用条件が書かれていなければ止める。
    実際に、AI が ffmpeg で合成した音を「著作権フリーの BGM・SE」と報告した事故があった。"""
    root = resolve(cfg, ".")
    used: set[str] = set()
    for src_file in list((root / "src").rglob("*.ts")) + list((root / "src").rglob("*.tsx")):
        for m in re.finditer(r"['\"](audio/[^'\"]+\.(?:mp3|wav|m4a|aac|ogg))['\"]", src_file.read_text(encoding="utf-8")):
            used.add(m.group(1))
    if not used:
        return
    ledger = root / "knowledge" / "assets.md"
    text = ledger.read_text(encoding="utf-8") if ledger.exists() else ""
    sec = text.split("## 音", 1)[1] if "## 音" in text else ""
    rows: dict[str, list[str]] = {}
    for line in sec.splitlines():
        if line.startswith("|") and not set(line) <= set("|-: "):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if cells and cells[0] not in ("ファイル",):
                rows[cells[0].strip("`")] = cells
    for ref in sorted(used):
        if not (public / ref).exists():
            continue  # 実在しないものは check_assets が別に指摘する
        name = ref.split("/")[-1]
        row = rows.get(ref) or rows.get(name) or rows.get("assets/" + ref)
        cond = row[4] if row and len(row) > 4 else ""
        if not row or not cond.strip():
            issues.append(f"[音の出所] {ref}: knowledge/assets.md の「音」の表に出所と利用条件がありません。"
                          "どこから入手した音か（配布元 URL・規約・クレジット要否）を書いてから進めてください。"
                          "自分で合成した音なら「ffmpeg で合成（正弦波）」のように、そのとおり書きます。出所を伏せて「著作権フリー」とだけ書いてはいけません")


def check_fixes_ledger(cfg: dict[str, Any], issues: list[str]) -> None:
    """同じセリフを2回以上作っている（＝指摘か失敗で作り直した）のに、指摘台帳 FIXES.md が無ければ止める。
    実際に、指摘10件を CURRENT.md の文章にだけ書いて台帳を作らなかったことがあった。"""
    root = resolve(cfg, ".")
    ledger = _gates.load_ledger(cfg)
    remade = [k for k, v in ledger.items() if int((v or {}).get("count", 0)) >= 2 and k != "reference"]
    if remade and not (root / "FIXES.md").exists() and not (root / "knowledge" / "FIXES.md").exists():
        issues.append(f"[指摘台帳] 作り直しがある（{', '.join(remade)}）のに FIXES.md がありません。"
                      "指摘は1件1行で FIXES.md に記録してください（完了の印を付けるのは依頼主だけ）")


def check_track_audio(track: dict[str, Any], path: Path, cfg: dict[str, Any], issues: list[str]) -> None:
    at = track["atSceneId"]
    real = _asr.probe_duration(path)
    tdur = track.get("durationSeconds")
    if real and tdur and float(tdur) > real + 0.05:
        issues.append(f"[track {at:g}] トラック尺 {tdur}s > 実ファイル {real:.2f}s（{path.name}）")

    # 末尾の混入音素: 長い音声から切り出すと次の語の頭が 0.1 秒前後の孤立した音として残ることがある。
    # 細かい閾値で発話ブロックを取り、最後が極端に短く、直前に間があれば疑う。
    fs, fe = silence_ranges(path, "-38dB", 0.03)
    if real and len(fe) >= 1 and len(fs) >= 2:
        blocks: list[tuple[float, float]] = []
        last = fe[0] if fs and fs[0] <= 0.05 else 0.0
        for a, b in zip(fs, fe + [real] * (len(fs) - len(fe))):
            if a > last + 0.01:
                blocks.append((last, a))
            last = b
        if last < real - 0.01:
            blocks.append((last, real))
        if len(blocks) >= 2:
            lb, prev = blocks[-1], blocks[-2]
            gap = lb[0] - prev[1]
            # 0.06秒未満は子音の破裂音など。音素として成立する 0.06〜0.35秒だけ疑う
            if 0.06 <= lb[1] - lb[0] < 0.35 and gap > 0.08:
                issues.append(
                    f"[track {at:g}] 末尾に孤立した短音 {lb[0]:.2f}-{lb[1]:.2f}s "
                    f"（{lb[1] - lb[0]:.2f}s、直前に{gap:.2f}sの間）→ 次の語の頭が混入している可能性。"
                    f"波形を目視して切り直すこと: {path.name}")

    # 末尾無音: 最後の無音が「終端まで続いている」場合のみ。
    # silence_end があってその後に発話が続くなら、それは文中の間であって末尾無音ではない。
    st, en = silence_ranges(path, "-35dB", 0.1)
    if st and real and (len(en) < len(st) or en[-1] >= real - 0.05):
        tail = real - st[-1]
        if tail > float(cfg["trackTailSilenceMaxSec"]):
            issues.append(
                f"[track {at:g}] 末尾に {tail:.2f}s の無音（余韻が不自然に伸びる）: {path.name}")


def check_ear(sc: dict[str, Any], cfg: dict[str, Any], public: Path, pd: dict[str, Any],
              has_track: bool, issues: list[str]) -> None:
    """危険語を含むセリフは、人の耳で確かめた記録が無ければ不合格にする。

    機械（音声認識）の一致だけでは合格にしない、という決まりを機械で守るための検査。
    記録は scripts/ear_check.py が対話でしか作れない。
    """
    cap = sc.get("caption")
    if not cap:
        return
    sid = sc["id_str"]
    extra, ignore = _gates.ear_check_words_config(cfg)
    words = _gates.danger_words(cap, pd, extra, ignore)
    if not words:
        return
    native = bool(re.search(r"\bnativeAudio:\s*true", sc.get("raw", "")))
    audio_ref = sc.get("audioSrc") or (sc.get("src") if native else None)
    if not audio_ref and not has_track:
        return   # 音の鳴らないシーンは対象外
    keys = [sid]
    if audio_ref:
        stem = Path(audio_ref).stem
        keys += [stem, stem.split("-t")[0]]
    rec = _gates.ear_check_for(cfg, keys)
    if rec is None:
        issues.append(
            f"[{sid}] 耳での確認がありません（危険語: {'、'.join(words)}）"
            f" → python3 scripts/ear_check.py {audio_ref and rel(cfg, public / audio_ref) or '<音声>'}"
            f" --id {sid} --text \"{caption_rows(cap)[0]}…\"")
        return
    if not rec.get("passed"):
        issues.append(f"[{sid}] 耳での確認で「どちらも不可」と判定されています"
                      f"（{rec.get('at')}）→ 台本の表記か読み方の辞書を直してから作り直す")
        return
    chosen = rec.get("chosen")
    if audio_ref and chosen and Path(chosen).name == Path(audio_ref).name:
        p_audio = public / audio_ref
        if p_audio.exists() and rec.get("audio_sha1") and _gates.sha1_of(p_audio) != rec["audio_sha1"]:
            issues.append(
                f"[{sid}] 耳で確認したときと音声の中身が違います（{audio_ref}）"
                f" → 差し替えたなら、もう一度 scripts/ear_check.py で聴き直してください")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", help="シーン定義ファイル（無指定なら config の sceneFiles）")
    ap.add_argument("--max-total", type=float, default=None, help="納品尺の上限秒（既定: config の maxTotalSeconds）")
    ap.add_argument("--skip-audio", action="store_true", help="音声ファイルの実測を省く（ffmpeg が無い環境の確認用）")
    a = ap.parse_args()

    cfg = load_config()
    _gates.check_project(cfg, "script")
    public = resolve(cfg, cfg["publicDir"])
    max_total = a.max_total if a.max_total is not None else float(cfg["maxTotalSeconds"])
    pd = _asr.load_dicts_from_config(cfg, resolve)
    issues: list[str] = []
    grand_total = 0.0
    scene_count = 0

    for f in scene_files(cfg, a.files):
        text = f.read_text(encoding="utf-8")
        scenes = parse_scenes(text)
        tracks = parse_tracks(text)
        scene_count += len(scenes)
        print(f"=== preflight: {rel(cfg, f)}")

        for sc in scenes:
            check_caption(sc, cfg, issues)
            check_ear(sc, cfg, public, pd, bool(tracks), issues)
            if not a.skip_audio:
                check_assets(sc, cfg, public, issues)

        if not a.skip_audio:
            check_audio_provenance(cfg, public, issues)
        check_fixes_ledger(cfg, issues)

        order = [sc["id_str"] for sc in scenes]
        scene_dur = {sc["id_str"]: (sc.get("durationSeconds") or 0.0) for sc in scenes}
        own_audio = {sc["id_str"] for sc in scenes if sc.get("audioSrc")}
        other_tracks = {f"{t['atSceneId']:g}" for t in tracks}

        for t in tracks:
            at = f"{t['atSceneId']:g}"
            p = public / t["src"]
            if not p.exists():
                issues.append(f"[track {at}] 音声が存在しない: {t['src']}")
            elif not a.skip_audio:
                check_track_audio(t, p, cfg, issues)

            # トラックが担当するシーン群の合計尺と一致しているか
            tdur = t.get("durationSeconds")
            if at in order and tdur:
                covered = 0.0
                nxt = other_tracks - {at}
                for sid in order[order.index(at):]:
                    # 次のトラック開始、または自前の audioSrc を持つシーンで打ち切る
                    if sid != at and (sid in nxt or sid in own_audio):
                        break
                    covered += scene_dur[sid]
                gapsec = abs(covered - float(tdur))
                if gapsec > float(cfg["trackSyncToleranceSec"]):
                    issues.append(
                        f"[track {at}] 音声 {tdur}s とシーン合計 {covered:.2f}s が {gapsec:.2f}s ずれている"
                        f"（無音の間延び／セリフ切れの原因）")

        total = sum(scene_dur.values())
        grand_total += total
        print(f"  scenes={len(scenes)} tracks={len(tracks)} total={total:.2f}s")

    if scene_count == 0:
        print("\nシーンがまだ定義されていません（src/scenes.ts が空です）。")
        print("  制作を始めるとここが埋まります。いまは検査するものがありません。")
        return 0

    if grand_total > max_total:
        issues.append(f"納品尺 {grand_total:.1f}s → 上限 {max_total:.0f}s を超過（尺を詰めること）")

    stamp = resolve(cfg, _gates.PREFLIGHT_OK)
    if issues:
        print(f"\n✗ {len(issues)}件の不合格:")
        for x in issues:
            print("  - " + x)
        if stamp.exists():
            stamp.unlink()
        return 1
    _gates.write_json(stamp, {"at": _gates.now(), "at_epoch": _gates.now_epoch(),
                              "scenes_sha1": _gates.scenes_digest(cfg), "skip_audio": bool(a.skip_audio)})
    print("\n✓ 全項目合格（レンダー可）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
