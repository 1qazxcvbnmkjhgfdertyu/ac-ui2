import os, json, random, struct, wave, shutil, subprocess, tempfile, time

from ac_ui.constants import (
    TOWN_TUNE_PATH, TOWN_TUNE_HOLD, TOWN_TUNE_OFF, TOWN_TUNE_RANDOM,
    TOWN_TUNE_NOTES, TOWN_TUNE_STEPS, TOWN_TUNE_TOKEN_TO_VALUE,
    TOWN_TUNE_VALUE_TO_TOKEN, TOWN_TUNE_ENABLED, TOWN_TUNE_STEP_SECONDS,
    TOWN_TUNE_SAMPLE_DIR, TOWN_TUNE_CHIME_ENABLED, DEFAULT_TOWN_TUNE,
    ACGC_TOWN_TUNE_RENDER, ACGC_TOWN_TUNE_DUMPER, ACGC_TOWN_TUNE_ASSET_ROOT,
    ACGC_TOWN_TUNE_DISC, ACGC_TOWN_TUNE_DUMP_SECONDS, ACGC_TOWN_TUNE_DUMP_TIMEOUT,
    LEGACY_TOWN_TUNE_NOTES, MPV, HOUR_CHIME_PATH,
    _atomic_write_json, _resolve_command_path,
)

def _normalize_tune_token(token):
    if token is None:
        return None
    t = str(token).strip().upper()
    if t in ("", "NONE"):
        return None
    if t in ("-", "OFF", "O", "X"):
        return TOWN_TUNE_OFF
    if t in ("?", "RANDOM", "RAND"):
        return TOWN_TUNE_RANDOM
    if t in ("Z", "H", "HOLD", "_"):
        return TOWN_TUNE_HOLD
    # Normalize note names like c4 -> C4
    if len(t) >= 2 and t[0] in "ABCDEFG":
        note = t[0]
        suffix = t[1:]
        if suffix and suffix[0] in ("#", "B"):
            note = note + suffix[0]
            suffix = suffix[1:]
        if suffix.isdigit():
            return f"{note}{suffix}"
    return None

def _coerce_tune_value(token):
    if isinstance(token, bool):
        return None
    if isinstance(token, int):
        return token & 0xF
    if isinstance(token, str):
        t = token.strip()
        if not t:
            return None
        try:
            value = int(t, 0)
        except ValueError:
            return None
        if 0 <= value <= 15:
            return value
    return None

def _coerce_tune_token(token):
    value = _coerce_tune_value(token)
    if value is not None:
        return TOWN_TUNE_VALUE_TO_TOKEN[value]
    tok = _normalize_tune_token(token)
    if tok in (TOWN_TUNE_HOLD, TOWN_TUNE_OFF, TOWN_TUNE_RANDOM) or tok in TOWN_TUNE_NOTES:
        return tok
    if tok in LEGACY_TOWN_TUNE_NOTES:
        midi_note = note_name_to_midi(tok)
        if midi_note is None:
            return TOWN_TUNE_OFF
        best = min(
            TOWN_TUNE_NOTES,
            key=lambda cand: abs(note_name_to_midi(cand) - midi_note),
        )
        return best
    return TOWN_TUNE_OFF

def town_tune_tokens_to_values(notes):
    return [TOWN_TUNE_TOKEN_TO_VALUE.get(_coerce_tune_token(n), 15) for n in normalize_town_tune(notes)]

def town_tune_values_to_tokens(values):
    out = []
    for value in values:
        coerced = _coerce_tune_value(value)
        out.append(TOWN_TUNE_VALUE_TO_TOKEN[15 if coerced is None else coerced])
    if len(out) < TOWN_TUNE_STEPS:
        out.extend([TOWN_TUNE_OFF] * (TOWN_TUNE_STEPS - len(out)))
    return out[:TOWN_TUNE_STEPS]

def pack_town_tune_values(values):
    packed = 0
    for i, value in enumerate(town_tune_tokens_to_values(town_tune_values_to_tokens(values))):
        packed |= (value & 0xF) << (60 - i * 4)
    return packed

