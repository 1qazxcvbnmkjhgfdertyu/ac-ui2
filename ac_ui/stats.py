import os, json, queue, threading, time

import ac_ui.colors as _clrs
from ac_ui.colors import c
from ac_ui.constants import (
    STATS_ENABLED, STATS_DIR, STATS_JSON, STATS_CSV,
    _atomic_write_json,
)
from ac_ui.visualizer import resample_bars

def load_stats():
    data = {
        "total_listen_seconds": 0,
        "hour_buckets": [0] * 24,
        "sessions": 0,
        "last_session": None,
    }
    try:
        if os.path.exists(STATS_JSON):
            with open(STATS_JSON, "r", encoding="utf-8") as f:
                src = json.load(f)
            if isinstance(src, dict):
                data.update(src)
    except Exception:
        pass
    # Normalize buckets
    hb = data.get("hour_buckets")
    if not isinstance(hb, list) or len(hb) != 24:
        data["hour_buckets"] = [0] * 24
    else:
        norm = []
        for value in hb[:24]:
            try:
                norm.append(max(0, int(value)))
            except Exception:
                norm.append(0)
        data["hour_buckets"] = norm
    try:
        data["total_listen_seconds"] = max(0, int(data.get("total_listen_seconds", 0)))
    except Exception:
        data["total_listen_seconds"] = 0
    try:
        data["sessions"] = max(0, int(data.get("sessions", 0)))
    except Exception:
        data["sessions"] = 0
    if not isinstance(data.get("last_session"), dict):
        data["last_session"] = None
    return data

def save_stats(data):
    _atomic_write_json(STATS_JSON, data)

def append_stats_csv(row):
    os.makedirs(STATS_DIR, exist_ok=True)
    new_file = not os.path.exists(STATS_CSV)
    with open(STATS_CSV, "a", encoding="utf-8", newline="") as f:
        if new_file:
            f.write("session_start,session_end,listen_seconds,top_hours\n")
        f.write(row + "\n")

def start_stats_writer():
    q = queue.Queue()
    stop_evt = threading.Event()

    def worker():
        while True:
            item = q.get()
            if item is None:
                break
            kind, payload = item
            try:
                if kind == "json":
                    save_stats(payload)
                elif kind == "csv":
                    append_stats_csv(payload)
            except Exception:
                pass
        stop_evt.set()

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    return q, stop_evt

def format_seconds(sec):
    sec = int(max(0, sec))
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    if h > 0:
        return f"{h}h {m}m {s}s"
    if m > 0:
        return f"{m}m {s}s"
    return f"{s}s"

def stats_cli():
    if not os.path.exists(STATS_JSON):
        print("No stats yet. Enable with AC_UI_STATS=1 and listen for a bit.")
        return 0
    data = load_stats()
    total = data.get("total_listen_seconds", 0)
    hb = data.get("hour_buckets", [0] * 24)
    top = sorted([(i, v) for i, v in enumerate(hb)], key=lambda x: x[1], reverse=True)[:3]
    top_fmt = ", ".join([f"{h:02d}:00 ({format_seconds(v)})" for h, v in top if v > 0]) or "(none)"
    print("AC-UI Listening Stats")
    print(f"Total listening time: {format_seconds(total)}")
    print(f"Top hours: {top_fmt}")
    return 0

def build_hour_histogram_lines(hour_buckets, current_hour, width):
    width = max(8, int(width))
    buckets = list(hour_buckets[:24]) if hour_buckets else [0] * 24
    if len(buckets) < 24:
        buckets.extend([0] * (24 - len(buckets)))
    hb_max = max(buckets) if any(buckets) else 1
    normalized = [min(1.0, max(0.0, value / hb_max)) for value in buckets]
    sampled = resample_bars(normalized, width)
    blocks = " ▁▂▃▄▅▆▇█"
    hist_plain = "".join(blocks[max(0, min(8, int(round(value * 8))))] for value in sampled)
    marker_pos = int(round((current_hour % 24) / 23 * (width - 1))) if width > 1 else 0
    marker_plain = (" " * marker_pos) + "▴" + (" " * max(0, width - marker_pos - 1))

    axis_chars = [" "] * width
    labels = ((0, "00"), (6, "06"), (12, "12"), (18, "18"), (23, "23"))
    for hour_value, label in labels:
        pos = int(round(hour_value / 23 * (width - 1))) if width > 1 else 0
        start = max(0, min(width - len(label), pos - len(label) // 2))
        for i, ch in enumerate(label):
            if start + i < width:
                axis_chars[start + i] = ch
    axis_plain = "".join(axis_chars)
    return hist_plain, marker_plain, axis_plain


