// 案件ごとに書き換える定数。フッター（常時表示）・音量・フォント。

/** PR 表記。**必要な場合だけ**書く（アフィリエイト、第三者の推奨など）。空なら何も描かない */
export const BRAND = '';

/** 運営者・広告主の表記。**必要な場合だけ**書く。空なら何も描かない */
export const OPERATOR = '';

/** BGM ファイル（assets/ からの相対パス）。ファイルが無ければ鳴らさない */
export const BGM_SRC = 'audio/bgm.mp3';

/** BGM 音量（0〜1）。セリフの聞き取りを優先して小さめにする */
export const BGM_VOLUME = 0.02;

/** セリフ音声の音量（0〜1） */
export const VO_VOLUME = 1.0;

/** フレームレート。scenes.ts の秒数はこの値でフレームに丸める */
export const FPS = 30;

/** フッターに常時出す注記（PR 表記の上に並ぶ）。AI 生成素材を使うときは注記を足す。例: ['※映像はイメージです', '※AI生成映像を使用しています'] */
export const FOOTER_NOTES: string[] = [];

// --- フォント ---------------------------------------------------------------
// 既定は Noto Sans JP。**別のフォントに変えられます。** AI に「〇〇に変えて」と頼めば、
// ここを書き換えて読み込み方も合わせます（Google Fonts にある日本語フォント、
// または手元のフォントファイル）。
//
//   Google Fonts の場合 : FONT にフォント名をそのまま書く（例 'Zen Kaku Gothic New'）
//   手元のファイルの場合: assets/fonts/ に置き、FONT_FILE にその相対パスを書く
//                         （FONT は CSS 上の名前として使われる）
//
// フォントを変えたら、テロップ幅の検査の係数も合わせます
// （ai-ad.config.json の fontFamily と fontCharWidth。詳しくは guides/quality.md）。

/** 使うフォントの名前（Google Fonts の表記、または FONT_FILE に付ける名前） */
export const FONT = 'Noto Sans JP';

/** 読み込むウェイト。太さを使わないなら減らしてよい */
export const FONT_WEIGHTS = ['400', '700', '900'];

/** 手元のフォントファイルを使うときだけ指定する（assets/ からの相対パス。例 'fonts/MyFont.woff2'） */
export const FONT_FILE = '';
