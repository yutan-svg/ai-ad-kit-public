#!/usr/bin/env python3
"""whisper-cli による文字起こしと、ASR結果の正規化・編集距離・読み方の辞書の適用。各スクリプト共通のモジュール。

- transcribe(): 全文テキスト（タイムスタンプなし）
- build_engines(): 検品に使う音声認識エンジンの組み立て（whisper / Gemini。合議は最大2つ）
- transcribe_tokens(): トークンごとの終了時刻（align_captions.py 用）
- norm(): 句読点除去 → 読み方の辞書の reading / asr_variants で表記ゆれを読みに寄せる → カタカナをひらがなに統一
- window_err(): 期待テキストと同じ長さの窓で測る最小編集距離率（前後のゴミに影響されにくい）
- load_pronunciation_dict(): キット標準の辞書に、案件ごとの追加辞書を重ねて読む
- apply_pronunciation_dict(): 台本に仮名置換を適用し、プロンプトに添える発音ガイドを返す
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

PUNCT_RE = re.compile(r"[、。「」！？!?\s・,\.…]")


def which_whisper() -> str:
    for name in ("whisper-cli", "whisper-cpp"):
        path = shutil.which(name)
        if path:
            return path
    raise SystemExit(
        "whisper-cli が見つかりません。音声認識の検品にはこれが要ります。\n"
        "  macOS: brew install whisper-cpp ffmpeg\n"
        "  モデル: mkdir -p .whisper-models && curl -L -o .whisper-models/ggml-large-v3-turbo.bin \\\n"
        "    https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo.bin"
    )


def run(cmd: list[str], **kw: Any) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def probe_duration(path: str | Path) -> float:
    r = run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)])
    return float(r.stdout.strip()) if r.stdout.strip() else 0.0


def to_wav16k(src: str | Path, wav: str | Path) -> Path:
    r = run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-vn", "-ac", "1", "-ar", "16000", str(wav)])
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg 失敗 ({src}): {r.stderr.strip()[-400:]}")
    return Path(wav)


def transcribe_wav(wav: str | Path, model: str | Path, language: str = "ja") -> str:
    """16kHz mono wav を全文文字起こしする（改行なしの1行）。"""
    r = run([which_whisper(), "-m", str(model), "-l", language, "-nt", "-np", str(wav)])
    if r.returncode != 0:
        raise RuntimeError(f"whisper-cli 失敗 (model={model}): {r.stderr.strip()[-400:]}")
    return r.stdout.strip().replace("\n", "")


def transcribe(path: str | Path, model: str | Path, language: str = "ja") -> str:
    """任意の音声/動画ファイルを全文文字起こしする。"""
    with tempfile.TemporaryDirectory() as td:
        wav = to_wav16k(path, Path(td) / "a.wav")
        return transcribe_wav(wav, model, language)


def transcribe_tokens(path: str | Path, model: str | Path, language: str = "ja") -> list[tuple[str, float]]:
    """whisper-cli のトークン列 [(text, end_sec)] を返す（-ojf の JSON から）。"""
    with tempfile.TemporaryDirectory() as td:
        wav = to_wav16k(path, Path(td) / "a.wav")
        out = Path(td) / "a"
        r = run([which_whisper(), "-m", str(model), "-l", language, "-ojf", "-of", str(out), "-np", str(wav)])
        json_path = out.with_suffix(".json")
        if r.returncode != 0 or not json_path.exists():
            raise RuntimeError(f"whisper-cli 失敗 (model={model}): {r.stderr.strip()[-400:]}")
        data = json.loads(json_path.read_text(encoding="utf-8", errors="replace"))
    toks: list[tuple[str, float]] = []
    for seg in data.get("transcription", []):
        for tk in seg.get("tokens", []):
            txt = tk.get("text", "")
            if txt.startswith("[_") or not txt.strip():
                continue
            toks.append((txt, tk["offsets"]["to"] / 1000.0))
    return toks


# ---------------------------------------------------------------------------
# 検品エンジン（whisper か Gemini。2つ並べて合議にする）
# ---------------------------------------------------------------------------
class Engine:
    """文字起こしをする1つのエンジン。`kind` は "whisper" か "gemini"。

    whisper は手元で動く（無料・鍵不要・モデルのダウンロードが要る）。
    Gemini は Google のサーバで動く（鍵が要る・わずかに費用がかかる・ダウンロード不要）。
    """

    def __init__(self, kind: str, name: str, model: Any):
        self.kind = kind
        self.name = name
        self.model = model

    def transcribe(self, wav: str | Path, language: str = "ja") -> str:
        if self.kind == "whisper":
            return transcribe_wav(wav, self.model, language)
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).resolve().parent))
        import _google  # noqa: PLC0415 - 鍵が要るので、使うときだけ読み込む
        return _google.transcribe(Path(wav), str(self.model))

    def __str__(self) -> str:  # 表示用
        return self.name


def build_engines(cfg: dict[str, Any], resolve_fn, warn=None) -> list[Engine]:
    """設定から検品エンジンを組み立てる。

    ai-ad.config.json の項目:
      "asrEngine":  "whisper" | "gemini"   … 1つ目のエンジン（既定 whisper）
      "asrEngine2": "whisper" | "gemini" | "none"  … 2つ目（既定 whisper。none で1エンジン）
      "geminiAsrModel": "gemini-3.5-flash" … Gemini を使うときのモデル名

    選べる組み合わせは3つです:
      whisper 2本   … 既定。手元だけで完結する（鍵も費用も要らない）
      whisper＋gemini … 手元のモデル1つと Google。癖の違うエンジンを突き合わせられる
      gemini のみ    … whisper を入れずに検品する（Google 製品だけで完結させたいとき。asrEngine2 は "none"）
    """
    from _config import whisper_model  # 遅延 import（_config は _asr を読まない）

    say = warn or (lambda _m: None)
    gemini_model = str(cfg.get("geminiAsrModel") or "gemini-3.5-flash")

    def make(kind: str, key: str, required: bool) -> Engine | None:
        if kind == "gemini":
            return Engine("gemini", f"gemini:{gemini_model}", gemini_model)
        if kind != "whisper":
            raise SystemExit(
                f'ai-ad.config.json の音声認識エンジンの指定が読めません: "{kind}"\n'
                '  使えるのは "whisper" / "gemini"（2つ目だけ "none" も可）です')
        path = whisper_model(cfg, key, required=required)
        return Engine("whisper", Path(path).stem, path) if path else None

    first = str(cfg.get("asrEngine") or "whisper").lower()
    second = str(cfg.get("asrEngine2") or "whisper").lower()
    engines: list[Engine] = [make(first, "whisperModel", True)]  # type: ignore[list-item]
    if second in ("none", "no", "off", ""):
        pass
    elif second == first == "gemini":
        say("NOTE asrEngine と asrEngine2 が同じ Gemini なので、2つ目は使いません"
            "（同じエンジンを2回呼んでも合議になりません）")
    else:
        e2 = make(second, "whisperModel2", False)
        if e2 is None:
            say("NOTE whisperModel2 が無いので1エンジンで判定します")
        else:
            engines.append(e2)
    return engines


# ---------------------------------------------------------------------------
# 正規化・編集距離
# ---------------------------------------------------------------------------
def kata_to_hira(s: str) -> str:
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in s)


EMPTY_DICT: dict[str, Any] = {"entries": [], "standard_clauses": [], "asr_variants": {}}


def _read_dict(path: str | Path | None) -> dict[str, Any]:
    if not path or not Path(path).exists():
        return dict(EMPTY_DICT)
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_pronunciation_dict(path: str | Path | None, extra: str | Path | None = None) -> dict[str, Any]:
    """読み方の辞書を読む。extra（案件ごとの追加辞書）があれば重ねる。

    同じ surface があれば extra 側が勝つ。standard_clauses は重複を除いて連結し、
    asr_variants は extra 側で上書きする。どちらのファイルも無ければ空の辞書を返す。
    こうしておくと、キットを新版に差し替えて scripts/ が入れ替わっても案件の語は残る。
    """
    base = _read_dict(path)
    if not extra or not Path(extra).exists():
        return base
    add = _read_dict(extra)
    merged: dict[str, Any] = dict(base)
    by_surface = {e.get("surface"): e for e in base.get("entries", []) if e.get("surface")}
    for e in add.get("entries", []):
        if e.get("surface"):
            by_surface[e["surface"]] = e
    merged["entries"] = list(by_surface.values())
    clauses = list(base.get("standard_clauses", []))
    for c in add.get("standard_clauses", []):
        if c not in clauses:
            clauses.append(c)
    merged["standard_clauses"] = clauses
    variants = dict(base.get("asr_variants", {}))
    variants.update(add.get("asr_variants", {}))
    merged["asr_variants"] = variants
    return merged


def load_dicts_from_config(cfg: dict[str, Any], resolve_fn, warn=None) -> dict[str, Any]:
    """設定の pronunciationDict ＋ pronunciationDictExtra を解決して読む（各スクリプト共通）。

    相対パスは必ず案件フォルダ基準で解決する。生の設定値のまま渡すと、別のディレクトリから
    実行したときに黙って空の辞書になり、正規化なしで不一致判定が出る。
    """
    main = resolve_fn(cfg, cfg["pronunciationDict"]) if cfg.get("pronunciationDict") else None
    extra = resolve_fn(cfg, cfg["pronunciationDictExtra"]) if cfg.get("pronunciationDictExtra") else None
    if warn and main is not None and not Path(main).exists():
        warn(f"⚠ 読み方の辞書が読めません（表記ゆれの正規化なしで進めます）: {main}")
    return load_pronunciation_dict(main, extra)


def build_kana_map(pd: dict[str, Any]) -> dict[str, str]:
    """表記 → 読み の置換表（辞書の reading ＋ asr_variants）。長い表記から順に適用する。"""
    kana: dict[str, str] = {}
    for e in pd.get("entries", []):
        if e.get("reading"):
            kana[e["surface"]] = e["reading"]
            if e.get("replace"):
                kana[e["replace"]] = e["reading"]
    kana.update({k: v for k, v in pd.get("asr_variants", {}).items() if not k.startswith("_")})
    return kana


def norm(text: str, kana: dict[str, str] | None = None) -> str:
    t = text.replace("\\n", "").replace("�", "")
    t = PUNCT_RE.sub("", t)
    if kana:
        for k in sorted(kana, key=len, reverse=True):
            t = t.replace(k, kana[k])
    return kata_to_hira(t)


def lev(a: str, b: str) -> int:
    if len(a) > len(b):
        a, b = b, a
    prev = list(range(len(a) + 1))
    for i, cb in enumerate(b, 1):
        cur = [i]
        for j, ca in enumerate(a, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def window_err(expected: str, asr: str) -> float:
    """期待テキスト（正規化済み）に対する、ASR（正規化済み）の同長ウィンドウとの最小編集距離率。"""
    n = len(expected)
    if n == 0:
        return 0.0
    if len(asr) <= n:
        return lev(expected, asr) / n
    return min(lev(expected, asr[i:i + n]) for i in range(len(asr) - n + 1)) / n


def load_ng_words(path: str | Path | None) -> list[str]:
    if not path or not Path(path).exists():
        return []
    return [w.strip() for w in Path(path).read_text(encoding="utf-8").splitlines() if w.strip() and not w.startswith("#")]


def ng_hits(text: str, normalized: str, ng_words: list[str]) -> list[str]:
    return [w for w in ng_words if w in text or norm(w) in normalized]


def apply_pronunciation_dict(text: str, pd: dict[str, Any], max_notes: int = 2) -> tuple[str, list[str], list[str]]:
    """台本に読み方の辞書を適用する。

    返り値: (置換後の台本, プロンプトに添えるガイド（最大 max_notes 件）, 件数超過で落としたガイド)
    - replace が設定された語は仮名などに置換する（漢字だと音素が崩れる実績のある語）
    - 台本に含まれる語の guide を最大 max_notes 件まで添える（ガイドが多いほど逆に崩れる）
    """
    notes: list[str] = []
    for e in pd.get("entries", []):
        surface, rep = e.get("surface", ""), e.get("replace")
        if not surface or surface not in text:
            continue
        if rep:
            text = text.replace(surface, rep)
        if e.get("guide"):
            notes.append(e["guide"])
    return text, notes[:max_notes], notes[max_notes:]


# ---------------------------------------------------------------------------
# 発話区間（尺チェック用）
# ---------------------------------------------------------------------------
def speech_span(path: str | Path, noise: str = "-33dB", min_silence: float = 0.05) -> tuple[float, float]:
    """(クリップ尺, 最終発話の終了時刻) を silencedetect の実測で返す。

    末尾の無音は短くても拾いたいので d=0.05。無音が EOF まで続くと ffmpeg は silence_end を EOF 時刻で出す
    （出さない版もある）ため、両方を「末尾まで無音」とみなす。
    """
    dur = probe_duration(path)
    out = run(["ffmpeg", "-hide_banner", "-i", str(path), "-af",
               f"silencedetect=noise={noise}:d={min_silence}", "-f", "null", "-"]).stderr
    starts = [float(x) for x in re.findall(r"silence_start: (-?[0-9.]+)", out)]
    ends = [float(x) for x in re.findall(r"silence_end: (-?[0-9.]+)", out)]
    if starts and (len(ends) < len(starts) or ends[-1] >= dur - 0.05):
        return dur, max(0.0, starts[-1])
    return dur, dur
