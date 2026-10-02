#!/usr/bin/env python3
"""BytePlus ModelArk Seedance 動画生成APIクライアント（自社実装）。

実装の根拠は公式APIリファレンスのみ:
  - Create a video generation task: https://docs.byteplus.com/en/docs/ModelArk/1520757
    POST {base}/api/v3/contents/generations/tasks  (Authorization: Bearer $ARK_API_KEY)
  - Retrieve a video generation task: https://docs.byteplus.com/en/docs/ModelArk/1521309
    GET  {base}/api/v3/contents/generations/tasks/{id}

標準ライブラリのみ使用。APIキーはリポジトリに保存せず、環境変数
(ARK_API_KEY / SEEDANCE_API_KEY / BYTEPLUS_ARK_API_KEY / MODELARK_API_KEY)
またはプロジェクト直下の .env（untracked）から読む。
"""

from __future__ import annotations

import argparse
import base64
import copy
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE_URL = "https://ark.ap-southeast.bytepluses.com"
TASKS_PATH = "/api/v3/contents/generations/tasks"
DEFAULT_OUT_DIR = PROJECT_ROOT / "out" / "seedance-runs"
API_KEY_ENV_VARS = ("ARK_API_KEY", "SEEDANCE_API_KEY", "BYTEPLUS_ARK_API_KEY", "MODELARK_API_KEY")

# 公式ドキュメントの status 値（queued/running は非終端）
TERMINAL_STATUSES = {"succeeded", "failed", "cancelled", "expired"}

# 生成パラメータ（Namespace属性名 = リクエストボディのフィールド名）
_GENERATION_FIELDS = (
    "resolution", "ratio", "duration", "frames", "generate_audio", "watermark",
    "output_format", "seed", "camera_fixed", "return_last_frame", "draft",
    "service_tier", "callback_url", "execution_expires_after", "priority",
    "safety_identifier", "omni_reference_task_type",
)


def load_project_env() -> None:
    """カレントディレクトリ → このスクリプトの置き場所の順に .env を読む（既存の環境変数を優先）。"""
    candidates = [Path.cwd() / ".env", PROJECT_ROOT / ".env"]
    env_path = next((p for p in candidates if p.exists()), None)
    if env_path is None:
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def default_model() -> str:
    return os.environ.get("SEEDANCE_MODEL", "dreamina-seedance-2-5-260628")


class _DefaultModelStr(str):
    """import時点で.env未読込でも、参照時に環境変数を反映できるようにする薄いラッパ。"""


DEFAULT_MODEL = os.environ.get("SEEDANCE_MODEL") or "dreamina-seedance-2-5-260628"


def _api_key(args: argparse.Namespace | None) -> str:
    if args is not None and getattr(args, "api_key_file", None):
        return Path(args.api_key_file).read_text(encoding="utf-8").strip()
    load_project_env()
    for name in API_KEY_ENV_VARS:
        value = os.environ.get(name)
        if value:
            return value.strip()
    raise SystemExit(f"APIキーが見つかりません。{' / '.join(API_KEY_ENV_VARS)} のいずれかを設定してください。")


def _base_url(args: argparse.Namespace | None) -> str:
    if args is not None and getattr(args, "base_url", None):
        return str(args.base_url).rstrip("/")
    return os.environ.get("SEEDANCE_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


def _file_to_data_url(path: str, fallback_mime: str) -> str:
    data = Path(path).read_bytes()
    mime = mimetypes.guess_type(path)[0] or fallback_mime
    return f"data:{mime};base64," + base64.b64encode(data).decode("ascii")


def build_payload(args: argparse.Namespace) -> dict[str, Any]:
    """Namespaceから公式リクエストボディを組み立てる。

    優先順位: args.payload（JSON文字列 or ファイルパス）> args.content > prompt+URL群
    """
    raw_payload = getattr(args, "payload", None)
    if raw_payload:
        text = Path(raw_payload).read_text(encoding="utf-8") if os.path.exists(raw_payload) else raw_payload
        return json.loads(text)

    content: list[dict[str, Any]]
    raw_content = getattr(args, "content", None)
    if raw_content:
        content = json.loads(Path(raw_content).read_text(encoding="utf-8")) if os.path.exists(str(raw_content)) else json.loads(raw_content)
    else:
        content = []
        prompt = getattr(args, "prompt", None)
        if prompt:
            content.append({"type": "text", "text": prompt})
        image_role = getattr(args, "image_role", None)
        for url in (getattr(args, "image_url", None) or []):
            item: dict[str, Any] = {"type": "image_url", "image_url": {"url": url}}
            if image_role:
                item["role"] = image_role
            content.append(item)
        for path in (getattr(args, "image_file", None) or []):
            item = {"type": "image_url", "image_url": {"url": _file_to_data_url(path, "image/png")}}
            if image_role:
                item["role"] = image_role
            content.append(item)
        for url in (getattr(args, "video_url", None) or []):
            content.append({"type": "video_url", "video_url": {"url": url}})
        for path in (getattr(args, "video_file", None) or []):
            content.append({"type": "video_url", "video_url": {"url": _file_to_data_url(path, "video/mp4")}})
        for url in (getattr(args, "audio_url", None) or []):
            content.append({"type": "audio_url", "audio_url": {"url": url}})
        for path in (getattr(args, "audio_file", None) or []):
            content.append({"type": "audio_url", "audio_url": {"url": _file_to_data_url(path, "audio/mpeg")}})

    payload: dict[str, Any] = {
        "model": getattr(args, "model", None) or default_model(),
        "content": content,
    }
    for field in _GENERATION_FIELDS:
        value = getattr(args, field, None)
        if value is not None:
            payload[field] = value
    return payload


def request_json(args: argparse.Namespace | None, method: str, path: str,
                 payload: dict[str, Any] | None = None) -> dict[str, Any]:
    url = _base_url(args) + path
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=body, method=method, headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {_api_key(args)}",
    })
    timeout = getattr(args, "timeout", None) or 60
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} {method} {path}: {detail[:2000]}") from exc


