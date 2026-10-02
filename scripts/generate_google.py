#!/usr/bin/env python3
"""Google のモデル（Veo 3.1 ／ Gemini Omni 1.1 Flash）で、人がセリフを話すクリップを作る。

`scripts/generate_lines.py`（Seedance 版）と**同じ lines.json** を読み、同じ場所（takesDir）に
`<id>-t<n>.mp4` を保存し、**同じ門**（承諾の記録・テイク上限・人物の参照）を通ります。
違うのは生成エンジンだけです。参照画像は Nano Banana 2（`--make-reference`）で作れます。

使い方（案件フォルダのルートで。`.env` に GEMINI_API_KEY が要ります）:

  # 送る内容を見るだけ（API は呼ばない＝無料）
  python3 scripts/generate_google.py --lines lines.json --engine veo --dry-run
  python3 scripts/generate_google.py --lines lines.json --engine omni --dry-run

  # 参照画像を1枚つくる（同じ人物を保つための土台。先に承諾が要ります）
  python3 scripts/approve.py --generation --ids reference --takes 1 --service nano-banana
  python3 scripts/generate_google.py --lines lines.json --make-reference --reference-out assets/images/reference.png

  # 本番（費用がかかります。先に承諾の記録が要ります）
  python3 scripts/approve.py --generation --ids s1 --takes 1 --service veo
  python3 scripts/generate_google.py --lines lines.json --engine veo --ids s1 --seconds 4

lines.json に足せる項目（Seedance 版と共通の項目はそのまま使えます）:
  defaults / 各行:
    "style"            人物と場所の説明（**英語**。日本語で書くと崩れます）
    "prompt_extra"     表情・仕草の追加（英語の短い1文）
    "speaker"          セリフの話者の呼び方（既定 "The speaker"）
    "ambient"          環境音（既定 "quiet room"）
    "negative"         出したくないもの（既定は字幕・透かし・口の破綻）
    "reference_image"  参照画像の**手元のファイルのパス**（Veo は referenceImages、Omni は同じターンの画像）
    "reference_prompt" --make-reference で作る参照画像の指示（英語）
    "resolution"       "720p"（既定）／"1080p"。1080p は8秒だけ
    "ratio"            "9:16"（既定）
    "duration"         4 / 6 / 8（Veo）。Omni は本文に秒数を書いて指示します

日本語のセリフの書き方（公式の作法。詳しくは guides/google-models.md）:
  - 話者 → says → **半角のダブルクオート**で囲む。全角の「」は公式の型ではありません
  - 曖昧な漢字は**ひらがなに開く**（読み方の辞書の `replace` を自動で適用します）
  - **発音（ふりがな・ローマ字）を指定する公式の手段はありません。** 辞書の `guide` は送りません
    （台本にない語を足される原因になるため）。読み違う語は台本の表記を開いてください
  - 「！」は音声の安全フィルタに落ちる実測があるので「。」に置き換えます（置き換えた語は表示します）
  - 字幕を出さない指示は、本文の末尾と negativePrompt の両方に入れます

機械で止まる決まり（文章ではなく、このスクリプトが止めます）:
  1. 生成の承諾   out/generation-approval.json が無ければ生成しない（`scripts/approve.py --generation`）
  2. テイク上限   同じ id への生成は2回まで。3回目は拒否（`--force "理由"` で例外。理由は台帳に残る）
  3. 人物の参照   2セリフ目以降は参照画像が無いと生成しない（`--allow-no-reference` で例外）
                  Veo は referenceImages（最大3枚・使うと尺は8秒固定）、Omni は同じターンに画像を渡します

Google 側の制約（2026-09-17 時点。https://ai.google.dev/gemini-api/docs/veo ／ /docs/omni）:
  - **参照音声は渡せません。** 声を選ぶ・同じ声で本数を揃える案件は Seedance（generate_lines.py）を使います
  - 日本語は公式に「評価外」の言語です。読み違いは仕様上想定されています
  - Omni はトークン課金で、公表の秒単価がありません。金額ではなくトークン数で報告してください
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "lib"))
import _asr  # noqa: E402
import _gates  # noqa: E402
import _google  # noqa: E402
from _config import load_config, rel, resolve  # noqa: E402
from generate_lines import find_existing, judge, print_table  # noqa: E402

VEO_TEMPLATE = (
    "{style} {prompt_extra} "
    '{speaker} says, "{text}" '
    "{speaker}'s mouth movements match the Japanese dialogue exactly, with no extra words. "
    "{speaker} speaks only the words inside the quotation marks and adds nothing after them. "
    "Ambient noise: {ambient}. No on-screen text, no captions, no subtitles."
)
OMNI_TEMPLATE = (
    "Vertical {ratio} video, about {duration} seconds long.\n"
    "[0-{duration}s] {style} {prompt_extra} "
    '{speaker} says in Japanese, "{text}" '
    "The lip movement matches the line exactly, no additional words.\n"
    "Ambient noise: {ambient}. No captions, no subtitles, no on-screen text."
)
REFERENCE_TEMPLATE = (
    "A photorealistic vertical portrait photograph. {style} "
    "Eye-level medium shot, {ratio} vertical framing, soft natural daylight, calm neutral expression, mouth closed. "
    "No on-screen text, no captions, no watermark, no logo."
)
DEFAULT_NEGATIVE = "subtitles, captions, on-screen text, watermark, distorted mouth, mismatched lip sync"
DEFAULT_SPEAKER = "The speaker"
DEFAULT_AMBIENT = "quiet room"
VEO_DURATIONS = (4, 6, 8)

NO_REFERENCE_HELP = """
  同じ人物を保つには、2セリフ目以降に「参照画像」を渡します。Google のモデルには
  「1カット目の動画を参照にする」入り口がないので、**参照画像**で揃えます。順番は決まっています:

    1. 参照画像を1枚つくる（人物と場所を決める）:
         python3 scripts/approve.py --generation --ids reference --takes 1 --service nano-banana
         python3 scripts/generate_google.py --lines lines.json --make-reference
    2. その画像を lines.json に書く:
         "defaults": {"reference_image": "assets/images/reference.png"}
    3. 1カット目を生成して人物を見てもらい、採用が決まってから残りを生成する

  Veo は参照画像を最大3枚まで受け取ります（**使うと尺は8秒に固定**されます）。
  Omni は同じターンに画像を渡します。
  参照なしで進める必要がある場合だけ --allow-no-reference を付けてください（人物は揃いません）。
