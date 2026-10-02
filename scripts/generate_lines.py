#!/usr/bin/env python3
"""汎用テイク生成: lines.json の「1セリフ＝1テイク」を Seedance で生成し、ASR で検品する。

使い方（案件フォルダのルートで。.env に ARK_API_KEY が必要。--dry-run は API を呼ばない）:
  python3 scripts/generate_lines.py --lines lines.json --ids s1,s2 --takes 2 --parallel 2 [--dry-run]
  python3 scripts/generate_lines.py --lines lines.json --check-only     # 生成せず既存テイクを検品だけ

lines.json の例:
{
  "defaults": {"model": null, "resolution": "720p", "ratio": "9:16", "duration": 5, "generate_audio": true,
               "reference_image": "assets/images/presenter.png", "reference_video": null, "reference_audio": null,
               "source_task_id": null,
               "language": "Japanese",
               "style": "落ち着いた30代女性が正面を向き、自然な表情で話す。背景は明るいオフィス"},
  "lines": [
    {"id": "s1", "text": "毎日の記録、手書きのままですか。", "duration": 5},
    {"id": "s2", "text": "アプリなら数分で終わります。", "prompt_extra": "少し驚いた表情"}
  ]
}
- model が null なら .env の SEEDANCE_MODEL（無ければ scripts/lib/seedance_api.py の既定）
- reference_image は画像ファイルのパスまたは URL。reference_video / reference_audio は URL 推奨
  （AI 映像制作ツールの新しいモデルは、音声・動画をファイルの中身のまま送ると必ず拒否する。公開URLで渡す）
- source_task_id は、採用済み source（無音の同一人物クリップ）のタスクID。その動画URLを
  reference_video として自動で使う（同じ人物を保つための標準の渡し方）
- 各セリフは prompt_extra（表情・仕草）、duration、seed、style、prompt_template を個別に上書きできる
- 台本には読み方の辞書（config の pronunciationDict と pronunciationDictExtra）が自動で適用される
  （仮名置換＋発音ガイド最大2件）

機械で止まる決まり（文章ではなく、このスクリプトが止めます）:
  1. 人物の参照   2セリフ目以降は、参照（reference_video の公開URL か source_task_id）が無いと生成しない。
                  参照の作り方は scripts/rehost.py（--allow-no-reference を明示したときだけ例外）
  2. テイク上限   同じ id への生成は2回まで。3回目は out/takes-ledger.json を見て拒否する
                  （--force "理由" で例外。理由は台帳に残る）
  3. 生成の承諾   out/generation-approval.json（何を・何本・どのサービスで作るかを伝えて y/N を取った記録）が
                  無ければ生成しない
                  （記録の作り方: python3 scripts/approve.py --generation --ids s1,s2 --takes 1 --service seedance）

処理:
  各テイクを <takesDir>/<id>-t<n>.mp4 に保存 → ffmpeg で 16kHz wav 抽出 → 音声認識（ai-ad.config.json の
  asrEngine / asrEngine2。既定は whisper 2本。gemini も選べる）→ 正規化（読み方の辞書の reading / asr_variants）→
  期待テキストとの編集距離率・余剰文字数・NGワード・尺（発話が末尾で切れていないか）で pass/fail →
  out/takes-report.json に {id, take, file, asr, asr2, err_rate, ng, pass, ...} を記録し、標準出力に表で表示。
  生成したタスクIDは out/takes-tasks.jsonl に残す（cost_ledger.py で集計できる）。
"""
from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "lib"))
import _asr  # noqa: E402
import _gates  # noqa: E402
import seedance_api  # noqa: E402
from _config import load_config, rel, resolve  # noqa: E402

