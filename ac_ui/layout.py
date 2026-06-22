import os, re, textwrap

import ac_ui.colors as _clrs
from ac_ui.colors import (
    USE_COLOR, RESET, c256, gradient_at, paint, sgr, theme_chrome, theme_role,
    theme_gradient_stops, visible_len, plain_visible_len,
)
from ac_ui.constants import (
    BOX_CHARS, BOX_TITLE_L, BOX_TITLE_R,
    CONTROL_GROUPS_FULL, CONTROL_GROUPS_COMPACT, CONTROL_GROUPS_CORE, CONTROL_GROUPS_MINI,
    CAVA_HEIGHT, GRADIENT_SPEED, GRADIENT_ANIMATE,
    BOX_BORDER_SPIN as _init_border_spin,
    BOX_BORDER_HILITE_LEN as _init_hilite_len,
    BOX_BORDER_SPEED,
    SYM_NOTE,
)
from ac_ui.term import truncate_plain, truncate_ansi_visible, fit_ansi_line
from ac_ui.tracks import parse_filename as _parse_filename

# Mutable globals updated by ui.py via module reference
BOX_BORDER_POS = 0
BOX_GRADIENT_PHASE = 0.0
BOX_BORDER_SPIN = _init_border_spin
BOX_BORDER_HILITE_LEN = _init_hilite_len
BOX_PULSE = 0.0   # 0..1 live bass energy — lifts every box border toward the highlight on beats

def wrap_plain(text, width):
    if width <= 0:
        return [text]
    return textwrap.wrap(text, width=width, break_long_words=True, replace_whitespace=False)

def layout_mode_for_size(term_cols, term_rows):
    if term_cols < 58 or term_rows < 18:
        return "tiny"
    if term_cols < 78 or term_rows < 22:
        return "small"
    return "normal"

def layout_min_spectrum_rows(term_rows, layout_mode):
    if term_rows < 5:
        return 1
    if term_rows < 10:
        return 3
    if term_rows < 14:
        return 4
    if layout_mode == "tiny":
        return 4
    if layout_mode == "small":
        return 5
    return 6

def layout_base_spectrum_rows(layout_mode, ultra_compact):
    if ultra_compact:
        return 3
    if layout_mode == "tiny":
        return 4
    if layout_mode == "small":
        return 5
    return CAVA_HEIGHT

def wrap_grouped_items(groups, width, prefix="", gap="  ", max_lines=2, indent=None):
    if width <= 0 or not groups:
        return []
    if indent is None:
        indent = " " * plain_visible_len(prefix)
    lines = []
    current_prefix = prefix
    current_items = []
    current_len = plain_visible_len(current_prefix)
    gap_len = plain_visible_len(gap)

    for group in groups:
        group_len = plain_visible_len(group)
        if group_len > width:
            return None
        next_len = current_len + (gap_len if current_items else 0) + group_len
        if current_items and next_len > width:
            lines.append(current_prefix + gap.join(current_items))
            if len(lines) >= max_lines:
                return None
            current_prefix = indent
            current_items = [group]
            current_len = plain_visible_len(current_prefix) + group_len
            if current_len > width:
                return None
        else:
            current_items.append(group)
            current_len = next_len
    if current_items:
        lines.append(current_prefix + gap.join(current_items))
    return lines if len(lines) <= max_lines else None

