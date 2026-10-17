# Issue records, 2026-10-14 to 2026-10-16

This is the one record of the studio's issue passes. It consolidates the six dated
documents that stood in `docs/`, so that each issue has one home:

| the six files this consolidates | section in this file |
|---|---|
| `docs/top-5-issues-2026-10-14.md` | The five highest-severity issues, 2026-10-14 |
| `docs/top-5-issues-2026-10-15.md` | The five highest-severity new issues, 2026-10-15 |
| `docs/issue-sweep-2026-10-15.md` | The issue sweep, 2026-10-15 |
| `docs/issue-sweep-2026-10-15b.md` | The issue sweep, 2026-10-15 (fourth pass) |
| `docs/issue-sweep-2026-10-16.md` | The issue sweep, 2026-10-16 |
| `docs/issue-sweep-2026-10-16b.md` | The next five issues, 2026-10-16 |

Each section carries its source document whole: every heading, every body, every
`**Fixed:**` resolution and every correction, and every appendix row with its
severity verdict. The text is the record as written; a reference in one record to
another of the six is now a link to that record's section here, and no other
wording was changed. The six files listed above no longer exist as separate
documents.


## The five highest-severity issues, 2026-10-14

_Consolidated from `docs/top-5-issues-2026-10-14.md`._

A fresh pass over the code, the tests, the UI/UX and the docs found the issues
below, and this pass fixed each one. Every issue names its artifact and line, what
is wrong, its severity, the drive that shows it, and the fix with the proof that
keeps it fixed.

### How this list was made

Four read-only area passes (code; tests and stated counts; UI/UX on the real
window; docs) reported 27 candidates between them. Every claim below was re-driven
against the tree by the orchestrator before it entered this record; the passes
found several claims that did not survive that check, and those are not here. The
candidates that were real but ranked below the five are in the appendix, so nothing
found is hidden.

**Ranking basis, in order of weight:**

1. **The repo's own gate fails.** The test suite is the gate every other claim is
   measured against; a red suite is the most severe state this tree can be in.
2. **The app tells the user something false, or loses their work.** A wrong word
   in a status line or badge costs a user a session of guessing; an unconfirmed
   destructive action costs them data.
3. **A documented promise is unmet, or a stated figure is wrong.** The manual and
   the READMEs are the contract with the reader.

Severity is the highest rule that applies. Ties inside a rule are broken by how
many surfaces the defect reaches.

---

### 1. The suite is red: the Import path resolves LoRA names with one live Civitai search after another (High)

**Artifacts.** `salad_studio/comfy_import.py:748-767` (the caller),
`salad_studio/comfy_import.py:652-659` (the pool it defeats),
`tests/test_import_civitai_image.py:101-102` (what the test stubs),
`tests/test_import_civitai_image.py:113-119` (the 30 s deadline).

**What is wrong.** `resolve_prompt_loras` is built to resolve every name it is
handed in one `ThreadPoolExecutor` pass (`:652`, `max_workers=min(8, len(unique))`).
`resolve_local_lora_nodes` calls it **once per LoRA node** with a single-element
list (`:762-767`), so `len(unique)` is always 1 and the pool runs one Civitai
search at a time, in sequence, inside the press path before the request is
enqueued. Measured with a 0.3 s stub on every search: four names cost 1.21 s of
wall time and four serial calls, where one parallel pass costs ~0.30 s. Against
the live Civitai API the same four names cost 12.5-15.7 s each.

The consequence is the red suite. `tests/test_import_civitai_image.py` stubs the
Civitai *image* fetch and the Salad POST transport but leaves the LoRA-name
searches live, then waits 30 s for the POST. When Civitai answers slowly the
deadline expires first:

```
python -m unittest tests.test_import_civitai_image -v
test_generate_posts_a_copy_with_no_pack_types_and_the_prompt ... ResourceWarning: Implicitly cleaning up <HTTPError 401: 'Unauthorized'>
AssertionError: None is not true : Generate never POSTed
Ran 3 tests in 200.846s
FAILED (failures=1)
```

**Fix.** Resolve the names in one pass: collect every `lora_name` input that needs
a search, run them through a single `resolve_prompt_loras` call (so the pool is
actually parallel), then write each node's result back by name. Make the test
hermetic at the same time: stub the LoRA search in both `setUp`s the way it already
stubs the image fetch, so the suite cannot depend on Civitai's latency.

**Proof.** `tests/test_comfy_import.py` gains
`LocalLoraSearchIsConcurrent.test_four_names_are_searched_in_one_pass`: it drives
the shipped `comfy_import.resolve_local_lora_nodes` on a four-`LoraLoader` graph
with a search stub that sleeps 0.3 s and requires the wall time to be under three
delays. It passes on the shipped function and fails on the pre-fix function taken
from git (`7.03s not less than 0.9s`). Driven directly, four names cost 1.82 s
before and 0.33 s after, with the same four searches and the same `missing` list.
`tests/test_import_civitai_image.py` runs green with the searches stubbed
(`Ran 3 tests … OK`, was `Ran 3 tests in 200.846s … FAILED`).

---

### 2. With no Salad key the badge never resolves and nothing says why (High)

**Artifacts.** `salad_studio/app.py:934-939` (the swallowed read),
`salad_studio/tokens.py:186-189` (the sentence that names the fix and is thrown
away), `salad_studio/app.py:251-254` (the status line).

**What is wrong.** One `except Exception: snaps = {}` wraps the API-key read *and*
every probe. With no key saved, `resolve_salad_key()` raises
`FileNotFoundError("Salad API key is empty. Save it on the Tokens tab (<path>).")`
— the sentence that names the cause and the fix — and the handler discards it.
The badge then sits on its `…` placeholder and the status line stays `Ready`:

```
key on disk        : (none)
the discarded text : 'Salad API key is empty. Save it on the Tokens tab (...studio-tokens.json).'
badge              : '…'
status line        : 'Ready'
any surface names the key: False
```

A user in this state sees a badge that never settles, a status line that claims
`Ready`, and nothing anywhere — Logs included — that mentions a key. The only
place the app says "no key saved" is the Tokens tab, which they have no reason to
open.

**Fix.** Read the key on the main thread, separately from the probes, and put the
key error where the user looks: the badge reads a word of its own (`No key`) and
the Logs carry the sentence that names the Tokens tab and the file. The status line
is deliberately left alone — it carries events (`retrying`, a refusal), and a
standing condition that rewrote it would erase the last thing the user did. The log
line is written once per distinct message, because the poll runs every 15 s.

**Proof.** The hidden-window drive in `tests/test_config_page.py` builds the app
with no key, runs the status check, and requires the badge to read `No key` and the
Logs to name the key and the Tokens tab — while the status line keeps whatever
event it was carrying. It fails on the old handler (the badge stays on its
placeholder and nothing names the key), and
`tests/test_queue_page.py::QueuePage::test_retry_selected_runs_off_the_tk_thread`
guards the other half: the key report must not erase a live `retrying` message.

---

### 3. `Delete profile` asks nothing and reports a deletion that did not happen (High)

**Artifact.** `salad_studio/app.py:4853-4872`.

**What is wrong.** Two defects in one handler.

- **No confirmation.** The handler deletes the saved profile and switches the
  active one on a single click, with no dialog, no undo, and no status line before
  the fact. The page's other destructive controls do ask: Prompt Catalog's Delete
  (`:2950-2962`) and Clean gallery (`:4901-4905`).
- **A false claim.** `self.status.set(f"Deleted {name}")` and the `warn` log line
  run whether or not anything was deleted. A typed name that was never saved
  reports `Deleted no-such-profile`:

```
saved profiles     : ['klein', 'klein5090'] -> ['klein5090']
dialogs asked      : []
status line        : 'Deleted klein'
unsaved name       : status line 'Deleted no-such-profile'
```

