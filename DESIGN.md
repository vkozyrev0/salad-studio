---
name: Salad Studio
description: A local image bench for Comfy graphs — darkroom quiet, printed precision.
colors:
  safelight-navy: "#1b2836"
  bench-slate: "#243344"
  ground-navy: "#1f2c3b"
  tray-ink: "#141e28"
  field-ink: "#0f1720"
  status-ink: "#16202b"
  paper-cream: "#e8dcc8"
  muted-paper: "#a6b0c0"
  safelight-rose: "#e39aa9"
  safelight-rose-hi: "#eba9b6"
  safelight-rose-press: "#d98d9d"
  ink-on-rose: "#1b2836"
  rose-wash: "#3a2a33"
  hover-wash: "#1f2d3b"
  bench-border: "#3a4f63"
  rule-line: "#33475b"
  hairline: "#2a3948"
  paper-margin: "#cdbfa6"
  telltale-green: "#8fbf9a"
  telltale-amber: "#e0a04a"
  telltale-rust: "#d48a9a"
  telltale-blue: "#7eb8d4"
  telltale-grey: "#94a5b7"
typography:
  display:
    fontFamily: "Palatino Linotype, Book Antiqua, Palatino, Georgia, serif"
    fontSize: "31px"
    fontWeight: 400
    lineHeight: 1.05
    letterSpacing: "-0.015em"
  headline:
    fontFamily: "Palatino Linotype, Book Antiqua, Palatino, Georgia, serif"
    fontSize: "20px"
    fontWeight: 400
    lineHeight: 1.1
  title:
    fontFamily: "Palatino Linotype, Book Antiqua, Palatino, Georgia, serif"
    fontSize: "15px"
    fontWeight: 600
    lineHeight: 1.2
  body:
    fontFamily: "Segoe UI Variable Text, Segoe UI, system-ui, sans-serif"
    fontSize: "13.5px"
    fontWeight: 400
    lineHeight: 1.45
  label:
    fontFamily: "Cascadia Mono, Cascadia Code, Consolas, monospace"
    fontSize: "10px"
    fontWeight: 500
    letterSpacing: "0.12em"
  data:
    fontFamily: "Cascadia Mono, Cascadia Code, Consolas, monospace"
    fontSize: "11.5px"
    fontWeight: 400
    lineHeight: 1.5
rounded:
  plate: "1px"
  chip: "2px"
  control: "3px"
  card: "4px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "24px"
components:
  button-primary:
    backgroundColor: "{colors.safelight-rose}"
    textColor: "{colors.ink-on-rose}"
    rounded: "{rounded.control}"
    height: "34px"
    padding: "0 15px 0 13px"
  button-primary-hover:
    backgroundColor: "{colors.safelight-rose-hi}"
    textColor: "{colors.ink-on-rose}"
    rounded: "{rounded.control}"
    height: "34px"
    padding: "0 15px 0 13px"
  button-primary-active:
    backgroundColor: "{colors.safelight-rose-press}"
    textColor: "{colors.ink-on-rose}"
    rounded: "{rounded.control}"
    height: "34px"
    padding: "0 15px 0 13px"
  button-ghost:
    backgroundColor: "{colors.bench-slate}"
    textColor: "{colors.paper-cream}"
    rounded: "{rounded.control}"
    height: "34px"
    padding: "0 13px"
  button-quiet:
    textColor: "{colors.muted-paper}"
    rounded: "{rounded.control}"
    height: "34px"
    padding: "0 13px"
  button-key:
    backgroundColor: "rgba(227, 154, 169, 0.06)"
    textColor: "{colors.safelight-rose}"
    rounded: "{rounded.control}"
    height: "34px"
    padding: "0 13px"
  field-input:
    backgroundColor: "{colors.field-ink}"
    textColor: "{colors.paper-cream}"
    rounded: "{rounded.control}"
    height: "36px"
    padding: "0 10px"
  rail-link-active:
    backgroundColor: "{colors.rose-wash}"
    textColor: "{colors.paper-cream}"
    padding: "6px 10px"
  data-row:
    backgroundColor: "{colors.safelight-navy}"
    textColor: "{colors.paper-cream}"
    height: "48px"
  dialog:
    backgroundColor: "{colors.bench-slate}"
    textColor: "{colors.paper-cream}"
    rounded: "{rounded.card}"
    width: "460px"
    padding: "16px"
  plate-print:
    backgroundColor: "{colors.paper-margin}"
    rounded: "{rounded.plate}"
    padding: "3px"
