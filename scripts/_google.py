#!/usr/bin/env python3
"""Gemini API（Google）への共通の入口。映像・画像・文字起こしのスクリプトが使う部品。

扱うもの（すべて標準ライブラリだけ。鍵の値は表示も保存もしない）:
  - api_key()        `.env` の GEMINI_API_KEY を読む（案件フォルダ → キットの順）
  - post_json/get_json/get_bytes   HTTP の往復。エラー本文に鍵が混ざっても伏せる
  - veo_generate()   Veo 3.1（predictLongRunning。非同期。完了まで待つ）
  - omni_generate()  Gemini Omni 1.1 Flash（POST /v1beta/interactions。同期。base64 で返る）
  - make_image()     Nano Banana 2（参照画像を1枚つくる）
  - transcribe()     音声を文字起こしする（whisper の代わりの検品エンジン）

公式の仕様（2026-09-17 確認）:
  https://ai.google.dev/gemini-api/docs/veo ／ /docs/omni ／ /docs/video
仕様は変わります。断定する前に上のページで確かめてください（RULES.md 決まり32）。
"""
from __future__ import annotations

import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
KIT_ROOT = HERE.parent

BASE = "https://generativelanguage.googleapis.com/v1beta"

# 既定のモデル。ai-ad.config.json で上書きできる項目は各スクリプトの引数を見てください。
VEO_MODEL = "veo-3.1-generate-preview"
OMNI_MODEL = "gemini-omni-1.1-flash"
IMAGE_MODEL = "gemini-3.1-flash-image"      # Nano Banana 2
ASR_MODEL = "gemini-3.5-flash"              # 文字起こし（gemini-3.5-transcribe は空応答の実測あり）

_KEY: str | None = None


# ---------------------------------------------------------------------------
# 鍵
# ---------------------------------------------------------------------------
def load_env() -> None:
    """案件フォルダ → キットの順に .env を読む（既にある環境変数が優先）。"""
    for path in (Path.cwd() / ".env", KIT_ROOT / ".env"):
        if not path.exists():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
        return


def api_key() -> str:
    global _KEY
    if _KEY:
        return _KEY
    load_env()
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key and os.environ.get("GOOGLE_KEY_BY_PROXY") == "1":
        # クラウドの作業環境（AI Studio の Antigravity agent）では、通信の代理サーバーが
        # generativelanguage.googleapis.com 宛てに鍵のヘッダーを付ける。鍵をファイルに置かずに済む。
        _KEY = ""
        return ""
    if not key:
        raise SystemExit(
            "GEMINI_API_KEY がありません。Google のモデル（Veo／Omni／Nano Banana／文字起こし）には鍵が要ります。\n"
            "  1) https://aistudio.google.com/apikey で鍵を作る\n"
            "  2) キットのルートで `cp .env.example .env`（既にあればそのまま）\n"
            "  3) .env の GEMINI_API_KEY= の右に貼る（鍵は人に見せない・チャットに貼らない）")
    _KEY = key
    return key


def redact(text: str) -> str:
    return text.replace(_KEY, "[REDACTED]") if _KEY else text


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def _headers() -> dict[str, str]:
    h = {"Content-Type": "application/json"}
    key = api_key()
    if key:
        h["x-goog-api-key"] = key
    return h


def post_json(url: str, body: dict[str, Any], timeout: float = 900, soft: bool = False) -> dict[str, Any]:
    """POST して JSON を返す。soft=True のときは HTTP エラーを {"_error": …} で返す（投げ直し用）。"""
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers=_headers(), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        msg = f"HTTP {exc.code}: " + redact(exc.read().decode("utf-8", "replace")[:2000])
        if soft:
            return {"_error": msg, "_code": exc.code}
        raise SystemExit(msg)
    except urllib.error.URLError as exc:
        msg = f"通信できませんでした: {exc}"
        if soft:
            return {"_error": msg, "_code": 0}
        raise SystemExit(msg)


