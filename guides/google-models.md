# Google 完結型の手順（Veo・Omni・Nano Banana・Gemini・Chirp 3 HD）

このキットには、**同じ作り方で2つの座組み**があります。流れ・決まり・検査・承諾はどちらも同じで、違うのは
「どのアプリで開くか」と「どのエンジンで作るか」だけです。

| 座組み | 開く場所 | 映像 | 参照画像 | 検品 | 読み上げ |
|---|---|---|---|---|---|
| **Google 完結型** | Antigravity | Veo 3.1 ／ Omni 1.1 Flash | Nano Banana 2 | Gemini の文字起こし | Chirp 3 HD |
| **汎用型** | Claude デスクトップアプリ ／ ChatGPT | Seedance | 画像生成 | whisper 2エンジン | Chirp 3 HD ／ 他 |

Google 完結型は、**鍵1本（`GEMINI_API_KEY`）で映像・参照画像・検品まで動きます**（読み上げだけ Google Cloud の認証が別）。
ただし **参照音声（同じ声で本数を揃える）だけは Google では代われません**。声を指定したい案件は汎用型（Seedance）を使ってください。
判断の材料は §6 の「できないこと」にまとめてあります。

---

## 1. Google 完結型でやること（この順番）

```
① Antigravity でフォルダを開く
② 参照画像を1枚つくる（Nano Banana 2）        ← 同じ人物を保つ土台
③ 1カット目を作って人物を見てもらう（Veo か Omni）
④ 残りのカットを、その参照画像で作る
⑤ 検品（Gemini の文字起こし）＋ 数字・固有名詞は耳で確認
⑥ 必要ならナレーションを作る（Chirp 3 HD）
⑦ シーンに配線して Studio で通して見る（Remotion）
⑧ 承諾を得てから書き出す
```

### ① Antigravity で開く

1. <https://antigravity.google/download> から入れます（macOS は 12 以降、Windows 10 以降、Linux も可）
2. 左のサイドバーの「フォルダに＋」のアイコン →「New Project」→ **Add Folder** でこのフォルダを選ぶ →「Create」
3. チャット欄に「このフォルダで動画広告を作りたいです。何から始めればいいですか。」と書いて Enter

Antigravity では、このキットの次のファイルが読まれます（中身は Claude 用・ChatGPT 用と同じです）。

| ファイル | 役割 |
|---|---|
| `GEMINI.md` | AI への指示書（`CLAUDE.md` / `AGENTS.md` と同じ内容） |
| `.agents/rules/00-confirm.md` | 「生成・書き出し・作り直しの前に承諾を得る」決まり。**Always On** で使ってください |
| `.agents/skills/` | 手順書（`.claude/skills` の写し） |
| `.agents/agents/` | 検査役（`.claude/agents` の写し） |
| `.agents/hooks.json` | 生成・書き出しのコマンドの前に、必ず確認を出す仕掛け |

ルールの有効化（Always On）は IDE の Rules の画面でも切り替えられます。`00-confirm.md` の先頭に書いてある
`trigger: always_on` が効かない版では、画面側で Always On にしてください（frontmatter の書式は公式ドキュメントに記載がありません）。
**`.agents/` は写しです。直すときは `.claude/` 側を直して `python3 scripts/sync_agents.py` を実行してください**
（`python3 scripts/check_parity.py` が食い違いを見つけます）。

> Antigravity は自前の API キー（BYOK）に対応していません。IDE の中での生成はプランの枠を使います。
> このキットの生成（Veo／Omni／Nano Banana）は**ターミナルから `.env` の鍵で動く**ので、IDE の枠とは別です。

### ② 参照画像を1枚つくる

```bash
python3 scripts/generate_google.py --lines lines.json --make-reference --dry-run   # 何を送るか見るだけ（無料）
python3 scripts/approve.py --generation --ids reference --takes 1 --service nano-banana
python3 scripts/generate_google.py --lines lines.json --make-reference --reference-out assets/images/reference.png
```

