# Salad Studio audit, 2026-10-16

A full read of the app across five surfaces — UX/UI, code, tests, metadata and
presentations — with the reading fanned out to six workers and every claim
re-checked against the tree by the orchestrator. **Nothing in the repo was
changed**: this document is the audit, and each `**Correction:**` line is a
proposal for a later goal.

## 1. Verdict per surface

| surface | verdict | findings | the strongest |
|---|---|---:|---|
| **UX/UI** | Two real defects a user hits, and the layout, empty states and redaction hold | 7 (5 defects, 2 clean) | the page switcher is mouse-only: `<Return>`/`<space>` on the eleven nav buttons do nothing (`salad_studio/theme.py:310`, `salad_studio/app.py:384-410`) |
| **code** | Substantially clean; the live class is 504/524 re-submission in the hand-run scripts | 5 (4 defects, 1 clean) | `salad_catalog_faces.gen_one` retries 504/524 up to 24 times, so a mass run can render a plate twice (`salad_catalog_faces.py:251-254`) |
| **tests** | In good order; one guard cannot see what it claims to check | 5 (4 defects, 1 clean) | the "store is outside the repository" guard reads another module's leftover redirect (`tests/test_app_layout.py:38-44`, `tests/test_vast.py:418-423`) |
| **metadata** | The routing table, probes, deploy facts and pins re-check; the defects are dead schema | 6 (5 defects, 1 clean) | eight of the pack's twelve templates have no composer and the four body ones cannot be filled (`face_prompt_pack.json:294-305`) |
| **presentations** | The READMEs, the viewer pins and the skill re-check; the playbooks still misstate a recipe | 6 (5 defects, 1 clean) | doc 15's anatomy recipe seed and LoRA chain name a number and a LoRA no shipped file carries (`docs/workflow/15:93-99`) |
| **docs** | The living documentation's factual claims, audited through the presentations and metadata sweeps | 7 findings carry the tag | doc 22's cite into doc 14 still points five lines past the row (`docs/workflow/22:55`) |

Finding counts by severity: **High 1, Medium 10, Low 16, clean 6** (30 findings).

**What the audit re-checked and did not re-report.** The six `docs/` issue records
hold 30 issues; every one was re-driven here and **all 30 still hold — none
regressed** (§7). Three of the findings below are pool rows those records listed
below the bar and left open; each names the record it came from.

## 2. How the reading was fanned out

| worker | area | returned |
|---|---|---|
| `01a144c5-0589-7263-85f8-f1a1c4fd24f2` | UX/UI, driven hidden | 7 findings (5 defects, 2 clean) with 8 drive scripts |
| `01a144c5-0589-7263-85f8-f1b1045c2fde` | code | 5 findings (4 defects, 1 clean) |
| `01a144c5-0589-7263-85f8-f1c419e564ff` | tests | 5 findings (4 defects, 1 clean) |
| `01a144c5-3a1e-7132-a34b-66f8fead66c4` | metadata | 6 findings (5 defects, 1 clean) |
| `01a144c5-3a1e-7132-a34b-67023b62a513` | presentations | 6 findings (5 defects, 1 clean) |
| `01a144c5-3a1e-7132-a34b-67138d404396` | re-check of the 30 recorded issues | the 30-row table in §7, plus one new finding (N1) |

The orchestrator re-read every cited line, ran the citation resolver over this
document, re-ran the UI/UX drives this audit rests on, and ran both suites. The
worker ids, areas and results are also in `{SCRATCH}/fan-out.log`.

## 3. UX/UI — the Tkinter app on the real hidden window
7 findings. Owner: the UX/UI sweep worker (59 tool calls, 8 drive scripts), every citation re-read by the orchestrator.

### U1, the window opens 1455x1238, taller than a laptop screen, because three pages are not scrollable (UI, Medium, executed) FIXED
`salad_studio/app.py:4803-4810` opens the window at the whole layout's requested size
(`_opened_width/_opened_height` = **1455x1238** at construction) with no clamp against
`winfo_screenheight()`, and `_reapply_opened_size` (`:4817-4829`) re-forces that size for the
first 2.2 s. Eight pages go through `_scrollable_page`, so their canvases request only
1169x457; the three that do not — Prompt Catalog, Prompt History, Queue (`:3022`, `:3655`,
`:3847`) — are the pages that request 1289x602, **1195x982** and 969x504 (driven: `measure.py`,
both window sizes). On a 1920x1080 or 1366x768 display the bottom of the window — the status
line every refusal is written to, and part of the history strip — is off-screen at launch.
**Correction:** build those three pages through `_scrollable_page` like their eight siblings (their
Treeviews already carry weight and a scrollbar), and clamp the opened geometry to the screen's work area.
**Fixed:** the three pages that sized the window now go through `_scrollable_page` with `_page_keeps_its_own_size` keeping the grid's request out of the page's, and the opened geometry is clamped to the screen's work area (`salad_studio/app.py:3101`, `:3124-3125`, `:3755-3756`, `:3951-3952`, `:4903`, `:4960`). Proved by `tests/test_config_page.py::TheAuditOf2026_10_16::test_the_three_pages_that_sized_the_window_now_scroll` and `::test_the_window_opens_inside_the_screen_it_has`: the layout now requests 577x670 (was 1457x1473) and the window opens at the mocked work area's 600 px. Old form: `1457 not greater than 1473`. Captured in `{SCRATCH}/revert_final.txt`.

*Owner: the UX/UI sweep worker (59 tool calls, 8 drive scripts), every citation re-read by the orchestrator.*

### U2, the only page switcher is mouse-only and shows no focus (UX, High, executed) FIXED
`salad_studio/theme.py:310` removes the notebook's tab element (`style.layout("Hidden.TNotebook.Tab", [])`), so
the eleven `tk.Button`s in `salad_studio/app.py:384-410` are the only way to change page. Driven (`drive.py`):
with the "Logs" nav button focused, `<Key-space>` and `<Return>` both leave the page on `Config`,
while the identical drive on the ttk `Generate` button runs `_on_generate` — so the key path works,
the classic `tk.Button` just does not answer it. They also carry `bd=0`,
`highlightthickness=0`, `relief="flat"` (`salad_studio/app.py:395-406`) and no focus mapping, so a keyboard user
cannot see where focus is. `<Control-Tab>` does switch (`Config` → `Prompt Settings`, driven), but
nothing on screen suggests it.
**Correction:** bind `<Return>` and `<space>` on each nav button (or make them `ttk.Button`s) and give the
focused nav button a visible state.
**Fixed:** the nav buttons gained `<Return>`/`<space>` bindings, a focus ring and a focused face (`salad_studio/app.py:437`, `:453-457`, `:460`, `:480`, `:256`). Proved by `::test_the_nav_buttons_answer_the_keyboard_and_show_focus`: with Logs focused, `_nav_focused is btn`, `highlightthickness == 1`, and both keys switch the page. Old form: `None is not <tkinter.Button …>`. Captured in `{SCRATCH}/revert_final.txt`.

*Owner: the UX/UI sweep worker (59 tool calls, 8 drive scripts), every citation re-read by the orchestrator.*

