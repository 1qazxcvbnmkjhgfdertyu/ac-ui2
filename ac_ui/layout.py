import re, textwrap

import ac_ui.colors as _clrs
from ac_ui.colors import (
    USE_COLOR, c256, gradient_at, visible_len, plain_visible_len,
)
from ac_ui.constants import (
    BOX_CHARS, BOX_TITLE_L, BOX_TITLE_R,
    CONTROL_GROUPS_FULL, CONTROL_GROUPS_COMPACT, CONTROL_GROUPS_CORE, CONTROL_GROUPS_MINI,
    CAVA_HEIGHT, GRADIENT_SPEED, GRADIENT_ANIMATE,
    BOX_BORDER_SPIN as _init_border_spin,
    BOX_BORDER_HILITE_LEN as _init_hilite_len,
    BOX_BORDER_SPEED,
)
from ac_ui.term import truncate_plain, truncate_ansi_visible

# Mutable globals updated by ui.py via module reference
BOX_BORDER_POS = 0
BOX_GRADIENT_PHASE = 0.0
BOX_BORDER_SPIN = _init_border_spin
BOX_BORDER_HILITE_LEN = _init_hilite_len

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

def colorize_hint_keys(text, key_color, base_code="2", bold=True):
    if not USE_COLOR:
        return text
    key_seq = f"\x1b[1;38;5;{key_color}m" if bold else f"\x1b[38;5;{key_color}m"
    base_seq = f"\x1b[{base_code}m" if base_code else ""
    colored = re.sub(
        r"\[([^\]]+)\]",
        lambda m: f"{key_seq}[{m.group(1)}]\x1b[0m{base_seq}",
        text,
    )
    return f"{base_seq}{colored}\x1b[0m"

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

def build_box(lines_plain, lines_color, maxw_override=None, title=None, title2=None):
    """
    Btop-style Unicode box with rounded corners, spinning highlight, and optional
    centered title injected into the top border (title2 into the bottom border).
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
    base_gray = 238      # slightly lighter than 16 for better contrast
    hilite = 255

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

    # ── Top border with rounded corners ─────────────────────────────────────
    h_line = BOX_CHARS["h"] * inner_w
    top_parts = (
        bc(BOX_CHARS["tl"], border_index(0, 0))
        + "".join(bc(BOX_CHARS["h"], border_index(0, c)) for c in range(1, width - 1))
        + bc(BOX_CHARS["tr"], border_index(0, width - 1))
    )
    # Inject centered title into top border (btop ┤ Title ├ pattern)
    if title:
        t_plain = f" {title} "
        t_vis = plain_visible_len(t_plain)
        title_block_vis = t_vis + 2
        if title_block_vis <= inner_w:
            insert = (inner_w - title_block_vis) // 2 + 1  # offset into border string
            _t_col = gradient_at(_clrs._active_tod_grad, 90)
            if USE_COLOR:
                t_colored = (
                    c256(BOX_TITLE_L, hilite)
                    + f"\x1b[1;38;5;{_t_col}m{t_plain}\x1b[0m"
                    + c256(BOX_TITLE_R, hilite)
                )
            else:
                t_colored = BOX_TITLE_L + t_plain + BOX_TITLE_R
            # Rebuild top stripping ansi for position counting
            top_plain_raw = BOX_CHARS["tl"] + BOX_CHARS["h"] * inner_w + BOX_CHARS["tr"]
            left_seg  = "".join(bc(ch, border_index(0, c)) for c, ch in enumerate(top_plain_raw[:insert]))
            right_seg = "".join(bc(ch, border_index(0, c)) for c, ch in enumerate(top_plain_raw[insert + title_block_vis:], start=insert + title_block_vis))
            top_parts = left_seg + t_colored + right_seg

    out = [top_parts]

    # ── Content rows ─────────────────────────────────────────────────────────
    for row, (plain, line) in enumerate(zip(lines_plain, lines_color)):
        line = truncate_ansi_visible(line, maxw)
        pad = " " * max(0, maxw - visible_len(line))
        left_border  = bc(BOX_CHARS["v"], border_index(row + 1, 0))
        right_border = bc(BOX_CHARS["v"], border_index(row + 1, width - 1))
        out.append(left_border + " " + line + pad + " " + right_border)

    # ── Bottom border with optional title2 ───────────────────────────────────
    bot_parts = (
        bc(BOX_CHARS["bl"], border_index(height - 1, 0))
        + "".join(bc(BOX_CHARS["h"], border_index(height - 1, c)) for c in range(1, width - 1))
        + bc(BOX_CHARS["br"], border_index(height - 1, width - 1))
    )
    if title2:
        t_plain = f" {title2} "
        t_vis = plain_visible_len(t_plain)
        title_block_vis = t_vis + 2
        if title_block_vis <= inner_w:
            insert = (inner_w - title_block_vis) // 2 + 1
            _t2_col = gradient_at(_clrs._active_tod_grad, 65)
            if USE_COLOR:
                t_colored = (
                    c256(BOX_TITLE_L, hilite)
                    + f"\x1b[2;38;5;{_t2_col}m{t_plain}\x1b[0m"
                    + c256(BOX_TITLE_R, hilite)
                )
            else:
                t_colored = BOX_TITLE_L + t_plain + BOX_TITLE_R
            bot_plain_raw = BOX_CHARS["bl"] + BOX_CHARS["h"] * inner_w + BOX_CHARS["br"]
            left_seg  = "".join(bc(ch, border_index(height-1, c)) for c, ch in enumerate(bot_plain_raw[:insert]))
            right_seg = "".join(bc(ch, border_index(height-1, c)) for c, ch in enumerate(bot_plain_raw[insert + title_block_vis:], start=insert + title_block_vis))
            bot_parts = left_seg + t_colored + right_seg

    out.append(bot_parts)
    return out, maxw

def pad_box_lines(box_lines, width, target_len):
    out = list(box_lines)
    if len(out) >= target_len:
        return out
    pad_line = (c256(BOX_CHARS["v"], 238) + " " * (width + 2) + c256(BOX_CHARS["v"], 238))
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

