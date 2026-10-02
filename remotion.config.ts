// Remotion の設定。動画編集ツール（Remotion）の CLI が studio / render / still の前に必ず読み込む。
//
// ここには2つのことだけ書いてある:
//   1. 素材フォルダの場所（assets/）。staticFile() はここからの相対パスになる
//   2. 書き出しの承諾ゲート。`remotion render` のときだけ scripts/approve.py --check を通す
//
// 2 が config にある理由: package.json の npm run render だけを守ると、
// `npx remotion render ...` を直接叩いた瞬間に決まりが素通りする。
// CLI がどの道この設定ファイルを読むので、ここに置けば経路によらず止まる。

import {Config} from '@remotion/cli/config';
import {spawnSync} from 'node:child_process';

// 素材フォルダ（既定の public/ ではなく assets/ を使う）
Config.setPublicDir('assets');

// ---------------------------------------------------------------------------
// 書き出しの承諾ゲート
// ---------------------------------------------------------------------------
const VIDEO_EXT = /\.(mp4|mov|mkv|webm|gif|m4a|mp3|wav|aac)$/i;

const positionalArgs = (argv: string[]): string[] => {
  const out: string[] = [];
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a.startsWith('-')) {
      continue;
    }
    out.push(a);
  }
  return out;
};

const gate = () => {
  const argv = process.argv.slice(2);
  const args = positionalArgs(argv);
  // 最初の位置引数がサブコマンド。render 以外（studio / still / compositions …）は素通し。
  if (args[0] !== 'render') {
    return;
  }
  const rest = args.slice(1);
  let composition = '';
  let out = '';
  for (const a of rest) {
    if (VIDEO_EXT.test(a)) {
      out = a;
    } else if (a.endsWith('.ts') || a.endsWith('.tsx') || a.endsWith('.js') || a.includes('/')) {
      // エントリーポイント（src/index.ts）。承諾の判定には使わない
    } else if (!composition) {
      composition = a;
    }
  }
  const checkArgs = ['scripts/approve.py', '--check'];
  if (composition) {
    checkArgs.push('--composition', composition);
  }
  if (out) {
    checkArgs.push('--out', out);
  }
  const res = spawnSync('python3', checkArgs, {stdio: 'inherit'});
  if (res.status !== 0) {
    // ここで止める。承諾の記録（out/approval.json）が無い／古いということ。
    process.exit(1);
  }
};

gate();