指示文は `lines.json` の `defaults.reference_prompt`、無ければ `defaults.style` から組み立てます（英語で書きます）。
出来たら `lines.json` に書きます。

```json
"defaults": {"reference_image": "assets/images/reference.png"}
```

### ③④ 映像を作る

```bash
# 送る内容を見る（API を呼ばない＝無料。ここで人に見せます）
python3 scripts/generate_google.py --lines lines.json --engine veo --ids s1 --seconds 4 --dry-run

# 承諾を取ってから本番
python3 scripts/approve.py --generation --ids s1 --takes 1 --service veo
python3 scripts/generate_google.py --lines lines.json --engine veo --ids s1 --seconds 4

# Omni で作る場合（尺はプロンプト本文で指示します）
python3 scripts/generate_google.py --lines lines.json --engine omni --ids s1 --seconds 8 --dry-run
```

`generate_google.py` は `generate_lines.py`（Seedance 版）と**同じ `lines.json`** を読み、同じ場所
（`assets/videos/takes/<id>-t<n>.mp4`）に保存し、**同じ門**を通ります。

| 門 | 何で止まるか |
|---|---|
| 生成の承諾 | `out/generation-approval.json` が無ければ生成しない |
| テイク上限 | 同じ id は2回まで。3回目は拒否（`--force "理由"` は台帳に残る） |
| 人物の参照 | 2セリフ目以降に参照画像が無ければ生成しない（`--allow-no-reference` で例外） |

### ⑤ 検品

`ai-ad.config.json` で、検品に使う音声認識エンジンを選べます。**3通りです。**

| 設定 | 何が起きるか | どんなとき |
|---|---|---|
| `"asrEngine": "whisper", "asrEngine2": "whisper"` | 手元の whisper 2本で合議（既定） | 鍵も費用も使いたくないとき |
| `"asrEngine": "whisper", "asrEngine2": "gemini"` | 手元の1本と Google で合議 | 癖の違うエンジンを突き合わせたいとき |
| `"asrEngine": "gemini", "asrEngine2": "none"` | Google だけで検品 | **Google 完結型**（whisper を入れずに済む） |

```bash
python3 scripts/generate_google.py --lines lines.json --check-only   # 既にあるテイクを検品だけする（無料）
python3 scripts/asr_gate.py assets/videos/takes/s1-t1.mp4            # 1本ずつ、2エンジンで確かめる
```

**機械の一致だけで合格にしないでください。** 数字・固有名詞・辞書に載せた語は、必ず耳で確かめます
（`python3 scripts/ear_check.py`）。記録が無ければ `preflight.py` が不合格にします。

### ⑥ ナレーション（必要なとき）

読み上げは Google Cloud の Chirp 3 HD（`scripts/generate_tts.py`）です。認証だけ別で、§5 にまとめてあります。

### ⑦⑧ 配線・確認・書き出し

ここから先は座組みによらず同じです（`guides/production.md`／`RULES.md`）。

```bash
python3 scripts/align_captions.py     # 音声を触ったら
python3 scripts/preflight.py
npm run studio                        # 通して見る
python3 scripts/approve.py --composition ad-9x16 --out out/ad-9x16.mp4
npm run render
python3 scripts/verify_render.py out/ad-9x16.mp4 --frames
```

---

## 2. 日本語セリフの書き方（公式の作法）

**日本語は公式に「評価されていない言語」です。** 公式ドキュメントは「英語は完全に対応、それ以外の言語は評価していない」と明記しています。
つまり**読み違いは仕様上想定されている**ということです。1回で通らなくても異常ではありません。作り直しの回数を見込んで段取りを組んでください。

### 決まった型

セリフは **話者 → says → 半角のダブルクオート** で書きます。これが公式の型です。

```
A woman says, "いっぷん ポチポチ にゅうりょく するだけで。"
```

