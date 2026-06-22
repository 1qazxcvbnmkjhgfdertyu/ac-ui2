# cython: language_level=3, boundscheck=False, wraparound=False, cdivision=True
"""Compiled hot path for the feedback-tunnel visualizers (kaleido / liquid /
plasma).  This mirrors the pure-Python ``_feedback_transform`` in visualizer.py
exactly; visualizer.py imports and uses it when built, and falls back to the
pure-Python version when this module isn't compiled.  Build with::

    .venv/bin/python build_native.py        # or: cythonize -i ac_ui/_vizfast.pyx
"""
from libc.math cimport sin, cos, atan2, sqrt, fmod, M_PI, pow, fabs, round
from libc.stdlib cimport malloc, free

cdef tuple _BRAILLE_CHAR_LUT = tuple(chr(0x2800 + i) for i in range(256))


def feedback_transform_into(list src_inten, list src_hue, list dst_inten, list dst_hue,
                            int dot_rows, int dot_cols,
                            double decay, double zoom, double rot,
                            double drift_x, double drift_y, double hue_shift,
                            int mirror, double swirl, double pinch,
                            double warp_amp, double warp_freq, double warp_phase):
    """Write the transformed feedback field into preallocated destination lists."""
    cdef int size = dot_rows * dot_cols
    if size <= 0:
        return
    if len(dst_inten) != size or len(dst_hue) != size:
        raise ValueError("destination buffers do not match feedback field size")

    cdef double cx = (dot_cols - 1) / 2.0
    cdef double cy = (dot_rows - 1) / 2.0
    cdef double sxcx = cx if cx > 1.0 else 1.0
    cdef double sycy = cy if cy > 1.0 else 1.0
    cdef double inv_cx = 1.0 / sxcx
    cdef double inv_cy = 1.0 / sycy
    cdef double cos_r = cos(rot)
    cdef double sin_r = sin(rot)
    cdef double inv_zoom = 1.0 / (zoom if zoom > 0.001 else 0.001)
    cdef bint per_pixel = (swirl != 0.0) or (pinch != 0.0) or (warp_amp != 0.0)
    cdef bint do_mirror = mirror != 0
    cdef double seg = (M_PI / (mirror if mirror >= 1 else 1)) if do_mirror else 0.0
    cdef double seg2 = seg * 2.0
    cdef int i, x, y, src_x, src_y, src_idx, row_out
    cdef double nx, ny, tx, ty, sxn, syn, r, f, a, ca, sa, ang, v

    # Copy source intensity into a C array for fast reads in the hot loop.
    cdef double* si = <double*> malloc(size * sizeof(double))
    if si == NULL:
        raise MemoryError()

    try:
        for i in range(size):
            si[i] = src_inten[i]
            dst_inten[i] = 0.0
            dst_hue[i] = 50

        for y in range(dot_rows):
            ny = (y - cy) * inv_cy
            ty = (ny - drift_y) * inv_zoom
            row_out = y * dot_cols
            for x in range(dot_cols):
                nx = (x - cx) * inv_cx
                tx = (nx - drift_x) * inv_zoom
                sxn = tx * cos_r + ty * sin_r
                syn = -tx * sin_r + ty * cos_r

                if per_pixel and (sxn != 0.0 or syn != 0.0):
                    r = sqrt(sxn * sxn + syn * syn)
                    if pinch != 0.0:
                        f = 1.0 + pinch * (0.6 - (1.4 if r > 1.4 else r))
                        sxn = sxn * f
                        syn = syn * f
                    if swirl != 0.0 and r < 1.0:
                        a = swirl * (1.0 - r)
                        ca = cos(a)
                        sa = sin(a)
                        sxn, syn = sxn * ca - syn * sa, sxn * sa + syn * ca
                    if warp_amp != 0.0:
                        sxn = sxn + warp_amp * sin(syn * warp_freq + warp_phase)
                        syn = syn + warp_amp * cos(sxn * warp_freq + warp_phase)

                if do_mirror and (sxn != 0.0 or syn != 0.0):
                    ang = atan2(syn, sxn)
                    r = sqrt(sxn * sxn + syn * syn)
                    ang = ang + seg
                    ang = fmod(ang, seg2)
                    if ang < 0.0:
                        ang = ang + seg2     # match Python's % (always non-negative)
                    ang = ang - seg
                    if ang < 0.0:
                        ang = -ang
                    sxn = cos(ang) * r
                    syn = sin(ang) * r

                src_x = <int>(sxn * sxcx + cx + 0.5)
                if src_x < 0 or src_x >= dot_cols:
                    continue
                src_y = <int>(syn * sycy + cy + 0.5)
                if src_y < 0 or src_y >= dot_rows:
                    continue
                src_idx = src_y * dot_cols + src_x
                v = si[src_idx] * decay
                if v > 0.01:
                    dst_inten[row_out + x] = v
                    dst_hue[row_out + x] = fmod(src_hue[src_idx] + hue_shift, 101.0)
    finally:
        free(si)

def feedback_transform(list src_inten, list src_hue, int dot_rows, int dot_cols,
                       double decay, double zoom, double rot,
                       double drift_x, double drift_y, double hue_shift,
                       int mirror, double swirl, double pinch,
                       double warp_amp, double warp_freq, double warp_phase):
    """Decayed, warped, kaleidoscope-mirrored copy of the previous dot field.

    Returns (out_inten, out_hue) as plain Python lists — same contract as the
    pure-Python implementation.
    """
    cdef int size = dot_rows * dot_cols
    cdef list out_inten = [0.0] * size
    cdef list out_hue = [50] * size
    if size <= 0:
        return out_inten, out_hue
    feedback_transform_into(
        src_inten, src_hue, out_inten, out_hue, dot_rows, dot_cols,
        decay, zoom, rot, drift_x, drift_y, hue_shift,
        mirror, swirl, pinch, warp_amp, warp_freq, warp_phase,
    )
    return out_inten, out_hue


