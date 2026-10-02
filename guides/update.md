# 新しい版のキットを受け取ったとき

キットは改良されていきます。新しい版を受け取ったら、**道具の部分だけを入れ替え、案件の内容は残します。**

---

## 0. どのアプリで開いてもいい

このキットは **Claude デスクトップアプリ ／ ChatGPT デスクトップアプリ／ Antigravity** のどれでも開けます。
読まれるファイルの名前が違うだけで、中身は同じです。

| 開く場所 | 読まれるもの |
|---|---|
| Claude デスクトップアプリ | `CLAUDE.md` ／ `.claude/skills` ／ `.claude/agents` |
| ChatGPT | `AGENTS.md` |
| Antigravity | `GEMINI.md` ／ `.agents/rules` ／ `.agents/skills` ／ `.agents/agents` ／ `.agents/hooks` |

**Antigravity での始め方**: <https://antigravity.google/download> でインストール → 左サイドバーの「フォルダに＋」→
「New Project」→ **Add Folder** でこのフォルダを選ぶ →「Create」→ チャット欄に話しかける。
`.agents/rules/00-confirm.md` は **Always On** にしてください（生成・書き出しの前に必ず確認が入ります）。

`.agents/` は `.claude/` の写しです。手で編集せず、`.claude/` を直してから次を実行します。

```bash
python3 scripts/sync_agents.py     # .claude/ → .agents/ に写す
python3 scripts/check_parity.py    # 3つの指示書と写しが揃っているか確かめる
```

---

## 1. 入れ替えるもの・残すもの

| 扱い | 場所 | 理由 |
|---|---|---|
| **入れ替える** | `scripts/` | 検査と生成の道具。改良の本体 |
| **入れ替える** | `guides/` | 手順書 |
| **入れ替える** | `RULES.md` | 決まり |
| **入れ替える** | `CLAUDE.md` / `AGENTS.md` / `GEMINI.md` / `.claude/` / `.agents/` | AI への指示書とスキル（3つの指示書は同じ内容。`.agents/` は Antigravity 用の写し） |
| **入れ替える** | `src/SceneVideo.tsx` / `src/types.ts` / `src/fonts.ts` | 見た目の共通部分と型 |
| **入れ替える** | `remotion.config.ts` | 素材フォルダの指定と、書き出しの承諾ゲート |
| **残す** | `knowledge/` | 商材・言ってよいこと・素材の台帳・進み具合・読み方の追加辞書 |
| **残す** | `src/scenes.ts` / `src/brand.ts` / `src/Root.tsx` | この案件のシーンと固定値 |
| **残す** | `assets/` | 映像・画像・音声の素材 |
| **残す** | `FIXES.md` | 指摘の台帳 |
| **残す** | `.env` / `ai-ad.config.json` / `lines.json` / `tts.json` | 鍵と設定 |
| **残す** | `out/` | 承諾・耳の確認・テイクの台帳（消すと確認をやり直すことになります） |

`ai-ad.config.json` は残しますが、**新版で設定の項目が増えることがあります。** 新版の `ai-ad.config.json` と見比べて、増えた項目を自分の設定に足してください（消してはいけません）。

---

## 2. 手順

```bash
# ① いまの状態を退避する（git を使っていなければ、フォルダごとコピーでも構いません）
git add -A && git commit -m "新版に入れ替える前の状態"

# ② 新版を別の場所に展開する
unzip ~/Downloads/ai-ad-kit-<日付>.zip -d ~/tmp/ai-ad-kit-new

# ③ 道具の部分だけを入れ替える
rm -rf scripts guides .claude .agents
cp -R ~/tmp/ai-ad-kit-new/scripts ~/tmp/ai-ad-kit-new/guides ~/tmp/ai-ad-kit-new/.claude ~/tmp/ai-ad-kit-new/.agents .
cp ~/tmp/ai-ad-kit-new/RULES.md ~/tmp/ai-ad-kit-new/CLAUDE.md ~/tmp/ai-ad-kit-new/AGENTS.md ~/tmp/ai-ad-kit-new/GEMINI.md .
cp ~/tmp/ai-ad-kit-new/src/SceneVideo.tsx ~/tmp/ai-ad-kit-new/src/types.ts ~/tmp/ai-ad-kit-new/src/fonts.ts src/
cp ~/tmp/ai-ad-kit-new/remotion.config.ts .

# ④ 設定と依存の差分を見る
diff ~/tmp/ai-ad-kit-new/ai-ad.config.json ai-ad.config.json
diff ~/tmp/ai-ad-kit-new/package.json package.json

# ⑤ 依存が変わっていれば入れ直す
npm i
```

`package.json` は、`scripts` の項（コマンドの並び）が新版で変わっていることがあります。
差分を見て、**新版のコマンドを取り込みつつ、案件で足したコマンドは残して**ください。

---

## 3. 入れ替えたあとの確認

順番に通します。**1つでも落ちたら、先に進まず原因を直してください。**

```bash
npm run typecheck
python3 scripts/check_parity.py   # 3つの指示書と .agents/ の写しが揃っているか
python3 scripts/preflight.py
npm run studio          # Studio で通して見て、見た目が変わっていないか確かめる
```

`src/brand.ts` は残るので、フォントの指定（`FONT`）もそのままです。新版で項目が増えていたら、
新版の `src/brand.ts` と見比べて足してください（`FONT` / `FONT_WEIGHTS` / `FONT_FILE` が無ければ足す）。

見た目が変わっていた場合は、`src/SceneVideo.tsx` の変更が原因です。新版の変更点を読み、`src/scenes.ts` 側で指定し直せるか確かめてください。
自分で `SceneVideo.tsx` を直していた場合は、その変更が消えています。退避した状態（手順①）から差分を取り、必要な変更を新版に当て直してください。

---

## 4. 読み方の辞書について

`scripts/pronunciation_dict.json` は**入れ替わります。** ここに案件の語を足していた場合、その変更は消えます。

案件の語は `knowledge/pronunciation.json`（`ai-ad.config.json` の `pronunciationDictExtra` が指す場所）に書いてください。
こちらは残り、キット標準の辞書に重ねて読まれます。同じ語があれば、案件側が優先されます。

---

## 5. 何が変わったかを記録する

入れ替えたら、`knowledge/CURRENT.md` に「いつ・どの版に入れ替えたか・確認は通ったか」を1行残してください。
あとで不具合が出たとき、入れ替えのタイミングと結びつけられます。
