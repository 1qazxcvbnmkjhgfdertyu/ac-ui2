import math
from dataclasses import dataclass, field

from ac_ui.constants import CAVA_CHANNELS, CAVA_HIGHER_CUTOFF, CAVA_LOWER_CUTOFF


@dataclass(slots=True)
class AudioFeatures:
    bass: float = 0.0
    bass_att: float = 0.0
    mids: float = 0.0
    mids_att: float = 0.0
    treble: float = 0.0
    treble_att: float = 0.0
    centroid: float = 0.0
    centroid_att: float = 0.0
    contrast: float = 0.0
    contrast_att: float = 0.0
    overall: float = 0.0
    onset: float = 0.0
    left: float = 0.0
    right: float = 0.0
    width: float = 0.0
    chroma: tuple[float, ...] = ()   # 12 pitch-class energies (C..B), peak-normalized
    key: int = -1                    # dominant pitch class 0..11, or -1 when silent
    key_strength: float = 0.0        # how dominant that key is over the chroma mean


@dataclass(slots=True)
class AudioSnapshot:
    """Shared per-frame audio contract between capture, analysis, and visuals."""

    bars: tuple[float, ...] = ()
    analysis_bars: tuple[float, ...] = ()
    bars_left: tuple[float, ...] = ()
    bars_right: tuple[float, ...] = ()
    waveform_left: tuple[float, ...] = ()
    waveform_right: tuple[float, ...] = ()
    waveform_mono: tuple[float, ...] = ()
    sample_rate: int = 0
    frame_dt: float = 0.0
    source_kind: str = "none"
    features: AudioFeatures = field(default_factory=AudioFeatures)

    @property
    def has_waveform(self):
        return bool(self.waveform_left or self.waveform_right or self.waveform_mono)


def _coerce_tuple(values):
    if values is None:
        return ()
    if isinstance(values, tuple):
        return values
    return tuple(float(v) for v in (values or ()))


# Pitch-class names in the 0=C convention, for callers that want to label a key.
CHROMA_NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")

_CHROMA_PC_CACHE = {}
_SPECTRUM_WINDOW_CACHE = {}
_GOERTZEL_COEFF_CACHE = {}


def _bar_pitch_classes(count, low, high):
    """Map each log-spaced spectrum bar to its pitch class (0=C .. 11=B).

    Bars are geometrically spaced between the cava cutoffs, so bar i sits at
    `low * (high/low)^(i/(count-1))` Hz.  Folding that frequency into the 12
    semitone classes (relative to A440) lets us bin bar energy into a chroma
    vector without a full FFT.
    """
    key = (int(count), int(low), int(high))
    cached = _CHROMA_PC_CACHE.get(key)
    if cached is not None:
        return cached
    if count <= 0 or high <= low or low <= 0:
        _CHROMA_PC_CACHE[key] = ()
        return ()
    if count == 1:
        freqs = (math.sqrt(low * high),)
    else:
        ratio = (high / low) ** (1.0 / (count - 1))
        freqs = tuple(low * (ratio ** i) for i in range(count))
    # semitones above A440 → pitch class, shifted so 0 == C (A is class 9).
    pcs = tuple((int(round(12.0 * math.log2(f / 440.0))) + 9) % 12 for f in freqs)
    _CHROMA_PC_CACHE[key] = pcs
    return pcs


def _compute_chroma(bars, state, low, high):
    """Bin bar energy into 12 smoothed, peak-normalized pitch classes.

    Returns (chroma_tuple, key, key_strength).  An exponential moving average
    keeps the wheel from strobing frame to frame the way raw bins would.
    """
    n = len(bars)
    pcs = _bar_pitch_classes(n, low, high)
    if not pcs:
        return (), -1, 0.0
    raw = [0.0] * 12
    for v, pc in zip(bars, pcs):
        raw[pc] += v
    prev = state.get("chroma_sm")
    if prev is None or len(prev) != 12:
        prev = list(raw)
    smoothed = []
    for i in range(12):
        cur = raw[i]
        alpha = 0.30 if cur >= prev[i] else 0.12
        smoothed.append(prev[i] + (cur - prev[i]) * alpha)
    state["chroma_sm"] = smoothed
    peak = max(smoothed)
    if peak <= 1e-9:
        return tuple(0.0 for _ in range(12)), -1, 0.0
    norm = tuple(c / peak for c in smoothed)
    key = max(range(12), key=lambda i: norm[i])
    mean = sum(norm) / 12.0
    key_strength = max(0.0, min(1.0, (norm[key] - mean) / max(1e-6, 1.0 - mean)))
    return norm, key, key_strength


