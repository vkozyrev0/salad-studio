# 59. Salad Studio audit, 2026-09-26 (app, layers, docs, tests, UI/UX)

**Scope:** the whole studio tree at the commit this audit was written against:
`salad_studio/` (the app and its suite), the five non-UI layers, the manuals
(`salad_studio/README.md`, root `README.md`, `salad_klein/README.md`), the
`docs/` claims those manuals lean on, and the UI/UX of the window itself.

**Goal of this pass:** find what is missing or outdated and correct it. The one
feature the brief named explicitly is a **queue management page** in the UI
layer, which the app did not have: the queue existed and worked, and nothing in
the window showed or managed it.

## 0. How this audit was run (and what is proven vs inferred)

- Every finding cites the file (and line, where the line matters) it came from.
- "executed" means a command or a driven window produced the evidence;
  "read-from-source" means the claim is a reading of the code, stated as such.
- The suite was run from the repo root:
  `python -m unittest discover -s salad_studio -p "test_*.py"`.
- The queue page was driven in a **hidden** window (`SaladStudio(show=False)`)
  with an injected transport, so no render and no network call happened.
- One measured behaviour matters for the test design and is recorded in A4: a
  Tcl call from a worker thread while the main thread sits inside a Tk callback
  deadlocks. It was hit twice while writing this pass's tests (a hung
  `test_salad_queue` run and a hung diagnostic script), and both were fixed by
  pumping `update()` instead of blocking in the callback.

## 1. Verdict per area

| Area | Verdict | Findings |
|---|---|---|
| App (`app.py`) | Accurate after this pass; one pre-existing logging hazard left open | A1 fixed, A2 fixed, A3 fixed, A4 deferred |
| Layers | Sound; the queue gained the operations the page needed | L1 fixed, L2 fixed, L3 fixed, L4 deferred |
| Docs | Three manuals had drifted; the drift is now machine-checked | D1-D6 fixed, D7 deferred |
| Tests | Green and now 616; the doc/code drift is checked instead of trusted | T1-T5 fixed |
| UI/UX | The queue is now visible and manageable; its limits are stated on the page | U1-U3 fixed, U4 deferred |

## 2. Findings

### A1, the queue had no page (Medium, executed, FIXED)

`app.py` built eleven tabs and none of them showed the queue; the only trace of a
queued or failed render was a line in the Logs tab (`app.py:2430 log`). The queue
itself was correct and tested (`salad_queue.py`), so a render could be waiting
behind another one with nothing in the window to say so.

Fixed: a **Queue** tab (`app.py: TAB_ORDER`, `_build_queue_tab`, `_refresh_queue_page`,
`_on_queue_cancel`, `_on_queue_retry`, `_on_queue_clear`). It renders the queue's
own records (`Job.id/state/attempts/status/reason/request`), shows a summary and
an explicit empty state, and its three controls act on `self.gen_queue`.
Evidence: `test_queue_page.py` (10 tests), captured to `{SCRATCH}/queue-page.log`,
`{SCRATCH}/queue-page-actions.log`, `{SCRATCH}/queue-page-ui.log`.

### A2, the module docstring described an app four years of tabs out of date (Low, read-from-source, FIXED)

`app.py:2` said "Salad Studio Windows UI: Config, LoRAs, Prompt Editor + history
strip". Fixed: it now names the twelve tabs, the queue and the graph pane.

### A3, dead routing helpers kept only for their tests (Low, read-from-source, FIXED)

`profiles.routing_conflict` and `profiles.profile_for_family` stopped shipping
when `plan_route` took over the decision (`app.py:3314`); a repo-wide grep found
their only callers in `test_profiles.py`. Fixed: both deleted, with their four
tests. The behaviour they covered (a graph whose family the group does not serve
is refused, with a reason) is covered by `test_studio_meta.py` and
`test_profiles.RoutingTest`.

### A4, a worker-thread log can deadlock the window (Medium, executed, DEFERRED)

`app.py:2430 log` appends to the Logs widget on the main thread and otherwise
calls `self.after(0, append)`; when that call raises (no main loop) it falls back
to `append()` from the worker thread, which is itself a Tcl call.

Measured here: a worker thread calling `after` while the main thread is inside a
Tk callback **blocks forever** (the diagnostic script had to be killed; the
`test_salad_queue` run hung for 198 s). In the shipped app the main loop is
running and callbacks are short, so this is a latent hazard rather than a
reported failure. Deferred: the fix is a log sink drained by a Tk timer, which is
a UI-layer redesign outside this pass's brief. The tests written here pump
`update()` instead of blocking, and say why.