def unpack_town_tune_packed(packed):
    if isinstance(packed, str):
        packed = int(packed.strip(), 0)
    packed = int(packed)
    return [(packed >> (60 - i * 4)) & 0xF for i in range(TOWN_TUNE_STEPS)]

def normalize_town_tune(notes):
    out = []
    for n in notes:
        out.append(_coerce_tune_token(n))
    if len(out) < TOWN_TUNE_STEPS:
        out.extend([TOWN_TUNE_OFF] * (TOWN_TUNE_STEPS - len(out)))
    return out[:TOWN_TUNE_STEPS]

def load_town_tune():
    notes = list(DEFAULT_TOWN_TUNE)
    try:
        if os.path.exists(TOWN_TUNE_PATH):
            with open(TOWN_TUNE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                if "packed" in data:
                    notes = town_tune_values_to_tokens(unpack_town_tune_packed(data["packed"]))
                    data = None
                elif "values" in data:
                    notes = town_tune_values_to_tokens(data["values"])
                    data = None
                elif "notes" in data:
                    data = data["notes"]
            if isinstance(data, list):
                if all(_coerce_tune_value(item) is not None for item in data):
                    notes = town_tune_values_to_tokens(data)
                else:
                    notes = data
    except Exception:
        pass
    return normalize_town_tune(notes)

def save_town_tune(notes):
    notes = normalize_town_tune(notes)
    values = town_tune_tokens_to_values(notes)
    _atomic_write_json(
        TOWN_TUNE_PATH,
        {
            "notes": notes,
            "values": values,
            "packed": f"0x{pack_town_tune_values(values):016X}",
        },
    )
    return notes

def note_name_to_midi(name):
    name = name.upper()
    if name in (TOWN_TUNE_HOLD, TOWN_TUNE_OFF, TOWN_TUNE_RANDOM):
        return None
    if len(name) < 2:
        return None
    note = name[0]
    rest = name[1:]
    accidental = 0
    if rest and rest[0] in ("#", "B"):
        accidental = 1 if rest[0] == "#" else -1
        rest = rest[1:]
    if not rest.isdigit():
        return None
    octave = int(rest)
    base = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}.get(note)
    if base is None:
        return None
    return 12 * (octave + 1) + base + accidental

def _var_len(value):
    buf = [value & 0x7F]
    value >>= 7
    while value:
        buf.append(0x80 | (value & 0x7F))
        value >>= 7
    return bytes(reversed(buf))

def write_town_tune_midi(notes, path, tempo_bpm=120, ticks_per_beat=480, step_fraction=1.0, program=0):
    notes = normalize_town_tune(notes)
    step_ticks = max(1, int(ticks_per_beat * step_fraction))
    events = []
    time_ticks = 0
    i = 0
    rng = random.Random()
    while i < len(notes):
        tok = notes[i]
        if tok == TOWN_TUNE_OFF:
            time_ticks += step_ticks
            i += 1
            continue
        if tok == TOWN_TUNE_HOLD:
            time_ticks += step_ticks
            i += 1
            continue
        if tok == TOWN_TUNE_RANDOM:
            tok = rng.choice(TOWN_TUNE_NOTES)
        midi_note = note_name_to_midi(tok)
        if midi_note is None:
            time_ticks += step_ticks
            i += 1
            continue
        dur = step_ticks
        j = i + 1
        while j < len(notes) and notes[j] == TOWN_TUNE_HOLD:
            dur += step_ticks
            j += 1
        events.append((time_ticks, 1, midi_note))  # note on
        events.append((time_ticks + dur, 0, midi_note))  # note off
        time_ticks += dur
        i = j
    events.sort(key=lambda e: (e[0], e[1]))  # note-off before note-on at same time

    track = bytearray()
    # Tempo meta event
    mpqn = int(60_000_000 / max(1, int(tempo_bpm)))
    track.extend(_var_len(0))
    track.extend(b"\xFF\x51\x03")
    track.extend(struct.pack(">I", mpqn)[1:])
    # Program change
    track.extend(_var_len(0))
    track.extend(bytes([0xC0, program & 0x7F]))
    # Notes
    last_time = 0
    for t, is_on, midi_note in events:
        delta = t - last_time
        track.extend(_var_len(delta))
        if is_on:
            track.extend(bytes([0x90, midi_note, 90]))
        else:
            track.extend(bytes([0x80, midi_note, 0]))
        last_time = t
    # End of track
    track.extend(_var_len(0))
    track.extend(b"\xFF\x2F\x00")

    with open(path, "wb") as f:
        f.write(b"MThd")
        f.write(struct.pack(">IHHH", 6, 0, 1, ticks_per_beat))
        f.write(b"MTrk")
        f.write(struct.pack(">I", len(track)))
        f.write(track)

