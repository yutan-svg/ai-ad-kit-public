#!/usr/bin/env python3
"""台本JSONから、話者ごとの声で読み上げ音声（TTS）をまとめて作る。Google Cloud Text-to-Speech を使う。

何をする道具か: 「誰が・何と言うか」を書いた台本JSONを読み、話者ごとに設定した声・速さ・高さで
音声ファイルを書き出す。人物クリップの参照音声（generate_talking_head.py）や、
図解動画のナレーションに使う。生成前に「読み間違いが起きる書き方」を機械で止める。

使い方（案件フォルダのルートで。まず --dry-run でリクエスト内容を確認する）:
  python3 scripts/generate_tts.py --script tts.json [--ids s1,s2] [--dry-run]

声の名前は Neural2 系のほか Chirp 3 HD 系（例: ja-JP-Chirp3-HD-Laomedeia）も使える（pitch は 0.0 のままで通る）。
認証は gcloud CLI が無くても、~/.config/gcloud/application_default_credentials.json（`gcloud auth application-default login` の結果）があれば B) の経路で動く。

台本JSON（tts.json）の例:
{
  "defaults": {"voice": "ja-JP-Chirp3-HD-Laomedeia", "speakingRate": 1.0, "pitch": 0.0, "outDir": "assets/audio"},
  "speakers": {
    "narrator": {"voice": "ja-JP-Chirp3-HD-Laomedeia", "speakingRate": 1.05},
    "guest":    {"voice": "ja-JP-Neural2-B", "ssmlGender": "FEMALE", "speakingRate": 1.10}
  },
  "lines": [
    {"id": "s1", "speaker": "narrator", "text": "はじめまして。", "out": "s1.mp3"},
    {"id": "s2", "speaker": "guest",    "text": "よろしくお願いします。"}
  ]
}
- speakers も speaker も省略できる。そのとき defaults の声で読む
- out を省くと <outDir>/<id>.mp3 になる。outDir は案件フォルダからの相対パス
- 1行ごとに voice / speakingRate / pitch / ssml を上書きできる（"ssml": true で text を SSML として送る）
- 声の一覧と最新の対応言語は Google Cloud TTS の公式ドキュメントで確認する
- 読み方の辞書（pronunciationDict）はここには効かない。読み違う語は台本側の表記を開く（漢字→ひらがな）

生成前の検査（不合格なら1件でも生成しない）:
  1. 「〜方が」の残存 … Google の読み上げが「かた」と読む事故が実際に起きる。「ほう」に開いてから生成する
  2. text が空、id の重複、未知の speaker

合格基準: 全行が書き出され、各行の実測秒数が表示されて exit 0。
失敗時に見る場所: エラー行に出る id と理由。認証エラーなら下の「認証」を確認する。

認証（どれか1つ。鍵の中身は表示もコミットもしない）:
  A) 環境変数 GOOGLE_TTS_ACCESS_TOKEN にアクセストークンを入れておく
     例: export GOOGLE_TTS_ACCESS_TOKEN=$(gcloud auth application-default print-access-token)
  B) gcloud の ADC ファイル（~/.config/gcloud/application_default_credentials.json）
     `gcloud auth application-default login` で作る。組織のポリシーで鍵JSONが禁止の環境はこれ
  C) 環境変数 GOOGLE_APPLICATION_CREDENTIALS に ADC 形式（authorized_user）のJSONのパス
  D) 上のどれも無ければ `gcloud auth application-default print-access-token` を実行して取得を試みる
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _asr  # noqa: E402

TTS_ENDPOINT = "https://texttospeech.googleapis.com/v1/text:synthesize"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
ADC_PATH = Path.home() / ".config/gcloud/application_default_credentials.json"

DEFAULT_VOICE = "ja-JP-Neural2-C"
DEFAULT_LANGUAGE = "ja-JP"
DEFAULT_OUT_DIR = "assets/audio"
LINEAR16_RATE = 24000

# 「〜方が」は Google の読み上げが「かた」と読む事故が起きる。生成前に必ず止める。
AMBIGUOUS_HOU = re.compile(r"[぀-ゟ゠-ヿ一-鿿]+方が")


# ---------------------------------------------------------------------------
# 認証
# ---------------------------------------------------------------------------
def _refresh_token(cred: dict[str, Any]) -> str:
    data = urllib.parse.urlencode({
        "client_id": cred["client_id"],
        "client_secret": cred["client_secret"],
        "refresh_token": cred["refresh_token"],
        "grant_type": "refresh_token",
    }).encode()
    with urllib.request.urlopen(urllib.request.Request(TOKEN_ENDPOINT, data=data)) as r:
        return json.load(r)["access_token"]


def get_credentials() -> tuple[str, str]:
    """(アクセストークン, quota project) を返す。取れなければ使い方を出して終了する。"""
    tok = os.environ.get("GOOGLE_TTS_ACCESS_TOKEN") or os.environ.get("GOOGLE_ACCESS_TOKEN")
    if tok:
        return tok.strip(), os.environ.get("GOOGLE_CLOUD_PROJECT", "")

    path = Path(os.environ["GOOGLE_APPLICATION_CREDENTIALS"]) if os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") else ADC_PATH
    if path.exists():
        cred = json.loads(path.read_text(encoding="utf-8"))
        if cred.get("type") == "service_account":
            raise SystemExit(
                f"サービスアカウント鍵（{path}）は本スクリプトでは直接使えません。\n"
                "  `gcloud auth application-default login` で ADC を作るか、\n"
                "  GOOGLE_TTS_ACCESS_TOKEN にアクセストークンを入れてください。")
        if cred.get("refresh_token"):
            return _refresh_token(cred), cred.get("quota_project_id", "")

    r = subprocess.run(["gcloud", "auth", "application-default", "print-access-token"],
                       capture_output=True, text=True)
    if r.returncode == 0 and r.stdout.strip():
        return r.stdout.strip(), os.environ.get("GOOGLE_CLOUD_PROJECT", "")

    raise SystemExit(
        "認証情報が見つかりません。次のどれかを用意してください（詳しくは本ファイル冒頭の「認証」）:\n"
        "  1) gcloud auth application-default login\n"
        "  2) export GOOGLE_TTS_ACCESS_TOKEN=$(gcloud auth application-default print-access-token)\n"
        "  3) GOOGLE_APPLICATION_CREDENTIALS に ADC 形式のJSONのパス")


# ---------------------------------------------------------------------------
# 台本の読み込みと検査
# ---------------------------------------------------------------------------
def load_script(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{path}: JSONとして読めません: {exc}")
    if not isinstance(data.get("lines"), list) or not data["lines"]:
        raise SystemExit(f"{path}: lines に1件以上のセリフが必要です")
    return data


def resolve_line(line: dict[str, Any], data: dict[str, Any], out_dir: Path) -> dict[str, Any]:
    defaults: dict[str, Any] = dict(data.get("defaults") or {})
    speakers: dict[str, Any] = data.get("speakers") or {}
    name = line.get("speaker")
    if name and name not in speakers:
        raise SystemExit(f"[{line.get('id')}] speakers に無い話者です: {name}")
    conf: dict[str, Any] = {}
    conf.update(defaults)
    if name:
        conf.update(speakers[name])
    conf.update({k: v for k, v in line.items() if k not in ("id", "text", "speaker", "out")})

    voice = str(conf.get("voice") or DEFAULT_VOICE)
    # 声の名前 "ja-JP-Neural2-C" の先頭2要素が言語コード。明示指定があればそちらを優先する。
    parts = voice.split("-")
    lang = str(conf.get("languageCode") or ("-".join(parts[:2]) if len(parts) >= 2 else DEFAULT_LANGUAGE))
    out_name = line.get("out") or f"{line['id']}.mp3"
    out_path = out_dir / out_name
    return {
        "id": str(line["id"]),
        "text": str(line["text"]),
        "speaker": name or "(default)",
        "voice": voice,
        "languageCode": lang,
        "ssmlGender": conf.get("ssmlGender"),
        "speakingRate": float(conf.get("speakingRate", 1.0)),
        "pitch": float(conf.get("pitch", 0.0)),
        "ssml": bool(conf.get("ssml", False)),
        "out": out_path,
    }


def precheck(items: list[dict[str, Any]]) -> list[str]:
    problems: list[str] = []
    seen: set[str] = set()
    for it in items:
        if it["id"] in seen:
            problems.append(f"[{it['id']}] id が重複しています")
        seen.add(it["id"])
        if not it["text"].strip():
            problems.append(f"[{it['id']}] text が空です")
        m = AMBIGUOUS_HOU.search(it["text"])
        if m:
            problems.append(
                f"[{it['id']}] 「{m.group(0)}」があります。読み上げが「かた」と読む事故を避けるため、"
                "「ほうが」に開いてから生成してください")
    return problems


# ---------------------------------------------------------------------------
# 生成
# ---------------------------------------------------------------------------
def synthesize(item: dict[str, Any], token: str, project: str, encoding: str) -> bytes:
    voice: dict[str, Any] = {"languageCode": item["languageCode"], "name": item["voice"]}
    if item["ssmlGender"]:
        voice["ssmlGender"] = item["ssmlGender"]
    audio_config: dict[str, Any] = {
        "audioEncoding": encoding,
        "speakingRate": item["speakingRate"],
        "pitch": item["pitch"],
    }
    if encoding == "LINEAR16":
        audio_config["sampleRateHertz"] = LINEAR16_RATE
    body = {
        "input": ({"ssml": item["text"]} if item["ssml"] else {"text": item["text"]}),
        "voice": voice,
        "audioConfig": audio_config,
    }
    headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
    if project:
        headers["x-goog-user-project"] = project
    req = urllib.request.Request(TTS_ENDPOINT, data=json.dumps(body).encode(), headers=headers)
    try:
        with urllib.request.urlopen(req) as r:
            payload = json.load(r)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:400]
        raise RuntimeError(f"TTS API エラー {exc.code}: {detail}")
    content = payload.get("audioContent")
    if not content:
        raise RuntimeError("audioContent が空でした")
    return base64.b64decode(content)


def write_audio(raw: bytes, out: Path, encoding: str, trim: bool) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    if encoding == "MP3" and not trim:
        out.write_bytes(raw)
        return
    if encoding == "MP3":
        cmd_in = ["-i", "pipe:0"]
    else:
        cmd_in = ["-f", "s16le", "-ar", str(LINEAR16_RATE), "-ac", "1", "-i", "pipe:0"]
    af = []
    if trim:
        # 前後の無音を落とす（頭の間・尾の余韻を残さない）
        af = ["-af", "silenceremove=start_periods=1:start_threshold=-40dB,areverse,"
                     "silenceremove=start_periods=1:start_threshold=-40dB,areverse"]
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", *cmd_in, *af, str(out)], input=raw, capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg 失敗: {r.stderr.decode('utf-8', 'replace')[-300:]}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--script", required=True, help="台本JSON（例: tts.json）")
    ap.add_argument("--ids", default="", help="生成する id をカンマ区切りで（既定: 全部）")
    ap.add_argument("--out-dir", default=None, help="出力先（既定: 台本の defaults.outDir、無ければ assets/audio）")
    ap.add_argument("--encoding", choices=("MP3", "LINEAR16"), default="MP3", help="音声形式（既定 MP3）")
    ap.add_argument("--trim-silence", action="store_true", help="前後の無音を落としてから保存する")
    ap.add_argument("--dry-run", action="store_true", help="API を呼ばず、生成内容だけ表示する（無料）")
    a = ap.parse_args()
    if not a.dry_run:
        import _gates  # noqa: E402
        from _config import load_config  # noqa: E402
        _gates.check_project(load_config(), "generate")

    data = load_script(Path(a.script))
    out_dir = Path(a.out_dir or (data.get("defaults") or {}).get("outDir") or DEFAULT_OUT_DIR)
    wanted = {x.strip() for x in a.ids.split(",") if x.strip()}
    items = [resolve_line(l, data, out_dir) for l in data["lines"]
             if not wanted or str(l.get("id")) in wanted]
    if not items:
        raise SystemExit("生成対象がありません（--ids の指定を確認してください）")

    problems = precheck(items)
    if problems:
        print("✗ 生成前の検査で不合格（1件でもあれば生成しません）:")
        for p in problems:
            print("  - " + p)
        return 1

    print(f"=== generate_tts: {len(items)}本  形式 {a.encoding}  出力先 {out_dir}/")
    for it in items:
        preview = it["text"] if len(it["text"]) <= 30 else it["text"][:30] + "…"
        print(f"  [{it['id']}] {it['speaker']} / {it['voice']} rate={it['speakingRate']} pitch={it['pitch']}"
              f" → {it['out']}  「{preview}」")
    if a.dry_run:
        print("\n--dry-run のため API は呼びませんでした")
        return 0

    token, project = get_credentials()
    errors: list[str] = []
    for it in items:
        try:
            raw = synthesize(it, token, project, a.encoding)
            write_audio(raw, it["out"], a.encoding, a.trim_silence)
            print(f"  ✓ {it['out']}  {_asr.probe_duration(it['out']):.2f}s")
        except Exception as exc:  # noqa: BLE001 - 1本の失敗で全体を止めない
            print(f"  ✗ [{it['id']}] {exc}")
            errors.append(f"{it['id']}: {exc}")

    if errors:
        print(f"\n✗ {len(errors)}件が失敗しました")
        return 1
    print(f"\n✓ {len(items)}本の生成が完了しました。"
          "実測の秒数をシーン定義の durationSeconds に反映し、align_captions.py で同期を取り直してください")
    return 0


if __name__ == "__main__":
    sys.exit(main())