def feedback_transform_into_buf(float[::1] src_inten, unsigned char[::1] src_hue,
                                float[::1] dst_inten, unsigned char[::1] dst_hue,
                                int dot_rows, int dot_cols,
                                double decay, double zoom, double rot,
                                double drift_x, double drift_y, double hue_shift,
                                int mirror, double swirl, double pinch,
                                double warp_amp, double warp_freq, double warp_phase):
    """Write the transformed feedback field into packed numeric buffers."""
    cdef int size = dot_rows * dot_cols
    if size <= 0:
        return
    if (
        src_inten.shape[0] != size or src_hue.shape[0] != size
        or dst_inten.shape[0] != size or dst_hue.shape[0] != size
    ):
        raise ValueError("feedback buffers do not match feedback field size")

    cdef double cx = (dot_cols - 1) / 2.0
    cdef double cy = (dot_rows - 1) / 2.0
    cdef double sxcx = cx if cx > 1.0 else 1.0
    cdef double sycy = cy if cy > 1.0 else 1.0
    cdef double inv_cx = 1.0 / sxcx
    cdef double inv_cy = 1.0 / sycy
    cdef double cos_r = cos(rot)
    cdef double sin_r = sin(rot)
    cdef double inv_zoom = 1.0 / (zoom if zoom > 0.001 else 0.001)
    cdef bint per_pixel = (swirl != 0.0) or (pinch != 0.0) or (warp_amp != 0.0)
    cdef bint do_mirror = mirror != 0
    cdef double seg = (M_PI / (mirror if mirror >= 1 else 1)) if do_mirror else 0.0
    cdef double seg2 = seg * 2.0
    cdef int i, x, y, src_x, src_y, src_idx, row_out
    cdef double nx, ny, tx, ty, sxn, syn, r, f, a, ca, sa, ang, v
    cdef double* x_cos = <double*> malloc(dot_cols * sizeof(double))
    cdef double* x_sin = <double*> malloc(dot_cols * sizeof(double))
    cdef double* y_sin = <double*> malloc(dot_rows * sizeof(double))
    cdef double* y_cos = <double*> malloc(dot_rows * sizeof(double))

    if x_cos == NULL or x_sin == NULL or y_sin == NULL or y_cos == NULL:
        if x_cos != NULL:
            free(x_cos)
        if x_sin != NULL:
            free(x_sin)
        if y_sin != NULL:
            free(y_sin)
        if y_cos != NULL:
            free(y_cos)
        raise MemoryError()

    try:
        for x in range(dot_cols):
            nx = (x - cx) * inv_cx
            tx = (nx - drift_x) * inv_zoom
            x_cos[x] = tx * cos_r
            x_sin[x] = -tx * sin_r

        for y in range(dot_rows):
            ny = (y - cy) * inv_cy
            ty = (ny - drift_y) * inv_zoom
            y_sin[y] = ty * sin_r
            y_cos[y] = ty * cos_r

        # Hue is consulted only where intensity survives the 0.01 cutoff, so we
        # only need to clear the intensity buffer here. Visible writes below
        # always refresh hue in lockstep with intensity.
        for i in range(size):
            dst_inten[i] = 0.0

        for y in range(dot_rows):
            row_out = y * dot_cols
            for x in range(dot_cols):
                sxn = x_cos[x] + y_sin[y]
                syn = x_sin[x] + y_cos[y]

                if per_pixel and (sxn != 0.0 or syn != 0.0):
                    r = sqrt(sxn * sxn + syn * syn)
                    if pinch != 0.0:
                        f = 1.0 + pinch * (0.6 - (1.4 if r > 1.4 else r))
                        sxn = sxn * f
                        syn = syn * f
                    if swirl != 0.0 and r < 1.0:
                        a = swirl * (1.0 - r)
                        ca = cos(a)
                        sa = sin(a)
                        sxn, syn = sxn * ca - syn * sa, sxn * sa + syn * ca
                    if warp_amp != 0.0:
                        sxn = sxn + warp_amp * sin(syn * warp_freq + warp_phase)
                        syn = syn + warp_amp * cos(sxn * warp_freq + warp_phase)

                if do_mirror and (sxn != 0.0 or syn != 0.0):
                    ang = atan2(syn, sxn)
                    r = sqrt(sxn * sxn + syn * syn)
                    ang = ang + seg
                    ang = fmod(ang, seg2)
                    if ang < 0.0:
                        ang = ang + seg2
                    ang = ang - seg
                    if ang < 0.0:
                        ang = -ang
                    sxn = cos(ang) * r
                    syn = sin(ang) * r

                src_x = <int>(sxn * sxcx + cx + 0.5)
                if src_x < 0 or src_x >= dot_cols:
                    continue
                src_y = <int>(syn * sycy + cy + 0.5)
                if src_y < 0 or src_y >= dot_rows:
                    continue
                src_idx = src_y * dot_cols + src_x
                v = src_inten[src_idx] * decay
                if v > 0.01:
                    dst_inten[row_out + x] = v
                    dst_hue[row_out + x] = <unsigned char> fmod(src_hue[src_idx] + hue_shift, 101.0)
    finally:
        free(x_cos)
        free(x_sin)
        free(y_sin)
        free(y_cos)


def feedback_transform_kaleido_buf(float[::1] src_inten, unsigned char[::1] src_hue,
                                   float[::1] dst_inten, unsigned char[::1] dst_hue,
                                   int dot_rows, int dot_cols,
                                   double decay, double zoom, double rot,
                                   double drift_x, double drift_y, double hue_shift,
                                   int mirror, double swirl, double pinch,
                                   double warp_amp, double warp_freq, double warp_phase):
    """Compatibility alias for the packed-buffer feedback helper."""
    feedback_transform_into_buf(
        src_inten, src_hue, dst_inten, dst_hue, dot_rows, dot_cols,
        decay, zoom, rot, drift_x, drift_y, hue_shift,
        mirror, swirl, pinch, warp_amp, warp_freq, warp_phase,
    )

