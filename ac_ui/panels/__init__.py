"""Panel renderers package.

Each panel is a pure renderer: given state, return (plain_lines, color_lines).
Panels have no side effects and do not read from terminal or audio.

Implemented:
  now_playing  — track name, progress bar, filter/vis/vol, pick reason (panels/now_playing.py)
  history      — recently played track list (panels/history.py)
  up_next      — next-candidates queue (panels/up_next.py)
  stats        — session listen time + hour histogram (panels/stats.py)
  help         — key binding overlay (panels/help.py)
"""