---

# Design System: Salad Studio

## Overview

**Creative North Star: "The Darkroom Bench"**

Salad Studio is a dark room with the lights low and one rose safelight on. The operator stands at a bench, reads instruments, and hangs finished plates on a contact sheet. Nothing on screen is decorative for its own sake: every surface is either the bench (navy), the paper (cream), or the safelight (rose), and the interface's job is to make a long, asynchronous render legible without becoming the thing you look at.

The system is built from two materials. The first is a dark, cool navy that recedes: `--bg` for the page, `--ground` for the working pane, `--well` and `--field` for places you type or read a log. The second is printed paper: a warm cream for text, a mono face for anything that is data, and a narrow paper margin around every generated image so a plate reads as a physical print. Palatino appears in exactly four places — the wordmark, the page title, the empty-sheet title and the aside name — so the serif stays a sign rather than a voice.

Density is that of a workbench: 34px controls, 36px fields, 48px table rows, 12px rhythm inside a row and 22px between sections. Motion is almost absent; a 120ms border or background shift acknowledges a press, and the only looping motion is a render's spinner and a page's breathing tick. The confirmed anti-reference is the generic dark SaaS dashboard: no glass, no gradients, no glow, no purple, no rounded cards floating in space.

**Key Characteristics:**
- Navy bench, cream paper, one rose safelight.
- Mono for data and labels; Segoe UI for prose; Palatino for signs.
- Flat by default; depth is tonal, with shadows only for what floats.
- Nearly square corners: 1px plates, 2px chips, 3px controls, 4px cards.
- Every state carries a word, not just a colour.
- Generated images are printed: paper margin, vignette, slightly desaturated.

## Colors

A cool navy ground with warm paper on it, and a single rose that behaves like light.

