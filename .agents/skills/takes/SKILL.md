---
name: takes
description: 台本から人がセリフを話すクリップを生成して検品する。1カット目で人物を決め、参照を作ってから残りを生成する順序、承諾の取り方、機械検品と耳での確認までを扱う。台本が決まったときに使う。
---
<!-- このファイルは scripts/sync_agents.py が .claude/skills/takes/SKILL.md から作った写しです。直接編集せず、元のファイルを直してから同期してください。 -->

# takes — セリフつきクリップの生成と検品

## 使う場面

台本が決まった後。**ここから費用が発生します。** 承諾の記録が無いと、スクリプトが生成を拒否します。

作り方の詳しい考え方は `guides/production.md` の「3. セリフつきクリップを作る」「4. 同じ人物を保つ」にあります。

## 入る前に確かめる3つ

`knowledge/project.md` §3 に、次の3つが書かれているかを見てください。**空欄なら、ここで止まります。**

1. 画面に出るのは誰か（申し込む側の人物／提供する側の人物／人物なしのナレーション）
2. 冒頭は「誰の・どんな場面」から始めるか
3. 最後にしてほしい行動

①が決まっていないと `style`（人物と背景の英文）が書けず、**1カット目からやり直しになります。**
②が決まっていないと、冒頭が一般論になります。LP から推し量って自分で決めないでください。
未確認なら `new-project` に戻って会話で確かめます（`RULES.md` 第1部1節）。
依頼主も決めかねているなら `ad-research` を勧めます。人物の設定は依頼主が選んだものを使います。聞き方は自由です。

## どちらの座組みで作るか（最初に決める）

| 座組み | 使うコマンド | 人物を揃える方法 | 向いている案件 |
|---|---|---|---|
| **汎用型**（既定） | `scripts/generate_lines.py`（Seedance） | 1カット目の動画を参照にする | 声を選びたい・同じ声で本数を揃えたい |
| **Google 完結型** | `scripts/generate_google.py`（Veo 3.1 ／ Omni） | **参照画像**で揃える | Google の製品だけで作りたい |

`lines.json` は**どちらも同じ**、保存先も同じ、通る門（承諾・テイク上限・参照）も同じです。
Google 完結型の手順と制約は `guides/google-models.md`。**参照音声（声の指定）は Google では使えません。**
下の手順は汎用型（Seedance）の書き方です。Google 完結型では ③④ が「参照画像を1枚つくる」に置き換わります:

```bash
python3 scripts/generate_google.py --lines lines.json --engine veo --dry-run      # 送る内容を見る（無料）
python3 scripts/approve.py --generation --ids reference --takes 1 --service nano-banana
python3 scripts/generate_google.py --lines lines.json --make-reference            # 参照画像を1枚
python3 scripts/approve.py --generation --ids s1 --takes 1 --service veo
python3 scripts/generate_google.py --lines lines.json --engine veo --ids s1 --seconds 4
```

## 順序（これを飛ばすと人物が別人になります）

```
台本を割る → lines.json を書く → 承諾 → ① 1カット目だけ生成
 → ② 依頼主に人物を見てもらい採用を決める
 → ③ 採用した原本を rehost.py で公開して参照URLにする
 → ④ 無音の source を1本作り、その task-id を lines.json に書く
 → ⑤ 承諾 → 残りのセリフを生成 → 検品 → 耳の確認 → 採用
```

### 1. 台本を一息の短文に割る

1チャンク＝1短文（約1.5〜2.5秒・1つの内容）にして、シーンと1対1で対応させます。
台本が先に確定していて長い場合は、**割ることを提案するか、そのまま通してリスクを明示するか**を依頼主に選んでもらいます。

### 2. `lines.json` を書く

`lines.json.example` をコピーして中身を入れ替えます。**`lines` の並び順が意味を持ちます**（先頭が1カット目）。

