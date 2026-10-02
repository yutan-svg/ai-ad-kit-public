#!/usr/bin/env python3
"""音声先行のトーキングヘッド生成: 先に用意した音声（TTS で作った mp3）を参照音声として渡し、
カメラ固定・動きを抑えた「人物が話すだけ」の縦型クリップを1本つくる。

人物画像は渡しません（実写の顔写真は privacy filter で拒否されることがあるため）。
人物と背景は日本語ではなく**英語の説明文**でプロンプトに渡します。

使い方（案件フォルダのルートで。`.env` に ARK_API_KEY が必要。`--dry-run` は API を呼ばない＝無料）:
  python3 scripts/generate_talking_head.py \
      --audio-file assets/audio/narration.mp3 \
      --person "A Japanese woman in her 30s, neat shoulder-length black hair, wearing a light gray jacket" \
      --background "a bright modern office with a window and green plants behind her" \
      --dry-run

  # 本番（課金されます）。音声は「公開URL」で渡す（作り方は guides/production.md「音声先行のトーキングヘッド」）
  python3 scripts/generate_talking_head.py --audio-url https://example.com/narration.mp3 \
      --audio-file assets/audio/narration.mp3 --person "..." --background "..." --take t1

引数の要点:
- 本番は `--audio-url`（公開URL）が必須。AI 映像制作ツールは音声をファイルの中身のまま受け取らないため、手元のファイルを直接は送れない
- `--audio-file` は手元の mp3 の長さ（2〜30秒）を機械で確かめるための指定。`--dry-run` ではこれだけで足りる。本番では `--audio-url` と併用できる（同じファイルを公開したURLを渡す）
- `--person` 人物の説明（英語）、`--background` 背景の説明（英語）、`--extra` 追加の指示（**英語の短い1文だけ**）
- `--script` 参照音声で読み上げている台本（日本語）。渡すと読み方の辞書（ai-ad.config.json の pronunciationDict と pronunciationDictExtra）の
  ガイドを最大2件、プロンプトに自動で添える。固有名詞・造語が一般語に差し替わるのを防ぐ
- **発音の指示を `--extra` に書かないこと**。日本語や長文を `--extra` に入れると発話全体が破綻する実測がある。
  発音は必ず読み方の辞書＋`--script` 経由で渡す
- `--duration -1`（既定）は尺を Seedance に任せる指定。出力は最長30秒
- プロンプトの型は `scripts/prompts/talking_head.txt`。`--prompt-file` で差し替えられる

制約（AI 映像制作ツール側の仕様）:
- 参照音声は1本 2〜30秒。出力の動画は最長30秒
- 参照音声は「声色＋読み上げ内容の参照」で、出力音声は新規生成されます（元の波形そのままにはならず、尺も少し変わります）
- 参照音声なしで台本をプロンプトに書くだけだと、漢字の読み違いが起きる実測があります（参照音声は必須）
- 参照音声が正しく読めていても、出力では固有名詞・造語が一般語に差し替わることがあります
  （参照音声では造語が正しく読めていても、出力では一般的な語に置き換わる実測がある）。`--script` を渡して
  読み方の辞書のガイドを添え、出力は必ず `scripts/asr_gate.py` で1語ずつ確かめてください

機械で止まる決まり（文章ではなく、このスクリプトが止めます）:
  1. テイク上限   同じ `--id` への生成は2回まで。3回目は out/takes-ledger.json を見て拒否する
                  （`--force "理由"` で例外。理由は台帳に残る）
  2. 生成の承諾   out/generation-approval.json（何を・何本・どのサービスで作るかを伝えて y/N を取った記録）が
                  無ければ生成しない
                  （記録の作り方: python3 scripts/approve.py --generation --ids talking-head --takes 1 --service seedance）

考え方・手順・つまずいたときの対処は `guides/production.md`「音声先行のトーキングヘッド」にあります。
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "lib"))
import seedance_api  # noqa: E402
import _asr  # noqa: E402
import _gates  # noqa: E402
from _config import load_config, rel, resolve  # noqa: E402

DEFAULT_PROMPT_FILE = HERE / "prompts" / "talking_head.txt"
AUDIO_MIN_SEC = 2.0
AUDIO_MAX_SEC = 30.0

# --extra の安全弁。日本語を入れる／長く書くと発話が破綻する実測があるため、
# 送る前に警告して確認を求める（--yes で抑止）。
EXTRA_MAX_CHARS = 200
NON_ASCII_RE = re.compile(r"[^\x00-\x7f]")


def say(msg: str) -> None:
    print(msg, flush=True)


def load_template(path: Path) -> str:
    """プロンプトの型を読む（「#」で始まる行はコメントとして読み飛ばす）。"""
    if not path.exists():
        raise SystemExit(f"プロンプトの型がありません: {path}")
    lines = [l for l in path.read_text(encoding="utf-8").splitlines() if not l.lstrip().startswith("#")]
    text = " ".join(" ".join(lines).split())
    if not text:
        raise SystemExit(f"プロンプトの型が空です: {path}")
    return text