DEFAULT_TEMPLATE = (
    "{style} {prompt_extra} The speaker says naturally in {language}: {{{text}}} "
    "{guide_part}{clauses} {negative}"
)
DEFAULT_NEGATIVE = "No subtitles, no on-screen text, no BGM."
REF_ROLES = {"reference_image": "image", "reference_video": "video", "reference_audio": "audio"}
DRY_RUN = False  # --dry-run のときは参照ファイルが無くても止めない（設定確認が目的のため）
_print_lock = threading.Lock()


def say(msg: str) -> None:
    with _print_lock:
        print(msg, flush=True)


def file_to_data_url(path: Path, fallback_mime: str) -> str:
    mime = mimetypes.guess_type(str(path))[0] or fallback_mime
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def media_item(role: str, value: str, cfg) -> dict[str, Any]:
    kind = REF_ROLES[role]
    if value.startswith(("http://", "https://", "data:")):
        url = value
    else:
        p = resolve(cfg, value)
        if not p.exists():
            if DRY_RUN:
                say(f"WARN {role}: ファイルがありません（dry-run なので続行）: {p}")
                return {"type": f"{kind}_url", f"{kind}_url": {"url": f"file-missing://{p}"}, "role": role}
            raise SystemExit(f"{role} のファイルがありません: {p}")
        if kind != "image":
            say(f"WARN {role}: ローカルファイルの中身をそのまま送ろうとしています。"
                "新しいモデルはこの渡し方を必ず拒否します（web url が要る）。公開URLを指定してください")
        url = file_to_data_url(p, {"image": "image/png", "video": "video/mp4", "audio": "audio/mpeg"}[kind])
    return {"type": f"{kind}_url", f"{kind}_url": {"url": url}, "role": role}


def build_prompt(line: dict[str, Any], d: dict[str, Any], pd: dict[str, Any]) -> tuple[str, str, list[str]]:
    """(プロンプト, 読み方の辞書の適用後の台本, 件数超過で落としたガイド) を返す。"""
    spoken, notes, dropped = _asr.apply_pronunciation_dict(line["text"], pd)
    guide = " ".join(notes + [g for g in [line.get("guide", "")] if g])
    template = line.get("prompt_template") or d.get("prompt_template") or DEFAULT_TEMPLATE
    prompt = template.format(
        style=line.get("style", d.get("style", "")),
        prompt_extra=line.get("prompt_extra", ""),
        language=line.get("language", d.get("language", "Japanese")),
        text=spoken,
        guide_part=f"Pronunciation guide for audio only: {guide} " if guide else "",
        clauses=" ".join(pd.get("standard_clauses", [])),
        negative=line.get("negative", d.get("negative", DEFAULT_NEGATIVE)),
    )
    return " ".join(prompt.split()), spoken, dropped


NO_REFERENCE_HELP = """
  同じ人物を保つには、2セリフ目以降に「1カット目の参照」を渡します。順番は決まっています:

    1. 1カット目（先頭のセリフ）を1テイクだけ生成し、人物を見て採用を決める
    2. 採用した**無加工の原本**を一時的な公開URLにする:
         python3 scripts/rehost.py assets/videos/takes/s1-t1.mp4
       （加工した原本は拒否されます。音を消した版・作り直した版も駄目です）
    3. その URL を参照にして、無音の source クリップを1本作る（同一人物の土台）
    4. source のタスクID（または動画URL）を lines.json に書く:
         "defaults": {"source_task_id": "cgt-..."}      ← これが2セリフ目以降の参照になる
       URL を直接渡す場合は "reference_video": "https://..."
    5. 残りのセリフを生成する

  同じ style と同じ seed だけでは人物は揃いません（別人になった実測があります）。
  参照なしで進める必要がある場合だけ --allow-no-reference を付けてください（人物は揃いません）。
"""