def build_warp_map_buf(int[::1] warp_idx, int dot_rows, int dot_cols,
                       double zoom, double rot,
                       double drift_x, double drift_y,
                       int mirror, double swirl, double pinch,
                       double warp_amp, double warp_freq, double warp_phase,
                       int row_start=0, int row_end=-1):
    """Precompute the per-destination source index map (Geiss-style warp map).

    Stores, for each destination pixel, the source index it samples from (or -1
    when the sample falls out of bounds). This is the *geometry only* — all the
    per-pixel trig (swirl/warp/mirror) lives here, computed ONCE. ``decay`` and
    ``hue_shift`` are deliberately NOT baked in; they stay live in the per-frame
    gather (``feedback_gather_buf``). Mirrors ``feedback_transform_into_buf``'s
    coordinate math exactly so a cached frame is geometrically identical.

    ``row_start``/``row_end`` restrict the build to a band of rows so a full map
    can be regenerated incrementally across several frames (Geiss built the next
    warp map "a row at a time in the background"), avoiding a single expensive
    rebuild spike.
    """
    cdef int size = dot_rows * dot_cols
    if size <= 0:
        return
    if warp_idx.shape[0] != size:
        raise ValueError("warp map does not match feedback field size")
    if row_end < 0 or row_end > dot_rows:
        row_end = dot_rows
    if row_start < 0:
        row_start = 0
    if row_start >= row_end:
        return

    cdef double cx = (dot_cols - 1) / 2.0
    cdef double cy = (dot_rows - 1) / 2.0
    cdef double sxcx = cx if cx > 1.0 else 1.0
    cdef double sycy = cy if cy > 1.0 else 1.0
    cdef double inv_cx = 1.0 / sxcx
    cdef double inv_cy = 1.0 / sycy
    cdef double cos_r = cos(rot)
    cdef double sin_r = sin(rot)
    cdef double inv_zoom = 1.0 / (zoom if zoom > 0.001 else 0.001)
    cdef bint per_pixel = (swirl != 0.0) or (pinch != 0.0) or (warp_amp != 0.0)
    cdef bint do_mirror = mirror != 0
    cdef double seg = (M_PI / (mirror if mirror >= 1 else 1)) if do_mirror else 0.0
    cdef double seg2 = seg * 2.0
    cdef int x, y, src_x, src_y, row_out
    cdef double nx, ny, tx, ty, ty_sin, ty_cos, sxn, syn, r, f, a, ca, sa, ang
    cdef double* x_cos = <double*> malloc(dot_cols * sizeof(double))
    cdef double* x_sin = <double*> malloc(dot_cols * sizeof(double))

    if x_cos == NULL or x_sin == NULL:
        if x_cos != NULL:
            free(x_cos)
        if x_sin != NULL:
            free(x_sin)
        raise MemoryError()

    try:
        for x in range(dot_cols):
            nx = (x - cx) * inv_cx
            tx = (nx - drift_x) * inv_zoom
            x_cos[x] = tx * cos_r
            x_sin[x] = -tx * sin_r

        for y in range(row_start, row_end):
            ny = (y - cy) * inv_cy
            ty = (ny - drift_y) * inv_zoom
            ty_sin = ty * sin_r
            ty_cos = ty * cos_r
            row_out = y * dot_cols
            for x in range(dot_cols):
                sxn = x_cos[x] + ty_sin
                syn = x_sin[x] + ty_cos

                if per_pixel and (sxn != 0.0 or syn != 0.0):
                    r = sqrt(sxn * sxn + syn * syn)
                    if pinch != 0.0:
                        f = 1.0 + pinch * (0.6 - (1.4 if r > 1.4 else r))
                        sxn = sxn * f
                        syn = syn * f
                    if swirl != 0.0 and r < 1.0:
                        a = swirl * (1.0 - r)
                        ca = cos(a)
                        sa = sin(a)
                        sxn, syn = sxn * ca - syn * sa, sxn * sa + syn * ca
                    if warp_amp != 0.0:
                        sxn = sxn + warp_amp * sin(syn * warp_freq + warp_phase)
                        syn = syn + warp_amp * cos(sxn * warp_freq + warp_phase)

                if do_mirror and (sxn != 0.0 or syn != 0.0):
                    ang = atan2(syn, sxn)
                    r = sqrt(sxn * sxn + syn * syn)
                    ang = ang + seg
                    ang = fmod(ang, seg2)
                    if ang < 0.0:
                        ang = ang + seg2
                    ang = ang - seg
                    if ang < 0.0:
                        ang = -ang
                    sxn = cos(ang) * r
                    syn = sin(ang) * r

                src_x = <int>(sxn * sxcx + cx + 0.5)
                if src_x < 0 or src_x >= dot_cols:
                    warp_idx[row_out + x] = -1
                    continue
                src_y = <int>(syn * sycy + cy + 0.5)
                if src_y < 0 or src_y >= dot_rows:
                    warp_idx[row_out + x] = -1
                    continue
                warp_idx[row_out + x] = src_y * dot_cols + src_x
    finally:
        free(x_cos)
        free(x_sin)