def build_footer_controls(term_cols, term_rows, tiny_term=False, ultra_compact=False):
    width = max(1, term_cols - 1)
    if ultra_compact or term_rows < 8 or width < 18:
        return [], False
    max_lines = 1 if term_rows < 16 else 2
    show_separator = USE_COLOR and term_rows >= 18
    candidates = []
    if tiny_term or term_cols < 80:
        candidates.extend([
            ("Controls: ", CONTROL_GROUPS_COMPACT),
            ("Controls: ", CONTROL_GROUPS_CORE),
            ("", CONTROL_GROUPS_COMPACT),
            ("", CONTROL_GROUPS_CORE),
            ("Controls: ", CONTROL_GROUPS_MINI),
            ("", CONTROL_GROUPS_MINI),
        ])
    else:
        candidates.extend([
            ("Controls: ", CONTROL_GROUPS_FULL),
            ("Controls: ", CONTROL_GROUPS_COMPACT),
            ("Controls: ", CONTROL_GROUPS_CORE),
            ("", CONTROL_GROUPS_COMPACT),
            ("", CONTROL_GROUPS_CORE),
            ("Controls: ", CONTROL_GROUPS_MINI),
        ])
    for prefix, groups in candidates:
        lines = wrap_grouped_items(groups, width, prefix=prefix, max_lines=max_lines)
        if lines:
            return lines, show_separator
    fallback = truncate_plain("n next  q quit  +/- vol", width)
    return ([fallback] if fallback else []), False

def colorize_hint_keys(text, key_color, base_code="2", bold=True, base_fg=None, dim=None):
    if not USE_COLOR:
        return text
    key_seq = sgr(fg=key_color, bold=bold)
    if base_fg is not None or dim is not None:
        base_seq = sgr(fg=base_fg, dim=(True if dim is None else dim))
    else:
        base_seq = f"\x1b[{base_code}m" if base_code else ""
    colored = re.sub(
        r"\[([^\]]+)\]",
        lambda m: f"{key_seq}[{m.group(1)}]{RESET}{base_seq}",
        text,
    )
    return f"{base_seq}{colored}{RESET}"

def selection_marker(selected=True):
    if not selected:
        return "  "
    return "> " if _clrs.ASCII_ONLY else "▶ "

def format_position_label(selected, total):
    try:
        total = int(total)
        selected = int(selected)
    except (TypeError, ValueError):
        return "0/0"
    if total <= 0:
        return "0/0"
    selected = max(0, min(total - 1, selected))
    return f"{selected + 1}/{total}"

def search_prompt_line(query, inner_w, placeholder="Search", count_text=None):
    """Uniform overlay search row: prompt on the left, result count on the right."""
    inner_w = max(1, int(inner_w))
    query = str(query or "")
    count_text = str(count_text or "").strip()
    lead = f"/ {placeholder}: "
    cursor = "_"
    count_w = plain_visible_len(count_text)
    prompt_w = inner_w if not count_text else max(1, inner_w - count_w - 1)
    prompt = truncate_plain(f"{lead}{query}{cursor}", prompt_w)
    if count_text:
        pad = " " * max(1, inner_w - plain_visible_len(prompt) - count_w)
        plain = truncate_plain(prompt + pad + count_text, inner_w)
    else:
        pad = ""
        plain = truncate_plain(prompt, inner_w)
    if not USE_COLOR:
        return plain, plain
    grad = _clrs._active_tod_grad
    if count_text:
        color = (
            c256(prompt, theme_role("accent", grad))
            + pad
            + c256(count_text, theme_role("label_dim", grad))
        )
        return plain, truncate_ansi_visible(color, inner_w)
    return plain, c256(plain, theme_role("accent", grad))

def empty_state_line(message, inner_w):
    row = truncate_plain(f"  {message}", max(1, int(inner_w)))
    if USE_COLOR:
        return row, paint(row, fg=theme_role("label_dim", _clrs._active_tod_grad), dim=True)
    return row, row

def section_heading_line(title, inner_w):
    row = truncate_plain(str(title), max(1, int(inner_w)))
    if USE_COLOR:
        return row, paint(row, fg=theme_role("accent", _clrs._active_tod_grad), bold=True)
    return row, row