_SPECTRUM_FREQ_CACHE = {}


def _freq_cache_key(count, sample_rate, low_cut, high_cut):
    return (int(count), int(sample_rate), int(low_cut), int(high_cut))


def _spectrum_frequencies(count, sample_rate, low_cut=None, high_cut=None):
    if count <= 0 or sample_rate <= 0:
        return ()
    low = max(10.0, float(low_cut or CAVA_LOWER_CUTOFF))
    high = min(float(high_cut or CAVA_HIGHER_CUTOFF), sample_rate * 0.48)
    if high <= low:
        high = min(sample_rate * 0.48, low * 1.5)
    key = _freq_cache_key(count, sample_rate, low, high)
    cached = _SPECTRUM_FREQ_CACHE.get(key)
    if cached is not None:
        return cached
    if count == 1:
        freqs = (math.sqrt(low * high),)
    else:
        ratio = (high / low) ** (1.0 / max(1, count - 1))
        freqs = tuple(low * (ratio ** i) for i in range(count))
    _SPECTRUM_FREQ_CACHE[key] = freqs
    return freqs


def _spectrum_window(count):
    count = int(count or 0)
    if count <= 0:
        return ()
    cached = _SPECTRUM_WINDOW_CACHE.get(count)
    if cached is not None:
        return cached
    last = count - 1
    if last <= 0:
        win = (1.0,)
    else:
        step = (2.0 * math.pi) / last
        win = tuple(0.5 - 0.5 * math.cos(step * i) for i in range(count))
    _SPECTRUM_WINDOW_CACHE[count] = win
    return win


def _goertzel_coeffs(freqs, sample_rate):
    if not freqs or sample_rate <= 0:
        return ()
    key = (id(freqs), int(sample_rate))
    cached = _GOERTZEL_COEFF_CACHE.get(key)
    if cached is not None:
        return cached
    scale = (2.0 * math.pi) / sample_rate
    coeffs = tuple(2.0 * math.cos(scale * freq) for freq in freqs)
    _GOERTZEL_COEFF_CACHE[key] = coeffs
    return coeffs


