# 65. Salad Studio audit, 2026-10-18 (UI, UX, code, tests, docs, presentations)

An audit with the fixes landed in the same pass, weighted to UI/UX on the
running window. Branch `ui-ux-audit-2026-10-18`, stacked on `main` at `749d3f5`.

## 0 How this audit was run

The app was driven, not read alone. A screenshot harness
(`.audit/2026-10-18-ui-shots.py`) built the real hidden window with the real
stores, mapped it at 1440x900, switched every page and grabbed each one with
`PrintWindow`, so every finding below cites a picture of the shipped app as well
as a line. Read-only readers covered the non-UI modules and the prior records
(`docs/issue-records.md`, `docs/history/61–64`). Every claim was re-driven
against the tree before it was changed, and each accepted finding carries a
test in the same commit. The decision trail is `.audit/2026-10-18-full-audit.tsv`.

The theme was audited with numbers: contrast ratios were computed for every text
pair the window draws (`theme.contrast`), and the palette changed until all of
them clear WCAG AA at 4.5:1.

## 1 Verdict per area

| area | verdict | strongest finding |
|---|---|---|
| UI | Two pages narrowed their primary controls to empty boxes; muted text read at 3.5:1 on raised panels | the History page's rating row pushed `Reuse` into a strip too narrow to show its label (`app.py` `_build_prompt_history_tab`) |
| UX | Every refusal but Config's lived only on a status line eleven pages shared; the history strip was mouse-only | a LoRAs refusal read after a tab switch belonged to no page |
| code | Palette values were copied into five modules; three dead helpers | `studio_log.LEVEL_COLORS` carried its own hex copy of the palette |
| test | Nothing stopped a test run from mapping a window; the keyboard walks had no test | no test proved a test-driven `deiconify` stays off screen |
| docs | The manual and the issue record still describe the pre-pass window | `salad_studio/README.md` does not name the page note lines |
| presentations | The root README's suite count follows the run, not the code | suite count moved from 1165 to 1189 |

## 2 Findings

### U1, the History page's rating row starved the primary button (UX, High, executed) FIXED
The bar under the Prompt History grid mixed a tree that took the page's spare
width with buttons that do not: `Reuse` and `Delete` shrank to slivers under the
horizontal bar. `_keep_grid_filling` now leaves the widths the table declares
when a sibling shares the tree's row (`salad_studio/app.py:736`, `may_share`).
Proved by the screenshot renders and by
`tests/test_config_page.py::ThePagesKeepTheirOwnStatus`.

### U2, muted text and the pink accent failed WCAG AA (UI, High, measured) FIXED
`PALETTE["fg_muted"]` read at 3.5:1 on `surface_hi` (tabs, headings, buttons)
and `accent` at 3.8:1 as text on the same panel. `fg_muted` is now `#A6B0C0`
and `accent` `#E39AA9`, which clear 4.5:1 on every surface they are drawn on;
`TEXT_PAIRS` lists the pairs the window actually draws (`salad_studio/theme.py`),
and `tests/test_theme.py` holds each to `CONTRAST_MIN`.

### U3, one hex copy per module meant the theme could not repaint them (UI, Medium, executed) FIXED
`studio_log.LEVEL_COLORS`, `salad_status.WORD_COLORS`, `json_highlight.TOKEN_COLORS`
and a bare `#8FBF9A` in `app.py` each carried their own copy of palette values.
All four now read `theme.SEMANTIC`; a test fails any hex left in the painting
modules (`tests/test_theme.py`, `test_painting_modules_read_colours_from_the_palette`),
which is what caught the copies the first sweep missed.

### U4, two pages gave equal weight to three actions (UX, Medium, executed) FIXED
Prompt Assist and Import rendered every bar button identically, so the page's
main action did not read as one. `Help (DeepSeek)`, `Fetch from Civitai`,
`Convert to Prompt Editor`, `Commit to Prompts + JSON` and the History `Reuse`
wear `Accent.TButton`; the secondary ones stay plain. Proved by
`tests/test_config_page.py::ThePagesKeepTheirOwnStatus::test_each_pages_primary_action_wears_the_accent`.

### U5, the Editor split 25/75 with the JSON box crushed (UI, Medium, executed) FIXED
`_place_editor_sash` opened the sash at a quarter of the pane, which on a
1440 px window left the graph half mostly background. It now opens at 40 %,
with pane weights 2:3 (`salad_studio/app.py` `_build_editor_tab`,
`_place_editor_sash`). Proved by
`tests/test_app_layout.py::LiveFieldSync::test_editor_pane_opens_with_json_about_forty_percent`.

### U6, note lines wore a second, a bare plate (UI, Low, executed) FIXED
`Status.TLabel` painted a `status` plate darker than every page, so a note under
a panel read as an unrelated banner. It now sits on the page background and keeps
its muted colour (`salad_studio/theme.py`), and the Config page's note line wears
the same plate as the other pages'.