### L1, the queue could not be managed (Medium, executed, FIXED)

`salad_queue.py` could hold, retry and report requests, and nothing could cancel
a request that had not been submitted, retry a failed one, or clear finished
ones. Fixed in `salad_queue.py`:

- `Job.submitted` / `Job.cancellable` / `Job.retryable` / `Job.accepted`, and
  `CANCELLED` as a terminal state.
- `cancel(job)`: drops a job that has **not** been submitted, wakes a caller
  waiting for its turn (`_wait_turn` now exits on a terminal job, `deliver`
  returns a cancelled job instead of running it), and refuses a submitted one.
- `retry(job)`: re-runs the job's own stored `work` through the same line, blocks
  until it is terminal again, and refuses a job the container already accepted
  (a re-POST would render the plate twice, docs/workflow/21).
- `clear_finished()` and `job_by_id()` for the page.

Evidence: `test_salad_queue.py` (20 tests, 6 of them new), `{SCRATCH}/queue-manage.log`.

### L2, doc 21 documented a signature that no longer exists (Low, read-from-source, FIXED)

`docs/workflow/21-klein-image-handoff.md` §2 printed
`profiles.route_payload(payload)` and a hardcoded `"snofs" in name` family test.
The shipped call is `plan_route(payload, form_profile, all_profiles)` and the
table lives in the metadata document (`studio_meta.py`). Fixed: the snippet now
shows the shipped calls, the refusal rule, and where the table lives.

### L3, the metadata document named a superseded image tag (Low, read-from-source, FIXED)

`salad_studio/studio-metadata.json` recorded `…prefetch5` for the klein family;
doc 21 §2 (the entry point for this work) records `…prefetch6-klein` for that
group and `…prefetch6-snofs` for SNOFS. Fixed: the document now carries
`prefetch6-klein`.

### L4, `generator.generate()` is used only by tests (Low, read-from-source, DEFERRED)

`generator.generate()` (prompt text + knobs, as opposed to `generate_from_payload`)
has no shipped caller: `app.py` always posts the editor JSON. It is exercised by
five tests and is the documented programmatic entry point, so it is kept rather
than deleted. Deferred with that reason.

### D1, the root README's test count was 50 tests behind (High, executed, FIXED)

`README.md` said "566 tests"; the suite was at 616. Fixed, and now checked:
`test_docs_match.py` counts `def test_` across `salad_studio/test_*.py` and
compares it with the number in the README, so this cannot drift silently again.

### D2, the root README named two dependencies the app does not use (Medium, executed, FIXED)

`README.md` requirements listed `requests` and `tkinterweb`; no module imports
`requests` (the app uses `urllib`), and the WebView2 embed is `tkwry`
(`graph_view.py:1304`). Fixed.

### D3, `salad_klein/README.md` pinned a superseded image (Medium, read-from-source, FIXED)

The build/push commands used `…prefetch4` and the prose said LIVE groups run
`prefetch3`; doc 21 §2 records `prefetch6-klein` / `prefetch6-snofs`. Fixed: the
commands use the current tags, the text names both live tags and points at doc 21
as the authority, and the older tags are kept as the record of how the rgthree
COPY arrived.

### D4, `salad_klein/README.md` gave a test command the repo does not use (Low, executed, FIXED)

It said `python -m unittest test_klein_recipes` from `salad_studio`; the repo
convention (both READMEs) is discovery from the repo root. Fixed.

### D5, the app manual's tab list stopped at eleven tabs (Low, read-from-source, FIXED)

`salad_studio/README.md` listed the tabs in the Layout paragraph and had no
**Queue** bullet. Fixed: the list names twelve tabs and the Queue bullet covers
the columns, the empty state, the refresh and the three controls' limits.

### D6, the root README's audit list stopped at 58 (Low, read-from-source, FIXED)

`README.md` linked audits 57 and 58. Fixed: 59 is linked.

### D7, doc 15's dated status block still says prefetch5 (Low, read-from-source, DEFERRED)

`docs/workflow/15-salad-flux2-klein-group.md` opens with a dated status note
("prefetch5 is pushed and both Klein groups were PATCHed"). It is a record of
what was true on that date, and doc 21 is the entry point that supersedes it.
Deferred: rewriting a dated note would falsify the record.

### T1, nothing compared the manuals with the code (High, executed, FIXED)

