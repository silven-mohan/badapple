#!/usr/bin/env python3
"""
Convert PNG frames in frames/ into ASCII text frames in ascii_frames/.

Approach (same family of techniques libcaca/aalib use internally):
  1. Brightness ramp for flat regions:
       bright (>=200)   -> 'Q'
       midtone (100-199) -> ordered-dithered 'b'/'y'  (mimics libcaca's dithering)
       dark (40-99)      -> '.'
       black (<40)       -> ' '
  2. Sobel gradient magnitude/direction for edges, split into three
     strength tiers so edges fade in and sharpen smoothly instead of
     snapping straight from a brightness glyph to a hard outline glyph:
       soft  (threshold      <= mag < threshold*1.6) -> '.' ',' ';'
       core  (threshold*1.6  <= mag < threshold*2.6) -> ':' '<' 'x' '^' 'n' 'z' '>'
       sharp (mag >= threshold*2.6)                  -> ']' '?' '*' 'Y' 'j' '+'
     Within each tier, glyphs are scattered with a checkerboard/3-way
     dither (keyed on pixel position) rather than repeating a single
     character across a whole edge run, which is what makes long edges
     read as sharp+textured instead of a solid stripe of one symbol.
  3. Optional 24-bit ANSI color per character (--color), sampled from the
     original pixel, for a libcaca-style colored render.

Since frames were pre-scaled by ffmpeg to exactly cols x rows, no resizing
happens here -> this is fast enough to run frame-by-frame smoothly.
"""

import argparse
import os
import sys
import numpy as np
from PIL import Image

RESET = "\x1b[0m"

def sobel(gray: np.ndarray):
    """Manual 3x3 Sobel (no scipy dependency)."""
    p = np.pad(gray, 1, mode="edge").astype(np.float32)

    gx = (
        -p[0:-2, 0:-2] + p[0:-2, 2:]
        - 2 * p[1:-1, 0:-2] + 2 * p[1:-1, 2:]
        - p[2:, 0:-2] + p[2:, 2:]
    )
    gy = (
        -p[0:-2, 0:-2] - 2 * p[0:-2, 1:-1] - p[0:-2, 2:]
        + p[2:, 0:-2] + 2 * p[2:, 1:-1] + p[2:, 2:]
    )
    return gx, gy


def edge_chars(gx: np.ndarray, gy: np.ndarray, threshold: float):
    """Return (is_edge, char_array) for pixels with a meaningful gradient.

    Not allowed: '/', '\\', '|', '-', '=', '_'.
    '~' has been dropped entirely (it was over-used, repeating on every
    near-horizontal edge pixel). In its place, edge strength is split
    into three tiers built from the requested glyph set
    (* ? ^ ] j Y n + . , ;), each scattered by pixel position so no
    single glyph dominates a run of edge pixels:

      soft  -> '.' ',' ';'                      (weak / transitional edges)
      core  -> ':' '<' 'x' '^' 'n' 'z' '>'       (normal directional edges)
      sharp -> ']' '?' '*' 'Y' 'j' '+'           (strong outlines/corners only)
    """
    mag = np.sqrt(gx * gx + gy * gy)
    is_edge = mag > threshold

    # angle of the gradient itself; edge direction is perpendicular to it.
    angle = (np.degrees(np.arctan2(gy, gx)) + 180.0) % 180.0  # 0-180

    h, w = angle.shape
    yy, xx = np.indices((h, w))
    checker = (xx + yy) % 2 == 0   # 2-way scatter for core/sharp tiers
    bucket3 = (xx + yy) % 3        # 3-way scatter for the soft tier

    # ---- core tier: directional glyph per ~22.5deg angle bin ----
    #   near-vertical      -> ':'
    #   vertical-leaning   -> '<' / '>'
    #   diagonal           -> 'x' / 'z'
    #   near-horizontal    -> '^' / 'n'  (dithered, replaces the old '~')
    core = np.full(angle.shape, ":", dtype="<U1")
    core[(angle >= 11.25) & (angle < 33.75)] = "<"
    core[(angle >= 33.75) & (angle < 56.25)] = "x"
    horiz = (angle >= 56.25) & (angle < 101.25)
    core[horiz & checker] = "^"
    core[horiz & ~checker] = "n"
    core[(angle >= 101.25) & (angle < 123.75)] = "z"
    core[(angle >= 123.75) & (angle < 146.25)] = ">"
    core[(angle >= 146.25) & (angle < 168.75)] = ":"

    # ---- soft tier: faint pre-edge glyphs that ease flat brightness
    # regions into a real edge, scattered 3-way so they read as texture
    # rather than a solid outline ----
    soft = np.full(angle.shape, ".", dtype="<U1")
    soft[bucket3 == 1] = ","
    soft[bucket3 == 2] = ";"

    # ---- sharp tier: only the strongest gradients (true outlines and
    # corners) earn these bolder glyphs, so they stay rare accents
    # instead of turning the frame into noise ----
    sharp = np.full(angle.shape, "]", dtype="<U1")
    sharp[(angle >= 11.25) & (angle < 33.75)] = "?"
    sharp[(angle >= 33.75) & (angle < 56.25)] = "*"
    horiz_sharp = (angle >= 56.25) & (angle < 101.25)
    sharp[horiz_sharp & checker] = "Y"
    sharp[horiz_sharp & ~checker] = "j"
    sharp[(angle >= 101.25) & (angle < 146.25)] = "+"

    strong_t = threshold * 1.6
    sharp_t = threshold * 2.6
    chars = np.where(mag >= sharp_t, sharp, np.where(mag >= strong_t, core, soft))
    return is_edge, chars


