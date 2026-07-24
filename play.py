#!/usr/bin/env python3
"""
Play back ascii_frames/*.txt in the terminal.

Smoothness tricks (same idea used by real terminal video players):
  - Never call `clear` between frames (that erases + redraws = flicker).
    Instead move the cursor to (0,0) with '\\x1b[H' and overwrite in place.
  - Build the whole frame as one string and issue a single write() + flush(),
    so the terminal receives it as one chunk instead of many small writes.
  - Pace playback against a wall-clock deadline per frame (not a fixed sleep),
    so rendering time doesn't accumulate drift over a long video.
"""

import argparse
import os
import sys
import time

HIDE_CURSOR = "\x1b[?25l"
SHOW_CURSOR = "\x1b[?25h"
CURSOR_HOME = "\x1b[H"
CLEAR_SCREEN = "\x1b[2J"


def read_meta(frames_dir: str, name: str, default):
    path = os.path.join(frames_dir, name)
    if os.path.exists(path):
        with open(path) as f:
            return f.read().strip()
    return default


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="ascii_frames")
    ap.add_argument("--fps", type=float, default=None,
                     help="Overrides fps.txt written during extraction if given.")
    ap.add_argument("--loop", action="store_true")
    args = ap.parse_args()

    if not os.path.isdir(args.dir):
        sys.exit(f"No such directory: {args.dir}. Run the conversion step first.")

    fps = args.fps or float(read_meta(args.dir, "fps.txt", 15))
    frame_interval = 1.0 / fps

    frame_files = sorted(
        f for f in os.listdir(args.dir) if f.lower().endswith(".txt")
        and f not in ("fps.txt", "cols.txt", "rows.txt")
    )
    if not frame_files:
        sys.exit(f"No ASCII frames found in {args.dir}/")

    # Preload frames into memory: keeps per-frame disk latency out of the
    # playback loop, which is what actually causes stutter on longer clips.
    frames = []
    for fname in frame_files:
        with open(os.path.join(args.dir, fname)) as f:
            frames.append(f.read())

    out = sys.stdout
    out.write(CLEAR_SCREEN + HIDE_CURSOR)
    out.flush()

    try:
        while True:
            start = time.perf_counter()
            for frame in frames:
                frame_start = time.perf_counter()
                out.write(CURSOR_HOME + frame)
                out.flush()
                elapsed = time.perf_counter() - frame_start
                remaining = frame_interval - elapsed
                if remaining > 0:
                    time.sleep(remaining)
            if not args.loop:
                break
    except KeyboardInterrupt:
        pass
    finally:
        out.write(SHOW_CURSOR)
        out.flush()


if __name__ == "__main__":
    main()