def resolve_reference(ln: dict[str, Any], d: dict[str, Any], dry_run: bool) -> tuple[str, str]:
    """このセリフに効く人物の参照を (種類, URL) で返す。無ければ ("", "")。

    reference_video（公開URL）がそのまま指定されていればそれを使う。source_task_id が
    指定されていれば、そのタスクの動画URLを取り出して reference_video として使う。
    """
    ref_video = ln.get("reference_video") or d.get("reference_video")
    if ref_video:
        return "reference_video", str(ref_video)
    task_id = ln.get("source_task_id") or d.get("source_task_id")
    if not task_id:
        return "", ""
    if dry_run:
        return "source_task_id", f"<source {task_id} の video_url を実行時に取得>"
    res = seedance_api.get_task(None, str(task_id))
    status = str(res.get("status", "")).lower()
    if status != "succeeded":
        raise SystemExit(
            f"source のタスクが使えません: {task_id}（status={status}）\n"
            "  採用済みの source を指定してください（作り方は guides/production.md「同じ人物を保つ」）")
    url = seedance_api.video_url_from_response(res)
    if not url:
        raise SystemExit(f"source のタスクに動画URLがありません: {task_id}")
    return "source_task_id", url


def build_jobs(spec: dict[str, Any], ids: list[str] | None, takes: int, start_take: int, cfg, pd,
               allow_no_reference: bool = False, dry_run: bool = False) -> list[dict[str, Any]]:
    d = spec.get("defaults", {})
    all_lines = spec.get("lines", [])
    order = {ln.get("id"): i for i, ln in enumerate(all_lines)}
    lines = all_lines
    if ids:
        known = {ln["id"] for ln in lines}
        unknown = [i for i in ids if i not in known]
        if unknown:
            raise SystemExit(f"lines.json に無い id: {', '.join(unknown)}")
        lines = [ln for ln in lines if ln["id"] in ids]
    if not lines:
        raise SystemExit("対象のセリフがありません")
    takes_dir = resolve(cfg, cfg["takesDir"])
    jobs = []
    for ln in lines:
        prompt, spoken, dropped = build_prompt(ln, d, pd)
        if dropped:
            say(f"NOTE {ln['id']}: 発音ガイドは最大2件のため次を省略: {' / '.join(g[:40] for g in dropped)}")
        ref_kind, ref_url = resolve_reference(ln, d, dry_run)
        is_first = order.get(ln["id"], 0) == 0
        if not is_first and not ref_url:
            if not allow_no_reference:
                raise SystemExit(
                    f"✗ {ln['id']} は2セリフ目以降ですが、人物の参照がありません。生成しません。"
                    + NO_REFERENCE_HELP)
            say(f"WARN {ln['id']}: 参照なしで生成します（--allow-no-reference）。"
                "人物は前のカットと揃わない前提で見てください")
        elif ref_url:
            say(f"[{ln['id']}] 人物の参照: {ref_kind} = {ref_url[:70]}")
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        for role in REF_ROLES:
            value = ref_url if (role == "reference_video" and ref_url) else ln.get(role, d.get(role))
            if value:
                if role == "reference_video" and str(value).startswith("<source "):
                    content.append({"type": "video_url", "video_url": {"url": str(value)}, "role": role})
                    continue
                content.append(media_item(role, value, cfg))
        payload: dict[str, Any] = {
            "model": ln.get("model") or d.get("model") or seedance_api.default_model(),
            "content": content,
            "resolution": ln.get("resolution", d.get("resolution", "720p")),
            "ratio": ln.get("ratio", d.get("ratio", "9:16")),
            "duration": int(ln.get("duration", d.get("duration", 5))),
            "generate_audio": bool(ln.get("generate_audio", d.get("generate_audio", True))),
            "watermark": bool(ln.get("watermark", d.get("watermark", False))),
        }
        for key in ("seed", "camera_fixed", "service_tier", "return_last_frame"):
            if key in ln or key in d:
                payload[key] = ln.get(key, d.get(key))
        warn_unsupported(ln["id"], payload)
        for n in range(start_take, start_take + takes):
            jobs.append({
                "id": ln["id"], "take": n, "key": f"{ln['id']}-t{n}",
                "text": ln["text"], "spoken": spoken, "payload": payload,
                "reference": ref_url, "out": takes_dir / f"{ln['id']}-t{n}.mp4",
            })
    return jobs


