import React from 'react';
import {
  AbsoluteFill,
  Audio,
  Easing,
  Img,
  OffthreadVideo,
  Sequence,
  interpolate,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';
import {getStaticFiles} from '@remotion/studio';
import {BGM_SRC, BGM_VOLUME, BRAND, FOOTER_NOTES, OPERATOR, VO_VOLUME} from './brand';
import {baseFont} from './fonts';
import {scenes as defaultScenes, tracks as defaultTracks} from './scenes';
import type {Scene, Track} from './types';

// ------------------------------------------------------------
// 尺の計算（scenes.ts の秒数をフレームに丸めて足す）
// ------------------------------------------------------------
export const sceneFrames = (scene: Scene, fps: number) => Math.max(1, Math.round(scene.durationSeconds * fps));
export const totalFrames = (list: Scene[], fps: number) => Math.max(1, list.reduce((sum, s) => sum + sceneFrames(s, fps), 0));
const framesBefore = (list: Scene[], index: number, fps: number) => list.slice(0, index).reduce((sum, s) => sum + sceneFrames(s, fps), 0);

// ------------------------------------------------------------
// 見た目の定数（テロップ: 黄 or 赤・黒縁取り・太字・中央揃え）
// ------------------------------------------------------------
const CAPTION_YELLOW = '#ffe94a';
const CAPTION_RED = '#ff4b4b';
const CAPTION_WHITE = '#ffffff';
const DEFAULT_FONT_SIZE = 88;
const CAPTION_LINE_HEIGHT = 1.22;
const CAPTION_WIDTH = 1000; // 左右 40px ずつ余白（ai-ad.config.json の captionMaxWidthPx と同じ）
const captionShadow = '0 4px 0 #111, 0 -2px 0 #111, 3px 0 0 #111, -3px 0 0 #111, 0 9px 20px rgba(0,0,0,0.72)';
const creditShadow = '0 2px 8px rgba(0,0,0,0.9), 0 1px 2px rgba(0,0,0,0.96)';

const ease = (frame: number, start: number, end: number, from: number, to: number) =>
  interpolate(frame, [start, end], [from, to], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.out(Easing.cubic),
  });

/** 4:5 判定（高さが 9:16 の 90% 未満なら「狭い」）。テロップ位置に narrowCaptionY を使う */
const useIsNarrow = () => useVideoConfig().height / 1920 < 0.9;

/** 1行を highlights の語で分割する（長い語を優先） */
const splitLine = (line: string, highlights: string[]) => {
  const ordered = highlights.filter((word) => word && line.includes(word)).sort((a, b) => b.length - a.length);
  if (ordered.length === 0) return [line];
  const pattern = new RegExp(`(${ordered.map((word) => word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})`, 'g');
  return line.split(pattern).filter(Boolean);
};

/** テロップ本体の色と、highlights の色（黄なら赤、赤・白なら黄で強調） */
const captionColors = (scene: Scene) => {
  const base = scene.captionTone === 'red' ? CAPTION_RED : scene.captionTone === 'yellow' ? CAPTION_YELLOW : CAPTION_WHITE;
  const highlight = scene.captionTone === 'yellow' ? CAPTION_RED : CAPTION_YELLOW;
  return {base, highlight};
};

// ------------------------------------------------------------
// 背景（動画 → 画像 → 単色 の順で採用）
// ------------------------------------------------------------
const coverStyle = (scale: number): React.CSSProperties => ({
  position: 'absolute',
  inset: 0,
  width: '100%',
  height: '100%',
  objectFit: 'cover',
  objectPosition: '50% 30%',
  transform: `scale(${scale})`,
});

const Background: React.FC<{scene: Scene; localFrame: number}> = ({scene, localFrame}) => {
  const {fps} = useVideoConfig();
  const frames = sceneFrames(scene, fps);
  // ゆっくり寄る（1.01 → 約1.03）。静止画・動画とも同じ動き
  const zoom = 1.01 + Math.min(0.022, (localFrame / Math.max(frames, 1)) * 0.022);
  return (
    <>
      <AbsoluteFill style={{backgroundColor: scene.bgColor}} />
      {scene.src ? (
        <OffthreadVideo
          src={staticFile(scene.src)}
          muted={!scene.nativeAudio}
          volume={scene.nativeAudio ? VO_VOLUME : 0}
          playbackRate={scene.playbackRate ?? 1}
          startFrom={Math.round((scene.videoStartSeconds ?? 0) * fps)}
          style={coverStyle(zoom)}
        />
      ) : scene.imageSrc ? (
        <Img src={staticFile(scene.imageSrc)} style={coverStyle(zoom)} />
      ) : null}
      {/* テロップの可読性を上げる薄い暗幕（上下） */}
      <div
        style={{
          position: 'absolute',
          inset: 0,
          background: 'linear-gradient(180deg, rgba(0,0,0,0.06) 0%, rgba(0,0,0,0.01) 25%, rgba(0,0,0,0.01) 64%, rgba(0,0,0,0.14) 100%)',
        }}
      />
    </>
  );
};

