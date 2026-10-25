# Contextual Controls: Floating Toolbar, Context Menus, Palette

**Status (2026-10-25):** design only. Nothing here is built. The mockups under
`docs/plans/assets/` are static pages, and nothing in them is wired.

**The owner's question:** "Would a Photoshop style floating toolbar be a good
idea? What about contextual menus, eg if you highlight something first and then
the relevant options pop up?" The apps target power users and keyboard
shortcuts, and "we DEFINITELY need a way to surface these features in the GUI so
that people can discover them". Scope: autoraffkat first, the other apps second.

**Builds on:** the shortcut registry being built on
`feat/autoraffkat-shortcut-help`: one table in `static/app.js` that generates
the keydown handler, the `<kbd>` hints, the tooltips and a `?` cheat sheet. The
branch was not on `origin` when this was written, so the section "What this
needs from the registry" states the contract this design depends on, not what
that branch contains.

## Decision

1. **No floating tool palette, in any of these apps.** A Photoshop tool palette
   switches between *tools*: modes that change what the pointer does on a
   canvas. None of these apps has tools. They have commands on objects, plus one
   transient mode (autoraffkat's lifted card). A palette of commands that floats
   over a 960 × 600 window covers the cards it acts on, needs a mouse to move it
   out of the way, and adds nothing the header does not already show.
2. **autoraffkat gets two contextual surfaces and one discovery layer, in this
   order:**
   1. **Keyboard carry with a carry bar.** The card is the app's only
      selection, and today the keyboard can lift one but not put it down. Lift
      with Enter, place with a digit, cancel with Esc. While a card is carried,
      the Tracks panel's own heading row shows those keys and every slot shows
      its digit. This is the selection-anchored contextual toolbar, but docked
      into an existing row rather than floating.
   2. **A context menu on track cards**, opened by right-click, Shift+F10, the
      Menu key and a visible `⋯` button. Every item comes from the registry and
      shows its key.
   3. **A command palette (⌘K)** that finds commands *and settings*, after the
      registry and the menu have landed.
3. **Not for autoraffkat:** a floating toolbar near the selection, a menu bar,
   context menus on the preview bar or the cut list (nothing there can be
   selected), and hover-only controls.
4. **podcast-magic:** nothing beyond key hints and a cheat sheet. It has
   nothing to select.
5. **automixer:** Textual's Footer already *is* a contextual toolbar (it shows
   the focused widget's bindings), and Ctrl+P already opens a palette that
   lists none of the app's own commands. Register them there, and bind the
   Speech/Music marking to the file list.
6. **kuulas (separate repository; a recommendation only):** it already has the
   registry, menu bar, palette, context menus and status-bar hints. Make the
   status-bar hints follow the *selection kind*, not only the panel, instead of
   adding a floating selection bar over the waveform. Check two suspected
   keyboard bugs in its context menu (see "Kuulas" below).

The rule that holds all of it together: **one registry, and every surface is a
view of it.** Nothing appears in a menu, bar or palette without its key, and
nothing has a key that cannot be found in the cheat sheet and the palette. Both
halves are tests, not intentions (see "The tests that make it true").

## What the code says: selection and actions per app

### autoraffkat

Read from `server/static/app.js`, `index.html`, `style.css` and
`server/CLAUDE.md` on `origin/main` at `8ec4914`.

**What can be selected today.** One thing: a track card, held in `picked`
(app.js:276). A click or `dragstart` lifts it, and a click on a slot or a
`drop` places it (`dropTarget`, app.js:767). `picked` is a single key. There is
no multiple selection, no time range, no selected shot and no selected cut-list
row.

| Surface | Selectable? | What the user can do there |
| --- | --- | --- |
| Track card (`trackCard`) | yes, one at a time (`picked`) | lift and place into a slot (sets role and speaker in `assign`); mic sliders; group-shot "Also in the shot" chips; seat-order chips and their reset; relink when a file is missing |
| Slot strip | no (it is a text field) | rename the speaker (`renameCovers`) |
| Preview bar (`#bar`, a canvas) | no | wheel zooms, drag pans when zoomed, double-click resets (`bindZoom`). No click, no keyboard, no range |
| Cut list (`#cut-table`) | no | read only |
| Rail panels (rhythm, overlap, audio rows) | no | radios, sliders, disclosure rows (`settingRow`), per-section reset |
| Header | n/a | Open (⌘O), Reload, Relink (only when files are missing), Process audio, Render video, Stop, Export (⌘E), FI/EN |

**Tools or commands?** Commands. No control changes what the pointer does on a
canvas. The one moded state is "a card is in your hand", and it is transient
(it ends when the card lands). That settles the floating-toolbar question.

**What the selection actually offers.** A lifted card can go to: the shared
row (the wide for video, room tone for audio), any speaker row, a group-shot
row, a new speaker row, a new group-shot row (video only), or the Unassigned
tray. `accepts()` (app.js:403) restricts it by kind. That is the whole set of
"actions that apply to the selection". Everything in the header and the rail
applies to the whole project.

**Surprises, all in the selection model:**

- **The keyboard can lift a card but cannot put it down.** The card's
  `keydown` handles Enter and Space by calling `pickUp(media)` only
  (app.js:632–636). The slot cells and the tray are `div`s with a `click`
  listener and no `tabIndex` (`dropTarget`, `slotCell`, `renderTray`), so they
  cannot be focused. Enter on a second card *re-lifts* that card instead of
  placing the first one, because `pickUp` toggles `picked` (app.js:494–497).
  The comment above `picked` says the same path serves "the mouse and the
  keyboard", and `server/CLAUDE.md` says so too, but for placing it does not.
  I read this; I did not drive it in a browser.
- **There is no way to cancel a lift except clicking the same card again.**
  There is no Escape anywhere in app.js. The global `keydown` (app.js:3319)
  knows only ⌘E and ⌘O.
- **The tray hint is the app's only description of the selection model:**
  "Drag a card into a slot — or click a card, then a slot"
  (`patch.hint`). It sits under the patch bay and says nothing about keys.
- **Finnish gives two different controls the same name.** The Ducking row
  (`audio.duckRow`) and its depth slider (`audio.duckDb`) are both
  "Vaimennus". Any surface that lists controls by label (a palette, a cheat
  sheet of settings) shows two identical entries. The palette mockup had to
  work around this by hand.

### podcast-magic

`server/static/index.html` and `app.js` plus five `mod_*.js` modules: a left
rail with the session and the tool tabs, and one form per tool with one Run
button. There is no `keydown` listener anywhere and nothing selectable. The
only object is the session file. There are no tools and no selection; the
commands are "switch tab" and "Run".

### automixer (Textual TUI)

`src/automixer/app.py`: five `TabPane`s, `BINDINGS` for q, ctrl+s, r, f12 and
space, and a `Footer`. It contains the one real select-then-act pattern in this
repository: a `SelectionList` of audio files, then the "🎤 Speech" / "🎵 Music"
buttons apply a role to the files that are ticked (`on_button_pressed`,
app.py:416). Those two buttons have no key.

Read in the installed Textual 8.2.8 (the version in `uv.lock`), not run:

- `App.ENABLE_COMMAND_PALETTE` defaults to `True` on `ctrl+p`, so automixer
  already has a palette. Its default commands are Textual's own (Theme, Quit,
  Keys, …). `get_system_commands` is the hook for adding the app's.
