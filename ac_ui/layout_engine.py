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

def resolve_panel_max_width(term_cols, layout_preset):
    """Compute the max inner width for sidebar panels given terminal/preset."""
    if term_cols >= 120:
        return max(30, min(48, (term_cols - 60) // 2))
    if layout_preset == "two_rail":
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

    chosen_sidebar = list(sorted_sidebar)
    info_target_w = None

    while chosen_sidebar:
        # All sidebar panels stack into one column of width = sidebar_outer_w
        sidebar_h = max(h for _n, h in chosen_sidebar)
        # inner width available for the info box
        max_info_inner = term_cols - _GAP - sidebar_outer_w - 4
        if max_info_inner >= min_info_inner and sidebar_h <= avail_rows:
            if max_info_inner < info_natural_w:
                info_target_w = max_info_inner
            break
        # Drop the lowest-priority panel (last after sort)
        chosen_sidebar.pop()

    return LayoutPlan(
        sidebar=[n for n, _h in chosen_sidebar],
        below=[n for n, _h in below_candidates],
        info_target_w=info_target_w,
        panel_max_w=panel_max_w,
    )