def _town_tune_sample_path(note):
    return os.path.join(TOWN_TUNE_SAMPLE_DIR, f"{note}.wav")

def _load_wav_pcm(path):
    with wave.open(path, "rb") as wf:
        params = wf.getparams()
        pcm = wf.readframes(wf.getnframes())
    return params, pcm

def _pad_pcm_segment(segment, wanted_bytes, frame_size):
    if len(segment) >= wanted_bytes:
        return segment[:wanted_bytes]
    if frame_size <= 0:
        return segment + (b"\x00" * (wanted_bytes - len(segment)))
    if len(segment) >= frame_size:
        last_frame = segment[-frame_size:]
    else:
        last_frame = b"\x00" * frame_size
    pad = bytearray(segment)
    while len(pad) + frame_size <= wanted_bytes:
        pad.extend(last_frame)
    if len(pad) < wanted_bytes:
        pad.extend(b"\x00" * (wanted_bytes - len(pad)))
    return bytes(pad)

def _run_acgc_audio_dump(args, path, timeout):
    if not ACGC_TOWN_TUNE_RENDER:
        return False
    dumper = _resolve_command_path(ACGC_TOWN_TUNE_DUMPER)
    if not dumper:
        return False

    asset_root = ACGC_TOWN_TUNE_ASSET_ROOT
    asset_file = os.path.join(asset_root, "assets", "audiorom.img")
    use_assets = os.path.exists(asset_file)
    use_disc = ACGC_TOWN_TUNE_DISC and os.path.exists(ACGC_TOWN_TUNE_DISC)
    if not use_assets and not use_disc:
        return False

    try:
        if os.path.exists(path):
            os.unlink(path)
    except Exception:
        pass

    env = os.environ.copy()
    env.setdefault("SDL_AUDIODRIVER", "dummy")
    env.setdefault("SDL_VIDEODRIVER", "dummy")
    if use_assets:
        env.pop("ACGC_DISC_PATH", None)
        cmd = [dumper] + list(args)
        cwd = asset_root
    else:
        cmd = [dumper, "--disc", ACGC_TOWN_TUNE_DISC] + list(args)
        cwd = None
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
            cwd=cwd,
            timeout=timeout,
        )
    except Exception:
        return False
    return result.returncode == 0 and os.path.exists(path) and os.path.getsize(path) > 44

def render_town_tune_from_game(notes, path):
    values = town_tune_tokens_to_values(notes)
    packed = f"{pack_town_tune_values(values):016X}"
    return _run_acgc_audio_dump(
        ["--dump-town-values", packed, path, "--dump-seconds", str(ACGC_TOWN_TUNE_DUMP_SECONDS)],
        path,
        ACGC_TOWN_TUNE_DUMP_TIMEOUT,
    )

def render_town_tune_note_from_game(note, path):
    note = _coerce_tune_token(note)
    if note not in TOWN_TUNE_NOTES:
        return False
    value = TOWN_TUNE_TOKEN_TO_VALUE[note]
    timeout = max(2.0, min(ACGC_TOWN_TUNE_DUMP_TIMEOUT, 4.0))
    return _run_acgc_audio_dump(
        ["--dump-town-note", str(value), path, "--dump-seconds", "1"],
        path,
        timeout,
    )