def render_selectable_row(label, selected, inner_w, right=None, dim=False):
    """Return one uniformly styled selectable row for menus, search results, and help."""
    inner_w = max(1, int(inner_w))
    prefix = selection_marker(selected)
    right = str(right or "").strip()
    right_w = plain_visible_len(right)
    label_w = max(1, inner_w - plain_visible_len(prefix) - (right_w + 1 if right else 0))
    label = truncate_plain(str(label), label_w)
    pad_w = inner_w - plain_visible_len(prefix) - plain_visible_len(label) - right_w
    if right:
        pad_w = max(1, pad_w)
    else:
        pad_w = max(0, pad_w)
    row = truncate_plain(f"{prefix}{label}{' ' * pad_w}{right}", inner_w)
    if plain_visible_len(row) < inner_w:
        row += " " * (inner_w - plain_visible_len(row))
    if not USE_COLOR:
        return row, row
    grad = _clrs._active_tod_grad
    if selected:
        return row, paint(row, fg=theme_role("focus_fg", grad), bg=theme_role("focus_bg", grad), bold=True)
    base_col = theme_role("label_dim" if dim else "label", grad)
    if right:
        return row, colorize_hint_keys(
            row,
            theme_role("accent_soft", grad),
            base_fg=base_col,
            dim=dim,
        )
    return row, paint(row, fg=base_col, dim=dim)

def format_filter_summary(game_label, variant_label):
    if game_label == "ALL" and variant_label == "ALL":
        return "ALL"
    if variant_label == "ALL":
        return game_label
    if game_label == "ALL":
        return variant_label
    return f"{game_label}/{variant_label}"

def build_ultra_compact_summary(game_label, variant_label, vis_mode, remaining, display_vol=None, muted=False, showing_chime=False, chime_kind=None, repeat_current=False):
    lead = (chime_kind or "hour chime") if showing_chime else format_filter_summary(game_label, variant_label)
    parts = [lead, vis_mode, f"{remaining//60:02d}:{remaining%60:02d}"]
    if repeat_current:
        parts.append("repeat")
    if display_vol is not None:
        vol_text = f"{int(display_vol)}%"
        if muted:
            vol_text += " muted"
        parts.append(vol_text)
    elif muted:
        parts.append("muted")
    return "  ".join(parts)

def format_visualizer_status(detail=None, label=None, waiting=False, max_width=None):
    source = str(label or "").strip() or None
    if waiting:
        summary = f"waiting for {source} audio" if source else "waiting for audio"
    else:
        raw = str(detail or "").strip()
        lower = raw.lower()
        via_match = re.search(r"\bvia ([^:]+)", raw, flags=re.IGNORECASE)
        if via_match and not source:
            source = via_match.group(1).strip()
        if lower == "cava not installed":
            summary = "visualizer unavailable: cava missing"
        elif lower.startswith("config error:"):
            summary = "visualizer config error"
        elif lower.startswith("start error:"):
            summary = "visualizer start error"
        elif "audio thread exited unexpectedly" in lower:
            summary = "visualizer lost audio"
        elif lower.startswith("cava exited"):
            code_match = re.search(r"cava exited \(([^)]+)\)", raw, flags=re.IGNORECASE)
            summary = f"visualizer exited ({code_match.group(1)})" if code_match else "visualizer exited"
        else:
            summary = raw or "visualizer idle"
        if source and source not in summary:
            summary += f" via {source}"
    rendered = f"({summary})"
    return truncate_plain(rendered, max_width) if max_width is not None else rendered

def _coerce_title_items(value):
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    try:
        items = []
        for item in value:
            text = str(item or "").strip()
            if text:
                items.append(text)
        return items
    except TypeError:
        text = str(value).strip()
        return [text] if text else []