- 全角の「」で囲むのは公式の型ではありません。**長い文で囲むと弾かれる**実測があります
- 引用符で厳密に区切ることが、**台本にない語を足されるのを防ぐ**唯一の公式手段です
- セリフの中に全角の「！」を入れると、音声の安全フィルタで落ちることがあります。「。」に替えると同じセリフが通ります（公式の根拠はありませんが、実測で差が出ます）。なお、フィルタで落ちた分は課金されません

`generate_google.py` は、この3つ（「！」を「。」にする、全角の鉤括弧を外す、半角のダブルクオートを外す）を
**送る前に自動で直し、直した内容を表示します。**

### 発音を指定する手段は無い

**ふりがな・ローマ字・発音記号を指定する公式の手段は、Veo にも Omni にもありません。**
対策は台本側の表記です。**曖昧な漢字をひらがなに開いて**渡します。キットの読み方の辞書の `replace`（仮名置換）が、そのまま使えます。

読み方の辞書の `guide`（英語の発音メモ）は、Google には**送りません**。指定する公式の手段が無いうえ、
台本にない語を足される原因になるためです（Seedance 版は送ります）。

### 字幕を出させない

字幕を出さないための専用のパラメータはありません。本文の末尾と `negativePrompt` の両方に書きます。

```
Ambient noise: quiet room. No on-screen text, no captions, no subtitles.
negativePrompt: subtitles, captions, on-screen text, watermark, distorted mouth, mismatched lip sync
```

**参照画像を使うと `negativePrompt` は併用できません**（スクリプトが自動で外して投げ直します）。本文末尾の指示だけが残ります。

### 人物を揃える

参照画像を使います。Veo 3.1 は **最大3枚**まで参照画像を受け取ります。
ただし**参照画像を使うと尺が8秒に固定**されます。Omni は同じターンに画像を渡し、本文で `<IMAGE_REF_1>` として指し示します。

---

## 3. 雛形

### Veo 3.1

```
Medium shot, eye-level, fixed camera, single take. A Japanese woman in her 30s, a calm
consultant in a navy jacket, sits at a wooden desk in a bright room, hands resting on the
desk, looking straight into the camera, small natural movements only.
She says, "（ひらがなに開いた台本）"
Her mouth movements match the Japanese dialogue exactly, with no extra words.
Ambient noise: quiet room. No on-screen text, no captions, no subtitles.
negativePrompt: subtitles, captions, on-screen text, watermark, distorted mouth, mismatched lip sync
```

### Omni

Omni は**区間を指定**できます。10秒刻みで最大40秒です。

```
[0-3s] Medium shot of a Japanese woman in her 30s ... looking at the camera.
[3-8s] She says in Japanese, "（ひらがなに開いた台本）" Her lip movement matches the line
       exactly, no additional words.
Ambient noise: quiet room. No captions, no subtitles, no on-screen text.
```

「言い直し」を指示する専用の構文は確認できていません。

---

## 4. 仕様と実測

### Veo 3.1（`veo-3.1-generate-preview`）

| 項目 | 値 |
|---|---|
| 呼び方 | `POST /v1beta/models/<model>:predictLongRunning` → operation を待つ（非同期） |
| 尺 | 4 / 6 / 8 秒（公式は文字列 `"4"`。数値で通った実測あり。片方で落ちたらスクリプトがもう片方で投げ直します） |
| 解像度 | 720p が既定。**1080p と 4k は8秒のみ** |
| 人物の生成 | text-to-video は `allow_all`。参照画像を使う場合は `allow_adult` |
| 参照画像 | 最大3枚（`referenceImages`）。使うと尺は8秒に固定 |
| 枠 | 日次の枠があります。切れると HTTP 429（**この失敗に費用はかかりません**） |
| 実測 | 9:16・720p・4秒＝約55秒で生成（2026-09-17）。8秒・1080p は約96秒（2026-09-16） |

4秒で作りたい場合は 720p にしてください。4秒で 1080p を指定すると、スクリプトが送る前に止めます。

### Gemini Omni 1.1 Flash（`gemini-omni-1.1-flash`）