def _resolve_town_tune_audition_note(tok, notes=None, cursor=None):
    tok = _coerce_tune_token(tok)
    if tok in TOWN_TUNE_NOTES:
        return tok
    if tok == TOWN_TUNE_RANDOM:
        return random.choice(TOWN_TUNE_NOTES)
    if tok != TOWN_TUNE_HOLD or not notes or cursor is None:
        return None
    for prev_idx in range(int(cursor) - 1, -1, -1):
        prev = _coerce_tune_token(notes[prev_idx])
        if prev in TOWN_TUNE_NOTES:
            return prev
        if prev == TOWN_TUNE_RANDOM:
            return random.choice(TOWN_TUNE_NOTES)
        if prev == TOWN_TUNE_OFF:
            return None
    return None

def render_town_tune_note_preview(tok, path, notes=None, cursor=None):
    note = _resolve_town_tune_audition_note(tok, notes=notes, cursor=cursor)
    if note is None:
        return False
    if render_town_tune_note_from_game(note, path):
        return True
    sample_path = _town_tune_sample_path(note)
    if not os.path.exists(sample_path):
        return False
    try:
        shutil.copyfile(sample_path, path)
    except Exception:
        return False
    return os.path.exists(path) and os.path.getsize(path) > 44

def render_town_tune_from_samples(notes, path):
    notes = normalize_town_tune(notes)
    if not os.path.isdir(TOWN_TUNE_SAMPLE_DIR):
        return False
    sample_paths = {note: _town_tune_sample_path(note) for note in TOWN_TUNE_NOTES}
    if not all(os.path.exists(sample_path) for sample_path in sample_paths.values()):
        return False

    ref_params = None
    sample_pcm = {}
    for note, sample_path in sample_paths.items():
        params, pcm = _load_wav_pcm(sample_path)
        if ref_params is None:
            ref_params = params
        elif (params.nchannels != ref_params.nchannels or
              params.sampwidth != ref_params.sampwidth or
              params.framerate != ref_params.framerate):
            return False
        sample_pcm[note] = pcm

    nchannels = ref_params.nchannels
    sampwidth = ref_params.sampwidth
    framerate = ref_params.framerate
    frame_size = nchannels * sampwidth
    step_frames = max(1, int(round(framerate * TOWN_TUNE_STEP_SECONDS)))
    step_bytes = step_frames * frame_size

    out = bytearray()
    current_note = None
    current_offset_frames = 0
    for tok in notes:
        tok = _coerce_tune_token(tok)
        if tok == TOWN_TUNE_OFF:
            current_note = None
            current_offset_frames = 0
            out.extend(b"\x00" * step_bytes)
            continue
        if tok == TOWN_TUNE_RANDOM:
            tok = random.choice(TOWN_TUNE_NOTES)
        if tok == TOWN_TUNE_HOLD:
            if current_note and current_note in sample_pcm:
                pcm = sample_pcm[current_note]
                start = current_offset_frames * frame_size
                seg = pcm[start:start + step_bytes]
                out.extend(_pad_pcm_segment(seg, step_bytes, frame_size))
                current_offset_frames += step_frames
            else:
                out.extend(b"\x00" * step_bytes)
            continue
        if tok in sample_pcm:
            current_note = tok
            current_offset_frames = 0
            pcm = sample_pcm[tok]
            seg = pcm[:step_bytes]
            out.extend(_pad_pcm_segment(seg, step_bytes, frame_size))
            current_offset_frames += step_frames
            continue
        current_note = None
        current_offset_frames = 0
        out.extend(b"\x00" * step_bytes)

    with wave.open(path, "wb") as wf:
        wf.setnchannels(nchannels)
        wf.setsampwidth(sampwidth)
        wf.setframerate(framerate)
        wf.writeframes(bytes(out))
    return True

def render_town_tune_preview(notes, path, audio_device=None):
    notes = normalize_town_tune(notes)
    return render_town_tune_from_game(notes, path) or render_town_tune_from_samples(notes, path)