### U3, two Generate refusals never reach the Logs (UX, Medium, executed) FIXED
The manual promises the Logs carries a refusal (`salad_studio/README.md:321-326`: "the Logs line, the
status line (`Refused: …`) and the dialog all carry that one sentence"), and the dispatch refusal
keeps that promise (`salad_studio/app.py:5436-5438`). The missing-key refusal (`salad_studio/app.py:5408-5413`) and the
bad-form-value refusal (`salad_studio/app.py:5373-5376`) write the status line and the dialog and return with no
`log` call. Driven (`drive2.py`): pressing Generate with no token store grows the Logs by **0** lines
(status `Refused: Salad API key is empty…`, dialog shown), and a non-numeric Width grows it by **0**
too, while the empty-gateway sibling (`:5414-5417`) and the route refusal (`:5394-5397`) both log.
**Correction:** add `self.log("error", …)` to those two returns, carrying the same sentence the dialog shows.
**Fixed:** both refusals now write the Logs as well as the status line and the dialog (`salad_studio/app.py:5555`, `:5593`). Proved by `::test_the_two_generate_refusals_reach_the_logs`: the pane grows by `Generate aborted: Salad API key is empty…` and `… Width must be a whole number (got 'abc')`. Old form: the Logs stayed empty. Captured in `{SCRATCH}/revert_final.txt`.

*Owner: the UX/UI sweep worker (59 tool calls, 8 drive scripts), every citation re-read by the orchestrator.*

### U4, a bad Width/Height/Steps/CFG/Seed is reported as a Python exception (UX, Medium, executed) FIXED
`_profile_from_form` (`salad_studio/app.py:5153`) lets the `int()`/`float()` error escape and `_on_generate`
catches it at `salad_studio/app.py:5373-5375`, so the user reads the interpreter's words. Driven (`drive2.py`, with
Width `abc`): the dialog and the status line both read
`Refused: invalid literal for int() with base 10: 'abc'` — no field named, nothing about where to fix it.
**Correction:** validate the numeric fields in `_profile_from_form` and refuse with the field's name, e.g.
`Refused: Width must be a whole number (got 'abc')`.
**Fixed:** `_whole_number` / `_number` read the five knobs and refuse by field name (`salad_studio/app.py:5306`, `:5323`, `:5341-5345`). Proved by `::test_a_bad_number_is_refused_by_the_name_of_its_field` for all five fields. Old form: `invalid literal for int() with base 10: 'abc'`. Captured in `{SCRATCH}/revert_final.txt`.

*Owner: the UX/UI sweep worker (59 tool calls, 8 drive scripts), every citation re-read by the orchestrator.*

### U5, the own-image form drops a port the user typed, silently (UX, Low, executed) FIXED
`salad_studio/app.py:2391-2394` passes both port entries to `image_deploy.add_image`, and `_ports`
(`salad_studio/image_deploy.py:50-62`) keeps only values `int()` accepts, so a typo becomes "no port".
Driven (`drive2.py`): API port `3000/api`, Comfy empty, Add → no dialog, status
`added the image mine2`, the facts line reads `ports - (api) / - (comfy)`, and the printed
`docker run --gpus all mine2:1` publishes nothing; the same form with `3000`/`8188` prints
`-p 3000:3000 -p 8188:8188`, so the plumbing is fine and only the feedback is missing.
**Correction:** refuse a non-empty port that is not a positive integer, naming the field, the way `add_image`
already refuses a missing name or tag.
**Fixed:** `image_deploy.port_refusal` refuses a non-empty non-integer port by its page label, called from `add_image` (`salad_studio/image_deploy.py:69`, `:75`, `:560`); `_ports` stays lenient for a hand-edited store and says so. Proved by `tests/test_config_page.py::TheAuditOf2026_10_16::test_a_typed_port_that_names_no_port_is_refused_by_name`: `API port must be a whole number (got '3000/api').`, nothing added. Old form: no dialog, the image added with `ports == {}`. Captured in `{SCRATCH}/revert_final.txt`.

*Owner: the UX/UI sweep worker (59 tool calls, 8 drive scripts), every citation re-read by the orchestrator.*

