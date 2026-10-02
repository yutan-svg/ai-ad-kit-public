#!/bin/bash
# 配布用の zip を作る。このスクリプト自体は配布物に含めない。
#
#   bash build_zip.sh [出力先ディレクトリ] [版の接尾辞]
#
# 既定の出力先は ~/Downloads。ファイル名は ai-ad-kit-<日付><接尾辞>.zip。
# 接尾辞を省いたときは、同じ日付の zip が既にあれば b, c, d… と自動で付ける
# （同じ日に作り直した版が、前の版を黙って上書きしないため）。
# 除外するもの: node_modules / .env / out / tmp / .git / .whisper-models / 生成したテイク /
#               キャッシュ / このスクリプト自身
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)"
OUT_DIR="${1:-$HOME/Downloads}"
SUFFIX="${2:-}"
DATE="$(date +%Y%m%d)"
mkdir -p "$OUT_DIR"

if [ -z "$SUFFIX" ]; then
  # 同じ日付の zip があれば b, c, … と繰り上げる
  if [ -e "$OUT_DIR/ai-ad-kit-$DATE.zip" ]; then
    for L in b c d e f g h i j k l m n o p q r s t u v w x y z; do
      if [ ! -e "$OUT_DIR/ai-ad-kit-$DATE$L.zip" ]; then SUFFIX="$L"; break; fi
    done
  fi
fi
NAME="ai-ad-kit-$DATE$SUFFIX"
ZIP="$OUT_DIR/$NAME.zip"

rm -f "$ZIP"

cd "$SRC"
zip -r -q "$ZIP" . \
  -x '*/node_modules/*' 'node_modules/*' \
  -x '.env' \
  -x 'out/*' '*/out/*' \
  -x 'tmp/*' '*/tmp/*' \
  -x '.git/*' '*/.git/*' \
  -x '.whisper-models/*' \
  -x 'costs/*' \
  -x 'assets/videos/takes/*' \
  -x '*/__pycache__/*' '__pycache__/*' \
  -x '*.pyc' \
  -x '.DS_Store' '*/.DS_Store' \
  -x 'build_zip.sh'

echo "作成しました: $ZIP"
echo "中身:"
unzip -l "$ZIP"
