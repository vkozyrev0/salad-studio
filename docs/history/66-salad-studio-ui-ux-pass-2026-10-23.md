# 66. Salad Studio UI/UX pass and the old frontend's removal, 2026-10-23

A design and usability pass over the Angular page, and the removal of the
Flet/Tk painting layer it replaced, on branch `ui-ux-pass-2026-10-23`, branched
from `main` at `1eaf640`. The page was driven, not read alone: Playwright
captured every page at 1440x900, 1024x800 and 720x900, with an empty strip and
with four plates in a temporary art tree, and measured each scroll container.
Type and the table treatment were A/B tested on the live page before the source
changed.

**Gate.** `npx ng build`, `node audit.cjs`, `npx ng test --watch=false`, and
`python -m unittest discover -s tests -p "test_*.py"` (1085 tests) all pass.
`ui/dist` is rebuilt and committed.

## Verdict

| area | before | after |
|---|---|---|
| Strip | an empty 121px contact sheet took a band from every page | collapses to one 51px line until a plate exists |
| Settings | knobs stacked one per row; Save fell below the fold | two-column knobs, a LoRA filter, a selected count, Save visible |
| LoRAs | Add and Save sat below the fold once plates existed; Source column ended 330px short of the table | actions in the section head; the table fills its width |
| Tokens | one Check re-probed all five keys, each 15s deep; colour was the only state | per-row Check, the state as a word, the server probes only the named kinds |
| Tables | pink bold headers with permanent filter icons | mono, uppercase, muted ledger headings; filter marks wait for hover |
| Type | 20-35 labels per page below 10px | no label below 10px; the display face is Palatino |
| Empty states | one sentence at the top of a void | a blank plate, a short title, and the line that fills it |
| Actions | every page mixed ghost, quiet and outlined near-actions | one rose fill per page or section |
| Legacy UI | Flet/Tk palette, role maps, ttk styles and a migration journal in the tree | removed; the Angular page owns every token |

## Findings

### 1. The empty strip spent a page's height on nothing (UI, High)
`app-history-strip` always rendered an 84px reel, its head and its arrows, so
the strip was 121px on every page even with zero plates. Pages lost about a
fifth of their usable height to a band that said "No plates yet". It now
renders one 41px line with a faint blank print, and only opens into the reel
when plates exist. Measured: the strip's grid row went from 121px to 51px, and
LoRAs, Import and Assist stopped needing a scroll for their primary action.

### 2. LoRAs hid its primary action below the fold (UX, High)
The Add / edit LoRA form ended with its actions, and the form was the last row
of a page that was already taller than the pane. With four plates present, Add,
Save edits, Verify and Remove were all off-screen at 1440x900. The actions now
sit in the form's section head, and the table row may shrink to 180px, so Add is
visible next to the heading it belongs to. The same pass made Source flexible,
so the table uses its full width instead of leaving 330px blank.

### 3. Verified read as an editable checkbox (UX, Medium)
The `verified` field is a boolean, so AG Grid drew a real checkbox. It looked
like a control, but clicking it selected the row; the action that changes the
value is Verify. The cell now draws `● yes` / `● no` in the valid/invalid
colour, so the value and the action are distinct again.

### 4. One key check stalled on all five providers (UX, High)
The Tokens page had one `Check keys` that probed every provider in sequence,
five 15 second timeouts deep when one hung, and there was no per-row way to ask
about the key in front of you. Each row now has its own Check. The controller's
`check_keys` reads an optional `kinds` list and probes only those; no list keeps
the old all-five behaviour for any other caller. The state also reads as a word
under the provider name, so the dot is no longer the only signal. Proved by
`tests/test_web_engine.py::EngineTest::test_a_check_naming_one_key_probes_only_that_key`,
which asserts one probe and that the other rows keep their state.

### 5. Table headers competed with the content (UI, Medium)
Every header was 13px semibold rose with a permanent funnel icon; a table of
five columns read as five pink menu bars. Headers are now 10px mono, uppercase
and muted, matching the page's eyebrows. A sort or hover lifts the label to the
foreground; the filter mark is at 30% until the header is hovered. The grid's
header weight, colour and padding live in `studioGridTheme` and the label
treatment in `data-grid.ts`.

### 6. The type floor was below the readable range (UI, Medium)
Pages carried 20-35 labels between 8.5px and 9.5px: replica meter names, the rail
footer, the strip captions, card stats, the history meta. All are 10px now, and
the keycap hint gets the same floor. The display face moved from Georgia to
Palatino (`'Palatino Linotype', 'Book Antiqua', Palatino, Georgia, serif`): the
book stress suits the printed-sheet metaphor, and Georgia remains the fallback.

