#!/usr/bin/env bash
# Merge flight+science DBA files one pair at a time.
# Usage: batch_dba_merge.sh <flight_dir> <science_dir> <out_dir>
#
# Pairs files by segment number: *-0.dba flight + *-0.dba science.
# Skips files with no matching pair.

set -euo pipefail

FLIGHT_DIR="${1:?Usage: $0 <flight_dir> <science_dir> <out_dir>}"
SCIENCE_DIR="${2:?Usage: $0 <flight_dir> <science_dir> <out_dir>}"
OUT_DIR="${3:?Usage: $0 <flight_dir> <science_dir> <out_dir>}"

mkdir -p "$OUT_DIR"

count=0
skipped=0
for flight in "$FLIGHT_DIR"/*.dba; do
    [ -f "$flight" ] || continue
    base="$(basename "$flight")"
    science="$SCIENCE_DIR/$base"
    if [ ! -f "$science" ]; then
        skipped=$((skipped + 1))
        continue
    fi
    /opt/dinkum/dba_merge "$flight" "$science" \
        > "$OUT_DIR/$base"
    count=$((count + 1))
done

echo "Merged $count pairs to $OUT_DIR ($skipped skipped)"
