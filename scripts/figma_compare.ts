/**
 * figma_compare.ts — Figma の設計 PNG と Remotion の実装を突き合わせ、合否を数値で出す。
 *
 * 1コマンドで次まで通します:
 *   ① 指定フレームを Remotion で静止画に書き出す（--comp を渡したとき）
 *   ② 見比べ用の画像を2枚作る（横並び・50%オーバーレイ）
 *   ③ 画素単位で差を測り、合否を判定する（平均差・最大差・帯ごとの差・差分領域・ヒートマップ）
 *
 * **見比べ用の画像を見て「ほぼ一致」と判断してはいけません。** 合否は必ず③の数値で決めます
 * （目視判断でやり直しを何度も招いた実例があるため、RULES.md に決まりとして書いてあります）。
 *
 * 使い方（案件フォルダのルートで）:
 *   npx tsx scripts/figma_compare.ts --comp ad-9x16 --figma design/scene3.png --frame 120
 *   npx tsx scripts/figma_compare.ts --comp ad-9x16 --figma design/scene3.png --scene 2 --durations 2.9,2.5,3.2
 *   npx tsx scripts/figma_compare.ts --figma design/scene3.png --remotion tmp/compare/scene2-remotion.png
 *
 * 合格基準:
 *   --mode full（既定。Figma の PNG をそのまま全面表示しているシーン）
 *       平均差 < 5 かつ 最大差 < 30 で合格。焼き込み画像同士なので完全一致が技術的に可能
 *   --mode decomposed（PNG の上に Remotion で見出し・帯・フッターを描いているシーン）
 *       平均差 < 5 のみで判定し、最大差は参考値。文字のアンチエイリアスで 1px の色反転が必ず起き、
 *       最大差 255 が構造的に出るため
 *   平均差 5〜10 は「要理由提示」（exit 2）。半透明描画の構造的な差、フォント描画差の累積などの
 *       理由を実行役が示し、レビュー側が許容を判断する
 *   帯の平均差が 12 を超えたら⚠。全体平均では埋もれる1文字レベルの文言差・フッター行の違いを拾う
 *
 * 終了コード: 0=合格 / 2=要理由提示 / 1=不合格
 * 注意: 両画像とも removeAlpha() で 3 channels に揃えてから比較します。
 *   channels=4(RGBA) と 3(RGB) を混在させると、実際には無い差（偽差）が出ます。
 * 必要なもの: このフォルダで `npm i`（tsx と sharp が入ります）。
 */
import {spawnSync} from 'node:child_process';
import {existsSync, mkdirSync} from 'node:fs';
import {createRequire} from 'node:module';
import path from 'node:path';

const HELP = `
使い方（案件フォルダのルートで実行する）:
  npx tsx scripts/figma_compare.ts --figma <Figma PNG> (--comp <名> --frame N | --comp <名> --scene N --durations d1,d2,... | --remotion <PNG>)

  --figma <path>       Figma から書き出した PNG（必須）
  --comp <name>        Remotion のコンポジション名（静止画から書き出す場合）
  --remotion <path>    書き出し済みの Remotion PNG（--comp の代わりに使う）
  --frame <n>          書き出すフレーム番号
  --scene <n>          フレーム番号の代わりに、何番目のシーンか（0始まり）
  --durations <csv>    --scene と併用。各シーンの尺（秒）をカンマ区切りで
  --at <ratio>         --scene と併用。シーン内の位置の比率（既定 0.9 = アニメ完了後）
  --fps <n>            フレームレート（既定 30）
  --width <px>         比較に使う幅（既定 1080）
  --height <px>        比較に使う高さ（既定 1920）
  --entry <path>       Remotion のエントリ（既定 src/index.ts）
  --out-dir <path>     出力先（既定 tmp/compare）
  --name <label>       出力ファイル名に使う見出し
  --mode <full|decomposed>  合否の当て方（既定 full）
  --pass-avg <n>       平均差の合格基準（既定 5）
  --pass-max <n>       最大差の合格基準（既定 30。decomposed では判定に使わない）
  --review-avg <n>     この値までは「要理由提示」として exit 2（既定 10）
  --bands <spec>       帯の指定。"名前:y0-y1" をカンマ区切り（既定: 高さの比率から自動。"none" で無効）
  --band-warn <n>      帯の平均差の警告値（既定 12）
  --row-threshold <n>  差分領域とみなす行平均差（既定 20）
  --no-preview         横並び・オーバーレイの画像を作らない
  --no-heatmap         差分ヒートマップを書き出さない
  --help               この説明
`;