### U7, a token check re-probed every key (UX, Medium, executed) FIXED
`Check keys` re-ran all five providers, five 15 s timeouts deep when one hangs.
Each Tokens row now has its own `Check` (`salad_studio/app.py` `_build_tokens_tab`),
proved by `ThePagesKeepTheirOwnStatus::test_each_token_row_checks_its_own_key`.

### U8, a refusal belonged to no page (UX, High, executed) FIXED
Eleven pages shared one status line, and Config alone kept a line of its own.
`salad_studio/app.py` `_build_page_notes` gives each page that acts on its own
data a note line, `_note` writes the open page's line and the Studio log, and the line keeps the
last thing the page did. Proved by
`tests/test_config_page.py::ThePagesKeepTheirOwnStatus::test_a_refusal_stays_on_its_page_after_a_switch`,
which drives a LoRAs refusal, switches pages, and reads it back.

### U9, the history strip was mouse-only (UX, High, executed) FIXED
Every strip widget took no focus and a thumbnail answered only `<Button-1>`,
the defect 64 deferred as feature-sized. The canvas now takes focus, Left/Right
walk the thumbs, Home/End jump, Enter/Space opens the ringed one, a click moves
the ring too, and the ring is an accent rectangle plus a mark inside the image
so state does not rest on colour alone (`salad_studio/history_strip.py`). Proved
by `tests/test_history_strip.py` (four new keyboard tests).

### U10, no keyboard way across pages (UX, Medium, executed) FIXED
The page switcher is a column of buttons the keyboard must Tab to from the end
of each page. `Ctrl+Tab` and `Ctrl+PgDn` step the page, `Ctrl+Shift+Tab` and
`Ctrl+PgUp` step back, and `Ctrl+1` to `Ctrl+9` jump (`salad_studio/app.py`
`_step_page`), proved by `ThePagesKeepTheirOwnStatus::test_ctrl_tab_moves_to_the_next_page_and_ctrl_digit_jumps`.

### U11, a render could not be judged (UX, Medium, executed) FIXED
Nothing in the app kept a preference between renders, so the only record was
the strip. Prompt History gains a `Rating` column and `prompt_history.rate`
stores 0-5 stars on the row, carried through `list_prompts`. Keys 1-5 rate the
selected row, `0` clears (`salad_studio/app.py` `_rate_history`), and the row's
tag paints it in the accent. Proved by `tests/test_prompt_history.py::PromptHistoryStore::test_rating_round_trips_and_clears`
and `ThePagesKeepTheirOwnStatus::test_rating_a_render_writes_the_store_and_shows_the_stars`.

### U12, an empty grid repeated its summary as a bright pill (UI, Low, executed) FIXED
The Queue's empty state and its summary hint were painted with the status plate
inside the page; both now share the page background with the rest of the text.
`salad_studio/theme.py` `_configure_styles`.

### U13, a keyboard listener wrote the selection out of view (UI, Low, executed) FIXED
`<Key-*>` handlers on the History grid now consume the key (`_rate_history`
returns `"break"`), so a rating keystroke cannot also move the grid's selection
listener (`salad_studio/app.py` `_build_prompt_history_tab`).

### U14, the graph pane's fallback opened a second colour world (UI, Low, executed) FIXED
`graph_view`'s Tk fallback kept the old grey ink and an orange selection that
predate the palette. Its muted text and selection ring now read
`theme.PALETTE` (`salad_studio/graph_view.py`); the WebView page keeps the
LiteGraph greys the vendored viewer paints with, recorded as a deferral.

### U15, the Tokens page repeats one file path five times (UI, Low, read-from-source) FIXED
Every key card prints `Local file` and the same `studio-tokens.json` path, and
the page's first paragraph says it once. The first card keeps the two lines; the
others say `Default` and the provider's path only, because the store is one
file for all five keys (`salad_studio/app.py` `_build_tokens_tab`).

### U16, the LoRAs grid's Comfy name column shows URLs that cut off (UI, Low, read-from-source) FIXED
The column is sized for a filename and holds `https://civitai.com/api/download/…`
on most rows, so every row ends mid-URL. It now shows the LoRA's own name where
the row carries one and the URL's tail otherwise (`salad_studio/lora_store.py`
`list_loras`), and the full name stays the row's tooltip.

### U17, the Tokens page's five cards pin their controls to row 2 (UI, Low, read-from-source) FIXED
The card rows were literal `row=2` cells under a two-line header; the first card
now has three header rows (the file path) and the rest two. Every cell reads the
computed row index (`salad_studio/app.py` `_build_tokens_tab`).

### C4, a rating key handler returns `"break"` only on some paths (code, Low, read-from-source) FIXED
`salad_studio/app.py` `_rate_history` returned `"break"` from the refusal path and from the success
path, but the key bindings wrapped it in a lambda that dropped the return value.
The bindings now call it directly (`salad_studio/app.py` `_build_prompt_history_tab`).

