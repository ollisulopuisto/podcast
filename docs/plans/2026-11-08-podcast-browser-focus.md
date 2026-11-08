# Podcast Magic file-browser focus repair, PR 196

Opening the browser focuses Close. Folder navigation now focuses the first
child folder, then the first session file if there are no child folders.
An empty folder focuses its parent entry, or Close at the filesystem root.
The file browser stays nonmodal (`aria-modal="false"`): Tab may leave it.
This is focus management, not a focus trap. Escape still closes it and returns
focus to Change.

The existing UI smoke test now tracks focus and covers initial opening,
repeated folder activation, file-only folders, empty folders, an empty root,
and return focus. Before the implementation it failed with Close focused
instead of the child folder.

Validation:

- Podcast Magic suite: 375 passed, 1 macOS-only CFBundleName test skipped.
- UI tests: 12 passed, including the Node behavior smoke test.
- Full-repository Ruff: passes.
- Workspace contract suite: 244 passed, 1 failed because zsh is unavailable
  locally (PermissionError when trying to execute it), 12 subtests passed.
- Real Chrome with mocked API state, 1280 x 820: Ctrl+O focuses Close;
  Tab/Enter navigates twice without dismissal; the folder outline is visible;
  Tab leaves the nonmodal browser; Escape closes it and restores focus.
  Initial and navigation screenshots inspected. No page errors.
- No native macOS file-picker or audio-pipeline validation in this change.

No version, dependency, lockfile, workflow or changelog changes. No merge,
release or build dispatch.
