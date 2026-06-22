#!/usr/bin/env python3
"""Dump the kaleido intensity field to grayscale PNGs (stdlib only) for
cache-off vs cache-on visual comparison at the same frame."""
import struct
import zlib

from ac_ui import visualizer as V
from bench_warp_e2e import music_bars


def write_png(path, rows, cols, field):
    raw = bytearray()
    for y in range(rows):
        raw.append(0)  # filter type 0
        base = y * cols
        for x in range(cols):
            v = field[base + x]
            g = 255 if v >= 1.0 else (0 if v <= 0.0 else int(v * 255))
            raw.append(g)

    def chunk(tag, data):
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xffffffff)

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", cols, rows, 8, 0, 0, 0, 0)  # 8-bit grayscale
    idat = zlib.compress(bytes(raw), 9)
    with open(path, "wb") as f:
        f.write(sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b""))


def grab(h, w, frames, *, cache, kmax=16, thresh=0.035, fps=60.0):
    V._WARP_CACHE = cache
    if cache:
        V._WARP_CACHE_KMAX = kmax
        V._WARP_CACHE_THRESH = thresh
    st = {}
    dt = 1.0 / fps
    dot_rows, dot_cols = h * 4, w * 2
    field = None
    for i in range(frames):
        bars = music_bars(w, i * dt)
        V.kaleido_tunnel_render_lines(bars, h, w, st, use_color=True, game_tag=None)
        field, _hue, _a, _b = V._feedback_buffers(st, dot_rows, dot_cols)
    return dot_rows, dot_cols, list(field)


if __name__ == "__main__":
    h, w = 30, 160
    for frame in (90, 150):
        r, c, off = grab(h, w, frame, cache=False)
        _, _, on = grab(h, w, frame, cache=True, kmax=16, thresh=0.035)
        write_png(f"/tmp/kaleido_off_{frame}.png", r, c, off)
        write_png(f"/tmp/kaleido_on_{frame}.png", r, c, on)
        print(f"frame {frame}: wrote /tmp/kaleido_off_{frame}.png /tmp/kaleido_on_{frame}.png")