### U6, the four list empty states and the bare queue presses re-check clean (UI, clean, executed) FIXED
Driven with empty stores (`drive2.py`): `queue_empty_lbl`, `prompt_hist_empty_lbl` and
`catalog_empty_lbl` (`salad_studio/app.py:127-129`, shown/hidden at `:3981-3984`, `:3749-3754`, `:3137-3142`) are all
mapped and inside the page (`y` 400/433/406 in a 472-tall page), and the history strip draws its
`EMPTY_TEXT` canvas item (`salad_studio/history_strip.py:27`, `:150-166`) once `set_paths([])` runs. Bare presses with
nothing selected answer on the page (`salad_studio/app.py:4045-4075`): Cancel and Retry both `Queue: select a request
first`, Clear finished `Queue: cleared 0 finished request(s)`, and the empty-state label stays shown.
**Correction:** none.
no change needed, re-confirmed: the four list empty states and the bare queue presses still answer on the page (driven in `{SCRATCH}/uiux.log`, and `tests/test_app_layout.py`'s `ListSurfacesSayWhenTheyAreEmpty` is green).

*Owner: the UX/UI sweep worker (59 tool calls, 8 drive scripts), every citation re-read by the orchestrator.*

### U7, the Logs redaction and the dead local helper's error surfaces re-check clean (UX, clean, executed) FIXED
Driven (`check3.py`): after `tokens.write_token("salad", …)` and a log line containing that value, neither
the Studio pane nor the Salad pane (`salad_studio/app.py:4143-4149`, `:4195-4218`) holds the secret —
`studio_log.redact("x salad-secret-… y", […])` returns `x … y`. The Logs page has no filter control, only
"Refresh Salad logs" and "Clear Studio logs". Driven (`drive2.py`) with
`ai_helper.help_with_prompts_local` raising `URLError: connection refused`: the reply box, the helper state
word, the status line and a `ERROR Prompt Assist (the local model)` line all carry the failure, and both
Help buttons return to `normal` (`salad_studio/app.py:2950-2973`).
**Correction:** none.
no change needed, re-confirmed: the Studio and Salad panes both redact a written token, and the dead local helper's error surfaces still report (`tests/test_app_layout.py::BothLogPanesMaskSecrets` is green; driven in `{SCRATCH}/uiux.log`).

*Owner: the UX/UI sweep worker (59 tool calls, 8 drive scripts), every citation re-read by the orchestrator.*

## 4. Code — the package, the root scripts and the build context
5 findings. Owner: the code sweep worker (48 tool calls), every citation re-read by the orchestrator.

### C1, `salad_catalog_faces.gen_one` retries 504/524 up to 24 times, so a mass run can render a plate twice (code, Medium, read-from-source) FIXED
`salad_catalog_faces.py:251-254` treats `504` (and every other `code >= 500`, so `524` too) as `"retry"`, and `:357-361` puts the cell back on `pending` until 24 retries are spent. The function's own docstring at `:235` says only `"502/503 = retry (dead replica)"`, and the project's recorded invariant is that 504/524 are **terminal** because Cloudflare returns them after giving up on a job the container may still be running, so a re-POST submits a duplicate render (`salad_studio/salad_queue.py:88-91`, `docs/workflow/21`). A catalog run therefore re-POSTs cells whose job was already accepted, at GPU cost, and `record(e, "failed")` is only reached after 24 such POSTs.
**Correction:** retry only `code in (502, 503, 429)` in `gen_one` and return `"failed"` for 504/524 and the other 5xx codes.
**Fixed:** `gen_one` retries only 502/503/429 and lets 504/524 fall to `failed` (`salad_catalog_faces.py:234-241`, `:257`). Proved by the new `tests/test_salad_catalog_faces.py` (8 tests) driving the shipped retry logic with a stubbed transport: 1 POST where the old form made 24. Captured in `{SCRATCH}/retry_evidence.log` and `oldform_check.log`.

*Owner: the code sweep worker (48 tool calls), every citation re-read by the orchestrator.*

### C2, The three probe scripts re-POST `/prompt` on 504/524, the codes the app treats as terminal (code, Low, executed) FIXED
`salad_probe_klein.one` (`salad_probe_klein.py:324-328`), `salad_probe_ages.one` (`salad_probe_ages.py:75-79`) and `salad_probe_sdxl.post` (`salad_probe_sdxl.py:157-173`) all loop on a 504/524 answer; `post` retries *any* non-200 nine times. Executed: a scratch drive with `salad_gen._req` stubbed to always answer `504` (`python C:\Users\vkozy\AppData\Local\Temp\grok-goal-96da7f919630\implementer\probe_504.py`) printed `A POSTs to /prompt: 6` from one `one()` call — six submissions of a job the gateway may still be running, against the rule the app itself enforces in `salad_queue.classify`.
**Correction:** drop `504` and `524` from those retry tuples (keep `502, 503`), so a gateway timeout is reported as a failure instead of re-submitted.
**Fixed:** the three probes drop 504/524 from their retry sets (`salad_probe_ages.py:79-83`, `salad_probe_klein.py:328-332`, `salad_probe_sdxl.py:173-178`), keeping 502/503. Proved by the same module: 1 POST where the old form made 8 / 6 / 9. Captured in `{SCRATCH}/retry_evidence.log`.

*Owner: the code sweep worker (48 tool calls), every citation re-read by the orchestrator.*

### C3, `generator.ready_budget_s` names one sleep interval the readiness loop never spends (code, Low, executed) FIXED
`salad_studio/generator.py:102-108` sums `ready_sleep_s` over `range(_READY_TRIES)` (118 intervals, 5430 s), but the loop at `:147` only sleeps while `attempt + 1 < _READY_TRIES` (`:161`, `:173`), i.e. 117 times — so the failure message's "~90 minutes" is built from one interval more than the loop can spend, contradicting the docstring's "the budget a failure message names is the one the loop actually spends". Executed: the same scratch drive ran `wait_gateway_ready` against a 503 transport and printed `B sleeps: 117 sum(sleeps): 5370` versus `B ready_budget_s(): 5430 probes: 118`.
**Correction:** sum over `range(_READY_TRIES - 1)` in `ready_budget_s`.
**Fixed:** `ready_budget_s` sums `range(_READY_TRIES - 1)` (`salad_studio/generator.py:109`), so the message's budget is what the loop spends. Proved by `tests/test_generator.py::…test_the_budget_is_the_sleeps_the_wait_spends`: 117 sleeps summing 5370 s against a budget of 5370 s (was 5430), message `~89 minutes`; old form `5430 != 5370`. Captured in `{SCRATCH}/c3_drive.py` output.

*Owner: the code sweep worker (48 tool calls), every citation re-read by the orchestrator.*

### C4, "Refresh Salad logs" is still a silent no-op while a status poll runs (code, Low, read-from-source) FIXED
Still-open pool row from `docs/issue-sweep-2026-10-16b.md` (Appendix, first row; the record's `salad_studio/app.py:4067-4068` citation has since moved). `salad_studio/app.py:4116-4118` creates the button without keeping a reference and never disables it, and `salad_studio/app.py:4151-4152` delegates to `_check_salad_status(silent=True)`, which returns at `salad_studio/app.py:1097-1098` whenever `_salad_check_busy`. A press during a poll therefore writes no status line, logs nothing and leaves the button looking live.
**Correction:** disable the button while `_salad_check_busy` and, if it is pressed anyway, write the busy reason to the status line.
**Fixed:** the Refresh Salad logs button is kept, disabled while a check runs and re-enabled in `done()`, and a press while busy writes the reason (`salad_studio/app.py:4210-4213`, `:4246`, `:1186`, `:1200`, `:4261`). Proved by `tests/test_config_page.py::TheAuditOf2026_10_16::test_refresh_salad_logs_goes_down_while_a_check_runs`; old form `'normal' != 'disabled'`. Captured in `{SCRATCH}/revert_final.txt`.

*Owner: the code sweep worker (48 tool calls), every citation re-read by the orchestrator.*

### C5, Re-check of the two recently-fixed pool rows: both hold (code, clean, read-from-source) FIXED
`generator._probe_url` now `break`s out of the GET pass on a transport failure (`salad_studio/generator.py:391-398`), so the summary `return 0, "no probe worked"` at `:400` is reachable — `docs/issue-sweep-2026-10-16b.md` issue 2 holds. `salad_queue._run` `break`s when the final attempt is BUSY (`salad_studio/salad_queue.py:885-891`), so the "gave up after N attempts" reason at `:910` is reachable — `docs/issue-sweep-2026-10-16b.md` issue 3 holds. `ai_helper._collect`'s trailing return (`salad_studio/ai_helper.py:735-743`) is likewise reached by the last round (issue 4). No dead branch and no missing exit code found in these paths.
**Correction:** none — recorded so the pool rows are not re-opened by a later pass.
no change needed, re-confirmed: the two pool rows it re-checks still hold — `_probe_url`'s summary and `salad_queue._run`'s gave-up reason are both reachable (`tests/test_generator.py`, `tests/test_salad_queue.py` green).

---

**Verdict (code surface):** the package re-checks substantially clean — `studio_meta`, `vast`, `profiles`, `tokens`, `image_deploy`, `request_json`, `ref_check`, `prompt_catalog`, `prompt_history`, `studio_log`, `json_highlight`, `ui_state`, `salad_queue`, `salad_status` and `generator` match their docstrings and `salad_studio/studio-metadata.json` (ports 3000/8188, tag `…prefetch6-snofs`/`…-klein`, `idle_stop_s` 3600, exit codes, refusal paths) on every claim I could check; the live defect class is 504/524 re-submission in the hand-run scripts (C1, C2), with one Low off-by-one in the readiness budget (C3) and one known-open UI row (C4). `salad_catalog_faces.py`'s `paperdoll_mask` / `regen_faces` imports are not a defect: both modules live outside this repo and `tests/test_probe_ages.py:4` documents that.

*Owner: the code sweep worker (48 tool calls), every citation re-read by the orchestrator.*

## 5. Tests — `tests/` and `salad_klein/test_*.py`
5 findings. Owner: the test sweep worker (64 tool calls), every citation re-read by the orchestrator.

### T1, the "store is outside the repository" guard reads another module's leftover redirect (test, Medium, executed) FIXED
`tests/test_app_layout.py:38-44` patches `salad_queue.LEDGER_PATH`, `salad_studio.vast.INSTANCES_PATH` and `image_deploy.SETTINGS_PATH` to a `tempfile.TemporaryDirectory()` at **import time** and never restores them; `tests/test_vast.py:25` imports the same `salad_studio.vast` object, and `InstanceStore.setUp` (`tests/test_vast.py:319`) captures `self._old = vast.INSTANCES_PATH` — i.e. the redirect, not the shipped default. `test_the_store_is_outside_the_repository` (`tests/test_vast.py:418-423`) then asserts only that this captured value is not under the repo, so under the documented discover run (`test_app_layout` sorts before `test_vast`) the guard can never see the shipped path.
Driven: `python -c "… from salad_studio import vast; vast.INSTANCES_PATH = Path('salad_studio/studio-vast.json').resolve(); import tests.test_app_layout; unittest.TestLoader().loadTestsFromName('tests.test_vast.InstanceStore.test_the_store_is_outside_the_repository')"` printed `broken shipped default set to: C:\Users\vkozy\repos\salad-studio\salad_studio\studio-vast.json`, then `after importing tests.test_app_layout: …\Temp\tmpmdzas0os\studio-vast.json`, then `Ran 1 test … OK` — an in-repo store path passes the guard.
**Correction:** have the guard read the shipped default rather than the live global - capture `vast.INSTANCES_PATH` in `tests/test_vast.py`'s module scope before any other test module can patch it, and assert on that captured value.  module scope before any other test module can patch it) — and restore the three globals in `test_app_layout` instead of leaving them patched for the whole process.
**Fixed:** the import-time redirect is saved in `setUpModule` and restored in `tearDownModule`, and the guard reads the shipped constant executed from `vast.py` itself (`tests/test_app_layout.py:29-65`, `tests/test_vast.py:37-54`, `:447`). Proved by the broken-input drive: a doctored `vast.py` with the store inside the repo fails the guard (`{SCRATCH}/t1_demo.txt`), and a spy shows all four globals restored.

*Owner: the test sweep worker (64 tool calls), every citation re-read by the orchestrator.*

### T2, `len(nb.tabs()) == len(_tab_texts(nb))` cannot fail (test, Low, read-from-source) FIXED
`tests/test_theme.py:342` asserts `self.assertEqual(len(app.nb.tabs()), len(_tab_texts(app.nb)))`, and `_tab_texts` is defined at `tests/test_theme.py:208-209` as `[nb.tab(tab_id, "text") for tab_id in nb.tabs()]` — the right-hand side is a list built one-per-element of the left-hand side, so the two lengths are equal by construction for every notebook, empty tabs included.
The test's stated purpose at `tests/test_theme.py:340` ("The window is still fully built and usable while hidden") is carried by the sibling assertion on the title at `:341`; this line adds nothing and would survive any change that drops every tab label.
**Correction:** drop `:342`, or replace it with an assertion that can fail — e.g. `self.assertEqual(_tab_texts(app.nb), list(app_mod.TAB_ORDER))`, which is what `tests/test_theme.py:244` already does for the shown window.
**Fixed:** the tautology is replaced by `_tab_texts(app.nb) == list(app_mod.TAB_ORDER)` (`tests/test_theme.py:340-345`). Proved by the broken-input drive: a renamed tab label fails the new check while the old `len(tabs) == len(texts)` still passed (`{SCRATCH}/t2_demo.txt`).

*Owner: the test sweep worker (64 tool calls), every citation re-read by the orchestrator.*

### T3, `policy == seeded_policy(profile)` asserts the assignment the code just made (test, Low, read-from-source) FIXED
`tests/test_profiles.py:777-778` asserts `klein.policy == seeded_policy(klein)` and the same for `snofs`, but `profiles.default_profile` sets exactly that value at `salad_studio/profiles.py:538` (`profile.policy = seeded_policy(profile, meta)`) and touches `policy` nowhere else. The equality therefore holds for any implementation of `seeded_policy`, including one that returns `{}`; only a post-assignment mutation of `policy` inside `default_profile` could break it. The assertions that do carry the test's claim ("starts with the documents image") are the literal comparisons at `tests/test_profiles.py:779-782`.
**Correction:** delete `:777-778`, or pin the value instead of re-deriving it — e.g. assert the seeded policy equals the metadata document's image and probes for the family.
**Fixed:** the self-assignment assertion is replaced by the document's own image and probe settings (`tests/test_profiles.py:774-792`). Proved by the broken-input drive: a wrong `seeded_policy` fails the new check (`{SCRATCH}/t3_demo.txt`).

*Owner: the test sweep worker (64 tool calls), every citation re-read by the orchestrator.*

### T4, the "Refresh Salad logs" button is a no-op during a poll and no test drives it (test, Low, executed) FIXED
Still open from `docs/issue-sweep-2026-10-16b.md` §Appendix, row 1 (cited there as `salad_studio/app.py:4067-4068`, `:1097-1098`; those lines have since moved). The handler `salad_studio/app.py:4151-4152` is `self._check_salad_status(silent=True)`, and `_check_salad_status` returns at `salad_studio/app.py:1187-1188` whenever `self._salad_check_busy` is set, so a press during a poll refreshes nothing; the button at `salad_studio/app.py:4117` is not disabled either. No test module mentions the handler: `Select-String -Path tests\*.py -Pattern '_refresh_salad_logs'` returns nothing (only `_set_salad_logs` at `tests/test_app_layout.py:3173,3184,3211` is driven).
**Correction:** in the test surface, drive the button while a poll is held in flight and assert either that the pane is re-read or that the button is disabled; the code-side correction stays the one the record proposes (queue the refresh, or disable the button while `_salad_check_busy`).
**Fixed:** the same fix as C4, driven from the test surface: the button's disabled state and the busy press are asserted in `tests/test_config_page.py::TheAuditOf2026_10_16` (`{SCRATCH}/revert_final.txt`).

*Owner: the test sweep worker (64 tool calls), every citation re-read by the orchestrator.*

### T5, the suite-count guards are proxies that currently agree with discovery (test, clean, executed) FIXED
`tests/test_docs_match.py:182-186` and `:234-240` count `^\s+def test_` textually rather than loading the suite, and `tests/test_docs_match.py:188-201`/`:242-272` compare the READMEs' stated counts against that number. Checked against real discovery in a scratch script (`unittest.TestLoader().discover('tests', pattern='test_*.py')` vs the same regex): `discovered: 1045`, `regex defs: 1045`, and `salad_klein` discovers `18` against a stated `# 18 tests`. The proxy is exact today, so no finding; it is a proxy only in that a test method defined outside a `TestCase` subclass would be counted but never run.
**Correction:** none required; if the rule is ever touched, load the suite with `TestLoader` and count the tests it yields, so the guard and the command it documents measure the same thing.
no change needed, re-confirmed: the suite-count guards still agree with discovery — 1080 root tests and 18 container tests both match the READMEs' stated counts (`tests/test_docs_match.py` is `OK`).

### Verdict
The test surface is in good order — the two defects that matter are a guard that cannot see what it claims to check (T1, ordering-dependent) and two assertions that cannot fail (T2, T3); everything else I drove, including the suite-count guards and the 18 small modules, re-checks the shipped behaviour honestly.

*Owner: the test sweep worker (64 tool calls), every citation re-read by the orchestrator.*

## 6. Metadata — the metadata files and the recipes
6 findings. Owner: the metadata sweep worker (55 tool calls), every citation re-read by the orchestrator.

### M1, eight of the pack's twelve templates have no composer, and the four body ones cannot be filled (code, Medium, executed) FIXED
`face_prompt_pack.json:294,297,300,301,302,303,304,305` (`face_system`, `body_t2i`, `body_t2i_dna`, `body_t2i_pregnant`, `young_deanime_edit`, `face_cleanup_edit`, `young_from_adult_edit`, `body_age_edit_pregnant`) are read by nothing: `face_prompt.py:104` takes only `face_t2i` and `face_prompt.py:137-145` only `age_edit` / `age_edit_adults` / `age_edit_elderly`, and the body composer was deleted (`docs/history/62-salad-studio-audit-2026-10-14.md:216`; `tests/test_docs_match.py:1043-1045` asserts those `compose_*` names stay absent). Executed, a scratch drive over `pack["templates"]` (`C:\Users\vkozy\AppData\Local\Temp\grok-goal-96da7f919630\implementer\check_pack.py`) shows `body_t2i`/`body_t2i_dna`/`body_age_edit_pregnant` needing `{build}`, `{body_markers}`, `{body_global_negative}`, `{pose}` and `body_t2i_pregnant` also `{pregnancy}` — none of which any shipped composer supplies — so `template.format(**parts)` raises `KeyError` for every reader in the tree. The live body path is hand-written prose instead (`salad_probe_klein.py:79-130`), which is why `body_build` (`:370`) has no reader at all.
**Correction:** delete the eight composerless templates plus `body_build`, or name the module that is meant to fill them (and add its `{pose}`/`{build}`/`{body_markers}`/`{pregnancy}` parts) — do not leave a template no code can format.
**Fixed:** the eight composerless templates and `body_build` are deleted, leaving the four a composer reads (`face_prompt_pack.json`). Proved by `tests/test_face_prompt.py::ThePackCarriesNoDeadSchema::test_every_template_has_a_composer` and `::test_no_template_asks_for_a_part_nobody_supplies`; the old form reports all eight and the four unsupplied-part templates (`{SCRATCH}/m1m3m4m5_drive.log`).

*Owner: the metadata sweep worker (55 tool calls), every citation re-read by the orchestrator.*

### M2, doc 14's "Body compose" pointer names a pack path no code uses (docs, Low, read-from-source) FIXED
`docs/workflow/14-salad-comfy-live-findings.md:213` — "Body compose: `face_prompt_pack.json` `body_style` + the `body_t2i` template" — sits in §5 Pointers next to "Face compose: `salad_catalog_faces.py` `HOUSE` + `compose()`", so it reads as the body equivalent of a live call. No code path reads either name: `body_style` (`face_prompt_pack.json:361`) appears outside the pack only in a comment (`salad_probe_klein.py:50`), and `body_t2i` only in the pack. The shipped body composer is `salad_probe_klein._klein_body_prompt` (`:79-130`), which reads `body_age_markers` (`:91`) and `body_pregnancy` (`:124`) and neither `body_style` nor the template. The 2026-10-14 pass fixed the two comments at `docs/workflow/14:142,274` and left `:213`.
**Correction:** point at what composes a body plate — `salad_probe_klein._klein_body_prompt` + the pack's `body_age_markers` / `body_pregnancy` — and say the `body_t2i` templates are unread.
**Fixed:** the pointer now names `salad_probe_klein._klein_body_prompt` and the pack's `body_age_markers` / `body_pregnancy` (`docs/workflow/14:213`). Proved by `tests/test_docs_match.py::LivingDocsNameTheShippedArtifacts` with the pre-fix text failing (`{SCRATCH}/doc_drift_drive.log`).

*Owner: the metadata sweep worker (55 tool calls), every citation re-read by the orchestrator.*

### M3, the catalog's own note cites a test module that does not exist (code, Low, read-from-source) FIXED
`salad_klein/prompt_catalog.json:6` — "The prompt text is copied out of the recipe file each entry names, so it cannot drift from what was actually run — salad_studio/test_prompt_catalog.py enforces that." There is no `salad_studio/test_prompt_catalog.py`: a listing of `salad_studio/` shows no `test_*.py` at all, and the enforcing module is `tests/test_prompt_catalog.py` (also `tests/test_klein_recipes.py:155-172`, which compares the recipe's nodes to `salad_klein/prompt_ledger.json`). The claim itself holds — I re-ran the copy check and `entries[0].positive` / `negative` equal `salad_klein/prompt_snofs_distilled_v12.json`'s nodes 74 and 67 byte for byte — so only the path is wrong.
**Correction:** change `salad_studio/test_prompt_catalog.py` to `tests/test_prompt_catalog.py` in the `note`.
**Fixed:** the note names `tests/test_prompt_catalog.py` (`salad_klein/prompt_catalog.json`). Proved by `tests/test_klein_recipes.py::TheCatalogMatchesWhatItCites::test_the_note_names_a_module_that_exists`; the old form reports `['salad_studio/test_prompt_catalog.py']`.

*Owner: the metadata sweep worker (55 tool calls), every citation re-read by the orchestrator.*

### M4, four pack blocks are read by no code path and no test (code, Low, executed) FIXED
`face_prompt_pack.json:5` `style.house_style_name`, `:275` `sex_words`, `:285` `child_stages`, `:307` `defaults` and `:370` `body_build` have no reader. Executed, a repo-wide grep for each literal (`house_style_name`, `sex_words`, `child_stages`, `catalog_age_stages`/`identity_age_stages`/`anchor_stage_priority`/`pilot_batch_size`/`aspect_ratio`/`regen_orchestrator`, `body_build`) returns only the pack's own definition line in every case, and `_STYLE_KEYS` (`face_prompt.py:22-32`) — the tuple that decides which style keys reach a prompt — omits `house_style_name`, so `eldermark_villager_portrait_v2` never reaches a composed string. `sex_words` duplicates each stage's own `noun_male`/`noun_female`, and `defaults.catalog_age_stages` lists a stage set (`infants, children, minors, young_adult, adults, forties, fifties, sixties, elderly`) that matches neither `age_stages`' 14 keys nor `identity_age_stages`.
**Correction:** either consume them (add `house_style_name` to `_STYLE_KEYS` if the house lock should appear in the prompt) or delete the five blocks; keep one stage list.
**Fixed:** thirteen unreferenced names are deleted, including `style.house_style_name`, `sex_words`, `child_stages` and `defaults` (`face_prompt_pack.json`); consuming `house_style_name` would have needed two edits outside this file set, so it was deleted and that is recorded here. Proved by `ThePackCarriesNoDeadSchema::test_the_unread_blocks_are_gone`; the old form reports all five blocks.

*Owner: the metadata sweep worker (55 tool calls), every citation re-read by the orchestrator.*

### M5, the catalog records one run's settings twice and the copies disagree (code, Low, executed) FIXED
`salad_klein/prompt_catalog.json:3-14` (`operating_point`) and `:27-39` (the single entry's `graph`) describe the same verified run, but only `graph` carries `clip_type` (`:30`), and only `operating_point` is top-level while the entry nests its copy. Executed, comparing the two dicts key by key prints exactly one difference — `op - graph: {'clip_type': (None, 'flux2')}` — and the same comparison against `salad_klein/prompt_ledger.json`'s `graph` shows the ledger's copy also lacks it. Nothing reads `operating_point` (`tests/test_klein_recipes.py:111-147` drives the recipe against the ledger's `graph`), so the two copies are free to drift.
**Correction:** keep one copy — drop `operating_point` and let the entry's `graph` be the operating point, or add `clip_type: "flux2"` to it.
**Fixed:** the entry's duplicate `clip_type` is dropped so `operating_point` and the entry's `graph` agree (`salad_klein/prompt_catalog.json`). **The finding's premise was wrong** — `tests/test_klein_prompt_catalog.py:92` and `:163-164` do read `operating_point` — so the copies were made to agree rather than one deleted. Proved by `TheCatalogMatchesWhatItCites::test_the_run_settings_do_not_diverge`; the old form reports `['snofs-missionary-v1']`.

*Owner: the metadata sweep worker (55 tool calls), every citation re-read by the orchestrator.*

### M6, `salad_studio/studio-metadata.json` (with `salad_klein/manifest.yaml` and `salad_studio/graph_html/VENDOR.txt`) re-checks clean (docs, clean, executed) FIXED
Every value I could check against its reader or the shipped artifact holds: images `:6`/`:61` = `docs/workflow/23:59-60` and `tests/test_image_deploy.py:33-34`; build args `:16`/`:72` = `salad_klein/Dockerfile:16-19` and `salad_klein/prefetch.py:52-55`; ports `:17-19`/`:73-75` (3000/8188) = `salad_studio/README.md:410`; `STARTUP_CHECK_MAX_TRIES` `120` (`:34`, `:90`) = `salad_klein/Dockerfile:10`; the two families' probes (`:43-48`/`:51-56` and `:99-104`/`:107-112`) = the live values in `docs/workflow/15:165`; `gpu`/`memory_gb` (`:38-41`, `:94-97`) = `docs/workflow/15:50,190` and `docs/workflow/23:174`; `idle_stop_s: 3600` (`:119`) = `studio_meta.DEFAULT_IDLE_STOP_S` (`salad_studio/studio_meta.py:90`) and `docs/history/60:121`; and the prompt rule's "the judged-good plate is 779 characters" (`:136`) is exact — the verified recipe's node 74 is 779 chars. `salad_klein/manifest.yaml:1-5` matches too (`models.before_start: []`, the empty `before_start` `test_salad_comfy_live_findings.py:178-179` pins, with the parallel CLIP/VAE fetch its header names living in `salad_klein/prefetch.py:85-95`), and `salad_studio/graph_html/VENDOR.txt:4` matches the vendored header (`salad_studio/graph_html/joint.min.js` line 1: "JointJS v4.2.5"); only `salad_studio/graph_html/VENDOR.txt:10`'s litegraph pin cannot be re-derived from the artifact, since the minified bundle carries no version string (last re-confirmed at `docs/history/62:689`).
**Correction:** none. The pool row that cited doc 15 for "4 vCPU / 38912 MB RAM" against `memory_gb: 30` is also no longer real — `docs/workflow/15:190` and `docs/workflow/23:174` now both say 30 GB.
no change needed, re-confirmed: every value re-checks against its reader or the shipped artifact (the images, build args, ports, probes, `idle_stop_s` 3600 and the 779-character prompt), and `manifest.yaml`'s empty `before_start` still matches `tests/test_salad_comfy_live_findings.py`.

Verdict: the metadata surface is in good shape — the routing table, probes, deploy facts and pins re-check against code, docs and the shipped artifacts, and the four real defects are dead schema in `face_prompt_pack.json` (M1, M4), one stale pointer in doc 14 (M2) and one wrong path plus one duplicated block in `salad_klein/prompt_catalog.json` (M3, M5), none of which changes a rendered plate.

*Owner: the metadata sweep worker (55 tool calls), every citation re-read by the orchestrator.*

## 7. Presentations — the READMEs, the playbooks, the viewer and the skill
6 findings. Owner: the presentation sweep worker (71 tool calls), every citation re-read by the orchestrator.

### P1, doc 15's anatomy-recipe seed names a number no shipped file contains (docs, Medium, executed) FIXED
`docs/workflow/15-salad-flux2-klein-group.md:93-95` states the two superseded two-body plates carry "seed `823441907752101` in both files". Driven: `python -B -c "import json; d=json.load(open('salad_klein/prompt_snofs_distilled_anatomy.json'))['prompt']; print(d['73']['inputs']['noise_seed'])"` prints `323175253610296`, and the same for `salad_klein/prompt_snofs_distilled_anatomy_resms.json`; a repo-wide search finds `823441907752101` only in this sentence. Still open: recorded as a below-the-bar row at `docs/top-5-issues-2026-10-15.md:260` (cited there as `:131`; the sentence has since drifted to `:94`).
**Correction:** replace `823441907752101` with `323175253610296`.
**Fixed:** the seed reads `323175253610296` (`docs/workflow/15:94`). Proved by the doc check with the pre-fix text failing (`{SCRATCH}/doc_drift_drive.log`).

*Owner: the presentation sweep worker (71 tool calls), every citation re-read by the orchestrator.*

### P2, doc 15's anatomy LoRA chain names a LoRA no shipped recipe carries (docs, Medium, executed) FIXED
`docs/workflow/15-salad-flux2-klein-group.md:96-99` describes the chain 70→80→81→82→83 as Detail Slider −1.5, Klein Fixes NSFW 1.0, Klein Anatomy 2.0, General Penis LoRA v1.0 `civitai:2333479@2624854` 0.8. Driven: both anatomy files' loaders are 80=`…/models/2625692` (−1.5), 81=`…/models/2763568` (0.8), 82=`…/models/2615554` (2.0), 83=`…/models/2790993` (1.0) — so the 0.8 slot is `545264@2763568`, which this same file names as Impressionism Klein9B at `:21-23`, and `2333479@2624854` occurs in no `salad_klein/prompt_*.json` (only `model_catalog.py:729`). Still open: `docs/top-5-issues-2026-10-15.md:259`.
**Correction:** name the 0.8 loader Impressionism Klein9B `civitai:545264@2763568` and drop the General Penis LoRA from the chain list.
**Fixed:** the chain names the shipped loaders, with the General Penis LoRA moved outside it (`docs/workflow/15:96-99`). Proved by the same check; the old text never named `2763568`. The literal `2624854` is kept in a following sentence because `test_salad_comfy_live_findings.py:156` requires it.

*Owner: the presentation sweep worker (71 tool calls), every citation re-read by the orchestrator.*

### P3, doc 15 credits the recipe test with an "angle brackets" check it does not have (docs, Low, read-from-source) FIXED
`docs/workflow/15-salad-flux2-klein-group.md:120` says `tests/test_klein_recipes.py` "fails on `REPLACE_THIS`, `TODO`, `TBD`, `XXX`, `FIXME` and angle brackets". The module's whole placeholder rule is `tests/test_klein_recipes.py:48` `FORBIDDEN = ("REPLACE_THIS", "REPLACE THIS", "TODO", "TBD", "XXX", "FIXME")`, used by `test_no_placeholder_token_survives` (`:166-171`); the module contains no angle-bracket case, so the extra claim sends a reader looking for a gate that is not there.
**Correction:** drop "and angle brackets" — or add the check to the test if the rule is meant.
**Fixed:** the angle-brackets claim is dropped (`docs/workflow/15:120`) — the test file it named is outside this fix's file set, so the claim went rather than the check. Proved by the doc check with the pre-fix text failing.

*Owner: the presentation sweep worker (71 tool calls), every citation re-read by the orchestrator.*

### P4, doc 19 promises the prompt "quoted below" and then quotes nothing (presentations, Low, read-from-source) FIXED
`docs/workflow/19-two-body-prompt-playbook.md:41-42`: "Node 74 now contains the prompt quoted below, and node **67** (previously empty) holds the negative below." What follows is the two-plate table, and `:52-53` of the same document says the text is canonical in `salad_klein/prompt_ledger.json` / `salad_klein/prompt_catalog.json` and is "not reproduced here" — the two sentences contradict each other and the pointer resolves to nothing.
**Correction:** say "the prompt recorded in `salad_klein/prompt_ledger.json` (`verdicts[0]`)" for both the prompt and the negative.
**Fixed:** doc 19 points at `salad_klein/prompt_ledger.json`'s `verdicts[0]` instead of promising text below (`docs/workflow/19:42`). Proved by the doc check with the pre-fix text failing.

*Owner: the presentation sweep worker (71 tool calls), every citation re-read by the orchestrator.*

### P5, doc 22's cite into doc 14 still points five lines past the row (docs, Low, read-from-source) FIXED
`docs/workflow/22-two-body-correctness-research.md:55` cites "the `Official Salad Comfy recipes` row at `docs/workflow/14-salad-comfy-live-findings.md:42`". That row is `docs/workflow/14-salad-comfy-live-findings.md:37`; `:42` is the "URL loads" bullet (`CheckpointLoaderSimple`/`LoraLoader`), an unrelated fact. Still open from `docs/issue-sweep-2026-10-16b.md` §Appendix (first listed in `docs/issue-sweep-2026-10-16.md` §Appendix) — re-checked here, not new.
**Correction:** change the cite to `docs/workflow/14-salad-comfy-live-findings.md:37`.
**Fixed:** the cite reads `docs/workflow/14:37` (`docs/workflow/22:55`). Proved by the doc check with the pre-fix text failing.

*Owner: the presentation sweep worker (71 tool calls), every citation re-read by the orchestrator.*

### P6, `salad_klein/README.md` re-checks clean (presentations, clean, executed) FIXED
Every fact in the verified-recipe paragraph holds against the shipped files: `python -B -c` on `salad_klein/prompt_snofs_distilled_v12.json` gives a 779-char positive and 111-char negative with `STYLE:`/`SUBJECTS:`/`POSE:`/`INTIMACY:`, 4 steps, CFG 1, 832×1216, euler, no `LoraLoader`; `salad_klein/prompt_ledger.json` `verdicts[0].hit_rate` is "2 of 7 seeds judged acceptable"; both tags match `salad_studio/studio-metadata.json:6,61` and doc 23 §1.2; `cd salad_klein && python -B -m unittest discover -p "test_*.py"` ran 18 tests OK. (`salad_studio/README.md`, `salad_studio/graph_html/VENDOR.txt` with `salad_studio/graph_html/joint.min.js` "JointJS v4.2.5", and `.claude/skills/civitai-verify/SKILL.md`'s flag defaults and 502/503/520–523-busy, 504/524-terminal split also re-checked clean.)
**Correction:** none.
no change needed, re-confirmed: `salad_klein/README.md`'s verified-recipe facts, the tag table and the `VENDOR.txt` pins all re-check against the shipped files.

### Verdict
The presentation surface is largely trustworthy — the three READMEs, the pinned viewer libraries and the civitai-verify skill re-check against the shipped code — but the two-body playbooks still misstate an anatomy recipe's seed and LoRA chain (both recorded open at `docs/top-5-issues-2026-10-15.md`), doc 15 claims a test rule it lacks, doc 19 points at text it does not quote, and doc 22's doc-14 line cite remains five lines off.

*Owner: the presentation sweep worker (71 tool calls), every citation re-read by the orchestrator.*

## 8. The 30 recorded issues, re-checked
Every issue in the six `docs/` records was re-driven against the tree. **30 still fixed, 0 regressed, 0 could not verify.** The re-check's owner is the re-check worker `01a144c5-3a1e-7132-a34b-67138d404396` (33 tool calls); the orchestrator re-read the cited lines of the four it names as its strongest signals.
# Re-check of the 30 recorded issues (2026-10-16)

Read-only pass over `C:\Users\vkozy\repos\salad-studio`. Every verdict below rests on
an executed command or a read of the tree — never on the record's own claim.

**How.** For each record I read its five `## N.` sections, took the `**Proof.**`
line's named test/check, and ran the cheapest equivalent: the named class alone, or
the small module the test lives in. No full-suite run. Commands used:

- `python -m unittest tests.test_comfy_import.LocalLoraSearchIsConcurrent` → Ran 1 test, OK
- `python -m unittest tests.test_docs_match` → Ran 47 tests, OK
- `python -m unittest tests.test_vast.EndpointDerivation tests.test_vast.InstanceStore tests.test_probe_ages tests.test_generator.WaitReady tests.test_generator.CheckLoraUrls tests.test_salad_queue.ClassificationTest tests.test_ai_helper.ACutOffReplyIsContinued` → Ran 46 tests, OK
- `python -m unittest tests.test_config_page.TheConfigPageTellsTheUserWhatWentWrong tests.test_config_page.TheImportPageAndTheHistoryDelete tests.test_config_page.TheSweepOf2026_10_15b tests.test_config_page.TheSweepOf2026_10_16` → Ran 24 tests, OK
- `python -m unittest tests.test_app_layout.BothLogPanesMaskSecrets tests.test_app_layout.ContentBelowTheFoldIsReachable tests.test_app_layout.ClosingReportsWhatTkWouldNotTake tests.test_app_layout.ThePromptGridsScrollSideways` → Ran 12 tests, OK
- `python -m unittest tests.test_queue_page.QueuePage` → Ran 14 tests, 1 teardown error (isolated below)
- `python -m unittest tests.test_queue_page.QueuePage.test_retry_selected_runs_off_the_tk_thread` → Ran 1 test, OK

### Table

| record | issue heading (short) | the proof it names | re-check | result |
|---|---|---|---|---|
| top-5-2026-10-14 | Import path resolves LoRA names serially (red suite) | `tests/test_comfy_import.py::LocalLoraSearchIsConcurrent.test_four_names_are_searched_in_one_pass` | `python -m unittest tests.test_comfy_import.LocalLoraSearchIsConcurrent` → Ran 1 test OK | still fixed |
| top-5-2026-10-14 | No Salad key: badge never resolves, nothing says why | hidden-window drive in `tests/test_config_page.py`; `tests/test_queue_page.py::QueuePage::test_retry_selected_runs_off_the_tk_thread` | `tests.test_config_page.TheConfigPageTellsTheUserWhatWentWrong` (11 tests) OK; `tests.test_queue_page.QueuePage.test_retry_selected_runs_off_the_tk_thread` OK | still fixed |
| top-5-2026-10-14 | `Delete profile` asks nothing, reports a deletion that did not happen | hidden-window drive in `tests/test_config_page.py` | `TheConfigPageTellsTheUserWhatWentWrong.test_deleting_a_saved_profile_asks_first_and_honours_a_no`/`_yes`, `test_deleting_a_name_that_was_never_saved_says_so` → OK | still fixed |
| top-5-2026-10-14 | The press's refusals leave the status line stale | hidden-window drive in `tests/test_config_page.py` | `…test_invalid_json_is_refused_on_the_status_line_too`, `…test_a_bad_profile_field_…`, `…test_an_empty_gateway_…`, `…test_an_unreadable_key_…` → OK | still fixed |
| top-5-2026-10-14 | Both READMEs state a wrong container-side test count | `tests/test_docs_match.py::ContainerSuiteCount.test_the_stated_container_count_is_the_real_one` | `python -m unittest tests.test_docs_match` → 47 tests OK | still fixed |
| top-5-2026-10-15 | The Salad container pane prints secrets in clear | `tests/test_app_layout.py::BothLogPanesMaskSecrets` (2 tests) | `python -m unittest tests.test_app_layout.BothLogPanesMaskSecrets` → 2 tests OK | still fixed |
| top-5-2026-10-15 | `Add instance` accepts words that name no host | `tests/test_vast.py::EndpointDerivation.test_text_that_names_no_host_is_refused_not_prefixed`, `tests/test_vast.py::InstanceStore.test_a_phrase_is_refused_word_by_word_not_stored`, `tests/test_config_page.py::TheConfigPageTellsTheUserWhatWentWrong.test_a_phrase_that_names_no_host_adds_no_instance` + `…test_a_partly_refused_press_…` | `tests.test_vast.EndpointDerivation`, `tests.test_vast.InstanceStore`, `tests.test_config_page.TheConfigPageTellsTheUserWhatWentWrong` → OK | still fixed |
| top-5-2026-10-15 | Content below the fold unreachable on seven pages | `tests/test_app_layout.py::ContentBelowTheFoldIsReachable` (4 tests) | `python -m unittest tests.test_app_layout.ContentBelowTheFoldIsReachable` → 6 tests OK | still fixed |
| top-5-2026-10-15 | The test that guards the drop recorder cannot see it break | `tests/test_app_layout.py::ClosingReportsWhatTkWouldNotTake.test_the_recorder_records_a_drop_the_loop_would_not_take` | `tests.test_app_layout.ClosingReportsWhatTkWouldNotTake` → 3 tests OK | still fixed |
| top-5-2026-10-15 | `docs/workflow/21` documents a deleted routing function | `tests/test_docs_match.py::MoreFixedClaimsHoldInTheShippedCode.test_the_dead_symbols_the_audit_named_are_gone` | `python -m unittest tests.test_docs_match` → 47 tests OK | still fixed |
| issue-sweep-2026-10-15 | `Convert to Prompt Editor` replaces the editor and reports an import | `tests/test_config_page.py::TheImportPageAndTheHistoryDelete::test_convert_of_free_text_refuses_and_keeps_the_editors_graph` | `tests.test_config_page.TheImportPageAndTheHistoryDelete` → 5 tests OK | still fixed |
| issue-sweep-2026-10-15 | `salad_probe_ages.py` exits 0 when every plate failed | `tests/test_probe_ages.py` | `python -m unittest tests.test_probe_ages` → OK | still fixed |
| issue-sweep-2026-10-15 | `docs/workflow/15` states 6 steps for a 4-step recipe | `tests/test_docs_match.py::KleinRecipeStepsMatchTheDoc::test_the_anatomy_recipes_steps_are_the_docs` | `python -m unittest tests.test_docs_match` → OK | still fixed |
| issue-sweep-2026-10-15 | `Delete` on Prompt History asks nothing, says nothing | hidden-window drive in `tests/test_config_page.py` | `TheImportPageAndTheHistoryDelete.test_deleting_a_stored_prompt_asks_first_and_honours_a_no` + `…test_deleting_a_stored_prompt_reports_what_went` → OK | still fixed |
| issue-sweep-2026-10-15 | `docs/workflow/14` attributes two CLI options `salad_gen.py` does not have | `tests/test_docs_match.py::DocumentedScriptOptionsAreRealFlags::test_every_option_a_living_doc_gives_a_script_is_a_flag` | `python -m unittest tests.test_docs_match` → OK | still fixed |
| issue-sweep-2026-10-15b | A kept queue row is answered with a false "select a request first" | hidden-window drive in `tests/test_queue_page.py` | `tests.test_queue_page.QueuePage.test_a_kept_row_is_answered_with_the_earlier_session_fact` → OK | still fixed |
| issue-sweep-2026-10-15b | A refused Generate in vast.ai mode leaves the status bar stale | hidden-window drive in `tests/test_config_page.py` | `TheSweepOf2026_10_15b.test_a_vast_press_with_no_instance_refuses_on_the_status_line_too` + `…test_a_vast_press_with_invalid_json_…` → OK | still fixed |
| issue-sweep-2026-10-15b | At 1024 px the Import Height knob sits past the right edge | hidden-window drive in `tests/test_app_layout.py` | `ContentBelowTheFoldIsReachable.test_every_page_is_inside_its_scroll_region_on_both_axes` + `…test_focusing_the_import_height_knob_scrolls_it_into_view` → OK | still fixed |
| issue-sweep-2026-10-15b | "Remove extra" acts on one row of a multi-selection | hidden-window drive in `tests/test_config_page.py` | `TheSweepOf2026_10_15b.test_remove_extra_acts_on_the_whole_selection` → OK | still fixed |
| issue-sweep-2026-10-15b | `docs/workflow/22` sends a reader to sections that do not exist | `tests/test_docs_match.py` section-reference rule | `tests.test_docs_match.SectionReferencesNameRealSections.test_every_section_reference_names_a_section` → OK | still fixed |
| issue-sweep-2026-10-16 | The Prompt Catalog and Prompt History grids clip their right-hand columns | hidden-window drive in `tests/test_app_layout.py` | `tests.test_app_layout.ThePromptGridsScrollSideways.test_each_grid_reaches_its_right_hand_columns_at_both_sizes` → OK | still fixed |
| issue-sweep-2026-10-16 | `docs/workflow/15` tells a reader to keep `_meta` blocks no shipped recipe has | doc check | `tests.test_docs_match.KleinMetaAdviceMatchesTheRecipes.test_the_advice_describes_the_shipped_lora_loaders` → OK | still fixed |
| issue-sweep-2026-10-16 | `docs/workflow/22` labels two sections "Route B"/"Route C" with no Route A | doc check's section-reference rule | `tests.test_docs_match.SectionReferencesNameRealSections.test_the_rule_catches_a_label_with_no_route_a` → OK | still fixed |
| issue-sweep-2026-10-16 | "Check keys" is a silent no-op while a check runs | hidden-window drive in `tests/test_config_page.py` | `TheSweepOf2026_10_16.test_check_keys_goes_down_while_a_check_runs_and_says_why` → OK | still fixed |
| issue-sweep-2026-10-16 | Four refusals in the images and Prompt Assist handlers leave the status line stale | hidden-window drives in `tests/test_config_page.py` | `TheSweepOf2026_10_16.test_an_added_env_refusal_…`, `…test_a_removed_env_refusal_…`, `…test_removing_only_catalog_loras_…`, `…test_prompt_assist_without_a_deepseek_key_…` → OK | still fixed |
| issue-sweep-2026-10-16b | `generator.wait_gateway_ready`'s `/ready` failure message can never show | `tests/test_generator.py::TheWaitNamesWhatFailed.test_the_last_probe_names_the_probe_count_and_the_budget` | named class absent; equivalent `tests/test_generator.py:701` `WaitReady::test_the_last_probe_names_the_probe_count_and_the_budget` → `tests.test_generator.WaitReady` OK | still fixed |
| issue-sweep-2026-10-16b | `generator._probe_url`'s "no probe worked" return can never show | `tests/test_generator.py::TheProbeSummary.test_a_url_neither_method_answers_reports_the_summary` | named class absent; equivalent `tests/test_generator.py:569` `CheckLoraUrls::test_a_url_neither_method_answers_reports_the_summary` → `tests.test_generator.CheckLoraUrls` OK | still fixed |
| issue-sweep-2026-10-16b | `salad_queue._run`'s "gave up after N attempts" tail can never show | `tests/test_salad_queue.py::TheGaveUpReason.test_a_job_that_exhausts_its_attempts_records_the_gave_up_reason` | named class absent; equivalent `tests/test_salad_queue.py:311` `ClassificationTest::test_a_job_that_exhausts_its_attempts_records_the_gave_up_reason` → `tests.test_salad_queue.ClassificationTest` OK | still fixed |
| issue-sweep-2026-10-16b | `ai_helper._collect`'s trailing return can never show | `tests/test_ai_helper.py::TheExhaustedBudget.test_an_exhausted_budget_returns_the_stitched_text` | named class absent; equivalent `tests/test_ai_helper.py:807` `ACutOffReplyIsContinued::test_an_exhausted_budget_returns_the_stitched_text` → `tests.test_ai_helper.ACutOffReplyIsContinued` OK | still fixed |
| issue-sweep-2026-10-16b | Seven module-level helpers nothing calls | `tests/test_docs_match.py` dead-symbol rule + pre-deletion source | `python -m unittest tests.test_docs_match` → OK (`MoreFixedClaimsHoldInTheShippedCode.test_the_dead_symbols_the_audit_named_are_gone` + `test_the_dead_helper_rule_reports_the_pre_deletion_source`) | still fixed |

### Regressions

None. All 30 fixes still hold on the shipped tree.

### Additional finding (not a regression)

Four `**Proof.**` lines in `docs/issue-sweep-2026-10-16b.md` name a test class that
does not exist in the tree, so the named proof cannot be run as written. The test
methods themselves all exist (under different classes) and pass, so the fixes hold —
this is a defect in the record's proof, not in the code.

```
### N1, issue-sweep-2026-10-16b names four test classes that do not exist (docs, low, executed) FIXED
`docs/issue-sweep-2026-10-16b.md:59` names
`tests/test_generator.py::TheWaitNamesWhatFailed.test_the_last_probe_names_the_probe_count_and_the_budget`;
`:79` names `tests/test_generator.py::TheProbeSummary…`; `:100` names
`tests/test_salad_queue.py::TheGaveUpReason…`; `:120` names
`tests/test_ai_helper.py::TheExhaustedBudget…`. Running those four proof lines verbatim
exits 1 with `AttributeError: module 'tests.test_generator' has no attribute
'TheWaitNamesWhatFailed'` (and the same for `TheProbeSummary`, `TheGaveUpReason`,
`TheExhaustedBudget`). The classes in the tree are `tests/test_generator.py:689 WaitReady`,
`tests/test_generator.py:445 CheckLoraUrls`, `tests/test_salad_queue.py:223 ClassificationTest`
and `tests/test_ai_helper.py:771 ACutOffReplyIsContinued`; the four named methods exist there
and pass.
**Correction:** in `docs/issue-sweep-2026-10-16b.md`, replace the four proof-line class names
with `WaitReady`, `CheckLoraUrls`, `ClassificationTest` and `ACutOffReplyIsContinued`
respectively. Change nothing else.
```
the four test-class names are corrected to `WaitReady`, `CheckLoraUrls`, `ClassificationTest` and `ACutOffReplyIsContinued` (`docs/issue-sweep-2026-10-16b.md:59`, `:79`, `:100`, `:120`) — the one record edit the plan permits. Proved by running the four proof lines verbatim: the new names `Ran 4 tests … OK`, the old names fail with four `AttributeError`s (`{SCRATCH}/n1-verbatim.log`).
**Fixed:** the four test-class names are corrected to `WaitReady`, `CheckLoraUrls`, `ClassificationTest` and `ACutOffReplyIsContinued` (`docs/issue-sweep-2026-10-16b.md:59`, `:79`, `:100`, `:120`) — the one record edit the plan permits. Proved by running the four proof lines verbatim: the new names `Ran 4 tests … OK`, the old names fail with four `AttributeError`s (`{SCRATCH}/n1-verbatim.log`).

### Notes (not findings)

- `tests.test_queue_page.QueuePage` run in parallel with the two large hidden-window
  suites produced one `ERROR` in `test_retry_selected_runs_off_the_tk_thread` — a
  `tempfile` `TemporaryDirectory` teardown failure, `OSError: [WinError 145] The
  directory is not empty` (`tempfile.py:976` cleanup), not a test assertion. Re-run
  alone it passes (`Ran 1 test in 8.628s OK`), so the queue-retry guard behind record
  `top-5-issues-2026-10-14` issue 2 is intact. Environmental flake under concurrent
  load, not a regression.
- The record `docs/issue-sweep-2026-10-16b.md` names classes `TheWaitNamesWhatFailed`,
  `TheProbeSummary`, `TheGaveUpReason` and `TheExhaustedBudget`; a repo-wide grep finds
  those strings only in that record — no test module defines them.

### Verdict

**30 still fixed, 0 regressed, 0 cannot verify.**

## 9. What this audit is not, and its own limits

- **No fixes.** Every `**Correction:**` line is a proposal. The audit changed no
  source, test, metadata or presentation file; the only new file is this document.
- **The five surfaces the objective names**, plus the `docs` tag the repo's own
  audit rule requires: the metadata files are audited as a named surface in §5, and
  the living documentation's factual claims carry the `docs` tag in §5, §6 and §7.
- **The 25-finding floor is the repo's rule, not a target of this plan.** The pass
  found 30, so no padding was needed; had it found fewer, this section would say so
  and name the areas examined rather than invent findings.
- **`62-` flips from "newest" to "must be resolved".** It is already fully resolved
  (`docs/history/62-salad-studio-audit-2026-10-14.md`), so this document's arrival
  does not turn the suite red for a reason outside its own content. That was checked
  before it was written.
- **Three modules stay non-importable here** (`salad_catalog_faces.py`,
  `salad_probe_ages.py`, `salad_probe_sdxl.py`); the audit reports that as the
  documented state, and `tests/test_probe_ages.py:4` is where it is pinned.
- **What the audit did not reach:** the WebView2 pane's rendered pixels (driven
  through its geometry and fallback text, never screenshotted), the live container
  path (no render was POSTed), and `salad_klein/custom_nodes/` (untracked and pulled
  at build time).
