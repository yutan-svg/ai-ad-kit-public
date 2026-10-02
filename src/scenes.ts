// シーン定義。1シーン1行で書く。
//
// 書式の決まり（scripts/ の検査が正規表現でこの並びを読むので崩さない）:
//   id が先頭 / caption は durationSeconds より前 / 文字列はシングルクォート / 改行は \n
//
// 1行の書き方（そのまま真似できる形）:
//   {id: 1, caption: '1行目\n2行目', durationSeconds: 2.8, src: 'videos/takes/s1-t1.mp4', nativeAudio: true, bgColor: '#1c2830', captionY: 1254, narrowCaptionY: 940, fontSize: 88, captionTone: 'yellow'},
//
//   - src / imageSrc / audioSrc は assets/ からの相対パス
//   - durationSeconds は音声の実測に合わせる（ffprobe で測る）
//   - 4:5 でも納品するなら narrowCaptionY を置き忘れない
//
// 制作を始めると、ここに採用したテイクが1行ずつ並びます。

import type {Scene, Track} from './types';

export const scenes: Scene[] = [
];

export const tracks: Track[] = [
  // 1本の音声が複数シーンにまたがる場合だけ使う（1行1トラック）。atSceneId のシーン開始位置から鳴る。
  // {src: 'audio/narration.m4a', startSeconds: 0, durationSeconds: 7.8, atSceneId: 1},
];
