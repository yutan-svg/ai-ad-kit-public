// テロップに使うフォントを読み込み、読み込み完了までレンダーを待たせる。
// これを通さないと、書き出し時にシステムのフォントに落ちて見た目が変わる。
//
// 使うフォントは src/brand.ts の FONT / FONT_WEIGHTS / FONT_FILE で決める。
// Google Fonts にある名前ならそこから読み、FONT_FILE を指定したときは assets/ のファイルを読む。
//
// Google Fonts に届かない環境（外部通信が許可制のクラウドの作業環境など）では、
// 同梱の Noto Sans JP（assets/fonts/NotoSansJP-Bold.ttf、SIL OFL）に自動で切り替える。
// 2026-09-26 に AI Studio の Antigravity agent で、フォントが読めずに書き出しが止まったため。

import {getAvailableFonts} from '@remotion/google-fonts';
import {cancelRender, continueRender, delayRender, staticFile} from 'remotion';
import {FONT, FONT_FILE, FONT_WEIGHTS} from './brand';

export const CAPTION_FONT_FAMILY = FONT;

export const baseFont: React.CSSProperties = {
  fontFamily: `"${FONT}", "Hiragino Sans", "Yu Gothic", "Noto Sans CJK JP", sans-serif`,
  letterSpacing: 0,
};

const handle = delayRender(`フォントの読み込み: ${FONT}`);

/** Google Fonts に届かないときの同梱フォント（assets/ からの相対パス） */
const BUNDLED_FALLBACK_FILE = 'fonts/NotoSansJP-Bold.ttf';

const loadLocalFile = async (file: string) => {
  const face = new FontFace(FONT, `url(${staticFile(file)})`);
  await face.load();
  document.fonts.add(face);
};

const loadGoogleFont = async () => {
  const entry = getAvailableFonts().find((f) => f.fontFamily === FONT);
  if (!entry) {
    throw new Error(
      `Google Fonts に「${FONT}」がありません。名前を確かめるか、` +
        'フォントファイルを assets/fonts/ に置いて src/brand.ts の FONT_FILE に指定してください',
    );
  }
  const mod = await entry.load();
  const {waitUntilDone} = mod.loadFont('normal', {weights: FONT_WEIGHTS});
  await waitUntilDone();
};

const loadWithFallback = async () => {
  if (FONT_FILE) {
    return loadLocalFile(FONT_FILE);
  }
  try {
    await loadGoogleFont();
  } catch (err) {
    // 通信が許可制の環境では Google Fonts に届かない。同梱フォントで続ける（見た目は同じ Noto Sans JP）
    console.warn(`Google Fonts に届かないため同梱フォント（${BUNDLED_FALLBACK_FILE}）を使います: ${err}`);
    await loadLocalFile(BUNDLED_FALLBACK_FILE);
  }
};

loadWithFallback()
  .then(() => continueRender(handle))
  .catch((err) => cancelRender(`フォント「${FONT}」の読み込みに失敗: ${err}`));
