"""
Panel layout engine — constraint-based placement for ac-ui panels.

Separates the *decision* (which panels fit, at what size) from the
*rendering* (building the actual box lines).  The compositor in ui.py
calls resolve_layout() and uses the resulting LayoutPlan to drive
build_box / combine_render_columns.

Zones:
  sidebar — rendered alongside the info box as a vertical column
  below   — rendered below the info box (combined horizontally if they fit,
             stacked otherwise)

Priority: lower number = drop first when space is tight.
"""

from ac_ui.layout import box_outer_width


# --------------------------------------------------------------------------- #
# Panel specs                                                                  #
# --------------------------------------------------------------------------- #

class PanelSpec:
    __slots__ = ("name", "min_cols", "max_cols", "min_rows", "priority")

    def __init__(self, name, *, min_cols=14, max_cols=48, min_rows=3, priority=10):
        self.name = name
        self.min_cols = min_cols
        self.max_cols = max_cols
        self.min_rows = min_rows
        self.priority = priority


DEFAULT_SPECS = {
    "history": PanelSpec("history", min_cols=18, max_cols=48, min_rows=3, priority=20),
    "up_next": PanelSpec("up_next", min_cols=18, max_cols=48, min_rows=3, priority=10),
    "stats":   PanelSpec("stats",   min_cols=20, max_cols=80, min_rows=3, priority=30),
}


# --------------------------------------------------------------------------- #
# Layout plan                                                                  #
# --------------------------------------------------------------------------- #

class LayoutPlan:
    __slots__ = ("sidebar", "below", "info_target_w", "panel_max_w")

    def __init__(self, sidebar, below, info_target_w, panel_max_w):
        self.sidebar = sidebar          # list[str] — panel names, order preserved
        self.below = below              # list[str] — panel names, order preserved
        self.info_target_w = info_target_w  # int | None (None = use natural width)
        self.panel_max_w = panel_max_w  # int — max inner width for all sidebar panels


# --------------------------------------------------------------------------- #
# Public helpers                                                               #
# --------------------------------------------------------------------------- #

def below_panel_inner_width(term_cols, n_panels, rmargin=2, gap_w=3):
    """Inner width for each panel sharing the full-width 'below' row.

    Panels in the below slot should tile the whole row (btop-style) rather than
    sit at the narrow sidebar width.  Splits the available width across
    ``n_panels``, accounting for the right margin, inter-panel gaps, and each
    box's 4 cols of chrome.
    """
    n = max(1, int(n_panels))
    avail = term_cols - rmargin - gap_w * (n - 1) - 4 * n
    return max(12, avail // n)


def resolve_panel_max_width(term_cols, layout_preset):
    """Compute the max inner width for sidebar panels given terminal/preset."""
    if term_cols >= 120:
        return max(30, min(48, (term_cols - 60) // 2))
    # wide_graph stacks three panels in the rail like two_rail, so it wants the
    # same compact rail width (leave the main graph area as wide as possible).
    if layout_preset in ("two_rail", "wide_graph"):
        return max(18, min(28, max(18, (term_cols - 11) // 3)))
    return max(14, min(28, max(14, (term_cols - 11) // 2)))


def resolve_layout(
    term_cols,
    avail_rows,
    info_natural_w,
    sidebar_candidates,
    below_candidates,
    layout_preset="two_rail",
    panel_specs=None,
):
    """
    Decide panel placement given terminal constraints.

    Parameters
    ----------
    term_cols           : int  — terminal width
    avail_rows          : int  — rows available below header/vis/footer
    info_natural_w      : int  — info box natural inner width (unconstrained)
    sidebar_candidates  : list of (name, box_height)
                          panels eligible for the sidebar, in desired order
    below_candidates    : list of (name, box_height)
                          panels eligible for below zone, in desired order
    layout_preset       : str  — current layout preset name
    panel_specs         : dict[str, PanelSpec] | None

    Returns
    -------
    LayoutPlan
    """
    specs = panel_specs or DEFAULT_SPECS
    panel_max_w = resolve_panel_max_width(term_cols, layout_preset)
    sidebar_outer_w = box_outer_width(panel_max_w)

    # Minimum inner width to keep the info box usable when sidebar is present
    min_info_inner = 55 if term_cols >= 120 else 28

    # Sort sidebar candidates by descending priority (highest = keep first)
    sorted_sidebar = sorted(
        sidebar_candidates,
        key=lambda x: specs.get(x[0], PanelSpec(x[0])).priority,
        reverse=True,
    )

    # Gap between info box and sidebar column ("   " = 3 chars in combine_render_columns)
    _GAP = 3
    # Right safety margin: never write to the last 2 columns, matching the
    # visualizer box (bars_len+4 == term_cols-2).  This keeps the top row off the
    # screen edge so it can't get clipped/wrapped when the real width is short.
    _RMARGIN = 2

    chosen_sidebar = list(sorted_sidebar)
    info_target_w = None

    while chosen_sidebar:
        # All sidebar panels stack into one column of width = sidebar_outer_w
        sidebar_h = max(h for _n, h in chosen_sidebar)
        # inner width available for the info box
        max_info_inner = term_cols - _RMARGIN - _GAP - sidebar_outer_w - 4
        if max_info_inner >= min_info_inner and sidebar_h <= avail_rows:
            # Stretch the info box to consume the full row width to the left of
            # the sidebar, so the top row tiles edge-to-edge (btop-style) instead
            # of leaving a dead gap on wide terminals.
            info_target_w = max_info_inner
            break
        # Drop the lowest-priority panel (last after sort)
        chosen_sidebar.pop()

    # No sidebar fits: let the info box span the whole width (minus the margin)
    # instead of sitting narrow with empty space beside it.
    if not chosen_sidebar and info_target_w is None and info_natural_w:
        info_target_w = max(info_natural_w, term_cols - _RMARGIN - 4)

    return LayoutPlan(
        sidebar=[n for n, _h in chosen_sidebar],
        below=[n for n, _h in below_candidates],
        info_target_w=info_target_w,
        panel_max_w=panel_max_w,
    )