# モデルによって受け付けないパラメータがある。送ってから HTTP 400 で落ちると1往復を無駄にするので、
# 組み立てた時点（--dry-run でも）で知らせる。参照画像・参照動画を使わない生成では camera_fixed が
# 通らないモデルがあり、その場合は style の英文に locked-off camera と書いて代用する。
def warn_unsupported(line_id: str, payload: dict[str, Any]) -> None:
    has_ref = any(c.get("type") in ("image_url", "video_url") for c in payload.get("content", []))
    if payload.get("camera_fixed") and not has_ref:
        say(f"WARN {line_id}: 参照画像・参照動画なしの生成で camera_fixed を指定しています。"
            "受け付けないモデルがあります（HTTP 400）。"
            "固定カメラにしたいときは style に locked-off camera, no camera movement と書いてください")


def payload_view(payload: dict[str, Any]) -> dict[str, Any]:
    view = json.loads(json.dumps(payload, ensure_ascii=False))
    for c in view.get("content", []):
        for k in ("image_url", "video_url", "audio_url"):
            if k in c and str(c[k].get("url", "")).startswith("data:"):
                url = c[k]["url"]
                c[k]["url"] = url.split(",", 1)[0] + f",...(base64 {len(url)} chars)"
    return view


def generate_one(job: dict[str, Any], ns: argparse.Namespace, poll: float, ledger: Path) -> dict[str, Any]:
    res = seedance_api.create_task(ns, job["payload"])
    tid = seedance_api.task_id_from_response(res)
    say(f"[{job['key']}] created task_id={tid}")
    with _print_lock:
        ledger.parent.mkdir(parents=True, exist_ok=True)
        with ledger.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"id": job["id"], "take": job["take"], "task_id": tid, "model": job["payload"]["model"],
                                 "created_at": time.strftime("%Y-%m-%d %H:%M:%S"), "text": job["spoken"]},
                                ensure_ascii=False) + "\n")
    result = seedance_api.wait_for_task(ns, tid, poll)
    status = str(result.get("status", "")).lower()
    if status != "succeeded":
        return {"task_id": tid, "error": f"status={status}: " + json.dumps(seedance_api.sanitize_for_storage(result), ensure_ascii=False)[:300]}
    url = seedance_api.video_url_from_response(result)
    job["out"].parent.mkdir(parents=True, exist_ok=True)
    seedance_api.download_url(url, job["out"])
    say(f"[{job['key']}] downloaded -> {job['out']}")
    return {"task_id": tid}


def find_existing(out: Path) -> Path | None:
    """<id>-t<n>.mp4 が無ければ同名の m4a/wav/mov も探す（ローカル音声での検品用）。"""
    for p in [out] + [out.with_suffix(ext) for ext in (".m4a", ".wav", ".mov", ".mp3")]:
        if p.exists():
            return p
    return None


