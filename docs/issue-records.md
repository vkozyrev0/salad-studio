# Issue records, 2026-10-14 to 2026-10-16

This is the one record of the studio's six issue passes. Each entry names the artifact, what was wrong, the measured drive, the fix or resolution, the check that keeps it fixed, and its status.

The six dated files this consolidates, all removed on 2026-10-17: `docs/top-5-issues-2026-10-14.md`, `docs/top-5-issues-2026-10-15.md`, `docs/issue-sweep-2026-10-15.md`, `docs/issue-sweep-2026-10-15b.md`, `docs/issue-sweep-2026-10-16.md`, and `docs/issue-sweep-2026-10-16b.md`.

Severity is the highest rule that applied: a red suite or a shipped break; the app exposing, losing, or falsifying the user's work; a documented claim a reader acts on and fails; a control or document a reader cannot reach. Ties break by how many surfaces the defect reaches.

A check named below fails on the old form and passes on the shipped form unless the entry says otherwise. Appendix rows that a later pass fixed or found unreal carry that status.

---

### 1. The suite is red: the Import path resolves LoRA names with one live Civitai search after another (High)

**Artifacts.** `salad_studio/comfy_import.py:748-767` (the caller), `salad_studio/comfy_import.py:652-659` (the pool it defeats), `tests/test_import_civitai_image.py:101-102`, `:113-119`.

**Wrong.** `resolve_prompt_loras` resolves every name it is handed in one `ThreadPoolExecutor` pass (`max_workers=min(8, len(unique))`). `resolve_local_lora_nodes` calls it **once per LoRA node** with a single-element list (`:762-767`), so `len(unique)` is always 1 and the pool runs one Civitai search at a time inside the press path. Measured with a 0.3 s stub: four names cost 1.21 s of wall time and four serial calls, where one parallel pass costs ~0.30 s. Against the live Civitai API the same four names cost 12.5-15.7 s each.

**Drive.**

```
python -m unittest tests.test_import_civitai_image -v
test_generate_posts_a_copy_with_no_pack_types_and_the_prompt ... ResourceWarning: Implicitly cleaning up <HTTPError 401: 'Unauthorized'>
AssertionError: None is not true : Generate never POSTed
Ran 3 tests in 200.846s
FAILED (failures=1)
```

**Fix or Resolution.** Collect every `lora_name` input that needs a search, run one `resolve_prompt_loras` call, then write each node's result back by name. Stub the LoRA search in both `setUp`s so the suite cannot depend on Civitai's latency. Driven directly, four names cost 1.82 s before and 0.33 s after, with the same four searches and the same `missing` list.

**Check.** `tests/test_comfy_import.py::LocalLoraSearchIsConcurrent.test_four_names_are_searched_in_one_pass` requires the wall time to be under three 0.3 s delays; it passes on the fix and fails on the pre-fix function (`7.03s not less than 0.9s`). `tests/test_import_civitai_image.py` runs green (`Ran 3 tests … OK`).

**Status.** Fixed 2026-10-14.

---

### 2. With no Salad key the badge never resolves and nothing says why (High)

**Artifacts.** `salad_studio/app.py:934-939` (the swallowed read), `salad_studio/tokens.py:186-189` (the sentence that names the fix), `salad_studio/app.py:251-254` (the status line).

**Wrong.** One `except Exception: snaps = {}` wraps the API-key read and every probe. With no key saved, `resolve_salad_key()` raises `FileNotFoundError("Salad API key is empty. Save it on the Tokens tab (<path>).")`, and the handler discards it.

**Drive.**

```
key on disk        : (none)
the discarded text : 'Salad API key is empty. Save it on the Tokens tab (...studio-tokens.json).'
badge              : '…'
status line        : 'Ready'
any surface names the key: False
```

**Fix or Resolution.** Read the key on the main thread, separately from the probes. The badge reads `No key`, and the Logs carry the sentence that names the Tokens tab and the file. The status line is deliberately left alone because it carries events (`retrying`, a refusal). The log line is written once per distinct message, because the poll runs every 15 s.

**Check.** The hidden-window drive in `tests/test_config_page.py` builds the app with no key and requires the badge to read `No key` and the Logs to name the key and the Tokens tab while the status line keeps its event. It fails on the old handler. `tests/test_queue_page.py` guards the other half: the key report must not erase a live `retrying` message.

**Status.** Fixed 2026-10-14.

---

### 3. `Delete profile` asks nothing and reports a deletion that did not happen (High)

**Artifacts.** `salad_studio/app.py:4853-4872`.

**Wrong.** Two defects in one handler. It deletes the saved profile and switches the active one on a single click, with no dialog, no undo, and no status line before the fact. And `self.status.set(f"Deleted {name}")` runs whether or not anything was deleted.

**Drive.**

```
saved profiles     : ['klein', 'klein5090'] -> ['klein5090']
dialogs asked      : []
status line        : 'Deleted klein'
unsaved name       : status line 'Deleted no-such-profile'
```

**Fix or Resolution.** Ask first, the same question the Catalog's Delete asks, and report what actually happened: name the deleted profile, and say so when the name is not a saved profile.

**Check.** The hidden-window drive in `tests/test_config_page.py`: a saved profile asks and a `No` leaves it alone; an unsaved name says no such profile exists instead of claiming a deletion. Both assertions fail on the old handler.

**Status.** Fixed 2026-10-14.

---

### 4. The press's refusals leave the status line stale (Medium)

**Artifacts.** `salad_studio/app.py:4934-4938` (invalid JSON), `:4976-4978` (unreadable key), `:4980-4983` (empty gateway), against `:5001-5004` (the stopped-badge refusal, which does set it).

**Wrong.** The manual promises the refusal reaches the status line (`salad_studio/README.md:362-366`), and the stopped-badge path honours it. The other refusals report through a dialog and never touch the status line.

**Drive.**

```
invalid JSON    : status 'SENTINEL'  dialog "Prompt Editor JSON is invalid: ..."
empty gateway   : status 'SENTINEL'  dialog "Gateway URL is empty."
unreadable key  : status 'SENTINEL'  dialog "Cannot read Salad API key: ..."
```