- `Screen.active_bindings` walks from the focused widget outwards and the first
  binding for a key wins. `SelectionList` binds Space to "select" with
  `show=False`. So while the file list has focus, Space ticks a file and the
  Footer correctly stops advertising "Play/Stop Preview". The Footer is already
  focus-contextual.

### kuulas (read-only clone, `/home/user/ollisulopuisto/kuulas`)

A timeline editor with real selections: clips, an in/out range, transcript
words and a current track. Already in place, per `docs/KEYS.md` (generated),
`docs/PLAN.md` WP5 and WP48, `ROADMAP.md` and `docs/BUGS.md`: a command
registry with per-context keymaps, a ⌘K palette, ⇧⌘K command search that shows
where a command is in the menus, a `?` cheat sheet, F1 help, an in-window menu
bar (pywebview's native menus could not show enabled state or keys; owner,
2026-10-18), right-click menus on clips, ranges, lanes, the ruler and the
track/bus headers (`ui/context-menu.js`, `ui/timeline-menu.js`), and status-bar
key hints (`ui/hints.js`, at most three). The owner has ruled that "ALL OPTIONS
have to be found from the menus" and that every menu item shows its key, and a
`menu-coverage` test enforces the first. kuulas also has the only real *tool* in
any of these apps: the preference "Mouse: dragging paints a range / moves
clips" (BUGS #45).