def judge(job: dict[str, Any], path: Path, cfg, engines: list, kana, ng_words) -> dict[str, Any]:
    exp = _asr.norm(job["spoken"], kana)
    duration, s_end = _asr.speech_span(path)
    tail_ok = (duration - s_end) >= float(cfg["asrTailMinSec"])
    rec: dict[str, Any] = {
        "id": job["id"], "take": job["take"], "file": rel(cfg, path), "expected": job["spoken"],
        "asr": None, "asr2": None, "err_rate": None, "err_rate2": None, "extra_chars": None, "ng": [],
        "duration": round(duration, 2), "speech_end": round(s_end, 2), "tail_ok": tail_ok,
        "pass": False, "reasons": [],
    }
    reasons: list[str] = []
    with tempfile.TemporaryDirectory() as td:
        wav = _asr.to_wav16k(path, Path(td) / "a.wav")
        for i, engine in enumerate(engines):
            text = engine.transcribe(wav, cfg["language"])
            n = _asr.norm(text, kana)
            err = round(_asr.window_err(exp, n), 3)
            extra = len(n) - len(exp)
            hits = _asr.ng_hits(text, n, ng_words)
            tag = "" if i == 0 else "2"
            rec["asr" + tag] = text
            rec["err_rate" + tag] = err
            if i == 0:
                rec["extra_chars"] = extra
            rec["ng"] = sorted(set(rec["ng"]) | set(hits))
            if err > float(cfg["asrErrRateMax"]):
                reasons.append(f"engine{i + 1}: err {err:.2f} > {cfg['asrErrRateMax']}")
            if extra > int(cfg["asrExtraCharsMax"]):
                reasons.append(f"engine{i + 1}: 余剰{extra}文字")
            if hits:
                reasons.append(f"engine{i + 1}: NG {','.join(hits)}")
    if not tail_ok:
        reasons.append(f"末尾切れの疑い（発話終了 {s_end:.2f}s / 尺 {duration:.2f}s）")
    rec["reasons"] = reasons
    rec["pass"] = not reasons
    return rec