def feedback_gather_buf(float[::1] src_inten, unsigned char[::1] src_hue,
                        float[::1] dst_inten, unsigned char[::1] dst_hue,
                        int[::1] warp_idx, int size,
                        double decay, double hue_shift):
    """Per-frame gather through a cached warp map — no trig.

    The cheap half of the Geiss split: read the precomputed source index for
    each destination pixel and apply the live ``decay``/``hue_shift``. This is
    all that runs on a frame where the warp map is reused.
    """
    if (
        src_inten.shape[0] != size or src_hue.shape[0] != size
        or dst_inten.shape[0] != size or dst_hue.shape[0] != size
        or warp_idx.shape[0] != size
    ):
        raise ValueError("feedback buffers do not match feedback field size")
    cdef int i, si
    cdef double v, t
    # Reduce hue_shift once; src_hue is 0..100 so src_hue + hs < 202 and a single
    # conditional subtract reproduces fmod(src_hue + hue_shift, 101) exactly,
    # avoiding a per-pixel fmod on the hottest loop.
    cdef double hs = fmod(hue_shift, 101.0)
    # Single pass: every dst_inten is written exactly once (0 for OOB / sub-
    # threshold), so no separate clear pass is needed. Hue is only refreshed on
    # visible writes (stale hue under unlit pixels is never read), matching
    # feedback_transform_into_buf.
    for i in range(size):
        si = warp_idx[i]
        if si >= 0:
            v = src_inten[si] * decay
            if v > 0.01:
                dst_inten[i] = v
                t = src_hue[si] + hs
                if t >= 101.0:
                    t -= 101.0
                dst_hue[i] = <unsigned char> t
            else:
                dst_inten[i] = 0.0
        else:
            dst_inten[i] = 0.0


def kaleido_overlay(list inten, list hue, list active, object bars,
                    double phase, int symmetry, double ang_off,
                    double f03, double f09):
    """Overlay kaleido tunnel spokes onto an existing feedback field in place."""
    cdef Py_ssize_t i, n = len(active)
    cdef object item
    cdef int idx, band_idx
    cdef long whole
    cdef double base_ang, omr22, hue_base, a, ang, ridge, q, ridge2, lane, twist, val
    cdef double seg = M_PI / (symmetry if symmetry >= 1 else 1)
    cdef double seg2 = seg * 2.0
    cdef double sym26 = symmetry * 2.6
    cdef double sym2 = symmetry * 2.0
    cdef double pi_inv = 18.0 / M_PI
    cdef double ridge_pi_inv = 1.0 / M_PI

    for i in range(n):
        item = active[i]
        idx = <int> item[0]
        base_ang = <double> item[1]
        band_idx = <int> item[2]
        omr22 = <double> item[3]
        hue_base = <double> item[4]

        a = base_ang + ang_off + seg
        ang = fmod(a, seg2)
        if ang < 0.0:
            ang += seg2
        ang -= seg
        if ang < 0.0:
            ang = -ang

        # The spoke ridge needs |sin(theta)| < 0.2 for lane>0, i.e. theta within
        # asin(0.2)=0.20135792 of a multiple of pi. Range-reduce to that distance
        # |d| and reject the ~87% of off-spoke pixels BEFORE paying for a sin
        # (sin was the overlay's dominant per-pixel cost). On a spoke,
        # |sin(theta)| == sin(|d|) exactly, so the kept pixels are unchanged.
        ridge = omr22 - phase + ang * sym26
        q = ridge * ridge_pi_inv
        whole = <long>(q + 0.5) if q >= 0.0 else <long>(q - 0.5)
        ridge = ridge - M_PI * whole
        if ridge < 0.0:
            ridge = -ridge
        if ridge >= 0.20135792079033079:
            continue
        ridge2 = ridge * ridge
        lane = 1.0 - (ridge * (1.0 - ridge2 / 6.0)) * 5.0

        twist = 0.5 + 0.5 * cos(ang * sym2 + f03)
        val = lane * lane * lane * (0.20 + <double> bars[band_idx] * 0.90) * (0.35 + twist * 0.80)
        if val <= 0.06:
            continue
        if val > inten[idx]:
            inten[idx] = val
            hue[idx] = <int> fmod(hue_base + ang * pi_inv + f09, 101.0)


def kaleido_overlay_buf(float[::1] inten, unsigned char[::1] hue, list active, object bars,
                        double phase, int symmetry, double ang_off,
                        double f03, double f09):
    """Overlay kaleido tunnel spokes onto packed feedback buffers in place."""
    cdef Py_ssize_t i, n = len(active)
    cdef object item
    cdef int idx, band_idx
    cdef long whole
    cdef double base_ang, omr22, hue_base, a, ang, ridge, q, ridge2, lane, twist, val
    cdef double seg = M_PI / (symmetry if symmetry >= 1 else 1)
    cdef double seg2 = seg * 2.0
    cdef double sym26 = symmetry * 2.6
    cdef double sym2 = symmetry * 2.0
    cdef double pi_inv = 18.0 / M_PI
    cdef double ridge_pi_inv = 1.0 / M_PI

    for i in range(n):
        item = active[i]
        idx = <int> item[0]
        base_ang = <double> item[1]
        band_idx = <int> item[2]
        omr22 = <double> item[3]
        hue_base = <double> item[4]

        a = base_ang + ang_off + seg
        ang = fmod(a, seg2)
        if ang < 0.0:
            ang += seg2
        ang -= seg
        if ang < 0.0:
            ang = -ang

        # The spoke ridge needs |sin(theta)| < 0.2 for lane>0, i.e. theta within
        # asin(0.2)=0.20135792 of a multiple of pi. Range-reduce to that distance
        # |d| and reject the ~87% of off-spoke pixels BEFORE paying for a sin
        # (sin was the overlay's dominant per-pixel cost). On a spoke,
        # |sin(theta)| == sin(|d|) exactly, so the kept pixels are unchanged.
        ridge = omr22 - phase + ang * sym26
        q = ridge * ridge_pi_inv
        whole = <long>(q + 0.5) if q >= 0.0 else <long>(q - 0.5)
        ridge = ridge - M_PI * whole
        if ridge < 0.0:
            ridge = -ridge
        if ridge >= 0.20135792079033079:
            continue
        ridge2 = ridge * ridge
        lane = 1.0 - (ridge * (1.0 - ridge2 / 6.0)) * 5.0

        twist = 0.5 + 0.5 * cos(ang * sym2 + f03)
        val = lane * lane * lane * (0.20 + <double> bars[band_idx] * 0.90) * (0.35 + twist * 0.80)
        if val <= 0.06:
            continue
        if val > inten[idx]:
            inten[idx] = val
            hue[idx] = <unsigned char> fmod(hue_base + ang * pi_inv + f09, 101.0)


