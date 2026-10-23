# 67. Salad Studio audit 2, 2026-10-23

A second audit of the Angular page and the Python server, with the fixes landed
in the same pass, on branch `ui-ux-pass-2026-10-23`. Three read-only readers
covered the Angular source, the Python backend, and docs/tests/CI. The page was
then driven with Playwright at 1440x900, 1024x800 and 720x900: every page, all
four Config tabs, the confirm dialog, a selected History row, the keyboard skip
path, and the populated strip. The design pass ran against those captures.

**Gate.** `npx ng build`, `node audit.cjs`, `npx ng test --watch=false` (9
specs), `python -m unittest discover -s tests -p "test_*.py"` (1097 tests) all
pass. `ui/dist` is rebuilt.

## Verdict

| area | strongest finding | outcome |
|---|---|---|
| Angular state | a failed POST left its in-flight key forever; a reply for another page replaced the open page | fixed with a catch/finally and a page guard; 2 store specs |
| Config | every action reply snapped the open tab back to Profile | the tab now posts `config.section`, and the reply seeds it once |
| Keyboard | the skip link navigated to the `page` route, which does not exist | focus moves to `main[tabindex="-1"]`, the route stays |
| Security | a History image cell interpolated its URL into `innerHTML` | the URL is escaped; `escapeHtml` has specs |
| Tables | at 1024 the last columns sat off the right edge in History, Catalog, LoRAs, Vast and Queue | one-column grid tracks, tightened columns, tooltips; every header is inside the pane |
| Graph | the default fit made node text unreadable and there was no way in | wheel/buttons zoom around the pointer, drag pans, Fit resets |
| Backend | `localhost` was refused by the origin check; a killed handler thread could hang the page | loopback origins accepted, POST guarded, 500 JSON, disconnects quiet |
| Tokens | `kinds` was unvalidated and `[]` probed all five | list of known kinds, clean refusal, `[]` checks none; 4 tests |
| Secrets | a queue reason could persist a Civitai `?token=` to the ledger and the page | redacted in `reason_of` and again at render |
| Design | the rating stars read as disabled; the confirm's initial focus had no ring; Vast's Active looked like a checkbox | visible stars, dialog ring, `● active`; Tokens is a link; the narrow rail wraps |

## Angular

### 1. A failed action kept its key forever (High)
`ui/src/app/core/studio-store.ts:128-145`: `act()` cleared `inFlight` only on
the success path. A 409, a 5xx or a dropped socket skipped the clear, so the
button spun and the line-117 guard refused every retry until reload. The catch
now clears the key, opens a dialog with the server's own message, and returns
null. `confirmYes` gets the same treatment. Proved by
`studio-store.spec.ts` (`clears the in-flight key and reports a refused action`).

### 2. A stale reply replaced the open page (High)
`studio-store.ts:173`: `apply()` set `page` from any reply. Leaving a page with
an action in flight let the reply overwrite the page now on screen. The state
is applied only when `reply.page` matches the open page; shell, effects and the
busy map still apply. Proved by the second store spec.

### 3. The Config tab was a local signal in a server-shaped page (High)
`pages/config/config-page.ts:546`: every reply re-seeded `section`, so an action
on Vast.ai returned to Profile. The tab click now posts `config.section`; the
reply seeds the page once. A typed profile name also survives a tab switch
because the name/gateway seed only when the active profile changes. Driven:
Vast.ai survives a Logs round trip and a typed name survives a tab switch.

### 4. The skip link went to a route that does not exist (High)
`shell/shell.ts:19`: `href="#page"` under hash routing is the `page` route,
which redirects to Config; `main` also had no `tabindex`. The link now prevents
the navigation, focuses `main#page`, and the pane draws a focus ring. Driven:
Enter leaves `#/config` and `document.activeElement.id === 'page'`.

### 5. A reply could overwrite fields the person was typing (Medium)
The Catalog effect re-seeded name/description on every row reply; Config
re-seeded name/gateway; Settings and Import cleared every draft on any reply.
Catalog now seeds on `pick` only; Config seeds name/gateway on a profile change;
Settings and Import drop a draft only when the reply's value equals it. This
keeps a typed value while an unrelated reply lands.

### 6. History wrote an image URL as HTML (Medium)
`pages/history/history-page.ts:185` interpolated the server's `image` into a
cell renderer that AG Grid treats as HTML. A name with a quote could add an
attribute. The URL is escaped through `shared/format.escapeHtml`; the helper and
the graph summary now live in `format.ts` with `format.spec.ts`.

### 7. Logs pulled the reader to the foot on every line (Medium)
`pages/logs/logs-page.ts:90-110` forced `scrollTop` on every appended line. Both
logs now track whether the reader is within 24px of the foot and only follow
when they are.