def build_box(lines_plain, lines_color, maxw_override=None, title=None, title2=None, focused=False,
              lines_fitted=False):
    """
    Btop-style Unicode box with title notches on the border.

    The primary `title` is cut into the top border near the left corner, and the
    optional `title2` becomes one secondary notch on the bottom border, which is
    closer to btop++'s real createBox() behavior than the older top-right badge
    system. When `focused` is True the border shifts toward the highlight color.
    `lines_fitted=True` tells the content loop the caller already guaranteed each
    row is exactly `maxw_override` visible columns wide, so it can skip the
    expensive truncate+measure walk for every line.
    """
    if maxw_override is not None:
        maxw = maxw_override
    else:
        maxw = max(
            [plain_visible_len(line) for line in lines_plain]
            + [visible_len(line) for line in lines_color]
            + [0]
        )
    inner_w = maxw + 2
    width = inner_w + 2
    height = len(lines_plain) + 2
    perimeter = (2 * width) + (2 * (height - 2))
    grad = _clrs._active_tod_grad
    hilite = theme_role("border_hi", grad)
    # Beat-reactive glow: the border breathes from its resting color toward the
    # highlight as the bass energy (BOX_PULSE) rises, so the whole frame pulses
    # with the music.  Focused boxes ride brighter (highlight → accent).
    _pulse = max(0.0, min(1.0, BOX_PULSE))
    if focused:
        _glow = theme_gradient_stops("border_hi", "accent", grad=grad, cache_name="box_glow_focus")
    else:
        _glow = theme_gradient_stops("border", "border_hi", grad=grad, cache_name="box_glow")
    base_gray = gradient_at(_glow, int(_pulse * 100))
    chrome = theme_chrome()
    box_chars = chrome.get("box_chars", BOX_CHARS)
    title_left = chrome.get("title_left", BOX_TITLE_L)
    title_right = chrome.get("title_right", BOX_TITLE_R)
    title_left_down = chrome.get("title_left_down", "+" if _clrs.ASCII_ONLY else "┘")
    title_right_down = chrome.get("title_right_down", "+" if _clrs.ASCII_ONLY else "└")

    def border_color(idx):
        if not BOX_BORDER_SPIN or perimeter <= 0:
            return base_gray
        pos = BOX_BORDER_POS % max(1, perimeter)
        span = max(1, BOX_BORDER_HILITE_LEN)
        if ((idx - pos) % perimeter) < span:
            return hilite
        return base_gray

    def border_index(row, col):
        if col == 0 and row <= height - 1:
            return row
        if row == height - 1:
            return (height - 1) + col
        if col == width - 1:
            return (height - 1) + (width - 1) + (height - 1 - row)
        return (height - 1) + (width - 1) + (height - 1) + (width - 1 - col)

    def bc(ch, idx):
        return c256(ch, border_color(idx))

    # When the border isn't spinning, every border cell is the same colour, so
    # we can paint whole runs in one escape instead of one-per-character — the
    # single biggest per-frame cost on low-end machines (and in NO_MOTION mode).
    _uniform_border = (not BOX_BORDER_SPIN) or perimeter <= 0

    def _color_run(chars, idx_fn, base=0):
        # Colour a horizontal border segment by coalescing consecutive same-
        # colour cells into one escape each. A static border is 1 run; a spinning
        # one is at most ~3 (base / highlight / base), versus one escape per cell.
        if not USE_COLOR or not chars:
            return chars
        parts = []
        start = 0
        cur = border_color(idx_fn(base))
        for k in range(1, len(chars)):
            col = border_color(idx_fn(base + k))
            if col != cur:
                parts.append(c256(chars[start:k], cur))
                start = k
                cur = col
        parts.append(c256(chars[start:], cur))
        return "".join(parts)

    _top_idx = lambda c: border_index(0, c)
    _bot_idx = lambda c: border_index(height - 1, c)

    def _title_inner(text, text_fg, *, bold=False, dim=False, hint=False):
        inner = f" {text} "
        if not USE_COLOR:
            return inner
        if hint:
            return colorize_hint_keys(inner, theme_role("accent", grad), base_fg=text_fg, dim=dim)
        return paint(inner, fg=text_fg, bold=bold, dim=dim)

    def _border_with_title(raw, idx_fn, text, left_marker, right_marker, text_fg, *, bold=False, dim=False, hint=False):
        if not text:
            return _color_run(raw, idx_fn)
        start = 2   # btop leaves one horizontal cell between the corner and title
        max_tw = width - 7
        if max_tw < 1:
            return _color_run(raw, idx_fn)
        text = text if plain_visible_len(text) <= max_tw else truncate_plain(text, max_tw)
        inner_plain = f" {text} "
        block_plain = left_marker + inner_plain + right_marker
        block_w = plain_visible_len(block_plain)
        if start + block_w > width - 1:
            return _color_run(raw, idx_fn)
        prefix = _color_run(raw[:start], idx_fn, base=0)
        suffix = _color_run(raw[start + block_w :], idx_fn, base=start + block_w)
        if not USE_COLOR:
            return prefix + block_plain + suffix
        left_col = c256(left_marker, border_color(idx_fn(start)))
        right_col = c256(right_marker, border_color(idx_fn(start + block_w - 1)))
        return prefix + left_col + _title_inner(text, text_fg, bold=bold, dim=dim, hint=hint) + right_col + suffix

    # ── Build top and bottom borders with btop-like title notches ─────────────
    top_raw = box_chars["tl"] + box_chars["h"] * inner_w + box_chars["tr"]
    top_title_color = theme_role("accent", grad) if focused else theme_role("panel_title", grad)
    out = [_border_with_title(top_raw, _top_idx, title, title_left, title_right, top_title_color, bold=True)]

    # ── Content rows ─────────────────────────────────────────────────────────
    # Pre-colour the vertical borders once when they don't vary per row.
    _vbar = c256(box_chars["v"], base_gray) if (_uniform_border and USE_COLOR) else None
    for row, (_plain, line) in enumerate(zip(lines_plain, lines_color)):
        if _vbar is not None:
            left_border = right_border = _vbar
        elif _uniform_border:
            left_border = right_border = box_chars["v"]
        else:
            left_border  = bc(box_chars["v"], border_index(row + 1, 0))
            right_border = bc(box_chars["v"], border_index(row + 1, width - 1))
        if lines_fitted:
            pad = ""
        else:
            line, _vis = fit_ansi_line(line, maxw)   # single walk: truncate + measure
            pad = " " * max(0, maxw - _vis)
        out.append(left_border + " " + line + pad + " " + right_border)

    # ── Bottom border (secondary title notch, like btop title2) ─────────────
    bot_raw = box_chars["bl"] + box_chars["h"] * (width - 2) + box_chars["br"]
    bottom_title = "  ".join(_coerce_title_items(title2))
    out.append(_border_with_title(
        bot_raw,
        _bot_idx,
        bottom_title,
        title_left_down,
        title_right_down,
        theme_role("panel_subtitle", grad),
        dim=True,
        hint=True,
    ))
    return out, maxw