def kaleido_overlay_geom_buf(
    float[::1] inten,
    unsigned char[::1] hue,
    unsigned int[::1] idx_arr,
    float[::1] base_ang_arr,
    unsigned int[::1] band_idx_arr,
    float[::1] omr22_arr,
    float[::1] hue_base_arr,
    object bars,
    double phase,
    int symmetry,
    double ang_off,
    double f03,
    double f09,
):
    """Overlay kaleido spokes using packed geometry arrays."""
    cdef Py_ssize_t i, n = idx_arr.shape[0]
    cdef int idx, band_idx
    cdef long whole
    cdef double base_ang, omr22, hue_base, a, ang, ridge, q, ridge2, lane, twist, val
    cdef double seg = M_PI / (symmetry if symmetry >= 1 else 1)
    cdef double seg2 = seg * 2.0
    cdef double sym26 = symmetry * 2.6
    cdef double sym2 = symmetry * 2.0
    cdef double pi_inv = 18.0 / M_PI
    cdef double ridge_pi_inv = 1.0 / M_PI

    if (
        base_ang_arr.shape[0] != n
        or band_idx_arr.shape[0] != n
        or omr22_arr.shape[0] != n
        or hue_base_arr.shape[0] != n
    ):
        raise ValueError("packed tunnel geometry arrays do not match")

    for i in range(n):
        idx = <int> idx_arr[i]
        base_ang = base_ang_arr[i]
        band_idx = <int> band_idx_arr[i]
        omr22 = omr22_arr[i]
        hue_base = hue_base_arr[i]

        a = base_ang + ang_off + seg
        ang = fmod(a, seg2)
        if ang < 0.0:
            ang += seg2
        ang -= seg
        if ang < 0.0:
            ang = -ang

        # The spoke ridge needs |sin(theta)| < 0.2 for lane>0, i.e. theta within
        # asin(0.2)=0.20135792 of a multiple of pi. Range-reduce to that distance
        # |d| and reject the ~87% of off-spoke pixels BEFORE paying for a sin
        # (sin was the overlay's dominant per-pixel cost). On a spoke,
        # |sin(theta)| == sin(|d|) exactly, so the kept pixels are unchanged.
        ridge = omr22 - phase + ang * sym26
        q = ridge * ridge_pi_inv
        whole = <long>(q + 0.5) if q >= 0.0 else <long>(q - 0.5)
        ridge = ridge - M_PI * whole
        if ridge < 0.0:
            ridge = -ridge
        if ridge >= 0.20135792079033079:
            continue
        ridge2 = ridge * ridge
        lane = 1.0 - (ridge * (1.0 - ridge2 / 6.0)) * 5.0

        twist = 0.5 + 0.5 * cos(ang * sym2 + f03)
        val = lane * lane * lane * (0.20 + <double> bars[band_idx] * 0.90) * (0.35 + twist * 0.80)
        if val <= 0.06:
            continue
        if val > inten[idx]:
            inten[idx] = val
            hue[idx] = <unsigned char> fmod(hue_base + ang * pi_inv + f09, 101.0)


def kaleido_overlay_geom_buf_typed(
    float[::1] inten,
    unsigned char[::1] hue,
    unsigned int[::1] idx_arr,
    float[::1] base_ang_arr,
    unsigned int[::1] band_idx_arr,
    float[::1] omr22_arr,
    float[::1] hue_base_arr,
    float[::1] bars,
    double phase,
    int symmetry,
    double ang_off,
    double f03,
    double f09,
):
    """Overlay kaleido spokes using packed geometry arrays and packed bar data."""
    cdef Py_ssize_t i, n = idx_arr.shape[0]
    cdef int idx, band_idx
    cdef long whole
    cdef double base_ang, omr22, hue_base, a, ang, ridge, q, ridge2, lane, twist, val
    cdef double seg = M_PI / (symmetry if symmetry >= 1 else 1)
    cdef double seg2 = seg * 2.0
    cdef double sym26 = symmetry * 2.6
    cdef double sym2 = symmetry * 2.0
    cdef double pi_inv = 18.0 / M_PI
    cdef double ridge_pi_inv = 1.0 / M_PI

    if (
        base_ang_arr.shape[0] != n
        or band_idx_arr.shape[0] != n
        or omr22_arr.shape[0] != n
        or hue_base_arr.shape[0] != n
    ):
        raise ValueError("packed tunnel geometry arrays do not match")

    for i in range(n):
        idx = <int> idx_arr[i]
        base_ang = base_ang_arr[i]
        band_idx = <int> band_idx_arr[i]
        omr22 = omr22_arr[i]
        hue_base = hue_base_arr[i]

        a = base_ang + ang_off + seg
        ang = fmod(a, seg2)
        if ang < 0.0:
            ang += seg2
        ang -= seg
        if ang < 0.0:
            ang = -ang

        # The spoke ridge needs |sin(theta)| < 0.2 for lane>0, i.e. theta within
        # asin(0.2)=0.20135792 of a multiple of pi. Range-reduce to that distance
        # |d| and reject the ~87% of off-spoke pixels BEFORE paying for a sin
        # (sin was the overlay's dominant per-pixel cost). On a spoke,
        # |sin(theta)| == sin(|d|) exactly, so the kept pixels are unchanged.
        ridge = omr22 - phase + ang * sym26
        q = ridge * ridge_pi_inv
        whole = <long>(q + 0.5) if q >= 0.0 else <long>(q - 0.5)
        ridge = ridge - M_PI * whole
        if ridge < 0.0:
            ridge = -ridge
        if ridge >= 0.20135792079033079:
            continue
        ridge2 = ridge * ridge
        lane = 1.0 - (ridge * (1.0 - ridge2 / 6.0)) * 5.0

        twist = 0.5 + 0.5 * cos(ang * sym2 + f03)
        val = lane * lane * lane * (0.20 + <double> bars[band_idx] * 0.90) * (0.35 + twist * 0.80)
        if val <= 0.06:
            continue
        if val > inten[idx]:
            inten[idx] = val
            hue[idx] = <unsigned char> fmod(hue_base + ang * pi_inv + f09, 101.0)


