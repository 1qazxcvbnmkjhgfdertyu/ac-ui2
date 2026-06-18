import os, sys, time, shutil

import ac_ui.colors as _clrs
from ac_ui.colors import USE_COLOR, c, c256, color_code, paint as color_paint, theme_role, visible_len, plain_visible_len
from ac_ui.meters import meter_bar
from ac_ui.constants import (
    ASCII_ONLY, BOX_CHARS,
    EQ_PRESETS, EQ_FREQ_LABELS, EQ_BAND_COUNT, EQ_BAND_MIN, EQ_BAND_MAX, EQ_CONFIG_PATH,
    SYM_ARROW_L, SYM_ARROW_R, SYM_ARROW_U, SYM_ARROW_D, SYM_ENTER,
    SYM_DOT_EMPTY, SYM_DOT_FILLED, SYM_ELLIPSIS, SYM_NOTE, SYM_PULSE_OFF,
    SYM_QUEUE_NEXT, SYM_SELECT,
    ACGC_MSCORE_MODAL_ERASE, ACGC_MSCORE_MODAL_END, ACGC_MSCORE_END_OPTIONS,
    ACGC_MSCORE_GLYPH_SELECTED, ACGC_MSCORE_GLYPH_IDLE,
    ACGC_MSCORE_ERASE_CHOICE_ACTIVE, ACGC_MSCORE_ERASE_CHOICE_IDLE,
    ACGC_MSCORE_CURSOR_OK, ACGC_MSCORE_TERMINAL_SLOT_POS,
    ACGC_MSCORE_TERMINAL_FIRST_INDENT, ACGC_MSCORE_TERMINAL_SECOND_INDENT,
    ACGC_MSCORE_OPEN_AUTOPLAY_DELAY, ACGC_NOTE_UI,
    TOWN_TUNE_HOLD, TOWN_TUNE_OFF, TOWN_TUNE_RANDOM,
    TOWN_TUNE_NOTES, TOWN_TUNE_STEPS, TOWN_TUNE_TOKEN_TO_VALUE,
    TOWN_TUNE_VALUE_TO_TOKEN, TOWN_TUNE_STEP_SECONDS,
    REFRESH_INTERVAL,
)
from ac_ui.term import (
    hide_cursor, show_cursor, invalidate_render_cache, render, _read_key,
    truncate_ansi_visible, truncate_plain,
)
from ac_ui.layout import wrap_grouped_items, colorize_hint_keys
from ac_ui.jump import next_match_index
from ac_ui.eq import (
    _clamp_eq_band, normalize_eq_bands, default_eq_bands,
    load_eq_bands, save_eq_bands, apply_mpv_eq, EQ_CONFIG_PATH,
)
from ac_ui.town_tune import (
    load_town_tune, save_town_tune, normalize_town_tune,
    _coerce_tune_token, spawn_town_tune, spawn_town_tune_note,
)


def _theme_col(role):
    return theme_role(role, _clrs._active_tod_grad) if USE_COLOR else None


def _editor_paint(text, color=None, *, bold=False, dim=False):
    if not USE_COLOR or color is None:
        return text
    return color_paint(text, fg=color, bold=bold, dim=dim)


def _col(text, color):
    return _editor_paint(text, color)


def _editor_rule(term_cols, side_pad=1):
    return (" " * side_pad) + (BOX_CHARS["h"] * max(0, term_cols - (side_pad * 2)))


_EQ_CENTER_SELECTED = " == " if ASCII_ONLY else " ━━ "
_EQ_CENTER = " -- " if ASCII_ONLY else " ╌╌ "
_EQ_FILL_SELECTED = " ## " if ASCII_ONLY else " ██ "
_EQ_FILL = " ++ " if ASCII_ONLY else " ▓▓ "
_EQ_TRACK_SELECTED = " .. " if ASCII_ONLY else " ░░ "
_EQ_MOVE = f"[{SYM_ARROW_L}/{SYM_ARROW_R}]band"
_EQ_GAIN = f"[{SYM_ARROW_U}/{SYM_ARROW_D}]+/-1dB"
_EQ_MOVE_TEXT = f"{SYM_ARROW_L}/{SYM_ARROW_R} band"
_EQ_GAIN_TEXT = f"{SYM_ARROW_U}/{SYM_ARROW_D} or +/-"
_TUNE_MOVE = f"[{SYM_ARROW_L}/{SYM_ARROW_R}]move"
_TUNE_NOTE = f"[{SYM_ARROW_U}/{SYM_ARROW_D}]note"
_TUNE_MOVE_TEXT = f"{SYM_ARROW_L}/{SYM_ARROW_R} move"
_TUNE_NOTE_TEXT = f"{SYM_ARROW_U}/{SYM_ARROW_D} note"


