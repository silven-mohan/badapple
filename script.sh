#!/usr/bin/env bash
# Extract video frames sized to EXACTLY fill the current terminal (1 pixel = 1 char cell).
# Usage: ./1_extract_frames.sh input.mp4 [fps]

set -euo pipefail

INPUT="${1:?Usage: $0 input.mp4 [fps]}"
FPS="${2:-15}"          # 15fps is a good balance of smoothness vs. frame count/CPU

COLS=$(tput cols)
ROWS=$(tput lines)

# Reserve 1 line so the terminal prompt/status doesn't cause scroll-jitter.
ROWS=$((ROWS - 1))

echo "Terminal size: ${COLS}x${ROWS} (cols x rows) @ ${FPS}fps"

rm -rf frames
mkdir -p frames

# scale=COLS:ROWS forces the frame to exactly COLS x ROWS pixels -> 1px = 1 char cell.
# This deliberately ignores source aspect ratio to fill the whole screen, since ASCII
# terminal cells are not square anyway (this is corrected for in the python conversion
# step below via the dithering density, not by ffmpeg).
ffmpeg -y -i "$INPUT" \
    -vf "fps=${FPS},scale=${COLS}:${ROWS}:flags=lanczos" \
    -pix_fmt rgb24 \
    frames/frame_%05d.png

echo "$FPS" > frames/fps.txt
echo "$COLS" > frames/cols.txt
echo "$ROWS" > frames/rows.txt

echo "Done. $(ls frames/*.png | wc -l) frames written to frames/"
