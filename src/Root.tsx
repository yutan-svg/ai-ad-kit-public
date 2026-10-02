import React from 'react';
import {Composition} from 'remotion';
import {FPS} from './brand';
import {scenes} from './scenes';
import {SceneVideo, totalFrames} from './SceneVideo';

// 9:16 と 4:5 の2本。尺は scenes.ts の合計から自動で決まる。
// 横型（16:9）が要るときは、下と同じ形で width={1920} height={1080} のコンポジションを足す。
// ID を変えるときは package.json の render スクリプトも合わせて変える。
const durationInFrames = totalFrames(scenes, FPS);

// --- 別バージョン（冒頭だけ差し替えた版、作り方ちがいの比較）を足すとき -----------
// SceneVideo は {scenes?, tracks?, label?} を prop で受けるので、同じテンプレートのまま
// コンポジションを増やせる（scenes.ts を書き換えたり、部品をコピーしたりしなくてよい）。
//
//   1. src/scenes-opening2.ts を作り、冒頭の1シーンだけ差し替えて他は scenes.ts からそのまま写す
//      （本編を共有しておくと、冒頭の差だけを比べられる）
//   2. 下の import と Composition のコメントを外す
//   3. npm run typecheck → npm run studio で確認し、
//      npx remotion render src/index.ts ad-9x16-opening2 out/ad-9x16-opening2.mp4 で書き出す
//
// import {scenesOpening2} from './scenes-opening2';
//
// label（省略可）は画面下部に「生成: 〜」と出す表記。作り方ちがいを並べて比べるとき以外は付けない。

export const Root: React.FC = () => (
  <>
    <Composition id="ad-9x16" component={SceneVideo} durationInFrames={durationInFrames} fps={FPS} width={1080} height={1920} />
    <Composition id="ad-4x5" component={SceneVideo} durationInFrames={durationInFrames} fps={FPS} width={1080} height={1350} />
    {/* 別バージョン（上の手順 2 でコメントを外す）
    <Composition id="ad-9x16-opening2" component={SceneVideo} defaultProps={{scenes: scenesOpening2}} durationInFrames={totalFrames(scenesOpening2, FPS)} fps={FPS} width={1080} height={1920} />
    */}
  </>
);
