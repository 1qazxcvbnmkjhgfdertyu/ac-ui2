"""Stats panel renderer — pure function, no side effects."""
from __future__ import annotations

from ac_ui.colors import USE_COLOR, c, c256, gradient_at, gradient_bar, _grad_for_hour
from ac_ui.stats import build_hour_histogram_lines, format_seconds
from ac_ui.term import truncate_plain


def render(
    stats_data: dict,
    session_listen: float,
    max_width: int,
    hour: int,
    tod_grad: list,
) -> tuple[list[str], list[str]]:
    """Return (plain_lines, color_lines) for the Stats panel.

    Args:
        stats_data:     Raw stats dict (keys: total_listen_seconds, hour_buckets).
        session_listen: Seconds listened this session (not yet flushed to stats_data).
        max_width:      Maximum line width in visible characters.
        hour:           Current hour (0–23), used to highlight the histogram.
        tod_grad:       Time-of-day gradient (from colors._active_tod_grad).
    """
    total_sec = int(stats_data.get("total_listen_seconds", 0) + session_listen)
    hb = stats_data.get("hour_buckets", [0] * 24)
    top = sorted([(i, v) for i, v in enumerate(hb)], key=lambda x: x[1], reverse=True)[:3]

    hb_total = sum(hb)
    peak_h, peak_v = (top[0][0], top[0][1]) if top and top[0][1] > 0 else (0, 0)
    peak_pct = int(peak_v / max(1, hb_total) * 100)
    active_count = sum(1 for v in hb if v > 0)
    avg_per_h = format_seconds(int(hb_total / max(1, active_count))) if active_count > 0 else "--"
    top_hours_text = ", ".join([f"{h:02d}:00" for h, v in top if v > 0]) or "(none yet)"
    hist_plain, marker_plain, axis_plain = build_hour_histogram_lines(hb, hour, max_width)

    plain = [
        truncate_plain(f"Total listening: {format_seconds(total_sec)}", max_width),
        truncate_plain(f"This session: {format_seconds(session_listen)}", max_width),
        truncate_plain(f"Most-listened hours: {top_hours_text}", max_width),
        truncate_plain(
            f"Busiest hour: {peak_h:02d}:00 ({peak_pct}% of total)" if peak_v > 0
            else "Busiest hour: (not enough listening yet)",
            max_width,
        ),
        truncate_plain(f"Hours used: {active_count} of 24   Avg used hour: {avg_per_h}", max_width),
        hist_plain,
        marker_plain,
        axis_plain,
    ]

    if USE_COLOR:
        _s_total_pct = min(100, int(total_sec / 360000 * 100))
        _s_sess_pct = min(100, int(session_listen / 28800 * 100))
        _s_total_bar = gradient_bar(_s_total_pct, 8, tod_grad)
        _s_sess_bar = gradient_bar(_s_sess_pct, 8, tod_grad)

        hist_parts = []
        for col_idx, ch in enumerate(hist_plain):
            if ch == " ":
                hist_parts.append(" ")
            else:
                h_idx = int(round(col_idx / max(1, max_width - 1) * 23))
                brightness = 100 if h_idx == (hour % 24) else 70
                col = gradient_at(_grad_for_hour(h_idx), brightness)
                bold = "\x1b[1;" if h_idx == (hour % 24) else "\x1b["
                hist_parts.append(f"{bold}38;5;{col}m{ch}\x1b[0m")
        hist_colored = "".join(hist_parts)

        _mc = gradient_at(tod_grad, 95)
        marker_pos = marker_plain.find("▴")
        marker_colored = (
            " " * max(0, marker_pos)
            + f"\x1b[1;38;5;{_mc}m▴\x1b[0m"
            + " " * max(0, max_width - marker_pos - 1)
        )
        axis_colored = c256(axis_plain, gradient_at(tod_grad, 35))

        _tc = gradient_at(tod_grad, 70)
        _pc = gradient_at(tod_grad, 80)
        _cc = gradient_at(tod_grad, 55)
        color: list[str] = [
            f"\x1b[2;36mTotal listening:\x1b[0m  \x1b[2m{format_seconds(total_sec)}\x1b[0m  {_s_total_bar}",
            f"\x1b[2;36mThis session:\x1b[0m  \x1b[2m{format_seconds(session_listen)}\x1b[0m  {_s_sess_bar}",
            f"\x1b[2;36mMost-listened hours:\x1b[0m \x1b[38;5;{_tc}m{top_hours_text}\x1b[0m",
            (
                f"\x1b[2;36mBusiest hour:\x1b[0m \x1b[38;5;{_pc}m{peak_h:02d}:00 ({peak_pct}% of total)\x1b[0m"
                if peak_v > 0 else
                f"\x1b[2;36mBusiest hour:\x1b[0m \x1b[38;5;{_cc}m(not enough listening yet)\x1b[0m"
            ),
            f"\x1b[2;36mHours used:\x1b[0m \x1b[2m{active_count} of 24\x1b[0m   \x1b[2;36mAvg used hour:\x1b[0m \x1b[2m{avg_per_h}\x1b[0m",
            hist_colored,
            marker_colored,
            axis_colored,
        ]
    else:
        color = [c(s, "2") for s in plain]

    return plain, color