def build_prompt(template: str, person: str, background: str, extra: str, guide: str = "") -> str:
    """{PERSON} {BACKGROUND} {EXTRA} {GUIDE} を置き換えて1行のプロンプトにする。

    {GUIDE} が型に無い場合（--prompt-file で自前の型を使うとき）は末尾に足す。
    """
    text = template.replace("{PERSON}", person.strip()).replace("{BACKGROUND}", background.strip())
    text = text.replace("{EXTRA}", extra.strip())
    guide_part = f"Pronunciation guide for audio only: {guide.strip()}" if guide.strip() else ""
    if "{GUIDE}" in text:
        text = text.replace("{GUIDE}", guide_part)
    elif guide_part:
        text = f"{text} {guide_part}"
    return " ".join(text.split())


def pronunciation_guide(cfg: dict[str, Any], script: str) -> str:
    """台本に含まれる語の発音ガイド（英語・最大2件）を読み方の辞書から取り出す。

    generate_lines.py と同じ `_asr.apply_pronunciation_dict()` を使う。トーキングヘッドでは
    台本そのものは送らない（読み上げ内容は参照音声が決める）ので、置換後の台本は使わずガイドだけを使う。
    """
    if not script.strip():
        return ""
    pd = _asr.load_dicts_from_config(cfg, resolve, warn=say)
    _spoken, notes, dropped = _asr.apply_pronunciation_dict(script, pd)
    if notes:
        say(f"発音ガイド {len(notes)} 件を添えます: " + " / ".join(n[:60] for n in notes))
    else:
        say("NOTE --script に読み方の辞書の登録語が見つかりませんでした（ガイドなしで送ります）")
    if dropped:
        say(f"NOTE ガイドは最大2件までです。{len(dropped)} 件は添えません（台本を分けて1本ずつ生成してください）")
    return " ".join(notes)


def check_extra(extra: str, assume_yes: bool) -> None:
    """--extra に日本語や長文が入っていたら警告して確認を求める。"""
    problems: list[str] = []
    if NON_ASCII_RE.search(extra):
        found = "".join(dict.fromkeys(NON_ASCII_RE.findall(extra)))[:20]
        problems.append(f"日本語（非ASCII）が含まれています: 「{found}」")
    if len(extra) > EXTRA_MAX_CHARS:
        problems.append(f"長すぎます: {len(extra)}文字（目安 {EXTRA_MAX_CHARS}文字まで）")
    if not problems:
        return
    say("")
    say("⚠ --extra の内容に注意してください（発話が破綻する実測があります）")
    for pb in problems:
        say(f"  - {pb}")
    say("  --extra は「英語の短い1文」だけにしてください（例: She smiles slightly at the end）。")
    say("  発音の指示は --extra ではなく、読み方の辞書 ＋ --script で渡します（--help 参照）。")
    if assume_yes:
        say("  --yes が指定されているのでこのまま続行します")
        return
    if not sys.stdin.isatty():
        raise SystemExit("中止しました。--extra を直すか、承知のうえで進めるなら --yes を付けて再実行してください")
    answer = input("  このまま送りますか？ [y/N]: ").strip().lower()
    if answer not in ("y", "yes"):
        raise SystemExit("中止しました（--extra を直して再実行してください）")


def audio_seconds(path: Path) -> float:
    """音声の長さを ffprobe で測る（秒）。"""
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout.strip()
    except FileNotFoundError:
        raise SystemExit(
            "ffprobe が見つかりません（音声の長さを測れません）。\n"
            "  macOS なら brew install ffmpeg で入ります"
        )
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"音声ファイルを読めません: {path}\n  {exc.stderr.strip()[:300]}")
    try:
        return float(out.splitlines()[0])
    except (ValueError, IndexError):
        raise SystemExit(f"音声の長さを判定できません: {path}（ffprobe の出力: {out[:100]}）")


