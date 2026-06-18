# cython: language_level=3, boundscheck=False, wraparound=False, cdivision=True
"""Compiled hot path for the feedback-tunnel visualizers (kaleido / liquid /
plasma).  This mirrors the pure-Python ``_feedback_transform`` in visualizer.py
exactly; visualizer.py imports and uses it when built, and falls back to the
pure-Python version when this module isn't compiled.  Build with::

    .venv/bin/python build_native.py        # or: cythonize -i ac_ui/_vizfast.pyx
"""
from libc.math cimport sin, cos, atan2, sqrt, fmod, M_PI
from libc.stdlib cimport malloc, free


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
                    out_inten[row_out + x] = v
                    out_hue[row_out + x] = fmod(src_hue[src_idx] + hue_shift, 101.0)
    finally:
        free(si)

    return out_inten, out_hue