| 項目 | 値 |
|---|---|
| 呼び方 | `POST /v1beta/interactions`（`generateContent` は使えません。400 になります） |
| 送るもの | `model` ／ `input`（文字列、または画像＋テキストの配列）／ `response_modalities: ["video"]` ／ `response_format` |
| `response_format` | `{"type": "video", "aspect_ratio": "9:16", "resolution": "720p", "delivery": "inline"}`（`delivery` に `base64` を送ると 400。`inline` か `uri`） |
| 尺 | プロンプト本文で指示します（区間指定 `[0-8s] …`）。延長で最大40秒 |
| 実測 | 9:16・720p・8秒＝約34秒で生成、47,398 トークン（2026-09-17） |
| 課金 | トークン課金。**公表の秒単価がありません** |

### Nano Banana 2（`gemini-3.1-flash-image`）

参照画像を1枚つくります。指示文を送ると画像が返ります（**返る形式は JPEG のことがあります**。
保存先の拡張子が `.png` でも中身どおりに扱われるので、そのまま参照に使えます）。

---

## 5. 読み上げ（Google Cloud / Chirp 3 HD）

`scripts/generate_tts.py` が使います。**API キーはありません。** 次のどちらかで認証します。

**A) `gcloud` コマンドが入っている場合**

```bash
gcloud auth application-default login
```

**B) `gcloud` コマンドが無い場合**

認証ファイル（`application_default_credentials.json`）が所定の場所にあれば、スクリプトが自分で読んで動きます。
`gcloud` が PATH に無い環境でも、この経路で問題なく動く実測があります。

### 声の指定

```json
{"defaults": {"voice": "ja-JP-Chirp3-HD-Laomedeia", "speakingRate": 1.0, "pitch": 0.0}}
```

Chirp 3 HD 系（`ja-JP-Chirp3-HD-<名前>`）と Neural2 系のどちらも使えます。
Chirp 3 HD は `pitch` に対応しないとされることがありますが、`pitch: 0.0` を送る現行の実装でエラーにはなりません。
声の一覧は Google Cloud Text-to-Speech の公式ドキュメントで確認してください。

### 読み方の辞書は効かない

読み上げには**キットの読み方の辞書が効きません**。台本の表記をそのまま読みます。
読み違う語は、台本側の表記を開いて（漢字をひらがなにして）ください。

`generate_tts.py` は、生成の前に「読み間違いが起きる書き方」を機械で止めます。止まったら、指摘された語を開いてから生成し直してください。

---

## 6. Google では**できない**こと（案件を受ける前に読む）

| できないこと | 中身 | どうするか |
|---|---|---|
| **参照音声（同じ声で本数を揃える）** | Veo・Omni とも API に音声の入り口がありません。Omni は「参照音声のアップロードは未対応」「参照動画の音声は無視される」と明記 | 声を指定する案件は**汎用型（Seedance）**で作ります |
| **既存の音声で新しいセリフを言わせる** | 同上。声の複製は Chirp 3 の Instant Custom Voice だけで、本人が同意文を録音する前提 | Google 完結型では引き受けません |
| **読み（音読み・訓読み）の指定** | ふりがな・ローマ字・発音記号の手段がありません | 台本の表記をひらがなに開く。それでも駄目なら言い換える／画面の文字にする |
| **日本語の品質保証** | 公式に「評価外」の言語 | 作り直しの回数を見込む。2回失敗したら台本を直す（`RULES.md` 決まり17） |
| **テロップの自動同期・耳の確認の切り出し** | `align_captions.py` と `ear_check.py` は語ごとの時刻が要るので **whisper（手元）が必要**です | この2つだけは whisper を入れてください（`brew install whisper-cpp` とモデル1つ）。検品の合否は Gemini だけでも回せます |

「Google 製品だけで完成します」とは言わないでください。**画と読み上げは置き換えられ、声の固定と読みの指定は置き換えられない**——これが 2026-09-17 時点の事実です。

---

## 7. 出典