def create_task(args: argparse.Namespace, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    return request_json(args, "POST", TASKS_PATH, payload or build_payload(args))


def get_task(args: argparse.Namespace | None, task_id: str) -> dict[str, Any]:
    return request_json(args, "GET", f"{TASKS_PATH}/{task_id}")


def task_id_from_response(response: dict[str, Any]) -> str:
    task_id = response.get("id")
    if not task_id:
        raise RuntimeError(f"レスポンスにタスクIDがありません: {json.dumps(response, ensure_ascii=False)[:500]}")
    return str(task_id)


def _find_first_url(node: Any, key: str) -> str | None:
    if isinstance(node, dict):
        if isinstance(node.get(key), str):
            return node[key]
        for value in node.values():
            found = _find_first_url(value, key)
            if found:
                return found
    elif isinstance(node, list):
        for value in node:
            found = _find_first_url(value, key)
            if found:
                return found
    return None


def video_url_from_response(response: dict[str, Any]) -> str:
    url = _find_first_url(response, "video_url")
    if not url:
        raise RuntimeError(f"video_urlが見つかりません: {json.dumps(sanitize_for_storage(response), ensure_ascii=False)[:800]}")
    return url


def sanitize_for_storage(response: dict[str, Any]) -> dict[str, Any]:
    """署名付きURLのクエリ部を落とした保存用コピーを返す。"""
    def _clean(node: Any) -> Any:
        if isinstance(node, dict):
            return {k: _clean(v) for k, v in node.items()}
        if isinstance(node, list):
            return [_clean(v) for v in node]
        if isinstance(node, str) and node.startswith("http") and "?" in node:
            return node.split("?", 1)[0] + "?<redacted>"
        return node
    return _clean(copy.deepcopy(response))


def download_url(url: str, output: str | Path, timeout: int = 120) -> Path:
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=timeout) as resp, open(output, "wb") as fh:
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            fh.write(chunk)
    return output


def wait_for_task(args: argparse.Namespace, task_id: str, poll_seconds: float = 15.0) -> dict[str, Any]:
    while True:
        result = get_task(args, task_id)
        status = str(result.get("status", "")).lower()
        print(f"status={status} task_id={task_id}", flush=True)
        if status in TERMINAL_STATUSES:
            return result
        time.sleep(poll_seconds)


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["create", "get", "wait", "download"], help="実行する操作")
    parser.add_argument("task_or_url", nargs="?", help="get/wait: タスクID、download: URL")
    parser.add_argument("--model", default=None)
    parser.add_argument("--prompt", default=None)
    parser.add_argument("--payload", default=None, help="JSON文字列またはファイルパス（content含む完全なボディ）")
    parser.add_argument("--content", default=None, help="content配列のJSON")
    parser.add_argument("--image-url", dest="image_url", action="append", default=[])
    parser.add_argument("--image-file", dest="image_file", action="append", default=[])
    parser.add_argument("--image-role", dest="image_role", default=None)
    parser.add_argument("--video-url", dest="video_url", action="append", default=[])
    parser.add_argument("--video-file", dest="video_file", action="append", default=[])
    parser.add_argument("--audio-url", dest="audio_url", action="append", default=[])
    parser.add_argument("--audio-file", dest="audio_file", action="append", default=[])
    for field in _GENERATION_FIELDS:
        parser.add_argument(f"--{field.replace('_', '-')}", dest=field, default=None)
    parser.add_argument("--base-url", dest="base_url", default=None)
    parser.add_argument("--api-key-file", dest="api_key_file", default=None)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--out", default=None, help="download: 保存先パス")
    parser.add_argument("--dry-run", dest="dry_run", action="store_true", help="create: ボディを表示して送信しない")
    return parser


def main() -> int:
    load_project_env()
    args = _build_arg_parser().parse_args()
    if args.command == "create":
        payload = build_payload(args)
        if args.dry_run:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0
        result = create_task(args, payload)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    if args.command in ("get", "wait"):
        if not args.task_or_url:
            raise SystemExit("タスクIDを指定してください")
        result = get_task(args, args.task_or_url) if args.command == "get" else wait_for_task(args, args.task_or_url)
        print(json.dumps(sanitize_for_storage(result), ensure_ascii=False, indent=2))
        return 0
    if args.command == "download":
        if not args.task_or_url or not args.out:
            raise SystemExit("URLと--outを指定してください")
        path = download_url(args.task_or_url, args.out, args.timeout)
        print(str(path))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