## The six options, judged against that code

| Option | autoraffkat | podcast-magic | automixer | kuulas (rec.) |
| --- | --- | --- | --- | --- |
| (a) Floating tool palette | **No** | No | Impossible in a TUI | No |
| (b) Contextual bar near the selection | **Docked, not floating:** the carry bar | No (nothing to select) | The Footer already is one | **Docked:** selection-aware status hints |
| (c) Context menu | **Yes, on cards** | No | No (no pointer menus; the palette covers it) | Exists; fix keyboard opening |
| (d) Command palette | **Yes, phase 3, with settings** | No | **Yes, it exists:** register commands | Exists |
| (e) Menu bar / grouped header | No; the header is the command bar | No | No | Exists |
| (f) Cheat sheet only | Not enough: it cannot place a card | **Yes** | Footer + palette | n/a |

### (a) Floating tool palette: no

- **There is nothing for it to hold.** Photoshop's Tools panel holds dozens of
  modes for one canvas. autoraffkat's actions are seven header commands, a lift
  and a place. A palette of commands is a second copy of the header, floating.
- **Screen space.** pywebview opens autoraffkat at 1280 × 820 with
  `min_size` 960 × 600 (`gui.py`). At 960 the rail already drops below the
  tracks (`style.css`: one column under 1000 px), and the header is a single
  row of six to eight buttons. A floating panel takes room from the patch bay,
  the one area the user is working in.
- **Focus and keyboard.** A floating panel is either one more tab stop the
  keyboard user walks through, or it is skipped and serves only the mouse. The
  WAI-ARIA toolbar pattern gives a toolbar "one stop" with arrow keys inside,
  which works, but it still means the user moves focus *away from the card* to
  act on it. The menu and the carry keys act from the card.
- **pywebview.** The page cannot float a panel outside its own window. A real
  utility window would be a second pywebview window with its own DOM and state,
  which is a second app.
- **Accessibility.** A movable overlay has no stable place in the reading
  order, and dragging it is mouse-only unless move keys are added for it too.

### (b) Selection-anchored contextual toolbar: yes as a docked bar, not a floating one

Photoshop's Contextual Task Bar, Figma and Google Docs float a bar next to the
selection. Adobe documents that its bar can be dragged, pinned, reset and
hidden (Photoshop Elements help, which describes the same bar). That set of
controls exists because the floating bar covers what you are editing. In
autoraffkat the "selection" is a card in transit, and what it would cover are
the slots it is about to land in. So the bar goes into a row that already
exists, the Tracks panel heading (`h2` "Tracks", left; carry keys, right), and
the slot digits go onto the slots themselves. It stays sticky under the header
while a card is carried, because at 600 px the tray is below the fold (seen in
the mockup; see "Mockups").

### (c) Context menu: yes, on cards, opened every way

NN/g's ten guidelines (read): use them for secondary actions, put the trigger
near its object, keep the icon visible "without hover", group only actions of
that object, and make them keyboard and screen-reader accessible. Guideline 8
says not to use one for one or two actions. A card has between five and twelve,
so it qualifies.