def print_table(rows: list[dict[str, Any]]) -> None:
    print()
    print(f"{'id':<8}{'take':<5}{'result':<7}{'err':<6}{'err2':<6}{'extra':<6}{'dur':<12}{'ng':<10}asr")
    for r in rows:
        if r.get("error"):
            print(f"{r['id']:<8}{r['take']:<5}{'ERROR':<7}{'':<6}{'':<6}{'':<6}{'':<12}{'':<10}{r['error'][:60]}")
            continue
        e1 = "-" if r["err_rate"] is None else f"{r['err_rate']:.2f}"
        e2 = "-" if r["err_rate2"] is None else f"{r['err_rate2']:.2f}"
        dur = f"{r['speech_end']:.1f}/{r['duration']:.1f}s" + ("" if r["tail_ok"] else "!")
        print(f"{r['id']:<8}{r['take']:<5}{('PASS' if r['pass'] else 'FAIL'):<7}{e1:<6}{e2:<6}"
              f"{str(r['extra_chars']):<6}{dur:<12}{','.join(r['ng'])[:9]:<10}{(r['asr'] or '')[:40]}")
    passed = sum(1 for r in rows if r.get("pass"))
    print(f"\n{passed}/{len(rows)} PASS")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lines", required=True, help="lines.json のパス")
    ap.add_argument("--ids", default=None, help="対象セリフ id（カンマ区切り。無指定で全件）")
    ap.add_argument("--takes", type=int, default=1, help="1セリフあたりのテイク数")
    ap.add_argument("--start-take", type=int, default=1, help="テイク番号の開始値（2回目のラウンドなどに）")
    ap.add_argument("--parallel", type=int, default=2, help="同時生成数")
    ap.add_argument("--poll", type=float, default=15.0, help="タスク状態のポーリング間隔（秒）")
    ap.add_argument("--dry-run", action="store_true", help="API を呼ばず、生成リクエストの JSON と保存先を表示して終了")
    ap.add_argument("--check-only", action="store_true", help="生成せず、既存のテイクを検品だけする")
    ap.add_argument("--skip-existing", action="store_true", help="既にあるテイクは生成せず検品だけする")
    ap.add_argument("--no-check", action="store_true", help="生成のみ（ASR 検品を省く）")
    ap.add_argument("--allow-no-reference", dest="allow_no_reference", default=None, metavar="理由",
                    help="2セリフ目以降を、人物の参照なしで生成する（人物は揃いません。理由を書いたときだけ。台帳に残る）")
    ap.add_argument("--force", default=None, metavar="理由",
                    help="テイク上限（同じ id は2回まで）を越えて生成する。理由を必ず書く（台帳に残ります）")
    ap.add_argument("--report", default="out/takes-report.json")
    a = ap.parse_args()

    global DRY_RUN
    DRY_RUN = a.dry_run
    seedance_api.load_project_env()
    cfg = load_config()
    spec = json.loads(resolve(cfg, a.lines).read_text(encoding="utf-8"))
    pd = _asr.load_dicts_from_config(cfg, resolve, warn=say)
    ids = [i.strip() for i in a.ids.split(",") if i.strip()] if a.ids else None
    target_ids = [ln["id"] for ln in spec.get("lines", []) if not ids or ln["id"] in ids]
    if not a.dry_run and not a.check_only:
        # --- 機械で止まる門（1円も使わない場所で先に確かめる。参照の解決も API を1回叩くため、その前に置く） ---
        _gates.check_project(cfg, "generate")
        _gates.check_generation_approval(cfg, target_ids, a.takes, resolve(cfg, a.lines))
        _gates.check_take_limit(cfg, target_ids, a.takes, a.force)
    jobs = build_jobs(spec, ids, a.takes, a.start_take, cfg, pd,
                      allow_no_reference=a.allow_no_reference, dry_run=a.dry_run)

    if a.dry_run:
        print("=== DRY RUN（API は呼びません） ===")
        seen = set()
        for job in jobs:
            if job["id"] not in seen:
                seen.add(job["id"])
                print(f"\n--- {job['id']}: 「{job['text']}」" + (f" → 読み方の辞書の適用後「{job['spoken']}」" if job["spoken"] != job["text"] else ""))
                print(json.dumps(payload_view(job["payload"]), ensure_ascii=False, indent=2))
            print(f"save -> {rel(cfg, job['out'])}")
        print(f"\n{len(jobs)} takes / parallel={a.parallel} / report -> {a.report}")
        return 0

    ns = argparse.Namespace()
    ledger = cfg["_cwd"] / "out" / "takes-tasks.jsonl"
    results: dict[str, dict[str, Any]] = {}
    if not a.check_only:
        todo = [j for j in jobs if not (a.skip_existing and j["out"].exists())]
        for j in todo:
            _gates.record_take(cfg, j["id"], j["take"], "generate_lines.py", j["spoken"], a.force,
                               no_reference_reason=a.allow_no_reference)
        say(f"=== 生成 {len(todo)} takes（parallel={a.parallel}, model={jobs[0]['payload']['model']}） ===")
        with ThreadPoolExecutor(max_workers=max(1, a.parallel)) as ex:
            futs = {ex.submit(generate_one, j, ns, a.poll, ledger): j for j in todo}
            for fut in as_completed(futs):
                j = futs[fut]
                try:
                    results[j["key"]] = fut.result()
                except Exception as exc:  # 1本の失敗で全体を止めない
                    results[j["key"]] = {"error": f"{type(exc).__name__}: {exc}"[:300]}
                    say(f"[{j['key']}] ERROR {exc}")

    if a.no_check:
        return 0

    engines = _asr.build_engines(cfg, resolve, warn=say)
    say("検品エンジン: " + " / ".join(str(e) for e in engines))
    kana = _asr.build_kana_map(pd)
    ng_words = _asr.load_ng_words(resolve(cfg, cfg["ngWords"]) if cfg.get("ngWords") else None)
    rows = []
    for job in jobs:
        gen = results.get(job["key"], {})
        path = find_existing(job["out"])
        if gen.get("error") or path is None:
            rows.append({"id": job["id"], "take": job["take"], "file": rel(cfg, job["out"]), "pass": False,
                         "error": gen.get("error") or "ファイルなし", "task_id": gen.get("task_id")})
            continue
        rec = judge(job, path, cfg, engines, kana, ng_words)
        rec["task_id"] = gen.get("task_id")
        rows.append(rec)
    report = resolve(cfg, a.report)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print_table(rows)
    print(f"report -> {rel(cfg, report)}")
    return 0 if rows and all(r.get("pass") for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