The tab list, the layer map and the test count were all trusted to stay in sync
by hand, and the count had already drifted (D1). Fixed: `test_docs_match.py`
holds three checks — the manual's tab list equals `app.TAB_ORDER` (order
included), every module in the layer map exists and every shipped module is
mapped, and the root README's stated count equals the number of test methods.

### T2, no test drove cancel, retry or clear (Medium, executed, FIXED)

Added to `test_salad_queue.py`: cancel a queued request before submission (with
the transport call count at zero and the caller returning), cancel refused after
submission, retry a failed request (transport called again, ends accepted), a
retry that fails again with its **new** reason, an accepted failure that is not
retryable, and clearing finished requests while a live one stays.

### T3, no test drove the page (Medium, executed, FIXED)

Added `test_queue_page.py`: the tab set, the empty state and its removal, one row
per job with state/attempts/status/reason/request read back from the queue's own
records, the cancel and retry controls invoked as a user click (with the retry
proven to run off the Tk thread), clear, the nothing-selected path, both reach
routes (sidebar button and tab lookup), a geometry/row-text dump, and a real
render driven through the app that appears on the page while running and shows
its recorded outcome after.

### T4, tests covered functions that no longer ship (Low, read-from-source, FIXED)

Four tests in `test_profiles.py` exercised `routing_conflict` and
`profile_for_family` (A3). Removed with the functions.

### T5, the tab-set copies had to grow with the set (Low, executed, FIXED)

`test_app_layout.py` asserts the notebook's labels against a literal list as well
as against `app_mod.TAB_ORDER`; `test_launch.py` keeps its own `TABS` tuple for
the launch check. Both were updated to include **Queue** deliberately; the other
three modules (`test_theme.py:232`, `test_tokens.py:339`,
`test_prompt_history.py:197`) read `app_mod.TAB_ORDER` and needed no change.

### U1, the queue was invisible in the window (Medium, executed, FIXED)

Covered by A1/L1: `app.py`'s `_build_queue_tab` shows the queue's real jobs, its
counts, and an explicit empty state (`app.QUEUE_EMPTY_TEXT`), all read back from
`salad_queue.SaladQueue.jobs()` on every refresh.

### U2, no new timer was needed (Low, executed, FIXED)

The page redraws on the tick the app already runs (`app.py:_poll_salad_status`,
15 s), on every queue event (`app.py:_on_queue_log`), when the tab opens
(`app.py:_on_notebook_tab`), and when a render finishes
(`app.py:_on_generate`'s `done`).

### U3, the controls state their own limits (Low, executed, FIXED)

Cancel applies to a request that has not been submitted, and Retry to a failure
the container did not accept. Both limits are on the page
(`app.py:QUEUE_CANCEL_NOTE` and the status line) and in
`salad_studio/README.md`, so the refusal is explained rather than silent.

### U4, a POST already accepted cannot be aborted (Low, read-from-source, DEFERRED)

Out of scope by the plan: a container that has the job keeps rendering it, so
cancel is limited to unsubmitted requests and retry to non-accepted failures.
Stated in `app.py`'s `QUEUE_CANCEL_NOTE` and in `salad_studio/README.md`.

## 3. Doc-vs-source verdicts

| Document | Verdict |
|---|---|
| `salad_studio/README.md` | Tab list and Queue bullet updated (D5); the layer map and metadata section were verified against the modules in this pass and now have a test (T1) |
| root `README.md` | Test count (D1), requirements (D2) and the audit list (D6) corrected |
| `salad_klein/README.md` | Image tags (D3) and the test command (D4) corrected |
| `docs/workflow/21-klein-image-handoff.md` | Routing snippet corrected to the shipped calls (L2) |
| `docs/workflow/15-salad-flux2-klein-group.md` | Dated status note left as the record; doc 21 is the authority (D7) |
| `docs/workflow/19`, `docs/history/57`, `58` | Read, no correction needed |

## 4. Observed test state

```
python -m unittest discover -s salad_studio -p "test_*.py"
Ran 619 tests ... OK
```

619 is 566 (the number the root README claimed before this pass) plus the tests
this pass added: `test_queue_page.py` (10), `test_docs_match.py` (8), six new
cases in `test_salad_queue.py`, minus the five tests that went with the two dead
routing helpers. The audit's own checks are part of that count, so the corrected
manuals are re-verified on every suite run.

## 5. Out of scope

- No Salad-side work: no image rebuild, no new groups, models or LoRAs, no change
  to the Klein prompt recipes.
- No redesign of the existing tabs, the theme, the history strip or the graph
  pane, and no queue durability across restarts.
- A4's log sink and U4's in-flight abort are the two deliberate deferrals.