### Primary
- **Safelight Rose** (#e39aa9): the one accent. Fills the primary button, the page-number chip, the focus ring, the active rail edge, the ring on the selected plate, and the lit wire in the graph pane. Its hover is **Safelight Rose High** (#eba9b6) and its press **Safelight Rose Press** (#d98d9d). Text on a rose fill is **Ink on Rose** (#1b2836).
- **Rose Wash** (#3a2a33): the rose read as a room, not a light. The selected rail row, a selected table row, a selected LoRA card, and `::selection` all sit on this, with a 2px rose edge where a row needs one.

### Neutral
- **Safelight Navy** (#1b2836): the page and the table's base. Also the ink on a rose fill.
- **Bench Slate** (#243344): the top bar, the rail, a dialog, an aside card, a graph card. One step up from the page.
- **Ground Navy** (#1f2c3b): the working pane behind a page. Slightly warmer and lighter than the page so the sheet reads as a separate surface.
- **Tray Ink** (#141e28): the darkest step. Keycaps, an empty state's frame, a plate's backdrop.
- **Field Ink** (#0f1720): the fill of an input, a select, a textarea, a log, a readout. Darker than the pane, so a place to type reads as recessed.
- **Status Ink** (#16202b): the status line at the foot of the window.
- **Paper Cream** (#e8dcc8): body text and headings. Warm, never pure white.
- **Muted Paper** (#a6b0c0): labels, hints, captions, table cells at rest, the inactive rail. Cool, so it recedes against cream.
- **Bench Border** (#3a4f63): a panel's full border, as on a dialog.
- **Rule Line** (#33475b): the structural rule under a bar, around a table, around a segmented control.
- **Hairline** (#2a3948): the quieter divider between sections and rows inside a surface.
- **Paper Margin** (#cdbfa6): the 3px edge around a printed plate.

### Telltales
- **Telltale Green** (#8fbf9a): ready replicas, a successful check, a `done` queue row, an `ok` log level.
- **Telltale Amber** (#e0a04a): starting replicas, a warning, a note that needs attention.
- **Telltale Rust** (#d48a9a): a failed render, a rejected key, an `error` level, the not-started count.
- **Telltale Blue** (#7eb8d4): an input port in the graph pane, informational state.
- **Telltale Grey** (#94a5b7): an unconfirmed provider check, an unknown value.

### Named Rules

**The Safelight Rule.** Rose is light, not paint. One primary rose fill per page; selection uses Rose Wash; a rose panel, rose background section, or rose heading is out of system.

**The Token Or Nothing Rule.** Every colour comes from the token block in `ui/src/styles.css`. A hex literal in a component fails `tests/test_theme.py`, which also holds every text pair the page draws to WCAG AA.

**The Word Beside The Colour Rule.** No state is carried by hue alone. Meters write Ready, Starting, Not started; log lines carry a level word; token checks write their state under the slot.

## Typography

**Display Font:** Palatino Linotype (with Book Antiqua, Palatino, Georgia)
**Body Font:** Segoe UI Variable Text (with Segoe UI, system-ui)
**Label/Mono Font:** Cascadia Mono (with Cascadia Code, Consolas)

**Character:** A book face against a technical one. Palatino gives the page a printed-sheet title; Cascadia gives every number, address, label and log line the even, evidence-like tone of a readout. Segoe UI carries the prose between them and stays out of the way.

### Hierarchy
- **Display** (400, 31px, 1.05, −0.015em): the page title only, beside its rose address chip. The wordmark is the same face at 20px; an aside's name and an empty-sheet title use it at 21px and 19px.
- **Title** (600, 15px, 1.2): a dialog's heading. The smallest the serif goes.
- **Body** (400, 13.5px, 1.45): prose, notes, field values, hints. Long lines cap around 80ch in a page foot and 46ch in an empty state.
- **Label** (500, 10px, 0.12em, uppercase): the mono label above every field, the eyebrow above a section, table headers at 0.1em, the rail's footer and address numbers. Never sentence case, never more than a few words.
- **Data** (400, 11.5px, 1.5): request JSON, log lines at 12px, readouts, counts, timestamps, keycaps at 10px. Monospace is the signal that a value is meant to be compared or copied.

### Named Rules

**The Two Voices Rule.** Palatino appears only in the wordmark, the page title, an empty-sheet title and the aside name. A serif paragraph, a serif button, or a serif table cell is out of system.

**The Mono Is Evidence Rule.** Mono marks anything a person compares, copies or trusts: addresses, counts, sizes, ids, times, keys, JSON, logs. Prose in mono and data in a proportional face both break the rule.

## Layout

The window is a fixed grid, not a flowing document. A 232px rail runs down the left; the rest is the pane. Rows are the 58px action bar, the pane, the status line, and the plate strip. The shell never scrolls; a page scrolls inside its own body, so its title, note and the strip stay in place while the sheet moves.

Every page opens through the same frame: a mono address chip in rose, the serif title, a 12.5px subtitle, then a note line with a 4px state dot and a timestamp. The body below it is the page's own composition.

Three compositions cover the eleven pages. A **split** puts a controls column beside a reading column (Prompt Settings: 280px knobs, LoRAs filling; Prompt Editor: 2fr JSON, 3fr graph). A **sheet** is one full-width table with a toolbar above and a note below (Queue, Prompt History, LoRAs, Logs). A **tabs** layout puts a segmented section strip over a main column and a 320px sticky aside (Config). Within all three, a row is a flex line of fields and buttons at a 12px gap that wraps before it clips; a section is a hairline above, a mono eyebrow, and 22px between sections.

Density is fixed by role: 34px buttons (28px for `sm`), 36px inputs and selects, 48px table rows under a 36px header, 84px for the plate strip's reel, and 232px of rail. Pane padding is 20px 24px 16px.

Breakpoints stack rather than shrink. At 1080px the Config aside drops below its column; at 1040px Prompt Settings stacks its two columns and the LoRA grid reflows; at 900px the editor stacks JSON above the graph; at 860px the rail becomes a horizontal wrapped tab bar under the bar and the strip's keyboard hints are dropped so the status sentence keeps its width.

**The Fixed Frame Rule.** The window is a bench, not a page: bars, rail, status and strip stay put and the page body is the only thing that scrolls. A full-window scroll or a floating toolbar is out of system.

## Elevation & Depth

The system is flat with tonal layering. Depth is a step in value, not a shadow: page (#1b2836) → pane ground (#1f2c3b) → surface (#243344) → field/well (#141e28). One-pixel rules (#33475b) and hairlines (#2a3948) do the separating, and a 1px border plus a 2px rose edge marks selection without lifting anything.

Shadows appear only where a thing genuinely floats above the bench.

### Shadow Vocabulary
- **Dialog lift** (`0 18px 48px rgb(0 0 0 / 0.45)`): the only deep shadow, on a modal box under a blurred scrim.
- **Floating control** (`0 2px 8px rgb(0 0 0 / 0.3)`): the graph's zoom control sitting over the drawing.
- **Plate edge** (`0 1px 2px rgb(0 0 0 / 0.5)`): the paper margin of a printed image, so it reads as a physical print.
- **Plate vignette** (`inset 0 0 10px rgb(0 0 0 / 0.38)`): the inner shadow inside a plate's image edge.
- **Field recess** (`inset 0 1px 0 rgb(0 0 0 / 0.35)`): the top lip of an input, so its fill reads as sunk.
- **Primary press** (`0 1px 0 rgb(0 0 0 / 0.25)`): the rose button's one-pixel ground contact.

### Named Rules

**The Flat-By-Default Rule.** A surface at rest has no shadow. If it is not a dialog, a floating control, or a printed plate, it is separated by tone and a 1px rule.

## Shapes

Nearly square. Plates use a 1px radius, chips and keycaps 2px, controls 3px, cards and dialogs 4px. Nothing is a pill, and nothing is rounder than 4px. Borders are 1px in `--rule` or `--hairline`; selection is a 2px edge in `--accent` on the left of a rail row or pick row, the bottom of a tab, or the full outline of a plate; focus is a 2px rose outline with a 2px offset, or a 1px rose outline flush with a field.

The recurring silhouettes are the printed plate (paper margin, vignette, slightly desaturated image) and the blank plate frame: a dashed 54×42 rectangle that stands in for a missing image in an empty table, and a 34×26 one in the empty strip. The segmented switch is a single bordered strip whose chosen part carries an inset 2px rose underline.

**The Nearly Square Rule.** Four pixels is the ceiling. A pill button, an 8px card, or a circular avatar introduces a different product.

## Components

### Buttons
- **Shape:** 3px radius, 34px tall (28px for `sm`), 12.5px semibold Segoe UI, 0.005em tracking, no uppercase.
- **Primary:** the rose fill, ink-on-rose text, `0 15px 0 13px` padding, one per page or one per action group. It is the only saturated fill on the screen.
- **Ghost:** bench-slate fill with a 1px rule. Hover raises it to `--wash`.
- **Quiet:** text only, muted; hover brings cream and a wash. Used for Cancel, Open, and dialog dismissals.
- **Key:** a rose-tinted outline button for the one action that changes the artifact (Validate). Rose border at 50% and a 6% rose fill, not a second primary.
- **Danger:** rust text, no fill at rest, a 9% rust wash on hover. Reserved for destructive confirmation.
- **Busy:** a button keeps its width and swaps its label for a 11px spinner plus a present participle (Rendering, Saving), so the row does not jump.

### Fields
- **Label:** mono 10px uppercase above the control, 0.12em, muted.
- **Shape:** 36px, 3px radius, 1px rule, field-ink fill, 13px Segoe UI, a 1px inner top shadow.
- **Hover / Focus:** the border goes to muted paper on hover; focus is a 1px rose outline flush with the border. A read-only field drops its text to muted.
- **Mono variant:** 12px Cascadia for JSON, URLs and keys, with spellcheck off.
- **Hint:** 11.5px muted below the field, 10.5px in mono.

### Segmented Switch and Tabs
- **Segmented switch:** a 34px strip in field ink with 1px rules between parts; the pressed part takes the wash and an inset 2px rose underline. It is the section control on Config.
- **Tabs:** a 38px text row over a 1px rule, 26px apart; the chosen tab is cream with a 2px rose underline sitting on the rule.

### Rail and Page Frame
- **Rail:** bench-slate, 232px, 10px inset. The wordmark is Palatino 20px; under it a mono eyebrow reads "Image bench · local". Eleven links, each a 2px transparent left edge, a mono 10px number, and a 13px name. Active is rose wash, cream text, rose edge, rose number. The foot is a mono 10px pair: page count and the Ctrl+1–9 hint.
- **Page frame:** a rose address chip (mono 10px, 2px radius, raised 6px to sit on the title's baseline), the 31px Palatino title, a 12.5px subtitle, then a note line with a 4px dot, a mono timestamp and the sentence. The note's dot and text carry the level; the body scrolls beneath it.

### Data Grid
- **Shape:** AG Grid Community on `themeQuartz`, one row selectable, no checkboxes, 48px rows, 36px header, square wrapper.
- **Header:** mono 10px uppercase at 0.1em in muted, quiet sort and filter marks that come to full opacity on hover.
- **Rows:** page-navy at rest, bench-slate on odd rows, a 1px rule between. Numbers are right-aligned with tabular figures.
- **Empty:** never an empty grid. A dashed plate frame, a 19px Palatino title, and one sentence saying what fills it.

### Printed Plate
- **Frame:** 3px of paper margin (2px at `small`), 1px radius, a 1px edge shadow, an inset vignette, and `filter: saturate(0.9) contrast(1.05)` on the image.
- **Selection:** a 2px rose outline at 2px offset. Hover is a 1px rule outline.
- **Strip:** the newest plates as a contact sheet in an 84px band, 56×48 thumbnails, a mono index and clock-time caption under each, tall arrows at each end. With no plates it collapses to one 34px line with a blank print frame.

### Dialog
- **Shape:** 460px wide, 4px radius, bench-slate, a 1px border with a 2px rose top edge, 16px padding, the 18/48 dialog shadow over a 62% black scrim with a 1.5px blur.
- **Content:** an 8px square mark (rose, or rust for an error), a 15px Palatino semibold title, 13px body with preserved line breaks, and a right-aligned foot. A confirm puts No first and Yes in rust. Focus is trapped, Escape dismisses, and focus returns to the opener.

### Graph Pane
- **Canvas:** field-ink with a 1px rule and 3px radius; grab and grabbing cursors.
- **Cards:** bench-slate with a 1px rule, 3px radius, a 600-weight Segoe title, mono 9.5px port and row text. Input ports are blue dots, output ports green. Selected is a 2.5px rose stroke; keyboard focus is a dashed rose stroke; a card not wired to the selection drops to 30% opacity so one wire can be followed end to end.
- **Zoom:** a floating bench-slate control at 8px from the corner, mono readout, 24px buttons.

### Log and Readout
- **Log:** field-ink, 6px padding, 3px radius, 12px mono at 1.5 line-height. A 5ch level word leads each line and carries the colour, so colour is never the only signal.
- **Readout:** a bordered field-ink block in 11.5px mono with preserved whitespace; a `.prose` variant switches to 12.5px Segoe.

### Meters, Eyebrows and Keycaps
- **Meter:** a mono label, a 22×3px track filled to the count (capped at four replicas), and a tabular count in a fixed 1.6ch slot so a changing number does not slide the bar. Ready is green, starting amber, not started rust.
- **Eyebrow:** mono 10px uppercase at 0.13em in muted; the section's name above a group of controls or a table.
- **Keycap:** mono 10px in a 2px-radius tray-ink box with a 1px rule; used for Ctrl+Tab, arrows and Enter.

## Do's and Don'ts

### Do:
- **Do** put a mono label above every control, and write labels as short nouns: Width, Steps, Seed, Gateway URL.
- **Do** print a plate: paper margin, 1px radius, vignette, slight desaturation, before it appears in a strip, a history row, or an aside.
- **Do** give a disabled action its reason in words, in the button's title or the page's note.
- **Do** use tabular figures and a fixed-width slot for any count that changes while the page is open.
- **Do** keep one rose fill per page and let Rose Wash carry selection.
- **Do** name the level in words next to the colour, in logs, meters and token dots.
- **Do** keep page bodies scrolling under a fixed frame, and let long lines cap near 80ch.

### Don't:
- **Don't** add glass, backdrop blur outside the dialog scrim, gradients, glow, or purple; the confirmed anti-reference is the generic dark SaaS dashboard.
- **Don't** round anything past 4px, and don't turn a control into a pill.
- **Don't** use the rose as a large fill, a section background, or a heading colour.
- **Don't** set a paragraph, button, or table cell in Palatino; the serif is a sign.
- **Don't** put prose in mono or data in a proportional face.
- **Don't** use pure white or pure black; paper cream and tray ink are the ends of the range.
- **Don't** show a bare `img` for a generated plate, and don't show an empty grid where a dashed frame and a sentence belong.
- **Don't** invent a second accent for a new state; reach for the telltales, and write the state's word.
