#!/usr/bin/env python3
"""ac-ui exhaustive performance benchmark.

Measures every per-frame subsystem so you can see where time goes and decide
where to spend optimisation effort. Nothing here mutates app state on disk.

Usage:
    .venv/bin/python benchmark.py                 # full run, human report
    .venv/bin/python benchmark.py --quick         # fewer iterations
    .venv/bin/python benchmark.py --json          # machine-readable
    .venv/bin/python benchmark.py --size 36x110   # visualizer/frame size
    .venv/bin/python benchmark.py --cava-src ~/cava-fork   # also bench cavacore

Reads as: lower ms = faster; "fps ceiling" = 1000/ms (single-thread, this op
alone); "%60" = share of a 16.7 ms / 60 fps frame budget this op would consume.
"""
from __future__ import annotations

import argparse
import io
import math
import os
import statistics
import subprocess
import sys
import time

FRAME_BUDGET_MS = 1000.0 / 60.0  # 16.67 ms


# ── timing core ──────────────────────────────────────────────────────────────
def median_ms(fn, runs, warmup=8):
    for _ in range(warmup):
        fn()
    samples = []
    for _ in range(runs):
        t = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t) * 1000.0)
    samples.sort()
    return samples[len(samples) // 2]


def _row(name, ms, extra=""):
    fps = 1000.0 / ms if ms > 0 else float("inf")
    pct = ms / FRAME_BUDGET_MS * 100.0
    return {"name": name, "ms": ms, "fps_ceiling": fps, "pct60": pct, "note": extra}


def _print_table(title, rows, *, show_fps=True):
    print(f"\n[{title}]")
    if not rows:
        print("    (skipped)")
        return
    nw = max(len(r["name"]) for r in rows)
    for r in rows:
        line = f"    {r['name']:<{nw}}  {r['ms']:8.3f} ms"
        if show_fps:
            line += f"  {r['fps_ceiling']:7.0f} fps  {r['pct60']:5.0f}%/60"
        if r.get("note"):
            line += f"   {r['note']}"
        print(line)


# ── synthetic inputs ─────────────────────────────────────────────────────────
def fake_bars(n, t=0.0):
    return tuple(max(0.0, abs(math.sin(t * 2.0 + i * 0.2))) * 0.7 for i in range(n))


# ── sections ─────────────────────────────────────────────────────────────────
def bench_startup(runs):
    """Cold `import ac_ui.ui` in a fresh interpreter (subprocess)."""
    code = "import time;s=time.perf_counter();import ac_ui.ui;print((time.perf_counter()-s)*1000)"
    samples = []
    for _ in range(max(5, runs // 2)):
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        if out.stdout.strip():
            samples.append(float(out.stdout))
    if not samples:
        return []
    samples.sort()
    return [_row("import ac_ui.ui (cold)", samples[len(samples) // 2])]


def bench_visualizers(size, runs):
    """Every visualizer mode, compiled (native) vs pure-Python fallback."""
    import ac_ui.visualizer as V
    from ac_ui.audio_snapshot import build_live_audio_snapshot
    from ac_ui.constants import VIS_MODES
    from ac_ui.visualizer import VisFrameCtx, render_frame

    h, w = size
    rows = []
    for mode in VIS_MODES:
        st, au = {}, {}

        def one():
            bars = fake_bars(w, time.time())
            snap = build_live_audio_snapshot(bars, au, frame_dt=1 / 60, fallback_bar_count=w)
            render_frame(mode, list(bars), h, w, VisFrameCtx(st, use_color=True,
                                                             features=snap.features, snapshot=snap))

        try:
            native = median_ms(one, runs)
            saved = V._vizfast
            V._vizfast = None
            st.clear()
            pure = median_ms(one, runs)
            V._vizfast = saved
            note = f"native; pure-py {pure:6.2f}ms ({pure / native:.1f}x)" if saved else "no native build"
            rows.append(_row(mode, native, note))
        except Exception as e:  # noqa: BLE001 — a broken mode shouldn't abort the run
            rows.append({"name": mode, "ms": 0.0, "fps_ceiling": 0, "pct60": 0, "note": f"ERROR {e}"})
    rows.sort(key=lambda r: r["ms"], reverse=True)
    return rows


def bench_chrome(size, runs):
    from ac_ui.layout import build_box
    from ac_ui.layout_preview import build_layout_preview

    h, w = size
    body = [f"line {i} of content" for i in range(max(1, h - 2))]
    rows = [
        _row(f"build_box ({w}w x {h}h)", median_ms(
            lambda: build_box(body, body, maxw_override=w, title="t", title2="x"), runs)),
        _row(f"build_layout_preview ({w}x{h})", median_ms(
            lambda: build_layout_preview(w, h), max(50, runs // 4))),
    ]
    return rows


def bench_audio(runs):
    from ac_ui.audio_snapshot import build_live_audio_snapshot
    au = {}
    bars = fake_bars(100)
    return [_row("build_live_audio_snapshot + features", median_ms(
        lambda: build_live_audio_snapshot(fake_bars(100, time.time()), au,
                                          frame_dt=1 / 60, fallback_bar_count=100), runs))]


def bench_render_write(size, runs):
    """The differential terminal writer, on a fully-changing frame (worst case)."""
    from ac_ui import term
    h, w = size
    counter = {"n": 0}

    def one():
        counter["n"] += 1
        # every line changes every frame -> exercises the full re-emit path
        lines = [f"\x1b[38;5;{(counter['n'] + i) % 256}m" + ("#" * (w - 1)) + "\x1b[0m" for i in range(h)]
        real = sys.stdout
        sys.stdout = io.StringIO()
        try:
            term.render(lines, w, h)
        finally:
            sys.stdout = real

    return [_row(f"render() full-change {w}x{h}", median_ms(one, runs))]


def bench_full_frame(size, runs):
    """Component breakdown of one representative heavy (kaleido) frame."""
    import ac_ui.visualizer as V
    from ac_ui.audio_snapshot import build_live_audio_snapshot
    from ac_ui.layout import build_box
    from ac_ui.visualizer import VisFrameCtx, render_frame

    h, w = size
    st, au = {}, {}

    def snapshot():
        return build_live_audio_snapshot(fake_bars(w, time.time()), au, frame_dt=1 / 60,
                                         fallback_bar_count=w)

    snap_holder = {"s": snapshot()}

    def do_snap():
        snap_holder["s"] = snapshot()

    def do_render():
        s = snap_holder["s"]
        st["_lines"] = render_frame("kaleido_tunnel", list(fake_bars(w, time.time())), h, w,
                                    VisFrameCtx(st, use_color=True, features=s.features, snapshot=s))

    def do_box():
        ln = st.get("_lines") or [""]
        build_box(ln, ln, maxw_override=w, title="kaleido", title2="x", lines_fitted=True)

    rows = [
        _row("  audio snapshot+features", median_ms(do_snap, runs)),
        _row("  kaleido render", median_ms(do_render, runs)),
        _row("  box chrome", median_ms(do_box, runs)),
    ]
    total = sum(r["ms"] for r in rows)
    rows.append(_row("  = full heavy frame", total, f"{1000 / total:.0f} fps ceiling"))
    return rows


def bench_cava(cava_src, runs):
    """Optional: compile + micro-bench the cava fork's cavacore (active + idle)."""
    src_dir = os.path.expanduser(cava_src)
    core = os.path.join(src_dir, "cavacore.c")
    if not os.path.isfile(core):
        return [{"name": f"cavacore.c not found in {src_dir}", "ms": 0, "fps_ceiling": 0, "pct60": 0, "note": "skipped"}]
    harness = os.path.join("/tmp", "_acui_cava_bench.c")
    with open(harness, "w") as fh:
        fh.write(_CAVA_HARNESS)
    out_bin = "/tmp/_acui_cava_bench"
    cc = subprocess.run(["gcc", "-O3", "-funroll-loops", f"-I{src_dir}", harness, core,
                         "-o", out_bin, "-lfftw3", "-lm"], capture_output=True, text=True)
    if cc.returncode != 0:
        return [{"name": "cavacore build failed", "ms": 0, "fps_ceiling": 0, "pct60": 0, "note": cc.stderr.strip()[:60]}]
    res = subprocess.run([out_bin], capture_output=True, text=True)
    rows = []
    for line in res.stdout.splitlines():
        if ":" in line and "us/call" in line:
            label, rest = line.split(":", 1)
            us = float(rest.strip().split()[0])
            rows.append({"name": f"cava {label.strip()}", "ms": us / 1000.0,
                         "fps_ceiling": 0, "pct60": 0, "note": f"{us:.2f} us/call"})
    return rows


_CAVA_HARNESS = r'''
#include "cavacore.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <string.h>
static double now_s(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return t.tv_sec+t.tv_nsec/1e9;}
int main(void){
    int bars=64,ch=2,rate=44100,fs=(rate/60)*ch,ITERS=20000;
    struct cava_plan *p=cava_init(bars,rate,ch,1,0.77,50,10000);
    if(!p||p->status<0){printf("init fail\n");return 1;}
    double *in=malloc(sizeof(double)*fs),*out=malloc(sizeof(double)*bars*ch),ph=0;
    for(int k=0;k<200;k++) cava_execute(in,fs,out,p);
    double t0=now_s();
    for(int k=0;k<ITERS;k++){
        for(int n=0;n<fs;n+=ch){double s=0.3*sin(ph)+0.2*sin(ph*3.1);in[n]=s;in[n+1]=s*0.9;ph+=0.07;if(ph>6283)ph-=6283;}
        cava_execute(in,fs,out,p);
    }
    printf("active : %.2f us/call\n",(now_s()-t0)/ITERS*1e6);
    memset(in,0,sizeof(double)*fs);
    for(int k=0;k<2000;k++) cava_execute(in,fs,out,p);
    t0=now_s();
    for(int k=0;k<ITERS;k++) cava_execute(in,fs,out,p);
    printf("idle   : %.2f us/call\n",(now_s()-t0)/ITERS*1e6);
    cava_destroy(p);return 0;
}
'''


def gc_probe(size):
    """Diagnostic: how often the cyclic GC fires under a heavy render loop."""
    import gc
    import ac_ui.visualizer as V
    from ac_ui.audio_snapshot import build_live_audio_snapshot
    from ac_ui.visualizer import VisFrameCtx, render_frame
    h, w = size
    st, au = {}, {}

    def frame():
        bars = fake_bars(w, time.time())
        snap = build_live_audio_snapshot(bars, au, frame_dt=1 / 60, fallback_bar_count=w)
        render_frame("kaleido_tunnel", list(bars), h, w,
                     VisFrameCtx(st, use_color=True, features=snap.features, snapshot=snap))

    for _ in range(20):
        frame()
    gc.collect()
    before = [s["collections"] for s in gc.get_stats()]
    n = 400
    for _ in range(n):
        frame()
    after = [s["collections"] for s in gc.get_stats()]
    return {"frames": n, "tracked_objects": len(gc.get_objects()),
            "gen_collections": [a - b for a, b in zip(before, after)]}


# ── driver ───────────────────────────────────────────────────────────────────
def main(argv=None):
    ap = argparse.ArgumentParser(description="ac-ui exhaustive benchmark")
    ap.add_argument("--quick", action="store_true", help="fewer iterations")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--size", default="24x80", help="visualizer/frame size WxH (default 24x80)")
    ap.add_argument("--big", default="36x110", help="large/fullscreen-ish size for the frame budget")
    ap.add_argument("--cava-src", default="", help="path to cava fork source to also bench cavacore")
    args = ap.parse_args(argv)

    runs = 40 if args.quick else 150
    w, h = (int(x) for x in args.size.lower().split("x"))
    bw, bh = (int(x) for x in args.big.lower().split("x"))
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    report = {
        "python": sys.version.split()[0],
        "cpu_count": os.cpu_count(),
        "size": [w, h],
        "big_size": [bw, bh],
        "frame_budget_ms": FRAME_BUDGET_MS,
        "sections": {},
    }

    sections = [
        ("startup", lambda: bench_startup(runs)),
        ("audio", lambda: bench_audio(runs)),
        (f"visualizers @ {w}x{h}", lambda: bench_visualizers((h, w), runs)),
        ("chrome", lambda: bench_chrome((h, w), runs)),
        ("terminal render", lambda: bench_render_write((h, w), runs)),
        (f"full heavy frame @ {bw}x{bh}", lambda: bench_full_frame((bh, bw), runs)),
    ]
    if args.cava_src:
        sections.append(("cava (fork)", lambda: bench_cava(args.cava_src, runs)))

    if not args.json:
        print("=" * 72)
        print(f"AC-UI EXHAUSTIVE BENCHMARK   Python {report['python']}   "
              f"{report['cpu_count']} CPUs   budget {FRAME_BUDGET_MS:.1f} ms/60fps")
        print("=" * 72)

    for title, fn in sections:
        try:
            rows = fn()
        except Exception as e:  # noqa: BLE001
            rows = [{"name": "ERROR", "ms": 0, "fps_ceiling": 0, "pct60": 0, "note": repr(e)}]
        report["sections"][title] = rows
        if not args.json:
            _print_table(title, rows)

    gc_info = gc_probe((bh, bw))
    report["gc"] = gc_info
    if not args.json:
        print(f"\n[gc] {gc_info['gen_collections']} collections over {gc_info['frames']} heavy "
              f"frames  ({gc_info['tracked_objects']:,} tracked objs)")
        # resource-prioritisation summary: hottest single ops
        flat = [r for rows in report["sections"].values() for r in rows
                if r["ms"] > 0 and not r["name"].startswith(("=", " "))]
        flat.sort(key=lambda r: r["ms"], reverse=True)
        print("\n[where the time is — top 8 costs]")
        for r in flat[:8]:
            print(f"    {r['ms']:8.3f} ms  {r['name']}")
        print("\nLower is better. For per-frame budgeting, anything > ~16.7 ms can't hold 60 fps alone.")

    if args.json:
        import json
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