// ------------------------------------------------------------
// テロップ
// ------------------------------------------------------------
const captionCenterY = (scene: Scene, narrow: boolean, sy: number) =>
  narrow ? (scene.narrowCaptionY ?? Math.min((scene.captionY ?? 900) * sy, 940)) : (scene.captionY ?? 900) * sy;

const Caption: React.FC<{scene: Scene; localFrame: number}> = ({scene, localFrame}) => {
  const {height} = useVideoConfig();
  const narrow = useIsNarrow();
  const sy = height / 1920;
  const opacity = ease(localFrame, 0, 7, 0, 1);
  const rise = ease(localFrame, 0, 10, 18, 0);
  const fontSize = scene.fontSize ?? DEFAULT_FONT_SIZE;
  const {base, highlight} = captionColors(scene);
  const lines = scene.caption.split('\n');
  return (
    <div
      style={{
        position: 'absolute',
        left: (1080 - CAPTION_WIDTH) / 2,
        width: CAPTION_WIDTH,
        top: captionCenterY(scene, narrow, sy),
        textAlign: 'center',
        color: base,
        fontSize,
        lineHeight: CAPTION_LINE_HEIGHT,
        fontWeight: 900,
        textShadow: captionShadow,
        opacity,
        transform: `translateY(calc(-50% + ${rise}px))`,
        ...baseFont,
      }}
    >
      {lines.map((line, lineIndex) => (
        <div key={`${scene.id}-${lineIndex}`} style={{whiteSpace: 'nowrap', display: 'flex', justifyContent: 'center'}}>
          {splitLine(line, scene.highlights ?? []).map((part, partIndex) => (
            <span key={`${part}-${partIndex}`} style={{color: scene.highlights?.includes(part) ? highlight : base}}>
              {part}
            </span>
          ))}
        </div>
      ))}
    </div>
  );
};

/** 注釈（※一例です 等）。テロップの下に小さく出す */
const Note: React.FC<{scene: Scene}> = ({scene}) => {
  const {height} = useVideoConfig();
  const narrow = useIsNarrow();
  const sy = height / 1920;
  const fontSize = scene.fontSize ?? DEFAULT_FONT_SIZE;
  const lineCount = scene.caption.split('\n').length;
  const top = captionCenterY(scene, narrow, sy) + (lineCount * fontSize * CAPTION_LINE_HEIGHT) / 2 + 40;
  return (
    <div
      style={{
        position: 'absolute',
        left: 82,
        width: 916,
        top,
        textAlign: 'center',
        color: '#fff',
        fontSize: 34,
        fontWeight: 400,
        textShadow: creditShadow,
        ...baseFont,
      }}
    >
      {scene.note}
    </div>
  );
};

// ------------------------------------------------------------
// フッター（PR 表記・運営表記・常設注記）。全シーン常時表示。
// BRAND / OPERATOR / FOOTER_NOTES がすべて空なら、フッターそのものを描かない。
// PR 表記は「必要な場合だけ」入れる（アフィリエイト、第三者の推奨など）。
// ------------------------------------------------------------
const CreditFooter: React.FC = () => {
  const lines = [...FOOTER_NOTES, BRAND, OPERATOR].filter((line) => line.trim() !== '');
  if (lines.length === 0) {
    return null;
  }
  return (
  <div
    style={{
      position: 'absolute',
      right: 30,
      bottom: 54,
      width: 940,
      color: '#fff',
      textAlign: 'right',
      fontSize: 35,
      lineHeight: '47px',
      fontWeight: 400,
      textShadow: creditShadow,
      ...baseFont,
    }}
  >
    {lines.map((line) => (
      <div key={line}>{line}</div>
    ))}
  </div>
  );
};

