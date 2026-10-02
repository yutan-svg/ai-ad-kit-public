#!/usr/bin/env python3
"""決まりを機械で止めるための共通部品（台帳・承諾の記録・危険語の判定）。

このモジュールを読む側は次の4つの門を使う:

| 門 | 記録の置き場所 | 止める場所 |
|---|---|---|
| 生成の承諾（何を・何本・どのサービスで） | out/generation-approval.json | generate_lines.py / generate_talking_head.py |
| テイク上限（同じ id は2回まで） | out/takes-ledger.json        | generate_lines.py / generate_talking_head.py |
| 耳での確認（危険語を人が聴く）   | out/ear-check.json           | preflight.py |
| 書き出しの承諾（何を書き出すか） | out/approval.json            | remotion.config.ts / approve.py --check |
| 聞き取りの記録（商材・相手・台本前の3つ） | knowledge/project.md      | build_research.py / generate_*.py / preflight.py / approve.py --check |

記録はすべて `out/` に置く（Git には入らない）。**人が手で書き換えてはいけません。**
耳の確認は、聴いた音声の中身のハッシュを記録に残し、preflight.py が照合します。
音声を差し替えれば記録は自動的に無効になります（聴き直しが必要になります）。
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _config import resolve  # noqa: E402

# 同じ id に許す生成回数。これを超える回（＝3回目）は拒否する。
MAX_TAKES_PER_ID = 2

TAKES_LEDGER = "out/takes-ledger.json"
GENERATION_APPROVAL = "out/generation-approval.json"
EAR_CHECK = "out/ear-check.json"
RENDER_APPROVAL = "out/approval.json"
PREFLIGHT_OK = "out/preflight-ok.json"


def scenes_digest(cfg: dict[str, Any]) -> str:
    """src/scenes.ts の中身のハッシュ。preflight 合格の記録がどの版に対するものかを固定する。"""
    from _config import scene_files  # noqa: E402
    h = hashlib.sha1()
    for f in scene_files(cfg):
        h.update(f.read_bytes())
    return h.hexdigest()


def check_preflight_passed(cfg: dict[str, Any]) -> None:
    """preflight が今の scenes.ts で合格していなければ、書き出しの承諾も書き出しも止める。
    実際に、耳の確認の記録が無いまま mp4 が書き出されたことがあった（preflight を通さずに承諾→render）。"""
    stamp = resolve(cfg, PREFLIGHT_OK)
    data = read_json(stamp, {}) if stamp.exists() else {}
    if not data or data.get("scenes_sha1") != scenes_digest(cfg) or data.get("skip_audio"):
        raise SystemExit(
            "✗ preflight の合格記録がありません（無い・古い・--skip-audio 付き）。書き出しの前に\n"
            "    python3 scripts/preflight.py\n"
            "  を通してください。耳の確認・音の出所・指摘台帳・テロップ幅はここで止まります")


def check_project(cfg: dict[str, Any], stage: str) -> None:
    """聞き取りの記録が埋まっていなければ止める（check_project.py を呼ぶ）。"""
    import check_project  # noqa: E402
    root = resolve(cfg, ".")
    if check_project.check(root, stage, quiet=True) != 0:
        raise SystemExit(2)


def now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def now_epoch() -> float:
    return time.time()


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{path}: JSON として読めません（手で書き換えていませんか）: {exc}")


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha1_of(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# テイク台帳（同じ id を何回生成したか）
# ---------------------------------------------------------------------------
def ledger_path(cfg: dict[str, Any]) -> Path:
    return resolve(cfg, TAKES_LEDGER)


def load_ledger(cfg: dict[str, Any]) -> dict[str, Any]:
    data = read_json(ledger_path(cfg), {})
    return data if isinstance(data, dict) else {}


def take_count(cfg: dict[str, Any], line_id: str) -> int:
    rec = load_ledger(cfg).get(line_id) or {}
    return int(rec.get("count", 0))


def check_take_limit(cfg: dict[str, Any], line_ids: list[str], new_takes: int,
                     force_reason: str | None) -> None:
    """同じ id への生成が上限を超えるなら止める。--force には理由の文字列が要る。"""
    ledger = load_ledger(cfg)
    over: list[str] = []
    for line_id in line_ids:
        done = int((ledger.get(line_id) or {}).get("count", 0))
        if done + new_takes > MAX_TAKES_PER_ID:
            over.append(f"{line_id}: すでに{done}回 + 今回{new_takes}本 = {done + new_takes}回目")
    if not over:
        return
    if force_reason:
        print("⚠ テイク上限を --force で越えます（台帳に理由を残します）")
        for line in over:
            print("   " + line)
        print(f"   理由: {force_reason}")
        return
    raise SystemExit(
        "✗ テイク上限（同じセリフは2回まで）に達しています。3回目は生成しません。\n"
        + "\n".join("   " + line for line in over)
        + "\n\n  同じ語で2回失敗したら、3回目を投げる前に原因を直します（RULES.md 決まり17）:\n"
          "    1. 読み方の辞書に、実際の誤読を `never 〜` として足す（knowledge/pronunciation.json）\n"
          "    2. 台本の表記を変える（かなで失敗したら漢字、漢字で失敗したらかな）\n"
          "    3. 一息の短文に割り直す／言い換える／画面の文字にする\n"
          "  直したうえでどうしても投げる必要があるなら、理由を書いて再実行してください:\n"
          '    --force "辞書に never を足し、表記をかなに変えたうえでの再試行"\n'
        + f"  台帳: {TAKES_LEDGER}"
    )


def record_take(cfg: dict[str, Any], line_id: str, take: int | str, tool: str,
                text: str = "", forced_reason: str | None = None,
                no_reference_reason: str | None = None) -> None:
    """生成を1本投げたことを台帳に足す（成否によらず、投げた時点で数える）。"""
    path = ledger_path(cfg)
    ledger = load_ledger(cfg)
    rec = ledger.setdefault(line_id, {"count": 0, "entries": []})
    rec["count"] = int(rec.get("count", 0)) + 1
    rec.setdefault("entries", []).append({
        "at": now(), "take": take, "tool": tool, "text": text[:80],
        **({"forced_reason": forced_reason} if forced_reason else {}),
        **({"no_reference_reason": no_reference_reason} if no_reference_reason else {}),
    })
    write_json(path, ledger)


# ---------------------------------------------------------------------------
# 生成の承諾（何を・何本・どのサービスで作るかを伝えて y/N を取った記録）
# ---------------------------------------------------------------------------
def generation_approval_path(cfg: dict[str, Any]) -> Path:
    return resolve(cfg, GENERATION_APPROVAL)


def check_generation_approval(cfg: dict[str, Any], line_ids: list[str], takes: int,
                              spec_path: Path | None = None) -> dict[str, Any]:
    """out/generation-approval.json に、いま投げる内容の承諾が残っているか確かめる。"""
    path = generation_approval_path(cfg)
    how = ("  承諾の取り方（何を・何本・どのサービスで作るかを伝えて、依頼主に y/N で答えてもらう）:\n"
           f"    python3 scripts/approve.py --generation --ids {','.join(line_ids) or '<id>'} "
           f"--takes {takes} --service <サービス名>\n")
    if not path.exists():
        raise SystemExit(
            "✗ 生成の承諾の記録がありません（費用のかかる生成は、先に何を・何本・どのサービスで作るかを伝えて承諾を得ます）。\n" + how)
    rec = read_json(path, {})
    approved = [str(x) for x in rec.get("ids", [])]
    missing = [i for i in line_ids if i not in approved]
    if missing:
        raise SystemExit(
            f"✗ 承諾の記録に無いセリフがあります: {', '.join(missing)}\n"
            f"  承諾済み: {', '.join(approved) or '（なし）'}\n" + how)
    if takes > int(rec.get("takes", 0)):
        raise SystemExit(
            f"✗ 承諾は1セリフ {rec.get('takes')} テイクまでです（今回は {takes} テイク）。\n" + how)
    if spec_path and spec_path.exists() and float(rec.get("at_epoch", 0)) < spec_path.stat().st_mtime:
        raise SystemExit(
            f"✗ 承諾のあとで {spec_path.name} が更新されています（別の内容になっています）。\n"
            "  作るものが変われば別の承諾が要ります。もう一度内容を伝えて承諾を取ってください。\n" + how)
    return rec


# ---------------------------------------------------------------------------
# 危険語（数字・固有名詞・辞書登録語）
# ---------------------------------------------------------------------------
_DIGIT_RE = re.compile(r"[0-9０-９]+")
_KANJI_NUM_RE = re.compile(
    r"[一二三四五六七八九〇十百千万億兆]+(?=[つ本人円年月日時分秒回割倍個件枚社名歳％%])")
_KATAKANA_RE = re.compile(r"[ァ-ヴー]{4,}")
_ALPHA_RE = re.compile(r"[A-Za-zＡ-Ｚａ-ｚ]{2,}")


def danger_words(text: str, pd: dict[str, Any] | None = None,
                 extra: list[str] | None = None, ignore: list[str] | None = None) -> list[str]:
    """耳で確かめるべき語を拾う。

    ①数字（算用数字・単位のついた漢数字）②読み方の辞書に登録された語
    ③案件の固有名詞（config の earCheckWords）④カタカナ4文字以上・アルファベット2文字以上
    （固有名詞の候補）。安全と分かった語は config の earCheckIgnore に足せば外れる。
    """
    plain = text.replace("\\n", "")
    found: list[str] = []
    for rx in (_DIGIT_RE, _KANJI_NUM_RE, _KATAKANA_RE, _ALPHA_RE):
        found += rx.findall(plain)
    for entry in (pd or {}).get("entries", []):
        surface = entry.get("surface")
        if surface and surface in plain:
            found.append(surface)
    for word in extra or []:
        if word and word in plain:
            found.append(word)
    drop = set(ignore or [])
    out: list[str] = []
    for w in found:
        if w and w not in drop and w not in out:
            out.append(w)
    return out


def ear_check_words_config(cfg: dict[str, Any]) -> tuple[list[str], list[str]]:
    """config の earCheckWords / earCheckIgnore を読む（どちらも省略可）。"""
    words = [str(w) for w in (cfg.get("earCheckWords") or [])]
    ignore = [str(w) for w in (cfg.get("earCheckIgnore") or [])]
    return words, ignore


# ---------------------------------------------------------------------------
# 耳での確認の記録
# ---------------------------------------------------------------------------
def ear_check_path(cfg: dict[str, Any]) -> Path:
    return resolve(cfg, EAR_CHECK)


def load_ear_checks(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    data = read_json(ear_check_path(cfg), [])
    return data if isinstance(data, list) else []


def ear_check_for(cfg: dict[str, Any], keys: list[str]) -> dict[str, Any] | None:
    """keys（シーンID・音声ファイルの名前など）のどれかに一致する記録を返す。"""
    for rec in load_ear_checks(cfg):
        if str(rec.get("id")) in [str(k) for k in keys] and rec.get("listened_by_human") is True:
            return rec
    return None
