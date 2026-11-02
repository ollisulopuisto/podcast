# Sentinel journal

## 2026-11-01 - cut-list speaker labels escaped (autoraffkat)

- Found: `renderCuts()` interpolated speaker/shot labels into `innerHTML`
  unescaped. Labels are typed by the user, but the same field can arrive in a
  shared project file, so the label must render as text, not markup.
- Repro: `tests/ui_escape.js` drives `renderCuts()` in a fake browser with a
  tag-and-attribute-breaking label and failed on the raw interpolation.
- Fix: `esc()` helper in `app.js`, applied to both label interpolations in
  `renderCuts()`. Translation strings stay unescaped on purpose - they are
  static.
- Verified: new regression test red before, green after; full UI test files
  (test_ui, test_escape, test_history, test_shortcuts) pass; ruff clean.
  test_video.py failures are a pre-existing sandbox ffmpeg limitation,
  identical on unmodified main.
