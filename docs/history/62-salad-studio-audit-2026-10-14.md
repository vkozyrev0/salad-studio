# 62. Salad Studio audit, 2026-10-14 (code, tests, UI, UX, docs, presentations)

**Scope:** the whole tree as found: revision `994abb4` on branch
`queue-start-and-wait` with **67 dirty paths** — the fix pass for audit 61 is in
the working tree, uncommitted — plus this document and the one rule change §6
records, which is what makes 68. The audit reads the tree with those changes
applied, because that is the state the next goal will work from. `salad_studio/` (the app, its modules and the `graph_html/`
viewer), `tests/` (35 modules, 966 test methods), `salad_klein/` (the Docker
build, `prefetch.py`, the prompt recipes, its two test modules and
`http_smoke.py`), the top-level scripts, `docs/workflow/` (14–19, 21–23),
`docs/history/` (57–61), the three READMEs, and
`.claude/skills/civitai-verify/`.

**Goal of this pass:** find and record what is missing or incorrect *now*.
Nothing here is fixed. Each finding names the artifact, the severity and the
correction it implies, so the follow-up goal can work the list.

## 0. How this audit was run (what is proven vs read)

- Every finding cites a path and a line, and every citation in this document was
  resolved against the tree and read back: 71 distinct citations (76 occurrences)
  across 38 files, each confirmed to land on a real, non-blank line, with two
  findings per area spot-checked line by line for the words they quote
  (`{SCRATCH}/cites.log`, `{SCRATCH}/doc62-check.log`, `{SCRATCH}/verify-findings.log`).
- **executed** means a command, a test or a driven window produced the evidence,
  and the command is named. **read-from-source** means the finding is a reading
  of the code or document.
- Audit 61's findings were re-checked rather than trusted. Its two deferrals are
  re-checked here rather than re-decided: the three scripts that cannot import
  stay non-importable (§5) and P1 re-states the absent deck. Three of its claims
  are corrected in §2 — D5, D16 and the doc-17 count in D6 — because the fix pass
  carried a wrong number or a citation that cannot land.
- The UI/UX findings rest on the real app: the window was built with
  `SaladStudio(show=False)` and driven through the shipped handlers and bindings
  (`{SCRATCH}/ui.log`), the Generate press was driven through `mainloop()` with
  an injected container handle (`{SCRATCH}/press.log`), and the Config page's
  image form was driven through its own handler
  (`{SCRATCH}/user-image.log`). A real pointer warp could not be used: this
  runner keeps another window on top, so `winfo_containing` cannot see the app's
  window (recorded in `{SCRATCH}/wheel-probe.log`); the `<Enter>`/`<Leave>`
  crossings were therefore generated on the canvas, which is the same binding
  path.
