"""Tests for jump-to-item navigation (jump.py)."""
from ac_ui.jump import next_match_index


LABELS = ["Apple", "banana", "Cherry", "apricot", "  date", "9 lives"]


def test_jumps_to_first_match_after_current():
    # From index 0 (Apple), 'a' should jump to the next 'a' item (apricot=3).
    assert next_match_index(LABELS, 0, "a") == 3


def test_wraps_around_and_cycles():
    # From apricot (3), 'a' wraps back to Apple (0).
    assert next_match_index(LABELS, 3, "a") == 0


def test_case_insensitive():
    assert next_match_index(LABELS, 0, "C") == 2
    assert next_match_index(LABELS, 0, "c") == 2


def test_ignores_leading_punctuation_and_space():
    # "  date" -> first alnum is 'd'.
    assert next_match_index(LABELS, 0, "d") == 4


def test_matches_digits():
    assert next_match_index(LABELS, 0, "9") == 5


def test_no_match_keeps_current():
    assert next_match_index(LABELS, 2, "z") == 2


def test_degenerate_inputs():
    assert next_match_index([], 0, "a") == 0
    assert next_match_index(LABELS, 0, "") == 0
    assert next_match_index(LABELS, -1, "a") == 0  # current out of range -> search from start


def test_single_match_returns_itself_only_after_wrap():
    labels = ["xenon", "yak", "zebra"]
    # Only one 'y'; from itself it should stay (no other match).
    assert next_match_index(labels, 1, "y") == 1
    # From elsewhere it finds it.
    assert next_match_index(labels, 0, "y") == 1
