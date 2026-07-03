#!/usr/bin/env bash
# Phase 1 一键 demo: 渲染 + 自动标注 + 校验图
# 用法: bash scripts/run_demo.sh [name] [azimuth] [elevation]
set -euo pipefail

BLENDER="${BLENDER:-/Applications/Blender.app/Contents/MacOS/Blender}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BLEND="${BLEND:-$ROOT/data/蓝色香烟盒子.blend}"

NAME="${1:-demo_000}"
AZ="${2:-35}"
EL="${3:-30}"
RES="${RES:-1024x1024}"
ENGINE="${ENGINE:-EEVEE}"

echo "[run_demo] blender render + annotate ($NAME, az=$AZ el=$EL)"
"$BLENDER" --background "$BLEND" \
    --python "$ROOT/src/blender/render_annotate.py" -- \
    --out "$ROOT/output" --name "$NAME" --res "$RES" \
    --engine "$ENGINE" --azimuth "$AZ" --elevation "$EL" --bg grey

echo "[run_demo] draw overlay for visual gate"
python3 "$ROOT/src/verify/draw_labels.py" --out "$ROOT/output" --name "$NAME"

echo "[run_demo] done. see output/debug/${NAME}_overlay.png"