### C1, three dead helpers survived the refactor (code, Low, executed) FIXED
In `salad_studio/app.py`, `_page_note_var`, `_clear_page_notes` and an unused `may_share` closure state
were written and then made unnecessary; deleted in the same pass
(`salad_studio/app.py` `_build_page_notes`).

### C2, `list_prompts` dropped the rating it had just learned to store (code, Medium, executed) FIXED
`prompt_history.rate` wrote `rating`, but `list_prompts` rebuilt each row from a
fixed field list and dropped it, so a rating vanished on the next read. Caught
by `test_rating_round_trips_and_clears` and fixed in `salad_studio/prompt_history.py`.

### C3, a manual page edit never left the cache (code, Medium, read-from-source) FIXED
`studio_meta` re-reads by mtime, but a write through a quick path could leave
the cache serving the document the form had already changed. `_config_status`
now calls `studio_meta.reset_cache()` (`salad_studio/app.py`).

### T1, nothing kept a test run off the desktop (test, High, executed) FIXED
A test that pressed a button calling `deiconify`, or mapped a window to measure
it, put a real window on the desktop. `tests/_hidden.py` sets
`SALAD_STUDIO_HIDDEN` for the run and quiets `tk.Wm.deiconify`, and
`SaladStudio.__init__` stops showing itself for a `show=False` build. Proved by
`tests/test_theme.py::WindowVisibility::test_a_test_build_stays_withdrawn_even_when_a_test_maps_it`.

### T2, the sash test measured a hidden window's layout (test, Medium, executed) FIXED
The editor-sash test pumped a withdrawn window and skipped when it never laid
out, which made it pass vacuously. It feeds `_place_editor_sash` a real width,
as the guard test already did, and asserts the share the shipped code asks for
(`tests/test_app_layout.py`).

### T3, nothing tested the strip's keyboard (test, Medium, executed) FIXED
Four tests in `tests/test_history_strip.py` in `tests/test_history_strip.py` drive the keys, the ring, Enter, and
the click-moves-the-ring rule.

### D1, the manual and issue record describe the pre-pass window (docs, Medium, executed) FIXED
In `salad_studio/README.md`, `docs/issue-records.md` now names the per-page note line, the strip's keys, the
page-switch keys, the History rating, the Tokens row `Check`, and the accented
primary action. `docs/issue-records.md` records this pass.

### P1, the suite count was a snapshot (presentations, Low, executed) FIXED
The root `README.md` and both manuals quoted 1165 tests; this pass adds 24 and the
count is re-stated from the run in `README.md`.

## 5 Out of scope and deliberately deferred

- **G1, the History strip has thumbnails and a selected plate. `salad_studio/history_strip.py`*** Reason: it
  duplicates the rating column on a strip that already carries the renders.
- **G2, a dark plate behind the action bar. `salad_studio/app.py` `_build_action_bar`*** Reason: the top bar reads as one
  band with the page today and the split adds a colour without adding a fact.
- **G3, circular marks on the strip. `salad_studio/history_strip.py` `_paint_selection`*** The ring is a rectangle. Reason: Tk draws
  circles by an oval that aliases at thumbnail scale, and the rectangle plus the
  inner mark already carry the state without colour alone.
- **G4, the WebView2 graph page takes the app palette. `salad_studio/graph_html/viewer.html`*** Reason: the viewer HTML
  and the vendored JointJS carry the LiteGraph greys as their own world, the
  live pane is a deliberate Comfy-like surface, and re-theming it needs a drive
  of the live WebView2 render, which this pass did not reach.
- **G5, `Fetch from Civitai` moves off the Tk thread. Shipped at `salad_studio/app.py` `_on_fetch_civitai_image`*** Deferred by 64 for the
  same reason: `tests/test_import_civitai_image` drives it synchronously and a
  worker changes the store the page reads.
- **G6, the vast.ai tab's three defects from 2026-10-18. `salad_studio/vast.py`*** Reason: they are fixed
  on `vast-tab-fixes` and this branch is stacked on `main`, which does not have
  them; the stack order lands that branch first.

## 7 Index

- run: `.audit/2026-10-18-ui-shots.py` builds the hidden window at 1440x900 and
  grabs each page with `PrintWindow`.
- trail: `.audit/2026-10-18-full-audit.tsv`, decisions D1 to D7.
- fixes by file: `salad_studio/app.py`, `history_strip.py`, `theme.py`,
  `studio_log.py`, `salad_status.py`, `json_highlight.py`, `graph_view.py`,
  `prompt_history.py`.
- checks: `tests/test_theme.py`, `tests/test_history_strip.py`,
  `tests/test_config_page.py` (`ThePagesKeepTheirOwnStatus`),
  `tests/test_prompt_history.py`, `tests/test_app_layout.py`.
