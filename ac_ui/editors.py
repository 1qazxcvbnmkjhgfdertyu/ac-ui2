import os, sys, time, shutil

import ac_ui.colors as _clrs
from ac_ui.colors import USE_COLOR, c, c256, gradient_at, visible_len, plain_visible_len
from ac_ui.constants import (
    EQ_PRESETS, EQ_FREQ_LABELS, EQ_BAND_COUNT, EQ_BAND_MIN, EQ_BAND_MAX, EQ_CONFIG_PATH,
    SYM_ARROW_L, SYM_ARROW_R, SYM_ARROW_U, SYM_ARROW_D, SYM_ENTER,
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
from ac_ui.eq import (
    _clamp_eq_band, normalize_eq_bands, default_eq_bands,
    load_eq_bands, save_eq_bands, apply_mpv_eq, EQ_CONFIG_PATH,
)
from ac_ui.town_tune import (
    load_town_tune, save_town_tune, normalize_town_tune,
    _coerce_tune_token, spawn_town_tune, spawn_town_tune_note,
)

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
            lines.append(c("10-BAND EQ", "36"))
            lines.append(c(f"Preset: {preset_names[preset_idx]}   Band: {EQ_FREQ_LABELS[cursor]} Hz   Gain: {bands[cursor]:+.1f} dB", "33"))
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
                lines.extend([c(token_line, "36") for token_line in token_lines])
            control_width = max(12, term_cols - 1)
            control_lines = None
            for groups in (
                (
                    "[←/→]band", "[↑/↓]±1dB", "[PgUp/Dn]±3dB",
                    "[p]reset", "[r]flat", "[s]ave", "[q]done",
                ),
                ("[←/→]band", "[+/-]gain", "[p]preset", "[r]flat", "[s]ave", "[q]done"),
                ("[←/→]band", "[+/-]gain", "[q]done"),
            ):
                control_lines = wrap_grouped_items(
                    groups,
                    control_width,
                    max_lines=(2 if term_rows >= 9 else 1),
                )
                if control_lines:
                    break
            if not control_lines:
                control_lines = [truncate_plain("←/→ band  +/- gain  q done", control_width)]
            if term_rows >= 10:
                lines.append("")
            for ctrl_line in control_lines:
                lines.append(colorize_hint_keys(ctrl_line, gradient_at(_clrs._active_tod_grad, 80), base_code="33"))
            if status:
                lines.append(c(status, "35"))
            if len(lines) < term_rows:
                lines.extend([""] * (term_rows - len(lines)))
            return lines, term_cols, term_rows

        lines = []

        # ── Header ──────────────────────────────────────────────────────────
        if USE_COLOR:
            _hi = gradient_at(_clrs._active_tod_grad, 85)
            _lo = gradient_at(_clrs._active_tod_grad, 55)
            lines.append(f"\x1b[1;38;5;{_hi}m 10-BAND EQ\x1b[0m  \x1b[2;36mfrequencies: cliamp-style\x1b[0m")
            lines.append(
                f"\x1b[2;36mPreset:\x1b[0m \x1b[38;5;{_lo}m{preset_names[preset_idx]}\x1b[0m"
                f"   \x1b[2;36mBand:\x1b[0m \x1b[38;5;{_hi}m{EQ_FREQ_LABELS[cursor]} Hz\x1b[0m"
                f"   \x1b[2;36mGain:\x1b[0m \x1b[1;38;5;{_hi}m{bands[cursor]:+.1f} dB\x1b[0m"
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

            row_parts = [c256(db_label, gradient_at(_clrs._active_tod_grad, 30)) if USE_COLOR else db_label]

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
                            row_parts.append(f"\x1b[1;38;5;{gradient_at(_clrs._active_tod_grad, 90)}m ━━ \x1b[0m")
                        else:
                            row_parts.append(f"\x1b[38;5;{gradient_at(_clrs._active_tod_grad, 25)}m ╌╌ \x1b[0m")
                    else:
                        row_parts.append(" -- " if not selected else " == ")
                elif filled:
                    if USE_COLOR:
                        if selected:
                            col = gradient_at(_clrs._active_tod_grad, 95)
                            row_parts.append(f"\x1b[1;38;5;{col}m ██ \x1b[0m")
                        else:
                            col = gradient_at(_clrs._active_tod_grad, 65)
                            row_parts.append(f"\x1b[38;5;{col}m ▓▓ \x1b[0m")
                    else:
                        row_parts.append(" ## ")
                else:
                    if USE_COLOR and selected:
                        row_parts.append(f"\x1b[38;5;{gradient_at(_clrs._active_tod_grad, 22)}m ░░ \x1b[0m")
                    else:
                        row_parts.append("    ")

            lines.append("".join(row_parts))

        # ── Frequency labels ─────────────────────────────────────────────────
        freq_row = " " * LABEL_W
        for i, label in enumerate(EQ_FREQ_LABELS):
            cell = f"{label:^{BAND_W}}"
            if USE_COLOR:
                if i == cursor:
                    freq_row += f"\x1b[1;38;5;{gradient_at(_clrs._active_tod_grad, 90)}m{cell}\x1b[0m"
                else:
                    freq_row += c256(cell, gradient_at(_clrs._active_tod_grad, 45))
            else:
                freq_row += f"[{label}]" if i == cursor else cell
        lines.append(freq_row)

        # Gain value row under frequency labels
        gain_row = " " * LABEL_W
        for i, gain in enumerate(bands):
            cell = f"{gain:+.0f}".center(BAND_W)
            if USE_COLOR:
                if i == cursor:
                    gain_row += f"\x1b[1;38;5;{gradient_at(_clrs._active_tod_grad, 85)}m{cell}\x1b[0m"
                elif gain != 0.0:
                    gain_row += c256(cell, gradient_at(_clrs._active_tod_grad, 55))
                else:
                    gain_row += c256(cell, gradient_at(_clrs._active_tod_grad, 28))
            else:
                gain_row += cell
        lines.append(gain_row)

        # ── Controls ─────────────────────────────────────────────────────────
        ctrl_full = "←/→ band   ↑/↓ or +/-  ±1 dB   PgUp/Dn ±3 dB   p preset   r flat   s save   q done"
        ctrl_short = "←/→ band  +/- ±1 dB  PgUp/Dn ±3 dB  p preset  s save  q done"
        ctrl = ctrl_full if plain_visible_len(ctrl_full) <= term_cols - 1 else ctrl_short
        ctrl = truncate_plain(ctrl, term_cols - 1)
        if USE_COLOR:
            _cc = gradient_at(_clrs._active_tod_grad, 60)
            lines.append(c256(ctrl, _cc))
        else:
            lines.append(ctrl)
        if status:
            lines.append(c(status, "35") if USE_COLOR else status)

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

    def ansi256_from_rgb(rgb):
        r, g, b = rgb
        r = max(0, min(5, int(round(r / 255 * 5))))
        g = max(0, min(5, int(round(g / 255 * 5))))
        b = max(0, min(5, int(round(b / 255 * 5))))
        return 16 + 36 * r + 6 * g + b

    def rgb_color_code(rgb, bold=True):
        suffix = ";1" if bold else ""
        return f"38;5;{ansi256_from_rgb(rgb)}{suffix}"

    def note_frame_code(value):
        return rgb_color_code(ACGC_NOTE_UI[value]["env"])

    def note_detail_code(value):
        return rgb_color_code(ACGC_NOTE_UI[value]["prim"], bold=False)

    def note_glyph_code(selected=False):
        rgb = ACGC_MSCORE_GLYPH_SELECTED if selected else ACGC_MSCORE_GLYPH_IDLE
        return rgb_color_code(rgb)

    def paint(text, code):
        return c(text, code) if USE_COLOR else text

    def green(text):
        return paint(text, "38;5;46;1")

    def blue(text):
        return paint(text, "38;5;20;1")

    def orange(text):
        return paint(text, "38;5;202;1")

    def cream(text):
        return paint(text, "38;5;230")

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
            return paint(text, frame_code)

        def detail(text):
            return paint(text, detail_code)

        def glyph(text):
            return " " * visible_len(text) if playing else paint(text, glyph_code)

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
        code = "38;5;226;1" if key in button_flash else "38;5;46;1"
        return paint(text, code)

    def modal_line():
        scale_hint = "" if modal_scale >= 0.95 else " " * max(0, 3 - int(modal_scale * 3))
        active_choice = rgb_color_code(ACGC_MSCORE_ERASE_CHOICE_ACTIVE)
        idle_choice = rgb_color_code(ACGC_MSCORE_ERASE_CHOICE_IDLE)

        def choice(label, active):
            prefix = "> " if active else "  "
            return paint(prefix + label, active_choice if active else idle_choice)

        if modal == ACGC_MSCORE_MODAL_ERASE:
            yes = choice("Yes", modal_idx == 0)
            no = choice("No", modal_idx == 1)
            return scale_hint + " " * 19 + paint("Are you sure?", "38;5;196;1") + "    " + yes + "    " + no
        if modal == ACGC_MSCORE_MODAL_END:
            parts = []
            for i, option in enumerate(ACGC_MSCORE_END_OPTIONS):
                parts.append(choice(option, modal_idx == i))
            return scale_hint + " " * 9 + paint("Is this OK?", "38;5;196;1") + "    " + "    ".join(parts)
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
        lines.append(c("TOWN TUNE", "36"))
        if modal == ACGC_MSCORE_MODAL_ERASE:
            prompt = f"Erase all? {'Yes' if modal_idx == 0 else 'No'}"
        elif modal == ACGC_MSCORE_MODAL_END:
            prompt = f"Finish: {ACGC_MSCORE_END_OPTIONS[modal_idx]}"
        elif cursor >= ACGC_MSCORE_CURSOR_OK:
            prompt = "Cursor: OK"
        else:
            prompt = f"Slot {cursor + 1:02d}/16   Note: {_coerce_tune_token(notes[cursor])}"
        lines.append(c(truncate_plain(prompt, max(10, term_cols - 1)), "33"))
        if term_rows >= 10:
            lines.append("")
        row_w = max(2, min(8, max(2, (term_cols + 1) // 4)))
        for start in range(0, cell_count, row_w):
            row_text = build_row(start, row_w)
            compact_pad = " " * max(0, (term_cols - plain_visible_len(row_text)) // 2)
            lines.append(compact_pad + row_text)
        control_width = max(12, term_cols - 1)
        control_candidates = [
            ("[←/→]move", "[↑/↓]note", "[Enter]next", "[X]play", "[Y]erase", "[B]back"),
            ("[←/→]move", "[↑/↓]note", "[X]play", "[Y]erase", "[B]back"),
            ("[←/→]move", "[↑/↓]note", "[X]play", "[B]back"),
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
            control_lines = [truncate_plain("←/→ move  ↑/↓ note  X play  B back", control_width)]
        extra_lines = wrap_grouped_items(
            extra_groups,
            control_width,
            max_lines=1,
        ) if term_rows >= 12 else []
        if term_rows >= 10:
            lines.append("")
        if input_locked:
            lines.append(c("Playing town tune...", "33"))
        else:
            for ctrl_line in control_lines:
                lines.append(colorize_hint_keys(ctrl_line, gradient_at(_clrs._active_tod_grad, 80), base_code="33"))
            for extra_line in (extra_lines or []):
                lines.append(colorize_hint_keys(extra_line, gradient_at(_clrs._active_tod_grad, 65), base_code="33", bold=False))
        if status:
            lines.append(c(status, "35"))
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
        + (paint("(OK)", "38;5;196;1") if ok_active else green("(OK)"))
    )
    lines.append(
        pad_s
        + " " * 52
        + (paint("START", "38;5;196;1") if ok_active else paint("START", "38;5;244"))
    )
    lines.append("")
    if input_locked:
        help_line = "Playing town tune..."
    else:
        help_line = f"{SYM_ARROW_L}{SYM_ARROW_R} move  {SYM_ARROW_U}{SYM_ARROW_D} pitch  {SYM_ENTER} next  X play  Y erase  R e-Reader"
    lines.append(c(help_line, "33"))
    if status:
        lines.append(c(status, "35"))

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
