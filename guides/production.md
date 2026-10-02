# 制作の手順書

作り方ごとの手順です。**必要な章だけ**を開いてください。各章は「要点 → 手順」の順に書いてあります。
全体の流れと判断基準は `RULES.md`、検査の仕組みは `guides/quality.md` にあります。

- [1. どの作り方を選ぶか](#1-どの作り方を選ぶか)
- [2. 準備（最初に1回だけ）](#2-準備最初に1回だけ)
- [3. セリフつきクリップを作る](#3-セリフつきクリップを作る)
- [4. 同じ人物を保つ（参照の作り方）](#4-同じ人物を保つ参照の作り方)
- [5. 音声先行のトーキングヘッド](#5-音声先行のトーキングヘッド)
- [6. 既にある静止画を動かす](#6-既にある静止画を動かす)
- [7. キーフレーム法（実写風を企画から作る）](#7-キーフレーム法実写風を企画から作る)
- [8. 比率（9:16 と 4:5、横型）とフォント](#8-比率916-と-45横型とフォント)

登場人物の素材づくりと音（効果音・BGM）の設計は `guides/assets-and-sound.md` にあります。

---

## 1. どの作り方を選ぶか

**要点**: 画をどう作るか（生成／既存）と、音をどう作るか（生成／読み上げ）の組み合わせで決まります。

| 作り方 | 画 | 音声 | 向く場面 | 章 |
|---|---|---|---|---|
| セリフつきクリップ | AI 映像制作ツールが台本から生成 | 生成される | セリフごとにテロップを切り替える広告 | 3 |
| トーキングヘッド | AI 映像制作ツールが参照音声から生成 | 先に読み上げで作る | 人がひと続きに話す画。声を選びたいとき | 5 |
| 既存の静止画を動かす | 既にある絵をわずかに動かす | 既にあるものを使う | 静止画の動画を動く版にしたいとき | 6 |
| キーフレーム法 | キーフレーム画像 → 短いクリップ | 読み上げ＋テロップ | 実写風・生活感のある画を企画から作るとき | 7 |

どの作り方でも共通する決まりは3つ。**費用のかかる生成の前に承諾を得る**（記録が無いとスクリプトが拒否）、
**`--dry-run` を先に通す**、**同じセリフの作り直しは2回まで**（3回目は台帳を見てスクリプトが拒否）。

---

## 2. 準備（最初に1回だけ）

**要点**: 動画編集ツールと、音声認識の道具を入れます。5〜10分で終わります。

```bash
npm i                                  # 動画編集ツール（Remotion）と検査の道具を入れる
cp .env.example .env                   # 使うサービスの鍵を入れる（値はこのファイルの外に出さない）
```

音声の検品（発音の確認）には、音声認識の道具とモデルが要ります。

```bash
brew install whisper-cpp ffmpeg        # macOS の場合
mkdir -p .whisper-models
curl -L -o .whisper-models/ggml-large-v3-turbo.bin \
  https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo.bin
```

2つ目のエンジン（`ai-ad.config.json` の `whisperModel2`）は任意です。2エンジンで一致を見る方が、
1つのエンジンの気まぐれに引きずられません。無ければ1エンジンで動きます。入っているか確かめる:

```bash
npm run typecheck
python3 scripts/preflight.py           # シーンが空なら「未定義」と出て合格になります
npm run studio                         # ブラウザで開けば準備は完了
```

---

## 3. セリフつきクリップを作る

**要点**: 1セリフ＝1クリップ。**1カット目で人物を決め、2カット目以降はその参照を渡す**（4章）。
台本は一息の短文に割る。初稿は各セリフ1テイク。

**構成を先に決める。** 人物が話すカットだけを並べないでください（`RULES.md` レイアウト 1-3）。
台本を割る前に、カットの並びを「状況の画 → 人物 → 人物 → 状況の画 → …」の形で紙に書き、冒頭は §3 の場面から始めます。
状況の画はセリフなし・4秒前後で、人物カットと同じ人物・同じ場所で作ると繋がります。

**台本を割る。** **1チャンク＝一息の短文（約1.5〜2.5秒・1つの内容）**にします。音声の崩れはクリップの長さではなく、1行の長さに比例します。
複数の文を1つに詰め込まないでください。敬体は文字数が1.5〜2倍に膨らむので、文体は意図して選びます。
台本が先に確定していて長い場合は、割る提案か、そのまま通してリスクを明示するかを依頼主に選んでもらいます（`RULES.md` 決まり13）。

**`lines.json` を書く。** `lines.json.example` をコピーして中身を入れ替えます。

```json
{
  "defaults": {
    "resolution": "720p", "ratio": "9:16", "duration": 5, "generate_audio": true,
    "source_task_id": null,
    "style": "A calm Japanese woman in her 30s in a light gray jacket sits at a desk in a bright office, looking straight into the camera, locked-off camera, no camera movement, small natural movements only"
  },
  "lines": [
    {"id": "s1", "text": "（一息で言える短文）", "duration": 4}
  ]
}
```

- **`lines` の並び順が意味を持ちます。** 先頭が1カット目（人物を決めるカット）、2件目以降は参照が要ります
- 口の形の精度が要るあいだは、**カメラ・頭・手を動かさない**指示を `style` に常備します（`locked-off camera`, `head steady`）
- 参照する動画・音声は**公開URLだけ**です。手元のファイルのパスは必ず拒否されます。否定形より肯定形の短い指示が安定します

**1カット目を作る。**

```bash
# ① 送る内容を確かめる（費用はかからない）
python3 scripts/generate_lines.py --lines lines.json --dry-run

# ② 何を・何本・どのサービスで作るかを伝えて承諾を得る（対話。ここで y と答えた記録が残る）
python3 scripts/approve.py --generation --ids s1 --takes 1 --service seedance

# ③ 1カット目だけ生成する（ここから費用がかかる）
python3 scripts/generate_lines.py --lines lines.json --ids s1 --takes 1
```

承諾の記録（`out/generation-approval.json`）が無ければ ③ は動きません。`--dry-run` は送る内容を表示するだけです。

**1カット目の人物を見てもらい、採用を決める。ここで止まります。** 人物（顔・髪・服・部屋）を依頼主に見てもらい、この人で進めてよいかを確かめます。
採用が決まってから、その人物を残りのカットに引き継ぎます（4章）。**先に全カットを作ってはいけません。**

**残りのセリフを生成する。** 4章で `source_task_id`（または `reference_video` の URL）を `lines.json` に書いてから、残りを生成します。

```bash
python3 scripts/approve.py --generation --ids s2,s3,s4 --takes 1 --service seedance
python3 scripts/generate_lines.py --lines lines.json --ids s2,s3,s4 --takes 1 --parallel 2
```

参照が無いまま2セリフ目以降を生成しようとすると、スクリプトが拒否します（人物が別人になるため）。
どうしても参照なしで進めるときだけ `--allow-no-reference` を付けます。

**検品の読み方。**

```bash
python3 scripts/generate_lines.py --lines lines.json --check-only    # 生成せず検品だけ
```

結果は表で出ます。`err`（台本との違いの割合）、`extra`（余分な文字数）、`dur`（発話終了／クリップ尺）、`ng`（禁止語）を見ます。
**1テイク目が誤読したら、その誤読を読み方の辞書の `guide` に `never 〜` として足してから2テイク目を投げます**（テイク数を増やさずに直せます）。
当て字は拗音・清濁・母音まで一致していれば合格、違えば別の音なので不合格です。
**機械の一致だけで合格にしてはいけません。** 数字・固有名詞・辞書に登録した語は人の耳で確かめます（次項）。

**危険語は耳で確かめる（機械だけで合格にしない）。**

```bash
python3 scripts/ear_check.py assets/videos/takes/s2-t1.mp4 assets/videos/takes/s2-t2.mp4 --id s2
```

対象の語の前後だけを切り出して並べ、依頼主に **A / B / どちらも不可** を選んでもらいます（全編は聴かせません）。
答えは `out/ear-check.json` に記録され、`preflight.py` が見ます。**記録が無ければ書き出し前の検査で落ちます。**
1本ずつ機械で確かめるコマンド:

```bash
python3 scripts/asr_gate.py assets/videos/takes/s1-t1.mp4
python3 scripts/asr_gate.py assets/videos/takes/s1-t1.mp4 --slow-window 1.2 0.8   # 危険な語を0.7倍速で
python3 scripts/audio_tools.py check assets/videos/takes/s1-t1.mp4 "確かめたい語"
```

**音声を整える（作り直す前に）。**

```bash
python3 scripts/build_chunk.py 入力.mp4 --out 出力.mp4 --audio-out 出力.m4a   # 頭と尾のトリム・間の詰め・尾のフェード
python3 scripts/audio_tools.py cut-gaps 入力.mp4 出力.mp4 --gaps 3.18:3.39    # 語中の不自然な間だけを詰める
```

速度は音声に焼かず、`src/scenes.ts` の `playbackRate` で指定します（`RULES.md` 決まり20）。

---

## 4. 同じ人物を保つ（参照の作り方）

**要点**: 同じ `style` と同じ `seed` では人物は揃いません（**別人になった実測があります**）。
揃えるには、**採用した1カット目の無加工の原本を一時的に公開し、それを参照にして無音の source を1本作り、
その source を残り全カットの参照にします**。順番を飛ばすと人物が変わります。

**① 1カット目を採用する**（3-4）。加工していない原本のまま使います。音を消した版・作り直した版は拒否されます。

**② 原本を一時的な公開URLにする。**

```bash
python3 scripts/rehost.py assets/videos/takes/s1-t1.mp4
```

渡したファイル**1つだけ**を配るサーバーを立て、一時的な公開URLを作り、届くこと（HTTP 200）を確かめて URL を表示します
（案件フォルダ全体は配りません。`.env` を晒さないためです）。`cloudflared` があればそれを使い、無ければ `npx localtunnel` を使います。
**URL を知っている人は誰でもそのファイルを取得できます。** 外に出さずに動きだけ確かめたいときは `--local-only` を付けます。

`--status` でいま配っている URL を確認、`--stop` で公開を止めます（用が済んだら必ず止めてください）。

**③ 無音の source クリップを1本作る。** ②の URL を `reference_video` にして、`generate_audio: false` で生成します。
声を出さない土台のクリップです。これが同一人物の基準になります。

```json
{"id": "source", "text": "", "generate_audio": false,
 "reference_video": "https://<rehost.py が出したURL>",
 "prompt_extra": "She looks at the camera with a gentle closed-mouth smile and small natural head motion. She does not speak."}
```

**④ source のタスクIDを `lines.json` に書く。**

```json
"defaults": {"source_task_id": "cgt-..."}
```

タスクIDは生成時の表示（`created task_id=...`）と `out/takes-tasks.jsonl` に残っています。
`generate_lines.py` が、そのタスクの動画URLを取り出して各セリフの参照に使います。**⑤ 残りのセリフを生成します**（3章）。

**失効したとき。** source の動画URLは1日程度で失効します。失効したら ② からやり直してください（数分で作り直せます）。
`--stop` を忘れると、手元のファイルが公開されたままになります。

---

## 5. 音声先行のトーキングヘッド

**要点**: 先に読み上げ音声を作り、それを**参照音声**として渡して「人が話すだけ」の画を作ります。
読み違いを防げること、声を選べることが利点です。参照音声は**公開URLでしか渡せません**。

**大事な前提**: 参照音声は「そのまま口に当てる」のではなく、**声色と読み上げ内容の参照**として使われ、
出力の音声は新しく作り直されます。**尺も少し変わります**（テロップは出力の音声に合わせます）。

**自然に見せる4つの設計。** 「AI っぽさ」は動きが大きいほど出ます。次の4つはプロンプトの型（`scripts/prompts/talking_head.txt`）に入っています。
①固定カメラ・ワンカット（バストショット1つで通す）②基本姿勢を固定（座る・手を組む等を最後まで変えない）
③動きは音声に同期した小さなものだけ（まばたきと小さなうなずき）④画面の文字・BGM・効果音なし（後から Remotion で載せる）。

**① 台本を2〜30秒に収める**（参照音声も出力も最長30秒。収まらなければ文の切れ目で分ける）。

**② 読み上げ音声を作る。**

```bash
cp tts.json.example tts.json          # 中身を入れ替える
python3 scripts/generate_tts.py --script tts.json --dry-run
python3 scripts/generate_tts.py --script tts.json
```

読み上げには**読み方の辞書が効きません**。読み違う語は、台本側の表記を開いて（漢字をひらがなにして）ください。

**③ 送る内容を確かめる（費用はかからない）。**

```bash
python3 scripts/generate_talking_head.py \
  --audio-file assets/audio/narration.mp3 \
  --person "A Japanese woman in her 30s, neat shoulder-length black hair, wearing a light gray jacket" \
  --background "a bright modern office with a large window and green plants behind her" \
  --dry-run
```

音声の長さ・プロンプトの文面・保存先が表示されます。長さが範囲外ならここで止まります。

**④ 音声を公開URLにする。** ファイルの中身のままでは送れません。**この作業は AI が行います。依頼主の操作は不要です。**

```bash
python3 scripts/rehost.py assets/audio/narration.mp3      # URL を作って 200 を確かめて表示
```

Google ドライブを使う場合は、共有を「リンクを知っている全員」にして**直ダウンロードURL**の形にします
（`https://drive.usercontent.google.com/download?id=<ファイルID>&export=download`。閲覧用の `/view` は HTML が返るので使えません）。
どちらでも、渡す前に `curl -sI "<URL>" | head -3` で **200 が返ってから**始めます（403・404 のまま走らせると課金だけして失敗します）。
生成が終わったら公開を止めます。

**⑤ 何を・何本・どのサービスで作るかを伝えて承諾を得て、生成する。**

```bash
python3 scripts/approve.py --generation --ids talking-head --takes 1 --service seedance \
  --note "narration.mp3（12秒）から、人が話すだけの映像を1本"
python3 scripts/generate_talking_head.py \
  --audio-url "<公開URL>" --audio-file assets/audio/narration.mp3 \
  --script "（参照音声で読み上げている台本をそのまま）" \
  --person "..." --background "..." --take t1
```

`--script` を渡すと、台本に含まれる語の**発音ガイドを最大2件**選んでプロンプトに添えます（**付けるのが既定**）。
**発音の指示を `--extra` に書いてはいけません。** `--extra` は「最後に少し微笑む」のような**英語の短い1文だけ**です。

**⑥ 耳と目で確かめる。**

音声（台本どおりに読めているか。固有名詞・数字は `ear_check.py` で耳の確認を取る）／口の動き（声とずれていないか）／
動きの量（姿勢が崩れていないか）／画面（文字・ロゴ・別の人物が入っていないか）／
尺（元の音声より少し変わります。テロップは**出力の音声**に合わせます）。

**人物と背景の書き方。** `--person` と `--background` は**英語**で書きます。カメラ・姿勢・動きは型に入っているので、人物と背景だけを考えれば足ります
（例: `A Japanese woman in her 30s, shoulder-length black hair, wearing a light gray jacket, calm expression` ／
`a bright modern office with a large window and green plants behind her`）。
思っていたものと違ったら、**言葉を足すより先に減らして**試します。

**うまくいかないとき。**

| 症状 | 見るところ |
|---|---|
| 台本と違う読みになる | 参照音声そのものを聴き直す。参照音声が誤読していれば、読み上げ側で作り直す（映像側では直らない） |
| 参照音声は正しいのに出力だけ語が変わる | 仕様です。`--script` を渡し、出力は `asr_gate.py` と `ear_check.py` で1語ずつ確かめる |
| `--extra` を書いたら発話が壊れた | `--extra` は英語の短い1文だけ。発音は `--script` ＋辞書で渡す |
| 顔が拒否される | 人物の写真を渡していないか確認する。この方式は画像を渡しません |
| 動きが大きい・姿勢が崩れる | `--person` に姿勢（座る・手を組む）を書き込む |
| URL で生成が失敗する | `curl -sI "<URL>" | head -3` で 200 を確かめる。閲覧用URLは使えない |

できあがったクリップは `src/scenes.ts` に1行で足し、`nativeAudio: true` で音声を使います
（1本を複数のシーンに割ってテロップを切り替える形が普通。`npm run align` の対象になります）。

---

## 6. 既にある静止画を動かす

**要点**: 絵だけを AI で微アニメ化し、**文字は動画編集ツール（Remotion）側のまま**保ちます。
AI は日本語の文字を正確に描けないので、分担を崩すと審査を通った表示要素まで壊れます。

差し替えるのは各シーンの画像だけで、ヘッダー・テロップ・注記・表記・音声・BGM・尺は Remotion 側のままにします。

| 項目 | 値 | 理由 |
|---|---|---|
| 生成モード | image-to-video（元の PNG を最初のフレームに） | 絵柄と構図をそのまま引き継ぐ |
| 比率 | adaptive（元画像に合わせる） | 実寸を崩さない |
| 解像度 | 720p | 上位解像度はアップスケールで実利が薄い |
| 尺 | そのシーンの音声尺以上（切り上げ） | 口が止まるずれの防止 |
| 音声の添付 | 口を動かすシーンだけ | 話していないシーンには添付しない |

生成の指示に必ず入れる内容: 添付画像を最初のフレームとしてそのまま動かす／絵柄・構図・色・線・顔立ち・吹き出し・
描かれた文字を変えない／カメラはほぼ固定／音声を添付する場合は**話者を見た目で名指しする**（例: 左側の眼鏡をかけた人物）／
発話していない人物の口は閉じたまま／図・表・端末画面は完全に静止。

```bash
python3 scripts/lib/seedance_api.py create \
  --image-file assets/images/panels/panel-06.png \
  --prompt "$(cat tmp/prompt-scene-09.txt)" \
  --ratio adaptive --resolution 720p --duration 11 \
  --dry-run
python3 scripts/lib/seedance_api.py wait <タスクID>
python3 scripts/lib/seedance_api.py download <動画URL> --out assets/videos/scene-09.mp4
```

取り込んだら `ffprobe` で尺と寸法を確認してから配線します。**クリップの音声は鳴らさず**、Remotion 側の音声を使います。
静止画の指定は残し、映像の指定を外せば静止版に戻せる状態を保ちます。比率ごとに別の画像を使うシーンは流用できません。

---

## 7. キーフレーム法（実写風を企画から作る）

**要点**: 文字の入っていないキーフレーム画像を作り、image-to-video で短いクリップにして繋ぎます。
**画は背景、言葉はテロップと音声**。生成された映像の中に文字を描かせません。

1. キーフレームを先に確定する（人物と場所の一貫性はキーフレームで担保する）
2. 音なしで見られる前提にする（読み上げの文言をそのまま大きな白テロップで同期表示）
3. 1クリップ1動作。長いフレーズは手元・横顔・小物などの細かいカットに割る

画を作り始める前に `knowledge/project.md` の §2〜§3 を埋めます。参考にした他社の動画の社数・金額・運営者表記・
具体的な数字は**流用しません**。数字を出す場合は自社で根拠を確認したものに差し替え、近くに一例である旨の注記を置きます。

**ショット表**: 1本 110〜130 秒を 8〜9 ショットに割ると扱いやすい単位です。列は、通し番号／開始と終了の秒／
担当する認識／読み上げ案（一人称の語り口）／テロップの分け方／そのショットの役目／画の指示。
見せる順序の型は、困りごとの提示（冒頭3秒で自分ごとに）→ 踏み出せない理由 → 放置したときの困りごと →
解決の手段との出会い → 選択肢の広がり → 一般的な手段との違い → 最大の抵抗を外す → 決断の意味づけを変える → 穏やかな行動のうながし。
ショット表とは別に、**読み上げ全文を1ブロックで書いた正本**を置き、音声・テロップ・検品はすべて正本を参照します。

**テロップ**: 音声の文言そのままの全文同期。1回の表示は 12〜22 文字程度、長い文でも2行まで。
画面の中央から下寄りに大きな白文字（黒フチか薄い影）。接続語だけのテロップを単独で出さない。

**キーフレームの生成指示**: 縦 9:16 の実写風、モデル顔でない自然な人物、広告然としない生活感、自然光、
テロップ用の余白（上 20〜25%、下 15〜20%）。毎回**読める文字・数字・ロゴ・字幕を出さない**ことを指定します。
紙・封筒・端末画面などの平面は「**白紙にはしないが、読める文字と数字は出さない**」と指定します。

**動画化**: image-to-video / 9:16 / 720p / 5〜8秒（1クリップ1動作）/ 音声は添付しない / 画面内は文字なし。
指示には、顔立ち・服装・配置を変えない、カメラは手持ちのごく小さな揺れだけ、人物の口は動かさない、
上下に余白を残すことを入れ、そのショットの主な動作を**1つだけ**足します。

**1ショット目で品質を確定させる。** いきなり全ショットを作らず、冒頭1カットだけ作って判断します。
読める文字・数字が出る／口が動いている／表情が極端／手や指が破綻／小物が別物になる／余白がない——
どれかに当てはまれば作り直します。合格したら人物と場所の参照を固定し（4章）、残りへ展開します。

音声ができたら、実測した時刻に合わせて表示を調整します（発話開始から 0〜3 フレーム、終了から 0〜6 フレーム以内）。

```bash
python3 scripts/align_captions.py
python3 scripts/preflight.py
```

---

## 8. 比率（9:16 と 4:5、横型）とフォント

**要点**: 比率ごとに**1シーンずつ完結**させます。まとめて実装すると、比率違い特有のずれが見逃されます。
**比例縮小では合いません。**

横型（16:9）も作れます。`src/Root.tsx` に `width={1920} height={1080}` のコンポジションを足してください
（テロップの縦位置は別に指定し直します）。

**着手前。** 参照元の比率版が存在するか、変換先の設計原稿があるか、映像素材が揃っているかを確かめます。
設計原稿が無い案件は、`narrowCaptionY` を各シーンで指定して 4:5 側の縦位置を決めます。
**指定を忘れると 9:16 の値から換算されて位置がずれます。置き忘れが最も多い事故です。**

**1シーンずつ完結させる。**

1. 変換先の設計原稿の該当シーンを**単独で**取得し、実測値を読む
2. 参照元の同じシーンの実装を読む
3. 変換先の値で実装する → `npm run typecheck`
4. `figma_compare.ts` で数値を出す（`guides/figma.md`）→ 見比べ用の画像も開いて確かめる
5. 差があれば 3 に戻る

置き換えるのは**座標・幅と高さ・文字の大きさと太さ・色・行間・字間・塗り・線・角丸・図の素材**です。
取得できない値を類推したり、他のシーンの値を流用したりはしません。反対に、
**アニメーションの設定・効果音との同期位置・要素の構成**は参照元と同じに保ちます。

```bash
npx tsx scripts/figma_compare.ts --comp ad-4x5 --width 1080 --height 1350 \
  --scene 2 --durations 2.8,2.68,2.35 --figma design/4x5/scene3.png
```

位置やサイズの修正を受けたときも、対象のシーンについて 1〜5 を全部やり直します。目分量の調整を当てると往復が増えます。
全シーン合格後に `npm run typecheck` と `python3 scripts/preflight.py` を通し、依頼主に通しで見てもらい、
承諾を記録してから書き出します（`python3 scripts/approve.py --composition ad-4x5 --out out/ad-4x5.mp4`）。

**フォント。** 既定は Noto Sans JP です。**変えられます。** 「〇〇というフォントに変えて」と頼まれたら、
`src/brand.ts` の `FONT`（Google Fonts の名前）か `FONT_FILE`（`assets/fonts/` に置いたファイル）を書き換えます。
フォントを変えたら、テロップ幅の検査の係数も合わせてください
（`ai-ad.config.json` の `fontFamily` と `fontCharWidth`。やり方は `guides/quality.md`）。