type Args = Record<string, string | boolean>;

function parseArgs(argv: string[]): Args {
  const out: Args = {};
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]!;
    if (!a.startsWith('--')) continue;
    const key = a.slice(2);
    const next = argv[i + 1];
    if (next === undefined || next.startsWith('--')) {
      out[key] = true;
    } else {
      out[key] = next;
      i++;
    }
  }
  return out;
}

function str(args: Args, key: string, fallback?: string): string {
  const v = args[key];
  if (typeof v === 'string') return v;
  if (fallback !== undefined) return fallback;
  console.error(`❌ --${key} が必要です（--help で使い方）`);
  process.exit(1);
}

function num(args: Args, key: string, fallback: number): number {
  const v = args[key];
  if (typeof v !== 'string') return fallback;
  const n = Number(v);
  if (Number.isNaN(n)) {
    console.error(`❌ --${key} には数値を指定してください: ${v}`);
    process.exit(1);
  }
  return n;
}

/** 案件フォルダ（cwd）の node_modules から解決する。 */
function loadSharp(): any {
  const req = createRequire(path.join(process.cwd(), 'package.json'));
  try {
    return req('sharp');
  } catch {
    console.error('❌ sharp が見つかりません。このフォルダで `npm i` を実行してください');
    process.exit(1);
  }
}

/** シーンの尺の一覧から、指定シーンの「比率 at の位置」のフレーム番号を出す。 */
function frameFromScenes(durations: number[], sceneIndex: number, at: number, fps: number): number {
  if (sceneIndex < 0 || sceneIndex >= durations.length) {
    console.error(`❌ --scene は 0〜${durations.length - 1} の範囲で指定してください`);
    process.exit(1);
  }
  let cum = 0;
  for (let i = 0; i < sceneIndex; i++) cum += Math.round(durations[i]! * fps);
  const sceneFrames = Math.round(durations[sceneIndex]! * fps);
  return cum + Math.round(sceneFrames * at);
}

type Band = {name: string; y0: number; y1: number};

/** 帯の指定。未指定なら高さの比率から見出し帯・フッター帯を置く。 */
function resolveBands(spec: string | undefined, H: number): Band[] {
  if (spec === 'none') return [];
  if (!spec) {
    return [
      {name: 'ヘッダー帯', y0: Math.round(H * 0.08), y1: Math.round(H * 0.29)},
      {name: 'フッター帯', y0: Math.round(H * 0.88), y1: Math.round(H * 0.99)},
    ];
  }
  return spec.split(',').map((part) => {
    const m = part.trim().match(/^(.+?):(\d+)-(\d+)$/);
    if (!m) {
      console.error(`❌ --bands は "名前:y0-y1" の形式で指定してください: ${part}`);
      process.exit(1);
    }
    return {name: m[1]!, y0: Number(m[2]), y1: Number(m[3])};
  });
}

