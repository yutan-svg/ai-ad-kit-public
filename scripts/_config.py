#!/usr/bin/env python3
"""案件設定（ai-ad.config.json）の読み込みと、シーン定義ファイルの解析。各スクリプト共通のモジュール。

各スクリプトは **案件フォルダ（cwd）** で実行される前提。cwd の ai-ad.config.json を読み、
無い項目は既定値で補う。sceneFiles が無ければ src/ 配下から `caption:` を含む .ts/.tsx を自動検出する。

ai-ad.config.json の例（すべて省略可）:
{
  "sceneFiles": ["src/scenes.ts"],
  "whisperModel": ".whisper-models/ggml-large-v3-turbo.bin",
  "whisperModel2": ".whisper-models/ggml-kotoba-whisper-v2.0.bin",
  "asrEngine": "whisper",
  "asrEngine2": "whisper",
  "captionMaxWidthPx": 1000,
  "defaultFontSize": 88,
  "takesDir": "assets/videos/takes",
  "pronunciationDict": "scripts/pronunciation_dict.json",
  "pronunciationDictExtra": "knowledge/pronunciation.json",
  "ngWords": "scripts/asr_ng_words.txt"
}

シーン定義の書式（1シーン1行のオブジェクトリテラル。正規表現で解析するので次を守る:
id が先頭、caption が durationSeconds より前、文字列はシングルクォート、改行は \\n）:
  {id: 1, caption: 'テキスト\\n2行目', durationSeconds: 3.2, src: 'videos/xxx.mp4', videoStartSeconds: 0, playbackRate: 1, bgColor: '#d7e3ec', captionY: 1254, narrowCaptionY: 940, fontSize: 88, captionTone: 'yellow', audioSrc: 'audio/xxx.m4a'},
音声トラック（複数シーンにまたがる1本の音声。1行ずつ）:
  {src: 'audio/xxx.m4a', startSeconds: 0, durationSeconds: 5.2, atSceneId: 1},
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

TOOL_ROOT = Path(__file__).resolve().parents[1]
CONFIG_NAME = "ai-ad.config.json"

DEFAULTS: dict[str, Any] = {
    "sceneFiles": [],                    # 空なら src/ 配下を自動検出
    "publicDir": "assets",               # src / audioSrc の基準ディレクトリ（Remotion の staticFile と同じ）
    "whisperModel": ".whisper-models/ggml-large-v3-turbo.bin",
    "whisperModel2": ".whisper-models/ggml-kotoba-whisper-v2.0.bin",   # ファイルが無ければ1エンジンで判定
    "captionMaxWidthPx": 1000,
    "defaultFontSize": 88,
    "takesDir": "assets/videos/takes",
    "pronunciationDict": str(TOOL_ROOT / "scripts" / "pronunciation_dict.json"),
    # 案件ごとに足す読み方（商材名・固有名詞）。キットを新版に差し替えても消えない場所に置く。
    # ファイルが無ければ無視されるので、必要になってから作ればよい。
    "pronunciationDictExtra": "knowledge/pronunciation.json",
    "ngWords": str(TOOL_ROOT / "scripts" / "asr_ng_words.txt"),
    "asrErrRateMax": 0.08,               # 期待テキストとの編集距離率の上限（generate_lines.py）
    "asrExtraCharsMax": 2,               # ASR側の余剰文字数の上限（誤発話・ゴミ混入の検出）
    "asrTailMinSec": 0.05,               # 発話終了からクリップ末尾までに必要な無音（末尾切れの検出）
    "language": "ja",                    # whisper の言語コード
    # 検品に使う音声認識エンジン。"whisper"（手元・無料）か "gemini"（Google・要 GEMINI_API_KEY）。
    # asrEngine2 を "none" にすると1エンジンだけで判定する（合議なし）。
    "asrEngine": "whisper",
    "asrEngine2": "whisper",
    "geminiAsrModel": "gemini-3.5-flash",
    # --- preflight.py（レンダー前の総合検査）で使う値 ---
    "videoWidth": 1080,                  # 画面幅px（縦型 9:16 の既定）
    "videoHeight": 1920,                 # 画面高px
    "safeMarginPx": 65,                  # 左右の安全マージンpx（配信面のUIと衝突させないため）
    "captionMaxRows": 3,                 # テロップの最大行数
    "graphicVisuals": [],                # 縦配置バンド検査の対象にする visual 値（図解シーンの識別子。空なら検査しない）
    "captionBandTop": 384,               # 図解シーンでテロップ上端がこれより上なら図と衝突の疑い
    "captionBandBottom": 1344,           # 図解シーンでテロップ下端がこれより下なら下すぎ
    "maxTotalSeconds": 118,              # 納品尺の上限（配信面の上限120秒に対する2秒のマージン）
    "trackTailSilenceMaxSec": 0.5,       # 音声トラック末尾に許す無音
    "trackSyncToleranceSec": 0.35,       # トラック尺とシーン合計尺のずれの許容
}


def load_config(cwd: Path | None = None) -> dict[str, Any]:
    """cwd の ai-ad.config.json を既定値にマージして返す。内部キー: _cwd, _configPath"""
    cwd = Path(cwd or Path.cwd())
    cfg: dict[str, Any] = dict(DEFAULTS)
    cfg["_cwd"] = cwd
    path = cwd / CONFIG_NAME
    cfg["_configPath"] = path if path.exists() else None
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"{path}: JSONとして読めません: {exc}")
        for key, value in data.items():
            if not key.startswith("_"):
                cfg[key] = value
    if isinstance(cfg["sceneFiles"], str):
        cfg["sceneFiles"] = [cfg["sceneFiles"]]
    return cfg


def resolve(cfg: dict[str, Any], path: str | Path) -> Path:
    """設定値のパスを cwd 基準で絶対パスにする。"""
    p = Path(path)
    return p if p.is_absolute() else cfg["_cwd"] / p


def rel(cfg: dict[str, Any], path: str | Path) -> str:
    """表示用: cwd からの相対パス（外なら絶対パス）。"""
    try:
        return str(Path(path).resolve().relative_to(cfg["_cwd"].resolve()))
    except ValueError:
        return str(path)


def scene_files(cfg: dict[str, Any], override: list[str] | None = None) -> list[Path]:
    """対象のシーン定義ファイル一覧。引数指定 > config の sceneFiles > src/ 自動検出。"""
    if override:
        files = [resolve(cfg, p) for p in override]
    elif cfg["sceneFiles"]:
        files = [resolve(cfg, p) for p in cfg["sceneFiles"]]
    else:
        src = cfg["_cwd"] / "src"
        files = []
        if src.is_dir():
            for p in sorted(src.rglob("*")):
                if p.suffix in (".ts", ".tsx") and "node_modules" not in p.parts:
                    try:
                        if "caption:" in p.read_text(encoding="utf-8"):
                            files.append(p)
                    except UnicodeDecodeError:
                        continue
        if not files:
            raise SystemExit(
                "シーン定義ファイルが見つかりません（src/ 配下に caption: を含む .ts/.tsx が無い）。\n"
                f"  {CONFIG_NAME} の sceneFiles で指定してください。"
            )
    missing = [p for p in files if not p.exists()]
    if missing:
        raise SystemExit("シーン定義ファイルがありません: " + ", ".join(str(p) for p in missing))
    return files


def whisper_model(cfg: dict[str, Any], key: str = "whisperModel", required: bool = True) -> Path | None:
    """音声認識モデルのパス。設定値の場所に無ければ、このキットの .whisper-models/ も探す。"""
    value = cfg.get(key)
    if not value:
        if required:
            raise SystemExit(f"{CONFIG_NAME} の {key} が未設定です")
        return None
    p = resolve(cfg, value)
    if p.exists():
        return p
    fallback = TOOL_ROOT / ".whisper-models" / Path(value).name
    if fallback.exists():
        return fallback
    if required:
        raise SystemExit(
            f"whisperモデルが見つかりません: {p}\n"
            "  次のコマンドでダウンロードできます（1回だけ・約1.5GB）:\n"
            "    mkdir -p .whisper-models\n"
            "    curl -L -o .whisper-models/ggml-large-v3-turbo.bin \\\n"
            "      https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo.bin"
        )
    return None


# ---------------------------------------------------------------------------
# シーン定義の解析
# ---------------------------------------------------------------------------
_NUM = r"(-?[0-9]+(?:\.[0-9]+)?)"
SCENE_LINE_RE = re.compile(r"^\s*\{id:\s*" + _NUM + r"\s*,")
TRACK_LINE_RE = re.compile(r"^\s*\{src:\s*'([^']+)'.*\batSceneId:\s*" + _NUM)
ASSET_RE = re.compile(r"\b(?:src|audioSrc|photoSrc):\s*'([^']+)'")


def _num_field(line: str, name: str) -> re.Match | None:
    return re.search(r"\b" + name + r":\s*" + _NUM, line)


def _str_field(line: str, name: str) -> str | None:
    m = re.search(r"\b" + name + r":\s*'([^']*)'", line)
    return m.group(1) if m else None


def parse_scenes(text: str) -> list[dict[str, Any]]:
    """`{id: ...}` で始まる行をシーンとして解析する。

    返す各要素: id(float), id_str, line_no, raw(その行の原文。個別スクリプトが追加の項目を読むため),
    caption(str|None; 改行は '\\n' の2文字のまま),
    durationSeconds(float|None), dur_span(ファイル全体でのオフセット。durationSeconds の数値部分),
    fontSize(int|None), videoStartSeconds, playbackRate, src, audioSrc, photoSrc
    """
    scenes: list[dict[str, Any]] = []
    offset = 0
    for line_no, line in enumerate(text.splitlines(keepends=True), 1):
        m = SCENE_LINE_RE.match(line)
        if m:
            sc: dict[str, Any] = {"id": float(m.group(1)), "id_str": m.group(1), "line_no": line_no,
                                  "raw": line.rstrip("\n")}
            sc["caption"] = _str_field(line, "caption")
            dm = _num_field(line, "durationSeconds")
            sc["durationSeconds"] = float(dm.group(1)) if dm else None
            sc["dur_span"] = (offset + dm.start(1), offset + dm.end(1)) if dm else None
            fm = _num_field(line, "fontSize")
            sc["fontSize"] = int(float(fm.group(1))) if fm else None
            for name in ("videoStartSeconds", "playbackRate"):
                nm = _num_field(line, name)
                sc[name] = float(nm.group(1)) if nm else None
            for name in ("src", "audioSrc", "photoSrc"):
                sc[name] = _str_field(line, name)
            scenes.append(sc)
        offset += len(line)
    return scenes


def parse_tracks(text: str) -> list[dict[str, Any]]:
    """`{src: 'audio/...', startSeconds: 0, durationSeconds: 5.2, atSceneId: 1}` 行を解析する。"""
    tracks: list[dict[str, Any]] = []
    for line_no, line in enumerate(text.splitlines(), 1):
        m = TRACK_LINE_RE.match(line)
        if not m:
            continue
        sm = _num_field(line, "startSeconds")
        dm = _num_field(line, "durationSeconds")
        tracks.append({
            "src": m.group(1),
            "startSeconds": float(sm.group(1)) if sm else 0.0,
            "durationSeconds": float(dm.group(1)) if dm else None,
            "atSceneId": float(m.group(2)),
            "line_no": line_no,
        })
    return tracks


def caption_rows(caption: str) -> list[str]:
    """caption 文字列を行に分割する（ソース上の '\\n' 2文字を改行として扱う）。"""
    return caption.replace("\\n", "\n").split("\n")