- `defaults`: 解像度・比率・尺・`style`（人物と背景の英文）。人物を揃える `source_task_id` は ④ で書き足します
- `lines[]`: `{"id": "s1", "text": "…", "duration": 4}`。表情を変えたい行だけ `prompt_extra` を足す
- 参照する動画・音声は**公開URLだけ**です。手元のファイルのパスは必ず拒否されます
- 読み方の辞書は自動で適用されます。商材名が入っているか `knowledge/pronunciation.json` を確かめてください

### 3. 送信内容を確かめ、承諾を取る（費用はかからない）

```bash
python3 scripts/generate_lines.py --lines lines.json --dry-run
python3 scripts/approve.py --generation --ids s1 --takes 1 --service seedance
```

`approve.py --generation` が **何を（id とセリフ）・何本・どのサービスで** 作るかを表示して y/N を聞き、
`out/generation-approval.json` に記録します（セリフは `lines.json` から読みます）。
**この記録をあなたが書いてはいけません**（対話でしか記録できない作りです）。曖昧な返事なら聞き返してください。

### 4. ① 1カット目だけ生成する

```bash
python3 scripts/generate_lines.py --lines lines.json --ids s1 --takes 1
```

**全部まとめて生成しないでください。** 1カット目は「この人物で進めてよいか」を決めるためのカットです。

### 5. ② 人物を見てもらう

クリップの置き場所を伝えて、人物（顔・髪・服・部屋）を見てもらいます。作り直すなら台本ではなく `style` を直します。
採用が決まってから次に進みます。

### 6. ③④ 参照を作る

```bash
python3 scripts/rehost.py assets/videos/takes/s1-t1.mp4      # 無加工の原本を一時公開（200 を確認して URL を表示）
```

その URL を `reference_video` にして、`generate_audio: false` の無音 source を1本作ります。
できた source のタスクID（`created task_id=...`）を `lines.json` の `defaults.source_task_id` に書きます。
用が済んだら `python3 scripts/rehost.py --stop` で公開を止めます。

### 7. ⑤ 残りのセリフを生成する

```bash
python3 scripts/approve.py --generation --ids s2,s3,s4 --takes 1 --service seedance
python3 scripts/generate_lines.py --lines lines.json --ids s2,s3,s4 --takes 1 --parallel 2
```

- **初稿は各セリフ1テイク**（`--takes 1`）
- **同じセリフの作り直しは2回まで。** 3回目は台帳（`out/takes-ledger.json`）を見てスクリプトが拒否します。
  拒否されたら、`--force` を探す前に原因（辞書・表記・割り方）を直してください
- 参照が無いまま2セリフ目以降を生成しようとすると拒否されます。それは人物が別人になる合図です
- 保存先は `assets/videos/takes/<id>-t<n>.mp4`。生成せず検品だけやり直すときは `--check-only`

### 8. 結果を表で報告する

`out/takes-report.json` を読み、**表にして**見せます。JSON をそのまま貼らないでください。

| id | テイク | 判定 | 聞き取られた文字 | 台本との差 | 備考 |
|---|---|---|---|---|---|

- 不合格には「なぜ落ちたか」を日本語で1行（台本との差・禁止語・尺切れのどれか）
- **1テイク目が誤読したら、その誤読を `knowledge/pronunciation.json` の `guide` に `never 〜` として足してから2テイク目を投げます**
- 音声が惜しいだけの不合格は、作り直す前に無コスト救済（`build_chunk.py` / `audio_tools.py cut-gaps`）を試します

### 9. 数字・固有名詞は耳で確かめてもらう（省略できません）

```bash
python3 scripts/ear_check.py assets/videos/takes/s2-t1.mp4 assets/videos/takes/s2-t2.mp4 --id s2
```

対象の語の前後だけを切り出して並べ、**A / B / どちらも不可**を選んでもらいます。全編は聴かせません。
記録が無いセリフは `preflight.py` が不合格にします。機械の一致だけで合格にしてはいけません。

### 10. 採用を決める

合格したテイクの id とファイル名を一覧にします。使わなかったテイクは消しません（後で比較に使います）。
新しく作った映像は `knowledge/assets.md` に印象を1行足してください。

## 次に使うスキル

`draft`（配線して初稿を見せる）。
