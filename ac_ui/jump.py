"""Jump-to-item navigation helper (Section 3.1).

A small, pure primitive for "type the first letter to jump" navigation in list
UIs (the playlist picker, file browser, …).  Kept separate from the editors so
it can be unit-tested without a terminal.
"""
from __future__ import annotations


def _first_alnum(label: str) -> str:
    for ch in label:
        if ch.isalnum():
            return ch.lower()
    return ""


def next_match_index(labels: list[str], current: int, ch: str) -> int:
    """Return the index of the next label whose first alphanumeric char is ``ch``.

    Search starts *after* ``current`` and wraps around, so repeatedly pressing
    the same key cycles through every item starting with that letter.  Matching
    is case-insensitive and ignores leading punctuation/whitespace.  Returns
    ``current`` unchanged when nothing matches or inputs are degenerate.
    """
    if not labels or not ch:
        return current
    target = ch.lower()
    n = len(labels)
    start = current if 0 <= current < n else -1
    for step in range(1, n + 1):
        idx = (start + step) % n
        if _first_alnum(labels[idx]) == target:
            return idx
    return current