### 8. Tables lost their last columns at 1024 (High, UI)
The page grid tracks sized to the columns' min-content, so the `.table` grew to
980/1236px inside a 744px pane; Rating, Plate, Source and Graph were off the
right edge. The History, Catalog, Queue and LoRAs grids now use
`grid-template-columns: minmax(0, 1fr)` and a bounded table; `DataGrid` has
`min-width: 0` and `overflow: hidden`. Columns were tightened for the Vast,
Queue, Catalog and LoRAs tables; the header cells all end inside the pane at
1024 and the values keep their tooltips.

### 9. The graph could not be read (Medium, design)
`pages/editor/graph.ts`: the fit view rendered a 2391-unit graph into a 690px
pane. A wheel or the `− / Fit / +` control now zooms around the pointer, drag
pans, and a layout change resets the view. A prompt edit that keeps the layout
does not throw the zoom away.

### 10. Smaller corrections
- Rating stars used `--rule` when enabled and read as disabled; they use
  `--fg-muted` now, with the accent for a chosen star.
- The confirm box focuses "No" for safety but had no visible ring after a mouse
  click; `.box button:focus` draws one. Config's four confirm titles now name
  the action ("Delete profile", "Reallocate the instance", "Remove instance",
  "Rent this instance") instead of "Salad Studio".
- Vast.ai's Active column drew a checkbox for a read-only boolean; it draws
  `● active` or blank.
- The Tokens reference on Config is a link; Import and Assist empty readouts say
  what will fill them; the strip ring clamps when Clean gallery shrinks it.
- At 720 the rail wraps into two rows instead of hiding pages behind a
  horizontal scroll.
- `Ctrl+0` opens Queue, the tenth page, so the digit order follows the rail.
  Logs stays on the rail and the page switcher.
- Dead code removed: the unused store `busy` signal, `Api.file`, `Field.focus`,
  `Selection`'s order/step methods, `DataGrid.order`, and the duplicate
  `pageId` in `route-sync`.

## Python

### 11. `localhost` was refused (Medium)
`web/server.py:161`: the origin check compared the header to
`http://127.0.0.1:<port>`. A page opened at `http://localhost:<port>` got 403 on
every action. The check now parses the origin and accepts `127.0.0.1`,
`localhost` or `::1` on the same port. The same check now covers `/api/*` GETs,
so a cross-site read cannot drive `open_page` or the event stream. Proved by
`test_web_http.py` (localhost POST/GET, wrong port, foreign GET).

### 12. A dying handler thread sent no response (Medium)
`server.py:126`: `engine.handle` was unguarded. A core timeout or a bug escaped
`do_POST`, and the client hung. Both the engine and registry paths now answer a
500 JSON envelope and log a line without the exception text. A refused/aborted
connection is no longer printed as a server traceback.

### 13. `kinds` was not validated (Medium)
`web/controllers.py:105-120`: a string matched substrings, a non-list raised,
`[]` probed all five, and unknown names were ignored. The controller now accepts
a list of known kind strings, rejects anything else with a refusal, and treats
`[]` as "check none". Four engine tests cover all, two, empty, malformed and
unknown.

### 14. A Civitai token could reach the queue ledger and page (High)
`salad_queue.reason_of` returned the attempt's error or body verbatim;
`_finish` persisted it and `pages/queue.py` rendered it. A Comfy error echoing
the tokenized LoRA URL put the token in `studio-queue.json` and on screen. The
reason is redacted in `reason_of` and again at render, including the retry note.
Proved by `test_salad_queue` (`the_reason_redacts_a_token...`).

### 15. A busy confirm lost its token (Low)
`web/engine.py:114`: `_confirm` popped the token before checking the busy map,
so a 409 spent the confirmation. The token survives a busy refusal and works
after the action finishes. Tested in `test_web_engine.py`.

### 16. A store write was not atomic (Low)
`vast.save_doc` used `Path.write_text`; a crash could leave a truncated
`studio-vast.json`. It now uses `atomic.write_text`, like every other store.

### 17. A partial POST body could hold a handler thread (Low)
`web/server.py:149-176`: `_body` read `Content-Length` bytes with no socket
timeout, so a client that sent a short body and kept the socket open could
block a handler thread forever. The read now has a 15 second timeout. A timeout
answers 408, a body that ends before its declared length answers 400, and both
close the connection. Proved by `test_web_http.py`, which sends a short body
over a raw socket with the timeout patched to 0.2 seconds and asserts the reply
arrives as 408 or 400.

## Kept as history

- **Dated Tk/Flet records** in `docs/history/57-65` and `docs/issue-records.md`
  remain as the repository's dated record. The live tree has no Flet/Tk import;
  `test_layers.py` and `test_docs_match.py` guard the imports and names, and
  `test_theme.py` guards the page palette.

## Checks

`tests/test_web_http.py` (origin, guard), `tests/test_web_engine.py` (kinds,
confirm busy), `tests/test_salad_queue.py` (reason redaction),
`tests/test_docs_match.py` (tripwire now names the removed paint constants and
files), `ui/src/app/core/studio-store.spec.ts`, `ui/src/app/shared/format.spec.ts`,
`npx ng build`, `node audit.cjs`, and the Playwright drive at three widths.
