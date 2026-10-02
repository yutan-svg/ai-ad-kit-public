#!/usr/bin/env python3
"""広告リサーチの JSON を、1ファイルの HTML にまとめる（手元のブラウザで見るための資料）。

何に使うか: `ad-research` スキルが集めた一次情報と、その分析・導線設計を、
目次つき・表つき・出典つきの HTML にします。
**このスクリプトは調べません。** 渡された JSON をそのまま形にし、書式の矛盾だけを落とします。
中身の正しさは `research-verifier`（サブエージェント）が、引用された URL を自分で開き直して判定します。

使い方（案件フォルダのルートで）:
  python3 scripts/build_research.py <入力.json>                 # out/research/<日付>_<商材>.html を作る
  python3 scripts/build_research.py <入力.json> --open           # 作ってブラウザで開く（macOS）
  python3 scripts/build_research.py <入力.json> --out <保存先>   # 保存先を自分で決める
  python3 scripts/build_research.py --print-schema               # 入力 JSON の書式を表示する

画面の写しは、HTML と同じ場所の `img/` に置き、JSON には `"shot": "img/<名前>.png"` と書きます
（HTML からの相対パスです。ファイルが無ければ、その場に「写しがありません」と赤字で出ます）。

--------------------------------------------------------------------------------
資料の並び（質問の3段）
--------------------------------------------------------------------------------
節の順序は固定です。**ファクト → 課題と選択肢 → 意思決定の材料**の順に並びます。

  1 ファクト（競合と媒体別の実物）      ─┬ ファクト
  2 3C・競争の型・非市場の制約           ─┘
  3 ターゲットと視聴シーン               ─┬ 課題と選択肢
  4 導線設計（媒体別・着地3案）           │
  5 訴求の選択肢（冒頭・ボディ・CTA）     ─┘
  6 まず試す1本と、捨てた案              ── 意思決定の材料
  7 出典と確認状況
  8 検証

中身の無い節は出ません（8 は必ず出ます）。**分からないことを埋めないでください。**

--------------------------------------------------------------------------------
確かめ方の印（mark）
--------------------------------------------------------------------------------
  direct    → [直接確認]  自分でその URL を開いて、画面で見た事実
  summary   → [要約のみ]  検索結果の要約や第三者の記事で読んだだけ
  unknown   → [未確認]    開けなかった・確かめられなかった
  inference → [推論]      事実から考えたこと（事実ではない）

**`direct` は、`sources` 側の `opened` も `direct` でないと通りません**（このスクリプトが落とします）。
「業界を調べた」と言いながら実際には検索の要約しか見ていない、という事故を防ぐための門です。
分析の節（2 の判定・4・5・6）で `mark` を省くと、自動で [推論] が付きます。
**事実の印を推論に付けないでください。** `research-verifier` がそこを見ます。

--------------------------------------------------------------------------------
入力 JSON の書式
--------------------------------------------------------------------------------
どの項目も**省けます**。共通の並びは次の2つです。

  「印つきの一言」  {"label": "…", "value": "…", "mark": "direct", "src": ["s1"]}
  「印つきの表の行」 {"cells": [...], "mark": "direct", "src": ["s1"], "shot": "img/x.png"}

  {
    "meta": {
      "title": "（架空）…のリサーチ", "subtitle": "…", "product": "…",
      "date": "2026-09-19", "prepared_for": "… ご担当者",
      "route": "内蔵ブラウザで直接開いた",   # 一次情報をどの経路で開いたか
      "lead": "冒頭の青い囲み", "footer": "末尾の断り書き"
    },

    "summary": ["先に結論を3〜6行", "…"],      # 目次の前に出ます

    # ---- 1 ファクト -------------------------------------------------------
    "scope": { "asked": "依頼の内容", "method": ["調べ方", "…"],
               "limits": ["開けなかったもの・分からなかったこと", "…"] },

    "companies": [
      { "id": "c1", "name": "（架空）A社 …", "kind": "自社",   # kind は "自社" か "競合"
        "one_line": "ひとことで言うと何か", "url": "https://…",
        "scale": [ {"label": "従業員数", "value": "約40名", "mark": "direct", "src": ["s1"]} ] }
    ],

    "media": [                                  # 媒体別の実物
      { "key": "search", "title": "検索広告（見出し・説明文）", "lead": "…",
        "columns": ["会社", "見出し", "説明文", "気づいたこと"],
        "rows": [ {"cells": ["A社", "…", "…", "…"], "mark": "direct",
                   "src": ["s2"], "shot": "img/a-search.png", "shot_caption": "…"} ],
        "notes": ["表の下に足す1行"] }
    ],
      # よく使う key: search / banner（画像バナー）/ video（動画）/ lp
      # 動画の列は「会社・尺・冒頭3秒・語り手・テロップ・CTA」、
      # LP の列は「会社・第一画面・オファー・証拠」を基本にします。

    "diff": { "columns": ["観点", "貴社", "A社"], "rows": [ … ],
              "same": ["同じところ"], "different": ["違うところ"] },

    # ---- 2 3C・競争の型・非市場の制約 -------------------------------------
    "nonmarket": [                              # 先に置く。表現の可否はここで決まる
      { "layer": "媒体の審査", "limit": "何が禁じられているか",
        "effect": "この案件の訴求への影響", "mark": "direct", "src": ["s9"] }
    ],
      # layer の例: 全業種の法令 / 業種の法令・ガイドライン / 媒体の審査 / 取引先のルール

    "three_c": {                                # 各項目は「印つきの一言」
      "customer":   [ {"label": "誰が", "value": "…", "mark": "direct", "src": ["s1"]},
                      {"label": "何に困っているか", "value": "…"},
                      {"label": "どう探しているか", "value": "検索需要は小さい。紹介で知る", "mark": "direct", "src": ["s8"]} ],
      "competitor": [ {"label": "規模感", "value": "…"}, {"label": "訴求", "value": "…"},
                      {"label": "媒体", "value": "…"}, {"label": "LP とオファー", "value": "…"} ],
      "company":    [ {"label": "提供価値", "value": "…"}, {"label": "証拠", "value": "…"},
                      {"label": "弱み", "value": "…"} ]
    },

    "competition": {                            # 競争の型。広告の訴求はこれに従う
      "chosen": "IO型（差別化で競争を避ける）",
      "why": "そう判断した理由",
      "options": [ {"type": "IO型（差別化で競争を避ける）", "fit": "◎ 主", "note": "…"},
                   {"type": "チェンバレン型（リソースで勝つ）", "fit": "△", "note": "…"},
                   {"type": "シュンペーター型（知と知の結合）", "fit": "×", "note": "…"} ],
      "implication": "だから広告では何を言うのか（1〜2行）"
    },

    "five_forces": [                            # 3行以内。代替品と買い手の価格感度を必ず入れる
      { "force": "代替品", "level": "高", "note": "…" },
      { "force": "買い手の価格感度", "level": "中", "note": "…" }
    ],

    "vrio": [                                   # 自社の強みのうち「広告で証明できるもの」だけ
      { "strength": "…", "value": "○", "rare": "○", "hard": "△", "org": "○",
        "proof": "広告のどの画で証明できるか", "mark": "direct", "src": ["s1"] }
    ],

    # ---- 3 ターゲットと視聴シーン ------------------------------------------
    "targets": [
      { "name": "…な人", "situation": "いまの状況・困りごと",
        "scenes": [ {"media": "Meta リール", "when": "夜、寝る前に片手で",
                     "mood": "受け身。音は消している", "mark": "inference"} ] }
    ],

    "emotion": [                                # 気づき→関心→不安→納得→行動
      { "stage": "気づき", "state": "心の状態", "trigger": "それを起こすもの", "risk": "ここで落ちる理由" }
    ],

    # ---- 4 導線設計 --------------------------------------------------------
    "funnels": [                                # 媒体ごとに1本の導線を描く
      { "media": "Meta リール",
        "scene": "どんな場面で見るか", "emotion": "その媒体での感情の動き",
        "video": { "length": "15〜20秒", "open": "冒頭（3秒）", "body": "ボディ", "cta": "CTA" },
        "landing": "着地（どの案を前提にするか）", "cv": "何をもって成果とするか",
        "measure": "何で測るか", "mark": "inference", "src": [] }
    ],

    "landings": [                               # 着地は3案を必ず並べる（A・B・C）
      { "key": "A", "title": "現状の LP のまま（動画を LP に合わせる）",
        "what": "具体的に何をするか",
        "hope": "期待（効く理由）", "risk": "懸念（外す理由・規制・工数）",
        "effect_on_video": "動画の作り方への影響（尺・訴求・CTA 文言）" },
      { "key": "B", "title": "LP を少し直す",
        "what": "直す箇所を具体的に（第一画面・オファー・証拠・フォームのどれか）", … },
      { "key": "C", "title": "診断フォームや簡易 LP を新設", "what": "…", … }
    ],

    # ---- 5 訴求の選択肢 ----------------------------------------------------
    "appeals": {                                # 期待と懸念を必ず対で書く
      "冒頭":   [ {"label": "…型", "copy": "画面に出す言葉の例",
                   "hope": "効く理由", "risk": "外す理由・規制上の注意"} ],
      "ボディ": [ … ], "CTA": [ … ]
    },

    # ---- 6 まず試す1本 -----------------------------------------------------
    "recommendation": {
      "pick": "まず試す1本（1行で）",
      "spec": [ {"label": "媒体", "value": "…"}, {"label": "尺", "value": "…"},
                {"label": "着地", "value": "B案"}, {"label": "成果", "value": "…"} ],
      "why": ["そう薦める理由", "…"],
      "judge": ["何をもって良し悪しを決めるか", "…"],
      "dropped": [ {"option": "捨てた案", "why": "捨てた理由"} ]
    },

    # ---- 7 出典 ------------------------------------------------------------
    "sources": [
      { "id": "s1", "label": "A社 LP", "url": "https://…",
        "opened": "direct",              # direct / summary / unknown
        "checked_on": "2026-09-19", "shot": "img/s1.png", "note": "…" }
    ],

    # ---- 8 検証（research-verifier の判定を貼る。最後に足す）----------------
    "verification": {
      "verified_at": "2026-09-19", "by": "research-verifier",
      "rows": [ {"claim": "本文のどの主張か", "src": "s1",
                 "result": "一致",       # 一致 / 不一致 / 出典に記載なし / 開けない
                 "note": "根拠"} ],
      "summary": "合格N件 / 要修正M件", "passed": true
    }
  }
"""
from __future__ import annotations

