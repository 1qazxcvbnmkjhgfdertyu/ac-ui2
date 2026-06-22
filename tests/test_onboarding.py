"""First-run Welcome overlay + guided Tour overlay."""
from ac_ui.overlay import TourOverlay, WelcomeOverlay
from ac_ui.tour import TOUR_GENERAL, build_tour_lines


def test_welcome_routes_to_wizards():
    for key, expect in (("i", "i"), ("X", "X"), ("G", "G")):
        ov = WelcomeOverlay()
        assert ov.handle(key) is True
        assert ov.result == expect
    ov = WelcomeOverlay()
    assert ov.handle("ESC") is True and ov.result is None
    # renders without error
    assert any("Welcome" in ln for ln in ov.build(80, 30))


def test_tour_pages_and_nav():
    ov = TourOverlay()
    assert len(ov.pages) >= 6
    # covers free play + playlists (the user-requested topics)
    titles = [t for t, _ in TOUR_GENERAL]
    assert any("Free play" in t for t in titles)
    assert any("playlist" in t.lower() for t in titles)

    # forward nav, can't go past the end without closing
    ov.idx = 0
    assert ov.handle("RIGHT") is False and ov.idx == 1
    assert ov.handle(" ") is False and ov.idx == 2
    ov.idx = len(ov.pages) - 1
    assert ov.handle(" ") is True          # space on last page closes
    # back nav clamps at 0
    ov.idx = 0
    ov.handle("LEFT")
    assert ov.idx == 0
    assert ov.handle("ESC") is True


def test_tour_renders_every_page():
    for i in range(len(TOUR_GENERAL)):
        box = build_tour_lines(TOUR_GENERAL, i, 64)
        assert box and all(isinstance(ln, str) for ln in box)