- Veo の API 仕様: https://ai.google.dev/gemini-api/docs/veo
- Omni の API 仕様: https://ai.google.dev/gemini-api/docs/omni
- 動画生成の概要: https://ai.google.dev/gemini-api/docs/video
- プロンプトの書き方: https://cloud.google.com/blog/products/ai-machine-learning/ultimate-prompting-guide-for-veo-3-1
- 安全に関する指針: https://docs.cloud.google.com/vertex-ai/generative-ai/docs/video/responsible-ai-and-usage-guidelines
- Google Cloud Text-to-Speech: https://cloud.google.com/text-to-speech/docs
- Antigravity: https://antigravity.google/docs/getting-started/ ／ /docs/ide/rules/ ／ /docs/ide/skills/ ／ /docs/ide/hooks/ ／ /docs/subagents/

仕様は変わります。断定する前に、上の一次情報で確かめてください（`RULES.md` 決まり32）。

## クラウドの作業環境（AI Studio の Antigravity agent）で動かすとき

2026-09-26 に当社で確かめた範囲の手順です。担当者のパソコンに何も入れずに、同じキットを動かします。

1. Playground で Antigravity Agent Preview を選び、Gemini API キーを紐づける
2. Sources → Repository に、キットのリポジトリを **https 形式**（`https://github.com/…`）で指定する（`github://` 形式だとエラーになる）。マウント先は既定の `/new_repository` のまま
3. Google のモデルだけを使うなら鍵のファイルは不要。既定の通信ルール「Gemini API (default)」が鍵のヘッダーを付けるので、環境変数 `GOOGLE_KEY_BY_PROXY=1` を付けて実行する（`GOOGLE_KEY_BY_PROXY=1 python3 scripts/generate_google.py …`）。Seedance など Google 以外を使うときだけ、Sources → Inline file で `/new_repository/.env` を作って鍵を入れる（File path を先に書き換える。既定の `/new_file` のままだと効かない）
4. Network に、npm の配布元 `registry.npmjs.org`、書き出し用ブラウザの配布元 `remotion.media`、使う生成 API のドメイン（Seedance は `ark.ap-southeast.bytepluses.com`。Gemini は既定ルールに含まれる）を足す。**設定を変えたら Type を New にして環境を作り直す**（既存の環境には効かない）。画面の癖: 行を1つ足して入力してから次を足すと、**最初の行が保存時に消える**ことがあった（3回再現）。先に必要な数だけ「Add to allowlist」で行を足し、そのあと上から順に入力し、保存後にもう一度開いて残っているか確かめる
5. 最初の会話で `npm i` を通す。ffmpeg と Python は最初から入っている。音声認識は whisper のモデルが無いので `ai-ad.config.json` の `asrEngine` を `gemini` にする
6. 承諾と耳の確認は端末が無いので、AI がチャットで内容を示し、依頼主の返答の原文を `approve.py --chat "…"`／`ear_check.py --chat-verdict A --chat "…"` に渡す（`RULES.md` 第1部0節）。切り出した音は Environment settings の Download で取り出して聴く
7. 書き出し（`npm run render`）は、初回に `npx remotion browser ensure` で書き出し用ブラウザ（約90MB）を `remotion.media` から取る。サンドボックスの中のブラウザは外部に届かない（許可した Google Fonts のホストでも名前解決に失敗する）ので、テロップのフォントは同梱の `assets/fonts/NotoSansJP-Bold.ttf` に自動で切り替わる（`src/fonts.ts`）。2026-09-26 に 2 秒の確認用シーンで h264 1080×1920 の mp4 が書き出せた
8. 完成した mp4 は Download（環境全体の tar）で取り出す。**ただし当社の試行では tar が 0 バイトで落ちてきた（4回）**。確実な取り出し方は未解決（Google に確認中）。応急策として、確認用の1コマを `ffmpeg` で小さな JPEG にし `base64` で会話に出す方法は通るが、モデルが写し間違えるので `split` と `md5sum` で区切って照合が要る

ページを開き直すと設定が初期化されるので、1つの会話の中で進めます。1回の作業のトークン上限（token cap）は会話の累計に効きます。