**Fix.** Ask first (the same question the Catalog's Delete asks), and report what
actually happened: name the profile that was deleted, and say so when the name is
not a saved profile.

**Proof.** The hidden-window drive in `tests/test_config_page.py`: with a saved
profile, the delete asks and the answer is honoured (a `No` leaves the profile
alone); with a name that was never saved, the status line and the Logs say no such
profile exists instead of claiming a deletion. Both assertions fail on the old
handler.

---

### 4. The press's refusals leave the status line stale (Medium)

**Artifacts.** `salad_studio/app.py:4934-4938` (invalid JSON),
`salad_studio/app.py:4976-4978` (unreadable key), `salad_studio/app.py:4980-4983`
(empty gateway), against `salad_studio/app.py:5001-5004` (the stopped-badge
refusal, which does set it).

**What is wrong.** The manual promises the refusal reaches the status line
(`salad_studio/README.md:362-366`), and the stopped-badge path honours it. The
other refusals report through a dialog (and, for two of them, the Logs) and never
touch the status line, so it keeps whatever it said before — `Generating…`,
`Ready`, or the last refusal's sentence:

```
invalid JSON    : status 'SENTINEL'  dialog "Prompt Editor JSON is invalid: ..."
empty gateway   : status 'SENTINEL'  dialog "Gateway URL is empty."
unreadable key  : status 'SENTINEL'  dialog "Cannot read Salad API key: ..."
```

The surfaces disagree, and the one that persists after the dialog is dismissed is
the one that is wrong.

**Fix.** Every refusal the press handler can make writes the status line, with the
same cause the dialog carries. The pass fixed all five paths in the handler, not
only the three measured above: the invalid-JSON refusal, the form-field refusal
(`_profile_from_form`'s `ValueError`), the routing refusal (`plan_route`), the
unreadable key, and the empty gateway.

**Proof.** The hidden-window drive in `tests/test_config_page.py` presses Generate
in each of four states and requires the status line to carry the refusal, after
the dialog is dismissed. Each fails on the old handler with the status line still
reading `SENTINEL`, and passes now.

---

### 5. Both READMEs state a container-side test count that is wrong, and no check can see it (Medium)

**Artifacts.** `README.md:33`, `salad_studio/README.md:549`,
`tests/test_docs_match.py:176` and `:183-189`.

**What is wrong.** The Quick start block states `# 16 tests` for
`cd salad_klein && python -m unittest discover -p "test_*.py"`. The suite has
**18** test methods (`test_prefetch.py` 17, `test_hf_gated_access.py` 1).

The claim has survived two audits because nothing can read it. `_real_count()`
globs `HERE.glob("test_*.py")`, where `HERE` is `tests/`, so it counts only the
root suite; the loop reads only `ROOT_README` and `MANUAL`; and
`re.search(r"#\s*(\d+)\s+tests", text)` takes only the **first** match in each
file, which is the root count. The container-side line is invisible, and
`salad_klein/README.md` is read by no test at all.

**Fix.** Correct both figures, and leave the check behind: a test that counts
`salad_klein/test_*.py` and asserts every stated container-side count — the check
fails on the old text and catches the claim drifting again.

**Proof.** `tests/test_docs_match.py` gains
`ContainerSuiteCount.test_the_stated_container_count_is_the_real_one`; it fails
with the old `# 16 tests` and passes with `# 18 tests`.

---

### Appendix: verified candidates below the bar

Real, re-driven, and ranked below the five. They are recorded so the pass is
auditable, and they are **not** part of the five. The one marked *fixed* was
corrected by this pass as well, because it sits in the same block as issue 5 and
cost nothing to correct.

| Site | What is wrong | Severity |
|---|---|---|
| `docs/workflow/21-klein-image-handoff.md:113` | Names `profiles.route_payload(payload, all_profiles)` as the live routing API; the function was deleted and `tests/test_docs_match.py:446` asserts it is gone. A reader following §2 writes a call that raises `AttributeError`. | Medium |
| `README.md:31`, `salad_studio/README.md:547` | *fixed* — stated `~14-18 min` for the root suite; the measured full run is 29.3 min (1758 s). Corrected to `~15-30 min`. A runtime has no reliable check, so this is a correction without one. | Medium |
| `salad_studio/app.py:252-254` | The status line has no `wraplength`, so a 215-char refusal sentence is clipped at a 1024 px window width and hides the action at its tail (`…Start it in the Salad console, then Generate again.`). | Medium |
| `salad_studio/generator.py:180-185` | The trailing failure block after the readiness loop cannot run (the `:179` raise fires first), so the message naming the probe count and the minutes is never shown. | Medium |
| `docs/workflow/15-salad-flux2-klein-group.md:119` | Says the anatomy recipe is `6 steps`; `salad_klein/prompt_snofs_distilled_anatomy.json`'s `Flux2Scheduler` is 4. | Medium |
| `docs/workflow/14-salad-comfy-live-findings.md:56` | Attributes optional `ckpt_name` / `lora_name` CLI options to `salad_gen.py`; they are `build_graph()` parameters, and the script's flags are `--prompt --negative --steps --seed --width --height --out --timeout --wait-ready`. | Medium |
| `docs/workflow/18-sdxl-migration-brief.md:129-130` | Cites `doc 15 §261, §280, §338, §441, §519`; doc 15 has no numbered sections, and the startup account is at `doc 15:356`. | Low |
| `docs/workflow/18-sdxl-migration-brief.md:266-267` | Says `test_generator.py` has `21 total`; it has 26. | Low |
| `docs/workflow/18-sdxl-migration-brief.md:209`, `:271` | Two sections numbered `3.3`. | Low |
| `docs/workflow/17-klein-two-body-anatomy-research.md:411` | Attributes per-position failure reports to the v1.4 LoRA page, while `:663-668` in the same file records that the page reports none. | Low |
| `salad_studio/theme.py:441`, `salad_studio/json_highlight.py:82`, `salad_studio/graph_view.py:1063` | Three module-level helpers with no caller and no reader. | Low |
| `salad_studio/ai_helper.py:743` | A `return` after a loop whose last round always raises. | Low |
| `salad_probe_ages.py:146` | Exits 0 when every plate failed; its siblings return 1 or 3. | Low |
| `tests/test_docs_match.py:189` | `self.assertIsNot(match, None)` repeats the `assertIsNotNone` three lines above: an assertion that cannot fail. | Low |
| `tests/test_docs_match.py:231`, `:493` | `AUDIT` is assigned twice, byte-identical. | Low |
| `tests/test_docs_match.py:2` | The docstring says "Three checks"; the module holds 11 classes and 37 tests. | Low |

---

## The five highest-severity new issues, 2026-10-15

_Consolidated from `docs/top-5-issues-2026-10-15.md`._

A fresh pass over the code, the tests, the UI/UX and the docs found the issues
below, none of which is one of the five recorded in
[`top-5-issues-2026-10-14.md`](#the-five-highest-severity-issues-2026-10-14). This pass fixed each
one, and each fix adds or repairs a capability rather than removing one.

### How this list was made

Four read-only area passes reported 31 candidates between them (code 7, tests 8,
UI/UX 8, docs 8). Every claim below was re-driven against the tree by the
orchestrator before it entered this record; the candidates that were real but
ranked below the five are in the appendix, so nothing found is hidden.

**Ranking basis, in order of weight:**

1. **The app exposes something it must not, persists what it did not mean to, or
   the suite cannot see a shipped break.** A credential in a log the user pastes
   into a report, an instance list filled with words the user never meant as
   addresses, and a gate that passes while the code under it is broken are the
   three ways this repo can be quietly wrong.
2. **A control or documented capability the user cannot reach.** The goal is that
   nothing the user could do before is gone; content below the fold with no way to
   scroll to it is exactly that.
3. **A documented claim a reader acts on and fails.**

Severity is the highest rule that applies; ties inside a rule are broken by how
many surfaces the defect reaches.

---

### 1. The Salad container pane prints secrets in clear (High)

**Artifacts.** `salad_studio/app.py:3803-3808` (`_set_salad_logs`),
`salad_studio/app.py:3835-3837` (`log`, which redacts),
`salad_studio/app.py:3813-3821` (the cached redaction list).

**What is wrong.** `log()` runs every line through `studio_log.redact` with the
token list. `_set_salad_logs` — which writes the container's own stdout into the
Salad pane, from `snaps[pid]["log_lines"]` in `_check_salad_status` — inserts the
text verbatim. The same value is therefore masked in one pane and shown in the
other, in an app whose manual says secrets stay out of the log:

```
the secret is 'hf_SUPERSECRETVALUE1234'
Studio pane : REDACTED
Salad pane  : IN CLEAR
Salad pane content: 'container stdout:\nHF_TOKEN=hf_SUPERSECRETVALUE1234\nready'
```

The redaction list is also cached until a token is saved (`:3819`), so a token that
arrives any other way is logged in clear too:

```
a token written after the cache was filled: IN CLEAR
```

**Fix.** Redact in `_set_salad_logs` the same way `log()` does, and clear the
cached list whenever a token is written, not only in one save path.

**Proof.** `tests/test_app_layout.py::BothLogPanesMaskSecrets` has two tests: a
container log line carrying a token is masked in both panes
(`test_a_container_log_line_is_masked_in_both_panes`), and a token written after
the cache is warm is masked too
(`test_a_token_written_after_the_cache_is_warm_is_masked_too`). Both fail on the
old handlers (`AssertionError: 'hf_FIRSTSECRETVALUE1234' unexpectedly found in … :
the Salad pane leaked the token`) and pass now.

---

### 2. `Add instance` accepts words that name no host, so one typed phrase becomes five instances reported as success (High)

**Artifacts.** `salad_studio/vast.py:144-160` (`normalize_endpoint`),
`salad_studio/app.py:1732-1754` (`_on_vast_add`).

**What is wrong.** `normalize_endpoint` prefixes `http://` to anything, so a word
that names no host comes back as one, and the page splits the box on whitespace:

```
normalize_endpoint('not') = 'http://not'
normalize_endpoint('not an address at all') = 'http://not an address at all'
normalize_endpoint('comfy-local') = 'http://comfy-local'

after pressing Add instance with a phrase: 5 rows ->
  ['http://not', 'http://an', 'http://address', 'http://at', 'http://all']
status line: 'added 5 instance(s): http://not, http://an, http://address, http://at, http://all'
dialog shown: False
```

The instance list is persisted with five unusable endpoints and the page reports
the five as a success. The function's own docstring says `"" means the text names
no host` — it does not honour that.

**Fix.** Make `normalize_endpoint` honour its docstring: with no scheme, the text
must look like a host (a dot or a port); with an explicit scheme it is taken as
typed. `http://comfy-local` still works, so no address a user could previously
reach becomes unreachable. `_on_vast_add` then reports the refusal it already has
words for, and names what it did and did not add.

**Proof.** Four tests, each failing on the old function and passing now:
`tests/test_vast.py::EndpointDerivation.test_text_that_names_no_host_is_refused_not_prefixed`,
`tests/test_vast.py::InstanceStore.test_a_phrase_is_refused_word_by_word_not_stored`,
`tests/test_config_page.py::TheConfigPageTellsTheUserWhatWentWrong.test_a_phrase_that_names_no_host_adds_no_instance`
(no rows, nothing persisted, a refusal on the dialog, the status line and the
Logs) and `…test_a_partly_refused_press_names_what_was_added_and_what_was_not`.
Driven directly, the old form returns `'http://not'` where the shipped function
returns `''`, and the page went from five rows to none.

---

### 3. Content below the fold is unreachable on seven of the eleven pages (High)

**Artifacts.** `salad_studio/app.py:1422-1488` (the Tokens page and its siblings),
against `salad_studio/app.py:431-438` (the Config page, the only one that scrolls
by design).

**What is wrong.** Only Config, Prompt Catalog, Prompt History and Queue have a
scrollbar. At a 1366×728 window the notebook is 476 px tall and seven pages are
taller than that, with nothing to scroll them:

```
window 1366x728: the notebook is 476 px tall
  Prompt Settings  needs   516 px  scrollbar=False
  Tokens           needs   751 px  scrollbar=False
  LoRAs            needs   700 px  scrollbar=False
  Prompt Editor    needs   488 px  scrollbar=False
  Prompt Assist    needs   811 px  scrollbar=False
  Import           needs   899 px  scrollbar=False
  Logs             needs   546 px  scrollbar=False
pages whose content exceeds the notebook with no scrollbar:
  Prompt Settings, Tokens, LoRAs, Prompt Editor, Prompt Assist, Import, Logs
```

On the Tokens page that hides the Vast.ai key box and the **Check keys** bar —
while the Vast.ai section tells the user to save that key on the Tokens tab. The
wheel does not help either: it is bound to the Config canvas only
(`salad_studio/app.py:554-562`), and the Config canvas does not follow the keyboard
(31 of 65 tab stops land off-screen), which is the same defect seen from the
keyboard.

**Fix.** A shared scrollable-page helper (the canvas + scrollbar pattern Config
already uses) applied to the pages whose content can exceed the viewport, so every
control is reachable by mouse and by wheel. No control, label or page is renamed or
removed.

**Proof.** `tests/test_app_layout.py::ContentBelowTheFoldIsReachable` has four
tests: every page at 1366×728 either fits or has its own scroll canvas with a
scroll region covering the body (`test_every_page_fits_or_scrolls_at_1366x728`),
the Tokens page scrolls to the bottom so the Vast.ai key box and the **Check keys**
bar are on screen (`test_the_tokens_page_reaches_the_vast_key_box_and_check_keys_bar`),
the wheel scrolls the page the pointer is on and no other
(`test_the_wheel_scrolls_the_page_the_pointer_is_on`), and a control that takes
focus scrolls its page into view
(`test_a_control_that_takes_focus_scrolls_its_page_into_view`). All four error on
the old layout (there is no scroll canvas) and pass now; the drive in
`uiux.log` reports `every page either fits or scrolls (unreachable: [])`.

---

### 4. The test that guards the drop recorder cannot see it break (High)

**Artifacts.** `tests/test_app_layout.py:3055`
(`test_a_dropped_callback_is_reported_when_the_window_closes`),
`salad_studio/app.py:834` and `:852` (the shipped recorder).

**What is wrong.** The test fabricates the entry it then asserts on:

```python
    def test_a_dropped_callback_is_reported_when_the_window_closes(self) -> None:
        self.app._dropped_afters.append("after(0): the main thread is not in the Tk loop")
        log = self._close_and_read()
        self.assertIn("dropped", log, ...)
```

So it proves the *reporter* works and never touches the recorder — the shipped
`_later` / `_later_idle` `except RuntimeError` path that the previous pass added so
a worker's handoff cannot vanish silently. Driven with the recorder broken at
runtime (`_later` and `_later_idle` swallowing the `RuntimeError` without
recording), the test still passes:

```
  test_a_dropped_callback_is_reported_when_the_window_closes
    shipped recorder: PASS
    broken recorder : PASS
```

**Fix.** Drive the shipped recorder: make a real `after` fail (a worker thread
scheduling while the main thread is not in the loop, or a window that is being
torn down) and require the drop to be recorded and then reported. Keep the
existing reporter assertion.

**Proof.** `tests/test_app_layout.py::ClosingReportsWhatTkWouldNotTake.test_the_recorder_records_a_drop_the_loop_would_not_take`
drives a real worker thread calling the shipped `_later`/`_later_idle` while the
main thread is out of the loop, and requires `_dropped_afters` to hold both
entries and the close handler to report them. With the recorder broken it fails
(`AssertionError: 0 != 2 : both refused callbacks must be recorded: []`) while the
old fabricating test still passes, which is the defect.

---

### 5. `docs/workflow/21` documents a routing function that was deleted (Medium)

**Artifacts.** `docs/workflow/21-klein-image-handoff.md:113`,
`tests/test_docs_match.py:520` (which asserts it is gone),
`salad_studio/profiles.py` (the shipped API).

**What is wrong.** The handoff's "How routing decides" block lists four calls a
reader can make. One of them does not exist:

```
110 studio_meta.family_for_unet(unet_name, doc)  -> the family whose unets/markers match
111 profiles.plan_route(payload, form_profile, all_profiles)
112                                             -> (Route | None, refusal reason)
113 profiles.route_payload(payload, all_profiles)
114                                             -> (group name, profile) for that family
```

`hasattr(profiles, "route_payload")` is `False`; the shipped routing entry point is
`profiles.plan_route` alone. A reader who follows the block writes a call that
raises `AttributeError`, and the doc check cannot see it because it only asserts
the symbol is gone, not that the document stops naming it.

**Fix.** Drop the dead call from the block, and leave the check behind: the doc
check asserts the document does not name `route_payload` either, so the claim
cannot come back.

**Proof.** `tests/test_docs_match.py` gains `LIVING_DOCS` and the rule
`route_payload_mentions(paths)`, asserted inside
`MoreFixedClaimsHoldInTheShippedCode.test_the_dead_symbols_the_audit_named_are_gone`
next to the check that the symbol is gone from the module. Driven with the pre-fix
text it reports `['…/old-doc-21.md:113']` and the test fails; against the shipped
living docs it reports `[]` and the test passes.

---

### Appendix: verified candidates below the bar

Real, re-driven, ranked below the five, and **not** part of the five.

| Site | What is wrong | Severity |
|---|---|---|
| `salad_studio/app.py:5176`, `:5181` | `_on_generate_vast`'s refusals never write `self.status`, though its docstring says it "reports its outcome the way the Salad path does" and the Salad path does. A separate handler from the previous pass's issue 4, with the same class of gap. | Medium |
| `salad_studio/app.py:4066-4082` | "Remove extra" acts on `sel[0]` of a multi-selection while the neighbouring "Verify" loops over all selected, and the status names only the row it took. | Medium |
| `salad_studio/app.py:1505-1508` | "Check keys" is a silent no-op while a check is running, and the button is never disabled — reachable because entering the Tokens tab starts a check itself. | Medium |
| `salad_studio/app.py:3380` | "Convert" reports `Imported Civitai workflow to Prompt Editor` when the generation-data box holds free text and no workflow was pasted. | Low |
| `salad_studio/app.py:2599-2606` | Prompt Assist's "no DeepSeek key" refusal is the only return in `_start_helper_call` that does not write the status line. | Low |
| `salad_studio/generator.py:180-185` | The trailing `/ready` failure block is unreachable, so the message naming the probe count and the minutes is never shown; the in-loop raise at `:179` fires instead. | Low |
| `salad_studio/salad_queue.py:905-908` | The "gave up after N attempts" tail of `_run` is unreachable (`max_attempts` is clamped ≥1). | Low |
| `salad_studio/comfy_import.py:2443-2445` | `convert_comfy_graph` never reads `meta_text`, `wf_raw` or `knobs`, though its caller passes all three, so the Import page's "set to override" knobs are dropped on the Comfy path. | Low |
| `salad_studio/ai_helper.py:743` | Unreachable trailing `return` in `_collect`. | Low |
| `salad_probe_ages.py:146` | `main()` returns 0 unconditionally, so a run where every plate failed exits 0; `salad_probe_klein.py:428` returns `1 if fails else 0`. | Medium |
| `salad_studio/theme.py:441`, `json_highlight.py:82`, `graph_view.py:1063` | Three module-level helpers with no caller and no reader. | Low |
| `tests/test_app_layout.py:2412`, `tests/test_config_page.py:1235` | Two tests drive the refusal path without stubbing `snapshot_gateway`, so they reach the live Salad API with a fake key. | Medium |
| `tests/test_config_page.py:1030`, `:1108` | `app.gen_queue.idle_stop_s = 3600` writes an attribute nothing reads (`SaladQueue` stores `_idle_stop_s`; the reader is `idle_timeout_s()`), so the tests' intent is not applied. | Medium |
| `tests/test_app_layout.py:1477`, `:2923-2932`, `:3028-3037` | Three window classes clobber the store paths with no `addCleanup`, and `_TempPaths` then saves the clobbered value, so the leak persists process-wide. | Medium |
| `salad_studio/graph_view.py:1363`, `:1382` | `GraphPane._soon` and its `destroy` override ship with no test. | Medium |
| `salad_studio/prompt_history.py:320` | The "`ts` matches no row → None" rule is documented and no test passes `ts`. | Medium |
| `docs/workflow/15-salad-flux2-klein-group.md:119`, `:129` | Says the anatomy recipe is "6 steps"; the shipped `prompt_snofs_distilled_anatomy.json`'s `Flux2Scheduler` is 4. | Medium |
| `docs/workflow/15-salad-flux2-klein-group.md:139-143` | Maps node 81 to the NSFW fix and 83 to a penis LoRA; the shipped JSON has node 81 = `2763568` (Impressionism 0.8) and 83 = `2790993`. | Medium |
| `docs/workflow/15-salad-flux2-klein-group.md:131` | Seed `823441907752101`; both anatomy files use `323175253610296`. | Medium |
| `docs/workflow/15-salad-flux2-klein-group.md:495` | "4 vCPU / 38912 MB RAM"; `studio-metadata.json` says `memory_gb: 30`. | Low |
| `docs/workflow/14-salad-comfy-live-findings.md:56` | Attributes optional `ckpt_name` / `lora_name` CLI options to `salad_gen.py`; they are `build_graph()` parameters. | Medium |
| `docs/workflow/16-salad-studio-prompt-graph.md:128-129` | "no `layout_xy` fallback"; `layout_xy` is defined at `graph_view.py:747` and called twice. | Low |
| `docs/workflow/18-sdxl-migration-brief.md:119-120` | Cites `doc 15 §261, §280, §338, §441, §519`; doc 15 has no numbered sections. | Low |
| `docs/workflow/15-salad-flux2-klein-group.md:3-8` | The dated banner says `prefetch5` is pushed and GET shows `prefetch4` while the same file, doc 21, doc 23 and the metadata document say `prefetch6`. Known and deliberately deferred: `docs/history/59:159` (D7) decided that rewriting a dated note would falsify the record. | Low, deferred |

---

## The issue sweep, 2026-10-15

_Consolidated from `docs/issue-sweep-2026-10-15.md`._

A fresh sweep of the code, the tests, the UI/UX and the docs found the five issues
below. None is one of the five in [`top-5-issues-2026-10-14.md`](#the-five-highest-severity-issues-2026-10-14) or the five in
[`top-5-issues-2026-10-15.md`](#the-five-highest-severity-new-issues-2026-10-15). Four of them are items those two records listed
*below the bar* and did not fix; this pass re-drove each one before promoting it,
and names where it was first noted.

### How this list was made

Four area readers swept code, tests, UI/UX and docs, each told the two earlier
records' below-the-bar lists so they would not present an old observation as a new
discovery. The UI/UX and docs readers returned; the code and tests readers ran for
an hour without producing a deliverable, so they were stopped and their areas'
candidates were re-driven by the orchestrator instead. Every claim below was driven
against the tree here; the drives are in `{SCRATCH}/redrive.log` and
`{SCRATCH}/redrive2.log`.

**Ranking basis, in order of weight:**

1. **The app destroys or falsifies the user's own work** — a button that replaces
   what the user wrote and reports success.
2. **A command or a stated figure a reader acts on and fails** — a false exit code,
   a wrong step count, an option that does not exist.
3. **A destructive action with no confirmation, or a surface that keeps a stale
   claim.**

---

### 1. `Convert to Prompt Editor` replaces the editor and reports an import that did not happen (High)

**Artifacts.** `salad_studio/app.py:3274-3276` (the button),
`salad_studio/app.py:3522` (`_on_import_civitai`), `:3543`, `:3545`.

**What is wrong.** With the Comfy workflow box empty and free text in the
generation-data box, the handler overwrites the Prompt Editor's JSON with a
fabricated default flux-2-klein graph, copies the free text into the Positive box,
and reports an import. The user's own graph is gone:

```
the editor still holds the user's graph : False      (the drive wrote seed 424242)
status line                             : 'Imported Civitai workflow to Prompt Editor'
dialogs                                 : []
log tail                                : ['[OK] imported Civitai paste  13 nodes · no LoRA · 1024×768 · 40 steps · cfg 1 · euler · flux2']
```

**Fix.** Refuse when there is no workflow to convert (the page already has the
words for a bad paste), and never replace the editor on a refusal.

**Proof.** The hidden-window drive in `tests/test_config_page.py` writes a graph
with a distinctive seed, presses Convert with free text in the metadata box and an
empty workflow box, and requires the editor to still hold that seed and the status
line to carry a refusal. It fails on the old handler (the seed is gone and the
status line claims an import).

**Resolution.** No change was needed: the guard the pass that wrote this record
added holds. Re-driven on the shipped tree, the drive's graph (`seed: 424242`)
survives Convert and the status line reads `Refused: Nothing to convert. Paste a
Comfy workflow JSON and/or Civitai generation data (prompt + Steps/CFG, or
Sampler/Seed/Model).`
`tests/test_config_page.py::TheImportPageAndTheHistoryDelete::test_convert_of_free_text_refuses_and_keeps_the_editors_graph`
passes on the shipped handler and fails against the handler rebuilt from the
shipped source with the guard taken out (the editor then holds the fabricated
graph). Captured in `{SCRATCH}/artifacts.log` and `{SCRATCH}/issues.log`.

---

### 2. `salad_probe_ages.py` exits 0 when every plate failed (Medium)

**Artifact.** `salad_probe_ages.py:146` (`return 0`), against
`salad_probe_klein.py:428` (`return 1 if fails else 0`) and
`salad_probe_sdxl.py:174` (`return 3`).

**What is wrong.** `main()` prints each job's result and returns 0 whatever
happened, so a run where all 26 plates failed reports success to any caller that
chains it:

```
   145             print(fut.result(), flush=True)
   146     return 0
sibling salad_probe_klein.py: return 1 if fails else 0
sibling salad_probe_sdxl.py: return 3
```

**Fix.** Count the results that start with `fail ` and return 1 when any did — the
same contract the sibling probe uses. This *adds* a signal; nothing is removed.

**Proof.** `tests/test_probe_ages.py` drives `salad_probe_ages.main()` with the
plate function stubbed to fail and requires a non-zero return, then with it
succeeding and requires 0. The first fails on the old `return 0`.

**Resolution.** No change was needed: `main()` now ends `return 1 if fails else 0`
with `fails` counting every result that starts with `fail `. Re-driven, the shipped
file's tail reads that line and the drive reports it. `tests/test_probe_ages.py`
passes on the shipped `main` and fails against `main` rebuilt from the shipped
source with `return 0` restored. Captured in `{SCRATCH}/artifacts.log` and
`{SCRATCH}/issues.log`.

---

### 3. `docs/workflow/15` states 6 steps for a 4-step recipe (Medium)

**Artifacts.** `docs/workflow/15-salad-flux2-klein-group.md:117`,
`salad_klein/prompt_snofs_distilled_anatomy.json` (the `Flux2Scheduler` node).

**What is wrong.** The recipe table says the anatomy recipe is `(euler, 6 steps)`;
the shipped file's scheduler is 4. A reader copying the recipe renders at the wrong
step count:

```
doc 15:117: `salad_klein/prompt_snofs_distilled_anatomy.json` (euler, 6 steps)
the shipped file: node 62 Flux2Scheduler steps=4
```

**Fix.** State 4, and leave the check behind: the doc check asserts doc 15's stated
step count equals the shipped recipe's `Flux2Scheduler` steps, so the figure cannot
drift again.

**Proof.** `tests/test_docs_match.py` gains the assertion; it fails on the old text
and passes on the new.

**Resolution.** No change was needed: doc 15 now states `(euler, 4 steps)` and the
shipped `salad_klein/prompt_snofs_distilled_anatomy.json`'s one `Flux2Scheduler`
reads `steps: 4`. Re-driven, the doc's stated count and the file's agree.
`tests/test_docs_match.py::KleinRecipeStepsMatchTheDoc::test_the_anatomy_recipes_steps_are_the_docs`
passes on the shipped text and fails on the pre-fix `(euler, 6 steps)` — the rule is
also driven against a scratch copy of that text so its teeth are seen, not assumed.
Captured in `{SCRATCH}/artifacts.log` and `{SCRATCH}/issues.log`.

---

### 4. `Delete` on the Prompt History page asks nothing and says nothing (Medium)

**Artifact.** `salad_studio/app.py:3674-3681`, the button at `:3585`.

**What is wrong.** The handler removes a stored prompt and its thumbnail with no
confirmation and without writing the status line, while the page's neighbours ask
first — the Catalog's Delete and the profile Delete both call `askyesno` (driven:
both `True`):

```
3674     def _delete_prompt_history(self) -> None:
3675         idx = self._selected_history_index()
3676         if idx is None:
3677             messagebox.showinfo("Salad Studio", "Select a prompt to delete.")
3678             return
3679         prompt_history.remove_at(idx)
3680         self._refresh_prompt_history()
3681         self.log("info", f"deleted prompt history #{idx}")
```

**Fix.** Ask first, the way the Catalog and the profile do, and report what was
deleted on the status line as well as in the Logs.

**Proof.** The hidden-window drive in `tests/test_config_page.py` seeds a prompt,
selects it, and requires the delete to ask and to honour a No; a second assertion
requires the status line to name what was deleted. Both fail on the old handler.

**Resolution.** No change was needed: `_delete_prompt_history` now calls
`messagebox.askyesno` naming the entry, sets `Kept prompt history #<n>` on a No and
`Deleted prompt history #<n>: <preview>` on a Yes, as well as logging. Re-driven,
the shipped handler asks and reports.
`tests/test_config_page.py::TheImportPageAndTheHistoryDelete` (its ask/No and
report/Yes tests) passes on the shipped handler and fails against the handler
rebuilt from the shipped source with the ask and the status line taken out (no
dialog is raised and the status line is untouched). Captured in
`{SCRATCH}/artifacts.log` and `{SCRATCH}/issues.log`.

---

### 5. `docs/workflow/14` attributes two CLI options to `salad_gen.py` that it does not have (Medium)

**Artifacts.** `docs/workflow/14-salad-comfy-live-findings.md:56`,
`salad_gen.py` (its argument parser and `build_graph`).

**What is wrong.** The tools table gives `salad_gen.py` "optional `ckpt_name` /
`lora_name`" in a column whose neighbouring rows name real CLI flags
(`--generate`, `--ignore-pause`, `--prefix`, `--ckpt`, `--lora`). Those two are
`build_graph()` keyword parameters, and the script rejects them as arguments:

```
doc 14:56: | `salad_gen.py` | `POST /prompt` Flux graph; optional `ckpt_name` / `lora_name` |
salad_gen flags: ['--height', '--negative', '--out', '--prompt', '--seed', '--steps', '--timeout', '--wait-ready', '--width']
salad_gen.py: error: unrecognized arguments: --ckpt_name x
```

**Fix.** Say what the script accepts (its `--…` flags) and name `ckpt_name` /
`lora_name` as `build_graph` parameters, and leave the check behind: the doc check
asserts every `--flag` a living document attributes to a shipped script exists in
that script's parser.

**Proof.** `tests/test_docs_match.py` gains the assertion; it fails on the old text
and passes on the new.

**Resolution.** No change was needed: doc 14's `salad_gen.py` row now names the
script's real flags and says `ckpt_name` / `lora_name` are `flux_payload()`
parameters rather than flags. Re-driven, the row's flags and `salad_gen.py`'s parser
agree, and `python salad_gen.py --ckpt_name x` still reports `unrecognized
arguments`. `tests/test_docs_match.py::DocumentedScriptOptionsAreRealFlags::test_every_option_a_living_doc_gives_a_script_is_a_flag`
passes on the shipped text and fails on the pre-fix row, reporting
`salad_gen.py has no ckpt_name` and `… no lora_name`; the rule is also driven
against a scratch copy of that row so its teeth are seen. Captured in
`{SCRATCH}/artifacts.log` and `{SCRATCH}/issues.log`.

---

### Appendix: verified candidates below the five

| Site | What is wrong | Severity |
|---|---|---|
| `salad_studio/app.py:5360-5387` | `_on_generate_vast`'s refusals never write `self.status` (the Salad sibling sets it 62 times), so the status line keeps `Generating…`. First noted below the bar in [`top-5-issues-2026-10-15.md`](#the-five-highest-severity-new-issues-2026-10-15). | Medium |
| `salad_studio/app.py:3822`, `:3872-3883` | A queue row kept from an earlier session (key `kept-<id>`) answers Cancel and Retry with "select a request first". | Medium |
| `salad_studio/app.py:4264` vs `:4219` | "Remove extra" acts on `sel[0]` of a multi-selection while "Verify" loops over all. First noted below the bar in [`top-5-issues-2026-10-15.md`](#the-five-highest-severity-new-issues-2026-10-15). | Medium |
| `docs/workflow/22:60` | The pointer names three homes (doc 23 §1.1/§1.3, doc 18 §3.1) that do not hold the fact; the enumeration it supported was cut by the previous pass. Home: doc 14:44. | Medium |
| `docs/workflow/15:201-206` | The `_meta` advice says "keep the `_meta` blocks when you edit these files", but no shipped Klein recipe carries `_meta` on a `LoraLoader`. | Medium |
| `salad_studio/app.py:441-489` | The scrollable-page helper sets no `xscrollcommand` and `_reveal` moves on Y only, so a control can sit past the right edge at ≤1024 px (`Add instance` 94 px, `Swap selected` 285 px). | Medium |
| `salad_studio/app.py` "Check keys" | A second press while a check runs is a silent no-op and the button is never disabled. | Low |
| `salad_studio/app.py:2599-2606` | Prompt Assist's "no DeepSeek key" refusal is the only return in `_start_helper_call` that skips the status line. | Low |
| `salad_studio/generator.py:180-185` | The trailing `/ready` failure block is unreachable, so the message naming the probe count and the minutes never shows. | Low |
| `salad_studio/salad_queue.py:905-908` | The "gave up after N attempts" tail is unreachable. | Low |
| `salad_studio/ai_helper.py:743` | An unreachable trailing `return`. | Low |
| `salad_studio/theme.py:441`, `json_highlight.py:82`, `graph_view.py:1063` | Three module-level helpers with no caller. | Low |
| `docs/workflow/17:202`, `:290` | Reference `doc 19 §4`, which no longer exists (doc 19 runs §3 → §5). | Low |
| `docs/workflow/23:9`, `:291` | Reference `doc 15 §0–6` and `doc 15 §4`, which no longer exist. | Low |
| `docs/workflow/15:234` | "downloads five files in parallel" — five is the `KLEIN_UNET_SET=all` set; both live tags pass explicit sets. | Low |

---

## The issue sweep, 2026-10-15 (fourth pass)

_Consolidated from `docs/issue-sweep-2026-10-15b.md`._

A fresh sweep of the code, the tests, the UI/UX and the docs found the five issues
below. None is one of the fifteen in [`top-5-issues-2026-10-14.md`](#the-five-highest-severity-issues-2026-10-14),
[`top-5-issues-2026-10-15.md`](#the-five-highest-severity-new-issues-2026-10-15) or [`issue-sweep-2026-10-15.md`](#the-issue-sweep-2026-10-15); four are items those
records listed *below the bar* and did not fix, re-driven here before promotion,
with the place they were first noted named in each section.

### How this list was made

Three area readers swept code and tests, UI/UX, and docs, each told the fifteen
already-recorded issues and the 15-row appendix of [`issue-sweep-2026-10-15.md`](#the-issue-sweep-2026-10-15) as
the documented pool. Their claims were re-driven against the tree by the
orchestrator before they entered this record. The three pool rows that are no
longer real are named in the appendix below so the next pass need not re-derive
them.

**Ranking basis, in order of weight:**

1. **The app answers a user's action with something false.** A row the user can
   see and select, answered with "select a request first", is the worst state this
   UI can be in.
2. **A refusal leaves a surface lying.** The status line is the surface that
   outlives the dialog.
3. **Content a user cannot reach, or an action that does less than it says.**
4. **A document that sends a reader to a section that does not exist.**

---

### 1. A queue row kept from an earlier session is answered with a false "select a request first" (High)

**Artifacts.** `salad_studio/app.py:3883` (`f"kept-{rid}"`, the row key),
`:3935-3941` (`int(selection[0])`), `:3946`, `:3962`.

**What is wrong.** The Queue page keeps finished records for four hours, and a row
restored from an earlier session is keyed `kept-<id>`. Cancel and Retry read the
selection as an integer, so both refuse a row the user has visibly selected:

```
  restarted window keys: ['kept-1']      selection: ('kept-1',)
  Cancel on kept-1 -> 'Queue: select a request first'
  Retry  on kept-1 -> 'Queue: select a request first'
```

A live finished row in the same tree answers correctly ("…has already been sent, so
it cannot be cancelled"), which is what makes the kept row stand out. First noted:
[`docs/issue-sweep-2026-10-15.md`](#the-issue-sweep-2026-10-15) §Appendix row 2.

**Fix.** Read the id off the row's own first cell rather than parsing the key, and
answer a kept row with the fact that its request finished in an earlier session.

**Proof.** The hidden-window drive in `tests/test_queue_page.py` restores a kept
row, selects it and presses Cancel and Retry, requiring both to answer with the
earlier-session fact and not the selection refusal; it fails on the old handler.

---

### 2. A refused Generate in vast.ai mode leaves the status bar claiming the last success (Medium)

**Artifacts.** `salad_studio/app.py:5435-5439` (the invalid-JSON refusal) and
`:5440-5448` (the no-instance refusal), against the Salad sibling at `:5247-5251`.

**What is wrong.** `_on_generate_vast`'s two refusals report through a dialog and
the Logs and never write `self.status`, so the status line keeps whatever the last
successful render wrote:

```
  no-instance: status = 'Wrote C:\plates\stale.png'
  no-instance: dialogs = [('info', 'No vast.ai instance is selected. …')]
  bad-json   : status = 'Wrote C:\plates\stale.png'
  SALAD sibling bad-json: status = 'Refused: the Prompt Editor JSON is invalid'
```

The Salad path states the rule in a comment ("Every refusal writes the status line
as well as the dialog … a stale 'Generating…' beside a refused press is the surface
that lies"). First noted: [`docs/issue-sweep-2026-10-15.md`](#the-issue-sweep-2026-10-15) §Appendix row 1.

**Fix.** Both refusals write the status line with the cause the dialog carries, the
way the Salad sibling does.

**Proof.** The hidden-window drive in `tests/test_config_page.py` sets vast.ai mode,
presses Generate with no instance selected and with invalid JSON, and requires the
status line to carry the refusal; both fail on the old handler.

---

### 3. At 1024 px the Import page's Height knob sits past the right edge and nothing scrolls sideways (Medium)

**Artifacts.** `salad_studio/app.py:441-489` (the scrollable-page helper: only
`yscrollcommand`), `:535-561` (`_reveal` moves on Y only), `:3227-3238` (five
unweighted Label+Entry pairs in one row).

**What is wrong.** Every page scrolls vertically and none scrolls horizontally, so
at a 1024 px window the Import page's own content is wider than its canvas and the
right-hand controls are unreachable:

```
--- 1024x720 ---  'Config': canvas_w=827 scrollregion=(0,0,827,2721) xscroll='' (content wants 1257px)
                  'Import': PAST right by 96px: 'PY_VAR86' (x=809)   <- the Height Entry
--- 900x700  ---  'Import': PAST right by 220px: 'PY_VAR86'; PAST right by 102px: 'Height'
                  'LoRAs': CLIPPED 42px of 124px wanted: 'Verify unverified'
```

First noted: [`docs/issue-sweep-2026-10-15.md`](#the-issue-sweep-2026-10-15) §Appendix row 6.

**Fix.** Give the helper a horizontal scrollbar and make the reveal move on both
axes, so a control that takes focus is brought into view whichever way it is off.

**Proof.** The hidden-window drive in `tests/test_app_layout.py` measures every page
at 1024×720 and 900×700 and requires each control to be inside its canvas's scroll
region on both axes, then focuses the Height knob and requires the canvas to reveal
it; it fails on the old helper.

---

### 4. "Remove extra" acts on one row of a multi-selection while "Verify" acts on all (Medium)

**Artifacts.** `salad_studio/app.py:4320-4335` (`lid = sel[0]` at `:4325`) against
`:4273-4300` (`for lid in sel:` at `:4280`); the two buttons are side by side at
`:2462` and `:2468`.

**What is wrong.** Two LoRAs selected, "Remove extra" removes the first and reports
the singular:

```
  selection size: 2
  Remove extra with 2 selected -> 24 -> 23; status='Removed civitai:90001@90001'
  still present: ['civitai:90002@90002']
```

The neighbouring "Verify" loops over the whole selection, so the two buttons
disagree about what a selection means. First noted:
[`docs/issue-sweep-2026-10-15.md`](#the-issue-sweep-2026-10-15) §Appendix row 3.

**Fix.** Loop over the whole selection and report the count, as Verify does.

**Proof.** The hidden-window drive in `tests/test_config_page.py` selects two extra
LoRAs, presses Remove extra, and requires both gone and the status line to name the
count; it fails on the old handler.

---

### 5. `docs/workflow/22` sends a reader to sections that do not exist (Medium)

**Artifacts.** `docs/workflow/22-two-body-correctness-research.md:84` (`(…, §1.3)`),
`:255` (`the binding ones are §1.1 and §6.3`).

**What is wrong.** Doc 22's headings are `## 1`, `## 3`–`## 8`; it has no `§2`, no
`§1.x` and no `§6.x`, so both references point at nothing. The first was left stale
by an earlier pass's cut (the section it named was deleted), and the second names
sub-sections that were never there.

**Fix.** Re-point both at the sections that hold the facts, and leave the check
behind: the doc check asserts every `§N`/`§N.M` a living document names exists as a
heading in the file it names.

**Proof.** `tests/test_docs_match.py` gains that check; it fails on the old text and
passes on the new.

---

### Appendix: verified candidates below the five, and pool rows that are no longer real

| Site | What is wrong | Severity |
|---|---|---|
| `docs/workflow/15:3-8` | The dated status banner says `prefetch5` is pushed and GET shows `prefetch4` while the same file, doc 21 and the metadata document say `prefetch6`. **Deliberately deferred**: `docs/history/59:159` (D7) decided rewriting a dated note would falsify the record, and the previous pass rejected the prune row that would have. | Low, deferred |
| `docs/workflow/18:119-120` | Cites `doc 15 §261, §280, §338, §441, §519`; doc 15 has no numbered sections (the 25-minute-startup fact is at 15:212-216). | Medium |
| `docs/workflow/17:202`, `:288` | Reference `doc 19 §4`; doc 19 runs §3 → §5. | Low |
| `docs/workflow/15:150` | "Keep the `_meta.title` / `_meta.base` blocks on every `LoraLoader`" — no shipped Klein recipe carries `_meta` on a `LoraLoader`. | Low |
| `salad_studio/app.py:2757-2772` | Prompt Assist's no-DeepSeek-key refusal is one of two returns in `_start_helper_call` that skip the status line. | Low |
| `salad_studio/app.py:1630`, `:1650-1653` | "Check keys" is a silent no-op while a check runs and the button is never disabled. | Low |
| `salad_studio/generator.py:180-185` | The trailing `/ready` failure block is unreachable (traced), so the message naming the probe count and the minutes never shows. | Low |
| `salad_studio/generator.py:391` | `return 0, "no probe worked"` is unreachable (traced). | Low |
| `salad_studio/salad_queue.py:903-906` | The "gave up after N attempts" tail is unreachable (traced). | Low |
| `salad_studio/ai_helper.py:743` | An unreachable trailing `return` (traced). | Low |
| `salad_studio/theme.py:441`, `json_highlight.py:82`, `graph_view.py:1063` | Three module-level helpers with no caller (repo-wide scan: one occurrence each). | Low |
| `salad_studio/graph_view.py:820`, `:1476`, `:1520`, `:1536` | Four dead canvas-drawing helpers; the fallback draws no cards. | Low |
| `salad_studio/app.py:2291-2292` | `_on_image_add_env`'s refusal also leaves the status stale (same class as issue 2, found while driving it). | Low |

Pool rows re-driven here and found **no longer real**, so they are not re-reported:
`docs/workflow/22:60`'s pointer now names doc 14:42 and doc 23 §1, both of which hold
the fact; `docs/workflow/23:9-10` and `:282` now name section titles that all exist
in doc 15; and doc 15's "downloads five files in parallel" is gone.

---

## The issue sweep, 2026-10-16

_Consolidated from `docs/issue-sweep-2026-10-16.md`._

A fresh sweep of the code, the tests, the UI/UX and the docs found the five issues
below. None is one of the twenty in [`top-5-issues-2026-10-14.md`](#the-five-highest-severity-issues-2026-10-14),
[`top-5-issues-2026-10-15.md`](#the-five-highest-severity-new-issues-2026-10-15), [`issue-sweep-2026-10-15.md`](#the-issue-sweep-2026-10-15) or
[`issue-sweep-2026-10-15b.md`](#the-issue-sweep-2026-10-15-fourth-pass); three are items those records listed *below the bar*
and did not fix, re-driven here before promotion, with the place each was first
noted named in its section.

### How this list was made

Three area readers swept code and tests, UI/UX, and docs, each told the twenty
already-recorded issues and the 13-row appendix of [`issue-sweep-2026-10-15b.md`](#the-issue-sweep-2026-10-15-fourth-pass) as
the documented pool. Their claims were re-driven against the tree by the
orchestrator before they entered this record. Two pool rows turned out to be **no
longer real** and are named in the appendix so the next pass need not re-derive
them; the deliberately deferred doc 15 banner was left deferred.

**Ranking basis, in order of weight:**

1. **A user cannot read what the page is showing.** A grid whose right-hand columns
   are off-screen with no way to scroll them.
2. **A document tells a reader to do something the shipped files contradict**, or
   sends them to a section the document does not have.
3. **A control that looks live does nothing**, or a refusal leaves a surface lying.

---

### 1. The Prompt Catalog and Prompt History grids clip their right-hand columns, with no horizontal scrollbar (Medium)

**Artifacts.** `salad_studio/app.py:3009-3027` (the Catalog tree, 1250 px of
columns, vertical scrollbar only), `:3622-3643` (the History tree, 56 + 1100 px,
same), `tests/test_app_layout.py:3571-3573` (the layout guard skips a page with no
scroll canvas, so neither tree is measured).

**What is wrong.** Both pages are plain `ttk.Frame(self.nb, padding=10)` and bypass
`_scrollable_page`, so their trees get a vertical scrollbar and no horizontal one.
Driven with the trees settled:

```
--- 1366x728 ---
  Prompt Catalog   tree_w= 1149  xview_span=0.916  clipped ~105 px
  Prompt History   tree_w= 1149  xview_span=0.990  clipped ~ 11 px
--- 1024x720 ---
  Prompt Catalog   tree_w=  807  xview_span=0.642  clipped ~449 px
  Prompt History   tree_w=  807  xview_span=0.695  clipped ~355 px
```

`xscroll=''` on both. At 1024×720 the Catalog's **Graph** column is entirely
off-screen. Honest limit: the columns are user-resizable, so dragging
**Description** narrower reveals **Graph** — friction rather than a wall, which is
why this is Medium and not High.

**Fix.** Give both trees a horizontal scrollbar (the columns keep their widths and
the user's drag still works), so nothing is unreachable at any window width.

**Proof.** The hidden-window drive in `tests/test_app_layout.py` measures both
trees' `xview` span at 1366×728 and 1024×720 and requires the full column set to be
reachable; it fails on the old layout (span 0.642 with no x-scrollbar).

---

### 2. `docs/workflow/15` tells a reader to keep `_meta` blocks that no shipped recipe has (Medium)

**Artifacts.** `docs/workflow/15-salad-flux2-klein-group.md:127` ("Keep the
`_meta.title` / `_meta.base` blocks on every `LoraLoader`"),
`salad_klein/prompt_*.json`, `docs/workflow/21-klein-image-handoff.md` §5.

**What is wrong.** Parsing every shipped Klein recipe finds 14 `LoraLoader` nodes
and **0** carrying `_meta`, while doc 21 §5 says a `LoraLoader` without one is
classified **foreign**. The advice therefore describes a state the tree does not
have and, followed literally, would make the reader's own recipes look foreign.
First noted: [`docs/issue-sweep-2026-10-15b.md`](#the-issue-sweep-2026-10-15-fourth-pass) §Appendix (its `:150` line cite has
since drifted to `:127`).

**Fix.** Say what is true: a `_meta` block is added by the Studio when it writes a
recipe, the shipped files carry none, and the rule is to keep it **if** the node has
one rather than to require it.

**Proof.** The doc check asserts every `LoraLoader` in a shipped recipe that carries
`_meta` is described, and that the sentence no longer claims the blocks are
universal; it fails on the old text and passes on the new.

---

### 3. `docs/workflow/22` labels two of its own sections "Route B" and "Route C" with no Route A left (Medium)

**Artifacts.** `docs/workflow/22-two-body-correctness-research.md:50`
(`## 3. Route B …`), `:147` (`## 4. Route C …`), `:218-222`
(`**A head-to-head of the three routes**`).

**What is wrong.** The document's headings are `## 1`, `## 3`–`## 8`; the Route A
section and its `## 2` were cut by an earlier pass, so "Route B", "Route C" and "the
three routes" name a framing that no longer exists. A reader looks for Route A and
cannot tell what B and C are relative to.

**Fix.** Name the sections by what they hold (the SDXL/Illustrious route and the 3D
route) and say the third route in the comparison is the current one.

**Proof.** The doc check's section-reference rule gains the label case; it fails on
the old text and passes on the new.

---

### 4. "Check keys" is a silent no-op while a check runs, and the button is never disabled (Medium)

**Artifacts.** `salad_studio/app.py:1652` (the button, never touched again),
`:1673-1675` (`if self._token_probe_busy: return`), `:1184` (opening the Tokens tab
starts a check, so the busy window is reachable without pressing anything).

**What is wrong.** A press during a check returns with no status line, no Log, no
dialog, and the button still looks enabled:

```
  busy            : True
  button state    : 'normal'
  status after a 2nd press: 'SENTINEL-2'
```

First noted: [`docs/issue-sweep-2026-10-15b.md`](#the-issue-sweep-2026-10-15-fourth-pass) §Appendix.

**Fix.** Disable the button while a check runs and say so on the status line if it
is pressed anyway (the busy return names the running check).

**Proof.** The hidden-window drive in `tests/test_config_page.py` starts a check
with a stubbed slow probe and requires the button to be `disabled` while busy and
the status line to carry the reason on a press; it fails on the old handler.

---

### 5. Four refusals in the images and Prompt Assist handlers leave the status line stale (Low)

**Artifacts.** `salad_studio/app.py:2312-2314` (`_on_image_add_env`),
`:2324-2333` (`_on_image_remove_env`'s two refusals), `:4394-4399`
("Remove selected" with only catalog rows), `:2785-2794` (Prompt Assist's no-key
refusal).

**What is wrong.** Each reports through a dialog or the reply box and returns
without writing `self.status`, so the status line keeps the last success — the class
the vast.ai refusals had before this pass fixed them:

```
  add env refused   status: 'SENTINEL-3'   dialogs: [('Salad Studio', 'Name is required.')]
  remove refused    status: 'SENTINEL-LORA'  dialogs: [… only extras added here can be removed.]
  Prompt Assist     status: 'SENTINEL-1'   helper_state: 'No DeepSeek key. Save one on the Tokens tab'
```

First noted: [`docs/issue-sweep-2026-10-15b.md`](#the-issue-sweep-2026-10-15-fourth-pass) §Appendix (row 6 for the first; the
others are the same class, found while re-driving it).

**Fix.** Each refusal writes the status line with the sentence the dialog or the
reply box carries.

**Proof.** The hidden-window drives in `tests/test_config_page.py` press each of the
four refusals and require the status line to carry the cause; all four fail on the
old handlers.

---

### Appendix: verified candidates below the five, and pool rows no longer real

| Site | What is wrong | Severity |
|---|---|---|
| `salad_studio/generator.py:180-185` | The trailing `/ready` failure block is unreachable (traced: every final-iteration path returns or raises), so the message naming the probe count and the minutes never shows. | Low |
| `salad_studio/generator.py:391` | `return 0, "no probe worked"` is unreachable (the GET pass always returns). | Low |
| `salad_studio/salad_queue.py:903-906` | The "gave up after N attempts" tail is unreachable (`next_action` never returns RETRY on the last attempt). | Low |
| `salad_studio/ai_helper.py:743` | An unreachable trailing `return` (the last round always returns or raises). | Low |
| `salad_studio/theme.py:441`, `json_highlight.py:82`, `graph_view.py:820`, `:1063`, `:1476`, `:1520`, `:1536` | Seven module-level helpers with no caller and no reader (a repo-wide scan finds one occurrence each). | Low |
| `salad_studio/app.py:4067-4068`, `:1097-1098` | "Refresh Salad logs" is a silent no-op during a poll, the same class as issue 4. | Low |
| `docs/workflow/22:55` | Cites a line into doc 14 that has moved; the fact's home is the same table's row above. | Low |
| `docs/workflow/17:109`, `:312`, `:401`, `docs/workflow/19:150` | References like "doc 21 §6.2 / §6.7" name list items, not headings; the section-reference rule skips them because the prose names the document rather than a section of the file it sits in. | Low |
| `docs/workflow/19` has no `## 4.`, `docs/workflow/22` no `## 2.`, `docs/workflow/14` a `## 4b.` with no `## 4.` | Any pointer to those numbers is born dead; no live pointer names one today. | Low |
| `docs/workflow/15:3-8` | The dated banner says `prefetch5` is pushed and GET shows `prefetch4` while the file, doc 21, doc 23 and the metadata document say `prefetch6`. **Deliberately deferred** at `docs/history/59:159` (D7): rewriting a dated note would falsify the record. It stays deferred. | Low, deferred |

Pool rows re-driven here and found **no longer real**, so they are not re-reported:
`docs/workflow/17`'s "dead `doc 19 §4` references" (no such reference exists; doc
17's doc-19 references at `:70`, `:199` and `:283` all resolve) and
`docs/workflow/18:119-120`'s dead `doc 15 §…` references (the title reference
resolves to `15:166`, and the fact is at `15:168`). Both were fixed by the
2026-10-15b pass.

---

## The next five issues, 2026-10-16

_Consolidated from `docs/issue-sweep-2026-10-16b.md`._

The documented pool from [`issue-sweep-2026-10-16.md`](#the-issue-sweep-2026-10-16)'s appendix is what is left after
four passes: it holds no High or Medium finding, so these five are the strongest
remaining — four unreachable failure paths in the code that reports a render's
failure, and seven helpers nothing calls. None is one of the twenty-five in
[`top-5-issues-2026-10-14.md`](#the-five-highest-severity-issues-2026-10-14), [`top-5-issues-2026-10-15.md`](#the-five-highest-severity-new-issues-2026-10-15),
[`issue-sweep-2026-10-15.md`](#the-issue-sweep-2026-10-15), [`issue-sweep-2026-10-15b.md`](#the-issue-sweep-2026-10-15-fourth-pass) or
[`issue-sweep-2026-10-16.md`](#the-issue-sweep-2026-10-16); each was listed below the bar there and is re-driven
here before promotion, with the place it was first noted named in its section.

### How this list was made

The pool is the 11-row appendix of [`issue-sweep-2026-10-16.md`](#the-issue-sweep-2026-10-16). Each row was
re-driven against the tree: the four tails located in their functions
(`generator.wait_gateway_ready` 111-185, `_probe_url` 366-391, `salad_queue._run`
862-906, `ai_helper._collect` 697-743), the seven helpers confirmed to have exactly
one occurrence each in the whole tree (the `def`), and the "Refresh Salad logs"
no-op driven in a hidden window. The two doc rows and the deferred banner stay in
the appendix.

**Ranking basis, in order of weight:**

1. **A failure path that can never report.** The message that names what went wrong
   is unreachable, so the operator gets a poorer one.
2. **Code nothing calls.** Dead weight that reads as live.

---

### 1. `generator.wait_gateway_ready`'s `/ready` failure message can never show (Low)

**Artifact.** `salad_studio/generator.py:180-185` (the trailing block), against the
in-loop raise at `:179`.

**What is wrong.** The loop over `_READY_TRIES` ends every final iteration by
returning or raising, so the block after it never runs:

```
   179         raise RuntimeError(msg + f"  (pre-probe /ready failed for {who})")
   180     msg = explain_http(int(last_code), last_body, url, method="GET")
   181     _log("error", msg)
   182     raise RuntimeError(
   183         f"{msg}  (pre-probe /ready failed for {who} after {_READY_TRIES} probes over "
   184         f"~{ready_budget_s() // 60} minutes; last status HTTP {int(last_code)})"
   185     )
```

The message that names the probe count and the budget — the one an operator needs
to tell "the replica never came up" from "the gateway refused" — is dead. First
noted: [`docs/issue-sweep-2026-10-15.md`](#the-issue-sweep-2026-10-15) §Appendix.

**Fix.** Let the last attempt fall out of the loop so the trailing block builds that
message; every earlier attempt keeps its current behaviour.

**Proof.** `tests/test_generator.py` drives the wait with a stubbed transport that
answers a retry code every time and requires the raised message to carry
`after 118 probes` and the minutes; it fails on the old code (the short in-loop
message).
**Fixed:** the final-attempt `raise` in `wait_gateway_ready` became a `break` (`generator.py:169-172`, `:180-182`), so the trailing block at `:185-189` runs. Measured: the raised message went from `Error 522: Connection timed out  (pre-probe /ready failed for https://example.salad.test/)` to the same sentence plus `after 118 probes over ~90 minutes; last status HTTP 522`. Proved by `tests/test_generator.py::WaitReady.test_the_last_probe_names_the_probe_count_and_the_budget`, which drives the rebuilt old function and the shipped one in one test.

---

### 2. `generator._probe_url`'s "no probe worked" return can never show (Low)

**Artifact.** `salad_studio/generator.py:391` (`return 0, "no probe worked"`),
inside `_probe_url` (366-391).

**What is wrong.** The loop tries `HEAD` then `GET`; the only `continue` is under
`method == "HEAD"`, so the `GET` pass always returns and the trailing return is
unreachable. A URL that neither method answers therefore reports the `GET` pass's
own reason rather than the summary the code intends. First noted:
[`docs/issue-sweep-2026-10-16.md`](#the-issue-sweep-2026-10-16) §Appendix.

**Fix.** Fall out of the loop when both methods have been tried, so the summary is
what the caller sees.

**Proof.** `tests/test_generator.py` drives `_probe_url` with both methods failing
and requires the returned reason to be the summary; it fails on the old code.
**Fixed:** the `GET` pass now `break`s out to the summary (`generator.py:393-398`); HEAD keeps its own reason, and HEAD's retryable `HTTPError` still continues to GET, so a `403` is still definitive only after a GET. Measured: `(0, 'URLError')` became `(0, 'no probe worked')`. Proved by `tests/test_generator.py::CheckLoraUrls.test_a_url_neither_method_answers_reports_the_summary`.

---

### 3. `salad_queue._run`'s "gave up after N attempts" tail can never show (Low)

**Artifact.** `salad_studio/salad_queue.py:904` (`job.reason = f"gave up after
{self.max_attempts} attempts"`), inside `_run` (862-906).

**What is wrong.** `next_action` returns `RETRY` only while
`attempt < max_attempts`, so the final iteration takes `ACCEPT` or `FAIL`, both of
which return from `_run` before the tail. A job that exhausted its attempts
therefore reports whatever `FAIL` says rather than the "gave up" reason the code
intends. First noted: [`docs/issue-sweep-2026-10-15b.md`](#the-issue-sweep-2026-10-15-fourth-pass) §Appendix.

**Fix.** Let the final iteration fall through to the tail so the "gave up" reason is
recorded, keeping the earlier attempts' behaviour.

**Proof.** `tests/test_salad_queue.py` drives a job through `max_attempts`
retryable failures and requires the job's reason to be the "gave up" sentence; it
fails on the old code.
**Fixed:** `_run` now `break`s when the final attempt fails while the job was BUSY (`salad_queue.py:886-891`), so the tail records the reason; a definitive `FAILED` keeps `reason_of(result)` and returns as before, and no sleep happens after the last attempt. Measured: the job's reason went from `'HTTP 503: unavailable'` to `'gave up after 3 attempts'`. Proved by `tests/test_salad_queue.py::ClassificationTest.test_a_job_that_exhausts_its_attempts_records_the_gave_up_reason`.

---

### 4. `ai_helper._collect`'s trailing return can never show (Low)

**Artifact.** `salad_studio/ai_helper.py:743` (`return text, attempts, info`),
inside `_collect` (697-743).

**What is wrong.** The loop over `range(attempts + 1)` raises on its last round, so
the trailing return is unreachable — the "attempts exhausted, here is what we got"
path the signature promises does not exist. First noted:
[`docs/issue-sweep-2026-10-16.md`](#the-issue-sweep-2026-10-16) §Appendix.

**Fix.** Return the collected text on the last round instead of raising, and keep
the raise for the rounds that still have an attempt left.

**Proof.** `tests/test_ai_helper.py` drives `_collect` with a stubbed transport that
always answers "continue" and requires the returned text rather than a raise; it
fails on the old code.
**Fixed:** the last round now falls out to the return instead of raising (`ai_helper.py:735-743`), and the module and `_collect` docstrings were updated to match. This is a behaviour change, as the issue prescribes: a still-cut reply now reaches `parse_reply_full`, which either recovers a complete object the model restarted after the cut or reports `ReplyError`. Measured: an `AiError` became `('…', 2, truncated=True)`. Proved by `tests/test_ai_helper.py::ACutOffReplyIsContinued.test_an_exhausted_budget_returns_the_stitched_text` and `::test_a_cut_reply_the_model_restarted_is_still_recovered`, with the existing still-cut test re-pointed at the stitched fragment.

---

### 5. Seven module-level helpers nothing calls (Low)

**Artifacts.** `salad_studio/theme.py:441` (`palette_snapshot`),
`salad_studio/json_highlight.py:82` (`token_kinds`),
`salad_studio/graph_view.py:820` (`node_boxes`), `:1063` (`round_polyline`),
`:1476` (`_draw_grid`), `:1520` (`_wrap`), `:1536` (`_rounded_rect`).

**What is wrong.** A repo-wide scan over every `.py` in the tree finds exactly one
occurrence of each name — its own `def`. They read as live code (two are exported by
their module's docstring) but nothing calls them. First noted:
[`docs/issue-sweep-2026-10-15.md`](#the-issue-sweep-2026-10-15) §Appendix (three of them) and
[`issue-sweep-2026-10-16.md`](#the-issue-sweep-2026-10-16) §Appendix (the rest).

**Fix.** Delete the seven. Each is unreachable from every shipped path and every
test, so no capability is removed.

**Proof.** `tests/test_docs_match.py`'s dead-symbol rule gains the seven names: it
asserts each is absent from its module, and the same rule driven against a scratch
copy of the pre-deletion source reports all seven present — so the check fails on
the old form and passes on the new.
**Fixed:** all seven deleted after a word-boundary scan over every `.py` found exactly one occurrence each (the `def`) and no `getattr`, subclass or test reference; `theme.py`'s then-unused `Mapping` import went with them. `tests/test_docs_match.py`'s dead-symbol rule gained the seven (a source scan, because `_draw_grid` was a method) plus a `PRE_DELETION_DEFS` copy of the verbatim blocks: the rule reports all seven against the pre-deletion source and none against the shipped text.

---

### Appendix: the pool rows left for a later pass

| Site | What is wrong | Severity |
|---|---|---|
| `salad_studio/app.py:4067-4068`, `:1097-1098` | "Refresh Salad logs" is a silent no-op during a poll (driven: the status line stays on the last success and the button is not disabled). | Low |
| `docs/workflow/22:55` | Cites a line into doc 14 that has moved; the fact's home is the same table's row above. | Low |
| `docs/workflow/17:109`, `:312`, `:401`, `docs/workflow/19:150` | References like "doc 21 §6.2 / §6.7" name list items, not headings; the section-reference rule skips them because the prose names the document rather than a section of the file it sits in. | Low |
| `docs/workflow/19` has no `## 4.`, `docs/workflow/22` no `## 2.`, `docs/workflow/14` a `## 4b.` with no `## 4.` | Any pointer to those numbers is born dead; no live pointer names one today. | Low |
| `docs/workflow/15:3-8` | The dated banner's `prefetch5`/`prefetch4` wording. **Deliberately deferred** at `docs/history/59:159` (D7): rewriting a dated note would falsify the record. It stays deferred. | Low, deferred |

---


---

# Closure, 2026-10-16

This section closes the work the six consolidated records' appendices left open, the
prune of the 13 living docs, and this document's own consolidation. It was written by
the orchestrator after the three workers below returned and every claim was re-read
against the tree. Captures live in the session's scratch dir; each is named where it
is used.

## 1. The rows, re-driven and closed

The six records' appendices hold **83 data rows** (the 89 the plan's baseline counted
included each appendix's own header row). Every row was re-driven against the tree by
the worker below, which opened each cited artifact at its cited line:

| outcome | rows | what it means |
|---|---:|---|
| still real → **fixed** | 5 | the cited line still said what the row reported; each fix has a test that passes on the fix and fails on the old form |
| **already fixed** | 35 | an earlier pass fixed it; the evidence is the test or the line that now reads correctly |
| **no longer real** | 7 | the artifact moved or the premise was wrong (e.g. `theme.py` is 437 lines, so its `:441` does not exist; `comfy_import`'s unused parameters are unread by design, pinned by a test present in HEAD) |
| out of scope for that worker | 32 | rows citing `docs/workflow/**`, the READMEs or `tests/test_docs_match.py`, which other sets own — all closed by the prune, the consolidation or the orchestrator |
| **deferred** | 4 occurrences of one row | doc 15's dated `prefetch5` banner, deferred at `docs/history/59:159` (D7); it stays deferred with that reason |

The five still-real rows, each fixed and proven:

| row | cited artifact | the fix | the proof |
|---|---|---|---|
| R1.3 | `salad_studio/app.py:252-254` | the status label moved to `app.py:320-328` and `_wrap_status` (`:357-370`) writes `wraplength = width-16` with a floor of `_STATUS_MIN_WRAP` (`:66`), so a long refusal is no longer clipped | `tests/test_app_layout.py::TheStatusLineWrapsInTheWindow` — `fixed: PASS` / `old: FAIL` |
| R2.13 | `tests/test_config_page.py:1030`, `:1108` | the two writes now set `_idle_stop_s`, the attribute `salad_queue` actually reads (`salad_queue.py:413`, `:739-744`), not `idle_stop_s` | `tests/test_salad_queue.py::LifecycleIdleTest::test_a_timeout_written_onto_the_queue_is_the_one_it_reads` — `fixed: PASS` / `old: FAIL` |
| R2.14 | `tests/test_app_layout.py:1477`, `:2923-2932`, `:3028-3037` | five window classes that clobbered the store paths now save them (`_redirect_store` / `_put_stores_back`, `test_app_layout.py:139-156`) and restore them with one `addCleanup` each | `::WindowClassesPutTheStoresBack` — `fixed: PASS` / `old: FAIL` |
| R2.15 | `salad_studio/graph_view.py:1363`, `:1382` | `GraphPane._soon` (`:1351-1368`) and its `destroy` (`:1370-1378`) now have a test | `tests/test_graph_view.py::PaneScheduledWorkIsCancelled` — `fixed: PASS` / `old: FAIL` |
| R2.16 | `salad_studio/prompt_history.py:320` | the "a `ts` that matches no row attaches nothing" rule now has a test | `tests/test_prompt_history.py::PromptHistoryStore::test_attach_image_with_a_ts_that_matches_no_row_attaches_nothing` |

The 32 out-of-scope rows were closed by the other two sets and by the orchestrator:
the `docs/workflow/**` rows by the prune (each cut names its surviving home in
`{SCRATCH}/prune.log`), the README rows by the prune's re-point and the orchestrator's
count re-sync, and the `tests/test_docs_match.py` rows by that module's own edits in
the consolidation (the tautology and the duplicated `AUDIT` were fixed by an earlier
pass; the N1 rule now reads this document).

## 2. The two recorded follow-ups

Both were still real and both are fixed.

1. **The grids no longer grew on a window wider than the grid.** Driven before the fix,
   at 1600×900 the Catalog tree was 1366 px wide with its columns totalling the
   declared 1250 (116 px dead) and the Queue 930/1366 (436 px dead); at 1920×1080 the
   dead room was 436/586/756 px. `_keep_grid_filling` (`salad_studio/app.py:605-661`),
   registered at `:3232`, `:3858` and `:4066`, now grows the columns to fill the room —
   grow-only and idempotent (the declared widths are read once, the room is recomputed
   from them every pass, `#0` is counted only where shown, nothing grows past the
   canvas viewport, and a repeated width short-circuits). Re-driven at 1600, 1920,
   1366 and 1024 and measured on the way back down: no sticky growth, no runaway.
   `tests/test_app_layout.py::AGridFillsAPageWiderThanIt` (3 tests) — `fixed: PASS` /
   `old: FAIL`, and the earlier U1 proof still passes (at 1366 and 1024 neither grid
   fits, so both keep their declared widths).
2. **Four modules read the user's real `~/.config/salad/studio-queue.json` in a discover
   run.** `tests/test_json_editor.py`, `test_prompt_history.py`, `test_tokens.py` and
   `test_theme.py` each build a window and none moved `salad_queue.LEDGER_PATH`, while
   `test_app_layout` moved it only for its own module. The new `tests/_stores.py`
   (`keep_queue_ledger_off_the_user_store()` / `restore_queue_ledger()`) is wired as
   each module's own `setUpModule`/`tearDownModule`
   (`test_json_editor.py:21-33`, `test_prompt_history.py:18-27`, `test_tokens.py:20-31`,
   `test_theme.py:25`, `:42-48`, `:69-71`).
   `tests/test_stores.py::EveryWindowModuleRedirectsTheLedger` — `fixed: PASS` /
   `old: FAIL` for all four.

## 3. The prune

The 13 living docs fell **2971 → 2846 lines (−125, 4.2%)**, inside the 2852 bar. The
cut came from `docs/workflow/22` (−58), `17` (−38), `19` (−17), `18` (−5), `21` (−2),
`README.md` (−1) and `salad_studio/README.md` (−4). `docs/workflow/14`, `15`, `16`,
`23`, `salad_klein/README.md` and the skill were kept whole because they are
load-bearing for the 45 and ~30 required snippet strings and for the tag, unet and
label checks. Every removal left a one-line pointer to a home the worker opened and
pasted back; the rest is compression rather than deletion, and the deferred doc-15
banner is byte-for-byte. All seven dated records still carry every finding with its
resolution (0/12/24/0/71/50/30 headings preserved). Full table:
`{SCRATCH}/prune.log`.

## 4. The consolidation

The six dated issue records became this one document (1423 lines). `docs/*.md`
now holds only `issue-records.md`, so the living-document count fell **20 → 10**.
This file has 0 `### <TAG>,` headings. The six issues in each pass use numbered
headings. It has 42 `###` headings, 30 numbered `### N.` issues, 5 `**Fixed:**`
lines and 83 appendix rows, and a survival check confirms each appears here.
`tests/test_docs_match.py`'s `ISSUE_RECORD` and ten comment references were
re-pointed in the same wave, and the root README's `docs/` row was re-pointed by
the prune worker whose set owns it. Full record: `{SCRATCH}/consolidate.log`.

## 5. The captures

| step | capture |
|---|---|
| the rows, re-driven and closed | `{SCRATCH}/findings.log` |
| each fix and its old form | `{SCRATCH}/issues.log` |
| the disjoint file sets | `{SCRATCH}/disjoint.log` |
| the prune, measured | `{SCRATCH}/prune.log` |
| the consolidation | `{SCRATCH}/consolidate.log` |
| the capability inventory | `{SCRATCH}/capability.log` |
| UI/UX on the real window | `{SCRATCH}/uiux.log` |
| both suites and the link resolver | `{SCRATCH}/suite.log`, `klein.log`, `docs.log` |
| this document's shape | `{SCRATCH}/shape.log` |

## 6. History 63, left as written

`docs/history/63-salad-studio-audit-2026-10-16.md` is a dated record. This pass
does not edit `docs/history/**`. A later reader of that file should take these
two facts from here.

The opening and §9 still say nothing in the repo was changed, and that each
`**Correction:**` is a proposal. A later pass then annotated `**Fixed:**` into
the same file. History 63 now carries 24 `**Fixed:**` lines. Those fixes landed
after the audit was written.

Lines 400 and 411-413 still name `docs/issue-sweep-2026-10-16b.md`, which is
gone with the other five dated issue files. The four proof-line class names
that record discussed (`WaitReady`, `CheckLoraUrls`, `ClassificationTest`,
`ACutOffReplyIsContinued`) live in this document, in The next five issues,
2026-10-16. Follow this file for those names.