**Fix or Resolution.** Every refusal the press handler can make writes the status line with the same cause the dialog carries: invalid JSON, the form-field refusal (`_profile_from_form`'s `ValueError`), the routing refusal (`plan_route`), the unreadable key, and the empty gateway.

**Check.** The hidden-window drive in `tests/test_config_page.py` presses Generate in each of four states and requires the status line to carry the refusal after the dialog is dismissed. Each fails on the old handler with `SENTINEL` and passes now.

**Status.** Fixed 2026-10-14.

---

### 5. Both READMEs state a container-side test count that is wrong, and no check can see it (Medium)

**Artifacts.** `README.md:33`, `salad_studio/README.md:549`, `tests/test_docs_match.py:176` and `:183-189`.

**Wrong.** The Quick start block states `# 16 tests` for the container suite. The suite has **18** test methods (`test_prefetch.py` 17, `test_hf_gated_access.py` 1). `_real_count()` counts only the root suite, the loop reads only `ROOT_README` and `MANUAL`, and `re.search` takes only the first count in each file, so the container-side line is invisible. `salad_klein/README.md` was read by no test at all.

**Drive.** `_real_count()` reports 18 container-side test methods; the stated line reads `# 16 tests`, and `test_docs_match.py` counts 0 of them.

**Fix or Resolution.** Correct both figures and leave a check: a test counts `salad_klein/test_*.py` and asserts every stated container-side count.

**Check.** `tests/test_docs_match.py::ContainerSuiteCount.test_the_stated_container_count_is_the_real_one` fails with `# 16 tests` and passes with `# 18 tests`.

**Status.** Fixed 2026-10-14.

---

### 6. The Salad container pane prints secrets in clear (High)

**Artifacts.** `salad_studio/app.py:3803-3808` (`_set_salad_logs`), `:3835-3837` (`log`, which redacts), `:3813-3821` (the cached redaction list).

**Wrong.** `log()` runs every line through `studio_log.redact`; `_set_salad_logs` inserts the container's stdout verbatim. The same value is masked in one pane and shown in the other. The redaction list is also cached until a token is saved, so a token that arrives any other way is logged in clear.

**Drive.**

```
the secret is 'hf_SUPERSECRETVALUE1234'
Studio pane : REDACTED
Salad pane  : IN CLEAR
Salad pane content: 'container stdout:\nHF_TOKEN=hf_SUPERSECRETVALUE1234\nready'
a token written after the cache was filled: IN CLEAR
```

**Fix or Resolution.** Redact in `_set_salad_logs` the same way `log()` does, and clear the cached list whenever a token is written, not only in one save path.

**Check.** `tests/test_app_layout.py::BothLogPanesMaskSecrets.test_a_container_log_line_is_masked_in_both_panes` and `::BothLogPanesMaskSecrets.test_a_token_written_after_the_cache_is_warm_is_masked_too` both fail on the old handlers (`AssertionError: 'hf_FIRSTSECRETVALUE1234' unexpectedly found in … : the Salad pane leaked the token`).

**Status.** Fixed 2026-10-15.

---

### 7. `Add instance` accepts words that name no host, so one typed phrase becomes five instances reported as success (High)

**Artifacts.** `salad_studio/vast.py:144-160` (`normalize_endpoint`), `salad_studio/app.py:1732-1754` (`_on_vast_add`).

**Wrong.** `normalize_endpoint` prefixes `http://` to anything, so a word that names no host comes back as one, and the page splits the box on whitespace.

**Drive.**

```
normalize_endpoint('not') = 'http://not'
normalize_endpoint('not an address at all') = 'http://not an address at all'
normalize_endpoint('comfy-local') = 'http://comfy-local'

after pressing Add instance with a phrase: 5 rows ->
  ['http://not', 'http://an', 'http://address', 'http://at', 'http://all']
status line: 'added 5 instance(s): http://not, http://an, http://address, http://at, http://all'
dialog shown: False
```

**Fix or Resolution.** With no scheme, the text must look like a host (a dot or a port); with an explicit scheme it is taken as typed. `http://comfy-local` still works. `_on_vast_add` reports the refusal and names what it did and did not add.

**Check.** Four tests fail on the old function and pass now: `tests/test_vast.py::EndpointDerivation.test_text_that_names_no_host_is_refused_not_prefixed`, `tests/test_vast.py::InstanceStore.test_a_phrase_is_refused_word_by_word_not_stored`, `tests/test_config_page.py::TheConfigPageTellsTheUserWhatWentWrong.test_a_phrase_that_names_no_host_adds_no_instance`, and `…test_a_partly_refused_press_names_what_was_added_and_what_was_not`. Driven directly, the old form returns `'http://not'` where the shipped function returns `''`, and the page went from five rows to none.

**Status.** Fixed 2026-10-15.

---

### 8. Content below the fold is unreachable on seven of the eleven pages (High)

**Artifacts.** `salad_studio/app.py:1422-1488` (the Tokens page and its siblings), against `:431-438` (the Config page, the only one that scrolls by design).

**Wrong.** Only Config, Prompt Catalog, Prompt History and Queue have a scrollbar. At a 1366×728 window the notebook is 476 px tall and seven pages are taller, with nothing to scroll them.

**Drive.**

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

On the Tokens page that hides the Vast.ai key box and the **Check keys** bar. The wheel is bound to the Config canvas only (`app.py:554-562`), and 31 of 65 tab stops land off-screen.

**Fix or Resolution.** A shared scrollable-page helper (the canvas + scrollbar pattern Config already uses) applied to the pages whose content can exceed the viewport. No control, label or page is renamed or removed.

**Check.** `tests/test_app_layout.py::ContentBelowTheFoldIsReachable` has four tests: every page fits or has a scroll canvas (`…test_every_page_fits_or_scrolls_at_1366x728`), the Tokens page reaches the Vast.ai key box and **Check keys** bar, the wheel scrolls only the page under the pointer, and a focused control scrolls into view. All four error on the old layout.

**Status.** Fixed 2026-10-15.

---

### 9. The test that guards the drop recorder cannot see it break (High)

**Artifacts.** `tests/test_app_layout.py:3055` (`test_a_dropped_callback_is_reported_when_the_window_closes`), `salad_studio/app.py:834` and `:852` (the recorder).

**Wrong.** The test fabricates the entry it asserts on:

```python
    def test_a_dropped_callback_is_reported_when_the_window_closes(self) -> None:
        self.app._dropped_afters.append("after(0): the main thread is not in the Tk loop")
        log = self._close_and_read()
        self.assertIn("dropped", log, ...)
```

Driven with the recorder broken at runtime, the test still passes.

**Drive.**

```
  test_a_dropped_callback_is_reported_when_the_window_closes
    shipped recorder: PASS
    broken recorder : PASS
```

**Fix or Resolution.** Drive the shipped recorder: make a real `after` fail and require the drop to be recorded and then reported. Keep the existing reporter assertion.

**Check.** `tests/test_app_layout.py::ClosingReportsWhatTkWouldNotTake.test_the_recorder_records_a_drop_the_loop_would_not_take` requires `_dropped_afters` to hold both entries. With the recorder broken it fails (`AssertionError: 0 != 2 : both refused callbacks must be recorded: []`).

**Status.** Fixed 2026-10-15.

---

### 10. `docs/workflow/21` documents a routing function that was deleted (Medium)

**Artifacts.** `docs/workflow/21-klein-image-handoff.md:113`, `tests/test_docs_match.py:520` (which asserts it is gone), `salad_studio/profiles.py` (the shipped API).

**Wrong.** The handoff's "How routing decides" block lists four calls. `hasattr(profiles, "route_payload")` is `False`; the shipped routing entry point is `profiles.plan_route` alone.

**Drive.**

```
110 studio_meta.family_for_unet(unet_name, doc)  -> the family whose unets/markers match
111 profiles.plan_route(payload, form_profile, all_profiles)
112                                             -> (Route | None, refusal reason)
113 profiles.route_payload(payload, all_profiles)
114                                             -> (group name, profile) for that family
```

**Fix or Resolution.** Drop the dead call from the block, and make the doc check assert that no living document names `route_payload`.

**Check.** `tests/test_docs_match.py::MoreFixedClaimsHoldInTheShippedCode.test_the_dead_symbols_the_audit_named_are_gone` fails on the pre-fix text (`['…/old-doc-21.md:113']`) and passes on the shipped text.

**Status.** Fixed 2026-10-15.

---

### 11. `Convert to Prompt Editor` replaces the editor and reports an import that did not happen (High)

**Artifacts.** `salad_studio/app.py:3274-3276` (the button), `:3522` (`_on_import_civitai`), `:3543`, `:3545`.

**Wrong.** With the Comfy workflow box empty and free text in the generation-data box, the handler overwrites the Prompt Editor's JSON with a fabricated default flux-2-klein graph, copies the free text into the Positive box, and reports an import. The user's graph is gone.

**Drive.**

```
the editor still holds the user's graph : False      (the drive wrote seed 424242)
status line                             : 'Imported Civitai workflow to Prompt Editor'
dialogs                                 : []
log tail                                : ['[OK] imported Civitai paste  13 nodes · no LoRA · 1024×768 · 40 steps · cfg 1 · euler · flux2']
```

**Fix or Resolution.** Refuse when there is no workflow to convert, and never replace the editor on a refusal. Re-driven on the shipped tree, the graph (`seed: 424242`) survives and the status line reads `Refused: Nothing to convert. Paste a Comfy workflow JSON and/or Civitai generation data (prompt + Steps/CFG, or Sampler/Seed/Model).`

**Check.** The hidden-window drive in `tests/test_config_page.py` is `TheImportPageAndTheHistoryDelete::test_convert_of_free_text_refuses_and_keeps_the_editors_graph`; it passes on the shipped handler and fails against the handler rebuilt with the guard taken out.

**Status.** Verified 2026-10-15; the guard holds, no change needed.

---

### 12. `salad_probe_ages.py` exits 0 when every plate failed (Medium)

**Artifacts.** `salad_probe_ages.py:146` (`return 0`), against `salad_probe_klein.py:428` (`return 1 if fails else 0`) and `salad_probe_sdxl.py:174` (`return 3`).

**Wrong.** `main()` prints each job's result and returns 0 whatever happened, so a run where all 26 plates failed reports success.

**Drive.**

```
   145             print(fut.result(), flush=True)
   146     return 0
sibling salad_probe_klein.py: return 1 if fails else 0
sibling salad_probe_sdxl.py: return 3
```

**Fix or Resolution.** Count the results that start with `fail ` and return 1 when any did. Re-driven, the shipped `main()` ends `return 1 if fails else 0`.

**Check.** `tests/test_probe_ages.py` drives `main()` with the plate function stubbed to fail and requires a non-zero return; it fails on the old `return 0`.

**Status.** Verified 2026-10-15; no change needed.

---

### 13. `docs/workflow/15` states 6 steps for a 4-step recipe (Medium)

**Artifacts.** `docs/workflow/15-salad-flux2-klein-group.md:117`, `salad_klein/prompt_snofs_distilled_anatomy.json` (the `Flux2Scheduler` node).

**Wrong.** The recipe table said `(euler, 6 steps)`; the shipped scheduler is 4.

**Drive.**

```
doc 15:117: `salad_klein/prompt_snofs_distilled_anatomy.json` (euler, 6 steps)
the shipped file: node 62 Flux2Scheduler steps=4
```

**Fix or Resolution.** State 4, and leave a check that doc 15's stated step count equals the shipped recipe's `Flux2Scheduler` steps. Re-driven, doc 15 states `(euler, 4 steps)` and the file reads `steps: 4`.

**Check.** `tests/test_docs_match.py::KleinRecipeStepsMatchTheDoc::test_the_anatomy_recipes_steps_are_the_docs` passes on the shipped text and fails on the pre-fix `(euler, 6 steps)`.

**Status.** Verified 2026-10-15; no change needed.

---

### 14. `Delete` on the Prompt History page asks nothing and says nothing (Medium)

**Artifacts.** `salad_studio/app.py:3674-3681`, the button at `:3585`.

**Wrong.** The handler removes a stored prompt and its thumbnail with no confirmation and without writing the status line, while the Catalog's Delete and the profile Delete both call `askyesno`.

**Drive.**

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

**Fix or Resolution.** Ask first and report what was deleted on the status line as well as in the Logs. Re-driven, a `No` sets `Kept prompt history #<n>` and a `Yes` sets `Deleted prompt history #<n>: <preview>`.

**Check.** `tests/test_config_page.py::TheImportPageAndTheHistoryDelete` (its ask/No and report/Yes tests) passes on the shipped handler and fails against the handler rebuilt without the ask and the status line.

**Status.** Verified 2026-10-15; no change needed.

---

### 15. `docs/workflow/14` attributes two CLI options to `salad_gen.py` that it does not have (Medium)

**Artifacts.** `docs/workflow/14-salad-comfy-live-findings.md:56`, `salad_gen.py` (its parser and `build_graph`).

**Wrong.** The tools table gave `salad_gen.py` "optional `ckpt_name` / `lora_name`" beside real CLI flags. Those two are `build_graph()` keyword parameters, and the script rejects them as arguments.

**Drive.**

```
doc 14:56: | `salad_gen.py` | `POST /prompt` Flux graph; optional `ckpt_name` / `lora_name` |
salad_gen flags: ['--height', '--negative', '--out', '--prompt', '--seed', '--steps', '--timeout', '--wait-ready', '--width']
salad_gen.py: error: unrecognized arguments: --ckpt_name x
```

**Fix or Resolution.** Name the script's real flags and say `ckpt_name` / `lora_name` are `flux_payload()` parameters rather than flags. A doc check asserts every `--flag` a living document attributes to a shipped script exists in that script's parser.

**Check.** `tests/test_docs_match.py::DocumentedScriptOptionsAreRealFlags.test_every_option_a_living_doc_gives_a_script_is_a_flag` passes on the shipped text and fails on the pre-fix row, reporting `salad_gen.py has no ckpt_name` and `… no lora_name`.

**Status.** Verified 2026-10-15; no change needed.

---

### 16. A queue row kept from an earlier session is answered with a false "select a request first" (High)

**Artifacts.** `salad_studio/app.py:3883` (`f"kept-{rid}"`, the row key), `:3935-3941` (`int(selection[0])`), `:3946`, `:3962`.

**Wrong.** The Queue page keeps finished records for four hours, and a row restored from an earlier session is keyed `kept-<id>`. Cancel and Retry read the selection as an integer, so both refuse a row the user has visibly selected.

**Drive.**

```
  restarted window keys: ['kept-1']      selection: ('kept-1',)
  Cancel on kept-1 -> 'Queue: select a request first'
  Retry  on kept-1 -> 'Queue: select a request first'
```

A live finished row answers correctly (`…has already been sent, so it cannot be cancelled`).

**Fix or Resolution.** Read the id off the row's own first cell rather than parsing the key, and answer a kept row with the fact that its request finished in an earlier session.

**Check.** The hidden-window drive in `tests/test_queue_page.py` restores a kept row, selects it, and presses Cancel and Retry; both must answer with the earlier-session fact, not the selection refusal. It fails on the old handler.

**Status.** Fixed 2026-10-15.

---

### 17. A refused Generate in vast.ai mode leaves the status bar claiming the last success (Medium)

**Artifacts.** `salad_studio/app.py:5435-5439` (the invalid-JSON refusal) and `:5440-5448` (the no-instance refusal), against the Salad sibling at `:5247-5251`.

**Wrong.** `_on_generate_vast`'s two refusals report through a dialog and the Logs and never write `self.status`.

**Drive.**

```
  no-instance: status = 'Wrote C:\plates\stale.png'
  no-instance: dialogs = [('info', 'No vast.ai instance is selected. …')]
  bad-json   : status = 'Wrote C:\plates\stale.png'
  SALAD sibling bad-json: status = 'Refused: the Prompt Editor JSON is invalid'
```

**Fix or Resolution.** Both refusals write the status line with the cause the dialog carries, the way the Salad sibling does.

**Check.** The hidden-window drive in `tests/test_config_page.py` presses Generate with no instance selected and with invalid JSON; both fail on the old handler.

**Status.** Fixed 2026-10-15.

---

### 18. At 1024 px the Import page's Height knob sits past the right edge and nothing scrolls sideways (Medium)

**Artifacts.** `salad_studio/app.py:441-489` (the helper: only `yscrollcommand`), `:535-561` (`_reveal` moves on Y only), `:3227-3238` (five unweighted Label+Entry pairs in one row).

**Wrong.** Every page scrolls vertically and none scrolls horizontally.

**Drive.**

```
--- 1024x720 ---  'Config': canvas_w=827 scrollregion=(0,0,827,2721) xscroll='' (content wants 1257px)
                  'Import': PAST right by 96px: 'PY_VAR86' (x=809)   <- the Height Entry
--- 900x700  ---  'Import': PAST right by 220px: 'PY_VAR86'; PAST right by 102px: 'Height'
                  'LoRAs': CLIPPED 42px of 124px wanted: 'Verify unverified'
```

**Fix or Resolution.** Give the helper a horizontal scrollbar and make the reveal move on both axes.

**Check.** The hidden-window drive in `tests/test_app_layout.py` measures every page at 1024×720 and 900×700 and requires each control inside its canvas's scroll region on both axes, then focuses the Height knob and requires the reveal. It fails on the old helper.

**Status.** Fixed 2026-10-15.

---

### 19. "Remove extra" acts on one row of a multi-selection while "Verify" acts on all (Medium)

**Artifacts.** `salad_studio/app.py:4320-4335` (`lid = sel[0]` at `:4325`) against `:4273-4300` (`for lid in sel:` at `:4280`); the buttons sit at `:2462` and `:2468`.

**Wrong.** Two LoRAs selected, "Remove extra" removes the first and reports the singular.

**Drive.**

```
  selection size: 2
  Remove extra with 2 selected -> 24 -> 23; status='Removed civitai:90001@90001'
  still present: ['civitai:90002@90002']
```

**Fix or Resolution.** Loop over the whole selection and report the count, as Verify does.

**Check.** The hidden-window drive in `tests/test_config_page.py` selects two extra LoRAs, presses Remove extra, and requires both gone and the status line to name the count. It fails on the old handler.

**Status.** Fixed 2026-10-15.

---

### 20. `docs/workflow/22` sends a reader to sections that do not exist (Medium)

**Artifacts.** `docs/workflow/22-two-body-correctness-research.md:84` (`(…, §1.3)`), `:255` (`the binding ones are §1.1 and §6.3`).

**Wrong.** Doc 22's headings are `## 1`, `## 3`–`## 8`; it has no `§2`, no `§1.x` and no `§6.x`, so both references point at nothing.

**Drive.** A heading scan finds `## 1` and `## 3`–`## 8`; `§1.3`, `§1.1` and `§6.3` each match no heading.

**Fix or Resolution.** Re-point both at the sections that hold the facts, and make the doc check assert every `§N`/`§N.M` a living document names exists as a heading in the file it names.

**Check.** The check fails on the old text and passes on the new.

**Status.** Fixed 2026-10-15.

---

### 21. The Prompt Catalog and Prompt History grids clip their right-hand columns, with no horizontal scrollbar (Medium)

**Artifacts.** `salad_studio/app.py:3009-3027` (the Catalog tree, 1250 px of columns), `:3622-3643` (the History tree, 56 + 1100 px), `tests/test_app_layout.py:3571-3573` (the layout guard skips a page with no scroll canvas).

**Wrong.** Both pages bypass `_scrollable_page`, so their trees get a vertical scrollbar and no horizontal one.

**Drive.**

```
--- 1366x728 ---
  Prompt Catalog   tree_w= 1149  xview_span=0.916  clipped ~105 px
  Prompt History   tree_w= 1149  xview_span=0.990  clipped ~ 11 px
--- 1024x720 ---
  Prompt Catalog   tree_w=  807  xview_span=0.642  clipped ~449 px
  Prompt History   tree_w=  807  xview_span=0.695  clipped ~355 px
```

At 1024×720 the Catalog's **Graph** column is entirely off-screen. The columns are user-resizable, so this is friction rather than a wall.

**Fix or Resolution.** Give both trees a horizontal scrollbar; the columns keep their widths and the user's drag still works.

**Check.** The hidden-window drive in `tests/test_app_layout.py` measures both trees' `xview` span at 1366×728 and 1024×720 and requires the full column set to be reachable; it fails on the old layout (span 0.642 with no x-scrollbar).

**Status.** Fixed 2026-10-16.

---

### 22. `docs/workflow/15` tells a reader to keep `_meta` blocks that no shipped recipe has (Medium)

**Artifacts.** `docs/workflow/15-salad-flux2-klein-group.md:127`, `salad_klein/prompt_*.json`, `docs/workflow/21-klein-image-handoff.md` §5.

**Wrong.** Parsing every shipped Klein recipe finds 14 `LoraLoader` nodes and **0** carrying `_meta`, while doc 21 says a `LoraLoader` without one is classified **foreign**.

**Drive.** `lora_meta_nodes(KLEIN_RECIPES)` returns 14 entries; none has a truthy `_meta`.

**Fix or Resolution.** Say what is true: the Studio adds a block when it writes a recipe, the shipped files carry none, and the rule is to keep it **if** the node has one.

**Check.** The doc check asserts every `LoraLoader` in a shipped recipe that carries `_meta` is described, and that the sentence no longer claims the blocks are universal.

**Status.** Fixed 2026-10-16.

---

### 23. `docs/workflow/22` labels two of its own sections "Route B" and "Route C" with no Route A left (Medium)

**Artifacts.** `docs/workflow/22-two-body-correctness-research.md:50` (`## 3. Route B …`), `:147` (`## 4. Route C …`), `:218-222` (`**A head-to-head of the three routes**`).

**Wrong.** The Route A section and its `## 2` were cut, so "Route B", "Route C" and "the three routes" name a framing that no longer exists.

**Drive.** A heading scan finds `## 3. Route B` and `## 4. Route C` with no `## 2` and no `Route A` label anywhere in the file.

**Fix or Resolution.** Name the sections by what they hold (the SDXL/Illustrious route and the 3D route) and say the third route in the comparison is the current one.

**Check.** The doc check's section-reference rule gains the label case; it fails on the old text and passes on the new.

**Status.** Fixed 2026-10-16.

---

### 24. "Check keys" is a silent no-op while a check runs, and the button is never disabled (Medium)

**Artifacts.** `salad_studio/app.py:1652` (the button, never touched again), `:1673-1675` (`if self._token_probe_busy: return`), `:1184` (opening the Tokens tab starts a check).

**Wrong.** A press during a check returns with no status line, no Log, no dialog, and the button still looks enabled.

**Drive.**

```
  busy            : True
  button state    : 'normal'
  status after a 2nd press: 'SENTINEL-2'
```

**Fix or Resolution.** Disable the button while a check runs and say so on the status line if it is pressed anyway.

**Check.** The hidden-window drive in `tests/test_config_page.py` starts a check with a stubbed slow probe and requires the button to be `disabled` while busy and the status line to carry the reason on a press. It fails on the old handler.

**Status.** Fixed 2026-10-16.

---

### 25. Four refusals in the images and Prompt Assist handlers leave the status line stale (Low)

**Artifacts.** `salad_studio/app.py:2312-2314` (`_on_image_add_env`), `:2324-2333` (`_on_image_remove_env`'s two refusals), `:4394-4399` ("Remove selected" with only catalog rows), `:2785-2794` (Prompt Assist's no-key refusal).

**Wrong.** Each reports through a dialog or the reply box and returns without writing `self.status`, so the status line keeps the last success.

**Drive.**

```
  add env refused   status: 'SENTINEL-3'   dialogs: [('Salad Studio', 'Name is required.')]
  remove refused    status: 'SENTINEL-LORA'  dialogs: [… only extras added here can be removed.]
  Prompt Assist     status: 'SENTINEL-1'   helper_state: 'No DeepSeek key. Save one on the Tokens tab'
```

**Fix or Resolution.** Each refusal writes the status line with the sentence the dialog or the reply box carries.

**Check.** The hidden-window drives in `tests/test_config_page.py` press each of the four refusals and require the status line to carry the cause; all four fail on the old handlers.

**Status.** Fixed 2026-10-16.

---

### 26. `generator.wait_gateway_ready`'s `/ready` failure message can never show (Low)

**Artifacts.** `salad_studio/generator.py:180-185` (the trailing block), against the in-loop raise at `:179`.

**Wrong.** The loop over `_READY_TRIES` ends every final iteration by returning or raising, so the block after it never runs.

**Drive.**

```
   179         raise RuntimeError(msg + f"  (pre-probe /ready failed for {who})")
   180     msg = explain_http(int(last_code), last_body, url, method="GET")
   181     _log("error", msg)
   182     raise RuntimeError(
   183         f"{msg}  (pre-probe /ready failed for {who} after {_READY_TRIES} probes over "
   184         f"~{ready_budget_s() // 60} minutes; last status HTTP {int(last_code)})"
   185     )
```

**Fix or Resolution.** The final-attempt `raise` became a `break` (`generator.py:169-172`, `:180-182`), so the trailing block at `:185-189` runs. Measured: the message went from `Error 522: Connection timed out  (pre-probe /ready failed for https://example.salad.test/)` to the same sentence plus `after 118 probes over ~90 minutes; last status HTTP 522`.

**Check.** `tests/test_generator.py::WaitReady.test_the_last_probe_names_the_probe_count_and_the_budget` drives the rebuilt old function and the shipped one in one test.

**Status.** Fixed 2026-10-16.

---

### 27. `generator._probe_url`'s "no probe worked" return can never show (Low)

**Artifacts.** `salad_studio/generator.py:391` (`return 0, "no probe worked"`), inside `_probe_url` (366-391).

**Wrong.** The loop tries `HEAD` then `GET`; the only `continue` is under `method == "HEAD"`, so the `GET` pass always returns and the trailing return is unreachable.

**Drive.** Before the fix the return was `(0, 'URLError')`; after it the summary is `(0, 'no probe worked')`.

**Fix or Resolution.** The `GET` pass now `break`s out to the summary (`generator.py:393-398`); HEAD keeps its own reason, and HEAD's retryable `HTTPError` still continues to GET. Measured: `(0, 'URLError')` became `(0, 'no probe worked')`.

**Check.** `tests/test_generator.py::CheckLoraUrls.test_a_url_neither_method_answers_reports_the_summary`.

**Status.** Fixed 2026-10-16.

---

### 28. `salad_queue._run`'s "gave up after N attempts" tail can never show (Low)

**Artifacts.** `salad_studio/salad_queue.py:904` (`job.reason = f"gave up after {self.max_attempts} attempts"`), inside `_run` (862-906).

**Wrong.** `next_action` returns `RETRY` only while `attempt < max_attempts`, so the final iteration takes `ACCEPT` or `FAIL`, both of which return before the tail.

**Drive.** Before the fix the job's reason was `'HTTP 503: unavailable'`; after it the reason is `'gave up after 3 attempts'`.

**Fix or Resolution.** `_run` now `break`s when the final attempt fails while the job was BUSY (`salad_queue.py:886-891`), so the tail records the reason; a definitive `FAILED` keeps `reason_of(result)`, and no sleep happens after the last attempt. Measured: the job's reason went from `'HTTP 503: unavailable'` to `'gave up after 3 attempts'`.

**Check.** `tests/test_salad_queue.py::ClassificationTest.test_a_job_that_exhausts_its_attempts_records_the_gave_up_reason`.

**Status.** Fixed 2026-10-16.

---

### 29. `ai_helper._collect`'s trailing return can never show (Low)

**Artifacts.** `salad_studio/ai_helper.py:743` (`return text, attempts, info`), inside `_collect` (697-743).

**Wrong.** The loop over `range(attempts + 1)` raises on its last round, so the trailing return is unreachable.

**Drive.** Before the fix an exhausted reply raised `AiError`; after it returns `('…', 2, truncated=True)`.

**Fix or Resolution.** The last round now falls out to the return (`ai_helper.py:735-743`), and the module and `_collect` docstrings were updated. A still-cut reply now reaches `parse_reply_full`, which either recovers a complete object or reports `ReplyError`. Measured: an `AiError` became `('…', 2, truncated=True)`.

**Check.** `tests/test_ai_helper.py::ACutOffReplyIsContinued.test_an_exhausted_budget_returns_the_stitched_text` and `::ACutOffReplyIsContinued.test_a_cut_reply_the_model_restarted_is_still_recovered`, with the existing still-cut test re-pointed at the stitched fragment.

**Status.** Fixed 2026-10-16.

---

### 30. Seven module-level helpers nothing calls (Low)

**Artifacts.** `salad_studio/theme.py:441` (`palette_snapshot`), `salad_studio/json_highlight.py:82` (`token_kinds`), `salad_studio/graph_view.py:820` (`node_boxes`), `:1063` (`round_polyline`), `:1476` (`_draw_grid`), `:1520` (`_wrap`), `:1536` (`_rounded_rect`).

**Wrong.** A repo-wide scan over every `.py` finds exactly one occurrence of each name, its own `def`.

**Drive.** The scan reports one occurrence per name, the `def` itself, and no `getattr`, subclass or test reference.

**Fix or Resolution.** All seven deleted after a word-boundary scan found no `getattr`, subclass or test reference; `theme.py`'s then-unused `Mapping` import went with them.

**Check.** `tests/test_docs_match.py`'s dead-symbol rule gains the seven names and a `PRE_DELETION_DEFS` copy of the verbatim blocks; the rule reports all seven against the pre-deletion source and none against the shipped text.

**Status.** Fixed 2026-10-16.

---

### Appendix: verified candidates, later fixes, and unreal rows

| Site | Defect | Severity | First noted | Status |
|---|---|---|---|---|
| `docs/workflow/21-klein-image-handoff.md:113` | Names `profiles.route_payload` as the live routing API; the function was deleted. | Medium | 2026-10-14 | Fixed 2026-10-15 (issue 10). |
| `README.md:31`, `salad_studio/README.md:547` | Stated `~14-18 min` for the root suite; measured 29.3 min (1758 s). | Medium | 2026-10-14 | Fixed 2026-10-14 to `~15-30 min`; no check. |
| `salad_studio/app.py:252-254` | The status line had no `wraplength`, so a 215-char refusal was clipped at 1024 px. | Medium | 2026-10-14 | Fixed 2026-10-16 (Closure R1.3). |
| `salad_studio/generator.py:180-185` | The trailing failure block could not run, so the probe-count message never showed. | Medium | 2026-10-14 | Fixed 2026-10-16 (issue 26). |
| `docs/workflow/15:119` | Said the anatomy recipe is `6 steps`; the shipped scheduler is 4. | Medium | 2026-10-14 | Fixed 2026-10-15 (issue 13). |
| `docs/workflow/14:56` | Attributed `ckpt_name` / `lora_name` CLI options to `salad_gen.py`. | Medium | 2026-10-14 | Fixed 2026-10-15 (issue 15). |
| `docs/workflow/18-sdxl-migration-brief.md:129-130` | Cited `doc 15 §261, §280, §338, §441, §519`; doc 15 has no numbered sections. | Low | 2026-10-14 | Historical; doc 18 removed 2026-10-17. |
| `docs/workflow/18:266-267` | Said `test_generator.py` has `21 total`; it has 26. | Low | 2026-10-14 | Historical; doc 18 removed. |
| `docs/workflow/18:209`, `:271` | Two sections numbered `3.3`. | Low | 2026-10-14 | Historical; doc 18 removed. |
| `docs/workflow/17-klein-two-body-anatomy-research.md:411` | Attributed per-position failure reports to the v1.4 page while `:663-668` records none. | Low | 2026-10-14 | Historical; doc 17 removed. |
| `salad_studio/theme.py:441`, `json_highlight.py:82`, `graph_view.py:1063` | Three module-level helpers with no caller. | Low | 2026-10-14 | Fixed 2026-10-16 (issue 30). |
| `salad_studio/ai_helper.py:743` | A `return` after a loop whose last round always raises. | Low | 2026-10-14 | Fixed 2026-10-16 (issue 29). |
| `salad_probe_ages.py:146` | Exits 0 when every plate failed; siblings return 1 or 3. | Low | 2026-10-14 | Fixed 2026-10-15 (issue 12). |
| `tests/test_docs_match.py:189` | `assertIsNot(match, None)` repeats `assertIsNotNone`; it cannot fail. | Low | 2026-10-14 | Fixed by an earlier pass. |
| `tests/test_docs_match.py:231`, `:493` | `AUDIT` assigned twice, byte-identical. | Low | 2026-10-14 | Fixed by an earlier pass. |
| `tests/test_docs_match.py:2` | Docstring said "Three checks"; the module holds 11 classes and 37 tests. | Low | 2026-10-14 | Fixed by an earlier pass. |
| `salad_studio/app.py:5176`, `:5181` | `_on_generate_vast`'s refusals never wrote `self.status`. | Medium | 2026-10-15 | Fixed 2026-10-15 (issue 17). |
| `salad_studio/app.py:4066-4082` | "Remove extra" acted on `sel[0]` of a multi-selection. | Medium | 2026-10-15 | Fixed 2026-10-15 (issue 19). |
| `salad_studio/app.py:1505-1508` | "Check keys" was a silent no-op while a check ran and was never disabled. | Medium | 2026-10-15 | Fixed 2026-10-16 (issue 24). |
| `salad_studio/app.py:3380` | "Convert" reported an import when the box held free text and no workflow. | Low | 2026-10-15 | Fixed 2026-10-15 (issue 11). |
| `salad_studio/app.py:2599-2606` | Prompt Assist's no-key refusal was the only return that skipped the status line. | Low | 2026-10-15 | Fixed 2026-10-16 (issue 25). |
| `salad_studio/salad_queue.py:905-908` | The "gave up after N attempts" tail was unreachable. | Low | 2026-10-15 | Fixed 2026-10-16 (issue 28). |
| `salad_studio/comfy_import.py:2443-2445` | `convert_comfy_graph` never reads `meta_text`, `wf_raw` or `knobs`. | Low | 2026-10-15 | No longer real: unread by design, pinned by a test in HEAD. |
| `tests/test_app_layout.py:2412`, `tests/test_config_page.py:1235` | Two tests drive the refusal path without stubbing `snapshot_gateway`, so they reach the live Salad API with a fake key. | Medium | 2026-10-15 | Open. |
| `tests/test_config_page.py:1030`, `:1108` | `app.gen_queue.idle_stop_s = 3600` writes an attribute nothing reads; the reader is `_idle_stop_s`. | Medium | 2026-10-15 | Fixed 2026-10-16 (Closure R2.13). |
| `tests/test_app_layout.py:1477`, `:2923-2932`, `:3028-3037` | Three window classes clobbered the store paths with no `addCleanup`. | Medium | 2026-10-15 | Fixed 2026-10-16 (Closure R2.14). |
| `salad_studio/graph_view.py:1363`, `:1382` | `GraphPane._soon` and its `destroy` override shipped with no test. | Medium | 2026-10-15 | Fixed 2026-10-16 (Closure R2.15). |
| `salad_studio/prompt_history.py:320` | The "`ts` matches no row → None" rule had no test passing `ts`. | Medium | 2026-10-15 | Fixed 2026-10-16 (Closure R2.16). |
| `docs/workflow/15:139-143` | Mapped node 81 to the NSFW fix and 83 to a penis LoRA; the shipped JSON has 81 = `2763568` and 83 = `2790993`. | Medium | 2026-10-15 | Fixed by an earlier pass; doc 15's chain now names both. |
| `docs/workflow/15:131` | Seed `823441907752101`; both anatomy files use `323175253610296`. | Medium | 2026-10-15 | Fixed by an earlier pass; doc 15 states the shipped seed. |
| `docs/workflow/15:495` | "4 vCPU / 38912 MB RAM"; `studio-metadata.json` says `memory_gb: 30`. | Low | 2026-10-15 | No longer real; the line is gone. |
| `docs/workflow/16-salad-studio-prompt-graph.md:128-129` | "no `layout_xy` fallback"; `layout_xy` is defined and called twice. | Low | 2026-10-15 | Historical; doc 16 removed. |
| `docs/workflow/15:3-8` | The dated banner says `prefetch5`/`prefetch4` while the file, doc 21, doc 23 and the metadata document say `prefetch6`. | Low, deferred | 2026-10-15 | Deferred at `docs/history/59:159` (D7); rewriting a dated note would falsify the record. |
| `salad_studio/app.py:5360-5387` | `_on_generate_vast`'s refusals never wrote `self.status`. | Medium | 2026-10-15 | Fixed 2026-10-15 (issue 17). |
| `salad_studio/app.py:3822`, `:3872-3883` | A kept queue row answered Cancel and Retry with "select a request first". | Medium | 2026-10-15 | Fixed 2026-10-15 (issue 16). |
| `docs/workflow/22:60` | The pointer named three homes that do not hold the fact. | Medium | 2026-10-15 | No longer real; the pointer now names doc 14:37 and doc 23 §1. |
| `docs/workflow/15:201-206` | The `_meta` advice said "keep the blocks on every `LoraLoader`", but no shipped recipe carries one. | Medium | 2026-10-15 | Fixed 2026-10-16 (issue 22). |
| `salad_studio/app.py:441-489` | The scrollable helper set no `xscrollcommand`; controls sat past the right edge. | Medium | 2026-10-15 | Fixed 2026-10-15 (issue 18). |
| `docs/workflow/17:202`, `:290` | Referenced `doc 19 §4`, which no longer exists. | Low | 2026-10-15 | Historical; doc 17 removed. |
| `docs/workflow/23:9`, `:291` | Referenced `doc 15 §0–6` and `§4`, which do not exist. | Low | 2026-10-15 | Fixed 2026-10-15; doc 23 now names existing section titles. |
| `docs/workflow/15:234` | "downloads five files in parallel"; five is the `all` set. | Low | 2026-10-15 | Fixed 2026-10-15; the claim is gone. |
| `salad_studio/generator.py:391` | `return 0, "no probe worked"` was unreachable. | Low | 2026-10-15 | Fixed 2026-10-16 (issue 27). |
| `salad_studio/graph_view.py:820`, `:1476`, `:1520`, `:1536` | Four dead canvas-drawing helpers. | Low | 2026-10-15 | Fixed 2026-10-16 (issue 30). |
| `salad_studio/app.py:2291-2292` | `_on_image_add_env`'s refusal left the status stale. | Low | 2026-10-15 | Fixed 2026-10-16 (issue 25). |
| `salad_studio/theme.py:441`, `json_highlight.py:82`, `graph_view.py:820`, `:1063`, `:1476`, `:1520`, `:1536` | Seven module-level helpers with no caller. | Low | 2026-10-16 | Fixed 2026-10-16 (issue 30). |
| `salad_studio/app.py:4067-4068`, `:1097-1098` | "Refresh Salad logs" is a silent no-op during a poll; the status line stays on the last success and the button is not disabled. | Low | 2026-10-16 | Open. |
| `docs/workflow/22:55` | Cited a line into doc 14 that had moved; the fact sits in the same table's row. | Low | 2026-10-16 | Fixed 2026-10-17; doc 22 now cites doc 14:37. |
| `docs/workflow/17:109`, `:312`, `:401`, `docs/workflow/19:150` | References like "doc 21 §6.2 / §6.7" name list items, not headings. | Low | 2026-10-16 | Historical; docs 17 and 19 removed. |
| `docs/workflow/19` has no `## 4.`, doc 22 no `## 2.`, doc 14 a `## 4b.` with no `## 4.` | Any pointer to those numbers is born dead; no live pointer names one today. | Low | 2026-10-16 | Historical; doc 19 removed. |

---

# Closure, 2026-10-16

This section closes the work the six records' appendices left open, the prune of the living docs, and this document's own consolidation. Every claim was re-read against the tree.

## 1. The rows, re-driven and closed

The split was 5 still real and fixed, 35 already fixed, 7 no longer real, 32 owned by the other workers, and 4 occurrences of the one deferred banner. The five still-real rows, each fixed and proven:

| row | artifact | fix | proof |
|---|---|---|---|
| R1.3 | `salad_studio/app.py:252-254` | the status label moved to `app.py:320-328` and `_wrap_status` (`:357-370`) writes `wraplength = width-16` with a floor of `_STATUS_MIN_WRAP` (`:66`) | `tests/test_app_layout.py::TheStatusLineWrapsInTheWindow.test_a_long_refusal_wraps_inside_a_narrow_window` (`fixed: PASS` / `old: FAIL`) |
| R2.13 | `tests/test_config_page.py:1030`, `:1108` | the writes now set `_idle_stop_s`, the attribute `salad_queue` reads (`salad_queue.py:413`, `:739-744`) | `tests/test_salad_queue.py::LifecycleIdleTest.test_a_timeout_written_onto_the_queue_is_the_one_it_reads` (`fixed: PASS` / `old: FAIL`) |
| R2.14 | `tests/test_app_layout.py:1477`, `:2923-2932`, `:3028-3037` | five window classes save store paths (`_redirect_store` / `_put_stores_back`, `test_app_layout.py:139-156`) and restore them with one `addCleanup` each | `tests/test_app_layout.py::WindowClassesPutTheStoresBack.test_each_class_puts_the_store_paths_back` (`fixed: PASS` / `old: FAIL`) |
| R2.15 | `salad_studio/graph_view.py:1363`, `:1382` | `GraphPane._soon` (`:1351-1368`) and its `destroy` (`:1370-1378`) now have a test | `tests/test_graph_view.py::PaneScheduledWorkIsCancelled.test_destroy_cancels_what_the_pane_scheduled` (`fixed: PASS` / `old: FAIL`) |
| R2.16 | `salad_studio/prompt_history.py:320` | the "`ts` matches no row attaches nothing" rule now has a test | `tests/test_prompt_history.py::PromptHistoryStore.test_attach_image_with_a_ts_that_matches_no_row_attaches_nothing` |

## 2. The two recorded follow-ups

Both were real and both are fixed. The grids no longer grew on a window wider than the grid: `_keep_grid_filling` (`salad_studio/app.py:605-661`) grows the columns to fill the room, grow-only and idempotent. `tests/test_app_layout.py::AGridFillsAPageWiderThanIt` passes on the fix and fails on the old form. Four modules no longer read the user's real `~/.config/salad/studio-queue.json`: `tests/_stores.py` redirects the ledger in each module's `setUpModule` / `tearDownModule`, proved by `tests/test_stores.py::EveryWindowModuleRedirectsTheLedger`.

## 3. The prune

The 13 living docs fell 2971 → 2846 lines (−125, 4.2%), inside the 2852 bar. The cut came from doc 22 (−58), 17 (−38), 19 (−17), 18 (−5), 21 (−2), `README.md` (−1) and `salad_studio/README.md` (−4). Every removal left a one-line pointer to a home the worker opened. The deferred doc-15 banner is byte-for-byte.

## 4. The consolidation

The six dated issue records became this one document (762 lines). It has 0 `### <TAG>,` headings, 31 `###` headings, 30 numbered `### N.` issues, 0 `**Fixed:**` lines and 49 appendix rows. The living-document count fell **20 → 10**.

## 5. History 63, left as written

`docs/history/63-salad-studio-audit-2026-10-16.md` is a dated record and is not edited. Its opening and §9 still say nothing in the repo was changed and that each `**Correction:**` is a proposal; a later pass annotated `**Fixed:**` into the same file, so History 63 now carries 24 `**Fixed:**` lines, which landed after the audit was written. Lines 400 and 411-413 still name `docs/issue-sweep-2026-10-16b.md`, gone with the other five dated issue files. The four proof-line class names that record discussed (`WaitReady`, `CheckLoraUrls`, `ClassificationTest`, `ACutOffReplyIsContinued`) live in this document, in the 2026-10-16 entries. Follow this file for those names.