def kaleido_overlay_geom_buf_typed_flat(
    float[::1] inten,
    unsigned char[::1] hue,
    unsigned int[::1] idx_arr,
    float[::1] base_ang_arr,
    unsigned int[::1] band_idx_arr,
    float[::1] omr22_arr,
    float[::1] hue_base_arr,
    float[::1] bars,
    double phase,
    int symmetry,
    double ang_off,
    double f09,
):
    """Lower-cost large-grid tunnel overlay without the twist cosine."""
    cdef Py_ssize_t i, n = idx_arr.shape[0]
    cdef int idx, band_idx
    cdef long whole
    cdef double base_ang, omr22, hue_base, a, ang, ridge, q, ridge2, lane, val
    cdef double seg = M_PI / (symmetry if symmetry >= 1 else 1)
    cdef double seg2 = seg * 2.0
    cdef double sym26 = symmetry * 2.6
    cdef double pi_inv = 18.0 / M_PI
    cdef double ridge_pi_inv = 1.0 / M_PI

    if (
        base_ang_arr.shape[0] != n
        or band_idx_arr.shape[0] != n
        or omr22_arr.shape[0] != n
        or hue_base_arr.shape[0] != n
    ):
        raise ValueError("packed tunnel geometry arrays do not match")

    for i in range(n):
        idx = <int> idx_arr[i]
        base_ang = base_ang_arr[i]
        band_idx = <int> band_idx_arr[i]
        omr22 = omr22_arr[i]
        hue_base = hue_base_arr[i]

        a = base_ang + ang_off + seg
        ang = fmod(a, seg2)
        if ang < 0.0:
            ang += seg2
        ang -= seg
        if ang < 0.0:
            ang = -ang

        ridge = omr22 - phase + ang * sym26
        q = ridge * ridge_pi_inv
        whole = <long>(q + 0.5) if q >= 0.0 else <long>(q - 0.5)
        ridge = ridge - M_PI * whole
        if ridge < 0.0:
            ridge = -ridge
        if ridge >= 0.20135792079033079:
            continue
        ridge2 = ridge * ridge
        lane = 1.0 - (ridge * (1.0 - ridge2 / 6.0)) * 5.0

        val = lane * lane * lane * (0.20 + <double> bars[band_idx] * 0.90) * 0.75
        if val <= 0.06:
            continue
        if val > inten[idx]:
            inten[idx] = val
            hue[idx] = <unsigned char> fmod(hue_base + ang * pi_inv + f09, 101.0)


def kaleido_overlay_geom_buf_typed_flat_folded(
    float[::1] inten,
    unsigned char[::1] hue,
    unsigned int[::1] idx_arr,
    float[::1] folded_ang_arr,
    unsigned int[::1] band_idx_arr,
    float[::1] omr22_arr,
    float[::1] hue_base_arr,
    float[::1] bars,
    double phase,
    int symmetry,
    double ang_off_mod,
    double f09,
):
    """Large-grid flat overlay using symmetry-folded base angles.

    ``folded_ang_arr`` stores ``(base_ang + seg) % (seg*2)`` for the current
    symmetry, so the per-pixel angle fold avoids fmod().
    """
    cdef Py_ssize_t i, n = idx_arr.shape[0]
    cdef int idx, band_idx
    cdef long whole
    cdef double omr22, hue_base, a, ang, ridge, q, ridge2, lane, val
    cdef double seg = M_PI / (symmetry if symmetry >= 1 else 1)
    cdef double seg2 = seg * 2.0
    cdef double sym26 = symmetry * 2.6
    cdef double pi_inv = 18.0 / M_PI
    cdef double ridge_pi_inv = 1.0 / M_PI

    if (
        folded_ang_arr.shape[0] != n
        or band_idx_arr.shape[0] != n
        or omr22_arr.shape[0] != n
        or hue_base_arr.shape[0] != n
    ):
        raise ValueError("packed tunnel geometry arrays do not match")

    for i in range(n):
        idx = <int> idx_arr[i]
        band_idx = <int> band_idx_arr[i]
        omr22 = omr22_arr[i]
        hue_base = hue_base_arr[i]

        a = folded_ang_arr[i] + ang_off_mod
        if a >= seg2:
            a -= seg2
        ang = a - seg
        if ang < 0.0:
            ang = -ang

        ridge = omr22 - phase + ang * sym26
        q = ridge * ridge_pi_inv
        whole = <long>(q + 0.5) if q >= 0.0 else <long>(q - 0.5)
        ridge = ridge - M_PI * whole
        if ridge < 0.0:
            ridge = -ridge
        if ridge >= 0.20135792079033079:
            continue
        ridge2 = ridge * ridge
        lane = 1.0 - (ridge * (1.0 - ridge2 / 6.0)) * 5.0

        val = lane * lane * lane * (0.20 + <double> bars[band_idx] * 0.90) * 0.75
        if val <= 0.06:
            continue
        if val > inten[idx]:
            inten[idx] = val
            hue[idx] = <unsigned char> fmod(hue_base + ang * pi_inv + f09, 101.0)