def get_json(url: str, timeout: float = 120) -> dict[str, Any]:
    req = urllib.request.Request(url, headers=_headers())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"HTTP {exc.code}: " + redact(exc.read().decode("utf-8", "replace")[:1500]))


def get_bytes(uri: str, timeout: float = 600) -> bytes:
    key = api_key()
    req = urllib.request.Request(uri, headers=({"x-goog-api-key": key} if key else {}))
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


# ---------------------------------------------------------------------------
# レスポンスの中から目的のものを探す（構造がバージョンで揺れるため再帰で探す）
# ---------------------------------------------------------------------------
def find_uri(obj: Any) -> str | None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("uri", "url") and isinstance(v, str) and v.startswith("http"):
                return v
            found = find_uri(v)
            if found:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = find_uri(v)
            if found:
                return found
    return None


def find_media(obj: Any) -> tuple[str, str] | None:
    """(base64文字列, mime) を再帰で探す。"""
    if isinstance(obj, dict):
        for key in ("inlineData", "inline_data", "data", "bytes", "bytesBase64Encoded"):
            v = obj.get(key)
            if isinstance(v, dict):
                got = find_media(v)
                if got:
                    return got
            if isinstance(v, str) and len(v) > 5000:
                return v, str(obj.get("mimeType") or obj.get("mime_type") or "application/octet-stream")
        for v in obj.values():
            got = find_media(v)
            if got:
                return got
    elif isinstance(obj, list):
        for v in obj:
            got = find_media(v)
            if got:
                return got
    return None


def skeleton(obj: Any, depth: int = 0) -> Any:
    """base64 を伏せた構造だけを返す（記録・表示用）。"""
    if depth > 6:
        return "..."
    if isinstance(obj, dict):
        return {k: skeleton(v, depth + 1) for k, v in obj.items()}
    if isinstance(obj, list):
        return [skeleton(obj[0], depth + 1), f"...x{len(obj)}"] if obj else []
    if isinstance(obj, str):
        return obj if len(obj) < 160 else f"<str {len(obj)}>"
    return obj


def b64_of(path: Path) -> tuple[str, str]:
    raw = path.read_bytes()
    mime = "image/png" if raw[:4] == b"\x89PNG" else "image/jpeg"
    return base64.b64encode(raw).decode("ascii"), mime


# ---------------------------------------------------------------------------
# Veo 3.1（非同期。predictLongRunning → operation を待つ）
# ---------------------------------------------------------------------------
_UNSUPPORTED_RE = re.compile(r"`([A-Za-z_]+)` (?:isn't|is not) supported")
# 「その値は使えません。使えるのは〜です」という形のエラー。指定を1つ目の候補に替えて投げ直す。
_BAD_VALUE_RE = re.compile(
    r"The value '([^']+)' is not supported for '([A-Za-z_.]+)'\.\s*Supported values:\s*'([^']+)'")


def _set_by_path(obj: dict[str, Any], dotted: str, value: Any) -> bool:
    """a.b.c のような場所に値を入れる。入れられたら True。"""
    parts = dotted.split(".")
    cur: Any = obj
    for key in parts[:-1]:
        if not isinstance(cur, dict) or key not in cur:
            return False
        cur = cur[key]
    if isinstance(cur, dict) and parts[-1] in cur:
        cur[parts[-1]] = value
        return True
    return False


