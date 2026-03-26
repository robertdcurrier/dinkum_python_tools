#!/usr/bin/env bash
# Convert *bd files one at a time to individual .dba files.
# Usage: batch_dbd2asc.sh <src_dir> <out_dir> <cache_dir>

set -euo pipefail

SRC_DIR="${1:?Usage: $0 <src_dir> <out_dir> <cache_dir>}"
OUT_DIR="${2:?Usage: $0 <src_dir> <out_dir> <cache_dir>}"
CACHE_DIR="${3:?Usage: $0 <src_dir> <out_dir> <cache_dir>}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

mkdir -p "$OUT_DIR"

count=0
for f in "$SRC_DIR"/*.*bd; do
    [ -f "$f" ] || continue
    base="$(basename "$f")"
    name="${base%.*}"
    python3 "$SCRIPT_DIR/dbd2asc.py" \
        -c "$CACHE_DIR" "$f" > "$OUT_DIR/${name}.dba"
    count=$((count + 1))
done

echo "Converted $count files to $OUT_DIR"