def pad_box_lines(box_lines, width, target_len):
    out = list(box_lines)
    if len(out) >= target_len:
        return out
    _pad_color = theme_role("border", _clrs._active_tod_grad)
    box_chars = theme_chrome().get("box_chars", BOX_CHARS)
    pad_line = c256(box_chars["v"], _pad_color) + " " * (width + 2) + c256(box_chars["v"], _pad_color)
    insert_at = max(1, len(out) - 1)
    while len(out) < target_len:
        out.insert(insert_at, pad_line)
    return out

def box_outer_width(inner_width):
    return max(0, int(inner_width)) + 4

def pad_render_block(lines, width, target_len):
    out = list(lines)
    blank = " " * max(0, int(width))
    while len(out) < target_len:
        out.append(blank)
    return out

def stack_render_blocks(blocks):
    rendered = []
    width = 0
    for lines, block_width in blocks:
        if not lines:
            continue
        rendered.extend(lines)
        width = max(width, int(block_width))
    return rendered, width

def combine_render_columns(blocks, gap="   ", box_fill=False):
    active = [(list(lines), int(width)) for lines, width in blocks if lines]
    if not active:
        return [], 0
    target_len = max(len(lines) for lines, _ in active)
    padded_blocks = []
    total_width = sum(width for _, width in active) + max(0, len(active) - 1) * len(gap)
    for lines, width in active:
        if box_fill and width >= 4:
            padded_blocks.append(pad_box_lines(lines, width - 4, target_len))
        else:
            padded_blocks.append(pad_render_block(lines, width, target_len))
    combined = []
    for row in range(target_len):
        combined.append(gap.join(block[row] for block in padded_blocks))
    return combined, total_width