"""


def say(msg: str) -> None:
    print(msg, flush=True)


# ---------------------------------------------------------------------------
# 台本の整形（Google に渡す前に、落ちる書き方・読み違う書き方を直す）
# ---------------------------------------------------------------------------
def sanitize_text(text: str) -> tuple[str, list[str]]:
    """セリフを Google のモデルに渡せる形に直す。直した内容は表示用に返す。"""
    notes: list[str] = []
    out = text
    for mark in ("！", "!"):
        if mark in out:
            out = out.replace(mark, "。")
            notes.append(f"「{mark}」→「。」（音声の安全フィルタに落ちる実測があるため）")
    for mark in ("「", "」", "『", "』"):
        if mark in out:
            out = out.replace(mark, "")
            notes.append(f"「{mark}」を外した（半角のダブルクオートで囲む公式の型に合わせるため）")
    if '"' in out:
        out = out.replace('"', "")
        notes.append("半角のダブルクオートを外した（セリフの区切りに使うため、中では使えません）")
    out = out.replace("\\n", " ").strip()
    return " ".join(out.split()), notes


def build_prompt(engine: str, line: dict[str, Any], d: dict[str, Any], pd: dict[str, Any],
                 duration: int, ratio: str) -> tuple[str, str]:
    """(プロンプト, 実際に話させる台本) を返す。"""
    spoken, _notes, _dropped = _asr.apply_pronunciation_dict(line["text"], pd)
    spoken, fixes = sanitize_text(spoken)
    for fix in fixes:
        say(f"NOTE {line['id']}: {fix}")
    values = {
        "style": line.get("style", d.get("style", "")),
        "prompt_extra": line.get("prompt_extra", ""),
        "speaker": line.get("speaker", d.get("speaker", DEFAULT_SPEAKER)),
        "ambient": line.get("ambient", d.get("ambient", DEFAULT_AMBIENT)),
        "text": spoken,
        "duration": duration,
        "ratio": ratio,
    }
    template = line.get("prompt_template") or d.get("prompt_template") or (
        VEO_TEMPLATE if engine == "veo" else OMNI_TEMPLATE)
    prompt = template.format(**values)
    # 改行は Omni の区間指定で意味があるので、行ごとに空白をつぶす
    prompt = "\n".join(" ".join(part.split()) for part in prompt.splitlines() if part.strip())
    return prompt, spoken


# ---------------------------------------------------------------------------
# 参照画像
# ---------------------------------------------------------------------------
def reference_path(cfg, line: dict[str, Any], d: dict[str, Any]) -> Path | None:
    value = line.get("reference_image") or d.get("reference_image")
    if not value:
        return None
    if str(value).startswith(("http://", "https://")):
        raise SystemExit(
            f"reference_image に URL が指定されています: {value}\n"
            "  Google のモデルには画像の中身を送ります。手元のファイルのパスを書いてください"
            "（例: assets/images/reference.png）")
    path = resolve(cfg, str(value))
    if not path.exists():
        raise SystemExit(f"参照画像がありません: {path}\n"
                         "  --make-reference で作るか、lines.json の reference_image を直してください")
    return path


def make_reference(cfg, spec: dict[str, Any], out: Path, prompt_override: str | None,
                   dry_run: bool, model: str) -> int:
    d = spec.get("defaults", {})
    prompt = prompt_override or d.get("reference_prompt") or REFERENCE_TEMPLATE.format(
        style=d.get("style", ""), ratio=d.get("ratio", "9:16"))
    prompt = " ".join(prompt.split())
    print("=== 参照画像を1枚つくる（Nano Banana 2 / " + model + "） ===")
    print(f"  保存先: {rel(cfg, out)}")
    print(f"  指示  : {prompt}")
    if dry_run:
        print("\n--dry-run のため API は呼びませんでした")
        return 0
    _gates.check_project(cfg, "generate")
    _gates.check_generation_approval(cfg, ["reference"], 1)
    _gates.record_take(cfg, "reference", 1, "generate_google.py --make-reference", prompt[:80])
    info = _google.make_image(prompt, out, model=model)
    print(f"✓ {rel(cfg, out)}  {out.stat().st_size} bytes  mime={info.get('mime')}")
    print(f"  usage: {json.dumps(info.get('usage', {}), ensure_ascii=False)}")
    print('  lines.json の defaults に書いてください: "reference_image": "' + rel(cfg, out) + '"')
    return 0


# ---------------------------------------------------------------------------
# 送る内容の組み立て
# ---------------------------------------------------------------------------
def check_veo_limits(line_id: str, duration: int, resolution: str, has_ref: bool) -> int:
    """Veo の仕様に合わない指定を、送る前に止める（400 で1往復を無駄にしないため）。"""
    if has_ref and duration != 8:
        say(f"NOTE {line_id}: 参照画像を使うと尺は8秒に固定されます（{duration}秒 → 8秒）")
        duration = 8
    if duration not in VEO_DURATIONS:
        raise SystemExit(f"✗ {line_id}: Veo の尺は 4／6／8 秒のどれかです（指定 {duration}秒）")
    if resolution in ("1080p", "4k") and duration != 8:
        raise SystemExit(
            f"✗ {line_id}: {resolution} は8秒のときだけ使えます（指定 {duration}秒）。\n"
            "  4秒で作るなら 720p にしてください")
    return duration


def build_jobs(spec: dict[str, Any], ids: list[str] | None, engine: str, takes: int, start_take: int,
               cfg, pd, seconds: int | None, resolution: str | None,
               allow_no_reference: bool) -> list[dict[str, Any]]:
    d = spec.get("defaults", {})
    all_lines = spec.get("lines", [])
    if not all_lines:
        raise SystemExit("lines.json に lines がありません")
    order = {ln.get("id"): i for i, ln in enumerate(all_lines)}
    lines = all_lines
    if ids:
        known = {ln["id"] for ln in lines}
        unknown = [i for i in ids if i not in known]
        if unknown:
            raise SystemExit(f"lines.json に無い id: {', '.join(unknown)}")
        lines = [ln for ln in lines if ln["id"] in ids]
    takes_dir = resolve(cfg, cfg["takesDir"])
    jobs: list[dict[str, Any]] = []
    for ln in lines:
        ratio = str(ln.get("ratio", d.get("ratio", "9:16")))
        res = str(resolution or ln.get("resolution", d.get("resolution", "720p")))
        duration = int(seconds or ln.get("duration", d.get("duration", 8)))
        ref = reference_path(cfg, ln, d)
        is_first = order.get(ln["id"], 0) == 0
        if not is_first and ref is None:
            if not allow_no_reference:
                raise SystemExit(
                    f"✗ {ln['id']} は2セリフ目以降ですが、人物の参照画像がありません。生成しません。"
                    + NO_REFERENCE_HELP)
            say(f"WARN {ln['id']}: 参照画像なしで生成します（--allow-no-reference）。"
                "人物は前のカットと揃わない前提で見てください")
        if engine == "veo":
            duration = check_veo_limits(ln["id"], duration, res, ref is not None)
        prompt, spoken = build_prompt(engine, ln, d, pd, duration, ratio)
        negative = str(ln.get("negative", d.get("negative", DEFAULT_NEGATIVE)))
        if engine == "veo":
            instance: dict[str, Any] = {"prompt": prompt}
            if ref is not None:
                b64, mime = _google.b64_of(ref)
                instance["referenceImages"] = [
                    {"image": {"inlineData": {"mimeType": mime, "data": b64}}, "referenceType": "asset"}]
            params: dict[str, Any] = {
                "aspectRatio": ratio,
                "resolution": res,
                "durationSeconds": duration,
                "personGeneration": "allow_adult" if ref is not None else "allow_all",
            }
            if ref is None:  # 参照画像と negativePrompt は併用できない（併用時は自動で外れます）
                params["negativePrompt"] = negative
            payload: dict[str, Any] = {"instance": instance, "parameters": params}
        else:
            if ref is not None:
                b64, mime = _google.b64_of(ref)
                prompt = prompt + "\nKeep exactly the same person as <IMAGE_REF_1>."
                input_value: Any = [
                    {"type": "image", "data": b64, "mime_type": mime},
                    {"type": "text", "text": prompt},
                ]
            else:
                input_value = prompt
            payload = {
                "model": _google.OMNI_MODEL,
                "input": input_value,
                "response_modalities": ["video"],
                "response_format": {"type": "video", "aspect_ratio": ratio,
                                    "resolution": res, "delivery": "inline"},
            }
        for n in range(start_take, start_take + takes):
            jobs.append({
                "id": ln["id"], "take": n, "key": f"{ln['id']}-t{n}", "engine": engine,
                "text": ln["text"], "spoken": spoken, "prompt": prompt, "payload": payload,
                "duration": duration, "resolution": res, "ratio": ratio,
                "reference": rel(cfg, ref) if ref else "",
                "out": takes_dir / f"{ln['id']}-t{n}.mp4",
            })
    if not jobs:
        raise SystemExit("対象のセリフがありません")
    return jobs


def payload_view(value: Any) -> Any:
    """表示用のコピー。**プロンプトはそのまま見せ、画像の中身（base64）だけ伏せる。**

    送る内容を人が読めないと、承諾を取る意味がありません。長い base64 は桁数だけ出します。
    """
    if isinstance(value, dict):
        return {k: ("<画像データ base64 " + str(len(v)) + " 文字>"
                    if k in ("data", "bytesBase64Encoded") and isinstance(v, str) and len(v) > 200
                    else payload_view(v))
                for k, v in value.items()}
    if isinstance(value, list):
        return [payload_view(v) for v in value]
    return value


# ---------------------------------------------------------------------------
# 生成
# ---------------------------------------------------------------------------
def generate_one(job: dict[str, Any], cfg, ledger: Path) -> dict[str, Any]:
    out = job["out"]
    t0 = time.time()
    if job["engine"] == "veo":
        info = _google.veo_generate(job["payload"]["instance"], job["payload"]["parameters"], out, say=say)
        record = {"engine": "veo", "operation": info.get("operation"),
                  "seconds": job["duration"], "resolution": job["resolution"]}
    else:
        info = _google.omni_generate(job["payload"], out, say=say)
        record = {"engine": "omni", "usage": info.get("usage"), "resolution": job["resolution"]}
    say(f"[{job['key']}] 保存しました -> {rel(cfg, out)}  {out.stat().st_size} bytes  {time.time() - t0:.0f}s")
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"id": job["id"], "take": job["take"],
                             "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                             "text": job["spoken"], **record}, ensure_ascii=False) + "\n")
    if record.get("usage"):
        say(f"[{job['key']}] usage: {json.dumps(record['usage'], ensure_ascii=False)}"
            "（Omni はトークン課金です。金額ではなくこの数で報告してください）")
    return record


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lines", default="lines.json", help="lines.json のパス（既定 lines.json）")
    ap.add_argument("--engine", choices=("veo", "omni"), default="veo", help="使う生成エンジン（既定 veo）")
    ap.add_argument("--ids", default=None, help="対象セリフ id（カンマ区切り。無指定で全件）")
    ap.add_argument("--takes", type=int, default=1, help="1セリフあたりのテイク数（既定 1）")
    ap.add_argument("--start-take", type=int, default=1, help="テイク番号の開始値")
    ap.add_argument("--seconds", type=int, default=None, help="尺の秒数（Veo は 4／6／8）")
    ap.add_argument("--resolution", default=None, help="解像度（720p／1080p。1080p は8秒のみ）")
    ap.add_argument("--dry-run", action="store_true", help="API を呼ばず、送る内容を表示する（無料）")
    ap.add_argument("--no-check", action="store_true", help="生成のみ（音声認識での検品を省く）")
    ap.add_argument("--check-only", action="store_true", help="生成せず、既にあるテイクを検品だけする（無料）")
    ap.add_argument("--allow-no-reference", dest="allow_no_reference", default=None, metavar="理由",
                    help="2セリフ目以降を参照画像なしで生成する（人物は揃いません。理由を書いたときだけ。台帳に残る）")
    ap.add_argument("--force", default=None, metavar="理由",
                    help="テイク上限（同じ id は2回まで）を越えて生成する。理由を必ず書く（台帳に残ります）")
    ap.add_argument("--make-reference", action="store_true",
                    help="Nano Banana 2 で参照画像を1枚つくって終わる")
    ap.add_argument("--reference-out", default="assets/images/reference.png", help="参照画像の保存先")
    ap.add_argument("--reference-prompt", default=None, help="参照画像の指示（英語。省略時は lines.json から作る）")
    ap.add_argument("--image-model", default=_google.IMAGE_MODEL, help=f"参照画像のモデル（既定 {_google.IMAGE_MODEL}）")
    ap.add_argument("--report", default="out/takes-report.json")
    a = ap.parse_args()

    cfg = load_config()
    spec_path = resolve(cfg, a.lines)
    if not spec_path.exists():
        raise SystemExit(f"{a.lines} がありません（lines.json.example をコピーして作ってください）")
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    pd = _asr.load_dicts_from_config(cfg, resolve, warn=say)

    if a.make_reference:
        return make_reference(cfg, spec, resolve(cfg, a.reference_out), a.reference_prompt,
                              a.dry_run, a.image_model)

    ids = [i.strip() for i in a.ids.split(",") if i.strip()] if a.ids else None
    target_ids = [ln["id"] for ln in spec.get("lines", []) if not ids or ln["id"] in ids]
    if not a.dry_run and not a.check_only:
        # --- 機械で止まる門（1円も使わない場所で先に確かめる） ---
        _gates.check_project(cfg, "generate")
        _gates.check_generation_approval(cfg, target_ids, a.takes, spec_path)
        _gates.check_take_limit(cfg, target_ids, a.takes, a.force)

    jobs = build_jobs(spec, ids, a.engine, a.takes, a.start_take, cfg, pd,
                      a.seconds, a.resolution, a.allow_no_reference or a.check_only)

    model_name = _google.VEO_MODEL if a.engine == "veo" else _google.OMNI_MODEL
    if a.dry_run:
        print(f"=== DRY RUN（API は呼びません） engine={a.engine} model={model_name} ===")
        seen = set()
        for job in jobs:
            if job["id"] not in seen:
                seen.add(job["id"])
                changed = " → 読み方の辞書と表記の直しの後「" + job["spoken"] + "」" if job["spoken"] != job["text"] else ""
                print(f"\n--- {job['id']}: 「{job['text']}」{changed}")
                print(f"参照画像: {job['reference'] or '（なし）'}")
                print(json.dumps(payload_view(job["payload"]), ensure_ascii=False, indent=2))
            print(f"save -> {rel(cfg, job['out'])}")
        total_takes = len(jobs)
        print(f"\n{total_takes} takes / report -> {a.report}")
        print("  この内容でよければ、承諾を取ってから本番を実行してください:")
        print(f"    python3 scripts/approve.py --generation --ids {','.join(target_ids)} "
              f"--takes {a.takes} --service {a.engine}")
        return 0

    ledger = cfg["_cwd"] / "out" / "google-tasks.jsonl"
    results: dict[str, dict[str, Any]] = {}
    if not a.check_only:
        say(f"=== 生成 {len(jobs)} takes（engine={a.engine}, model={model_name}） ===")
        say("  Veo は日次の枠があります。429 で止まったら枠が戻るまで待つか、Omni で作ってください")
    for job in [] if a.check_only else jobs:
        _gates.record_take(cfg, job["id"], job["take"], f"generate_google.py --engine {a.engine}",
                           job["spoken"], a.force, no_reference_reason=a.allow_no_reference)
        try:
            results[job["key"]] = generate_one(job, cfg, ledger)
        except SystemExit as exc:  # 1本の失敗で全体を止めない
            results[job["key"]] = {"error": str(exc)[:400]}
            say(f"[{job['key']}] ERROR {exc}")
        except Exception as exc:  # noqa: BLE001
            results[job["key"]] = {"error": f"{type(exc).__name__}: {exc}"[:400]}
            say(f"[{job['key']}] ERROR {exc}")

    if a.no_check:
        return 0 if all("error" not in r for r in results.values()) else 1

    engines = _asr.build_engines(cfg, resolve, warn=say)
    say("検品エンジン: " + " / ".join(str(e) for e in engines))
    kana = _asr.build_kana_map(pd)
    ng_words = _asr.load_ng_words(resolve(cfg, cfg["ngWords"]) if cfg.get("ngWords") else None)
    rows = []
    for job in jobs:
        gen = results.get(job["key"], {})
        path = find_existing(job["out"])
        if gen.get("error") or path is None:
            rows.append({"id": job["id"], "take": job["take"], "file": rel(cfg, job["out"]),
                         "pass": False, "error": gen.get("error") or "ファイルなし"})
            continue
        rows.append(judge(job, path, cfg, engines, kana, ng_words))
    report = resolve(cfg, a.report)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print_table(rows)
    print(f"report -> {rel(cfg, report)}")
    print("※ 数字・固有名詞は機械の一致だけで合格にしないでください（scripts/ear_check.py で耳の確認）")
    return 0 if rows and all(r.get("pass") for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
