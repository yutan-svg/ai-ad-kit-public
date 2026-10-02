// シーン定義の型。src/scenes.ts はこの型に従って「1シーン1行」で書く（書式の決まりは scenes.ts の冒頭）。

export type CaptionTone = 'yellow' | 'red';

export type Scene = {
  /** シーン番号。先頭に置く（scripts/ の検査が `{id: N, ...` を目印に解析する） */
  id: number;
  /** テロップ本文。改行は \n。セリフの逐語 */
  caption: string;
  /** シーンの長さ（秒）。音声の実測値（ffprobe）に合わせる */
  durationSeconds: number;
  /** 背景動画（assets/ からの相対パス）。imageSrc より優先 */
  src?: string;
  /** 背景静止画（assets/ からの相対パス） */
  imageSrc?: string;
  /** 背景動画の再生開始位置（秒） */
  videoStartSeconds?: number;
  /** 背景動画の再生速度（1 = 等速） */
  playbackRate?: number;
  /** 背景色。映像・画像が無いとき、または読み込み前に見える色 */
  bgColor: string;
  /** 9:16 でのテロップ中心 y（px, 1080×1920 基準） */
  captionY?: number;
  /** 4:5 でのテロップ中心 y（px, 1080×1350 基準）。未指定時は captionY から換算 */
  narrowCaptionY?: number;
  /** テロップの文字サイズ（px）。基準 88・最低 72 */
  fontSize?: number;
  /** テロップ全体の色。yellow=通常の強調 / red=ネガティブ・警告 */
  captionTone?: CaptionTone;
  /** テロップ内で色を変える語句（部分強調） */
  highlights?: string[];
  /** 注釈（※一例です 等）。テロップ下に小さく出す */
  note?: string;
  /** このシーンで鳴らす音声（assets/ からの相対パス） */
  audioSrc?: string;
  /** 背景動画に含まれる音声をそのまま使う（人物のリップシンク映像など） */
  nativeAudio?: boolean;
};

export type Track = {
  /** 音声ファイル（assets/ からの相対パス） */
  src: string;
  /** 音声ファイル内の再生開始位置（秒）。通常 0 */
  startSeconds: number;
  /** 再生する長さ（秒） */
  durationSeconds: number;
  /** どのシーンの開始位置から鳴らすか（Scene.id） */
  atSceneId: number;
};