### 7. Emptiness was an afterthought (UI, Medium)
Queue, History, Catalog and LoRAs drew one muted sentence at the top of a large
empty pane. They now share `.empty-sheet`: a faint blank plate, a short title in
the display face, and the server's line that says what fills it. The strip's
empty line uses the same blank print, so every empty surface reads as an
unexposed sheet rather than a missing panel.

### 8. Primary actions were not ranked (UX, Medium)
Config's Save profile was an outline while Settings' Save was filled; History's
Reuse was a ghost; Catalog's payoff, Load into Prompt Editor, was one of four
identical ghosts; the Editor's Validate was a ghost while Swap was filled. Each
page now has one rose fill: Save profile, Save environment, Apply to Salad, Save
list, Save keys, Save to profile, Add, Load into Prompt Editor, Reuse, Commit,
and Convert. History's Reuse, Catalog's Load and the Editor's Validate are the
actions their page exists for.

### 9. History and Catalog cut their graph summary mid-id (UI, Low)
A 48-character slice of `14 nodes · 1 LoRA (civitai:2795018@0.5) · 512×1024`
ended every row in `(civitai:27950…`. Both pages now drop the model ids from the
cell and keep the full line as the tooltip: `14 nodes · 1 LoRA · 512×1024`.
History's Plate header no longer takes a filter, so its label fits.

### 10. Import's Convert row was one scroll away (UX, Medium)
Two 8-row textareas and a 90px issues well pushed Fill / Convert / Clear below
the fold. The boxes are 4 and 6 rows and the well starts at 64px; the Convert
button is visible at 1440x900 with a full strip.

### 11. Logs' clear action floated away from its log (UI, Low)
`Clear Studio logs` sat on its own line below the Studio log, reading as a
footer for the page. It is now a small quiet button in the section head, on the
same line as the log's name.

### 12. The stylesheet carried the whole control layer twice (code, Medium)
`ui/src/styles.css` held the fields, buttons, segmented switch, sections, pick
lists and readouts twice, verbatim, with only the log styles added at the end.
The second copy was dead weight and a trap for the next edit. It is one copy.
The hard-coded rose fills for `.btn.key` and `.btn.danger` became `color-mix`
over `--accent` / `--invalid`, so a palette change reaches every button.

### 13. Narrow widths lost the status line (UX, Low)
At 720px the status bar's keyboard hint ran off the right edge and squeezed the
sentence it sat beside; the top bar also spent three rows on controls. Below
860px the hint hides, the replica meters share the bar's first row, and the
History prompt column ellipsizes on one line instead of wrapping inside a fixed
48px row. The strip's plate captions are now a render's clock time (or a dated
file's month-day) and clip with an ellipsis, so a long name cannot run into the
next plate.

### 14. The Flet/Tk frontend leftovers are gone (code, High)
The product is a Python HTTP server and an Angular page. The tree still carried
the painting layer of the two frontends it replaced: `salad_studio/theme.py`
(Flet material role maps, ttk style lookups, Tk font tuples, notebook tab
expansion), `MIGRATION.md` (the Tk-to-Flet journal), `LEVEL_COLORS` and
`level_color` in the log path, `WORD_COLORS` and `STRIP_COLORS` in the status
module, `tokens.state_color`, and the gitignored `.audit` Flet/Tk harnesses.
The Python server now paints nothing: the Angular page's `styles.css` is the
single source of colour, and `tests/test_theme.py` reads that block instead of a
Python palette module. `test_layers.py` and `test_docs_match.py` keep the old
imports and the old names from returning.

## Deliberately not changed

- **The palette.** Every base pair was measured and fixed to WCAG AA on
  2026-10-18; the pass adds no colour. Structure is `--rule` and `--hairline`,
  selection is rose wash with a left accent edge, and the one fill is accent.
- **The rail's page numbers.** They are the page's address (`Ctrl+2` is the
  second page), which is why the rail keeps its 01-11 column.
- **Row height.** 48px is the visual prototype's row, and it gives the
  thumbnails in History a square to sit in.
- **The palette.** The page keeps its tokens in `ui/src/styles.css` and
  `studio-grid-theme.ts`; `tests/test_theme.py` reads that block, holds every
  text pair to WCAG AA and keeps the grid copy to declared tokens. This pass
  adds no colour.
- **The server's job.** The page is the only UI; the server keeps state,
  actions and events. The new `kinds` list on `tokens.check_keys` is API, not
  presentation, and the old paint constants went with the frontend.

## Index

- page build: `ui/dist/ui/browser`, from `npx ng build`.
- checks: `ui/audit.cjs`, `npx ng test`, `tests/test_web_engine.py`.
- captures: the running Angular page at 1440x900, 1024x800 and 720x900; taken
  with Playwright, not committed.
