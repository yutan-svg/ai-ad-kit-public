---
name: draft
description: 合格したテイクを src/scenes.ts に配線し、機械検査を通して Studio で見せ、【初稿】ラベルと気づいている問題の一覧を付けて報告する。書き出しはしない。テイクの検品が終わったときに使う。
---
<!-- このファイルは scripts/sync_agents.py が .claude/skills/draft/SKILL.md から作った写しです。直接編集せず、元のファイルを直してから同期してください。 -->

# draft — 初稿を組んで見せる

## 使う場面

合格したテイクが決まった後、初めて通しで見てもらうとき。**ここでは書き出しません。**

## 手順

### 1. `src/scenes.ts` に配線する

**1シーン1行**で書きます。書式を崩すと `scripts/` の検査が効かなくなります。

```ts
{id: 1, caption: '（セリフの逐語）\n（2行目）', durationSeconds: 2.9, src: 'videos/takes/s1-t1.mp4', nativeAudio: true, bgColor: '#1c2830', captionY: 1254, narrowCaptionY: 940, fontSize: 88, captionTone: 'yellow'},
```

- `id` が先頭、`caption` は `durationSeconds` より前、文字列はシングルクォート、改行は `\n`
- 人物のテイクは `src` ＋ `nativeAudio: true`（テイクの音声をそのまま使う）
- `caption` はセリフの逐語。同じテロップを2回出さない
- 秒数は音声の実測に合わせる: `ffprobe -v error -show_entries format=duration -of csv=p=0 <ファイル>`
- 4:5 でも納品するなら `narrowCaptionY` を置き忘れない（**最も多い事故です**）
- 新しく画を作る前に `knowledge/assets.md` を引いて、流用できないか見る

### 2. 機械検査（この順・1コマンドずつ）

```bash
npm run align          # 音声を触った・シーンを割った・文言を変えたとき
npm run preflight      # テロップの幅・行数・強調語・素材の実在と尺・末尾無音・納品尺・耳の確認
npm run typecheck
```

`preflight` が「耳での確認がありません」と言ったら、そのセリフに数字か固有名詞が入っています。
`python3 scripts/ear_check.py <音声> --id <シーンID> --text "<セリフ>"` で依頼主に聴いてもらってください。

- 幅を超えたら、**文字を小さくする前に行の割り直し**（基準88px・最低72px）
- `align` の警告が出た箇所は目で確かめる

### 3. 自分で通して見る

```bash
npm run studio
npx remotion still src/index.ts ad-9x16 tmp/draft-<frame>.png --frame=<N>
```

代表 2〜3 枚の静止画を確かめます（初稿では全シーンの審査はしません）。
テロップが人物の口元や図に重なっていたら、報告の前に直してください。

### 4. 報告する

報告の**先頭に必ず** `【初稿】` と書き、続けて次を書きます。

1. **見方**: 「`npm run studio` を実行し、ブラウザで `ad-9x16` を選んで再生してください」
2. **内容**: シーン番号 / セリフ / テロップ / 秒数の表
3. **気づいている問題の一覧**: 発音が惜しい・映像が単調・注記の位置など。**隠さない**
4. **見てほしいところ**: 「気になる所をシーン番号で教えてください。画面の写真があると一番早いです」

**書き出しはしません。** 依頼主が書き出しに承諾するまで待ちます。

## 次に使うスキル

指摘が来たら `fix`。承諾が出たら `export`。中断するなら `handoff`。
