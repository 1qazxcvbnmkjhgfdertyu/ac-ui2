"""Stats panel renderer — pure function, no side effects."""
from __future__ import annotations

from ac_ui.colors import USE_COLOR, c256, gradient_at, paint, theme_role, _grad_for_hour
from ac_ui.constants import SYM_HIST_MARKER
from ac_ui.meters import braille_graph, meter_bar
from ac_ui.stats import build_hour_histogram_lines, format_seconds
from ac_ui.term import truncate_plain

# Rows in the btop-style 24-hour listening area graph.
HOUR_GRAPH_HEIGHT = 3


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
    _hist_plain, marker_plain, axis_plain = build_hour_histogram_lines(hb, hour, max_width)

    # btop-style multi-row area graph of the 24h listening histogram.
    hb_max = max(hb) if any(hb) else 1
    normalized = [min(1.0, max(0.0, v / hb_max)) for v in hb]
    graph_plain = braille_graph(normalized, max_width, HOUR_GRAPH_HEIGHT, use_color=False)

    text_plain = [
        truncate_plain(f"Total listening: {format_seconds(total_sec)}", max_width),
        truncate_plain(f"This session: {format_seconds(session_listen)}", max_width),
        truncate_plain(f"Most-listened hours: {top_hours_text}", max_width),
        truncate_plain(
            f"Busiest hour: {peak_h:02d}:00 ({peak_pct}% of total)" if peak_v > 0
            else "Busiest hour: (not enough listening yet)",
            max_width,
        ),
        truncate_plain(f"Hours used: {active_count} of 24   Avg used hour: {avg_per_h}", max_width),
    ]
    plain = text_plain + graph_plain + [marker_plain, axis_plain]

    if USE_COLOR:
        _s_total_pct = min(100, int(total_sec / 360000 * 100))
        _s_sess_pct = min(100, int(session_listen / 28800 * 100))
        _s_total_bar = meter_bar(_s_total_pct, 8, tod_grad)
        _s_sess_bar  = meter_bar(_s_sess_pct,  8, tod_grad)

        # Per-column time-of-day palette: each column glows in that hour's color,
        # brightest at the current hour — a living 24h timeline, btop-style.
        cur_hour = hour % 24
        col_colors = []
        for col_idx in range(max_width):
            h_idx = int(round(col_idx / max(1, max_width - 1) * 23))
            brightness = 100 if h_idx == cur_hour else 72
            col_colors.append(gradient_at(_grad_for_hour(h_idx), brightness))
        graph_colored = braille_graph(normalized, max_width, HOUR_GRAPH_HEIGHT,
                                      col_colors=col_colors, use_color=True)

        _mc = theme_role("title", tod_grad)
        marker_pos = marker_plain.find(SYM_HIST_MARKER)
        marker_colored = (
            " " * max(0, marker_pos)
            + paint(SYM_HIST_MARKER, fg=_mc, bold=True)
            + " " * max(0, max_width - marker_pos - 1)
        )
        axis_colored = c256(axis_plain, theme_role("label_dim", tod_grad))

        _tc = theme_role("accent", tod_grad)
        _pc = theme_role("value", tod_grad)
        _cc = theme_role("label", tod_grad)
        _lc = theme_role("label_dim", tod_grad)
        color = [
            f"{paint('Total listening:', fg=_lc, dim=True)}  {paint(format_seconds(total_sec), fg=_cc)}  {_s_total_bar}",
            f"{paint('This session:', fg=_lc, dim=True)}  {paint(format_seconds(session_listen), fg=_cc)}  {_s_sess_bar}",
            f"{paint('Most-listened hours:', fg=_lc, dim=True)} {paint(top_hours_text, fg=_tc)}",
            (
                f"{paint('Busiest hour:', fg=_lc, dim=True)} {paint(f'{peak_h:02d}:00 ({peak_pct}% of total)', fg=_pc)}"
                if peak_v > 0 else
                f"{paint('Busiest hour:', fg=_lc, dim=True)} {paint('(not enough listening yet)', fg=_cc)}"
            ),
            f"{paint('Hours used:', fg=_lc, dim=True)} {paint(f'{active_count} of 24', fg=_cc)}   {paint('Avg used hour:', fg=_lc, dim=True)} {paint(avg_per_h, fg=_cc)}",
            *graph_colored,
            marker_colored,
            axis_colored,
        ]
    else:
        color = list(plain)

    return plain, color