def _spawn_audio_file(path, audio_device=None):
    cmd = [MPV, "--no-video", "--quiet", "--no-terminal"]
    if audio_device:
        cmd.append(f"--audio-device={audio_device}")
    cmd.append(path)
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def _wait_for_ipc_socket(ipc_path, timeout=0.75):
    deadline = time.monotonic() + max(0.05, timeout)
    while time.monotonic() < deadline:
        try:
            if ipc_path and os.path.exists(ipc_path):
                return True
        except Exception:
            pass
        time.sleep(0.02)
    return False

def spawn_town_tune(audio_device=None, notes=None):
    if not TOWN_TUNE_ENABLED:
        return None, None
    notes = load_town_tune() if notes is None else normalize_town_tune(notes)
    tmp = tempfile.NamedTemporaryFile(prefix="ac-ui-tune-", suffix=".wav", delete=False)
    tmp.close()
    try:
        if not render_town_tune_preview(notes, tmp.name, audio_device=audio_device):
            raise RuntimeError("town tune preview render failed")
        proc = _spawn_audio_file(tmp.name, audio_device=audio_device)
        return proc, tmp.name
    except Exception:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass
        return None, None

def spawn_town_tune_note(tok, audio_device=None, notes=None, cursor=None):
    if not TOWN_TUNE_ENABLED:
        return None, None
    tmp = tempfile.NamedTemporaryFile(prefix="ac-ui-note-", suffix=".wav", delete=False)
    tmp.close()
    try:
        if not render_town_tune_note_preview(tok, tmp.name, notes=notes, cursor=cursor):
            raise RuntimeError("town tune note preview render failed")
        proc = _spawn_audio_file(tmp.name, audio_device=audio_device)
        return proc, tmp.name
    except Exception:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass
        return None, None

def town_tune_cli(action=None):
    notes = load_town_tune()
    if action in ("show", "print"):
        values = town_tune_tokens_to_values(notes)
        print("Town tune (16 steps):")
        print(" ".join(f"{i+1:02d}:{n}" for i, n in enumerate(notes)))
        print("Values:")
        print(" ".join(f"{value:02X}" for value in values))
        print(f"Packed: 0x{pack_town_tune_values(values):016X}")
        return 0
    if action in ("reset", "default"):
        notes = save_town_tune(DEFAULT_TOWN_TUNE)
        values = town_tune_tokens_to_values(notes)
        print(f"Reset to ACGC default town tune: 0x{pack_town_tune_values(values):016X}")
        return 0
    if action in ("play", "preview"):
        if not _resolve_command_path(MPV):
            print(f"Required player not found: {MPV}")
            return 1
        tmp = tempfile.NamedTemporaryFile(prefix="ac-ui-tune-", suffix=".wav", delete=False)
        tmp.close()
        try:
            if not render_town_tune_preview(notes, tmp.name, audio_device=None):
                print("town tune game renderer and sample bank are unavailable.")
                return 1
            result = subprocess.run([MPV, "--no-video", "--quiet", "--no-terminal", tmp.name],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        finally:
            try:
                os.unlink(tmp.name)
            except Exception:
                pass
        return result.returncode if result is not None else 1
    # Interactive editor
    print("Town tune editor (16 steps).")
    print("Available notes:")
    print("  " + " ".join(TOWN_TUNE_NOTES))
    print("Special tokens: RANDOM (random note), HOLD/Z (extend previous note), OFF (silence)")
    print("Press Enter to keep the current value.")
    updated = []
    for i in range(TOWN_TUNE_STEPS):
        current = notes[i]
        resp = input(f"Step {i+1:02d} [{current}]: ").strip()
        if not resp:
            updated.append(current)
            continue
        tok = _normalize_tune_token(resp)
        if tok in TOWN_TUNE_NOTES or tok in (TOWN_TUNE_RANDOM, TOWN_TUNE_HOLD, TOWN_TUNE_OFF):
            updated.append(tok)
        else:
            print("  Invalid token; using OFF.")
            updated.append(TOWN_TUNE_OFF)
    save_town_tune(updated)
    print(f"Saved to {TOWN_TUNE_PATH}")
    return 0