def brightness_chars(gray: np.ndarray):
    h, w = gray.shape
    chars = np.full((h, w), " ", dtype="<U1")

    yy, xx = np.indices((h, w))
    checker = (xx + yy) % 2 == 0

    chars[gray >= 200] = "Q"
    mid = (gray >= 100) & (gray < 200)
    chars[mid & checker] = "b"
    chars[mid & ~checker] = "y"
    chars[(gray >= 40) & (gray < 100)] = "."
    # gray < 40 stays as ' '
    return chars


def frame_to_ascii(img: Image.Image, edge_threshold: float, color: bool) -> str:
    rgb = np.array(img.convert("RGB"))
    gray = np.array(img.convert("L"), dtype=np.float32)

    gx, gy = sobel(gray)
    is_edge, e_chars = edge_chars(gx, gy, edge_threshold)
    b_chars = brightness_chars(gray)

    final = np.where(is_edge, e_chars, b_chars)

    h, w = final.shape
    lines = []
    if not color:
        for y in range(h):
            lines.append("".join(final[y]))
        return "\n".join(lines)

    # Color mode: prefix each character with a truecolor escape code.
    # Batches runs of identical color to keep file size / draw cost reasonable.
    for y in range(h):
        row_chars = final[y]
        row_rgb = rgb[y]
        parts = []
        last_color = None
        for x in range(w):
            r, g, b = row_rgb[x]
            col = (r, g, b)
            if col != last_color:
                parts.append(f"\x1b[38;2;{r};{g};{b}m")
                last_color = col
            parts.append(row_chars[x])
        parts.append(RESET)
        lines.append("".join(parts))
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames-dir", default="frames")
    ap.add_argument("--out-dir", default="ascii_frames")
    ap.add_argument("--edge-threshold", type=float, default=120.0,
                     help="Lower = more edges detected (more edge glyphs).")
    ap.add_argument("--color", action="store_true",
                     help="Embed 24-bit ANSI color codes (bigger files, richer look).")
    args = ap.parse_args()

    if not os.path.isdir(args.frames_dir):
        sys.exit(f"No such directory: {args.frames_dir}. Run the ffmpeg extraction step first.")

    os.makedirs(args.out_dir, exist_ok=True)

    frame_files = sorted(
        f for f in os.listdir(args.frames_dir) if f.lower().endswith(".png")
    )
    if not frame_files:
        sys.exit(f"No PNG frames found in {args.frames_dir}/")

    for meta in ("fps.txt", "cols.txt", "rows.txt"):
        src = os.path.join(args.frames_dir, meta)
        if os.path.exists(src):
            with open(src) as fh, open(os.path.join(args.out_dir, meta), "w") as out:
                out.write(fh.read())

    total = len(frame_files)
    for i, fname in enumerate(frame_files, 1):
        img = Image.open(os.path.join(args.frames_dir, fname))
        ascii_text = frame_to_ascii(img, args.edge_threshold, args.color)
        out_name = os.path.splitext(fname)[0] + ".txt"
        with open(os.path.join(args.out_dir, out_name), "w") as f:
            f.write(ascii_text)
        if i % 10 == 0 or i == total:
            print(f"\rConverted {i}/{total} frames", end="", flush=True)

    print(f"\nDone. ASCII frames written to {args.out_dir}/")


if __name__ == "__main__":
    main()