// ------------------------------------------------------------
// 生成方式ラベル（比較動画用）。画面下部の左に小さく「生成: <方式名>」を出す。
// label が空なら何も出さない（通常の案件では未指定＝非表示）。
// ------------------------------------------------------------
const GenLabel: React.FC<{label?: string}> = ({label}) =>
  label ? (
    <div
      style={{
        position: 'absolute',
        left: 30,
        bottom: 54,
        maxWidth: 470,
        color: '#fff',
        textAlign: 'left',
        fontSize: 32,
        lineHeight: '42px',
        fontWeight: 400,
        textShadow: creditShadow,
        ...baseFont,
      }}
    >
      {`生成: ${label}`}
    </div>
  ) : null;

// ------------------------------------------------------------
// 1シーン
// ------------------------------------------------------------
const SceneRenderer: React.FC<{scene: Scene; label?: string}> = ({scene, label}) => {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill>
      <Background scene={scene} localFrame={frame} />
      {scene.caption ? <Caption scene={scene} localFrame={frame} /> : null}
      {scene.note ? <Note scene={scene} /> : null}
      <div
        style={{
          position: 'absolute',
          left: 0,
          right: 0,
          bottom: 0,
          height: 300,
          background: 'linear-gradient(to bottom, rgba(0,0,0,0) 0%, rgba(0,0,0,0.38) 78%)',
          pointerEvents: 'none',
        }}
      />
      <CreditFooter />
      <GenLabel label={label} />
    </AbsoluteFill>
  );
};

// ------------------------------------------------------------
// BGM の有無（assets/ に BGM_SRC が無ければ鳴らさない）
// ------------------------------------------------------------
const hasStaticFile = (relativePath: string) => {
  const wanted = relativePath.replace(/^\/+/, '');
  return getStaticFiles().some((file) => file.name === wanted);
};

// ------------------------------------------------------------
// 全体
// ------------------------------------------------------------
// バリエーション（冒頭だけ差し替えた別コンポジション、生成方式ちがいの比較動画）は、
// Root.tsx の Composition に scenes / tracks / label を defaultProps で渡して作る。
// label は画面下部の「生成: 〜」表記。いずれも未指定なら scenes.ts の既定を使うので、
// 既存の呼び出し（<Composition component={SceneVideo} />）はそのまま動く。
// 作り方は src/Root.tsx のコメントを参照。
export const SceneVideo: React.FC<{scenes?: Scene[]; tracks?: Track[]; label?: string}> = ({
  scenes: scenesProp,
  tracks: tracksProp,
  label,
}) => {
  const scenes = scenesProp ?? defaultScenes;
  const tracks = tracksProp ?? defaultTracks;
  const {fps} = useVideoConfig();
  const bgmAvailable = React.useMemo(() => hasStaticFile(BGM_SRC), []);
  return (
    <AbsoluteFill style={{backgroundColor: '#111'}}>
      {bgmAvailable && BGM_VOLUME > 0 ? <Audio src={staticFile(BGM_SRC)} volume={BGM_VOLUME} loop /> : null}

      {/* 複数シーンにまたがる音声: atSceneId のシーン開始位置から */}
      {tracks.map((track, i) => {
        const index = scenes.findIndex((s) => s.id === track.atSceneId);
        if (index < 0) return null;
        return (
          <Sequence
            key={`track-${i}-${track.src}`}
            layout="none"
            from={framesBefore(scenes, index, fps)}
            durationInFrames={Math.max(1, Math.round(track.durationSeconds * fps))}
          >
            <Audio src={staticFile(track.src)} startFrom={Math.round(track.startSeconds * fps)} volume={VO_VOLUME} />
          </Sequence>
        );
      })}

      {/* シーン単位の音声 */}
      {scenes.map((scene, index) =>
        scene.audioSrc && !scene.nativeAudio ? (
          <Sequence key={`audio-${scene.id}`} layout="none" from={framesBefore(scenes, index, fps)} durationInFrames={sceneFrames(scene, fps)}>
            <Audio src={staticFile(scene.audioSrc)} volume={VO_VOLUME} />
          </Sequence>
        ) : null
      )}

      {/* 映像とテロップ */}
      {scenes.map((scene, index) => (
        <Sequence key={`scene-${scene.id}`} from={framesBefore(scenes, index, fps)} durationInFrames={sceneFrames(scene, fps)}>
          <SceneRenderer scene={scene} label={label} />
        </Sequence>
      ))}
    </AbsoluteFill>
  );
};
