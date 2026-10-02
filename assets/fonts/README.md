# 同梱フォント

- `NotoSansJP-Bold.ttf` — Noto Sans JP（Bold）。Google Fonts の配布物（SIL Open Font License 1.1、`OFL.txt`）。
  普段は Google Fonts から読み込むので使わない。外部通信が許可制の環境（クラウドの作業環境など）で
  Google Fonts に届かないときだけ、`src/fonts.ts` が自動でこのファイルに切り替える。
- 別のフォントを使うときは、ここに置いて `src/brand.ts` の `FONT_FILE` に相対パスを書く。