def braille_field(list inten, list hue, int dot_rows, int dot_cols,
                  int height, int width,
                  object esc=None, object esc_bold=None,
                  bint use_color=True, double threshold=0.05,
                  double hot_threshold=0.7, str reset="\x1b[0m"):
    """Render the braille dot field using the same contract as visualizer.py."""
    cdef list lines_out = [None] * height
    cdef list row_str
    cdef tuple chars = _BRAILLE_CHAR_LUT
    cdef bint colored = use_color and esc is not None and esc_bold is not None
    cdef int row, col, base_col, idx, k
    cdef int row0, row1, row2, row3
    cdef int bits, best_hue
    cdef double best, v
    cdef object prefix, active_prefix

    for row in range(height):
        row_str = []
        row0 = row * 4 * dot_cols
        row1 = row0 + dot_cols
        row2 = row1 + dot_cols
        row3 = row2 + dot_cols
        active_prefix = None
        for col in range(width):
            bits = 0
            best = threshold
            best_hue = 50
            base_col = col * 2

            idx = row0 + base_col
            v = <double> inten[idx]
            if v > threshold:
                bits |= 0x01
                if v > best:
                    best = v
                    best_hue = <int> hue[idx]
            v = <double> inten[idx + 1]
            if v > threshold:
                bits |= 0x08
                if v > best:
                    best = v
                    best_hue = <int> hue[idx + 1]

            idx = row1 + base_col
            v = <double> inten[idx]
            if v > threshold:
                bits |= 0x02
                if v > best:
                    best = v
                    best_hue = <int> hue[idx]
            v = <double> inten[idx + 1]
            if v > threshold:
                bits |= 0x10
                if v > best:
                    best = v
                    best_hue = <int> hue[idx + 1]

            idx = row2 + base_col
            v = <double> inten[idx]
            if v > threshold:
                bits |= 0x04
                if v > best:
                    best = v
                    best_hue = <int> hue[idx]
            v = <double> inten[idx + 1]
            if v > threshold:
                bits |= 0x20
                if v > best:
                    best = v
                    best_hue = <int> hue[idx + 1]

            idx = row3 + base_col
            v = <double> inten[idx]
            if v > threshold:
                bits |= 0x40
                if v > best:
                    best = v
                    best_hue = <int> hue[idx]
            v = <double> inten[idx + 1]
            if v > threshold:
                bits |= 0x80
                if v > best:
                    best = v
                    best_hue = <int> hue[idx + 1]

            if bits == 0:
                if active_prefix is not None:
                    row_str.append(reset)
                    active_prefix = None
                row_str.append(" ")
            elif colored:
                k = best_hue
                if k < 0:
                    k = 0
                elif k > 100:
                    k = 100
                prefix = esc_bold[k] if best > hot_threshold else esc[k]
                if prefix != active_prefix:
                    row_str.append(prefix)
                    active_prefix = prefix
                row_str.append(chars[bits])
            else:
                if active_prefix is not None:
                    row_str.append(reset)
                    active_prefix = None
                row_str.append(chars[bits])
        if active_prefix is not None:
            row_str.append(reset)
        lines_out[row] = "".join(row_str)
    return lines_out


def braille_field_buf(float[::1] inten, unsigned char[::1] hue, int dot_rows, int dot_cols,
                      int height, int width,
                      object esc=None, object esc_bold=None,
                      bint use_color=True, double threshold=0.05,
                      double hot_threshold=0.7, str reset="\x1b[0m",
                      int field_v_dots=4):
    """Render the braille dot field from packed numeric buffers.

    ``field_v_dots`` is how many vertical dot-rows the FIELD actually has per
    character cell (4 = full braille; 2 = half-resolution field; 1 = one field
    row per terminal row). Lower values cut upstream feedback/overlay work at
    large sizes, at the cost of vertical blockiness.
    """
    cdef list lines_out = [None] * height
    cdef list row_str
    cdef tuple chars = _BRAILLE_CHAR_LUT
    cdef bint colored = use_color and esc is not None and esc_bold is not None
    cdef int row, col, base_col, idx, k
    cdef int row0, row1, row2, row3
    cdef int bits, best_hue
    cdef double best, v
    cdef object prefix, active_prefix

    for row in range(height):
        row_str = []
        if field_v_dots >= 4:
            row0 = row * 4 * dot_cols
            row1 = row0 + dot_cols
            row2 = row1 + dot_cols
            row3 = row2 + dot_cols
        elif field_v_dots <= 1:
            row0 = row * dot_cols
            row1 = row0
            row2 = row0
            row3 = row0
        else:
            # Half-res field: 2 field rows per char, each feeding 2 braille dots.
            row0 = row * 2 * dot_cols
            row1 = row0
            row2 = row0 + dot_cols
            row3 = row2
        active_prefix = None
        for col in range(width):
            bits = 0
            best = threshold
            best_hue = 50
            base_col = col * 2

            if field_v_dots >= 4:
                idx = row0 + base_col
                v = inten[idx]
                if v > threshold:
                    bits |= 0x01
                    if v > best:
                        best = v
                        best_hue = hue[idx]
                v = inten[idx + 1]
                if v > threshold:
                    bits |= 0x08
                    if v > best:
                        best = v
                        best_hue = hue[idx + 1]

                idx = row1 + base_col
                v = inten[idx]
                if v > threshold:
                    bits |= 0x02
                    if v > best:
                        best = v
                        best_hue = hue[idx]
                v = inten[idx + 1]
                if v > threshold:
                    bits |= 0x10
                    if v > best:
                        best = v
                        best_hue = hue[idx + 1]

                idx = row2 + base_col
                v = inten[idx]
                if v > threshold:
                    bits |= 0x04
                    if v > best:
                        best = v
                        best_hue = hue[idx]
                v = inten[idx + 1]
                if v > threshold:
                    bits |= 0x20
                    if v > best:
                        best = v
                        best_hue = hue[idx + 1]

                idx = row3 + base_col
                v = inten[idx]
                if v > threshold:
                    bits |= 0x40
                    if v > best:
                        best = v
                        best_hue = hue[idx]
                v = inten[idx + 1]
                if v > threshold:
                    bits |= 0x80
                    if v > best:
                        best = v
                        best_hue = hue[idx + 1]
            elif field_v_dots <= 1:
                # Ultra-low-res: one field row per terminal row. Each field dot
                # feeds all four vertical braille dots in its column.
                idx = row0 + base_col
                v = inten[idx]
                if v > threshold:
                    bits |= 0x47          # 0x01 | 0x02 | 0x04 | 0x40
                    if v > best:
                        best = v
                        best_hue = hue[idx]
                v = inten[idx + 1]
                if v > threshold:
                    bits |= 0xB8          # 0x08 | 0x10 | 0x20 | 0x80
                    if v > best:
                        best = v
                        best_hue = hue[idx + 1]
            else:
                # Low-res: row0==row1 and row2==row3, so each field cell feeds a
                # vertical pair of braille dots. Read each cell ONCE and OR the
                # paired bits — bit-identical to the 8-read path, half the reads.
                idx = row0 + base_col
                v = inten[idx]
                if v > threshold:
                    bits |= 0x03          # 0x01 | 0x02
                    if v > best:
                        best = v
                        best_hue = hue[idx]
                v = inten[idx + 1]
                if v > threshold:
                    bits |= 0x18          # 0x08 | 0x10
                    if v > best:
                        best = v
                        best_hue = hue[idx + 1]

                idx = row2 + base_col
                v = inten[idx]
                if v > threshold:
                    bits |= 0x44          # 0x04 | 0x40
                    if v > best:
                        best = v
                        best_hue = hue[idx]
                v = inten[idx + 1]
                if v > threshold:
                    bits |= 0xA0          # 0x20 | 0x80
                    if v > best:
                        best = v
                        best_hue = hue[idx + 1]

            if bits == 0:
                if active_prefix is not None:
                    row_str.append(reset)
                    active_prefix = None
                row_str.append(" ")
            elif colored:
                k = best_hue
                if k < 0:
                    k = 0
                elif k > 100:
                    k = 100
                prefix = esc_bold[k] if best > hot_threshold else esc[k]
                if prefix != active_prefix:
                    row_str.append(prefix)
                    active_prefix = prefix
                row_str.append(chars[bits])
            else:
                if active_prefix is not None:
                    row_str.append(reset)
                    active_prefix = None
                row_str.append(chars[bits])
        if active_prefix is not None:
            row_str.append(reset)
        lines_out[row] = "".join(row_str)
    return lines_out