def veo_generate(instance: dict[str, Any], parameters: dict[str, Any], out: Path,
                 model: str = VEO_MODEL, poll: float = 10.0, timeout: float = 900,
                 say=print) -> dict[str, Any]:
    """Veo に1本投げて、出来た動画を out に保存する。返り値は記録用の情報。

    受け付けないパラメータがあるとエラー本文にその名前が出る。HTTP 400 は課金されないので、
    名指しされた項目を外して投げ直す（1往復の無駄を減らすため）。
    """
    url = f"{BASE}/models/{model}:predictLongRunning"
    params = dict(parameters)
    op = None
    for _ in range(8):
        res = post_json(url, {"instances": [instance], "parameters": params}, soft=True)
        if "_error" not in res:
            op = res
            break
        msg = str(res["_error"])
        m = _UNSUPPORTED_RE.search(msg)
        if m and m.group(1) in params:
            say(f"[param] {m.group(1)} はこのモデルが受け付けないので外して投げ直します")
            params.pop(m.group(1))
            continue
        if "durationSeconds" in msg and "durationSeconds" in params:
            # 公式ドキュメントは文字列 "8"、実測では数値 8 が通る。片方で落ちたらもう片方で投げ直す。
            value = params["durationSeconds"]
            params["durationSeconds"] = int(value) if isinstance(value, str) else str(value)
            say(f"[param] durationSeconds を {value!r} から {params['durationSeconds']!r} に変えて投げ直します")
            continue
        if "Negative prompt is not supported" in msg and "negativePrompt" in params:
            say("[param] negativePrompt は参照画像と併用できないので外して投げ直します"
                "（字幕を出さない指示は本文の末尾に入っています）")
            params.pop("negativePrompt")
            continue
        if res.get("_code") == 429:
            raise SystemExit(
                "✗ Veo の枠が切れています（HTTP 429。この失敗に費用はかかりません）。\n"
                "  日次の枠が戻るまで待つか、Omni（--engine omni）で作ってください。\n"
                "  元のエラー: " + msg[:400])
        raise SystemExit(msg)
    if op is None:
        raise SystemExit("Veo がリクエストを受け付けませんでした")

    name = op.get("name")
    if not name:
        raise SystemExit(f"operation の名前がありません: {json.dumps(op, ensure_ascii=False)[:800]}")
    say(f"[op] {name}")
    t0 = time.time()
    while True:
        time.sleep(poll)
        state = get_json(f"{BASE}/{name}")
        if state.get("done"):
            break
        if time.time() - t0 > timeout:
            raise SystemExit(f"Veo がタイムアウトしました（{timeout:.0f}秒）。operation: {name}")
    if "error" in state:
        raise SystemExit("Veo の生成エラー: " + json.dumps(state["error"], ensure_ascii=False)[:1200])

    blob = json.dumps(state, ensure_ascii=False)
    if "raiMediaFiltered" in blob:
        raise SystemExit(
            "✗ 安全フィルタ（RAI）で落ちました。この失敗に費用はかかりません。\n"
            "  日本語のセリフでは「！」や全角の「」が原因になる実測があります。"
            "「。」に替える・引用符を半角にするなど、台本の表記を変えて試してください。\n"
            "  応答: " + blob[:600])
    uri = find_uri(state)
    if not uri:
        raise SystemExit("動画の場所が応答にありません: " + blob[:800])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(get_bytes(uri))
    return {"operation": name, "elapsed_sec": round(time.time() - t0, 1), "parameters": params}