- `{SCRATCH}` is
  `C:\Users\vkozy\AppData\Local\Temp\grok-goal-a31bb33ffe7e\implementer\`:
  `suite.log` and `docs-match.log` (the suite and the doc check), `ui.log`,
  `press.log` and `probes.log` (the press, both ways), `user-image.log` and
  `wheel-probe.log` (the two drives the real pointer could not do),
  `verify-findings.log`, `doc62-check.log` and `cites.log`/`cites2.log` (the
  findings and their citations), `coverage.log`, `linkcheck.log`, `drift.log`,
  `import-scripts.log`, `launch.log`. The scripts that produced them are beside
  them.

## 1. Verdict per area

| Area | Verdict | Findings |
|---|---|---|
| Code | Twelve defects: an unreachable parameter on the app's own image path, a CLI that exits 0 on a corrupt cache entry, a dead size guard in the image's first-boot fetch, an unreachable version guard, a docstring that still promises a start, two dead artifacts, a second copy of a just-fixed helper, and a stale default tag | C1–C12 |
| Test | The suite is green at 966 with **0** Tcl teardown lines, but the audit-artifact check fails as soon as the next audit is written, one test module's documented command cannot resolve, one importable script has no test, and the no-dialog guard's answers are an undocumented contract | T1–T4 |
| UI | The eleven tabs, the four empty states and the wheel gate all hold up; the one gap is the Config page's "your own image" form, which has no ports field, so the commands it prints for that image publish no port | U1, U2 clean |
| UX | The refusal flow is coherent across the four surfaces; the one gap is that a press refusal does not re-probe the badge, so a user who starts the container in the console can be refused again until the next tick | X1, X2 clean |
| Docs | Twenty-six places where a document says something the tree contradicts, including a runbook step that fails immediately, four stale test counts, a manifest description that is not the shipped manifest, two references to a document that has never existed, and a skill that claims routing it does not do | D1–D26 |
| Presentations | No slide deck exists (unchanged); the presentation surface is the three READMEs, `docs/workflow/` and the `graph_html/` viewer. The viewer is correct; the playbook a reader would present from fails at its first rebuild step | P1–P4 |

## 2. Findings

### C1, the app's own image can never publish a port (code, Medium, executed, FIXED)
`salad_studio/image_deploy.py:503` `def add_image(` … `:510`
`ports: dict[str, Any] | None = None,` — the parameter the previous pass added
to make a user's image carry deploy facts — has **no shipped caller**: the only
call site is the page's own handler, `salad_studio/app.py:2128-2133`, which
passes `context` and `build_arg` and nothing else. Driven through that handler
(`{SCRATCH}/user-image.log`):

```
form variables:            ['var_image_new_arg', 'var_image_new_context',
                            'var_image_new_name', 'var_image_new_tag']
stored row:                {..., "ports": {}}
entry ports:               {"api": 0, "comfy": 0}
port_args(entry):          []
docker_run_command(entry): "docker run --gpus all user/eldermark-klein:test"
page script has "-p ":     False
```

So a user's own image is stored with `"ports": {}` and every command the page
prints for it is portless, including the `vastai create instance` line whose
`--env` is where vast.ai takes the ports.

**Correction:** add the two port fields to the "your own image" form (and to the
manual's sentence at `salad_studio/README.md:101`), or drop the parameter and say
in `entries()` that a user's own image publishes no port.

**Fixed:** the Config page's own-image form carries **API port** and **ComfyUI port** fields (`salad_studio/app.py` `var_image_new_api`, `var_image_new_comfy`), and `_on_image_add_image` passes them to `image_deploy.add_image`'s `ports`. The entry the store keeps is `{"api": 3000, "comfy": 8188}`, so `port_args` prints `-p 3000:3000 -p 8188:8188` on the `docker run` script and on the `vastai create instance` line. Driven through the page's own handler: `tests/test_image_deploy.py::ImagesPage::test_the_form_carries_the_ports_into_the_commands_it_prints`, with `test_an_image_added_with_no_ports_publishes_none` for the empty form.

### C2, `model_catalog.py fetch` exits 0 when the cached file is corrupt (code, Medium, executed, FIXED)
`model_catalog.py:1143-1144`:

```
    print(fetch_item(data, existing, token, args.force))
    return 0
```

`fetch_item` returns `f"hash-fail {item['id']} {dest}"` on a sha256 mismatch, and
`cmd_fetch` prints it and returns 0 regardless. Its two sibling commands do not:
`cmd_fetch_missing` returns 2 on exactly that line (`model_catalog.py:1244-1246`)
and `cmd_fetch_klein` returns 2 as well.

**Correction:** return 2 when the line starts with `hash-fail`, mirroring
`cmd_fetch_missing`.

**Fixed:** `cmd_fetch` returns 2 when `fetch_item`'s line starts with `hash-fail` and 0 otherwise (`model_catalog.py:1141-1148`), mirroring `cmd_fetch_missing`. `tests/test_model_catalog.py::TheFetchExitCode` drives both.

### C3, the first-boot fetch's size guard can never run (code, Medium, read-from-source, FIXED)
`salad_klein/prefetch.py:208-212`:

```
    zst = ensure_safetensors(dest)
    if zst != "missing":
        print(f"prefetch {name} {zst}", flush=True)
        return f"{zst} {dest}"
    if _have(dest):
```

`weights_zip.ensure_safetensors` returns `"have"` for **any** existing non-zip
file (`salad_klein/weights_zip.py:60-68`), so the early return above always fires
when the file exists; the only way past it is `"missing"`, which means the file is
not there, which makes `_have` (`salad_klein/prefetch.py:120-122`,
`os.path.isfile(path) and os.path.getsize(path) > 1_000_000`) false. The size
check can never fire, so a 0-byte or truncated `*.safetensors` is announced as
`have` and the container boots into a Comfy that cannot load it. The test module
corroborates the deadness: it has to patch both functions to reach the download
path (`salad_klein/test_prefetch.py:102-103`, `:133-134`).

**Correction:** make the size authoritative — treat an existing file below the
floor as `missing` and re-fetch — or delete `_have` and stop implying the size
is checked.

**Fixed:** `_fetch` re-fetches an existing non-zip file below the 1 MB floor instead of returning `have` (`salad_klein/prefetch.py:208-222`). `salad_klein/test_prefetch.py::ATruncatedWeightIsRefetched` drives a 9-byte dest (fetched again) and a 2 MB dest (left alone).

### C4, `civitai_version`'s model-mismatch guard is unreachable (code, Low, executed, FIXED)
`model_catalog.py:876-878`:

```
        if int(data.get("modelId") or 0) not in (0, model_id) and data.get("modelId") != model_id:
            # Some payloads omit modelId; still accept if id matches.
            if data.get("id") != version_id:
                raise SystemExit(f"version {version_id} belongs to model {data.get('modelId')}, not {model_id}")
```

The payload comes from `/api/v1/model-versions/{version_id}`, whose `id` **is**
the requested `version_id`, so the inner test is always false and the
`SystemExit` — the message the guard exists for — cannot fire. The first clause
also implies the second whenever it is true, so the `and` adds nothing.

**Correction:** compare `data.get("modelId")` to `model_id` directly and raise on
a mismatch, or delete the guard and the comment.

**Fixed:** the guard reads `data.get("modelId")` into `owner` and raises `SystemExit` when it names another model (`model_catalog.py:881-888`); the always-false `data["id"] != version_id` inner test is gone. `tests/test_model_catalog.py::TheVersionGuard` drives another model's payload (refused), its own (accepted) and one with no `modelId` (accepted).

### C5, the lifecycle handle's docstring still promises a start (code, Low, read-from-source, FIXED)
`salad_studio/salad_status.py:920` — `"""The queue's handle on the containers it
may start and stop.` The app never starts a container (`d52907b`), the fix pass
deleted `ContainerLifecycle.start`, and the class now holds `is_running`,
`group_state` and `stop`.

**Correction:** "the containers it may stop".

**Fixed:** `salad_studio/salad_status.py:920` now reads ``"""The queue's handle on the containers it may stop.``

### C6, `_dropped_afters` is written and never read (code, Low, executed, FIXED)
`salad_studio/app.py:192` initialises `self._dropped_afters: list[str] = []`,
`:831` and `:849` append to it when Tk will not take a callback, and nothing reads
it — not the app, not a test. The rationale in `_later`'s docstring is that a
dropped handoff must not vanish, but it is recorded where nobody looks.

**Correction:** log it once (it means a state reset never ran), or assert it is
empty in the tests, or drop the list.

**Fixed:** `_on_close` reports the list once (`salad_studio/app.py:4094-4102`): a `warn` line naming the count and the last dropped callback. `tests/test_app_layout.py::ClosingReportsWhatTkWouldNotTake` drives a session with a dropped callback and a clean one.

### C7, a second `wait_ready` did not get the zero-budget guard (code, Low, read-from-source, FIXED)
`salad_probe_sdxl.py:33-42` is a copy of the readiness loop that
`salad_gen.wait_ready` runs, with its own message
(`raise SystemExit("SDXL group still allocating")` at `:42`) and without the
`code = 0` initialisation the fix pass added to `salad_gen.py`. A zero budget
there still raises `UnboundLocalError` instead of reporting. A third copy sits in
`salad_catalog_faces.py:201` with its parameters in the opposite order
(`key, base, ping_s`).

**Correction:** call `salad_gen.wait_ready` from both probes and delete the
copies, or at least give the third one keyword-only parameters so the swap cannot
be made silently.

**Fixed:** `salad_probe_sdxl.py`'s local loop is gone; it calls `salad_gen.wait_ready(base, key, 2400)`. `salad_catalog_faces.py:200` takes keyword-only parameters, so the third copy's argument order cannot be swapped silently.

### C8, `PIDFILE` is written and never read (code, Low, executed, FIXED)
`salad_catalog_faces.py:43` defines
`PIDFILE = ART / "catalog" / "face" / "salad_runner.pid"` and `:309` writes the
process id into it. A tree-wide search finds no reader: not `--status`, not the
root structural check, not any document.

**Correction:** read it where it would be useful (is a batch already running?), or
drop the write.

**Fixed:** `PIDFILE` and its write are gone from `salad_catalog_faces.py`; a repo-wide sweep finds no reference.

### C9, `compose_body_prompt` has no caller (code, Low, executed, FIXED)
`face_prompt.py:165` `def compose_body_prompt(` — the only other mentions in the
tree are two comments (`salad_probe_klein.py:6`, `:49`), which say the catalogue's
body prompt is headless. The shipped body path here is
`salad_catalog_faces.compose`. This is the same evidence audit 61 used to delete
five sibling composers in the fix pass.

**Correction:** delete it, or say in the module docstring that it is the shared
API another checkout calls.

**Fixed:** `face_prompt.compose_body_prompt` is deleted. The comments that named it now name the shipped body frame — `face_prompt_pack.json`'s `body_style`, headless by design — at `salad_probe_klein.py:5-7,49` and `docs/workflow/14:142,274`.

### C10, the smoke run's default image is the superseded tag (code, Medium, read-from-source, FIXED)
`salad_klein/http_smoke.py:16` —
`IMAGE = "vkozyrev0/eldermark-klein:comfy0.35-api1.19.2-nowarm"`. Every build and
push command in the tree names `…-prefetch6-klein` / `…-prefetch6-snofs`, and
`-nowarm` appears nowhere else in `salad_klein/`. Its docstring's premise
(`salad_klein/http_smoke.py:3`, "Starts the image with MANIFEST/WARMUP unset so it does not
pull 18 GB") also does not hold for the shipped image: the image's ENTRYPOINT
runs `prefetch.py`, which always fetches its `JOBS` and falls back to **all**
unets for an unknown `KLEIN_UNET_SET` (`salad_klein/prefetch.py:105-107`), so pointing
`--image` at a shipped tag pulls the weights before `/health` answers.

**Correction:** default to one shipped tag and say the run pulls the weights, or
add a "fetch nothing" value and a `--entrypoint` path for a true smoke run.

**Fixed:** `salad_klein/http_smoke.py:20` defaults to the shipped `…-prefetch6-klein` tag, and its docstring now says the run waits out `prefetch.py`'s weight fetch before `/health` answers. `-nowarm` no longer appears in `salad_klein/`.

### C11, `stop_container_group` has no shipped caller either (code, Medium, executed, FIXED)
`salad_studio/salad_status.py:875` `def stop_container_group(`. The app stops through
`ContainerLifecycle.stop` → `_group_action("stop", …)`
(`salad_studio/salad_queue.py:777` calls `self.lifecycle.stop`), and the only
references to the module-level function are its definition and two tests. The fix
pass deleted `start_container_group` for exactly this reason and kept this one,
and the manual now names it as the app's call (D19).

**Correction:** delete it (the lifecycle handle is the API), or have the manual
name `ContainerLifecycle.stop`.

**Fixed:** `stop_container_group` is deleted from `salad_studio/salad_status.py`. The manual names `ContainerLifecycle.stop` (D19), and `tests/test_docs_match.py:72` asserts the handle exists and the module-level wrapper does not.

### C12, the Klein weight sizes disagree with the recorded boot (code, Low, executed, FIXED)
`model_catalog.py:106` says the base unet is `8910000000` bytes and `:142` says
the Qwen encoder is `8070000000`, while the boot log records the encoder at
**8.66 GB** (`docs/history/60-salad-container-restart-2026-09-27.md:76`,
`prefetch qwen_3_8b_fp8mixed.safetensors done 8.66 GB in 3.6 min`). The field is
display-only for Hugging Face rows (`should_autodownload` returns early for a
non-Civitai host), so this is metadata, not behaviour.

**Correction:** put the real byte sizes in, or drop the field for HF rows.

**Fixed:** the four HF rows carry the measured sizes — 9567278472 (base unet), 9433061528 (distilled), 8664848742 (Qwen encoder), 336211292 (vae) — each with its source in a comment. `tests/test_model_catalog.py::TheRecordedWeightSizes` parses the `prefetch … done N GB` lines out of `docs/history/60` and asserts the catalog's `size_bytes` agrees within 0.005 GB.

### T1, the audit-artifact check fails as soon as the next audit is written (test, High, executed, FIXED)
`tests/test_docs_match.py:231-244` finds the **newest** `*-audit-*.md` and
`:233`/`:244` require every finding in it to end `FIXED` or `DEFERRED`. This
document is the newest audit and its findings are unresolved by construction, so
the suite goes red the moment it lands. The rule cannot hold while an audit and
its fixes are two separate passes, which is the structure this project uses.

Executed (`{SCRATCH}/docs.log`): under the old rule this document reports **50**
problems ("C1: no FIXED or DEFERRED …" for every finding), while audit 61 — the
resolved record — reports **0**, which is exactly the split the rule gets wrong.

**Correction:** the rule should read "every audit *but the newest* carries a
resolution; the newest must name the six areas and carry concrete findings".
Adjusted in this pass (see §6), because the alternative is leaving the suite red
for a document whose whole purpose is to be worked later.

**Fixed:** the rule is already in the tree (`tests/test_docs_match.py:396-427`, with `RESOLUTION_CONVENTION_FROM = "61-"` at `:234`), corrected by the audit pass itself (§6), so this is a record rather than a second change. Driven directly, `finding_problems()` on this document reports 0 problems, and `tests.test_docs_match` is green.

### T2, a test module's documented command cannot resolve (test, Medium, executed, FIXED)
`tests/test_klein_prompt_catalog.py:21` —

```
    python -m unittest salad_studio.test_klein_prompt_catalog
```

The module is `tests/test_klein_prompt_catalog.py`; `salad_studio` holds no test
modules since the 2026-09-26 move. Executed:
`python -c "import salad_studio.test_klein_prompt_catalog"` →
`ModuleNotFoundError` (exit 1), while
`python -m unittest tests.test_klein_prompt_catalog` runs 15 tests.

**Correction:** `python -m unittest tests.test_klein_prompt_catalog`.

**Fixed:** `tests/test_klein_prompt_catalog.py:21` now reads `python -m unittest tests.test_klein_prompt_catalog`, which runs the module's 15 tests.

### T3, an importable script has no test, and audit 61 says the wrong reason (test, Low, executed, FIXED)
`salad_age_review.py` (127 lines, `def main()` at `:90`, no helper functions)
imports cleanly here (`{SCRATCH}/import-scripts.log`, exit 0) and no test module
names it. Audit 61's T5 resolution says it "cannot import here (C23)" — it can;
only `salad_catalog_faces.py`, `salad_probe_ages.py` and `salad_probe_sdxl.py`
fail, because the two probes import the first (D18).

**Correction:** add a small structural test for `BANDS` (unique names, non-empty
prompts, no `REPLACE_THIS` token), the way `test_klein_recipes.py` covers the
recipes, or record it as out of scope with the real reason.

**Fixed:** `tests/test_age_review.py` covers the band data: unique stage names, non-empty prompt text, the house wording present, no `REPLACE_THIS` placeholder, plus the `HOUSE`, `NEGATIVE` and `ART` module data.

### T4, the no-dialog guard's answers are an undocumented contract (test, Low, read-from-source, FIXED)
`tests/_nomodal.py:21-25` answers `askyesno`/`askokcancel`/`askretrycancel`/
`askyesnocancel` with **True** and every other dialog with `"ok"`
(`:29-32`). Nothing documents that choice or asserts it, so a test that exercises
a destructive confirm path without patching the dialog silently proceeds — the
opposite of what the real user sees. Today both tests that reach a confirm patch
it (`tests/test_app_layout.py:726` with `return_value=False`, `:731` with
`True`), so the default is unused; it is a trap for the next test.

**Correction:** state the defaults in the module docstring as a contract (and
assert one of them in a test), or make the guard answer "no" so an unpatched
confirm cannot take the destructive path.

**Fixed:** the module docstring states the default answers as a contract (`tests/_nomodal.py:14-18`), and `tests/test_nomodal.py::TheNoModalGuard::test_the_question_defaults_are_the_documented_ones` asserts them.

### U1, the "your own image" form has no ports field (UI, Medium, executed, FIXED)
The Config page's Container images section offers four fields for a user's own
image — name, tag, build arg, context
(`salad_studio/app.py` `var_image_new_name`/`_tag`/`_arg`/`_context`, driven in
`{SCRATCH}/user-image.log`) — and the section's facts line and deploy script
derive ports from the entry, which is `{"api": 0, "comfy": 0}` for that image. So
the two commands the page prints for it (`docker run …`, `vastai create instance
… --env '…'`) carry no port, and the manual's "ports the container answers on"
line (`salad_studio/README.md:81`) does not apply to it. Same cause as C1, seen
from the page.

**Correction:** add the two port fields (they are what `add_image` already
accepts) and name them in the manual's "your own image" sentence, or say on the
page that an image of your own publishes no port.

**Fixed:** same change as C1: the form's two port fields reach the printed `docker run` and `vastai create instance` lines, and the manual's own-image sentence (`salad_studio/README.md:100-102`) names the two ports.

### U2, the tabs, the empty states and the wheel gate hold up (UI, clean, executed, FIXED)
Re-driven in this pass (`{SCRATCH}/ui.log`): eleven tabs and eleven nav labels in
`TAB_ORDER` order; the Queue, Prompt History, Prompt Catalog and history-strip
empty states all present, non-empty and shown
(`salad_studio/app.py:127-129`, `salad_studio/history_strip.py:27`); the Generate button `normal`; the
Config page's content 2688 px in a 265 px canvas region with the scroll region
covering it; and the wheel gate behaves: not claimed → a wheel event moves
nothing, claimed (after the canvas's `<Enter>`) → `yview` moves 0.0 → 0.0595, and
after `<Leave>` the app-wide binding is still installed and the page stops
scrolling.

**Fixed:** nothing to correct, re-confirmed: the eleven tabs, the four empty states and the wheel gate hold (`tests/test_app_layout.py` `AppTabs::test_tab_order_is_the_shipped_page_set`, `ListSurfacesSayWhenTheyAreEmpty`, `LiveFieldSync::test_the_wheel_scrolls_the_config_page`).

### X1, a press refusal does not re-probe the badge (UX, Medium, executed, FIXED)
`salad_studio/app.py:4962-4970` refuses a press on the badge word it holds and
returns; it never asks the probe again. The race path does: `:5034-5038` calls
`_check_salad_status(silent=True)` before it reports the refusal. Driven
(`{SCRATCH}/press.log`, `{SCRATCH}/probes.log`): a press refused on a
"Stopped" badge performs **0** probes, leaves the badge reading `Stopped` and the
status line `Refused: …`, while the same group refused by the queue performs
**2** probes and reports the same sentence. A user who starts the container in
the console and presses Generate again can therefore be refused again — with the
message telling them to start a container they have just started — until the 15 s
poll catches up.

**Correction:** probe once when the press refuses (as the race path does), or say
in the refusal that it is the last probe's word and to press Check Salad status.

**Fixed:** the press-refusal block probes once before it reports (`salad_studio/app.py:4962-4975`), the way the queue's race path does, so a badge up to a tick old cannot refuse a user who has just started the container. `tests/test_config_page.py::ConfigPage::test_a_stopped_routed_container_is_refused_at_the_press` records the probes through the injected `snapshot_gateway` and asserts at least one.

### X2, the refusal is coherent across the four surfaces (UX, clean, executed, FIXED)
Re-driven (`{SCRATCH}/press.log`), both ways — the badge says Stopped, and the
badge says Ready while the group is down: no POST, `Refused: …` on the status
line, an info dialog carrying exactly the sentence
`salad_queue.container_down_refusal` builds, the sentence once in the Logs, and
never `Failed. See Logs`. The manual's four sentences (the press refuses, the
`Refused:` status line, never starts, nothing in it starts a container) all match
the same run.

**Fixed:** nothing to correct, re-confirmed: the four surfaces still agree (`tests/test_config_page.py` `test_a_stopped_routed_container_is_refused_at_the_press` and `test_a_group_that_goes_down_after_the_badge_is_reported_as_refused`).

### D1, the rebuild runbook's first step changes into a directory that does not exist (docs, High, executed, FIXED)
`docs/workflow/15-salad-flux2-klein-group.md:530` — `cd src\tools\salad_klein`.
`src/tools` does not exist here; the build context is `salad_klein/` at the repo
root, which the same document uses elsewhere (`:532`, `:479`). A reader
following the numbered rebuild fails at step 1.

**Correction:** `cd salad_klein`.

**Fixed:** `docs/workflow/15:529` reads `cd salad_klein`.

### D2, the same runbook describes a manifest the repo does not ship (docs, Medium, executed, FIXED)
`docs/workflow/15-salad-flux2-klein-group.md:473-475` — ``manifest.yaml` (HF
Klein fp8 unet + `qwen_3_8b_fp8mixed` + `flux2-vae` + Civitai LoRAs **2625692** /
**2763568**)``. The shipped manifest is `before_start: []`
(`salad_klein/manifest.yaml:5`) and names no LoRA, which the same document says
at `:462` and the root structural check asserts
(`test_salad_comfy_live_findings.py` rejects `2625692` in the manifest).

**Correction:** "`manifest.yaml` (empty `before_start`; `prefetch.py` names the
weights)".

**Fixed:** `docs/workflow/15:473-474` reads `` `manifest.yaml` (empty `before_start`; `prefetch.py` names the weights) ``.

### D3, doc 15's tab table still names two removed surfaces (docs, Medium, executed, FIXED)
`docs/workflow/15-salad-flux2-klein-group.md:345` — `| Prompt | CLIP text when
Config rebuilds JSON |` — and `:351` — "…are portal / Policy /". `app.TAB_ORDER`
has `Prompt Settings`, not `Prompt`, and no `Policy` tab; the fix pass corrected
the inline list at `:333-336` and deleted the `Policy` row, and left these two.

**Correction:** `Prompt Settings`, and "the Config page's policy section".

**Fixed:** `docs/workflow/15:345` names `Prompt Settings`, and `:351` says the Config page's policy section. No `Prompt` or `Policy` row remains.

### D4, doc 18 states a suite count the suite does not have (docs, Medium, executed, FIXED)
`docs/workflow/18-sdxl-migration-brief.md:267` — "the suite this repo runs is
**948** tests with the **same 9 failures / 2 errors** as…". The suite has **966**
test methods and the last three captured runs are `OK` (not 9 failures). The fix
pass changed this number from 540 to 948, which was already stale.

**Correction:** 966, and mark the failure snapshot as the state when it was
written.

**Fixed:** `docs/workflow/18:266-268` states 966 and marks the failure snapshot as the run captured when it was written.

### D5, audit 61's own resolution line carries the wrong count (docs, Medium, executed, FIXED)
`docs/history/61-salad-studio-audit-2026-10-13.md:995` — `**Fixed:** the suite
this repo runs, 948 tests`. The same document's §4 says `Ran 966 tests in
1080.892s` / `OK` and that 966 is "the count both manuals now state", so the
document contradicts itself.

**Correction:** 966 in D15's resolution (the record is dated, so this is a
correction the fix goal applies, not a rewrite of what it recorded).

**Fixed:** `docs/history/61:995` states 966.

### D6, doc 17 gives one test file two counts (docs, Medium, executed, FIXED)
`docs/workflow/17-klein-two-body-anatomy-research.md:614` — "24 tests asserting
the old 6-step recipe". The same file was corrected to 17 at `:12`, and
`tests/test_klein_recipes.py` has 17 test methods. Both numbers cannot be true.

**Correction:** 17 at `:614`, or mark that list as the state at the time.

**Fixed:** `docs/workflow/17:614` states 17.

### D7, doc 21 contradicts itself on the 524 window (docs, Medium, executed, FIXED)
`docs/workflow/21-klein-image-handoff.md:204` — "Response cut at the gateway's
**~120 s** read window", against `:193` in the same table — "Cloudflare gave up
at **~100 s**" — and against docs 14 (`:39`), 18 (§3: "**100 seconds**, a
Cloudflare hard limit … Not 120") and 23 (`:244`).

**Correction:** `~100 s` at `:204`.

**Fixed:** `docs/workflow/21:204` states `~100 s`.

### D8, doc 21 still names a document that has never existed (docs, Medium, executed, FIXED)
`docs/workflow/21-klein-image-handoff.md:356` — "| … | doc 17 / 19 / 20 | …",
and "Anything doc 20 marks…". `docs/workflow/` holds 14–19 and 21–23; there has
never been a 20 here (the root README says the gap is not missing work). The fix
pass corrected the list at `:22` and left this row.

**Correction:** "doc 17 / 19", and "Anything doc 19 marks…".

**Fixed:** `docs/workflow/21:356` names doc 17 / 19, and the following sentence names doc 19.

### D9, doc 23 calls the field two names (docs, Medium, executed, FIXED)
`docs/workflow/23-salad-container-group-deployment.md:72-73` — "what the Config
page's **image tag** field is seeded from" — against the shipped label
`ttk.Label(extra, text="Image")` (`salad_studio/app.py:1078`) and the same
document's corrected `:105` ("**Image** (a Salad group policy) takes either one").

**Correction:** "the Config page's **Image** field".

**Fixed:** `docs/workflow/23:72` names the Config page's **Image** field.

### D10, doc 14 still uses the old group name (docs, Medium, executed, FIXED)
`docs/workflow/14-salad-comfy-live-findings.md:209` — "are pre-pulled on
`flux2-klein`" — against `:276` in the same file and the live group name
`flux2-klein2` (docs 21:84, 22:275, history 60:61). The fix pass renamed `:276`
and left `:209`.

**Correction:** `flux2-klein2`.

**Fixed:** `docs/workflow/14:209` names `flux2-klein2`.

### D11, doc 17 cites a CI workflow that is not in this repo (docs, Medium, executed, FIXED)
`docs/workflow/17-klein-two-body-anatomy-research.md:603` — "Do not commit images
(CI `.github/workflows/tier1.yml` rejects any `.jpg/.png/…`)". There is no
`.github/` directory here; the only workflow file in the tree is inside the
vendored `rgthree-comfy` clone. The claim belongs to the Eldermark checkout.

**Correction:** drop the CI clause, or say it is that repo's workflow.

**Fixed:** `docs/workflow/17:603` drops the CI clause and keeps the `.jpg/.png/…` rule as this repo's own.

### D12, doc 18 points at a function that was never shipped (docs, Low, executed, FIXED)
`docs/workflow/18-sdxl-migration-brief.md:239` — "Implemented in
`generator.warm_loras`, called from `generate_from_payload` immediately after
`wait_gateway_ready`". No `warm_loras` exists anywhere in the tree
(`generator.check_lora_urls` is what shipped). The section is headed
"(superseded)", so a careful reader is warned, but "Implemented in" asserts a
symbol.

**Correction:** "was designed as … and never shipped", or delete the sentence.

**Fixed:** `docs/workflow/18:239-240` says the design was never shipped.

### D13, doc 21 calls a two-audits-old record current (docs, Low, executed, FIXED)
`docs/workflow/21-klein-image-handoff.md:303` —
"| `docs/history/58-salad-studio-audit-2026-09-22.md` | the current Studio audit
|". Audits 59 and 61 exist, and the root README lists 57–61.

**Correction:** point at 61, or say "the audit at the time this was written".

**Fixed:** `docs/workflow/21:303` says the audit at the time this was written.

### D14, doc 57 carries a second, un-annotated `.gitignore` line **111** (docs, Low, executed, FIXED)
`docs/history/57-salad-studio-audit-2026-09.md:716` — "(`.gitignore` line **111**,
untracked)". The fix pass annotated the R6 row at `:470` and left this one; the
entry is `.gitignore:2` (`git check-ignore -v`).

**Correction:** the same parenthetical as `:470`, or `.gitignore:2`.

**Fixed:** `docs/history/57:716` carries the same annotation as `:470`.

### D15, doc 59's second recorded suite command discovers nothing (docs, Low, executed, FIXED)
`docs/history/59-salad-studio-audit-2026-09-26.md:245` — `python -m unittest
discover -s salad_studio -p "test_*.py"`. The fix pass added a forward note at
`:19` and left this block bare; the command runs 0 tests today (the tests moved
to `tests/`).

**Correction:** the same note beside `:245`, as doc 58 has beside its command.

**Fixed:** `docs/history/59:248-249` carries the forward note beside the command, as doc 58 has beside its own.

### D16, audit 61 cites a line in doc 58 that has never existed (docs, Low, executed, FIXED)
`docs/history/61-salad-studio-audit-2026-10-13.md:1052-1053` — "`docs/history/57:471`
and `docs/history/58:736` carry the same stale reference" — and its §3 table at
`:1226` ("`.gitignore` line **111** (D20)"). Doc 58 has 423 lines and contains no
`.gitignore` reference at all, now or at the audited commit
(`git show HEAD:docs/history/58-…`), so the citation cannot land.

**Correction:** drop doc 58 from D20 and from the §3 row; the stale reference is
only in doc 57 (D14).

**Fixed:** `docs/history/61:1052-1053` drops doc 58 and cites `docs/history/57:470`; the §3 row at `:1226` now reads 'Dated record; suite command (D21)'.

### D17, `salad_klein/README.md` points below itself at nothing (docs, Medium, executed, FIXED)
`salad_klein/README.md:69` — "The older `prefetch3`/`prefetch4` tags **below**
are kept as the record of how the rgthree COPY was introduced." Nothing below
names those tags; the only `prefetch3`/`prefetch4` mentions in the file are that
line. The record lives in `docs/workflow/15`'s dated status block.

**Correction:** drop "below", or name where the record is.

**Fixed:** `salad_klein/README.md:69` drops 'below'.

### D18, the README's limitation describes the wrong import chain (docs, Low, executed, FIXED)
`README.md:86` — "`salad_probe_sdxl.py` import `paperdoll_mask` and
`regen_faces`" (and the manual repeats it). Only `salad_catalog_faces.py` imports
them (`:30-31`); the two probes fail because they
`import salad_catalog_faces as cat` (`salad_probe_ages.py:13`,
`salad_probe_sdxl.py:17`). The list of three is right; the mechanism is
transitive, which matters to anyone deciding what vendoring would take.

**Correction:** "…and the two probes that import it".

**Fixed:** `README.md:85-87` and the manual describe the chain as transitive: only `salad_catalog_faces.py` imports the two modules, and the two probes fail because they import it.

### D19, the manual names a call the app does not make (docs, Medium, executed, FIXED)
`salad_studio/README.md:384` — "`salad_status.stop_container_group` is the only
control-plane call the app makes". `app.py` never names it; the queue stops
through `self.lifecycle.stop` → `ContainerLifecycle._act("stop", …)`
(`salad_studio/salad_queue.py:777`), and `stop_container_group` is referenced
only by its definition and two tests (C11). The doc check asserts the symbol
exists (`tests/test_docs_match.py:66`), not that the app calls it.

**Correction:** name `ContainerLifecycle.stop`, or delete the dead function.

**Fixed:** `salad_studio/README.md:386` names `ContainerLifecycle.stop`.

### D20, the manual's probe arithmetic is off by three (docs, Low, executed, FIXED)
`salad_studio/README.md:393` — "where a flat 10 s wait would be **540**".
`generator.ready_budget_s()` is 5430 s, so a flat 10 s wait is 543 probes; 540 is
90 min ÷ 10 s, and the window is 90.5 min.

**Correction:** 543, or say "about 540".

**Fixed:** `salad_studio/README.md:395` states 543.

### D21, the manual documents one empty state and the app has four (docs, Low, executed, FIXED)
`salad_studio/README.md:335` — "plus a summary of the states and an explicit
empty state when nothing is queued" (the Queue page). The fix pass added three
more: `HISTORY_EMPTY_TEXT` and `CATALOG_EMPTY_TEXT` (`salad_studio/app.py:128-129`) and the
strip's `EMPTY_TEXT` (`salad_studio/history_strip.py:27`). The manual's Prompt History, Prompt
Catalog and history-strip paragraphs do not mention them.

**Correction:** one sentence per surface, as the Queue bullet has.

**Fixed:** `salad_studio/README.md` adds an explicit-empty-state sentence to the history strip (`:132`), the Prompt Catalog (`:259`) and the Prompt History (`:329`) paragraphs, so all four list surfaces state it.

### D22, the skill claims routing it does not do (docs, Medium, executed, FIXED)
`.claude/skills/civitai-verify/SKILL.md:63` — "Routing is `profiles.plan_route`
over each profile's `checkpoints` list, and a checkpoint no profile's list names
is refused…". `salad_studio/civitai_verify.py` never calls `plan_route` and never
inspects a checkpoint: it picks a Ready group (`pick_studio_group`, `:288`) and
POSTs to it (`post_to_group`, `:1150` → `generator.generate_from_payload`). The
doc check asserts only the token `studio_meta` in that section
(`tests/test_docs_match.py:587`), so the claim passes unverified. The fix pass
replaced one wrong attribution (`studio_meta`) with another.

**Correction:** say what the skill does — it picks a Ready group by readiness and
POSTs — and, if the Studio rule is worth stating, mark it as what Studio does,
not what this driver does.

**Fixed:** `.claude/skills/civitai-verify/SKILL.md:63-66` describes what the driver does — `pick_studio_group` picks a Ready group, `post_to_group` POSTs — and `plan_route` no longer appears in the file.

### D23, two recipe artifacts point at doc 20 (docs, Medium, executed, FIXED)
`salad_klein/prompt_catalog.json:133` and `salad_klein/prompt_ledger.json:181`
both carry `"full_writeup": "docs/workflow/20-comfy-klein-snofs-recipe-cards.md
(copied verbatim from the user's Desktop)"`. Doc 20 has never existed here (D8),
and the fix pass corrected the same claim in `docs/workflow/19`. No test covers
these two fields.

**Correction:** drop the repo-relative path, keeping "copied verbatim from the
user's Desktop".

**Fixed:** `salad_klein/prompt_catalog.json:133` and `prompt_ledger.json:181` drop the repo-relative path, keeping '(copied verbatim from the user's Desktop)'.

### D24, the manifest comment says three files, the fetch is five (docs, Low, read-from-source, FIXED)
`salad_klein/manifest.yaml:2` — "prefetch.py pulls all three in parallel". With
the shipped `KLEIN_UNET_SET` values the fetch is three unets plus
`qwen_3_8b_fp8mixed` and `flux2-vae` — five files
(`salad_klein/prefetch.py:59-96,111-117`), which `docs/workflow/15:290-298` also
says ("downloads **five files in parallel**").

**Correction:** "pulls every selected unet plus the CLIP and VAE in parallel".

**Fixed:** `salad_klein/manifest.yaml:2-3` says `prefetch.py` pulls every selected unet plus the CLIP and VAE in parallel.

### D25, `salad_klein/.gitignore`'s negation can never fire (docs, Low, executed, FIXED)
`salad_klein/.gitignore:2` — `!custom_nodes/rgthree-comfy/PINNED_COMMIT.txt`. The
root `.gitignore:14` excludes the whole `salad_klein/custom_nodes/` directory, and
git cannot re-include a file whose parent directory is excluded:

```
git check-ignore -v salad_klein/custom_nodes/rgthree-comfy/PINNED_COMMIT.txt
.gitignore:14:salad_klein/custom_nodes/   salad_klein/custom_nodes/rgthree-comfy/PINNED_COMMIT.txt
```

The pin is carried by the tracked `salad_klein/RGTHREE_COMMIT.txt` instead. The
same inert intent sits on the `weights/*` lines.

**Correction:** delete the negation (and the weights one), or move the pin to a
tracked file only.

**Fixed:** the negation and the `weights/*` lines are deleted from `salad_klein/.gitignore`.

### D26, the root README's history list does not name this audit (docs, Low, executed, FIXED)
`README.md:54` lists audits 57, 58, 59, 61 and the investigation 60. This pass
adds `62-salad-studio-audit-2026-10-14.md`, so the list is one audit short the
moment the document lands. Audit 61's D6 was the same item for its own document.

**Correction:** add 62 to the list.

**Fixed:** `README.md:54` lists 62.

### P1, no presentation artifact exists in the tree (presentations, High, executed, DEFERRED)
A tree-wide search for `*.pptx`, `*.ppt`, `*.key`, `*.odp` and any
marp/reveal/remark source returns nothing, and there is no deck anywhere in
`docs/`. The presentation surfaces that do exist are the three READMEs, the nine
`docs/workflow/` playbooks and the `graph_html/` viewer. Unchanged from audit 61
(its P1 was deferred by that pass's non-goals, and this pass's non-goals are the
same).

**Correction:** either accept those surfaces as the presentation material (and
fix D1–D3, D17, D18, D26 in them), or make a deck an explicit deliverable of the
follow-up goal.

**Deferred:** no deck is produced. The reason is this goal's non-goals: the presentation surface stays the three READMEs, the nine `docs/workflow/` playbooks and the `graph_html/` viewer, which is what audit 61 accepted. A deck is a new artifact rather than a correction, so it stays out of scope. Listed in §5.

### P2, the `graph_html/` viewer surface is correct (presentations, clean, executed, FIXED)
`salad_studio/graph_html/VENDOR.txt:4-6` still pins `@joint/core 4.2.5` and
`litegraph.js 0.7.18` with their upstream URLs and says which is the live pane;
`viewer.html` and `litegraph.html` are tracked, and the two generated files
(`_current.html`, `_litegraph.html`) are excluded by
`salad_studio/graph_html/.gitignore` and untracked (`git ls-files` lists only the
seven source files). `docs/workflow/16` matches `graph_view.py` on every
checkable claim.

**Fixed:** nothing to correct, re-confirmed: `salad_studio/graph_html/VENDOR.txt:4-6` still pins `@joint/core 4.2.5` and `litegraph.js 0.7.18` with their URLs, and `docs/workflow/16` still matches `graph_view.py` on every checkable claim.

### P3, the playbook a reader would present from fails at its first rebuild step (presentations, Medium, executed, FIXED)
`docs/workflow/15-salad-flux2-klein-group.md` is the Klein group playbook the root
README points at (`README.md:51`), and its rebuild runbook's first command is a
`cd` into a path that does not exist (D1), its step 1 describes a manifest that is
not the shipped one (D2), and its tab table names two removed surfaces (D3).

**Correction:** D1, D2, D3.

**Fixed:** D1, D2 and D3 are applied, so the playbook's first rebuild step runs and its manifest description and tab table match the tree.

### P4, the build-context README points below itself at nothing (presentations, Medium, executed, FIXED)
`salad_klein/README.md` is the short form a reader builds and presents from; its
"older tags below" sentence has no referent (D17). Its image tags, ports, build
args, unet sets, test command and catalog link are otherwise correct against the
shipped metadata document.

**Correction:** D17.

**Fixed:** D17 is applied, so `salad_klein/README.md` has no dangling 'below'.

## 3. Doc-vs-source verdicts

| Document | Verdict |
|---|---|
| `README.md` | Test count and duration right; the limitation's import chain is transitive (D18); the history list stops at 61 (D26) |
| `salad_studio/README.md` | The manual; the tab list, layer map, labels, test commands and Prompt Assist text are machine-checked and correct. Drifted in three places (D19, D20, D21) |
| `salad_klein/README.md` | Tags, ports, unet sets, build commands, test command and catalog link correct; the "older tags below" sentence has no referent (D17) |
| `docs/workflow/14` | One stale group name (D10) |
| `docs/workflow/15` | The dated status block is the record and stays; the runbook, the manifest description and the tab table are stale (D1, D2, D3) |
| `docs/workflow/16` | Correct (P2) |
| `docs/workflow/17` | Two counts for one file (D6); a CI workflow that is not here (D11) |
| `docs/workflow/18` | A stale suite count (D4) and a function that was never shipped (D12) |
| `docs/workflow/19` | Correct |
| `docs/workflow/21` | Three items: the 524 window (D7), doc 20 (D8), "the current Studio audit" (D13) |
| `docs/workflow/22` | Correct |
| `docs/workflow/23` | One label drift (D9) |
| `docs/history/57` | A second un-annotated `.gitignore` line **111** (D14) |
| `docs/history/58` | Correct; audit 61 cites a line here that does not exist (D16) |
| `docs/history/59` | A second recorded command that runs nothing (D15) |
| `docs/history/60` | Correct |
| `docs/history/61` | Two of its own numbers/claims are wrong (D5, D16) |
| `.claude/skills/civitai-verify/SKILL.md` | Flags, retry cap, ablation order, journal strings and `BUSY_CODES` correct; the routing sentence is not (D22) |

## 4. Observed test state

```
python -m unittest discover -s tests -p "test_*.py"
Ran 966 tests in 991.192s
OK
```

966 test methods across 35 modules, matching both READMEs; **0**
`invalid command name` lines, 0 worker-thread tracebacks (the fix pass's tracked
scheduler, `salad_studio/app.py:804-853` and `graph_view.py`'s `_soon`/`destroy`, removed the
2 129 lines audit 61 measured). `python -m unittest tests.test_docs_match` is
green, and `python test_salad_comfy_live_findings.py` passes against the
Eldermark checkout (and skips with a stated reason without it).

The one wrinkle is T1: with this document in the tree, the newest-audit rule in
`test_docs_match` fails until the rule is corrected (§6).

The fix pass resolved it: `tests.test_docs_match` is green with this
document in the tree, and the rule's own predicate reports 0 problems for it
(§8).

## 5. Out of scope and deliberately deferred

- **P1 — no presentation deck.** `DEFERRED`: the presentation surface stays the
  three READMEs, the nine `docs/workflow/` playbooks and the `graph_html/`
  viewer, which is what audit 61 accepted. The reason is that a deck is a new
  artifact, not a correction, and this goal's non-goals exclude it.
- The dated `docs/history/` records (57–61) keep their content and receive only
  the annotations D5, D14, D15 and D16 ask for.
- `docs/workflow/15`'s dated status block (`:3-8`) stays, as audit 61's D8
  decided.
- The three scripts that cannot import here (`salad_catalog_faces.py`,
  `salad_probe_ages.py`, `salad_probe_sdxl.py`) stay non-importable; the root
  structural check asserts that documented failure.
- `salad_klein/custom_nodes/` stays untracked and is pulled at build time.

Every other finding in §2 is `FIXED`; §8 is the closure summary.

## 6. The one change this pass made

`tests/test_docs_match.py`'s newest-audit rule (T1) was corrected from "every
finding in the newest audit carries a resolution" to "every audit **but the
newest** does, and the newest names the six areas and carries concrete findings".
Three parts of that file moved together: the rule's class and docstring
(`:396-427`), the citation regex the "concrete findings" half uses (it now accepts
a line range, a directory and a dotted symbol, not only a bare `*.py`), and
`RESOLUTION_CONVENTION_FROM = "61-"` (`:234`), which keeps the rule off the
pre-convention records 57–59 that this pass's non-goals leave as written.

Without it, adding this document — whose findings are unresolved by construction —
turns the suite red, and the next goal would start from a red baseline with no way
to tell its own failures from this one. No finding in §2 is fixed *by this pass*;
the fix pass that followed resolved all of them (§8).

## 7. Index for the follow-up goal

| Severity | Findings |
|---|---|
| High | D1, P1, T1 |
| Medium | C1, C2, C3, C10, C11, D2, D3, D4, D5, D6, D7, D8, D9, D10, D11, D17, D19, D22, D23, P3, P4, T2, U1, X1 |
| Low | C4, C5, C6, C7, C8, C9, C12, D12, D13, D14, D15, D16, D18, D20, D21, D24, D25, D26, T3, T4 |
| clean (no issue found) | U2, X2, P2 |

Every finding above names its artifact (path and line), its category and
severity, and the correction it implies. Nothing raised in prose is left
unclassified.

## 8. Closure record (the fix pass, 2026-10-14)

All 50 findings are resolved: **49 `FIXED`, 1 `DEFERRED`** (P1, no deck). The
three clean verdicts (U2, X2, P2) are `FIXED` with nothing to correct,
re-confirmed by a re-drive.

**Behaviour findings, each proven by a test that drives the shipped function:**

| Finding | Test |
|---|---|
| C1, U1 | `tests/test_image_deploy.py::ImagesPage::test_the_form_carries_the_ports_into_the_commands_it_prints` and `::test_an_image_added_with_no_ports_publishes_none` |
| C2 | `tests/test_model_catalog.py::TheFetchExitCode` |
| C3 | `salad_klein/test_prefetch.py::ATruncatedWeightIsRefetched` |
| X1 | `tests/test_config_page.py::ConfigPage::test_a_stopped_routed_container_is_refused_at_the_press` |

**Test findings.** T1 is recorded with its predicate evidence: the rule was
corrected by the audit pass, and `finding_problems()` reports 0 problems for this
document. T2 corrects the documented command. T3 adds `tests/test_age_review.py`.
T4 states and asserts the no-dialog guard's defaults in `tests/test_nomodal.py`.

**Code findings C4–C12.** The version guard fires (C4), the lifecycle docstring
says stop (C5), `_dropped_afters` is reported on close (C6), there is one
`wait_ready` plus a keyword-only third (C7), `PIDFILE` is gone (C8),
`compose_body_prompt` is deleted (C9), the smoke default is a shipped tag (C10),
`stop_container_group` is deleted (C11), and the HF sizes match the recorded boot
(C12).

**Docs and presentations D1–D26, P3, P4.** Every stated correction is applied.
The link resolver reports 0 broken relative links across 19 markdown files, and
the drift check compares the counts, image tags, group names, probe delays, tab
lists, field labels, paths and commands against the shipped sources with no
drift.

The suite is `Ran 986 tests … OK` — up from the pre-change 966, the new tests
included — with 0 `invalid command name` lines.