def build_header_bar(term_cols, last_time_str, bass_energy, tod_grad, current_track, muted, ultra_compact, level_history=None):
    """Return a single rendered header bar string.

    When `level_history` (recent bass-energy samples, oldest→newest) is given,
    the filler between the clock and the title becomes a live btop-style braille
    sparkline of that history, sitting on a dotted baseline so it still reads as
    a divider when the music is quiet.
    """
    header_time = last_time_str if term_cols >= 48 else last_time_str[-8:]
    chrome = theme_chrome()
    divider = chrome.get("divider", BOX_CHARS["h"])
    header_left = chrome.get("header_left", BOX_TITLE_L)
    header_right = chrome.get("header_right", BOX_TITLE_R)
    if USE_COLOR:
        _tod_hi = gradient_at(tod_grad, min(100, 65 + int(bass_energy * 35)))
        playing_indicator = c256(SYM_NOTE, _tod_hi) if (current_track and not muted) else c256(SYM_NOTE, theme_role("border", tod_grad))
        _hdr_left_plain = f"{divider * 3} {SYM_NOTE} {header_time} "
        _dash_bright = gradient_at(tod_grad, min(50, 28 + int(bass_energy * 22)))
        _hdr_left = c256(divider * 3, _dash_bright) + " " + playing_indicator + " " + c256(header_time, theme_role("label", tod_grad)) + " "
        if ultra_compact and current_track:
            _hdr_tag = _parse_filename(os.path.basename(current_track))
            _hdr_inner_text = f"{_hdr_tag['game']}: {_hdr_tag['variant']}" if _hdr_tag else os.path.basename(current_track)
        else:
            _hdr_inner_text = "ac-ui"
        if term_cols < 28:
            return truncate_ansi_visible(_hdr_left.rstrip(), term_cols)
        _hdr_inner_max = max(1, term_cols - plain_visible_len(_hdr_left_plain) - plain_visible_len(f"{header_left}  {header_right}"))
        _hdr_inner = f" {truncate_plain(_hdr_inner_text, _hdr_inner_max)} "
        _hdr_right_plain = f"{header_left}{_hdr_inner}{header_right}"
        _hdr_pad = max(0, term_cols - plain_visible_len(_hdr_left_plain) - plain_visible_len(_hdr_right_plain))
        _hdr_dim = theme_role("label_dim", tod_grad)
        _hdr_right = c256(header_left, _hdr_dim) + paint(_hdr_inner, fg=theme_role("title", tod_grad), bold=True) + c256(header_right, _hdr_dim)
        if level_history and _hdr_pad >= 6:
            # Floor keeps the bottom braille dots lit, so the graph doubles as a
            # continuous divider that rises into spikes as the audio gets loud.
            series = [max(0.14, min(1.0, v)) for v in level_history]
            mid = _hdr_spark(series, _hdr_pad, tod_grad)
        else:
            mid = c256(divider * _hdr_pad, _dash_bright)
        return _hdr_left + mid + _hdr_right
    return truncate_plain(f"{divider * 3} {SYM_NOTE} {header_time}", term_cols)


def _hdr_spark(series, width, tod_grad):
    """One-row braille sparkline for the header filler (lazy import avoids cycle)."""
    from ac_ui.meters import braille_graph
    rows = braille_graph(series, width, 1, grad=tod_grad)
    return rows[0] if rows else ""