/** ① Remotion の静止画を書き出す。--remotion が渡されていればそれをそのまま使う。 */
function renderStill(args: Args, outDir: string, fps: number): string {
  if (typeof args['remotion'] === 'string') {
    return path.resolve(process.cwd(), str(args, 'remotion'));
  }
  const comp = str(args, 'comp');
  const entry = str(args, 'entry', 'src/index.ts');

  let frame: number;
  let label: string;
  if (typeof args['frame'] === 'string') {
    frame = num(args, 'frame', 0);
    label = str(args, 'name', `frame${frame}`);
  } else if (typeof args['scene'] === 'string') {
    const durations = str(args, 'durations').split(',').map((x) => Number(x.trim())).filter((x) => !Number.isNaN(x));
    if (durations.length === 0) {
      console.error('❌ --durations にシーンの尺をカンマ区切りで渡してください');
      process.exit(1);
    }
    const sceneIndex = num(args, 'scene', 0);
    frame = frameFromScenes(durations, sceneIndex, num(args, 'at', 0.9), fps);
    label = str(args, 'name', `scene${sceneIndex}`);
  } else {
    console.error('❌ --frame か、--scene と --durations の組み合わせが必要です（--help）');
    process.exit(1);
  }

  mkdirSync(outDir, {recursive: true});
  const remotionPath = path.join(outDir, `${label}-remotion.png`);
  console.log(`\n🎬 ${comp} / フレーム ${frame}（${fps}fps）を書き出し中...`);
  const result = spawnSync('npx', ['remotion', 'still', entry, comp, remotionPath, `--frame=${frame}`], {
    cwd: process.cwd(),
    stdio: 'inherit',
  });
  if (result.status !== 0) {
    console.error('❌ remotion still に失敗しました（--comp / --entry を確認）');
    process.exit(1);
  }
  return remotionPath;
}

/** ② 見比べ用の画像（横並び・50%オーバーレイ）。合否には使わない。 */
async function writePreviews(sharp: any, figmaBuf: Buffer, remotionBuf: Buffer, W: number, H: number,
                             outDir: string, label: string): Promise<[string, string]> {
  mkdirSync(outDir, {recursive: true});
  const sideBySidePath = path.join(outDir, `${label}-side-by-side.png`);
  await sharp({
    create: {width: W * 2 + 40, height: H + 80, channels: 4, background: {r: 30, g: 30, b: 30, alpha: 1}},
  })
    .composite([
      {input: figmaBuf, left: 10, top: 70},
      {input: remotionBuf, left: W + 30, top: 70},
      {
        input: Buffer.from(
          `<svg width="${W * 2 + 40}" height="60">
            <rect width="100%" height="100%" fill="#1e1e1e"/>
            <text x="${W / 2 + 10}" y="40" font-size="30" fill="#4ec9b0" text-anchor="middle" font-family="sans-serif" font-weight="bold">Figma (設計)</text>
            <text x="${W + 30 + W / 2}" y="40" font-size="30" fill="#ce9178" text-anchor="middle" font-family="sans-serif" font-weight="bold">Remotion (実装)</text>
          </svg>`,
        ),
        top: 0,
        left: 0,
      },
    ])
    .png()
    .toFile(sideBySidePath);

  const overlayPath = path.join(outDir, `${label}-overlay.png`);
  const remotionSemi = await sharp(remotionBuf)
    .ensureAlpha()
    .composite([
      {input: Buffer.from([255, 255, 255, 128]), raw: {width: 1, height: 1, channels: 4}, tile: true, blend: 'dest-in'},
    ])
    .toBuffer();
  await sharp(figmaBuf).composite([{input: remotionSemi, top: 0, left: 0}]).png().toFile(overlayPath);
  return [sideBySidePath, overlayPath];
}