import argparse
import html
import json
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = Path(__file__).resolve().parent / "templates" / "research.html"

MARKS = {
    "direct": ("mk-d", "直接確認"),
    "summary": ("mk-s", "要約のみ"),
    "unknown": ("mk-u", "未確認"),
    "inference": ("mk-i", "推論"),
}
OPENED = {
    "direct": ("mk-d", "自分で開いた"),
    "summary": ("mk-s", "要約のみ"),
    "unknown": ("mk-u", "開けなかった"),
}
RESULTS = {"一致": "mk-d", "不一致": "mk-u", "出典に記載なし": "mk-u", "開けない": "mk-s"}
LANDING_KEYS = ("A", "B", "C")

errors: list[str] = []
warnings: list[str] = []


# ---------------------------------------------------------------- 小さな部品

def esc(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def lines(value) -> str:
    """改行を <br> にする（表の中で使う）。"""
    return esc(value).replace("\n", "<br>")


def mark_badge(mark: str | None, where: str, default: str | None = None) -> str:
    mark = mark or default
    if not mark:
        return ""
    if mark not in MARKS:
        errors.append(f"{where}: mark は direct / summary / unknown / inference のどれかです（{mark!r} でした）")
        return ""
    cls, label = MARKS[mark]
    return f'<span class="mk {cls}">{label}</span>'


def src_links(ids, sources: dict, where: str, mark: str | None = None) -> str:
    ids = ids or []
    if isinstance(ids, str):
        ids = [ids]
    if mark == "direct" and not ids:
        errors.append(f"{where}: [直接確認] と書くなら、どの出典を開いたかを src に書いてください")
    out = []
    for sid in ids:
        s = sources.get(sid)
        if not s:
            errors.append(f"{where}: 出典 {sid!r} が sources にありません")
            continue
        if mark == "direct" and s.get("opened") != "direct":
            errors.append(
                f"{where}: [直接確認] なのに、出典 {sid!r}（{s.get('label', '')}）の opened が "
                f"{s.get('opened')!r} です。自分で開いていないなら summary か unknown にしてください"
            )
        if mark == "inference" and s.get("opened") == "direct":
            pass  # 推論の根拠に一次情報を挙げるのは正しい
        label = esc(s.get("label") or sid)
        if s.get("url"):
            out.append(f'<a href="{esc(s["url"])}" target="_blank" rel="noreferrer">{label}</a>')
        else:
            out.append(label)
    return '<span class="src">出典: ' + " / ".join(out) + "</span>" if out else ""


def proof(row: dict, sources: dict, where: str, default: str | None = None) -> str:
    """確かめ方の印と出典を1つの塊にする。"""
    mark = row.get("mark") or default
    out = mark_badge(mark, where, default)
    link = src_links(row.get("src"), sources, where, mark)
    if link:
        out += ("<br>" if out else "") + link
    return out


def shot_html(path, caption: str, out_dir: Path, where: str) -> str:
    if not path:
        return ""
    if not (out_dir / path).exists():
        warnings.append(f"{where}: 画面の写し {path} が {out_dir / path} にありません")
        return f'<div class="shot miss">画面の写しがありません（{esc(path)}）</div>'
    cap = f'<div class="cap">{lines(caption)}</div>' if caption else ""
    return f'<div class="shot"><img src="{esc(path)}" alt="{esc(caption or path)}">{cap}</div>'


def table(columns, rows, sources: dict, out_dir: Path, where: str, default_mark: str | None = None) -> str:
    """columns（見出しの配列）と rows（{cells, mark, src, shot} の配列）から表を作る。"""
    if not columns or not rows:
        return ""
    head = "".join(f"<th>{lines(c)}</th>" for c in columns) + "<th>確かめ方</th>"
    body = []
    for i, row in enumerate(rows):
        spot = f"{where} の {i + 1} 行目"
        cells = row.get("cells") or []
        if len(cells) != len(columns):
            errors.append(f"{spot}: 列が {len(columns)} なのに、中身が {len(cells)} 個です")
        tds = []
        for j, cell in enumerate(cells):
            label = esc(columns[j]) if j < len(columns) else ""
            klass = ' class="nm"' if j == 0 else ""
            tds.append(f'<td{klass} data-l="{label}">{lines(cell)}</td>')
        shot = shot_html(row.get("shot"), row.get("shot_caption", ""), out_dir, spot)
        tds.append(f'<td data-l="確かめ方">{proof(row, sources, spot, default_mark)}{shot}</td>')
        body.append("<tr>" + "".join(tds) + "</tr>")
    return (f'<table class="t-card"><thead><tr>{head}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table>')


def item_table(items, sources: dict, out_dir: Path, where: str,
               head=("項目", "分かったこと"), default_mark: str | None = None) -> str:
    """「印つきの一言」（label / value / mark / src）の配列を表にする。"""
    rows = [{"cells": [i.get("label"), i.get("value")], "mark": i.get("mark"),
             "src": i.get("src"), "shot": i.get("shot")} for i in items or []]
    return table(list(head), rows, sources, out_dir, where, default_mark)


def kv(pairs) -> str:
    """印の要らない、ただの対の表。"""
    rows = "".join(f'<tr><th>{lines(p.get("label"))}</th>'
                   f'<td data-l="{esc(p.get("label"))}">{lines(p.get("value"))}</td></tr>'
                   for p in pairs or [])
    return f'<table class="kv"><tbody>{rows}</tbody></table>' if rows else ""


def bullets(items) -> str:
    items = items or []
    if not items:
        return ""
    return "<ul>" + "".join(f"<li>{lines(i)}</li>" for i in items) + "</ul>"


def h3(text: str) -> str:
    return f"<h3>{esc(text)}</h3>"


# ---------------------------------------------------------------- 節の組み立て

def sec(sid: str, num: int, title: str, lead: str, body: str) -> str:
    sub = f'<div class="sub-l">{lines(lead)}</div>' if lead else ""
    return (f'<section id="{sid}">\n'
            f'<h2><span><span class="num">{num}.</span>{esc(title)}</span>'
            f'<a class="up" href="#top">先頭へ</a></h2>\n{sub}\n{body}\n</section>')


LEGEND = ('<div class="legend">'
          '<div><span class="mk mk-d">直接確認</span>その URL を自分で開いて画面で見た</div>'
          '<div><span class="mk mk-s">要約のみ</span>検索結果の要約や第三者の記事で読んだ</div>'
          '<div><span class="mk mk-u">未確認</span>開けなかった・確かめられなかった</div>'
          '<div><span class="mk mk-i">推論</span>事実から考えたこと（事実ではない）</div>'
          "</div>")

STEPS = ('<div class="steps">'
         '<i><b>1. ファクト</b><span>一次情報で確認したこと（1〜2節）</span></i>'
         '<i><b>2. 課題と選択肢</b><span>誰に・どこで・何を言うか（3〜5節）</span></i>'
         '<i><b>3. 意思決定の材料</b><span>まず試す1本と、捨てた案（6節）</span></i>'
         "</div>")


def build_fact(data, sources, out_dir) -> str:
    body = ""
    scope = data.get("scope") or {}
    if scope.get("asked") or scope.get("method") or scope.get("limits"):
        body += h3("調査の範囲と限界")
        if scope.get("asked"):
            body += f"<p>{lines(scope['asked'])}</p>"
        if scope.get("method"):
            body += "<h4>調べ方</h4>" + bullets(scope["method"])
        if scope.get("limits"):
            body += ('<h4>調べられなかったこと</h4>'
                     '<div class="note warn"><span class="t">未確認</span>'
                     + bullets(scope["limits"]) + "</div>")

    companies = data.get("companies") or []
    if companies:
        body += h3("各社と規模感")
        for c in companies:
            where = f"companies[{esc(c.get('id') or c.get('name'))}]"
            head = f'<h4>{esc(c.get("name"))}'
            if c.get("kind"):
                head += f'　<span class="mk mk-i">{esc(c["kind"])}</span>'
            body += head + "</h4>"
            if c.get("one_line"):
                body += f"<p>{lines(c['one_line'])}</p>"
            if c.get("url"):
                body += f'<p><a href="{esc(c["url"])}" target="_blank" rel="noreferrer">{esc(c["url"])}</a></p>'
            body += item_table(c.get("scale"), sources, out_dir, where)

    media = data.get("media") or []
    if media:
        body += h3("媒体別の実物")
        for m in media:
            key = m.get("key") or "media"
            where = f"media[{esc(key)}]"
            body += f'<h4>{esc(m.get("title") or key)}</h4>'
            if m.get("lead"):
                body += f"<p>{lines(m['lead'])}</p>"
            body += table(m.get("columns"), m.get("rows"), sources, out_dir, where)
            body += bullets(m.get("notes"))

    diff = data.get("diff") or {}
    dbody = table(diff.get("columns"), diff.get("rows"), sources, out_dir, "diff")
    cards = ""
    if diff.get("same"):
        cards += '<div class="bx"><div class="t">同じところ</div>' + bullets(diff["same"]) + "</div>"
    if diff.get("different"):
        cards += '<div class="bx"><div class="t">違うところ</div>' + bullets(diff["different"]) + "</div>"
    if cards:
        dbody += f'<div class="cards">{cards}</div>'
    if dbody:
        body += h3("貴社との差異と共通点") + dbody
    return body


def build_frame(data, sources, out_dir) -> str:
    body = ""
    nm = data.get("nonmarket") or []
    if nm:
        rows = [{"cells": [n.get("layer"), n.get("limit"), n.get("effect")],
                 "mark": n.get("mark"), "src": n.get("src")} for n in nm]
        body += (h3("非市場の制約（規制・審査・媒体ポリシー）")
                 + "<p>表現の可否はここで決まります。訴求を考える前に置きます。</p>"
                 + table(["層", "何が縛られるか", "この案件への影響"], rows, sources, out_dir, "nonmarket"))

    c3 = data.get("three_c") or {}
    labels = [("customer", "顧客（誰が・何に困り・どう探しているか）"),
              ("competitor", "競合（規模感・訴求・媒体・LP・オファー）"),
              ("company", "自社（提供価値・証拠・弱み）")]
    c3body = ""
    for key, title in labels:
        items = c3.get(key) or []
        if items:
            c3body += f"<h4>{esc(title)}</h4>" + item_table(items, sources, out_dir, f"three_c[{key}]")
    if c3body:
        body += h3("3C") + c3body

    comp = data.get("competition") or {}
    if comp:
        cbody = ""
        if comp.get("options"):
            rows = [{"cells": [o.get("type"), o.get("fit"), o.get("note")],
                     "mark": o.get("mark"), "src": o.get("src")} for o in comp["options"]]
            cbody += table(["型", "当てはまり", "この案件での中身"], rows, sources, out_dir,
                           "competition.options", default_mark="inference")
        if comp.get("chosen"):
            cbody += (f'<div class="note"><span class="t">この案件の型</span>'
                      f'<b>{esc(comp["chosen"])}</b>')
            if comp.get("why"):
                cbody += f"<br>{lines(comp['why'])}"
            cbody += "</div>"
        if comp.get("implication"):
            cbody += (f'<div class="tip"><b>だから広告では:</b> {lines(comp["implication"])}</div>')
        body += h3("競争の型（広告の訴求はこれに従う）") + cbody

    ff = data.get("five_forces") or []
    if ff:
        if len(ff) > 3:
            warnings.append("five_forces が3行を超えています（代替品と買い手の価格感度に絞ってください）")
        rows = [{"cells": [f.get("force"), f.get("level"), f.get("note")],
                 "mark": f.get("mark"), "src": f.get("src")} for f in ff]
        body += (h3("5F（代替品と、買い手の価格感度）")
                 + table(["力", "強さ", "中身"], rows, sources, out_dir, "five_forces",
                         default_mark="inference"))

    vrio = data.get("vrio") or []
    if vrio:
        rows = [{"cells": [v.get("strength"), v.get("value"), v.get("rare"),
                           v.get("hard"), v.get("org"), v.get("proof")],
                 "mark": v.get("mark"), "src": v.get("src")} for v in vrio]
        body += (h3("VRIO（広告で証明できる強みだけ）")
                 + "<p>画面で見せられないものは、ここに書かないでください。</p>"
                 + table(["強み", "価値", "希少", "模倣困難", "組織で使えるか", "広告のどの画で証明するか"],
                         rows, sources, out_dir, "vrio"))
    return body


def build_target(data, sources, out_dir) -> str:
    body = ""
    targets = data.get("targets") or []
    if targets:
        body += h3("ターゲット像と、媒体ごとの視聴シーン")
        for t in targets:
            body += f'<h4>{esc(t.get("name"))}</h4>'
            if t.get("situation"):
                body += f"<p>{lines(t['situation'])}</p>"
            rows = [{"cells": [s.get("media"), s.get("when"), s.get("mood")],
                     "mark": s.get("mark"), "src": s.get("src")} for s in t.get("scenes") or []]
            body += table(["媒体", "見る場面", "そのときの気持ち"], rows, sources, out_dir,
                          f"targets[{esc(t.get('name'))}]", default_mark="inference")

    emotion = data.get("emotion") or []
    if emotion:
        stages = [str(e.get("stage") or "") for e in emotion]
        flow = '<div class="flow">' + "<s>→</s>".join(f"<i>{esc(s)}</i>" for s in stages) + "</div>"
        rows = [{"cells": [e.get("stage"), e.get("state"), e.get("trigger"), e.get("risk")],
                 "mark": e.get("mark"), "src": e.get("src")} for e in emotion]
        body += (h3("感情の流れ") + flow
                 + table(["段階", "心の状態", "それを起こすもの", "ここで落ちる理由"],
                         rows, sources, out_dir, "emotion", default_mark="inference"))
    return body


def build_funnel(data, sources, out_dir) -> str:
    body = ""
    funnels = data.get("funnels") or []
    landings = data.get("landings") or []

    if funnels:
        body += h3("媒体ごとの導線")
        for f in funnels:
            where = f"funnels[{esc(f.get('media'))}]"
            v = f.get("video") or {}
            steps = ["視聴シーン", "感情の流れ", "動画", "着地", "CV"]
            flow = '<div class="flow">' + "<s>→</s>".join(f"<i>{esc(s)}</i>" for s in steps) + "</div>"
            pairs = [
                {"label": "視聴シーン", "value": f.get("scene")},
                {"label": "感情の流れ", "value": f.get("emotion")},
                {"label": "動画の尺", "value": v.get("length")},
                {"label": "動画｜冒頭", "value": v.get("open")},
                {"label": "動画｜ボディ", "value": v.get("body")},
                {"label": "動画｜CTA", "value": v.get("cta")},
                {"label": "着地", "value": f.get("landing")},
                {"label": "CV（何をもって成果とするか）", "value": f.get("cv")},
                {"label": "測り方", "value": f.get("measure")},
            ]
            pairs = [p for p in pairs if p["value"]]
            mark = proof(f, sources, where, "inference")
            body += (f'<div class="funnel"><div class="fh">{esc(f.get("media"))}</div>'
                     f'<div class="fb">{flow}{kv(pairs)}<p>{mark}</p></div></div>')

    if landings:
        keys = [str(l.get("key") or "").upper() for l in landings]
        missing = [k for k in LANDING_KEYS if k not in keys]
        if missing:
            errors.append("landings: 着地は3案そろえてください（足りない案: "
                          + " / ".join(missing) + "）。A=現状の LP のまま、B=LP を少し直す、C=新設")
        cards = ""
        for l in landings:
            where = f"landings[{esc(l.get('key'))}]"
            if not l.get("hope") or not l.get("risk"):
                errors.append(f"{where}: 期待（hope）と懸念（risk）は必ず対で書いてください")
            if not l.get("effect_on_video"):
                errors.append(f"{where}: 動画の作り方への影響（effect_on_video）が抜けています")
            inner = f'<div class="h">{esc(l.get("key"))}案　{esc(l.get("title"))}</div>'
            if l.get("what"):
                inner += f'<p><b>すること:</b> {lines(l["what"])}</p>'
            inner += f'<p><b>期待:</b> {lines(l.get("hope"))}</p>'
            inner += f'<p><b>懸念:</b> {lines(l.get("risk"))}</p>'
            inner += f'<p><b>動画の作り方への影響:</b> {lines(l.get("effect_on_video"))}</p>'
            mark = proof(l, sources, where, "inference")
            if mark:
                inner += f"<p>{mark}</p>"
            cards += f'<div class="bx">{inner}</div>'
        body += (h3("着地の3案")
                 + "<p>動画だけを直すのか、LP まで触るのかで、作る動画が変わります。3案を並べて依頼主に選んでもらいます。</p>"
                 + f'<div class="cards c1">{cards}</div>')
    return body


def build_appeal(data, sources, out_dir) -> str:
    appeals = data.get("appeals") or {}
    body = ""
    for place in ("冒頭", "ボディ", "CTA"):
        items = appeals.get(place) or []
        if not items:
            continue
        body += h3(place)
        cards = ""
        for a in items:
            where = f"appeals[{esc(place)}] の {esc(a.get('label'))}"
            if not a.get("hope") or not a.get("risk"):
                errors.append(f"{where}: 期待（hope）と懸念（risk）は必ず対で書いてください")
            inner = f'<div class="h">{esc(a.get("label"))}</div>'
            if a.get("copy"):
                inner += f'<p><b>言葉の例:</b> {lines(a["copy"])}</p>'
            inner += f'<p><b>期待:</b> {lines(a.get("hope"))}</p>'
            inner += f'<p><b>懸念:</b> {lines(a.get("risk"))}</p>'
            mark = proof(a, sources, where, "inference")
            if mark:
                inner += f"<p>{mark}</p>"
            cards += f'<div class="bx">{inner}</div>'
        body += f'<div class="cards">{cards}</div>'
    return body


def build_pick(data, sources, out_dir) -> str:
    r = data.get("recommendation") or {}
    if not r:
        return ""
    body = ""
    if r.get("pick"):
        body += ('<div class="pick"><div class="t">まず試す1本</div>'
                 f'<div class="h">{lines(r["pick"])}</div>' + kv(r.get("spec")) + "</div>")
    elif r.get("spec"):
        body += kv(r["spec"])
    if r.get("why"):
        body += h3("そう薦める理由") + bullets(r["why"])
    if r.get("judge"):
        body += h3("何をもって良し悪しを決めるか") + bullets(r["judge"])
    dropped = r.get("dropped") or []
    if dropped:
        rows = [{"cells": [d.get("option"), d.get("why")], "mark": d.get("mark"), "src": d.get("src")}
                for d in dropped]
        body += (h3("捨てた案と、その理由")
                 + table(["捨てた案", "なぜ捨てたか"], rows, sources, out_dir,
                         "recommendation.dropped", default_mark="inference"))
    elif r.get("pick"):
        warnings.append("recommendation: 捨てた案（dropped）が空です。選ばなかった案と理由も残してください")
    return body


def build_sources(data, out_dir) -> str:
    rows = []
    for s in data.get("sources") or []:
        opened = s.get("opened")
        if opened not in OPENED:
            errors.append(f"sources[{s.get('id')}]: opened は direct / summary / unknown のどれかです（{opened!r}）")
            badge = ""
        else:
            cls, label = OPENED[opened]
            badge = f'<span class="mk {cls}">{label}</span>'
        if opened == "direct" and not s.get("shot"):
            warnings.append(f"sources[{s.get('id')}]: 自分で開いたのに、画面の写し（shot）がありません")
        url = (f'<a href="{esc(s["url"])}" target="_blank" rel="noreferrer">{esc(s["url"])}</a>'
               if s.get("url") else "—")
        shot = shot_html(s.get("shot"), "", out_dir, f"sources[{s.get('id')}]")
        rows.append(
            f'<tr><td class="nm" data-l="番号">{esc(s.get("id"))}</td>'
            f'<td data-l="何を見たか">{lines(s.get("label"))}{shot}</td>'
            f'<td class="u" data-l="URL">{url}</td>'
            f'<td data-l="開き方">{badge}</td>'
            f'<td data-l="確認日">{esc(s.get("checked_on") or "")}</td>'
            f'<td data-l="備考">{lines(s.get("note") or "")}</td></tr>')
    if not rows:
        return ""
    return ('<table class="t-card srcs"><thead><tr><th>番号</th><th>何を見たか</th><th>URL</th>'
            "<th>開き方</th><th>確認日</th><th>備考</th></tr></thead>"
            f'<tbody>{"".join(rows)}</tbody></table>')


def build_verify(data) -> str:
    v = data.get("verification")
    if not v:
        warnings.append("verification がありません（research-verifier に通してから渡してください）")
        return ('<div class="note warn"><span class="t">未検証</span>'
                "この資料はまだ検証を通していません。<code>research-verifier</code> に渡し、"
                "その判定をこの節に載せてから依頼主に見せてください。</div>")
    rows, bad = [], 0
    for r in v.get("rows") or []:
        result = r.get("result")
        cls = RESULTS.get(result)
        if cls is None:
            errors.append(f"verification: result は 一致 / 不一致 / 出典に記載なし / 開けない のどれかです（{result!r}）")
            cls = "mk-u"
        if result != "一致":
            bad += 1
        rows.append(f'<tr><td data-l="主張">{lines(r.get("claim"))}</td>'
                    f'<td class="nm" data-l="出典">{esc(r.get("src") or "")}</td>'
                    f'<td data-l="判定"><span class="mk {cls}">{esc(result)}</span></td>'
                    f'<td data-l="根拠">{lines(r.get("note") or "")}</td></tr>')
    who = esc(v.get("by") or "research-verifier")
    when = esc(v.get("verified_at") or "")
    body = (f"<p>{who} が、引用された URL を自分で開き直し、"
            f"事実と推論の区別も含めて判定しました。（{when}）</p>")
    if v.get("summary"):
        body += f"<p><b>{lines(v['summary'])}</b></p>"
    body += ('<div class="note ok"><span class="t">検証ずみ</span>要修正はありません。</div>'
             if bad == 0 and v.get("passed", True) else
             f'<div class="note warn"><span class="t">要修正</span>'
             f"{bad} 件が「一致」以外です。直してから渡してください。</div>")
    if rows:
        body += ('<table class="t-card"><thead><tr><th>主張</th><th>出典</th><th>判定</th><th>根拠</th>'
                 f'</tr></thead><tbody>{"".join(rows)}</tbody></table>')
    return body


SECTIONS = [
    ("sec-fact", "ファクト（競合と媒体別の実物）",
     "実際に開いた画面から取れた事実だけです。空欄は「分からなかった」という意味です。", build_fact),
    ("sec-frame", "3C・競争の型・非市場の制約",
     "何ができて何ができないかを先に置き、そのうえで誰とどう戦うかを決めます。", build_frame),
    ("sec-target", "ターゲットと視聴シーン", "", build_target),
    ("sec-funnel", "導線設計（媒体別・着地3案）",
     "媒体ごとに、見る場面から成果までを1本の線で描きます。着地は必ず3案を並べます。", build_funnel),
    ("sec-appeal", "訴求の選択肢（冒頭・ボディ・CTA）",
     "どれを選ぶかは依頼主が決めます。効く理由（期待）と、外す理由・規制上の注意（懸念）を対で並べています。",
     build_appeal),
    ("sec-pick", "まず試す1本と、捨てた案", "", build_pick),
]


def build_body(data: dict, sources: dict, out_dir: Path) -> tuple[str, str]:
    parts: list[str] = []
    toc: list[str] = []
    n = 0

    def add(sid: str, title: str, lead: str, body: str):
        nonlocal n
        if not body.strip():
            return
        n += 1
        parts.append(sec(sid, n, title, lead, body))
        toc.append(f'<a href="#{sid}">{n}. {esc(title)}</a>')

    top = ""
    if data.get("summary"):
        top = ('<div class="top"><h2><span>要点</span></h2>'
               + STEPS + LEGEND + bullets(data["summary"]) + "</div>")

    for sid, title, lead, fn in SECTIONS:
        add(sid, title, lead, fn(data, sources, out_dir))
    add("sec-source", "出典と確認状況",
        "本文の主張は、すべてこの一覧のどれかに紐づいています。", build_sources(data, out_dir))
    add("sec-verify", "検証", "", build_verify(data))

    return top + "\n".join(parts), "\n".join(toc)


# ---------------------------------------------------------------- 組み立て

def build(data: dict, out_path: Path) -> str:
    meta = data.get("meta") or {}
    sources = {}
    for s in data.get("sources") or []:
        sid = s.get("id")
        if not sid:
            errors.append("sources に id の無い項目があります")
            continue
        if sid in sources:
            errors.append(f"sources の id {sid!r} が重複しています")
        sources[sid] = s

    body, toc = build_body(data, sources, out_path.parent)

    title = meta.get("title") or "広告リサーチ"
    head = ['<div class="co">広告リサーチ</div>', f"<h1>{esc(title)}"]
    if meta.get("subtitle"):
        head.append(f'<span>— {esc(meta["subtitle"])}</span>')
    head.append("</h1>")
    by = []
    if meta.get("prepared_for"):
        by.append(esc(meta["prepared_for"]))
    if meta.get("date"):
        by.append(f'調査日: <b>{esc(meta["date"])}</b>')
    if meta.get("route"):
        by.append(f'一次情報の開き方: <b>{esc(meta["route"])}</b>')
    if by:
        head.append(f'<div class="by">{"　／　".join(by)}</div>')
    if meta.get("lead"):
        head.append(f'<div class="lead">{lines(meta["lead"])}</div>')

    foot = meta.get("footer") or (
        "この資料の主張には、確かめ方の印（直接確認／要約のみ／未確認／推論）が付いています。"
        "印の無い主張はありません。数字と固有名詞は、出典の URL でご確認ください。")

    text = TEMPLATE.read_text(encoding="utf-8")
    for key, value in (("TITLE", esc(title)), ("HEAD", "\n".join(head)),
                       ("TOC", toc), ("BODY", body), ("FOOT", f"<b>{esc(title)}</b>　{lines(foot)}")):
        text = text.replace(f"<!--{{{{{key}}}}}-->", value)
    return text


def default_out(data: dict) -> Path:
    meta = data.get("meta") or {}
    date = str(meta.get("date") or "").strip() or "undated"
    product = str(meta.get("product") or meta.get("title") or "research").strip()
    for ch in '/\\:*?"<>| ':
        product = product.replace(ch, "_")
    return ROOT / "out" / "research" / f"{date}_{product}.html"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", nargs="?", help="リサーチの JSON")
    ap.add_argument("--out", help="保存先の HTML（既定は out/research/<日付>_<商材>.html）")
    ap.add_argument("--open", action="store_true", dest="open_", help="作ったあとブラウザで開く（macOS）")
    ap.add_argument("--print-schema", action="store_true", help="入力 JSON の書式を表示して終わる")
    a = ap.parse_args()

    if a.print_schema:
        print(__doc__)
        return 0
    if not a.input:
        ap.error("リサーチの JSON を渡してください（書式は --print-schema）")

    import check_project  # noqa: E402
    if check_project.check(ROOT, "research", quiet=True) != 0:
        return 2
    src = Path(a.input)
    if not src.exists():
        print(f"✗ {src} がありません")
        return 1
    try:
        data = json.loads(src.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"✗ {src} が JSON として読めません: {exc}")
        return 1
    if not TEMPLATE.exists():
        print(f"✗ 雛形がありません: {TEMPLATE}")
        return 1

    out = Path(a.out) if a.out else default_out(data)
    out.parent.mkdir(parents=True, exist_ok=True)
    (out.parent / "img").mkdir(exist_ok=True)

    text = build(data, out)

    if errors:
        print("✗ 入力に直すところがあります（HTML は作りません）:")
        for e in errors:
            print("   " + e)
        return 1

    out.write_text(text, encoding="utf-8")
    print(f"✓ 作成しました: {out}")
    for w in warnings:
        print("   ⚠ " + w)

    if a.open_:
        if platform.system() == "Darwin":
            subprocess.run(["open", str(out)], check=False)
        else:
            print(f"   （macOS 以外では自動で開きません。ブラウザでこのファイルを開いてください: {out}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