def run_eq_editor(audio_device=None, ipc_getter=None):
    """Full-screen 10-band EQ editor (press E). Live-updates mpv via IPC."""
    bands, saved_preset = load_eq_bands()
    preset_names = list(EQ_PRESETS.keys())
    # Restore the preset cursor to wherever the user last saved
    if saved_preset and saved_preset in preset_names:
        preset_idx = preset_names.index(saved_preset)
    else:
        preset_idx = 0
    cursor = 0
    status = None
    last_lines = None

    def current_ipc():
        if ipc_getter:
            try:
                return ipc_getter()
            except Exception:
                return None
        return None

    def push_eq(preset_name=None):
        ipc = current_ipc()
        if ipc:
            apply_mpv_eq(ipc, bands)
        save_eq_bands(bands, preset_name=preset_name)

    def build_lines():
        term_cols, term_rows = shutil.get_terminal_size(fallback=(80, 24))
        LABEL_W = 4
        BAND_W  = 4
        MIN_EQ_COLS = LABEL_W + EQ_BAND_COUNT * BAND_W  # 44

        # ── Compact fallback for narrow terminals ─────────────────────────
        if term_cols < MIN_EQ_COLS or term_rows < 8:
            lines = []
            lines.append(c256("10-BAND EQ", _theme_col("accent")))
            lines.append(c256(f"Preset: {preset_names[preset_idx]}   Band: {EQ_FREQ_LABELS[cursor]} Hz   Gain: {bands[cursor]:+.1f} dB", _theme_col("label")))
            token_groups = []
            for i, label in enumerate(EQ_FREQ_LABELS):
                gain = bands[i]
                if i == cursor:
                    token_groups.append(f"[{label}:{gain:+.0f}]")
                else:
                    token_groups.append(f"{label}:{gain:+.0f}")
            token_lines = wrap_grouped_items(token_groups, max(12, term_cols - 2), max_lines=max(2, term_rows))
            if token_lines:
                if term_rows >= 10:
                    lines.append("")
                lines.extend([c256(token_line, _theme_col("accent_soft")) for token_line in token_lines])
            control_width = max(12, term_cols - 1)
            control_lines = None
            for groups in (
                (
                    _EQ_MOVE, _EQ_GAIN, "[PgUp/Dn]+/-3dB",
                    "[p]reset", "[r]flat", "[s]ave", "[q]done",
                ),
                (_EQ_MOVE, "[+/-]gain", "[p]reset", "[r]flat", "[s]ave", "[q]done"),
                (_EQ_MOVE, "[+/-]gain", "[q]done"),
            ):
                control_lines = wrap_grouped_items(
                    groups,
                    control_width,
                    max_lines=(2 if term_rows >= 9 else 1),
                )
                if control_lines:
                    break
            if not control_lines:
                control_lines = [truncate_plain(f"{_EQ_MOVE_TEXT}  +/- gain  q done", control_width)]
            if term_rows >= 10:
                lines.append("")
            for ctrl_line in control_lines:
                lines.append(colorize_hint_keys(ctrl_line, _theme_col("accent")))
            if status:
                lines.append(c256(status, _theme_col("value")))
            if len(lines) < term_rows:
                lines.extend([""] * (term_rows - len(lines)))
            return lines, term_cols, term_rows

        lines = []

        # ── Header ──────────────────────────────────────────────────────────
        if USE_COLOR:
            _hi = _theme_col("title")
            _lo = _theme_col("label")
            _dim = _theme_col("label_dim")
            lines.append(f"{_editor_paint(' 10-BAND EQ', _hi, bold=True)}  {_editor_paint('frequencies: cliamp-style', _dim, dim=True)}")
            lines.append(
                f"{_editor_paint('Preset:', _dim, dim=True)} {_editor_paint(preset_names[preset_idx], _lo)}"
                f"   {_editor_paint('Band:', _dim, dim=True)} {_editor_paint(f'{EQ_FREQ_LABELS[cursor]} Hz', _hi)}"
                f"   {_editor_paint('Gain:', _dim, dim=True)} {_editor_paint(f'{bands[cursor]:+.1f} dB', _hi, bold=True)}"
            )
        else:
            lines.append("10-BAND EQ  (cliamp-style frequencies)")
            lines.append(f"Preset: {preset_names[preset_idx]}   Band: {EQ_FREQ_LABELS[cursor]} Hz   Gain: {bands[cursor]:+.1f} dB")

        # ── Vertical bar graph ───────────────────────────────────────────────
        # Compute bar area: odd number of rows so center is a full row.
        overhead = 6  # header(2) + freq-labels(1) + gain-row(1) + controls(1) + status(1)
        available = max(5, term_rows - overhead)
        half_rows = max(2, min(12, (available - 1) // 2))
        bar_rows = half_rows * 2 + 1   # center row + equal halves
        center_r = half_rows            # index of the 0-dB row

        # Band column width: label up to 3 chars + 1 space = 4 each, plus 1 leading label col
        # LABEL_W / BAND_W defined at function start

        for r in range(bar_rows):
            dist = center_r - r   # positive = above 0 dB, negative = below
            db_at_row = dist * (EQ_BAND_MAX / half_rows)

            # Left-side dB scale
            if r == 0:
                db_label = f"+{int(EQ_BAND_MAX):2d} "
            elif r == center_r:
                db_label = "  0 "
            elif r == bar_rows - 1:
                db_label = f"{int(EQ_BAND_MIN):3d} "
            else:
                db_label = "    "

            row_parts = [c256(db_label, _theme_col("border")) if USE_COLOR else db_label]

            for i, gain in enumerate(bands):
                selected = (i == cursor)
                # Is this row inside the gain bar?
                if dist > 0:
                    filled = gain >= 0 and db_at_row <= gain
                elif dist < 0:
                    filled = gain < 0 and db_at_row >= gain
                else:
                    filled = False

                if r == center_r:
                    # Center dashed line
                    if USE_COLOR:
                        if selected:
                            row_parts.append(_editor_paint(_EQ_CENTER_SELECTED, _theme_col("title"), bold=True))
                        else:
                            row_parts.append(_editor_paint(_EQ_CENTER, _theme_col("track_bg")))
                    else:
                        row_parts.append(" -- " if not selected else " == ")
                elif filled:
                    if USE_COLOR:
                        if selected:
                            row_parts.append(_editor_paint(_EQ_FILL_SELECTED, _theme_col("title"), bold=True))
                        else:
                            row_parts.append(_editor_paint(_EQ_FILL, _theme_col("accent_soft")))
                    else:
                        row_parts.append(" ## ")
                else:
                    if USE_COLOR and selected:
                        row_parts.append(_editor_paint(_EQ_TRACK_SELECTED, _theme_col("track_bg")))
                    else:
                        row_parts.append("    ")

            lines.append("".join(row_parts))

        # ── Frequency labels ─────────────────────────────────────────────────
        freq_row = " " * LABEL_W
        for i, label in enumerate(EQ_FREQ_LABELS):
            cell = f"{label:^{BAND_W}}"
            if USE_COLOR:
                if i == cursor:
                    freq_row += _editor_paint(cell, _theme_col("title"), bold=True)
                else:
                    freq_row += c256(cell, _theme_col("label"))
            else:
                freq_row += f"[{label}]" if i == cursor else cell
        lines.append(freq_row)

        # Gain value row under frequency labels
        gain_row = " " * LABEL_W
        for i, gain in enumerate(bands):
            cell = f"{gain:+.0f}".center(BAND_W)
            if USE_COLOR:
                if i == cursor:
                    gain_row += _editor_paint(cell, _theme_col("accent"), bold=True)
                elif gain != 0.0:
                    gain_row += c256(cell, _theme_col("label"))
                else:
                    gain_row += c256(cell, _theme_col("border"))
            else:
                gain_row += cell
        lines.append(gain_row)

        # ── Controls ─────────────────────────────────────────────────────────
        ctrl_full = f"{_EQ_MOVE_TEXT}   {_EQ_GAIN_TEXT}  +/-1 dB   PgUp/Dn +/-3 dB   p preset   r flat   s save   q done"
        ctrl_short = f"{_EQ_MOVE_TEXT}  +/-1 dB  PgUp/Dn +/-3 dB  p preset  s save  q done"
        ctrl = ctrl_full if plain_visible_len(ctrl_full) <= term_cols - 1 else ctrl_short
        ctrl = truncate_plain(ctrl, term_cols - 1)
        if USE_COLOR:
            _cc = _theme_col("accent_soft")
            lines.append(c256(ctrl, _cc))
        else:
            lines.append(ctrl)
        if status:
            lines.append(c256(status, _theme_col("value")) if USE_COLOR else status)

        if len(lines) < term_rows:
            lines.extend([""] * (term_rows - len(lines)))
        return lines, term_cols, term_rows

    push_eq()

    def _on_eq_key(ch):
        nonlocal cursor, status, preset_idx
        if ch in ("LEFT", "h", "H"):
            cursor = (cursor - 1) % EQ_BAND_COUNT
            status = None
        elif ch in ("RIGHT", "l", "L"):
            cursor = (cursor + 1) % EQ_BAND_COUNT
            status = None
        elif ch in ("+", "=", "UP", "k", "K"):
            bands[cursor] = _clamp_eq_band(bands[cursor] + 1.0)
            push_eq(); status = "updated"
        elif ch in ("-", "DOWN", "j", "J"):
            bands[cursor] = _clamp_eq_band(bands[cursor] - 1.0)
            push_eq(); status = "updated"
        elif ch == "PAGEUP":
            bands[cursor] = _clamp_eq_band(bands[cursor] + 3.0)
            push_eq(); status = "+3 dB"
        elif ch == "PAGEDOWN":
            bands[cursor] = _clamp_eq_band(bands[cursor] - 3.0)
            push_eq(); status = "-3 dB"
        elif ch in ("p", "P"):
            preset_idx = (preset_idx + 1) % len(preset_names)
            name = preset_names[preset_idx]
            bands[:] = normalize_eq_bands(EQ_PRESETS[name])
            push_eq(preset_name=name); status = f"preset: {name}"
        elif ch in ("r", "R"):
            bands[:] = default_eq_bands()
            preset_idx = 0
            push_eq(preset_name="flat"); status = "reset flat"
        elif ch in ("s", "S"):
            status = f"saved {EQ_CONFIG_PATH}" if save_eq_bands(bands, preset_name=preset_names[preset_idx]) else "save failed"
        elif ch in ("\r", "\n"):
            return True  # exit
        return False

    from ac_ui.modal import Modal
    try:
        with Modal() as m:
            m.run(build_lines, _on_eq_key, fps=20)
    finally:
        save_eq_bands(bands, preset_name=preset_names[preset_idx])


def _render_tune_editor(
    notes,
    cursor,
    status=None,
    confirm_menu_idx=None,
    anim_frame=0,
    modal=None,
    modal_idx=0,
    modal_scale=1.0,
    button_flash=None,
    playback_idx=None,
    playback_active=False,
    input_locked=False,
):
    size = shutil.get_terminal_size(fallback=(80, 24))
    term_cols = size.columns
    term_rows = size.lines
    notes = normalize_town_tune(notes)
    if modal is None and confirm_menu_idx is not None:
        modal = ACGC_MSCORE_MODAL_ERASE
        modal_idx = confirm_menu_idx
    if button_flash is None:
        button_flash = set()
    elif isinstance(button_flash, str):
        button_flash = {button_flash}
    else:
        button_flash = set(button_flash)

    cell_count = TOWN_TUNE_STEPS
    board_w = 78
    pad_s = " " * max(0, (term_cols - board_w) // 2)
    required_rows = 24

    def token(tok):
        tok = _coerce_tune_token(tok)
        if tok == TOWN_TUNE_RANDOM:
            return "?"
        if tok == TOWN_TUNE_HOLD:
            return "Z"
        if tok == TOWN_TUNE_OFF:
            return "-"
        return tok[0]

    def note_value(idx):
        return TOWN_TUNE_TOKEN_TO_VALUE.get(_coerce_tune_token(notes[idx]), 15)

    def rgb_color_code(rgb, bold=True, dim=False):
        prefix = "1;" if bold else ("2;" if dim else "")
        return f"{prefix}{color_code(rgb)}"

    def note_frame_code(value):
        return rgb_color_code(ACGC_NOTE_UI[value]["env"])

    def note_detail_code(value):
        return rgb_color_code(ACGC_NOTE_UI[value]["prim"], bold=False)

    def note_glyph_code(selected=False):
        rgb = ACGC_MSCORE_GLYPH_SELECTED if selected else ACGC_MSCORE_GLYPH_IDLE
        return rgb_color_code(rgb)

    def paint_code(text, code):
        return c(text, code) if USE_COLOR else text

    def green(text):
        return _editor_paint(text, _theme_col("good"), bold=True)

    def blue(text):
        return _editor_paint(text, _theme_col("label"), bold=True)

    def orange(text):
        return _editor_paint(text, _theme_col("warning"), bold=True)

    def cream(text):
        return _editor_paint(text, _theme_col("value_soft"))

    def frog_parts(idx):
        value = note_value(idx)
        ui = ACGC_NOTE_UI[value]
        selected = idx == cursor and not playback_active
        playing = playback_active and idx == playback_idx
        pulse = selected and (anim_frame % 18) >= 9
        frame_code = note_frame_code(value)
        detail_code = note_detail_code(value)
        glyph_code = note_glyph_code(selected)

        def frame(text):
            return paint_code(text, frame_code)

        def detail(text):
            return paint_code(text, detail_code)

        def glyph(text):
            return " " * visible_len(text) if playing else paint_code(text, glyph_code)

        mark = ui["label"]
        eye = "O" if pulse else "o"
        dot = "O" if pulse else "."

        if ui["frame"] == "random":
            top = detail(eye) + frame("-") + detail(eye) + frame("-") + detail(eye)
            body = frame("[") + glyph(f"{mark:^3}") + frame("]")
        elif ui["frame"] == "rest":
            top = glyph(" Z Z ")
            body = frame("(") + detail("---") + frame(")")
        elif ui["frame"] == "off":
            top = detail(dot) + frame(" ") + detail(dot) + frame(" ") + detail(dot)
            body = frame("(") + glyph(f"{mark:^3}") + frame(")")
        else:
            top = detail(eye) + frame("   ") + detail(eye)
            body = frame("(") + glyph(f"{mark:^3}") + frame(")")
        return top, body

    def staff_line(start):
        cells = []
        active_idx = playback_idx if playback_active else cursor
        for i in range(start, start + 8):
            cells.append("==O" if i == active_idx else "--o")
        return orange("o--" + "--".join(cells) + "-->")

    def note_lane(idx):
        ui = ACGC_NOTE_UI[note_value(idx)]
        visual_y = ui["ofs_y"]
        if visual_y >= -16.0:
            return 0
        if visual_y >= -23.0:
            return 2
        return 4

    def pitched_note_rows(start, indent):
        pos = ACGC_MSCORE_TERMINAL_SLOT_POS
        rows = [[] for _ in range(6)]
        for lane in rows:
            lane.append(" " * indent)
        for slot in range(8):
            idx = start + slot
            lane_idx = min(note_lane(idx), 4)
            eyes, body = frog_parts(idx)
            for lane_no, lane in enumerate(rows):
                target = indent + pos[slot]
                current = visible_len("".join(lane))
                if current < target:
                    lane.append(" " * (target - current))
                if lane_no == lane_idx:
                    lane.append(eyes)
                elif lane_no == lane_idx + 1:
                    lane.append(body)
                else:
                    lane.append("     ")
        return ["".join(row).rstrip() for row in rows]

    def paper(line=""):
        inner_w = board_w - 6
        visible = visible_len(line)
        if visible > inner_w:
            line = truncate_ansi_visible(line, inner_w)
            visible = visible_len(line)
        if visible < inner_w:
            line = line + (" " * (inner_w - visible))
        return pad_s + green("||") + " " + cream(line) + " " + green("||")

    def button(text, key):
        role = "warning" if key in button_flash else "good"
        return _editor_paint(text, _theme_col(role), bold=True)

    def modal_line():
        scale_hint = "" if modal_scale >= 0.95 else " " * max(0, 3 - int(modal_scale * 3))
        active_choice = rgb_color_code(ACGC_MSCORE_ERASE_CHOICE_ACTIVE)
        idle_choice = rgb_color_code(ACGC_MSCORE_ERASE_CHOICE_IDLE)

        def choice(label, active):
            prefix = "> " if active else "  "
            return paint_code(prefix + label, active_choice if active else idle_choice)

        if modal == ACGC_MSCORE_MODAL_ERASE:
            yes = choice("Yes", modal_idx == 0)
            no = choice("No", modal_idx == 1)
            return scale_hint + " " * 19 + _editor_paint("Are you sure?", _theme_col("danger"), bold=True) + "    " + yes + "    " + no
        if modal == ACGC_MSCORE_MODAL_END:
            parts = []
            for i, option in enumerate(ACGC_MSCORE_END_OPTIONS):
                parts.append(choice(option, modal_idx == i))
            return scale_hint + " " * 9 + _editor_paint("Is this OK?", _theme_col("danger"), bold=True) + "    " + "    ".join(parts)
        return ""

    def compact():
        def build_row(start_idx, width):
            row = []
            for i in range(start_idx, min(start_idx + width, cell_count)):
                tok = token(notes[i])
                cell = f"[{tok:1}]" if i == cursor else f" {tok:1} "
                row.append(cell)
            return " ".join(row)

        lines = []
        lines.append(c256("TOWN TUNE", _theme_col("accent")))
        if modal == ACGC_MSCORE_MODAL_ERASE:
            prompt = f"Erase all? {'Yes' if modal_idx == 0 else 'No'}"
        elif modal == ACGC_MSCORE_MODAL_END:
            prompt = f"Finish: {ACGC_MSCORE_END_OPTIONS[modal_idx]}"
        elif cursor >= ACGC_MSCORE_CURSOR_OK:
            prompt = "Cursor: OK"
        else:
            prompt = f"Slot {cursor + 1:02d}/16   Note: {_coerce_tune_token(notes[cursor])}"
        lines.append(c256(truncate_plain(prompt, max(10, term_cols - 1)), _theme_col("label")))
        if term_rows >= 10:
            lines.append("")
        row_w = max(2, min(8, max(2, (term_cols + 1) // 4)))
        for start in range(0, cell_count, row_w):
            row_text = build_row(start, row_w)
            compact_pad = " " * max(0, (term_cols - plain_visible_len(row_text)) // 2)
            lines.append(compact_pad + row_text)
        control_width = max(12, term_cols - 1)
        control_candidates = [
            (_TUNE_MOVE, _TUNE_NOTE, "[Enter]next", "[X]play", "[Y]erase", "[B]back"),
            (_TUNE_MOVE, _TUNE_NOTE, "[X]play", "[Y]erase", "[B]back"),
            (_TUNE_MOVE, _TUNE_NOTE, "[X]play", "[B]back"),
        ]
        if term_cols >= 32:
            control_candidates.insert(0, control_candidates[0] + ("[R]e-Reader",))
        extra_groups = ("[O]off", "[Z/H]hold", "[?]random")
        control_lines = None
        for groups in control_candidates:
            control_lines = wrap_grouped_items(
                groups,
                control_width,
                max_lines=(2 if term_rows >= 10 else 1),
            )
            if control_lines:
                break
        if not control_lines:
            control_lines = [truncate_plain(f"{_TUNE_MOVE_TEXT}  {_TUNE_NOTE_TEXT}  X play  B back", control_width)]
        extra_lines = wrap_grouped_items(
            extra_groups,
            control_width,
            max_lines=1,
        ) if term_rows >= 12 else []
        if term_rows >= 10:
            lines.append("")
        if input_locked:
            lines.append(c256("Playing town tune...", _theme_col("accent_soft")))
        else:
            for ctrl_line in control_lines:
                lines.append(colorize_hint_keys(ctrl_line, _theme_col("accent")))
            for extra_line in (extra_lines or []):
                lines.append(colorize_hint_keys(extra_line, _theme_col("accent_soft"), bold=False))
        if status:
            lines.append(c256(status, _theme_col("value")))
        if len(lines) < term_rows:
            lines.extend([""] * (term_rows - len(lines)))
        elif len(lines) > term_rows:
            lines = lines[:term_rows]
        return lines

    if term_rows < required_rows or term_cols < board_w + 2:
        return compact()

    lines = []
    lines.append(pad_s + " " * 14 + blue("____") + green("  oo  ") + blue("____"))
    lines.append(pad_s + blue("      /") + green("=" * (board_w - 14)) + blue("\\"))
    lines.append(pad_s + green("   ." + "=" * (board_w - 8) + "."))
    if modal is None:
        lines.append(paper(""))
    else:
        lines.append(paper(modal_line()))
    for note_row in pitched_note_rows(0, ACGC_MSCORE_TERMINAL_FIRST_INDENT):
        if note_row.strip():
            lines.append(paper(note_row))
    lines.append(paper(" " * 4 + staff_line(0)))
    for note_row in pitched_note_rows(8, ACGC_MSCORE_TERMINAL_SECOND_INDENT):
        if note_row.strip():
            lines.append(paper(note_row))
    lines.append(paper(" " * 12 + staff_line(8)))
    lines.append(paper(""))
    lines.append(pad_s + green("   '" + "=" * (board_w - 8) + "'"))
    ok_active = cursor == ACGC_MSCORE_CURSOR_OK or "OK" in button_flash or "START" in button_flash
    lines.append(
        pad_s
        + button("    (Y) Erase all", "Y")
        + (" " * 8)
        + button("(X) Play", "X")
        + (" " * 8)
        + button("(R) e-Reader", "R")
        + (" " * 7)
        + (_editor_paint("(OK)", _theme_col("danger"), bold=True) if ok_active else green("(OK)"))
    )
    lines.append(
        pad_s
        + " " * 52
        + (_editor_paint("START", _theme_col("danger"), bold=True) if ok_active else _editor_paint("START", _theme_col("label_dim")))
    )
    lines.append("")
    if input_locked:
        help_line = "Playing town tune..."
    else:
        help_line = f"{SYM_ARROW_L}{SYM_ARROW_R} move  {SYM_ARROW_U}{SYM_ARROW_D} pitch  {SYM_ENTER} next  X play  Y erase  R e-Reader"
    lines.append(_editor_paint(help_line, _theme_col("accent_soft")))
    if status:
        lines.append(_editor_paint(status, _theme_col("value")))

    if len(lines) < term_rows:
        lines.extend([""] * (term_rows - len(lines)))
    elif len(lines) > term_rows:
        lines = lines[:term_rows]
    return lines

def _town_tune_next_value(tok):
    value = TOWN_TUNE_TOKEN_TO_VALUE.get(_coerce_tune_token(tok), 15)
    if value != 13:
        if value == 15:
            value = 0
        else:
            value += 1
    return TOWN_TUNE_VALUE_TO_TOKEN[value]

def _town_tune_prev_value(tok):
    value = TOWN_TUNE_TOKEN_TO_VALUE.get(_coerce_tune_token(tok), 15)
    if value != 14:
        if value == 0:
            value = 15
        else:
            value -= 1
    return TOWN_TUNE_VALUE_TO_TOKEN[value]

def run_tune_editor(audio_device=None):
    notes = load_town_tune()
    original_notes = list(notes)
    cursor = 0
    status = None
    last_lines = None
    preview_proc = None
    preview_tmp = None
    preview_kind = None
    preview_started = 0.0
    modal = None
    modal_idx = 0
    modal_scale = 0.0
    anim_frame = 0
    button_flash = None
    button_flash_until = 0.0
    auto_play_at = time.monotonic() + ACGC_MSCORE_OPEN_AUTOPLAY_DELAY
    auto_play_pending = True

    def stop_preview():
        nonlocal preview_proc, preview_tmp, preview_kind, preview_started
        if preview_proc and preview_proc.poll() is None:
            try:
                preview_proc.terminate()
            except Exception:
                pass
        preview_proc = None
        preview_kind = None
        preview_started = 0.0
        if preview_tmp:
            try:
                os.unlink(preview_tmp)
            except Exception:
                pass
            preview_tmp = None

    def clear_finished_preview():
        nonlocal preview_proc, preview_tmp, preview_kind, preview_started
        if preview_proc and preview_proc.poll() is not None:
            preview_proc = None
            preview_kind = None
            preview_started = 0.0
            if preview_tmp:
                try:
                    os.unlink(preview_tmp)
                except Exception:
                    pass
                preview_tmp = None

    def full_playback_state(now):
        if preview_kind != "full" or not preview_proc or preview_proc.poll() is not None:
            return False, None
        elapsed = now - preview_started
        duration = TOWN_TUNE_STEPS * TOWN_TUNE_STEP_SECONDS
        if elapsed >= duration + 0.10:
            stop_preview()
            return False, None
        idx = int(max(0.0, elapsed) / max(0.001, TOWN_TUNE_STEP_SECONDS))
        return True, min(TOWN_TUNE_STEPS - 1, idx)

    def set_button_flash(key):
        nonlocal button_flash, button_flash_until
        button_flash = key
        button_flash_until = time.monotonic() + 0.16

    def open_modal(kind, idx=0):
        nonlocal modal, modal_idx, modal_scale
        modal = kind
        modal_idx = idx
        modal_scale = 0.0

    def close_modal():
        nonlocal modal, modal_idx, modal_scale
        modal = None
        modal_idx = 0
        modal_scale = 0.0

    def spawn_full_preview(message="Previewing current tune..."):
        nonlocal preview_proc, preview_tmp, preview_kind, preview_started, status
        stop_preview()
        preview_proc, preview_tmp = spawn_town_tune(audio_device, notes=notes)
        if preview_proc:
            preview_kind = "full"
            preview_started = time.monotonic()
            status = message
        else:
            status = "Preview unavailable (game renderer or sample bank missing)."

    def audition_current():
        nonlocal preview_proc, preview_tmp, preview_kind, preview_started, status
        stop_preview()
        if cursor >= ACGC_MSCORE_CURSOR_OK:
            status = "OK"
            return
        value = TOWN_TUNE_TOKEN_TO_VALUE.get(_coerce_tune_token(notes[cursor]), 15)
        if value in (14, 15):
            return
        preview_proc, preview_tmp = spawn_town_tune_note(notes[cursor], audio_device, notes=notes, cursor=cursor)
        if preview_proc:
            preview_kind = "note"
            preview_started = time.monotonic()
            status = f"Audition: {_coerce_tune_token(notes[cursor])}"

    from ac_ui.modal import _invalidate_after_modal
    invalidate_render_cache(clear_screen=True)
    try:
        while True:
            now = time.monotonic()
            clear_finished_preview()
            if button_flash and now >= button_flash_until:
                button_flash = None
            if modal is not None:
                modal_step = 0.20 if modal == ACGC_MSCORE_MODAL_END else 0.25
                modal_scale = min(1.0, modal_scale + modal_step)
            if auto_play_pending and modal is None and now >= auto_play_at:
                auto_play_pending = False
                spawn_full_preview("Previewing current tune...")
                now = time.monotonic()
            playback_active, playback_idx = full_playback_state(now)

            lines = _render_tune_editor(
                notes,
                cursor,
                status=status,
                anim_frame=anim_frame,
                modal=modal,
                modal_idx=modal_idx,
                modal_scale=modal_scale,
                button_flash={button_flash} if button_flash else set(),
                playback_idx=playback_idx,
                playback_active=playback_active,
                input_locked=playback_active,
            )
            if lines != last_lines:
                render(lines)
                last_lines = list(lines)
            status = None

            key = _read_key(sys.stdin.fileno(), timeout=REFRESH_INTERVAL)
            if not key:
                anim_frame = (anim_frame + 1) % 18
                continue

            if playback_active:
                continue

            if modal == ACGC_MSCORE_MODAL_ERASE:
                if key in ("q", "Q", "ESC", "b", "B", "n", "N"):
                    close_modal()
                    status = "Erase all cancelled."
                    continue
                if key in ("UP", "LEFT"):
                    modal_idx = 0
                    continue
                if key in ("DOWN", "RIGHT"):
                    modal_idx = 1
                    continue
                if key in ("\r", "\n", "a", "A", "y", "Y"):
                    if modal_idx == 0:
                        notes = [TOWN_TUNE_HOLD] * TOWN_TUNE_STEPS
                        status = "Erase all: set every slot to Z."
                    else:
                        status = "Erase all cancelled."
                    close_modal()
                    anim_frame = 0
                    continue
                continue

            if modal == ACGC_MSCORE_MODAL_END:
                if key in ("b", "B"):
                    close_modal()
                    cursor = 0
                    anim_frame = 0
                    status = "Rewrite: returned to editing."
                    continue
                if key in ("q", "Q", "ESC"):
                    close_modal()
                    status = "Still editing."
                    continue
                if key in ("UP", "LEFT"):
                    modal_idx = max(0, modal_idx - 1)
                    continue
                if key in ("DOWN", "RIGHT"):
                    modal_idx = min(len(ACGC_MSCORE_END_OPTIONS) - 1, modal_idx + 1)
                    continue
                if key in ("\r", "\n", "a", "A", "s", "S"):
                    if modal_idx == 0:
                        save_town_tune(notes)
                        stop_preview()
                        return
                    if modal_idx == 1:
                        close_modal()
                        cursor = 0
                        anim_frame = 0
                        status = "Rewrite: returned to editing."
                        continue
                    notes = list(original_notes)
                    save_town_tune(notes)
                    stop_preview()
                    return
                continue

            if key in ("q", "Q", "ESC", "s", "S"):
                set_button_flash("START")
                open_modal(ACGC_MSCORE_MODAL_END, 0)
                continue
            if key in ("\r", "\n", "a", "A"):
                if cursor == ACGC_MSCORE_CURSOR_OK:
                    set_button_flash("START")
                    open_modal(ACGC_MSCORE_MODAL_END, 0)
                    continue
                cursor += 1
                anim_frame = 0
                audition_current()
                continue
            if key in ("p", "P", "x", "X"):
                set_button_flash("X")
                spawn_full_preview()
                continue
            if key in ("LEFT", "b", "B"):
                if cursor > 0:
                    cursor -= 1
                    anim_frame = 0
                    audition_current()
                continue
            if key in ("RIGHT",):
                if cursor < ACGC_MSCORE_CURSOR_OK:
                    cursor += 1
                    anim_frame = 0
                    audition_current()
                continue
            if key in ("y", "Y"):
                set_button_flash("Y")
                open_modal(ACGC_MSCORE_MODAL_ERASE, 0)
                status = None
                continue
            if key in ("r", "R"):
                set_button_flash("R")
                status = "e-Reader/GBA transfer path is not available in terminal mode."
                continue
            if key in ("o", "O"):
                if cursor == ACGC_MSCORE_CURSOR_OK:
                    continue
                notes[cursor] = TOWN_TUNE_OFF
                anim_frame = 0
                audition_current()
                continue
            if key in ("z", "Z", "h", "H"):
                if cursor == ACGC_MSCORE_CURSOR_OK:
                    continue
                notes[cursor] = TOWN_TUNE_HOLD
                anim_frame = 0
                audition_current()
                continue
            if key in ("?", "/"):
                if cursor == ACGC_MSCORE_CURSOR_OK:
                    continue
                notes[cursor] = TOWN_TUNE_RANDOM
                anim_frame = 0
                audition_current()
                continue
            if key in ("UP", "DOWN"):
                if cursor == ACGC_MSCORE_CURSOR_OK:
                    continue
                if key == "UP":
                    notes[cursor] = _town_tune_next_value(notes[cursor])
                else:
                    notes[cursor] = _town_tune_prev_value(notes[cursor])
                anim_frame = 0
                audition_current()
                continue
    finally:
        stop_preview()
        from ac_ui.modal import _invalidate_after_modal
        _invalidate_after_modal()


# ── Playlist infrastructure ────────────────────────────────────────────────────

_PICKER_PLAYLIST_EXTS = {".acpl", ".m3u"}
_PICKER_AUDIO_EXTS    = {".midi", ".mid", ".mp3", ".flac", ".ogg", ".wav", ".opus", ".aac", ".m4a"}
_PICKER_PLAYLISTS_DIR = os.path.expanduser("~/.local/share/ac-terminal-radio/playlists")
_PICKER_BROWSE_START  = os.path.expanduser("~/Downloads")

_WT_FILLED = SYM_DOT_FILLED
_WT_EMPTY  = SYM_DOT_EMPTY


def _wt_dots(weight, max_wt=5):
    """Filled/empty dot weight display (e.g. ●●●○○)."""
    w = max(1, min(max_wt, int(weight)))
    return _WT_FILLED * w + _WT_EMPTY * (max_wt - w)


def _picker_scan_saved():
    """Return list of (path, display_name, unique_count, ext) from the playlists dir.

    Walks the whole tree (not just one level) so playlists nested in subfolders
    show up in the picker.
    """
    from ac_ui.tracks import load_playlist_source
    results = []
    if not os.path.isdir(_PICKER_PLAYLISTS_DIR):
        return results
    for root, dirs, files in os.walk(_PICKER_PLAYLISTS_DIR):
        dirs.sort()
        for name in sorted(files):
            ext = os.path.splitext(name)[1].lower()
            if ext not in _PICKER_PLAYLIST_EXTS:
                continue
            full = os.path.join(root, name)
            src = load_playlist_source(full)
            unique = len({e.path for e in src.entries if e.exists})
            results.append((full, src.name, unique, ext))
    return results


def _picker_scan_browser(path):
    """Directory browser: (label, full_path, kind) — kind in up/dir/playlist/audio_dir."""
    entries = [("..", os.path.dirname(path), "up")]
    try:
        names = sorted(os.listdir(path),
                       key=lambda n: (not os.path.isdir(os.path.join(path, n)), n.lower()))
    except OSError:
        return entries
    for name in names:
        if name.startswith("."):
            continue
        full = os.path.join(path, name)
        ext  = os.path.splitext(name)[1].lower()
        if os.path.isdir(full):
            try:
                sub_names = os.listdir(full)
            except OSError:
                sub_names = []
            has_audio = any(
                os.path.splitext(n)[1].lower() in _PICKER_AUDIO_EXTS | _PICKER_PLAYLIST_EXTS
                for n in sub_names
            )
            # Directories with media are selectable as a source ("audio_dir");
            # plain directories are still listed so deeper folders are reachable.
            entries.append((name + "/", full, "audio_dir" if has_audio else "dir"))
        elif ext in _PICKER_PLAYLIST_EXTS:
            entries.append((name, full, "playlist"))
    return entries


def _editor_scan_browser(path):
    """Like _picker_scan_browser but also lists individual audio files."""
    entries = [("..", os.path.dirname(path), "up")]
    try:
        names = sorted(os.listdir(path),
                       key=lambda n: (not os.path.isdir(os.path.join(path, n)), n.lower()))
    except OSError:
        return entries
    for name in names:
        if name.startswith("."):
            continue
        full = os.path.join(path, name)
        ext  = os.path.splitext(name)[1].lower()
        if os.path.isdir(full):
            try:
                sub_names = os.listdir(full)
            except OSError:
                sub_names = []
            has_media = any(os.path.splitext(n)[1].lower() in _PICKER_AUDIO_EXTS | _PICKER_PLAYLIST_EXTS
                            for n in sub_names)
            entries.append((name + "/", full, "audio_dir" if has_media else "dir"))
        elif ext in _PICKER_PLAYLIST_EXTS:
            entries.append((name, full, "playlist"))
        elif ext in _PICKER_AUDIO_EXTS:
            entries.append((name, full, "audio"))
    return entries


def _inline_prompt_lines(label, buf, cursor_pos, hint, term_cols):
    """Return (input_line, hint_line) for rendering an inline text prompt."""
    lo = _theme_col("label")
    acc = _theme_col("accent")
    dim = _theme_col("label_dim")
    focus_bg = _theme_col("focus_bg")
    focus_fg = _theme_col("focus_fg")
    text   = "".join(buf)
    before = text[:cursor_pos]
    after  = text[cursor_pos:]
    cur_ch = after[0] if after else " "
    rest   = after[1:] if after else ""
    if USE_COLOR:
        cursor_cell = (
            _editor_paint(cur_ch, focus_fg, bold=True)
            if focus_bg is None
            else color_paint(cur_ch, fg=focus_fg, bg=focus_bg, bold=True)
        )
        input_line = (_editor_paint(f"  {label}: ", lo) +
                      _editor_paint(before, acc) +
                      cursor_cell +
                      _editor_paint(rest, acc))
    else:
        input_line = f"  {label}: {before}[{cur_ch}]{rest}"
    hint_line = _editor_paint(truncate_plain(f"  {hint}", term_cols - 1), dim, dim=True)
    return input_line, hint_line


def _handle_input_key(key, buf, pos):
    """Process one key in text-input mode.
    Returns (new_buf, new_pos, done: bool, cancelled: bool)."""
    if key in ("\r", "\n"):
        return buf, pos, True, False
    if key == "ESC":
        return buf, pos, False, True
    if key in ("\x7f", "\x08"):
        if pos > 0:
            buf = list(buf); buf.pop(pos - 1); pos -= 1
        return buf, pos, False, False
    if key == "DELETE":
        if pos < len(buf):
            buf = list(buf); buf.pop(pos)
        return buf, pos, False, False
    if key == "LEFT":
        return buf, max(0, pos - 1), False, False
    if key == "RIGHT":
        return buf, min(len(buf), pos + 1), False, False
    if key == "HOME":
        return buf, 0, False, False
    if key == "END":
        return buf, len(buf), False, False
    if key and len(key) == 1 and key.isprintable() and len(buf) < 64:
        buf = list(buf); buf.insert(pos, key); pos += 1
    return buf, pos, False, False


# ── Playlist Editor ─────────────────────────────────────────────────────────────


def _editor_render_browse(browse_dir, entries, cursor, term_cols, term_rows):
    """Track-add browser (shows dirs + playlists + individual audio files)."""
    hi = _theme_col("title")
    lo = _theme_col("label")
    dim = _theme_col("label_dim")
    acc = _theme_col("accent")
    grn = _theme_col("good")
    yel = _theme_col("warning")
    home = os.path.expanduser("~")
    display_dir = browse_dir.replace(home, "~") if browse_dir.startswith(home) else browse_dir
    title_sep = " - " if ASCII_ONLY else " — "
    lines = [_col(f" PLAYLIST EDITOR{title_sep}Add Tracks", hi)]
    lines.append(_col(f"  {truncate_plain(display_dir, term_cols - 4)}", lo))
    lines.append(_editor_paint(_editor_rule(term_cols), dim, dim=True))
    visible_rows = max(4, term_rows - 6)
    scroll = max(0, cursor - visible_rows + 2)
    for i, (label, full_path, kind) in enumerate(entries[scroll : scroll + visible_rows]):
        real_i = i + scroll
        sel = (real_i == cursor)
        arrow = SYM_SELECT if sel else " "
        label_str = truncate_plain(label, max(10, term_cols - 10))
        kc, tag = {
            "playlist":  (acc, ".pl"),
            "audio_dir": (grn, f" {SYM_NOTE}/"),
            "audio":     (yel, f" {SYM_NOTE} "),
            "up":        (dim, " .."),
        }.get(kind, (lo, "  /"))
        line = f"  {arrow} {tag} {label_str}"
        if USE_COLOR:
            lines.append(_editor_paint(line, kc or hi, bold=sel, dim=(kc == dim and not sel)))
        else:
            lines.append(("[" + line.strip() + "]") if sel else line)
    lines.append(_editor_paint(_editor_rule(term_cols), dim, dim=True))
    hints = f"  {SYM_ARROW_U}/{SYM_ARROW_D} move  Enter open/add  s add-all-from-dir  b back  q done"
    lines.append(_editor_paint(truncate_plain(hints, term_cols - 1), dim, dim=True))
    while len(lines) < term_rows:
        lines.append("")
    return lines[:term_rows]


def _editor_render_main(pl_name, entries, cursor, status, scroll, modified,
                        input_mode, input_buf, input_pos, term_cols, term_rows):
    """Render the playlist editor track-list view."""
    hi = _theme_col("title")
    lo = _theme_col("label")
    dim = _theme_col("label_dim")
    acc = _theme_col("accent")
    red = _theme_col("danger")
    title_sep = " - " if ASCII_ONLY else " — "
    dirty     = f" {SYM_DOT_FILLED}" if modified else "  "
    title     = truncate_plain(f" PLAYLIST EDITOR{title_sep}{pl_name}{dirty}", max(20, term_cols - 16))
    count_str = f"{len(entries)} track{'s' if len(entries) != 1 else ''}"
    pad = max(1, term_cols - len(title) - len(count_str) - 1)
    lines = [_col(title + " " * pad + count_str, hi)]
    lines.append(_editor_paint(_editor_rule(term_cols), dim, dim=True))
    header_rows = 2
    hint_rows   = 3
    track_rows  = max(1, term_rows - header_rows - hint_rows)
    num_w  = len(str(max(1, len(entries))))
    name_w = max(10, term_cols - num_w - 12)
    if not entries:
        empty_sep = " - " if ASCII_ONLY else " — "
        lines.append(_editor_paint(f"  (empty{empty_sep}press [a] to add tracks, [i] to import a directory)", dim, dim=True))
    else:
        for i, e in enumerate(entries[scroll : scroll + track_rows]):
            real_i = i + scroll
            sel     = (real_i == cursor)
            missing = not e.get("exists", True)
            name  = truncate_plain(os.path.basename(e["file"]), name_w)
            wt_n  = max(1, min(5, int(e["weight"])))
            num   = f"{real_i + 1:>{num_w}}"
            arrow = SYM_SELECT if sel else " "
            left  = f"  {arrow} {num}  {name:<{name_w}}  "
            if USE_COLOR:
                # btop-style per-row weight meter (1-5 → gradient fill).
                wbar = meter_bar(wt_n / 5 * 100, 5, use_color=True)
                base = acc if sel else (red if missing else lo)
                lines.append(_editor_paint(left, base, bold=sel) + wbar)
            else:
                line = left + _wt_dots(wt_n)
                lines.append(("[" + line.strip() + "]") if sel else line)
    while len(lines) < header_rows + track_rows:
        lines.append("")
    lines.append(_editor_paint(_editor_rule(term_cols), dim, dim=True))
    if input_mode:
        inp_l, inp_h = _inline_prompt_lines("Rename", input_buf, input_pos,
                                            "Enter confirm  Esc cancel", term_cols)
        lines.append(inp_l)
        lines.append(inp_h)
    else:
        lines.append(_col(f"  {status}", _theme_col("value")) if status else "")
        hints = "  [a] add  [x] remove  [K/J] move up/down  [1-5] weight  [R] rename  [s] save  [q] quit"
        lines.append(_editor_paint(truncate_plain(hints, term_cols - 1), dim, dim=True))
    while len(lines) < term_rows:
        lines.append("")
    return lines[:term_rows]


def run_playlist_editor(path=None, name=None):
    """Full-screen .acpl playlist editor.
    path: existing .acpl to edit (None = create new).
    name: initial name for new playlist.
    Returns (saved_path_or_None, was_saved: bool).
    """
    from ac_ui.tracks import load_acpl_full, save_acpl
    from ac_ui.modal import _invalidate_after_modal, modal_confirm
    import re as _re

    if path and os.path.isfile(os.path.expanduser(path)):
        pl_name, entries = load_acpl_full(path)
        pl_path = os.path.expanduser(path)
    else:
        pl_name  = (name or "New Playlist").strip()
        entries  = []
        pl_path  = None

    orig_name    = pl_name
    orig_entries = [dict(e) for e in entries]

    cursor     = 0
    scroll     = 0
    screen     = "main"
    browse_dir = _PICKER_BROWSE_START if os.path.isdir(_PICKER_BROWSE_START) else os.path.expanduser("~")
    b_entries  = _editor_scan_browser(browse_dir)
    b_cursor   = 0
    status     = None
    in_mode    = False
    in_buf: list = []
    in_pos     = 0
    last_lines = None

    def is_modified():
        return pl_name != orig_name or [dict(e) for e in entries] != orig_entries

    def clamp():
        nonlocal cursor, scroll
        n = len(entries)
        cursor = max(0, min(cursor, n - 1)) if n else 0
        tc, tr = shutil.get_terminal_size(fallback=(80, 24))
        tr_rows = max(1, tr - 5)
        scroll_max = max(0, n - tr_rows)
        scroll = max(0, min(scroll, scroll_max))
        if cursor < scroll:
            scroll = cursor
        elif cursor >= scroll + tr_rows:
            scroll = cursor - tr_rows + 1

    try:
        hide_cursor()
        invalidate_render_cache()
        while True:
            term_cols, term_rows = shutil.get_terminal_size(fallback=(80, 24))
            clamp()
            if screen == "main":
                lines = _editor_render_main(pl_name, entries, cursor, status, scroll,
                                            is_modified(), in_mode, in_buf, in_pos,
                                            term_cols, term_rows)
            else:
                lines = _editor_render_browse(browse_dir, b_entries, b_cursor, term_cols, term_rows)
            if lines != last_lines:
                render(lines, term_cols, term_rows)
                last_lines = list(lines)

            key = _read_key(sys.stdin.fileno(), timeout=0.1)
            if key is None:
                continue
            status = None

            # ── Inline rename input ─────────────────────────────────────
            if in_mode:
                in_buf, in_pos, done, cancelled = _handle_input_key(key, in_buf, in_pos)
                if done:
                    result = "".join(in_buf).strip()
                    if result:
                        pl_name = result
                    in_mode = False
                elif cancelled:
                    in_mode = False
                last_lines = None
                continue

            # ── Browse screen ───────────────────────────────────────────
            if screen == "browse":
                if key in ("UP", "k"):
                    b_cursor = max(0, b_cursor - 1)
                elif key in ("DOWN", "j"):
                    b_cursor = min(len(b_entries) - 1, b_cursor + 1)
                elif key in ("\r", "\n"):
                    if b_entries:
                        _label, fp, kind = b_entries[b_cursor]
                        if kind in ("dir", "up", "audio_dir"):
                            if os.path.isdir(fp):
                                browse_dir = fp
                                b_entries  = _editor_scan_browser(browse_dir)
                                b_cursor   = 0
                        elif kind == "audio":
                            if not any(e["file"] == fp for e in entries):
                                entries.append({"file": fp, "weight": 1, "exists": os.path.isfile(fp)})
                                status = f"Added {os.path.basename(fp)}"
                                cursor = len(entries) - 1
                            else:
                                status = "Already in playlist"
                            screen = "main"
                        elif kind == "playlist":
                            # Import a playlist *definition* so per-track weights
                            # survive instead of being flattened to weight 1.
                            from ac_ui.tracks import load_playlist_source
                            src = load_playlist_source(fp)
                            existing = {os.path.abspath(e["file"]) for e in entries}
                            added = 0
                            for pe in src.entries:
                                ap = os.path.abspath(pe.path)
                                if ap not in existing:
                                    entries.append({"file": pe.path, "weight": pe.weight,
                                                    "exists": pe.exists})
                                    existing.add(ap)
                                    added += 1
                            status = f"Imported {added} tracks from {os.path.basename(fp)}"
                            screen = "main"
                elif key in ("s", "S"):
                    from ac_ui.tracks import scan_free_play_dir
                    new_t = scan_free_play_dir(browse_dir)
                    existing = {e["file"] for e in entries}
                    added = 0
                    for t in new_t:
                        if t not in existing:
                            entries.append({"file": t, "weight": 1, "exists": os.path.isfile(t)})
                            existing.add(t)
                            added += 1
                    status = f"Added {added} tracks from directory"
                    screen = "main"
                elif key in ("b", "B", "LEFT"):
                    parent = os.path.dirname(browse_dir)
                    if parent and parent != browse_dir:
                        browse_dir = parent
                        b_entries  = _editor_scan_browser(browse_dir)
                        b_cursor   = 0
                    else:
                        screen = "main"
                elif key in ("q", "Q", "ESC"):
                    screen = "main"
                last_lines = None
                continue

            # ── Main screen ─────────────────────────────────────────────
            if key in ("UP", "k"):
                cursor = max(0, cursor - 1)
            elif key in ("DOWN", "j"):
                cursor = min(max(0, len(entries) - 1), cursor + 1)
            elif key == "K" and entries and cursor > 0:
                entries[cursor], entries[cursor - 1] = entries[cursor - 1], entries[cursor]
                cursor -= 1
            elif key == "J" and entries and cursor < len(entries) - 1:
                entries[cursor], entries[cursor + 1] = entries[cursor + 1], entries[cursor]
                cursor += 1
            elif key in ("x", "DELETE", "\x7f") and entries:
                entries.pop(cursor)
                cursor = min(cursor, max(0, len(entries) - 1))
            elif key.isdigit() and 1 <= int(key) <= 5 and entries:
                entries[cursor]["weight"] = int(key)
            elif key in ("a", "i"):
                screen    = "browse"
                b_entries = _editor_scan_browser(browse_dir)
                b_cursor  = 0
            elif key == "R":
                in_mode = True
                in_buf  = list(pl_name)
                in_pos  = len(in_buf)
            elif key in ("s", "S"):
                if not pl_path:
                    dest = _PICKER_PLAYLISTS_DIR
                    os.makedirs(dest, exist_ok=True)
                    safe = _re.sub(r'[^\w\s-]', '', pl_name).strip().replace(" ", "_") or "playlist"
                    pl_path = os.path.join(dest, safe + ".acpl")
                    if os.path.exists(pl_path):
                        base, ext = os.path.splitext(pl_path)
                        i = 2
                        while os.path.exists(f"{base}_{i}{ext}"):
                            i += 1
                        pl_path = f"{base}_{i}{ext}"
                if save_acpl(pl_path, pl_name, entries):
                    orig_name    = pl_name
                    orig_entries = [dict(e) for e in entries]
                    return pl_path, True
                status = "Error: could not save playlist"
            elif key in ("q", "Q", "ESC"):
                if is_modified():
                    if modal_confirm("Discard unsaved changes?", term_cols, term_rows):
                        return pl_path, False
                    invalidate_render_cache()
                else:
                    return pl_path, False
            last_lines = None
    finally:
        show_cursor()
        _invalidate_after_modal()


# ── Queue Manager ───────────────────────────────────────────────────────────────


def _queue_render(playlist, idx, cursor, current_track, scroll, status, term_cols, term_rows):
    """Render the free-play queue manager."""
    hi = _theme_col("title")
    lo = _theme_col("label")
    dim = _theme_col("label_dim")
    acc = _theme_col("accent")
    grn = _theme_col("good")
    n = len(playlist)
    title     = " QUEUE MANAGER"
    count_str = f"[{n} tracks]"
    pad = max(1, term_cols - len(title) - len(count_str) - 1)
    lines = [_col(title + " " * pad + count_str, hi)]
    if current_track:
        ct = truncate_plain(os.path.basename(current_track), term_cols - 14)
        lines.append(_col(f"  {SYM_NOTE} now playing: {ct}", grn))
    else:
        lines.append(_editor_paint("  (nothing playing)", dim, dim=True))
    lines.append(_editor_paint(_editor_rule(term_cols), dim, dim=True))
    header_rows = 3
    hint_rows   = 3
    track_rows  = max(1, term_rows - header_rows - hint_rows)
    num_w  = len(str(max(1, n)))
    name_w = max(10, term_cols - num_w - 14)
    for i, track in enumerate(playlist[scroll : scroll + track_rows]):
        real_i  = i + scroll
        sel     = (real_i == cursor)
        is_next = (real_i == idx)
        played  = (real_i < idx)
        is_now  = bool(current_track and
                       os.path.abspath(current_track) == os.path.abspath(track))
        name  = truncate_plain(os.path.basename(track), name_w)
        num   = f"{real_i + 1:>{num_w}}"
        arrow = SYM_SELECT if sel else " "
        if is_now:
            tag = _col(f" {SYM_NOTE} ", grn) if USE_COLOR else f"[{SYM_NOTE}]"
        elif is_next:
            tag = _col(f" {SYM_QUEUE_NEXT} ", acc) if USE_COLOR else f"[{SYM_QUEUE_NEXT}]"
        elif played:
            tag = _editor_paint(f" {SYM_PULSE_OFF} ", dim, dim=True) if USE_COLOR else f" {SYM_PULSE_OFF} "
        else:
            tag = "   "
        line = f"  {arrow} {num}  {name:<{name_w}}"
        if USE_COLOR:
            if sel:
                line_out = _editor_paint(line, acc, bold=True) + tag
            elif played:
                line_out = _editor_paint(line, dim, dim=True) + tag
            elif is_now:
                line_out = _col(line, grn) + tag
            elif is_next:
                line_out = _col(line, acc) + tag
            else:
                line_out = _col(line, lo) + tag
        else:
            marker   = "[NOW]" if is_now else ("[NEXT]" if is_next else "")
            line_out = (("[" + line.strip() + "]") if sel else line) + marker
        lines.append(line_out)
    while len(lines) < header_rows + track_rows:
        lines.append("")
    lines.append(_editor_paint(_editor_rule(term_cols), dim, dim=True))
    lines.append(_col(f"  {status}", _theme_col("value")) if status else "")
    hints = f"  {SYM_ARROW_U}/{SYM_ARROW_D} move  [K/J] reorder  [x] remove  [Enter] play now  [s] save  [r] shuffle  [q] close"
    lines.append(_editor_paint(truncate_plain(hints, term_cols - 1), dim, dim=True))
    while len(lines) < term_rows:
        lines.append("")
    return lines[:term_rows]


def run_queue_manager(fp_playlist, fp_idx, current_track=None):
    """Full-screen queue manager for free-play mode.
    Returns (new_fp_playlist, new_fp_idx, play_now: bool).
    """
    from ac_ui.tracks import save_queue_acpl
    from ac_ui.modal import _invalidate_after_modal
    import re as _re

    if not fp_playlist:
        return fp_playlist, fp_idx, False

    playlist = list(fp_playlist)
    idx      = max(0, min(fp_idx, len(playlist)))
    cursor   = max(0, min(idx, len(playlist) - 1))
    scroll   = 0
    status   = None
    last_lines = None

    def clamp():
        nonlocal cursor, scroll
        n = len(playlist)
        cursor = max(0, min(cursor, n - 1)) if n else 0
        _tc, tr = shutil.get_terminal_size(fallback=(80, 24))
        tr_rows = max(1, tr - 6)
        scroll_max = max(0, n - tr_rows)
        scroll = max(0, min(scroll, scroll_max))
        if cursor < scroll:
            scroll = cursor
        elif cursor >= scroll + tr_rows:
            scroll = cursor - tr_rows + 1

    try:
        hide_cursor()
        invalidate_render_cache()
        while True:
            term_cols, term_rows = shutil.get_terminal_size(fallback=(80, 24))
            clamp()
            lines = _queue_render(playlist, idx, cursor, current_track,
                                  scroll, status, term_cols, term_rows)
            if lines != last_lines:
                render(lines, term_cols, term_rows)
                last_lines = list(lines)
            key = _read_key(sys.stdin.fileno(), timeout=0.1)
            if key is None:
                continue
            status = None
            if key in ("UP", "k"):
                cursor = max(0, cursor - 1)
                last_lines = None
            elif key in ("DOWN", "j"):
                cursor = min(max(0, len(playlist) - 1), cursor + 1)
                last_lines = None
            elif key == "K" and cursor > idx and cursor > 0:
                playlist[cursor], playlist[cursor - 1] = playlist[cursor - 1], playlist[cursor]
                cursor -= 1
                last_lines = None
            elif key == "J" and cursor >= idx and cursor < len(playlist) - 1:
                playlist[cursor], playlist[cursor + 1] = playlist[cursor + 1], playlist[cursor]
                cursor += 1
                last_lines = None
            elif key in ("x", "DELETE", "\x7f") and cursor >= idx:
                playlist.pop(cursor)
                if not playlist:
                    return [], 0, False
                cursor = min(cursor, len(playlist) - 1)
                idx    = min(idx, len(playlist))
                last_lines = None
            elif key in ("\r", "\n"):
                if cursor != idx:
                    track = playlist.pop(cursor)
                    playlist.insert(idx, track)
                return playlist, idx, True
            elif key in ("r", "R"):
                import random as _rnd
                remaining = playlist[idx:]
                _rnd.shuffle(remaining)
                playlist[idx:] = remaining
                status = "Remaining tracks shuffled"
                last_lines = None
            elif key in ("s", "S"):
                import time as _t
                default_name = f"Queue {_t.strftime('%b %d %H:%M')}"
                os.makedirs(_PICKER_PLAYLISTS_DIR, exist_ok=True)
                safe = _re.sub(r'[^\w\s-]', '', default_name).strip().replace(" ", "_")
                dest = os.path.join(_PICKER_PLAYLISTS_DIR, safe + ".acpl")
                if os.path.exists(dest):
                    base, ext = os.path.splitext(dest)
                    i = 2
                    while os.path.exists(f"{base}_{i}{ext}"):
                        i += 1
                    dest = f"{base}_{i}{ext}"
                # Aggregate duplicate paths back into weights and save only the
                # upcoming portion of the queue (from the current position).
                status = (f"Saved: {default_name}"
                          if save_queue_acpl(dest, default_name, playlist, idx)
                          else "Error saving playlist")
                last_lines = None
            elif key in ("q", "Q", "ESC"):
                return playlist, idx, False
    finally:
        show_cursor()
        _invalidate_after_modal()


# ── Add to Playlist ─────────────────────────────────────────────────────────────


def _add_to_playlist_render(track_name, saved, cursor, status,
                            input_mode, input_buf, input_pos, term_cols, term_rows):
    """Render the add-to-playlist track selector."""
    hi = _theme_col("title")
    lo = _theme_col("label")
    dim = _theme_col("label_dim")
    acc = _theme_col("accent")
    lines = [_col(" ADD TO PLAYLIST", hi)]
    lines.append(_col(f"  Track: {truncate_plain(track_name, term_cols - 10)}", lo))
    lines.append(_editor_paint(_editor_rule(term_cols), dim, dim=True))
    visible_rows = max(3, term_rows - 8)
    scroll = max(0, cursor - visible_rows + 2) if cursor >= visible_rows - 1 else 0
    name_w = max(10, term_cols - 20)
    for i, (path, name, count, ext) in enumerate(saved[scroll : scroll + visible_rows]):
        real_i = i + scroll
        sel = (real_i == cursor)
        arrow = SYM_SELECT if sel else " "
        nm = truncate_plain(name, name_w)
        line = f"  {arrow} {nm:<{name_w}}  {count:>3}tr  {ext}"
        if USE_COLOR:
            lines.append(_editor_paint(line, acc if sel else lo, bold=sel))
        else:
            lines.append(("[" + line.strip() + "]") if sel else line)
    new_i = len(saved)
    sel   = (cursor == new_i)
    arrow = SYM_SELECT if sel else " "
    new_line = f"  {arrow} [+ New playlist{SYM_ELLIPSIS}]"
    if USE_COLOR:
        lines.append(_editor_paint(new_line, acc if sel else dim, bold=sel, dim=not sel))
    else:
        lines.append("[+ New playlist]" if sel else new_line)
    lines.append(_editor_paint(_editor_rule(term_cols), dim, dim=True))
    if input_mode:
        inp_l, inp_h = _inline_prompt_lines("New playlist name", input_buf, input_pos,
                                            "Enter confirm  Esc cancel", term_cols)
        lines.append(inp_l)
        lines.append(inp_h)
    else:
        lines.append(_col(f"  {status}", _theme_col("value")) if status else "")
        hints = f"  {SYM_ARROW_U}/{SYM_ARROW_D} move  Enter add here  n new playlist  q cancel"
        lines.append(_editor_paint(truncate_plain(hints, term_cols - 1), dim, dim=True))
    while len(lines) < term_rows:
        lines.append("")
    return lines[:term_rows]


def run_add_to_playlist(track_path):
    """Quick modal: add track_path to a chosen playlist.
    Returns (acpl_path, playlist_name, new_track_count) or None if cancelled.
    """
    from ac_ui.tracks import add_track_to_acpl, load_acpl_full, create_empty_acpl
    from ac_ui.modal import _invalidate_after_modal

    if not track_path or not os.path.isfile(track_path):
        return None

    saved      = _picker_scan_saved()
    cursor     = 0
    total      = len(saved) + 1
    status     = None
    in_mode    = False
    in_buf: list = []
    in_pos     = 0
    last_lines = None
    track_name = os.path.basename(track_path)

    try:
        hide_cursor()
        invalidate_render_cache()
        while True:
            term_cols, term_rows = shutil.get_terminal_size(fallback=(80, 24))
            lines = _add_to_playlist_render(track_name, saved, cursor, status,
                                            in_mode, in_buf, in_pos, term_cols, term_rows)
            if lines != last_lines:
                render(lines, term_cols, term_rows)
                last_lines = list(lines)
            key = _read_key(sys.stdin.fileno(), timeout=0.1)
            if key is None:
                continue
            status = None
            if in_mode:
                in_buf, in_pos, done, cancelled = _handle_input_key(key, in_buf, in_pos)
                if done:
                    new_name = "".join(in_buf).strip()
                    if new_name:
                        new_path = create_empty_acpl(new_name)
                        if new_path and add_track_to_acpl(new_path, track_path):
                            return new_path, new_name, 1
                        status = "Error creating playlist"
                    in_mode = False
                elif cancelled:
                    in_mode = False
                last_lines = None
                continue
            if key in ("UP", "k"):
                cursor = (cursor - 1) % total
                last_lines = None
            elif key in ("DOWN", "j"):
                cursor = (cursor + 1) % total
                last_lines = None
            elif key in ("\r", "\n"):
                if cursor < len(saved):
                    acpl_path, pl_name, _, _ = saved[cursor]
                    if add_track_to_acpl(acpl_path, track_path):
                        _, ents = load_acpl_full(acpl_path)
                        return acpl_path, pl_name, len(ents)
                    status = "Could not add track"
                    last_lines = None
                else:
                    in_mode = True; in_buf = []; in_pos = 0
                    last_lines = None
            elif key in ("n", "N"):
                in_mode = True; in_buf = []; in_pos = 0
                last_lines = None
            elif key in ("q", "Q", "ESC"):
                return None
    finally:
        show_cursor()
        _invalidate_after_modal()


# ── Playlist Picker (select + manage) ──────────────────────────────────────────


def _picker_render_main_v2(saved, cursor, status, fp_playlist, term_cols, term_rows):
    """Picker main screen: saved playlists + Browse + optional Save Queue."""
    hi = _theme_col("title")
    lo = _theme_col("label")
    dim = _theme_col("label_dim")
    acc = _theme_col("accent")
    title_sep = " - " if ASCII_ONLY else " — "
    lines = [_col(f" FREE PLAY{title_sep}Playlists", hi)]
    lines.append(_editor_paint(_editor_rule(term_cols), dim, dim=True))
    visible_rows = max(3, term_rows - 9)
    scroll = max(0, cursor - visible_rows + 2) if cursor >= visible_rows - 1 else 0
    if saved:
        name_w = max(10, term_cols - 26)
        for i, (path, name, count, ext) in enumerate(saved[scroll : scroll + visible_rows]):
            real_i = i + scroll
            sel = (real_i == cursor)
            arrow = SYM_SELECT if sel else " "
            nm = truncate_plain(name, name_w)
            mtime = ""
            try:
                import datetime as _dt
                mtime = _dt.datetime.fromtimestamp(os.path.getmtime(path)).strftime("%b %d")
            except Exception:
                pass
            line = f"  {arrow} {nm:<{name_w}}  {count:>5} tracks  {mtime:>6}  {ext}"
            if USE_COLOR:
                lines.append(_editor_paint(line, acc if sel else lo, bold=sel))
            else:
                lines.append(("[" + line.strip() + "]") if sel else line)
    else:
        empty_sep = " - " if ASCII_ONLY else " — "
        lines.append(_editor_paint(f"  (no playlists{empty_sep}press [n] to create one)", dim, dim=True))
    lines.append(_editor_paint(_editor_rule(term_cols, side_pad=2), dim, dim=True))
    browse_i = len(saved)
    sel = (cursor == browse_i); arrow = SYM_SELECT if sel else " "
    bl = f"  {arrow} Browse files{SYM_ELLIPSIS}"
    lines.append(_editor_paint(bl, acc if sel else lo, bold=sel))
    if fp_playlist:
        sq_i = len(saved) + 1; sel = (cursor == sq_i); arrow = SYM_SELECT if sel else " "
        sl = f"  {arrow} Save current queue ({len(fp_playlist)} tracks){SYM_ELLIPSIS}"
        lines.append(_editor_paint(sl, acc if sel else lo, bold=sel))
    lines.append(_editor_paint(_editor_rule(term_cols, side_pad=2), dim, dim=True))
    lines.append(_col(f"  {status}", _theme_col("value")) if status else "")
    hints = "  Enter play  [e] edit  [o] $EDITOR  [n] new  [d] del  [c] copy  [a-z] jump  [q] cancel"
    lines.append(_editor_paint(truncate_plain(hints, term_cols - 1), dim, dim=True))
    while len(lines) < term_rows:
        lines.append("")
    return lines[:term_rows]


def _picker_render_browse(browse_dir, entries, cursor, term_cols, term_rows):
    """File-browser screen for the picker (dirs + playlist/audio-dir only)."""
    hi = _theme_col("title")
    lo = _theme_col("label")
    dim = _theme_col("label_dim")
    acc = _theme_col("accent")
    grn = _theme_col("good")
    home = os.path.expanduser("~")
    display_dir = browse_dir.replace(home, "~") if browse_dir.startswith(home) else browse_dir
    title_sep = " - " if ASCII_ONLY else " — "
    lines = [_col(f" FREE PLAY{title_sep}Browse", hi)]
    lines.append(_col(f"  {display_dir}", lo))
    lines.append(_editor_paint(_editor_rule(term_cols), dim, dim=True))
    visible_rows = max(4, term_rows - 6)
    scroll = max(0, cursor - visible_rows + 1) if cursor >= visible_rows else 0
    for i, (label, full_path, kind) in enumerate(entries[scroll : scroll + visible_rows]):
        real_i = i + scroll; sel = (real_i == cursor); arrow = SYM_SELECT if sel else " "
        label_str = truncate_plain(label, max(10, term_cols - 10))
        kc, _tag = {"playlist": (acc, ".pl"), "audio_dir": (grn, f" {SYM_NOTE}"),
                    "up": (dim, "..")}.get(kind, (lo, "  /"))
        line = f"  {arrow} {label_str}"
        if USE_COLOR:
            lines.append(_editor_paint(line, kc or hi, bold=sel, dim=(kc == dim and not sel)))
        else:
            lines.append(("[" + line.strip() + "]") if sel else line)
    lines.append(_editor_paint(_editor_rule(term_cols, side_pad=2), dim, dim=True))
    lines.append(_editor_paint(truncate_plain(f"  {SYM_ARROW_U}/{SYM_ARROW_D} move  Enter open  s use this  b back  [a-z] jump  q cancel",
                                              term_cols - 1), dim, dim=True))
    while len(lines) < term_rows:
        lines.append("")
    return lines[:term_rows]


def run_playlist_picker(fp_playlist=None):
    """Full-screen playlist picker with inline create/edit/delete.
    fp_playlist: pass current fp_playlist to enable 'Save queue' option.
    Returns selected path string or None if cancelled.
    """
    from ac_ui.modal import _invalidate_after_modal, modal_confirm
    from ac_ui.tracks import save_queue_acpl, duplicate_acpl
    import re as _re

    saved      = _picker_scan_saved()
    cursor     = 0
    browse_dir = _PICKER_BROWSE_START if os.path.isdir(_PICKER_BROWSE_START) else os.path.expanduser("~")
    b_entries  = _picker_scan_browser(browse_dir)
    b_cursor   = 0
    screen     = "main"
    status     = None
    last_lines = None

    def refresh():
        nonlocal saved
        saved = _picker_scan_saved()

    def total():
        return len(saved) + (2 if fp_playlist else 1)

    try:
        hide_cursor()
        invalidate_render_cache()
        while True:
            term_cols, term_rows = shutil.get_terminal_size(fallback=(80, 24))
            cursor = max(0, min(cursor, total() - 1))
            if screen == "main":
                lines = _picker_render_main_v2(saved, cursor, status, fp_playlist,
                                               term_cols, term_rows)
            else:
                lines = _picker_render_browse(browse_dir, b_entries, b_cursor, term_cols, term_rows)
            if lines != last_lines:
                render(lines, term_cols, term_rows)
                last_lines = list(lines)

            key = _read_key(sys.stdin.fileno(), timeout=0.1)
            if key is None:
                continue
            status = None

            if screen == "main":
                if key in ("UP", "k"):
                    cursor = (cursor - 1) % total(); last_lines = None
                elif key in ("DOWN", "j"):
                    cursor = (cursor + 1) % total(); last_lines = None
                elif key in ("\r", "\n", "p"):
                    n_saved = len(saved)
                    if cursor < n_saved:
                        return saved[cursor][0]
                    elif cursor == n_saved:
                        screen = "browse"; b_cursor = 0; last_lines = None
                    elif fp_playlist and cursor == n_saved + 1:
                        import time as _t
                        dn   = f"Queue {_t.strftime('%b %d %H:%M')}"
                        os.makedirs(_PICKER_PLAYLISTS_DIR, exist_ok=True)
                        safe = _re.sub(r'[^\w\s-]', '', dn).strip().replace(" ", "_")
                        dst  = os.path.join(_PICKER_PLAYLISTS_DIR, safe + ".acpl")
                        status = (f"Saved: {dn}" if save_queue_acpl(dst, dn, fp_playlist)
                                  else "Error saving")
                        refresh(); last_lines = None
                elif key in ("e", "E") and cursor < len(saved):
                    run_playlist_editor(saved[cursor][0])
                    refresh(); cursor = min(cursor, max(0, len(saved) - 1))
                    invalidate_render_cache(); last_lines = None
                elif key in ("n", "N"):
                    run_playlist_editor(name="New Playlist")
                    refresh(); invalidate_render_cache(); last_lines = None
                elif key in ("d", "D") and cursor < len(saved):
                    pl_name = saved[cursor][1]
                    if modal_confirm(f"Delete '{pl_name}'?", term_cols, term_rows):
                        try:
                            os.unlink(saved[cursor][0])
                        except OSError:
                            pass
                        refresh(); cursor = min(cursor, max(0, len(saved) - 1))
                    invalidate_render_cache(); last_lines = None
                elif key in ("c", "C") and cursor < len(saved):
                    src      = saved[cursor]
                    new_name = src[1] + " (copy)"
                    new_path = duplicate_acpl(src[0], new_name)
                    status   = f"Duplicated: {new_name}" if new_path else "Error duplicating"
                    refresh(); last_lines = None
                elif key in ("o", "O") and cursor < len(saved):
                    # Hand off to $EDITOR on the raw .acpl, then reload.
                    from ac_ui.external import open_in_editor
                    open_in_editor(saved[cursor][0])
                    refresh(); cursor = min(cursor, max(0, len(saved) - 1))
                    invalidate_render_cache(); last_lines = None
                elif key in ("q", "Q", "ESC"):
                    return None
                elif len(key) == 1 and key.isalnum():
                    # Jump mode: type a letter to hop to the next matching item.
                    labels = [s[1] for s in saved] + ["Browse files"]
                    if fp_playlist:
                        labels.append("Save current queue")
                    new_cur = next_match_index(labels, cursor, key)
                    if new_cur != cursor:
                        cursor = new_cur; last_lines = None

            else:  # browse
                if key in ("UP", "k"):
                    b_cursor = max(0, b_cursor - 1)
                elif key in ("DOWN", "j"):
                    b_cursor = min(len(b_entries) - 1, b_cursor + 1)
                elif key in ("\r", "\n"):
                    if b_entries:
                        _label, fp, kind = b_entries[b_cursor]
                        if kind in ("dir", "up"):
                            if os.path.isdir(fp):
                                browse_dir = fp; b_entries = _picker_scan_browser(browse_dir); b_cursor = 0
                        elif kind in ("playlist", "audio_dir"):
                            return fp
                elif key in ("s", "S"):
                    if b_entries:
                        _, fp, kind = b_entries[b_cursor]
                        return browse_dir if kind == "up" else fp
                    return browse_dir
                elif key in ("b", "B", "LEFT"):
                    parent = os.path.dirname(browse_dir)
                    if parent and parent != browse_dir:
                        browse_dir = parent; b_entries = _picker_scan_browser(browse_dir); b_cursor = 0
                    else:
                        screen = "main"
                elif key in ("q", "Q", "ESC"):
                    screen = "main"
                elif len(key) == 1 and key.isalnum():
                    # Jump mode: type a letter to hop to the next matching entry.
                    labels = [e[0] for e in b_entries]
                    new_cur = next_match_index(labels, b_cursor, key)
                    if new_cur != b_cursor:
                        b_cursor = new_cur
                last_lines = None
    finally:
        show_cursor()
        _invalidate_after_modal()