def check_audio_file(cfg: dict[str, Any], value: str) -> tuple[Path, float]:
    """参照音声の実在と長さ（2〜30秒）を確かめる。範囲外なら理由を出して止める。"""
    path = resolve(cfg, value)
    if not path.exists():
        raise SystemExit(f"音声ファイルがありません: {path}")
    seconds = audio_seconds(path)
    if seconds < AUDIO_MIN_SEC:
        raise SystemExit(
            f"参照音声が短すぎます: {seconds:.2f}秒（{AUDIO_MIN_SEC:.0f}秒以上が必要）。\n"
            "  台本を足すか、前後の無音を残して2秒以上にしてください"
        )
    if seconds > AUDIO_MAX_SEC:
        raise SystemExit(
            f"参照音声が長すぎます: {seconds:.2f}秒（上限 {AUDIO_MAX_SEC:.0f}秒）。\n"
            "  台本を削るか、文の切れ目で音声を分けて1本ずつ生成してください"
        )
    return path, seconds


def payload_view(payload: dict[str, Any], audio_note: str | None) -> dict[str, Any]:
    """表示用のコピー。base64 の本体は出さず、音声の長さとファイル名だけを見せる。"""
    view = json.loads(json.dumps(payload, ensure_ascii=False))
    for c in view.get("content", []):
        url = str(c.get("audio_url", {}).get("url", "")) if "audio_url" in c else ""
        if url.startswith("data:") and audio_note:
            c["audio_url"]["url"] = url.split(",", 1)[0] + f",...(base64 / {audio_note})"
    return view


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--audio-file", dest="audio_file", default=None,
                    help="手元の参照音声（長さ 2〜30秒 の確認に使う。本番で送るのは --audio-url）")
    ap.add_argument("--audio-url", dest="audio_url", default=None,
                    help="参照音声の公開URL（本番で必須。2〜30秒。ファイルの中身のままでは受け取ってもらえない）")
    ap.add_argument("--person", required=True, help="人物の説明（英語）。例: A Japanese man in his 40s, white shirt")
    ap.add_argument("--background", required=True, help="背景の説明（英語）。例: a bright modern office")
    ap.add_argument("--extra", default="",
                    help="追加の指示（**英語の短い1文だけ**）。例: He smiles slightly at the end。"
                         "日本語や長文を入れると発話が破綻します。発音の指示はここではなく --script ＋読み方の辞書で渡してください")
    ap.add_argument("--script", default="",
                    help="参照音声で読み上げている台本（日本語）。読み方の辞書（pronunciationDict と pronunciationDictExtra）のガイドを最大2件、"
                         "プロンプトに自動で添えます。固有名詞・造語が一般語に差し替わるのを防ぎます")
    ap.add_argument("--take", default="t1", help="テイク名（出力ファイル名に付く。既定 t1）")
    ap.add_argument("--id", dest="line_id", default="talking-head",
                    help="台帳につける名前（既定 talking-head）。同じ名前への生成は2回まで")
    ap.add_argument("--force", default=None, metavar="理由",
                    help="テイク上限を越えて生成する。理由を必ず書く（台帳に残ります）")
    ap.add_argument("--duration", type=int, default=-1, help="尺（秒）。-1 で Seedance に任せる（既定）。出力は最長30秒")
    ap.add_argument("--resolution", default="720p")
    ap.add_argument("--ratio", default="9:16")
    ap.add_argument("--model", default=None, help="未指定なら .env の SEEDANCE_MODEL")
    ap.add_argument("--out", default="assets/videos", help="保存先ディレクトリ（既定 assets/videos）")
    ap.add_argument("--prompt-file", dest="prompt_file", default=None,
                    help=f"プロンプトの型（既定 {DEFAULT_PROMPT_FILE.name}）")
    ap.add_argument("--poll", type=float, default=15.0, help="タスク状態のポーリング間隔（秒）")
    ap.add_argument("--dry-run", dest="dry_run", action="store_true",
                    help="API を呼ばず、送るリクエストの中身と保存先を表示して終了（無料）")
    ap.add_argument("--yes", "-y", dest="assume_yes", action="store_true",
                    help="--extra の警告が出ても確認を求めずに続行する")
    a = ap.parse_args()

    seedance_api.load_project_env()
    cfg = load_config()

    check_extra(a.extra, a.assume_yes)
    guide = pronunciation_guide(cfg, a.script)
    if not a.script.strip():
        say("NOTE --script（参照音声の台本）を渡すと、読み方の辞書のガイドを自動で添えます（固有名詞が別の語に差し替わるのを防ぐため）")

    template = load_template(Path(a.prompt_file) if a.prompt_file else DEFAULT_PROMPT_FILE)
    prompt = build_prompt(template, a.person, a.background, a.extra, guide)

    audio_note: str | None = None
    if not a.audio_file and not a.audio_url:
        ap.error("--audio-file（長さの確認）か --audio-url（本番で送る公開URL）の少なくとも一方を指定してください")
    if a.audio_file:
        path, seconds = check_audio_file(cfg, a.audio_file)
        audio_note = f"{path.name} / {seconds:.2f}秒"
        say(f"参照音声（手元）: {rel(cfg, path)}（{seconds:.2f}秒）")
    if a.audio_url:
        say(f"参照音声（送るURL）: {a.audio_url}")
        if not a.audio_file:
            say(f"NOTE URL だけでは長さを確認できません。{AUDIO_MIN_SEC:.0f}〜{AUDIO_MAX_SEC:.0f}秒に収まっているか自分で確かめてください")
    elif not a.dry_run:
        say("ERROR 本番では --audio-url（公開URL）が必要です。音声はファイルの中身のままでは送れません。")
        say("      自分で公開する場合（どちらか）:")
        say("        A) Google ドライブに置いて共有リンクを直リンクに変える")
        say("           https://drive.google.com/uc?export=download&id=<共有リンクのファイルID>")
        say("        B) 手元から一時的に公開する:")
        say("           python3 -m http.server 8000 &  /  cloudflared tunnel --url http://localhost:8000")
        say("      音声を他の人に用意してもらう場合は、配信できる状態になったか先に確かめます:")
        say("        curl -sI '<URL>' | head -1   # 200 が返ってから生成を始める")
        say("      手順の全体: guides/production.md「音声先行のトーキングヘッド」")
        return 1
    else:
        say("NOTE 本番では、この音声を公開URLに置いて --audio-url で渡します"
            "（作り方: guides/production.md「音声先行のトーキングヘッド」）")

    ns = argparse.Namespace(
        prompt=prompt, image_file=[], image_url=[], image_role=None, video_url=[], video_file=[],
        audio_url=[a.audio_url] if a.audio_url else [], audio_file=[],
        payload=None, content=None, model=a.model, resolution=a.resolution, ratio=a.ratio,
        duration=a.duration, generate_audio=True, watermark=False,
    )
    payload = seedance_api.build_payload(ns)
    for c in payload["content"]:
        if c.get("type") == "audio_url":
            c["role"] = "reference_audio"   # ModelArk の音声参照はこの role のみ

    out = resolve(cfg, a.out) / f"talking-head-{a.take}.mp4"

    if a.dry_run:
        if not a.audio_url:
            # 本番で送る形を見せる（URL は実行時に --audio-url で渡す）
            payload["content"].append({"type": "audio_url", "audio_url": {"url": "<--audio-url で渡す公開URL>"}, "role": "reference_audio"})
        print("=== DRY RUN（API は呼びません） ===")
        print(json.dumps(payload_view(payload, audio_note), ensure_ascii=False, indent=2))
        print(f"\nsave -> {rel(cfg, out)}")
        return 0

    # --- 機械で止まる門（ここを通らないと1円も使わせない） ---
    _gates.check_project(cfg, "generate")
    _gates.check_generation_approval(cfg, [a.line_id], 1)
    _gates.check_take_limit(cfg, [a.line_id], 1, a.force)
    _gates.record_take(cfg, a.line_id, a.take, "generate_talking_head.py", a.script, a.force)

    res = seedance_api.create_task(ns, payload)
    task_id = seedance_api.task_id_from_response(res)
    say(f"created task_id={task_id}")
    ledger = cfg["_cwd"] / "out" / "takes-tasks.jsonl"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"id": a.line_id, "take": a.take, "task_id": task_id, "model": payload["model"],
                             "created_at": time.strftime("%Y-%m-%d %H:%M:%S")}, ensure_ascii=False) + "\n")

    result = seedance_api.wait_for_task(ns, task_id, a.poll)
    status = str(result.get("status", "")).lower()
    if status != "succeeded":
        print("FAILED status=" + status + " " +
              json.dumps(seedance_api.sanitize_for_storage(result), ensure_ascii=False)[:600])
        return 1

    url = seedance_api.video_url_from_response(result)
    out.parent.mkdir(parents=True, exist_ok=True)
    seedance_api.download_url(url, out)
    out.with_suffix(".url.txt").write_text(url, encoding="utf-8")
    say(f"downloaded -> {rel(cfg, out)}")
    say(f"耳と目で確認: 台本どおりに読めているか / 動きが大きすぎないか（{rel(cfg, out)}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