def _resample_signal(values, count):
    values = _coerce_tuple(values)
    if not values or count <= 0:
        return ()
    if len(values) == count:
        return values
    if count == 1:
        return (values[len(values) // 2],)
    last = len(values) - 1
    out = []
    for i in range(count):
        pos = i / max(1, count - 1) * last
        lo = int(pos)
        hi = min(lo + 1, last)
        frac = pos - lo
        out.append(values[lo] * (1.0 - frac) + values[hi] * frac)
    return tuple(out)


def _smooth_signal(values, passes=1):
    values = _coerce_tuple(values)
    if len(values) < 3 or passes <= 0:
        return values
    work = list(values)
    for _ in range(int(passes)):
        nxt = [work[0]]
        for i in range(1, len(work) - 1):
            nxt.append(work[i - 1] * 0.2 + work[i] * 0.6 + work[i + 1] * 0.2)
        nxt.append(work[-1])
        work = nxt
    return tuple(work)


def _focused_window(values, count, *, cycles=6, min_frames=192, max_frames=960):
    values = _coerce_tuple(values)
    if not values:
        return ()
    span = max(min_frames, min(max_frames, max(count * cycles, count)))
    if len(values) <= span:
        return values
    return values[-span:]


def _trigger_align_signal(values, state=None, key="wave_trigger"):
    values = _coerce_tuple(values)
    n = len(values)
    if n < 8:
        return values
    mean = sum(values) / n
    centered = tuple(v - mean for v in values)
    lo = max(1, n // 10)
    hi = max(lo + 2, (n * 3) // 4)
    target = max(lo, min(hi - 1, int((state or {}).get(key, n // 4))))
    best_idx = None
    best_dist = None
    best_slope = None
    for i in range(lo, hi):
        prev = centered[i - 1]
        cur = centered[i]
        if prev <= 0.0 < cur:
            dist = abs(i - target)
            slope = cur - prev
            if best_idx is None or dist < best_dist or (dist == best_dist and slope > best_slope):
                best_idx = i
                best_dist = dist
                best_slope = slope
    if best_idx is None:
        return centered
    if state is not None:
        state[key] = best_idx
    return centered[best_idx:] + centered[:best_idx]


def _signal_rms(values):
    if not values:
        return 0.0
    return math.sqrt(sum(v * v for v in values) / len(values))


def _bar_views(source):
    if isinstance(source, AudioSnapshot):
        raw_bars = source.bars
        mono_bars = source.analysis_bars or raw_bars
        left_bars = source.bars_left or raw_bars
        right_bars = source.bars_right or raw_bars
        return raw_bars, mono_bars, left_bars, right_bars

    raw_bars = _coerce_tuple(source)
    if CAVA_CHANNELS == "stereo" and len(raw_bars) >= 2:
        left_bars = raw_bars[0::2]
        right_bars = raw_bars[1::2]
        n = min(len(left_bars), len(right_bars))
        if n > 0:
            left_bars = left_bars[:n]
            right_bars = right_bars[:n]
            mono_bars = tuple((l + r) * 0.5 for l, r in zip(left_bars, right_bars))
            return raw_bars, mono_bars, left_bars, right_bars
    return raw_bars, raw_bars, raw_bars, raw_bars


def analyze_audio_features(source, state=None):
    """Extract a shared musical feature set from bars or an AudioSnapshot."""
    _raw_bars, mono_bars, left_bars, right_bars = _bar_views(source)
    if not mono_bars:
        return AudioFeatures()

    bars = mono_bars
    n = len(bars)
    bass_end = max(1, n // 6)
    treble_start = max(bass_end + 1, (n * 2) // 3)
    bass = sum(bars[:bass_end]) / bass_end
    mids_slice = bars[bass_end:treble_start]
    mids = sum(mids_slice) / len(mids_slice) if mids_slice else bass
    treble_slice = bars[treble_start:]
    treble = sum(treble_slice) / len(treble_slice) if treble_slice else mids
    overall = sum(bars) / n
    total = sum(bars)
    if total > 1e-9 and n > 1:
        centroid = sum((i / (n - 1)) * v for i, v in enumerate(bars)) / total
    else:
        centroid = 0.0
    contrast = min(1.0, math.sqrt(sum((b - overall) ** 2 for b in bars) / n) * 2.2)
    stereo_n = min(len(left_bars), len(right_bars))
    left = sum(left_bars) / max(1, len(left_bars))
    right = sum(right_bars) / max(1, len(right_bars))
    width = (
        sum(abs(l - r) for l, r in zip(left_bars[:stereo_n], right_bars[:stereo_n])) / stereo_n
        if stereo_n > 0 else 0.0
    )

    if state is None:
        state = {}

    chroma, key, key_strength = _compute_chroma(bars, state, CAVA_LOWER_CUTOFF, CAVA_HIGHER_CUTOFF)

    prev_bass = state.get("prev_bass_raw", bass)
    prev_overall = state.get("prev_overall_raw", overall)
    onset = max(0.0, bass - prev_bass) * 1.35 + max(0.0, overall - prev_overall) * 0.45
    state["prev_bass_raw"] = bass
    state["prev_overall_raw"] = overall

    def _damp(key, raw, rise=0.28, fall=0.12):
        prev = state.get(key, raw)
        alpha = rise if raw >= prev else fall
        value = prev + (raw - prev) * alpha
        state[key] = value
        return value

    return AudioFeatures(
        bass=bass,
        bass_att=_damp("bass_att", bass, rise=0.32, fall=0.11),
        mids=mids,
        mids_att=_damp("mids_att", mids, rise=0.24, fall=0.10),
        treble=treble,
        treble_att=_damp("treble_att", treble, rise=0.20, fall=0.08),
        centroid=centroid,
        centroid_att=_damp("centroid_att", centroid, rise=0.18, fall=0.08),
        contrast=contrast,
        contrast_att=_damp("contrast_att", contrast, rise=0.22, fall=0.09),
        overall=overall,
        onset=min(1.5, onset),
        left=left,
        right=right,
        width=width,
        chroma=chroma,
        key=key,
        key_strength=key_strength,
    )


def _smooth_gain(state, key, target):
    if state is None:
        return target
    prev = float(state.get(key, target))
    alpha = 0.18 if target >= prev else 0.08
    gain = prev + (target - prev) * alpha
    state[key] = gain
    return gain


def _smooth_level(state, key, target, rise=0.24, fall=0.08):
    if state is None:
        return target
    prev = float(state.get(key, target))
    alpha = rise if target >= prev else fall
    value = prev + (target - prev) * alpha
    state[key] = value
    return value


def _condition_signal(values, count, state=None, gain_key="wave_gain", *, max_gain=6.0, noise_floor=0.10):
    values = _smooth_signal(_resample_signal(values, count), passes=2 if count >= 48 else 1)
    if not values:
        return ()
    mean = sum(values) / len(values)
    centered = tuple(v - mean for v in values)
    rms = _signal_rms(centered)
    if rms <= 0.008:
        return tuple(0.0 for _ in centered)
    peak = max((abs(v) for v in centered), default=0.0)
    if peak <= 1e-5:
        return tuple(0.0 for _ in centered)
    target_gain = min(max_gain, 0.82 / max(max(peak, rms * 2.2), noise_floor))
    gain = _smooth_gain(state, gain_key, target_gain)
    return tuple(max(-1.0, min(1.0, v * gain)) for v in centered)


def conditioned_waveform_mono(source, count, state=None, gain_key="wave_gain"):
    if isinstance(source, AudioSnapshot):
        values = source.waveform_mono or source.waveform_left or source.waveform_right
    else:
        values = source
    values = _focused_window(values, count, cycles=6, min_frames=192, max_frames=960)
    values = _trigger_align_signal(values, state, f"{gain_key}_trigger")
    return _condition_signal(values, count, state, gain_key, max_gain=4.0, noise_floor=0.14)


def conditioned_waveform_stereo(source, count, state=None, gain_key="scope_gain"):
    if isinstance(source, AudioSnapshot):
        left = source.waveform_left or source.waveform_mono
        right = source.waveform_right or source.waveform_mono
    else:
        left = right = source
    left = _coerce_tuple(left)
    right = _coerce_tuple(right)
    if left and right:
        span = min(len(left), len(right), max(192, min(960, max(count * 6, count))))
        left = left[-span:]
        right = right[-span:]
        _trigger_align_signal(tuple((l + r) * 0.5 for l, r in zip(left, right)), state, f"{gain_key}_trigger")
        if state is not None:
            shift = int(state.get(f"{gain_key}_trigger", 0))
            if shift > 0:
                left = left[shift:] + left[:shift]
                right = right[shift:] + right[:shift]
    left = _smooth_signal(_resample_signal(left, count), passes=2 if count >= 48 else 1)
    right = _smooth_signal(_resample_signal(right, count), passes=2 if count >= 48 else 1)
    if not left or not right:
        return (), ()

    left_mean = sum(left) / len(left)
    right_mean = sum(right) / len(right)
    left_centered = tuple(v - left_mean for v in left)
    right_centered = tuple(v - right_mean for v in right)
    peak = max(
        max((abs(v) for v in left_centered), default=0.0),
        max((abs(v) for v in right_centered), default=0.0),
    )
    rms = max(_signal_rms(left_centered), _signal_rms(right_centered))
    if rms <= 0.008:
        zeros = tuple(0.0 for _ in left_centered)
        return zeros, zeros
    if peak <= 1e-5:
        zeros = tuple(0.0 for _ in left_centered)
        return zeros, zeros

    target_gain = min(4.0, 0.82 / max(max(peak, rms * 2.2), 0.12))
    gain = _smooth_gain(state, gain_key, target_gain)
    left_out = tuple(max(-1.0, min(1.0, v * gain)) for v in left_centered)
    right_out = tuple(max(-1.0, min(1.0, v * gain)) for v in right_centered)
    return left_out, right_out


def _prepare_spectrum_signal(values, max_frames=1024):
    values = _coerce_tuple(values)
    if not values:
        return ()
    if len(values) > max_frames:
        values = values[-max_frames:]
    n = len(values)
    mean = sum(values) / n
    if n == 1:
        return (values[0] - mean,)
    window = _spectrum_window(n)
    return tuple((values[i] - mean) * window[i] for i in range(n))


def _goertzel_magnitudes(samples, freqs, sample_rate, coeffs=None):
    if not samples or not freqs or sample_rate <= 0:
        return ()
    coeffs = coeffs or _goertzel_coeffs(freqs, sample_rate)
    out = []
    n = len(samples)
    append = out.append
    for coeff in coeffs:
        q0 = q1 = q2 = 0.0
        for sample in samples:
            q0 = sample + coeff * q1 - q2
            q2 = q1
            q1 = q0
        power = q1 * q1 + q2 * q2 - coeff * q1 * q2
        append(math.sqrt(max(0.0, power)) / max(1, n))
    return tuple(out)


def _normalize_spectrum(mags, state=None, scale_key="pcm_spec_scale"):
    if not mags:
        return ()
    peak = max(mags)
    if peak <= 1e-8:
        return tuple(0.0 for _ in mags)
    scale = _smooth_level(state, scale_key, peak, rise=0.35, fall=0.06)
    scale = max(scale, peak * 0.5, 1e-6)
    return tuple(min(1.0, (m / scale) ** 0.72) for m in mags)


def spectrum_bars_from_waveform(
    waveform_left,
    waveform_right=None,
    count=32,
    *,
    sample_rate=48000,
    state=None,
    low_cut=None,
    high_cut=None,
):
    """Derive coarse mono/stereo spectrum bars from live PCM waveform windows."""
    count = max(1, int(count or 0))
    left_raw = _coerce_tuple(waveform_left)
    right_raw = _coerce_tuple(waveform_right)
    if not left_raw and not right_raw:
        return (), (), ()
    if not left_raw:
        left_raw = right_raw
    if not right_raw:
        right_raw = left_raw

    left = _prepare_spectrum_signal(left_raw)
    right = _prepare_spectrum_signal(right_raw)
    mono = tuple((l + r) * 0.5 for l, r in zip(left, right))
    if not mono:
        return (), (), ()
    if _signal_rms(mono) < 1e-4:
        zeros = tuple(0.0 for _ in range(count))
        return zeros, zeros, zeros

    freqs = _spectrum_frequencies(count, sample_rate, low_cut=low_cut, high_cut=high_cut)
    coeffs = _goertzel_coeffs(freqs, sample_rate)
    mono_mags = _goertzel_magnitudes(mono, freqs, sample_rate, coeffs=coeffs)
    left_mags = _goertzel_magnitudes(left, freqs, sample_rate, coeffs=coeffs)
    right_mags = _goertzel_magnitudes(right, freqs, sample_rate, coeffs=coeffs)
    bars = _normalize_spectrum(mono_mags, state, "pcm_spec_scale")
    left_bars = _normalize_spectrum(left_mags, state, "pcm_spec_scale_left")
    right_bars = _normalize_spectrum(right_mags, state, "pcm_spec_scale_right")
    return bars, left_bars, right_bars


def build_audio_snapshot(
    bars,
    state=None,
    *,
    analysis_bars=None,
    bars_left=None,
    bars_right=None,
    waveform_left=None,
    waveform_right=None,
    waveform_mono=None,
    sample_rate=0,
    frame_dt=0.0,
    source_kind="unknown",
):
    """Build the shared audio snapshot from the currently available inputs."""
    raw_bars = _coerce_tuple(bars)
    raw_bars, default_mono_bars, default_left_bars, default_right_bars = _bar_views(raw_bars)
    mono_bars = _coerce_tuple(analysis_bars)
    left_bars = _coerce_tuple(bars_left)
    right_bars = _coerce_tuple(bars_right)
    if mono_bars or left_bars or right_bars:
        if not mono_bars:
            if left_bars and right_bars:
                n = min(len(left_bars), len(right_bars))
                mono_bars = tuple((l + r) * 0.5 for l, r in zip(left_bars[:n], right_bars[:n]))
            else:
                mono_bars = tuple(default_mono_bars or left_bars or right_bars or raw_bars)
        if not left_bars:
            left_bars = tuple(default_left_bars or mono_bars or raw_bars)
        if not right_bars:
            right_bars = tuple(default_right_bars or mono_bars or raw_bars)
    else:
        mono_bars = default_mono_bars
        left_bars = default_left_bars
        right_bars = default_right_bars
    wave_left = _coerce_tuple(waveform_left)
    wave_right = _coerce_tuple(waveform_right)
    wave_mono = _coerce_tuple(waveform_mono)
    if not wave_mono:
        if wave_left and wave_right:
            n = min(len(wave_left), len(wave_right))
            wave_mono = tuple((l + r) * 0.5 for l, r in zip(wave_left[:n], wave_right[:n]))
        else:
            wave_mono = tuple(wave_left or wave_right)

    snap = AudioSnapshot(
        bars=raw_bars,
        analysis_bars=mono_bars,
        bars_left=left_bars,
        bars_right=right_bars,
        waveform_left=wave_left,
        waveform_right=wave_right,
        waveform_mono=wave_mono,
        sample_rate=int(sample_rate or 0),
        frame_dt=float(frame_dt or 0.0),
        source_kind=str(source_kind or "unknown"),
        features=AudioFeatures(),
    )
    snap.features = analyze_audio_features(snap, state)
    return snap


def build_live_audio_snapshot(
    bars,
    state=None,
    *,
    waveform_left=None,
    waveform_right=None,
    waveform_mono=None,
    sample_rate=0,
    frame_dt=0.0,
    fallback_bar_count=0,
    low_cut=None,
    high_cut=None,
):
    """Build a live snapshot, deriving spectrum bars from PCM when needed.

    The main UI prefers external bar feeds from `cava`, but PCM waveform capture
    can still drive the visualizer and feature extraction when that feed is
    missing. In that case we derive a coarse bar view from the waveform so the
    rest of the rendering pipeline can continue using the shared snapshot
    contract unchanged.
    """
    raw_bars = _coerce_tuple(bars)
    wave_left = _coerce_tuple(waveform_left)
    wave_right = _coerce_tuple(waveform_right)
    wave_mono = _coerce_tuple(waveform_mono)
    sample_rate = int(sample_rate or 0)

    analysis_bars = None
    bars_left = None
    bars_right = None
    has_waveform = bool(wave_left or wave_right or wave_mono)

    if raw_bars:
        source_kind = "cava+pcm" if has_waveform else "cava"
    elif has_waveform and sample_rate > 0 and int(fallback_bar_count or 0) > 0:
        spec_mono, spec_left, spec_right = spectrum_bars_from_waveform(
            wave_left or wave_mono,
            wave_right or wave_mono,
            int(fallback_bar_count),
            sample_rate=sample_rate,
            state=state,
            low_cut=low_cut,
            high_cut=high_cut,
        )
        raw_bars = _coerce_tuple(spec_mono)
        analysis_bars = raw_bars
        bars_left = _coerce_tuple(spec_left)
        bars_right = _coerce_tuple(spec_right)
        source_kind = "pcm"
    elif has_waveform:
        source_kind = "pcm"
    else:
        source_kind = "none"

    return build_audio_snapshot(
        raw_bars,
        state,
        analysis_bars=analysis_bars,
        bars_left=bars_left,
        bars_right=bars_right,
        waveform_left=wave_left,
        waveform_right=wave_right,
        waveform_mono=wave_mono,
        sample_rate=sample_rate,
        frame_dt=frame_dt,
        source_kind=source_kind,
    )