Apple's HIG (read): "Always make context menu items available in the main
interface, too", "Aim for a small number of menu items", about three groups at
most, "Hide unavailable menu items, don't dim them", submenus at most one
level, and **"Show keyboard shortcuts in your app's main menus, not in context
menus"**. This design breaks that last rule on purpose. Apple's reason is that
the menu bar already teaches the keys. autoraffkat has no menu bar and the
owner's goal is to teach the keys, so the context menu is where they are
taught. kuulas made the same call (owner, 2026-10-18).

WAI-ARIA APG, Menu and Menubar Pattern (read): focus goes to the first item on
open, Up/Down move, Enter activates and closes, Escape closes "and return[s]
focus to the element or context" that opened it, Tab closes, Home/End are
optional, and type-ahead is optional ("Move focus to the next item … whose
label begins with that printable character"). Disabled items may take focus
but not activate.

MDN on `contextmenu` (read): it fires on right-click "or by pressing the
context menu key". Shift+F10 is not mentioned, and macOS keyboards have no
Menu key, so Shift+F10 must be bound in the registry and not left to the
browser.

### (d) Command palette: yes, but third, and for settings as much as commands

autoraffkat has about eight header commands, too few to need searching. What
it has many of is **settings**: the audio panel showed 26 sliders before they
were put one disclosure away (`server/CLAUDE.md`), and `app.js` has 15
`settingRow` call sites (disclosure rows in the Cut and Audio panels) and 26
slider specs in its `*_KNOBS` tables. "Where is the ducking depth?" is the question a palette answers, by
opening the row and focusing the slider. That is the reason to build it, and
it is also why it waits for the registry: it needs settings described as data,
which the registry does not contain yet.

### (e) Menu bar: no

The header already is autoraffkat's command bar, ordered by the workflow from
left to right (open, reload, process, render, export). A menu bar would add a
row to a 600 px window to show the same eight commands. kuulas needed one
because it has over a hundred commands (`docs/KEYS.md`). Apple's toolbar
guidance ("Make every toolbar item available as a command in the menu bar")
assumes a native menu bar. pywebview's native menus cannot show enabled state
or the current key (kuulas found this), so the registry-driven palette and
cheat sheet stand in for it.

### (f) Cheat sheet only: not enough for autoraffkat, enough for podcast-magic

The cheat sheet lists keys. It cannot fix the missing keyboard path for placing
a card, and it does not answer "what can I do with *this*?" For podcast-magic,
with no selection and a handful of commands, it is the right amount.

## What to build in autoraffkat

### 1. Keyboard carry and the carry bar

**Appears** when a card is lifted (Enter or Space on a focused card, a click on
a card, `dragstart`, or the menu's "Pick up" item). **Disappears** when the card
lands, on Esc, or when the card is clicked again (as now).

**Contents, in the Tracks heading row:** "Moving STATUS CAM 4", then
`1–3 slot`, `N new speaker`, `G group shot`, `0 unassigned`, `Esc cancel`. It is
generated from the registry's carry-scope commands, with the range collapsed
when the digits are consecutive. Each slot that accepts the card shows its
digit as a badge, numbered top to bottom in the same order as `buildSlots()`:
shared row, speakers in palette order, group shots. Cells that do not accept
the card's kind get no digit, exactly as `applyPicked` already leaves them
without `.is-target`.

**Why digits, and why up to nine:** `SPEAKER_COLORS` has 5 entries and
`GROUP_COLORS` 3 (app.js:8–10), so a fully distinct board is 1 shared + 5
speakers + 3 group shots = 9 rows, exactly 1–9. Beyond five speakers the
colours repeat (`colorFor` wraps), and rows past the ninth get no digit; they
are still reachable with the mouse and from the menu with the arrow keys.
`N`, `G` and `0` are fixed, so they never move as rows are added.

**Keyboard story:** Tab to a card, Enter lifts, a digit places, Esc cancels.
Focus stays on the placed card in its new slot, so the next Tab continues from
where the user is. That needs `renderTracks` to restore focus by `data-track`,
because it rebuilds the whole board. Single keys are inactive while a text
field (the speaker names, the mic name) has focus.

**Several things selected:** cannot happen; `picked` is one key. **Nothing
selected:** no bar, and the heading row looks as it does today.

**Translated:** every label is a `T()` key in both languages in the same
commit. The digits are not translated. Finnish label lengths were checked in
the mockup at 960 px and fit on one line.

**Never:** shift the layout (it uses the existing heading row), cover a slot,
or take focus away from the card.

### 2. Card context menu

**Appears** on right-click on a card, Shift+F10 or the Menu key with the card
focused, or a click on the card's `⋯` button. **Disappears** on Esc (focus
returns to the card), Tab (closes; focus moves on), a pick, a click outside, a
window blur or a resize. One menu at a time.

**Contents (for the card it was opened on):**

1. Caption: "Move STATUS CAM 1 to".
2. Destinations as `menuitemradio`, with the current one checked. The digit is
   the same as in carry mode, so the two surfaces teach one numbering. A
   destination that replaces something says so ("Wide, replaces STATUS CAM 2",
   because `assign` sends the old wide to Unassigned). Destinations the card
   cannot take are not listed (Apple: hide, don't dim).
3. Card commands, only when they apply: "Pick up and place with the keyboard"
   (↵), "Relink files…" when the file is missing, "Use the measured order" when
   the seat order is manual. All three already exist on the card or in the
   header; the menu never holds the only path to anything.

**Maximum 12 items.** In the mockup an item is about 32 px high, and the
960 × 600 window holds about 15 after the 16 px margins and the caption. Twelve
keeps the menu from scrolling and leaves some of the board visible. With
digit-numbered destinations capped at nine, plus N/G/0, plus up to three card
commands, the cap is reached only on a board with more than five speakers.

**Keyboard story:** the APG menu pattern: focus on the first item, Up/Down,
Home/End, Enter activates and closes, Esc closes and returns focus to the card.
Type-ahead is replaced by the digit and letter accelerators: speaker names
often share a first letter, and the digits are already the keys the user should
learn. The `⋯` button has `tabIndex = -1`, so the tab order through the board
does not double. The keyboard opens the menu from the card itself.

**Key hints:** every item shows its key, right-aligned, in the same chip as
`<kbd>`. A context-menu item without a key fails a test (below).

**Translated:** labels come from the registry's `T()` keys. Speaker names are
data and are not translated.

**Never:** appear on hover; hide a command that exists nowhere else; cover the
card it was opened on (it opens beside the `⋯` and slides up only as far as it
must, never flipping above the card. In the mockup, flipping covered the header
and the speaker's name at 960 × 600); steal focus without returning it.

### 3. Command palette (⌘K), after 1 and 2

**Contents:** every registry command (with its key, or with no key and "palette
only") and every setting, shown with where it lives ("Audio › Ducking") and its
current value. Choosing a setting opens its disclosure row and focuses the
control; it never changes the value by itself. Results are grouped Settings
and Commands, and matching also uses the `why.*` text, so "bleed" finds
de-bleeding.

**Keyboard:** ⌘K opens, typing filters, Up/Down move, Enter runs or opens, Esc
closes and returns focus. It is a modal dialog with a combobox and a listbox.

**Never:** be the only place a command lives; reorder results while the user
is pressing arrows.

**Prerequisite found while mocking it up:** every setting needs a label that
is unique in both languages. Finnish `audio.duckRow` and `audio.duckDb` are
both "Vaimennus".

## What this needs from the registry

The other branch defines the registry. This design needs these fields per
command. Where that branch names them differently, this list is the contract,
not the names.

```text
id          stable string, e.g. "card.place", "app.export"
labelKey    T() key, present in both languages
keys        zero or more combos, as the cheat sheet shows them
scope       "global" | "card" | "carry"   (which surface may show it)
when(state) whether it applies now        (hide, don't dim, in context menus)
run(state, arg)
targets(state, card) -> [{ arg, labelKey|label, key }]
            for parameterised commands: card.place lists its slots with their
            digits, so the menu and the carry bar read one list
```

Settings for the palette are a separate table generated from the existing
`*_KNOBS` and `settingRow` specs (`{ key, labelKey, where, value(state),
reveal() }`). They are not commands and need no keys.

## The tests that make it true

All of these run in `tests/test_ui.py` / `tests/ui_smoke.js`, which already
load `app.js` and `i18n.js` in a stub DOM in both languages.

1. **Every item has a key and a translation.** Build the card menu for every
   card in the smoke state (video, audio, group, wide, missing file, manual
   seats) in `fi` and `en`. Assert that each item has a non-empty key and that
   its `labelKey` exists in both catalogues. The existing
   `test_every_visible_string_is_translated_in_both_languages` only sees
   literal `T('…')` calls, so registry `labelKey` strings need the same check.
2. **Nothing has a key without being discoverable.** For each registry entry
   with a key: it is in the cheat sheet data and in the palette list.
3. **Menu and carry agree.** For each card, `targets()` gives the same arg→key
   pairs to the menu and to the badges.
4. **The keyboard can place a card** (red today). Fire Enter on a card, then
   the digit `2` on the window, and assert the card's `config.role` and
   `config.speaker` changed as `assign` would set them. This fails on
   `origin/main` because nothing handles the digit, and also because no
   focusable element accepts a drop.
5. **Esc cancels a lift** (red today): `picked` is null after Esc and the card
   stays where it was.
6. **Labels are unique per language**, among the palette's settings (red today:
   `Vaimennus` twice).
7. **Coverage stays total.** The smoke test already fails on any top-level
   function that is never called (`NEVER_CALLED_OK`). The new menu and palette
   functions are called by firing their handlers, not excused.

## Phased plan

Each phase is one PR and is shippable on its own.

| Phase | What ships | The test that proves it |
| --- | --- | --- |
| 0 | (other branch) the registry, `<kbd>` hints, `?` cheat sheet | that branch's own tests |
| 1 | Keyboard carry: Esc cancels, digits/N/G/0 place, focus returns to the placed card, slot badges, carry bar in the Tracks heading (sticky while carrying) | tests 4 and 5, red first; 3 for the badges; smoke in both languages |
| 2 | Card context menu: right-click, Shift+F10, Menu key, `⋯`; APG keys; focus return | tests 1 and 3; a smoke check that Esc returns focus to the card |
| 3 | Unique labels (`audio.duckDb` gets its own Finnish name), then the settings table | test 6 red first |
| 4 | Command palette with commands and settings | test 2; opening a setting from the palette expands its row (smoke) |
| A | automixer: register app actions in `get_system_commands`; bind Speech/Music on the file list | a Textual `run_test` pilot: Ctrl+P lists every `BINDINGS` action and every `Button` id has a command; the key marks ticked files |
| P | podcast-magic: keys on tabs and Run, `?` sheet, only if the shared registry shape fits without a second copy | its `tests/ui_smoke.js` |

What not to build, at any phase: a floating palette, a hover toolbar, a menu
bar, a context menu on the preview canvas or the cut list, or a way to switch
any of this off. With nothing floating, there is nothing that needs pinning.

## Mockups

`docs/plans/assets/contextual-controls-mockup.html` links autoraffkat's real
`style.css` by relative path, so the tokens (`--bg`, `--panel`, `--line`,
`--accent`, `--sp0…`), the header, panels, slots, cards and disclosure rows are
the shipping ones. Only the menu, carry bar and palette are new CSS, built from
the same tokens. `apps/autoraffkat/DESIGN.md` has no visual tokens; they live
in `style.css`'s `:root`. The app is dark only (no `prefers-color-scheme` in
`style.css`), so there is no light version. `?lang=en|fi&state=menu|carry|palette`
picks the view. `render-contextual-mockups.js` re-renders the six PNGs with the
preinstalled Chromium and fails if the page makes any non-file request (it
made none). The thumbnails are blank on purpose, and the key ⇧⌘M on "Process
audio" is a placeholder: only ⌘O and ⌘E exist today, and the registry branch
decides the rest.

**Nothing in these pictures is wired.**

### Context menu on a card

![Card context menu, English, 1280 × 820](assets/contextual-menu-en-1280.png)

![Card context menu, Finnish, 960 × 600](assets/contextual-menu-fi-960.png)

### Carrying a card with the keyboard

![Carry bar and slot digits, English, 1280 × 820](assets/contextual-carry-en-1280.png)

![Carry bar sticky while the lifted card is at the bottom, Finnish, 960 × 600](assets/contextual-carry-fi-960.png)

### Command palette

![Palette finding the ducking settings, English, 1280 × 820](assets/contextual-palette-en-1280.png)

![Palette, Finnish, 960 × 600](assets/contextual-palette-fi-960.png)

### What I looked at, and what changed because of it

I opened every PNG and read it. Changes made after looking:

- **Finnish menu at 960 × 600:** the first version flipped the menu above the
  card when it did not fit below. It then covered the header buttons and the
  "Nyman" strip, the row the menu is about. It now slides up only as far as it
  must. It still overlapped the strip until I removed a footer line ("Also:
  right-click · Shift+F10 · ⋯") that the `⋯` tooltip and the cheat sheet carry
  anyway. In the final image the menu starts below the strip.
- **Carry at 960 × 600:** with the lifted card in the tray, the card is below
  the fold, and the carry bar in the panel heading scrolled away with the page.
  The bar is now sticky under the header while carrying. In the final image it
  sits under the header with the card in view at the bottom. The slot "1" badge
  shows through the header's fade, as content does in the real app.
- **Palette:** the key chip "⇧⌘M" was hard to read at 11.5 px; it is 12.5 px
  now. The Finnish depth value was an invented 0.3 s; it is the real default,
  0.60 s (`speechmix.masks.DUCK_MIN_CLOSED`). −9 dB and 6 dB are `DUCK_DB` and
  `DUCK_DOMINANCE_DB`.
- **Fidelity:** in carry mode every cell that accepts the card is outlined as
  `.is-target`, as `applyPicked` does, not just the empty rows.

What I did not check: real fonts on macOS (Chromium on Linux rendered the
`-apple-system` stack with its fallback), Retina rendering, pywebview's WebKit
(the screenshots are Chromium), and screen readers. The pictures are only a
claim about layout, wording and fit at the two window sizes.

## Other apps

### automixer

The Footer is the TUI's contextual toolbar and already follows focus. What is
missing is that the app's own commands are not in the palette and the two
marking buttons have no key. Add `get_system_commands` yielding one
`SystemCommand` per `BINDINGS` action and per button action (Scan for ad break,
Render preview, Render final mix, Open plugin window, Mark as speech, Mark as
music). Bind marking on the `SelectionList` itself, so the Footer shows those
keys only when the file list has focus. Which letters to use is the owner's
call: `s` and `m` read well, and q, r and space are taken at app level.

### podcast-magic

Key hints on the tool tabs and on each Run button, and a `?` sheet. No menus.
If the autoraffkat registry ends up small and generic, it can be copied here
deliberately. Otherwise this app does not need one.

### Kuulas (recommendation; separate repository, not edited)

- **Docked selection hints instead of a floating bar.** `STATUS_HINTS` in
  `ui/keymap-default.js` is keyed by panel and capped at three
  (`ui/hints.js`, `MAX_HINTS`). With clips or a range selected in the
  timeline, the first three that apply are play, view and split, not the
  cut/delete/copy keys a selection invites. Keying the list by selection kind
  (nothing, clips, range, words, candidate) gives kuulas Photoshop's contextual
  task bar without covering the waveform.
- **Suspected: the keyboard-opened timeline menu ignores the selection.**
  `showTimelineMenu` detects a keyboard opening by `clientX === 0 &&
  clientY === 0`, and `timeline.js`'s `contextmenu` handler has already passed
  `hitAt(event)` with those coordinates. The menu is therefore built for
  whatever is under the canvas's top-left corner, and for a lane or ruler hit
  `contextPress` sets `seek` to that frame. I read this and did not run it.
- **Suspected: no Shift+F10 on macOS, and no focus return.** Nothing in
  `ui/` binds F10 (searched), and macOS keyboards have no Menu key. `close()`
  in `ui/context-menu.js` removes the menu without refocusing the opener.
- **Two menu rules disagree.** BUGS #42 says the right-click menu lists only
  what is possible for the target. `context-menu-model.js` (the header menus)
  keeps disabled items with `aria-disabled`. Apple says hide in context menus.
  Pick one.

## What is not known

| Unknown | Why it matters | Cheapest way to find out |
| --- | --- | --- |
| Does the owner place cards by mouse or keyboard? | If always drag, phase 1's value is the keys it teaches, not the path it adds | Ask; or count, for one week, `pickUp` calls from `click`/`dragstart` vs `keydown` in the terminal log (a debug-only line, removed after) |
| Is the right-click menu found at all in a pywebview window on macOS? | WKWebView must deliver `contextmenu` to the page and not show its own menu; not tested here | Five minutes on the owner's Mac with phase 2's branch: right-click, Ctrl+click, two-finger click |
| Is Shift+F10 free in pywebview/WKWebView on macOS? | It may be swallowed before the page sees it | Same session, with a `keydown` logger |
| How many speakers do real episodes have? | Above five, slots lose distinct colours and digits past nine | Count roles in the owner's existing `*.autoraffkat.json` files (they sit beside every episode) |
| Will anyone open the palette for settings rather than commands? | Phase 4's whole argument | Ship phase 4 with "recent" stored per user; look at the list after a month of episodes |
| Touch (an iPad browser on the local server)? | Long-press would be the context-menu trigger, and the carry bar is already touch-safe | Ask whether autoraffkat is ever opened on a tablet; if not, ignore it |
| The letters for automixer's marking keys | Owner's taste; `s` and `m` are only a suggestion | Ask |

## Sources read for this document

- Nielsen Norman Group, "Designing Effective Contextual Menus: 10 Guidelines",
  <https://www.nngroup.com/articles/contextual-menus-guidelines/>
- W3C WAI-ARIA Authoring Practices, Menu and Menubar Pattern,
  <https://www.w3.org/WAI/ARIA/apg/patterns/menubar/>, and Toolbar Pattern,
  <https://www.w3.org/WAI/ARIA/apg/patterns/toolbar/>
- Apple Human Interface Guidelines, Context menus and Toolbars, read through
  the JSON behind
  <https://developer.apple.com/design/human-interface-guidelines/context-menus>
  and <https://developer.apple.com/design/human-interface-guidelines/toolbars>
  (the HTML pages render with JavaScript)
- MDN, `Element: contextmenu event`,
  <https://developer.mozilla.org/en-US/docs/Web/API/Element/contextmenu_event>
- Adobe, Photoshop Elements help, Contextual Task Bar,
  <https://helpx.adobe.com/lt/photoshop-elements/desktop/workspace-and-environment/contextual-task-bar.html>
  (Photoshop's own help page returned 403; read through a search summary, not
  the full page)
- Textual 8.2.8 source as installed: `app.py` (`ENABLE_COMMAND_PALETTE`,
  `get_system_commands`), `screen.py` (`active_bindings`),
  `widgets/_selection_list.py`