# ---------------------------------------------------------------------------
# Gemini Omni 1.1 Flash（同期。Interactions API）
# ---------------------------------------------------------------------------
def omni_generate(body: dict[str, Any], out: Path, timeout: float = 900, say=print) -> dict[str, Any]:
    """Omni に1本投げて、返ってきた動画（base64）を out に保存する。

    `generateContent` は使えません（400 "This model only supports Interactions API."）。
    受け付けない項目があれば名指しで返るので、外して投げ直す（400 は課金されない）。
    """
    url = f"{BASE}/interactions"
    payload = json.loads(json.dumps(body, ensure_ascii=False))
    res = None
    for _ in range(6):
        got = post_json(url, payload, timeout=timeout, soft=True)
        if "_error" not in got:
            res = got
            break
        msg = str(got["_error"])
        bad = _BAD_VALUE_RE.search(msg)
        if bad and _set_by_path(payload, bad.group(2), bad.group(3)):
            say(f"[param] {bad.group(2)} を {bad.group(1)!r} から {bad.group(3)!r} に替えて投げ直します")
            continue
        m = _UNSUPPORTED_RE.search(msg) or re.search(r'Unknown name "([A-Za-z_]+)"', msg)
        if m and m.group(1) in payload:
            say(f"[param] {m.group(1)} は受け付けられないので外して投げ直します")
            payload.pop(m.group(1))
            continue
        if got.get("_code") == 429:
            raise SystemExit("✗ Omni の枠が切れています（HTTP 429。この失敗に費用はかかりません）。\n  " + msg[:400])
        raise SystemExit(msg)
    if res is None:
        raise SystemExit("Omni がリクエストを受け付けませんでした")

    usage = res.get("usage") or res.get("usageMetadata") or {}
    media = find_media(res)
    if not media:
        uri = find_uri(res)
        if uri:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(get_bytes(uri))
            return {"usage": usage, "sent": payload}
        raise SystemExit("動画が応答にありません。構造: "
                         + json.dumps(skeleton(res), ensure_ascii=False)[:800])
    b64, mime = media
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(base64.b64decode(b64))
    return {"usage": usage, "mime": mime, "sent": payload}


# ---------------------------------------------------------------------------
# Nano Banana 2（参照画像）
# ---------------------------------------------------------------------------
def make_image(prompt: str, out: Path, model: str = IMAGE_MODEL, timeout: float = 300) -> dict[str, Any]:
    res = post_json(f"{BASE}/models/{model}:generateContent",
                    {"contents": [{"parts": [{"text": prompt}]}]}, timeout=timeout)
    for cand in res.get("candidates", []):
        for part in cand.get("content", {}).get("parts", []):
            inline = part.get("inlineData") or part.get("inline_data")
            if inline and inline.get("data"):
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(base64.b64decode(inline["data"]))
                return {"mime": inline.get("mimeType") or inline.get("mime_type"),
                        "usage": res.get("usageMetadata", {})}
    raise SystemExit("画像が返りませんでした: " + json.dumps(skeleton(res), ensure_ascii=False)[:800])


# ---------------------------------------------------------------------------
# 文字起こし（検品エンジン）
# ---------------------------------------------------------------------------
TRANSCRIBE_PROMPT = (
    "この音声を日本語で厳密に文字起こししてください。聞こえたままを書き、聞こえない語を補完しないでください。"
    "説明・前置き・記号は付けず、文字起こしの本文だけを1行で出力してください。")


def transcribe(path: Path, model: str = ASR_MODEL, timeout: float = 300) -> str:
    """音声（または動画）を文字起こしして1行で返す。whisper の代わりの検品エンジン。"""
    raw = Path(path).read_bytes()
    suffix = Path(path).suffix.lower()
    mime = {".wav": "audio/wav", ".mp3": "audio/mpeg", ".m4a": "audio/mp4",
            ".mp4": "video/mp4", ".mov": "video/quicktime"}.get(suffix, "audio/wav")
    body = {"contents": [{"parts": [
        {"text": TRANSCRIBE_PROMPT},
        {"inline_data": {"mime_type": mime, "data": base64.b64encode(raw).decode("ascii")}},
    ]}]}
    res = post_json(f"{BASE}/models/{model}:generateContent", body, timeout=timeout)
    parts = ((res.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
    text = " ".join(p.get("text", "") for p in parts).strip()
    if not text:
        raise RuntimeError(
            f"{model} が文字起こしを返しませんでした（空応答）。"
            "ai-ad.config.json の geminiAsrModel を別のモデルにするか、asrEngine を whisper に戻してください")
    return text.replace("\n", " ").strip()


if __name__ == "__main__":  # 鍵の確認だけ（値は表示しない）
    load_env()
    print("GEMINI_API_KEY: " + ("あり" if os.environ.get("GEMINI_API_KEY") else "なし"))
    sys.exit(0)