async function main(): Promise<void> {
  const args = parseArgs(process.argv.slice(2));
  if (args['help'] || process.argv.length <= 2) {
    console.log(HELP);
    process.exit(args['help'] ? 0 : 1);
  }

  const figmaPath = path.resolve(process.cwd(), str(args, 'figma'));
  const outDir = path.resolve(process.cwd(), str(args, 'out-dir', path.join('tmp', 'compare')));
  const W = num(args, 'width', 1080);
  const H = num(args, 'height', 1920);
  const fps = num(args, 'fps', 30);
  const mode = str(args, 'mode', 'full');
  if (mode !== 'full' && mode !== 'decomposed') {
    console.error('❌ --mode は full か decomposed です');
    process.exit(1);
  }
  const PASS_AVG = num(args, 'pass-avg', 5);
  const PASS_MAX = num(args, 'pass-max', 30);
  const REVIEW_AVG = num(args, 'review-avg', 10);
  const BAND_WARN = num(args, 'band-warn', 12);
  const ROW_THRESHOLD = num(args, 'row-threshold', 20);
  const bands = resolveBands(typeof args['bands'] === 'string' ? args['bands'] : undefined, H);

  if (!existsSync(figmaPath)) {
    console.error(`❌ Figma PNG が見つかりません: ${figmaPath}`);
    console.error('   Figma でシーンを選択 → File > Export → PNG @1x で書き出して配置してください');
    process.exit(1);
  }

  const sharp = loadSharp();
  const remotionPath = renderStill(args, outDir, fps);
  if (!existsSync(remotionPath)) {
    console.error(`❌ Remotion の出力が見つかりません: ${remotionPath}`);
    process.exit(1);
  }
  const label = path.basename(remotionPath).replace(/-remotion\.png$/i, '').replace(/\.png$/i, '');

  if (!args['no-preview']) {
    console.log('\n🖼  見比べ用の画像を生成中...');
    const figmaBuf = await sharp(figmaPath).resize(W, H, {fit: 'fill'}).toBuffer();
    const remotionBuf = await sharp(remotionPath).resize(W, H, {fit: 'fill'}).toBuffer();
    const [sbs, ov] = await writePreviews(sharp, figmaBuf, remotionBuf, W, H, outDir, label);
    console.log(`   横並び比較:   ${path.relative(process.cwd(), sbs)}`);
    console.log(`   オーバーレイ: ${path.relative(process.cwd(), ov)}`);
    console.log('   ⚠ この2枚を見て「ほぼ一致」と判断してはいけません。合否は下の数値で決めます');
  }

  // ⚠ 両画像とも removeAlpha() で 3 channels に統一してから比較する（混在すると偽差が出る）
  const [figma, remotion] = await Promise.all([
    sharp(figmaPath).resize(W, H, {fit: 'fill'}).removeAlpha().raw().toBuffer(),
    sharp(remotionPath).resize(W, H, {fit: 'fill'}).removeAlpha().raw().toBuffer(),
  ]);

  let sumDiff = 0;
  let maxDiff = 0;
  const total = W * H * 3;
  for (let i = 0; i < total; i++) {
    const d = Math.abs(figma[i]! - remotion[i]!);
    sumDiff += d;
    if (d > maxDiff) maxDiff = d;
  }
  const avgDiff = sumDiff / total;

  // 行ごとの平均差 → 差分領域（連続する y 範囲）
  const rowDiffs: number[] = [];
  for (let y = 0; y < H; y++) {
    let rowSum = 0;
    for (let x = 0; x < W; x++) {
      const i = (y * W + x) * 3;
      rowSum += Math.abs(figma[i]! - remotion[i]!) + Math.abs(figma[i + 1]! - remotion[i + 1]!) + Math.abs(figma[i + 2]! - remotion[i + 2]!);
    }
    rowDiffs.push(rowSum / (W * 3));
  }
  const regions: Array<{start: number; end: number; avg: number}> = [];
  let inDiff = false;
  let regionStart = 0;
  for (let y = 0; y < H; y++) {
    if (rowDiffs[y]! > ROW_THRESHOLD) {
      if (!inDiff) {
        regionStart = y;
        inDiff = true;
      }
    } else if (inDiff) {
      const slice = rowDiffs.slice(regionStart, y);
      regions.push({start: regionStart, end: y - 1, avg: slice.reduce((a, b) => a + b, 0) / slice.length});
      inDiff = false;
    }
  }
  if (inDiff) {
    const slice = rowDiffs.slice(regionStart);
    regions.push({start: regionStart, end: H - 1, avg: slice.reduce((a, b) => a + b, 0) / slice.length});
  }

  // 帯の平均差（全体平均では埋もれる文言差・位置差を表に出す）
  const bandAvg = (y0: number, y1: number): number => {
    const a = Math.max(0, Math.min(H, y0));
    const b = Math.max(0, Math.min(H, y1));
    if (b <= a) return 0;
    let s = 0;
    for (let y = a; y < b; y++) {
      for (let x = 0; x < W; x++) {
        const i = (y * W + x) * 3;
        s += Math.abs(figma[i]! - remotion[i]!) + Math.abs(figma[i + 1]! - remotion[i + 1]!) + Math.abs(figma[i + 2]! - remotion[i + 2]!);
      }
    }
    return s / ((b - a) * W * 3);
  };

  // 差分ヒートマップ（赤＝差が大きい、黒＝一致）
  let heatmapPath = '';
  if (!args['no-heatmap']) {
    const heatmap = Buffer.alloc(W * H * 3);
    for (let i = 0; i < W * H; i++) {
      const dR = Math.abs(figma[i * 3]! - remotion[i * 3]!);
      const dG = Math.abs(figma[i * 3 + 1]! - remotion[i * 3 + 1]!);
      const dB = Math.abs(figma[i * 3 + 2]! - remotion[i * 3 + 2]!);
      heatmap[i * 3] = Math.min(255, ((dR + dG + dB) / 3) * 3);
      heatmap[i * 3 + 1] = 0;
      heatmap[i * 3 + 2] = 0;
    }
    heatmapPath = remotionPath.replace(/\.png$/i, '') + '-diff-heatmap.png';
    mkdirSync(path.dirname(heatmapPath), {recursive: true});
    await sharp(heatmap, {raw: {width: W, height: H, channels: 3}}).png().toFile(heatmapPath);
  }

  console.log('');
  console.log(`🔍 pixel diff（removeAlpha + 3 channels / mode=${mode}）`);
  console.log(`   Figma:    ${path.relative(process.cwd(), figmaPath)}`);
  console.log(`   Remotion: ${path.relative(process.cwd(), remotionPath)}`);
  console.log('');
  console.log(`   平均ピクセル差: ${avgDiff.toFixed(2)} （基準 < ${PASS_AVG}）`);
  console.log(`   最大ピクセル差: ${maxDiff} （基準 < ${PASS_MAX}${mode === 'decomposed' ? ' / decomposed では参考値' : ''}）`);

  let bandWarn = 0;
  for (const b of bands) {
    const v = bandAvg(b.y0, b.y1);
    const warn = v > BAND_WARN;
    if (warn) bandWarn++;
    console.log(`   ${b.name}(y${b.y0}-${b.y1}) 平均差: ${v.toFixed(2)}${warn ? ' ⚠ 文言・位置の差の可能性 — 1文字ずつ目視照合' : ''}`);
  }

  console.log('');
  if (regions.length === 0) {
    console.log(`   差分領域なし（全行で行平均 < ${ROW_THRESHOLD}）`);
  } else {
    console.log(`   差分領域（行平均 > ${ROW_THRESHOLD}）:`);
    for (const r of regions) {
      console.log(`     y=${r.start}-${r.end} (h=${r.end - r.start + 1}, 平均差=${r.avg.toFixed(1)})`);
    }
  }
  if (heatmapPath) {
    console.log(`   差分ヒートマップ: ${path.relative(process.cwd(), heatmapPath)}`);
  }
  console.log('');

  const maxOk = mode === 'decomposed' ? true : maxDiff < PASS_MAX;
  if (avgDiff < PASS_AVG && maxOk) {
    console.log(`✅ 合格（平均差 < ${PASS_AVG}${mode === 'full' ? ` / 最大差 < ${PASS_MAX}` : ''}）`);
    if (bandWarn > 0) {
      console.log(`   ただし帯が ${bandWarn} 件⚠。帯の文字を目視照合してから合格にすること`);
    }
    process.exit(0);
  }
  if (avgDiff < REVIEW_AVG && maxOk) {
    console.log(`🟡 要理由提示（平均差 ${avgDiff.toFixed(2)} が ${PASS_AVG}〜${REVIEW_AVG} の範囲）`);
    console.log('   半透明描画の構造的な差／フォント描画差の累積 などの理由を明示し、レビュー側の許容判断を仰ぐ');
    console.log('   差分領域が数十px以上に広がっている場合は、フォント差ではなく配置ズレを疑う');
    process.exit(2);
  }
  console.log('❌ 不合格 — 実装を直してから、もう一度このコマンドを実行する');
  process.exit(1);
}

main().catch((err) => {
  console.error('❌ エラー:', err);
  process.exit(1);
});