def flash_disc_buf(
    float[::1] inten,
    unsigned char[::1] hue,
    int dot_cols,
    int min_x,
    int max_x,
    int min_y,
    int max_y,
    double cx,
    double cy,
    double radius,
    double gain,
    unsigned char hue_value,
    double x_div,
    double y_mul,
):
    """Add a brightest-wins flash disc into packed feedback buffers."""
    cdef int x, y, idx
    cdef double inv_r = 1.0 / (radius if radius > 0.001 else 0.001)
    cdef double dx, dy, dist, v

    for y in range(min_y, max_y + 1):
        dy = (y - cy) * y_mul
        for x in range(min_x, max_x + 1):
            dx = (x - cx) / x_div
            dist = sqrt(dx * dx + dy * dy)
            if dist > radius:
                continue
            v = gain * (1.0 - dist * inv_r)
            idx = y * dot_cols + x
            if v > inten[idx]:
                inten[idx] = v
                hue[idx] = hue_value


def plasma_field_buf(
    float[::1] inten,
    unsigned char[::1] hue,
    int dot_rows,
    int dot_cols,
    double phase,
    double frame,
    double pulse,
    double contrast_att,
    double bass_att,
    double overall,
):
    """Render the plasma bloom field into packed feedback buffers in place."""
    cdef double cx = (dot_cols - 1) / 2.0
    cdef double cy = (dot_rows - 1) / 2.0
    cdef double inv_cx = 1.0 / (cx if cx > 1.0 else 1.0)
    cdef double inv_cy = 1.0 / (cy if cy > 1.0 else 1.0)
    cdef double phase15 = phase * 1.5
    cdef double phase11 = phase * 1.1
    cdef double phase07 = phase * 0.7
    cdef double phase05 = phase * 0.5
    cdef double petal_freq = 3.2 + contrast_att * 2.2
    cdef double bloom_scale = 1.02 + bass_att * 0.32
    cdef double overall_scale = 0.24 + overall * 0.96
    cdef double ring_center = 0.16 + pulse * 0.26
    cdef double hue_time = frame * 0.7
    cdef int x, y, idx
    cdef double nx, ny, r, swirl, petals, bloom, val, ring, hue_v

    for y in range(dot_rows):
        ny = (y - cy) * inv_cy
        for x in range(dot_cols):
            nx = (x - cx) * inv_cx
            r = sqrt((nx * 1.05) * (nx * 1.05) + (ny * 1.20) * (ny * 1.20))
            if r > 1.35:
                continue
            swirl = (
                sin(nx * 6.4 + phase15)
                + sin(ny * 5.2 - phase11)
                + sin((nx + ny) * 4.1 + phase07)
            ) / 3.0
            petals = 0.5 + 0.5 * cos(atan2(ny, nx) * petal_freq - phase05)
            bloom = 1.0 - r * bloom_scale
            if bloom < 0.0:
                bloom = 0.0
            val = swirl * 0.5 + 0.24
            if val < 0.0:
                val = 0.0
            val *= pow(bloom, 1.9) * (0.30 + petals * 0.80) * overall_scale
            ring = 0.20 - fabs(r - ring_center)
            if ring < 0.0:
                ring = 0.0
            val += ring * pulse * 1.7
            if val <= 0.05:
                continue
            idx = y * dot_cols + x
            if val > inten[idx]:
                inten[idx] = val
                hue_v = fmod(44.0 + swirl * 18.0 + petals * 20.0 + hue_time - r * 28.0, 101.0)
                if hue_v < 0.0:
                    hue_v += 101.0
                hue[idx] = <unsigned char> hue_v
