# 61. Salad Studio audit, 2026-10-13 (code, tests, UI, UX, docs, presentations)

**Scope:** the whole tree at commit `994abb4` on branch `queue-start-and-wait`:
`salad_studio/` (the app, its modules and the `graph_html/` viewer), `tests/`
(including `civitai_fixtures/`), `salad_klein/` (Docker build, `prefetch.py`,
the prompt recipes and its own three test modules), the top-level scripts
(`model_catalog.py`, `salad_gen.py`, the four probes, `face_prompt.py`,
`salad_age_review.py`, `salad_catalog_faces.py`), `docs/workflow/` (14–23),
`docs/history/` (57–60), the three READMEs, and
`.claude/skills/civitai-verify/`.

**Goal of this pass:** find and record what is missing or incorrect. Nothing
here is fixed. Every finding states the correction it implies, so a follow-up
goal can work the list item by item.

## 0. How this audit was run (what is proven vs read)

- Every finding cites the file and line it came from, and every citation in
  this document was checked against the file at the audited commit: a script
  resolved all 124 distinct `path:line` citations across 45 files and confirmed
  each lands on a real, non-blank line, and a second pass read 125 cited lines
  and confirmed each says what the finding quotes from it. Citations that had
  drifted were corrected, not reported.
- The citations describe the tree **as it was audited** (commit `994abb4`). A
  finding marked FIXED deliberately no longer says what its citation reports:
  the `**Fixed:**` line under it says what does now, and §5 records the two
  deferrals.
- **executed** means a command or a driven window produced the evidence, and
  the command is named. **read-from-source** means the finding is a reading of
  the code or document, stated as such.
- The full suite was run from the repo root and captured:
  `python -m unittest discover -s tests -p "test_*.py"` →
  `Ran 917 tests in 1253.590s` / `OK`. Captured to
  `{SCRATCH}/suite.log`. The second documented command,
  `python test_salad_comfy_live_findings.py`, passes (exit 0).
- The UI/UX findings rest on the **real app**, not a mock: a window was built
  with `SaladStudio(show=False)`, mapped at 1280×900, driven with a real
  pointer warp and real `<MouseWheel>` events, and a Generate press was driven
  through `mainloop()` with an injected container handle. Captured to
  `{SCRATCH}/ui-drive2.log` (geometry, wheel, unbind, empty states) and
  `{SCRATCH}/ui-stopped2.log` (the press on a stopped group). The essential
  output of both is quoted inline below.
- `{SCRATCH}` is
  `C:\Users\vkozy\AppData\Local\Temp\grok-goal-d7bad01f458a\implementer\`:
  `suite.log` and `docs-match.log` (the two documented commands),
  `ui-drive2.log` and `ui-stopped2.log` (the driven window),
  `verify-code.log`, `verify-code2.log`, `verify-docs.log`, `verify-last.log`
  (the reproductions and the caller sweeps), `coverage.log` (the module-against-
  test sweep), `theater.log` (the assertion sweep), `cites.log`, `cites2.log`
  and `cites-all.log` (the citation checks), `selfcheck.log` (the document's
  structure and spot-checks) and `verify-plan.log` (this plan's five steps).
  The scripts that produced them are beside them.

## 1. Verdict per area

| Area | Verdict | Findings |
|---|---|---|
| Code | One behavior contradicted its own documentation in four places, two stores aborted on a hand-broken file where every sibling degrades, two dead branches, one silent-truncation contract break, and a long tail of dead shipped symbols | C1–C23, all FIXED except C23 |
| Test | The run was green and honest about the repo's known gaps, but buried in 2 129 Tcl teardown errors, with the one test that claims to prove the config page scrolls asserting on a mock, and two whole test modules plus four scripts run by nothing | T1–T10, all FIXED |
| UI | The pages and their empty states held up, with three exceptions: no empty state on three list surfaces, a stale tab name in a shipped docstring, and a `bind_all`/`unbind_all` pair that was not symmetric | U1 FIXED, U2/U3 re-confirmed clean |
| UX | The refusal for a container that is not running reached the user as a **failed render**, and the log line above it promised a start that never happens | X1–X4, all FIXED |
| Docs | The manuals and playbooks had drifted in 26 places, including two commands that ran zero tests, a dead link, a function that does not exist, a metadata key that was deleted, and a table that told a reader to build the wrong image | D1–D26, all FIXED |
| Presentations | No slide deck, `*.pptx`, or marp/reveal/remark source exists anywhere in the tree; the presentation surface is the three READMEs, `docs/workflow/`, and the `graph_html/` viewer | P1 DEFERRED, P2/P5 re-confirmed clean, P3/P4 FIXED |

## 2. Findings

### C1, the press does not gate a container that is not running (code, High, executed, FIXED)

Four places state that a group which is not running is refused **when Generate
is pressed**:

- `salad_studio/app.py:815` — ``the press is the gate. A`` … ``:818`` —
  ``is refused with a reason when it is made`` (in `_set_salad_word`).
- `salad_studio/app.py:4852` — ``# A stopped group is not a reason to refuse:``
  and `:4864` — ``f"{p.name} reads {word or 'unknown'}; the queue starts it if it is "``
  / ``"stopped and waits for it to become ready"``.
- `salad_studio/salad_status.py:850` — ``A **stopped** group is dispatchable: the queue starts the container the``
  / ``request routes to and the generator waits for its ``/ready`` before it POSTs``.
- `salad_studio/salad_status.py:961` — ``The caller starts a container only on a definite ``False``, so an``.

The shipped behavior is neither. Driven through the real window with the badge
word `Stopped` and a container handle that reports the group stopped
(`{SCRATCH}/ui-stopped2.log`):

```
status:        "Failed. See Logs"
gen_state:     "Failed after 0s"
posted:        []                       <- no POST was ever attempted
queue_jobs:    [{"state": "failed", "reason": "the container for profile 'klein' ... is down ..."}]
lifecycle:     [["is_running", "klein", "https://..."]]     <- the only call
dialog:        messagebox.showerror("Salad Studio", "the container for profile 'klein' ... is down:
               its group is not running, and this app does not start containers.
               Start it in the Salad console, then Generate again.")
log:           "[INFO] klein reads Stopped; the queue starts it if it is stopped and waits
                for it to become ready"        <- the promise C1 names
```

So the press is **accepted**, the request is enqueued, and the refusal is
delivered one layer down by `salad_queue.ensure_container` (which is correct —
`salad_studio/salad_queue.py:669-703`, and it never starts anything). The user
sees a render that failed, and the line above it says a start is coming.

**Correction:** pick one. Either make the press the gate it claims to be (call
`self.gen_queue.ensure_container(p.name, p.gateway)` in `_on_generate` before
enqueuing, and report the refusal the way `generate_dispatch_reason` does), or
reword all four claims to say the refusal is the queue's and arrives as a
failed render. The mismatch is the defect; the current state is a promise the
code does not keep.

**Fixed:** one sentence, `salad_queue.container_down_refusal`, is what the press and the queue both give; `salad_status.generate_dispatch_reason` refuses a stopped group with it, the press logs `Generate refused: …` once and sets `Refused: …`, and `generator.ContainerDown` reports the race case as a refusal. Tests: `test_app_layout.py` `test_generate_refuses_a_stopped_group_at_the_press`, `test_config_page.py` `test_a_group_that_goes_down_after_the_badge_is_reported_as_refused`

### C2, a half-written profile store aborts app startup (code, High, executed, FIXED)

`salad_studio/profiles.py:396` — `data = json.loads(raw)` inside `_load_doc`,
with no `except`. The module's own `_coerce` docstring
(`salad_studio/profiles.py:422`) says the opposite:

```
A hand-edited or half-written ``studio-profiles.json`` must not abort
``load_all`` (and with it app startup).
```

`_save_doc` writes non-atomically, so a crash mid-write leaves a truncated
file that kills the next launch. Repro (`{SCRATCH}/verify-code.log`):

```
[CONFIRMED] PROFILES-CORRUPT: load_all raised JSONDecodeError: Expecting value: line 1 column 24 (char 23)
```

Every sibling store degrades instead: `studio_meta._read`, `vast.load_doc`,
`salad_queue.load_ledger`, `tokens._load_local`, `prompt_history._load`,
`prompt_catalog._load` and `image_deploy.load_settings` all return an empty
document.

**Correction:** wrap the parse the way `studio_meta._read` does and return
`{"profiles": {}, "active": None}`, and write the file through a temp path plus
`replace` the way `salad_queue.save_ledger` does.

**Fixed:** `profiles._load_doc` reads a truncated or unreadable file as no profiles, like every sibling store. Test: `test_profiles.py` `TruncatedStoreDegrades`

### C3, a half-written LoRA extras file aborts LoRA listing (code, Medium, executed, FIXED)

`salad_studio/lora_store.py:90` — `data = json.loads(raw)` in `_load_extras`,
with no `except`. This loader is on the path of every LoRA render
(`list_loras`, `comfy_import.resolve_prompt_loras`, `request_json.build_request`),
and it is the only store loader in the package that raises. Repro
(`{SCRATCH}/verify-code.log`):

```
[CONFIRMED] LORA-EXTRAS-RAISE: list_loras raised JSONDecodeError: Expecting value: line 1 column 9 (char 8)
```

**Correction:** `try: data = json.loads(raw) except ValueError: return []`,
matching the module's siblings.

**Fixed:** `lora_store._load_extras` reads a truncated or unreadable file as no extras. Test: `test_lora_store.py` `TruncatedExtrasDegrades`

### C4, an in-flight Comfy history entry is treated as terminal (code, Medium, read-from-source, FIXED)

`salad_studio/generator.py:257`:

```
if st.get("status_str") == "error" or st.get("completed") is False and st.get("status_str"):
```

`and` binds tighter than `or`, so the second clause reads "not completed and
has any status string". ComfyUI's history entry while a prompt is still
executing is exactly `{"status": {"status_str": "...", "completed": false, ...}}`,
so the function returns `None` and the caller reports no image and fails the
render. The docstring two screens up (`salad_studio/generator.py:228-230`) states the
intended rule: *"a body that is not JSON and an entry with no image all just
wait for the next try: the render is still running until Comfy says otherwise."*
No test covers this branch (`grep completed|status_str tests/test_generator.py`
→ no matches).

**Correction:** `if st.get("status_str") == "error":`.

**Fixed:** `generator.poll_history_image` treats only `status_str == "error"` as terminal. Test: `test_generator.py` `HistoryPoll`

### C5, a user's own image can never carry ports (code, Medium, executed, FIXED)

`salad_studio/image_deploy.py:120-123` reads ports out of the settings row:

```
"ports": {
    studio_meta.PORT_API: _int((row.get("ports") or {}).get(studio_meta.PORT_API)),
    studio_meta.PORT_COMFY: _int((row.get("ports") or {}).get(studio_meta.PORT_COMFY)),
},
```

but the store never keeps a `ports` key: `add_image`
(`salad_studio/image_deploy.py:487`) writes name/tag/context/build_arg,
`save_settings` (`:454-467`) writes those four, and `load_settings`
(`:405-436`) rebuilds each row from those four. So `row.get("ports")` is always
`{}`, `port_args()` returns `[]`, the `docker run` line has no `-p`, the
`vastai create instance` line has no port env, and the page's facts line shows
`-`. A hand-edited `ports` key is dropped by the round trip. Executed
(`{SCRATCH}/verify-code2.log`):

```
[CONFIRMED] IMGDEPLOY-PORTS: stored_keys=['build_arg', 'context', 'name', 'tag'] ports={'api': 0, 'comfy': 0} port_args=[]
[CONFIRMED] IMGDEPLOY-PORTS-DROP: hand-written ports survive load_settings? False
```

**Correction:** persist ports (keep them in `add_image` / `save_settings` /
`load_settings`, and expose them in the add-image form), or delete the read and
say in `entries()` that a user's own image has no published ports.

**Fixed:** `load_settings`, `save_settings` and `add_image` keep a row's `ports`, so `entries` reports the ports the store names. Test: `test_image_deploy.py` `SettingsStore` ports cases

### C6, a size-filling branch can never run (code, Medium, read-from-source, FIXED)

`salad_studio/comfy_import.py:3105-3106` fills every dangling
`width`/`height`/`batch_size`/`steps` link with `1024`, and it runs from
`_fill_dangling_size_links` (`:3112`), which the shipped order calls first
(`salad_studio/comfy_import.py:3023-3024`: `_fill_dangling_size_links(out)`
then `_rewire_missing_links(out)`). By the time `_rewire_missing_links` runs
there is nothing left in that set, so its copy of the rule is dead weight that
would silently disagree if the default changed in one place.

**Correction:** delete the size branch from `_rewire_missing_links` (keep
`text`/`clip`), or have `_rewire_missing_links` call `_fill_dangling_size_links`.

**Fixed:** the size branch is gone from `_rewire_missing_links`, whose docstring now says `_fill_dangling_size_links` owns that rule

### C7, two container-start entry points have no shipped caller (code, Medium, executed, FIXED)

`salad_studio/salad_status.py:924` — `def start_container_group(` and
`salad_studio/salad_status.py:1006` — `def start(self, profile: str, gateway: str)`.
A repo-wide sweep finds them only in their own definitions, the tests, and the
manual (`{SCRATCH}/verify-code2.log`):

```
start_container_group: ['salad_studio\\salad_status.py:924', 'tests\\test_salad_status.py:709', 'tests\\test_salad_status.py:735']
```

The app only ever stops a container (commit `d52907b`), and the manual says so
at `salad_studio/README.md:379`: ``control-plane calls; the app only ever uses the stop.``

**Correction:** delete both, or re-point a caller at them. Keeping them is only
defensible if the manual also says they exist for the console path.

**Fixed:** `start_container_group` and `ContainerLifecycle.start` are deleted, with their tests; the manual names `stop_container_group` as the only control-plane call the app makes, and `test_docs_match.py` asserts no start call is shipped

### C8, `profiles.route_payload` is a second, unconsulted routing decision (code, Medium, executed, FIXED)

`salad_studio/profiles.py:258` — `def route_payload(`. Its only callers are
`tests/test_profiles.py` (11 sites) and `tests/test_studio_meta.py:169`
(`{SCRATCH}/verify-code2.log`). The app routes with `profiles.plan_route`
(`salad_studio/app.py:4827`). `docs/history/58` already recorded it as
*"correct, and never consulted"*. Two routing implementations in one module is
the drift trap `plan_route`'s own docstring warns about.

**Correction:** delete `route_payload`, or make `plan_route` the only entry
point and have `route_payload` delegate.

**Fixed:** `profiles.route_payload` is deleted; its tests drive `plan_route`, the shipped decision

### C9, `TERMINAL_CODES` is defined and never read (code, Low, executed, FIXED)

`salad_studio/salad_queue.py:90` — `TERMINAL_CODES = (504, 524)`. A repo-wide
sweep returns that one line and nothing else, not even a test
(`{SCRATCH}/verify-code2.log`). `classify` (`:227-236`) implements
terminal-ness as "not 200, not 0, not in `BUSY_CODES`", so the tuple is
documentation that drifted into code.

**Correction:** delete the constant, or use it in `classify`.

**Fixed:** `TERMINAL_CODES` is deleted; the comment above `MAX_ATTEMPTS` says `classify` is what makes 504/524 terminal

### C10, `vast.list_instances` truncates silently while promising it does not (code, Low, read-from-source, FIXED)

`salad_studio/vast.py:29` — `MAX_PAGES = 4` with the comment *"so a bigger
account is read in a few requests rather than truncated"*, and the docstring at
`salad_studio/vast.py:233-234` — *"are followed (bounded by :data:`MAX_PAGES`)
so a bigger account is not silently truncated."* The loop at `:244-266` simply
stops at `MAX_PAGES`, and when the API still offers `next_token` it returns
`out["error"] == ""` with the rest of the account missing.

**Correction:** raise `MAX_PAGES` past any plausible account size, or set
`out["error"]` (or a `truncated` flag) when `after` is still set after the last
page.

**Fixed:** `vast.list_instances` sets `truncated` when the API still offers a page after `MAX_PAGES`, and the Config page's fetch note says so. Tests: `test_vast.py` `ListInstances` truncation cases

### C11, `salad_gen.wait_ready` raises the wrong error on a zero budget (code, Low, executed, FIXED)

`salad_gen.py:151` is `while time.time() < deadline:` and `:158` is
`raise SystemExit(f"gateway not ready after {timeout_s}s (last HTTP {code})")`.
`code` is assigned only inside the loop, so `timeout_s=0` skips the body and
the message line raises instead. Executed:

```
[CONFIRMED] SALADGEN-READY: UnboundLocalError: cannot access local variable 'code' where it is not associated with a value
```

Callers pass literals today (120, 900, 2400), so it is latent — but the failure
message is exactly what a caller needs when the budget is wrong.

**Correction:** initialise `code = 0` before the loop.

**Fixed:** `salad_gen.wait_ready` initialises `code = 0`, so a zero budget reports "not ready after 0s". Test: `test_generator.py` `WaitReady`

### C12, the `selected_loras` fallback in `_profile_from_dict` is unreachable (code, Low, executed, FIXED)

`salad_studio/profiles.py:468-469`:

```
if "selected_loras" not in data and use_loras and not selected:
    selected = list(DEFAULT_KLEIN_LORA_IDS)
```

`use_loras` is set at `:465-467` from the same predicate, and
`_coerce_selected_loras` (`:410-416`) already returns
`DEFAULT_KLEIN_LORA_IDS` whenever `use_loras` is truthy, so `use_loras` true
implies `selected` non-empty. Driven over every stored shape
(`{SCRATCH}/verify-last.log`):

```
data={}                          branch_fires=False  selected_loras=['civitai:2334190@2625692', 'civitai:545264@2763568']
data={'use_loras': True}         branch_fires=False  selected_loras=[...]
data={'use_loras': False}        branch_fires=False  selected_loras=[]
data={'selected_loras': []}      branch_fires=False  selected_loras=[]
data={'selected_loras': ['a']}   branch_fires=False  selected_loras=['a']
```

**Correction:** delete lines 468-469.

**Fixed:** the unreachable fallback is deleted from `_profile_from_dict`

### C13, `civitai_verify` keeps a second copy of the incompatible-family set (code, Low, read-from-source, FIXED)

`salad_studio/civitai_verify.py:767-774` — `_WRONG_LORA_FAMILIES = {"SDXL",
"Pony", "Illustrious", "Krea 2", "Flux.1 Dev", "Flux.1 D"}` — versus
`salad_studio/comfy_import.py:227-234` — `_INCOMPATIBLE_FAMILIES` with the same
six members in a different order. `civitai_verify` already imports
`comfy_import as ci`.

**Correction:** import one from the other.

**Fixed:** `civitai_verify` imports `comfy_import.INCOMPATIBLE_FAMILIES` (renamed from the private `_INCOMPATIBLE_FAMILIES`); its own copy is gone

### C14, the same progress field is scaled two ways (code, Low, read-from-source, FIXED)

`salad_studio/salad_status.py:705` — `pull={int(float(pull or 0) * 100)}%`
multiplies unconditionally, while `pull_pct` (`:547-554`) multiplies only when
`p <= 1.0` ("Salad reports 0–1 or 0–100"). A Salad answer of `33` prints as
`pull=3300%` here and `Downloading 33%` through `_instance_word`. Latent today
because `format_status` itself has no shipped caller (C20).

**Correction:** call `pull_pct(pull)` in `format_status`.

**Fixed:** resolved with C20: `format_status`, the only caller that scaled `pulling_progress` itself, is deleted

### C15, `strengths_for` re-implements its own table by substring (code, Low, read-from-source, FIXED)

`salad_studio/lora_store.py:827` reads `_STRENGTH` (defined at `:71-75`, which
already maps `"civitai:1449678@2795018": (0.5, 0.5)`), and then `:830-832`
falls back to `if "2795018" in blob or "1449678" in blob: return (0.5, 0.5)`.
The substring test also catches unrelated ids containing those digits, and it
is the second copy a reader will edit next.

**Correction:** drop the substring fallback and add any missing id to
`_STRENGTH`.

**Fixed:** `strengths_for` reads `_STRENGTH` and returns `(1.0, 1.0)`; the substring fallback is gone

### C16, `studio_meta.deployment_for_family` is advertised and unused (code, Low, executed, FIXED)

`salad_studio/studio_meta.py:22` — the module docstring says
``:mod:`image_deploy` builds the deploy commands from it.``, but
`salad_studio/studio_meta.py:418` `deployment_for_family` and
`salad_studio/studio_meta.py:71`
`DEPLOYMENT_KEYS` appear only at their definitions; `image_deploy.entries`
(`salad_studio/image_deploy.py:79-81`) reads
`entry.get(studio_meta.DEPLOYMENT)` directly.

**Correction:** use `deployment_for_family` in `image_deploy.entries` (or
delete it and the docstring line) and delete `DEPLOYMENT_KEYS`.

**Fixed:** `image_deploy.entries` calls `studio_meta.deployment_for_family`; `DEPLOYMENT_KEYS` is deleted

### C17, `attach_image` attaches to the newest row when the timestamp misses (code, Low, read-from-source, FIXED)

`salad_studio/prompt_history.py:309` initialises `idx = 0` and `:310-314` only
advances it on a match, so a `ts` that matches no row leaves `idx = 0`; `:319`
then reads `old = rows[idx].get("image")` and `_unlink_thumb(old)` deletes the
**newest** row's thumbnail before attaching the new one to it. Both shipped
call sites pass no `ts` (`salad_studio/app.py:4933`, `:5018`), so this is
latent.

**Correction:** when `ts` is given and nothing matches, return `None` (or
append a row) instead of falling back to index 0.

**Fixed:** `prompt_history.attach_image` returns None when `ts` matches no row, so it cannot take the newest row's thumbnail

### C18, `AUTO_MAX_BYTES`'s comment describes LoRA auto-fetch the code refuses (code, Low, read-from-source, FIXED)

`model_catalog.py:62-63` — `# Auto-fetch LoRAs under this size. UltraRealPhoto
v2 is ~2 GB, metadata only.` — versus `model_catalog.py:1026-1027`
(`if item.get("kind") == "lora": return False`). No LoRA is auto-downloaded
now, so the constant only gates Civitai-hosted checkpoints.

**Correction:** `# Auto-fetch Civitai checkpoints under this size.`

**Fixed:** the comment now says "Civitai checkpoints", which is what the gate admits

### C19, `cmd_fetch_klein` says three weights, the list has four (code, Low, read-from-source, FIXED)

`model_catalog.py:1220` — `"""Download the three Klein HF weights in parallel,
optionally stage for Docker."""` — versus `model_catalog.py:49-54`
(`KLEIN_HF_IDS` holds `base`, `distilled`, `qwen_3_8b_fp8mixed` and
`flux2-vae`), which the function iterates.

**Correction:** say "the four Klein HF weights".

**Fixed:** `cmd_fetch_klein`'s docstring says four weights, which is what `KLEIN_HF_IDS` holds

### C20, dead shipped symbols with no caller (code, Low, executed, FIXED)

Each of these appears only at its definition in a repo-wide sweep
(`{SCRATCH}/verify-code2.log`), or only in the tests named. The correction for
all of them is the same: delete, or re-point a caller.

| Symbol | Path:line | Sweep result |
|---|---|---|
| `_body_snippet` | `salad_studio/generator.py:82` | definition only |
| `read_key`, `clear_history` | `salad_studio/generator.py:78`, `:769` | tests only |
| `SKIP_TYPES` (empty set), `_primitive_value` | `salad_studio/comfy_import.py:23`, `:1128` | definition only |
| `issues_from_pastes` | `salad_studio/comfy_import.py:2890` | tests only |
| `CIVITAI_VERSION` | `salad_studio/ref_check.py:32` | definition only |
| `SAMPLE_URL`, `visual_gap_actionable` | `salad_studio/civitai_verify.py:38`, `:963` | definition only |
| `salad_loader_name` | `model_catalog.py:1072` | definition only |
| `token_path`, `probe_all` | `salad_studio/tokens.py:90`, `:267` | tests only |
| `content_of`, `fetch_local_models` | `salad_studio/ai_helper.py:663`, `:1021` | tests only |
| `compose_face_system_prompt`, `compose_young_deanime_edit_prompt`, `compose_face_cleanup_edit_prompt`, `compose_body_age_edit_prompt`, `compose_body_negative` | `face_prompt.py:124`, `:246`, `:269`, `:299`, `:333` | definition only |
| `zip_safetensors` | `salad_klein/weights_zip.py:61` | `salad_klein/test_prefetch.py:164` only |
| `shown_policy`, `color_for_status`, `format_status` | `salad_studio/salad_status.py:218`, `:557`, `:683` | tests only |
| `_default_selected_loras`, `SNOFS_MARKER`, `SNOFS_UNET` | `salad_studio/profiles.py:42`, `:106`, `:109` | definition only (`SNOFS_UNET` also in tests) |

`face_prompt.py`'s module docstring calls itself the *"SINGLE prompt path for
both /fal and /xai-image"*; only `compose_age_edit_prompt` is still reachable
(from `main()`), so five of its six composers are leftovers of that backend.

**Correction:** delete every symbol in the table, or re-point a caller at it.
`read_key`, `clear_history`, `probe_all`, `token_path`, `content_of`,
`fetch_local_models` and `issues_from_pastes` are the ones with tests that would
need to move to the API the app actually uses.

**Fixed:** every symbol in the table is deleted: `generator` (`read_key`, `_body_snippet`, `clear_history`), `comfy_import` (`SKIP_TYPES`, `_primitive_value`, `issues_from_pastes`), `ref_check.CIVITAI_VERSION`, `civitai_verify` (`SAMPLE_URL`, `visual_gap_actionable`), `model_catalog.salad_loader_name`, `tokens` (`token_path`, `probe_all`), `ai_helper` (`content_of`, `fetch_local_models`), `salad_status` (`shown_policy`, `color_for_status`, `format_status`), five `face_prompt` composers, `salad_klein/weights_zip.zip_safetensors`, `profiles` (`SNOFS_MARKER`, `SNOFS_UNET`, `_default_selected_loras`). The tests that used them drive the shipped API instead (`inspect_pastes`, `probe_token`, `reply_info`, `local_models`, `resolved_policy`, `request_json.UNET_SNOFS`)

### C21, three docstrings name pages and tabs that no longer exist (code, Low, read-from-source, FIXED)

The Images and Vast.ai tabs were merged into Config on 2026-10-13 (`bd4fe11`),
and `tests/test_app_layout.py:1190` asserts the strings `"Vast.ai tab"` and
`"Images tab"` are absent from the UI. The code's own comments were not all
updated:

- `salad_studio/app.py:4957-4958` — ``it authenticates the vast.ai control API (the Vast.ai`` / ``tab's listing and the Tokens tab's check)``.
- `salad_studio/image_deploy.py:5` — ``Vast.ai page renders on one)``.
- `salad_studio/image_deploy.py:380` — ``"""The whole deploy story for one entry, as the Images page shows it."""``
- `salad_studio/studio_meta.py:21` — ``The Images page renders this``.
- `salad_studio/vast.py:310` — ``Images page describes.``

**Correction:** say "the Config page's Vast.ai instances section" and "the
Config page's Container images section". The manual's own stale copy is D4.

**Fixed:** the five docstrings and comments name the Config page's sections

### C22, the wheel claim is not symmetric with its release (code, Low, executed, FIXED)

`salad_studio/app.py:531` claims the wheel with
`self.bind_all("<MouseWheel>", self._on_config_wheel, add="+")`; `:534`
releases it with `self.unbind_all("<MouseWheel>")`. `unbind_all` is
application-wide and ignores the `add="+"` registration, so leaving the page
also cancels any `<MouseWheel>` binding another part of the app installed.
Executed (`{SCRATCH}/ui-drive2.log`), with a second `bind_all` installed first:

```
before_leave:              {"probe_widget_binding": true, "foreign_bind_all": true}
after_pointer_left_app:    {"app_bind_all_nonempty": false, "probe_widget_binding_survives": true}
```

Nothing else installs one today (the history strip uses per-widget `bind`,
`salad_studio/history_strip.py:162`), so this is latent.

**Correction:** unbind this handler only (`self.unbind_all` has no
handler-scoped form; keep the funcid from `bind_all` and unbind by sequence, or
guard the handler on a flag that `_on_config_leave` clears).

**Fixed:** there is no `unbind_all` anywhere: the wheel handler is bound once and gates itself on `_config_wheel_active`, which `<Enter>`/`<Leave>` set. Test: `test_app_layout.py` `test_the_wheel_is_claimed_only_while_the_pointer_is_on_the_page`

### C23, three shipped scripts cannot run in this repo (code, Low, executed, DEFERRED)

`salad_catalog_faces.py`, `salad_probe_ages.py` and `salad_probe_sdxl.py`
import `paperdoll_mask` and `regen_faces`, which stayed in the Eldermark repo,
so they fail on import here. The root README (`README.md:82-88`) and the manual
(`salad_studio/README.md:526-532`) document this, and
`test_salad_comfy_live_findings.py` asserts the documented failure rather than
reporting a false pass — so this is a known, honestly-recorded gap, not a
false green.

**Correction:** none implied by this pass; recorded so the follow-up goal can
decide whether to vendor the two modules or delete the three scripts.

**Deferred:** the three scripts still import `paperdoll_mask` and `regen_faces` from the Eldermark repo. Reason: vendoring those two modules, or deleting the scripts, is a decision this pass was told to leave open (the plan's non-goals). The root structural check asserts the documented failure, so nothing here is a false pass

### T1, a green run prints 2 129 Tcl teardown errors (test, Medium, executed, FIXED)

`python -m unittest discover -s tests -p "test_*.py"` ends `OK`, and
`{SCRATCH}/suite.log` (9 564 lines) contains:

```
invalid command name: 2129        while executing: 2129
Exception in thread: 35           RuntimeError: 52
```

Grouped by the callback Tk could not find:

```
1192  lift_editor_over_webview      540  reapply_opened_size
  14  refresh_queue_page              5  redraw
   4  poll_salad_status               2  place_editor_sash
 ~350  anonymous lambdas
```

Every one is an `after()` callback that fires after the window it belongs to
was destroyed. The dominant two are `_lift_editor_over_webview`
(`salad_studio/app.py:4367`) and `_reapply_opened_size`
(`salad_studio/app.py:4279`); the rest are `_place_editor_sash` (`:4293`),
`_schedule_json_chrome` (`:4471`), `_refresh_queue_page` (`:3516`) and
`_poll_salad_status` (`:729`). A suite that prints 2 129 errors to say `OK` is
one where a real teardown failure is indistinguishable from the noise. It is
also the same hazard class as audit 59's A4.

**Correction:** have the app cancel its pending `after` ids on `<Destroy>`
(`_on_destroy_cancel_poll` already cancels the Salad poll), and have the Tk
tests call `app.update()` once after `destroy()` (or assert the log is clean in
one place) so a new teardown error fails instead of scrolling past.

**Fixed:** every callback the window schedules for itself goes through `_later`/`_later_idle`, which track the id and are cancelled on Destroy; the captured run has 0 `invalid command name` lines

### T2, the test that claims to prove the config page scrolls asserts on a mock (test, Medium, executed, FIXED)

`tests/test_app_layout.py:1220` `test_the_wheel_scrolls_the_config_page`:

```
1223:        with mock.patch.object(canvas, "yview_scroll") as scroll:
1224:            app._on_config_wheel(type("E", (), {"delta": -120})())
1225:            scroll.assert_called_once_with(1, "units")
```

It patches the method whose effect it claims to prove, drives the handler
directly with a hand-built event, and never checks that the canvas moved, that
the scroll region covers the content, or that the wheel is bound at the time.
Its own commit message is *"Prove the merged Config page scrolls"*. The
neighbouring test (`:1234` `test_the_wheel_is_claimed_only_while_the_pointer_is_on_the_page`)
asserts `bind_all` is falsy after a leave, which passes even though the release
also destroys other components' bindings (C22) — so C22 is invisible to the
suite.

Driven for real in this audit (`{SCRATCH}/ui-drive2.log`): the page is
2 688 px tall against a 644 px viewport, a real pointer warp into the page and
six real `<MouseWheel>` events moved `yview` from `0.0` to `0.14286`. The
behavior is correct; the test does not prove it.

**Correction:** assert on `canvas.yview()` after a real `event_generate`
against a mapped window (or at minimum assert the scroll region covers the
body's requested height), and keep the mock assertion as a unit check of the
arithmetic.

**Fixed:** `test_the_wheel_scrolls_the_config_page` drives the real canvas and asserts the view moved by the canvas's own increment

### T3, a Docker smoke script is named like a test module and runs zero tests (test, Medium, executed, FIXED)

`salad_klein/test_http.py` is a manual Docker smoke script (`main()` runs
`docker run`, probes `/health`, removes the container). Its name matches the
unittest discovery pattern, so discovery imports it and reports nothing:

```
python -m unittest test_http      ->  Ran 0 tests ... NO TESTS RAN
```

**Correction:** rename it (`http_smoke.py`) or move it out of the discovery
pattern; then decide whether `salad_klein/` should be part of the documented
suite.

**Fixed:** the script is `salad_klein/http_smoke.py`, out of the discovery pattern, and doc 23 lists it as a manual run

### T4, two real test modules are never run by any documented command (test, Medium, executed, FIXED)

`salad_klein/test_prefetch.py` (15 tests) and `salad_klein/test_hf_gated_access.py`
(1 test) both pass, and nothing runs them:

```
python -m unittest test_prefetch          ->  Ran 15 tests ... OK
python -m unittest test_hf_gated_access   ->  Ran 1 test ... OK
```

Neither documented command reaches them: `README.md:31` and
`salad_studio/README.md:537` run `discover -s tests -p "test_*.py"`, and
`README.md:32` runs the root structural check. `salad_klein/`'s tests cover
`prefetch.py`, the first-boot entrypoint the image depends on.

**Correction:** add a third documented command (`cd salad_klein; python -m
unittest discover -p "test_*.py"`) or move the two modules into `tests/`.

**Fixed:** both READMEs document `cd salad_klein && python -m unittest discover -p "test_*.py"` (16 tests), and doc 23 says the same

### T5, the largest script in the repo has no test at all (test, Medium, executed, FIXED)

A sweep of every shipped module against every test module
(`{SCRATCH}/coverage.log`):

| Artifact | Lines | Test that drives it | Verdict |
|---|---|---|---|
| `model_catalog.py` | 1251 | none | untested |
| `salad_probe_sdxl.py` | 262 | none | untested |
| `salad_probe_ages.py` | 133 | none | untested |
| `salad_age_review.py` | 116 | none | untested |
| `face_prompt.py` | 353 | `salad_probe_klein.py` only, which is itself only read by the root structural check | effectively untested |
| every `salad_studio/*.py` module | — | at least one `tests/test_*.py` | covered |

`model_catalog.py` is the local LoRA/checkpoint cache with Civitai provenance,
including the download and verification paths; `face_prompt.py` composes the
age-locked face prompts.

**Correction:** add a test module for `model_catalog.py`'s pure helpers
(`should_autodownload`, the Civitai URL builders, `civitai_version`), and one
for `face_prompt.compose_face_prompt`'s determinism. `salad_probe_*` and
`salad_age_review` need a decision instead: they cannot import here (C23), so
either vendor their two missing modules or record them as out of scope.

**Fixed:** `tests/test_model_catalog.py` drives the ref parser and the auto-download gate; `tests/test_face_prompt.py` drives the composers from the shipped pack

### T6, the audit-artifact check is pinned to one file (test, Low, read-from-source, FIXED)

`tests/test_docs_match.py:212` — `AUDIT = TOOLS / "docs" / "history" / "59-salad-studio-audit-2026-09-26.md"`
(repeated at `:283`), and `class AuditDocument` asserts that document's shape
and re-checks five of its "FIXED" claims. Nothing checks this document, or any
later one, so a follow-up audit can be written without a structural check.

**Correction:** parameterise the check over every `docs/history/NN-*audit-*.md`
(or point it at the newest), and assert the six areas and the
category/severity/correction shape each finding needs.

**Fixed:** `test_docs_match.py` finds the newest `*-audit-*.md` and requires a resolution on every finding, with the rule itself driven by documents that break it

### T7, a test docstring asserts the container-start behavior that was removed (test, Low, read-from-source, FIXED)

`tests/test_app_layout.py:2331` — ``A stopped (or unprobed) container is dispatchable now: the queue starts``
/ ``:2332`` — ``the container the request routes to and the generator waits for its``.
This is the C1 claim again, in a test. The test body only asserts the request
reaches the queue with a mocked `generate_from_payload`, so it passes for a
reason unrelated to the docstring.

**Correction:** reword to match C1's chosen correction.

**Fixed:** the docstring says a booting or unprobed replica is dispatched and a stopped group is refused

### T8, the root structural check reads another repository (test, Low, read-from-source, FIXED)

`test_salad_comfy_live_findings.py:17-30` resolves `ELDERMARK_REPO` (default
`C:\Users\vkozy\repos\lifesim-design`) and asserts prose in that repo's
`docs/00-INDEX.md`, `docs/workflow/13-*.md`, `docs/systems/02-*.md` and two of
its skills, plus `art/catalog/face/salad_PAUSE.txt`. In a standalone clone of
salad-studio the file cannot pass, and it is not part of the discover run. The
README documents the setting (`README.md:69`) but not that the check depends on
another checkout existing.

**Correction:** skip with a stated reason when `ELDERMARK_REPO` is absent, and
say in the README that the second command needs that checkout.

**Fixed:** the check now says what it needs and stops: without the checkout it prints `skipped: the Eldermark checkout is not at …` and exits 0 instead of failing on another repository's files, and the README's configuration table says the second command needs that checkout. Driven both ways in this pass

### T9, 42 tests use bare `assert` and vanish under `-O` (test, Low, executed, FIXED)

A static sweep of `tests/` (`{SCRATCH}/theater.log`) found 42 test methods whose
only assertions are bare `assert` statements (e.g.
`tests/test_config_page.py::ConfigPage.test_the_page_adds_and_removes_a_checkpoint`,
`tests/test_lora_store.py::AddFromSources.test_add_local_path`). Under
`python -O` those become no-ops and the tests pass without checking anything.
No test method in the suite has zero assertions, and only two use mock-call
assertions alone (T2 and `tests/test_theme.py:366`).

**Correction:** convert them to `self.assert*` (or run the suite with `-O` in
one CI-ish check so the difference shows up).

**Fixed:** all 57 bare asserts in test methods are `self.assert*` calls; a sweep finds none left

### T10, `poll_history_image`'s terminal branch is untested (test, Low, read-from-source, FIXED)

`salad_studio/generator.py:257` (C4) has no test: `grep completed|status_str
tests/test_generator.py` returns nothing. The branch decides whether an
in-flight render is reported as failed.

**Correction:** add a case with a `completed: false` entry carrying a status
string and assert the function keeps waiting.

**Fixed:** `test_generator.py` `HistoryPoll` drives an in-flight entry, a missing status and an error status

### U1, three list surfaces have no empty state (UI, Low, executed, FIXED)

The Queue page has an explicit empty state
(`salad_studio/app.py:3441-3443`, `QUEUE_EMPTY_TEXT` at `:127`). Driven over
the real pages (`{SCRATCH}/verify-last.log`), the page strings are:

```
Prompt History page:  ['Reuse', 'Delete']
Prompt Catalog page:  ['Short name', 'PY_VAR76', 'Description', ... 'Delete']
history strip:        ['◀', '▶']
```

So an empty Prompt History page, an empty Prompt Catalog page and an empty
history strip are a bare tree (or two arrows) with nothing saying the list is
empty or how to fill it, while the Queue page says *"The queue is empty. Press
Generate to submit a render."*

**Correction:** give each list surface the Queue page's treatment: one label
that says it is empty and what fills it, shown and hidden with the rows.

**Fixed:** the Prompt History page, the Prompt Catalog page and the history strip each carry an empty-state line, shown and hidden with their rows. Test: `test_app_layout.py` `ListSurfacesSayWhenTheyAreEmpty`

### U2, the config page scroll claim holds in the real app (UI, clean, executed, FIXED)

Recorded as the area's executed check, because the last commit claims it and
the test does not prove it (T2). The wiring is `salad_studio/app.py:421-441`
(the canvas, `vscroll` at `:424`, the `<Configure>` handlers that set the
scroll region and the window width, and the `<Enter>`/`<Leave>` wheel claim),
and `tests/test_app_layout.py:1196` checks the region covers the body. With the
window mapped at 1280×900 (`{SCRATCH}/ui-drive2.log`):

```
canvas_actual: [1083, 644]     body_req: [1257, 2688]
scrollregion:  "0 0 1083 2688"  body_covers_canvas: true   scrollbar_present: true
yview_at_top:  [0.0, 0.2396]
pointer_over_config: widget under the pointer is a descendant of the config body
wheel after one event:  yview [0.02381, 0.26339]
wheel after six events: yview [0.14286, 0.38244]
```

The page is ~4 viewports tall, the wheel scrolls it, and the claim the test
makes is true of the app.

**Fixed:** re-confirmed in this pass with a mapped 1280×900 window and real wheel events; nothing to correct

### U3, the app's UI carries no stale tab name (UI, clean, executed, FIXED)

The tab set is 11 entries, matching `TAB_ORDER` and the manual's list:
`('Config', 'Prompt Settings', 'Tokens', 'LoRAs', 'Prompt Editor', 'Prompt
Assist', 'Prompt Catalog', 'Import', 'Prompt History', 'Queue', 'Logs')`. The
`gen_btn` state is `normal` with a request in flight, which is the documented
design ("Generate is never disabled"). `tests/test_app_layout.py:1190` asserts
the merged-page strings are gone from the UI. The stale copies that remain are
in comments and docstrings (C21) and in the manual (D4).

**Fixed:** re-confirmed: the tab set is 11 entries and `test_app_layout.py:1190` still asserts the merged-page strings are absent; nothing to correct

### X1, a stopped container reaches the user as a failed render (UX, High, executed, FIXED)

The UX face of C1. Driven through the real window
(`{SCRATCH}/ui-stopped2.log`): pressing Generate with the badge reading
`Stopped` produced no pre-flight refusal. The request was enqueued, no POST was
made, and the outcome was a modal error dialog, `status = "Failed. See Logs"`,
`gen_state = "Failed after 0s"`, and a Queue row in state `failed` whose reason
is the refusal text. The manual's promise (`salad_studio/README.md:359-361`) is
that the press refuses it *"with their reason when the press is made, not by
greying the button out"*.

The user-visible consequence: a container that is merely stopped is reported
through the render-failure channel, so the same dialog serves "the container is
down, start it in the console" and "the graph was rejected".

**Correction:** same choice as C1. If the press refuses, the dialog and the
status line say so before anything is queued; if not, the status line should
read "Refused: container down" rather than "Failed. See Logs".

**Fixed:** a refusal is a refusal: `generator.ContainerDown` makes the press report `Refused: …` with an info dialog and the Logs line the queue wrote, not `Failed. See Logs`

### X2, the log line above the refusal promises a start that never happens (UX, Medium, executed, FIXED)

`salad_studio/app.py:4863-4866` logs
``f"{p.name} reads {word or 'unknown'}; the queue starts it if it is "`` /
``"stopped and waits for it to become ready"``. The queue does no such thing
(`salad_studio/salad_queue.py:669-703`), and the observed sequence in the drive
is that line, then `queue: klein is down; not starting it`, then the failure.

**Correction:** delete the clause, or replace it with what happens: the queue
reads the group's state and refuses a container that is down.

**Fixed:** the false clause is gone; the line now says the request waits for the container's `/ready`

### X3, the same refusal is logged four times in one press (UX, Low, executed, FIXED)

One Generate press on a stopped group produced the refusal text four times
(`{SCRATCH}/ui-stopped2.log`): as the `dispatch_once` error
(`salad_studio/generator.py:607`), inside
`queue: request 1 failed on attempt 1/6 (...)`
(`salad_studio/salad_queue.py:879`), and twice more from the press's own
failure handler (`salad_studio/app.py:4913`). A reader of the Logs tab cannot
tell one event from four.

**Correction:** log the refusal once at `error` and let the Queue row carry it
thereafter.

**Fixed:** one press writes one line with the refusal sentence: `dispatch_once` no longer logs it, the queue logs it once, and the press reports it without repeating it. Tests: `test_config_page.py` `test_a_group_that_goes_down_after_the_badge_is_reported_as_refused`

### X4, the documented suite time is ~3.5× the measured one (UX, Low, executed, FIXED)

`README.md:31` and `salad_studio/README.md:537` both say
`# 917 tests, ~6 min`. The captured run took `1253.590s` (20.9 min) on this
machine, with nothing else heavy running. The count is right; the duration is
not.

**Correction:** state the measured figure, or drop the duration.

**Fixed:** both READMEs state the measured range, `~14-18 min` (820 s, 1081 s and 827 s across the three runs of this pass; the audit's own run was 1253.6 s), instead of `~6 min`

### D1, the manual says a group that is not running is refused at the press (docs, High, executed, FIXED)

`salad_studio/README.md:359-360`:

```
being blocked. The press is the gate — a replica that is gone, and a group that
is not running, are refused with their reason when the press is made, not by
greying the button out.
```

The shipped behavior is C1/X1: the press is not refused. **Correction:** match
whichever way C1 is resolved.

**Fixed:** the manual says the press refuses a gone replica and a group the badge says is stopped, with the Logs line, the status line and the dialog carrying that one sentence

### D2, `salad_klein/README.md` links a test that moved (docs, Medium, executed, FIXED)

`salad_klein/README.md:33` — the link target `../salad_studio/test_klein_prompt_catalog.py`.
`salad_studio/test_klein_prompt_catalog.py` does not exist; the file is
`tests/test_klein_prompt_catalog.py` (moved by `6df70fc`). This is the only
broken relative link among the 71 links in the tree.

**Correction:** `../tests/test_klein_prompt_catalog.py`.

**Fixed:** the link is `../tests/test_klein_prompt_catalog.py`

### D3, `salad_klein/README.md` gives a test command that runs zero tests (docs, High, executed, FIXED)

`salad_klein/README.md:34` — ``Tests for the verified recipe: `python -m unittest discover -s salad_studio -p "test_klein_recipes.py"` ``.
Executed:

```
python -m unittest discover -s salad_studio -p "test_klein_recipes.py"  ->  Ran 0 tests ... NO TESTS RAN
python -m unittest discover -s tests          -p "test_klein_recipes.py"  ->  Ran 17 tests ... OK
```

**Correction:** `-s tests`.

**Fixed:** the command is `discover -s tests -p "test_klein_recipes.py"`, and the same file documents the `salad_klein` command

### D4, the manual names a Vast.ai page that no longer exists (docs, High, executed, FIXED)

`salad_studio/README.md:141-142` — ``provider file convention, so the store is its only home: the **Vast.ai** page`` / ``reads it from there.``
There is no `Vast.ai` tab (`app.TAB_ORDER` has 11 entries, none of them
`Vast.ai`); the instances section lives on Config, and the code already says so
(`salad_studio/tokens.py:11`).

**Correction:** "the **Config** page's Vast.ai instances section reads it from
there."

**Fixed:** the manual says the Config page's Vast.ai instances section

### D5, the root README says the package holds the test suite (docs, Medium, executed, FIXED)

`README.md:49` — `| `salad_studio/` | The Tkinter app and its test suite. ... |`.
`salad_studio/` holds no `test_*.py`; the suite moved to `tests/` (`6df70fc`),
and the manual says so (`salad_studio/README.md:540-542`). The layout table has
no `tests/` row at all.

**Correction:** drop "and its test suite" and add a `tests/` row.

**Fixed:** the layout table says the app, and has a `tests/` row

### D6, the history list stops at 59 (docs, Low, read-from-source, FIXED)

`README.md:52` links audits 57, 58 and 59.
`docs/history/60-salad-container-restart-2026-09-27.md` exists and is not
listed (it is an investigation rather than an audit, so say that).

**Correction:** list 60, labelled.

**Fixed:** the history list names 57, 58, 59, 61 and the container-restart investigation 60

### D7, `docs/workflow/15` names tabs that no longer exist (docs, Medium, executed, FIXED)

`docs/workflow/15-salad-flux2-klein-group.md:333` — ``Tabs: **Config**, **Policy**, **Tokens**, **LoRAs**, **Prompt Editor**, **Prompt**, **Import**, **Prompt History**, **Logs**.``
plus a `| Policy |` row at `:339`. `Policy` and `Prompt` are gone (the policy
is the Config page's section; `Prompt` is `Prompt Settings`), and
`Prompt Assist`, `Prompt Catalog` and `Queue` are missing. The
`test_docs_match` tab check covers the manual, not this document.

**Correction:** replace with the 11 shipped tabs and delete the `Policy` row.

**Fixed:** the tab list is the 11 shipped tabs and the `Policy` row is gone

### D8, `docs/workflow/15` tells a reader to build the superseded image (docs, Medium, executed, FIXED)

The document's dated status block (`:1-10`, 2026-09-21) is a record and should
stay. The **instructions** are not: `:313` `Rebuild + push (**recipe prefetch4**; ...)`,
`:317-318` `docker build/push ... -prefetch4 salad_klein`, `:439-440`
`| Published image (recipe) | ...-prefetch4 |` / `| Published image (live) | .-prefetch3 until the group Image is PATCHed |`,
`:476-485` and `:530-582` the same `-prefetch4` build, push and registry
commands. The shipped document and every current doc use `prefetch6`:

```
studio-metadata.json klein image = docker.io/vkozyrev0/eldermark-klein:comfy0.35-api1.19.2-prefetch6-klein
studio-metadata.json snofs image = docker.io/vkozyrev0/eldermark-klein:comfy0.35-api1.19.2-prefetch6-snofs
```

**Correction:** update the tables and the build/push commands to the two
`prefetch6` tags, leaving the dated status block as the record (the precedent
audit 59's D7 set).

**Fixed:** the tables and the build/push commands use `-prefetch6-klein` / `-prefetch6-snofs`; the dated status block above them stays as the record

### D9, `docs/workflow/15` uses the old group name (docs, Low, read-from-source, FIXED)

`docs/workflow/15-salad-flux2-klein-group.md:44` — `| Portal / API name | `flux2-klein` | `flux2-klein-5090` |`
(also `:57`, `:442`, `:493`). The same document writes `flux2-klein2` at
`:325`, and `docs/workflow/21:84`, `docs/workflow/22:275` and
`docs/history/60:61` all name `flux2-klein2` for the gateway the app uses.

**Correction:** `flux2-klein2`.

**Fixed:** `flux2-klein2`

### D10, `docs/workflow/14` uses the old group name (docs, Low, read-from-source, FIXED)

`docs/workflow/14-salad-comfy-live-findings.md:276` — ``- Flux.2 Klein custom group **`flux2-klein`** (`life-sim` / `default`,``.
Same correction as D9.

**Correction:** `flux2-klein2`.

**Fixed:** `flux2-klein2`

### D11, two documents state a startup-probe delay the shipped document contradicts (docs, Medium, executed, FIXED)

`docs/workflow/15-salad-flux2-klein-group.md:53` — ``| Startup | `GET /health` :3000, delay 600, period 120, fail 20 (~50 min) | same |``
(also `:302`, `:363`, `:588`) and
`docs/workflow/23-salad-container-group-deployment.md:193` — ``| Startup probe | `GET /health`, delay **600**, period **120**, fail **20** (~50 min). ...``.
The shipped metadata document says `initial_delay_seconds: 1200`, and
`docs/history/60:147` records the live group at 1200. A reader creating a group
from doc 23's portal table configures 600.

**Correction:** 1200 (~60 min) in both.

**Fixed:** both documents say delay 1200 (~60 min), matching the shipped document and the live group

### D12, `docs/workflow/15` cites a test count and a command that no longer resolve (docs, Medium, executed, FIXED)

`docs/workflow/15-salad-flux2-klein-group.md:269` — ``...drives both files through the Studio Validate gate and the POST copy (24 tests).``
The module is `tests/test_klein_recipes.py` with 17 test methods, and
`docs/history/58:353-354` records the rewrite from 24 to 17.

**Correction:** the discovery command and "17 tests".

**Fixed:** the discovery command and "17 tests"

### D13, `docs/workflow/17` calls a function that does not exist (docs, High, executed, FIXED)

`docs/workflow/17-klein-two-body-anatomy-research.md:85` — ``so `generator.warm_loras` fetches the graph's Civitai``.
`generator.warm_loras` is not in `salad_studio/generator.py` (sweep: zero
hits), and the design it describes was superseded — `docs/workflow/18` §3.2
records the replacement, `generator.check_lora_urls`, which verifies a URL and
downloads nothing.

**Correction:** replace the sentence with the shipped URL-verify behavior.

**Fixed:** the paragraph now describes `generator.check_lora_urls` and points at the superseded warm-up design

### D14, `docs/workflow/17` states the old test count (docs, Low, executed, FIXED)

`docs/workflow/17-klein-two-body-anatomy-research.md:12` — ``- `tests/test_klein_recipes.py`, 24 tests asserting the old recipe.``
The module has 17 test methods and its docstring records the change.

**Correction:** "17 tests asserting the verified entry".

**Fixed:** "17 tests asserting the verified entry"

### D15, `docs/workflow/18` names a suite path that does not exist here (docs, Low, executed, FIXED)

`docs/workflow/18-sdxl-migration-brief.md:267` — ``...and the full `src/tools` suite is 540 tests ...``.
This repo has no `src/tools`; the suite is `tests/` at 917 methods.

**Correction:** name the current path and count, or mark the figure historical.

**Fixed:** the suite this repo runs, 966 tests

### D16, `docs/workflow/19` claims a document was copied into the repo (docs, Medium, executed, FIXED)

`docs/workflow/19-two-body-prompt-playbook.md:283` — ``### 6.8 Comfy recipe cards. `docs/workflow/20-comfy-klein-snofs-recipe-cards.md```
and `:285` — ``The full write-up (21 KB, **copied verbatim into the repo**) adds four position cards ...``.
`docs/workflow/20-comfy-klein-snofs-recipe-cards.md` does not exist, and
`README.md:61` says the numbering *"skips 20 because those files came from a
larger docs tree; the gaps are not missing work."* A document that depends on
it contradicts that.

**Correction:** restore the file, or drop the "copied verbatim into the repo"
claim and the section's pointer.

**Fixed:** the section no longer claims a file that is not here; the heading says the cards are kept outside the repo

### D17, `docs/workflow/21` describes a metadata key that was deleted (docs, High, executed, FIXED)

`docs/workflow/21-klein-image-handoff.md:124` — ``of the saved profiles is left alone. Changing the document's `group` (or its``
/ `:125` — ``optional `gateway`) moves a family with no code edit;``.
Commit `cc8768e` removed both: *"The document keeps what a family is (its seed
unets, markers, image); group and gateway are gone because the profile is the
authority now."* The shipped families carry only
`deployment`, `image`, `markers`, `readiness_probe`, `startup_probe`, `unets`.

**Correction:** delete the sentence; a family moves by editing a profile's
`checkpoints` list on Config.

**Fixed:** the paragraph says a profile's `checkpoints` list decides, and that the document's `group`/`gateway` are gone

### D18, `docs/workflow/21` attributes the refusal to the document (docs, Medium, executed, FIXED)

`docs/workflow/21-klein-image-handoff.md:119-120` — ``A checkpoint with no entry in `routing.families` is **refused with a stated`` / ``reason** rather than sent to a group that cannot serve it.``
`profiles.checkpoint_family` (`salad_studio/profiles.py:126-131`) says the
opposite — *"A checkpoint the metadata does not classify is its own family, so
a profile that lists only it is consistent, and a checkpoint that does not
exist yet needs no metadata edit to be routable"* — and `plan_route` refuses
when **no profile lists** the checkpoint.

**Correction:** "A checkpoint no profile's list names is refused…".

**Fixed:** the refusal is attributed to the profile list, and a checkpoint the document does not classify is its own family

### D19, `docs/workflow/21` lists a document that is not in the tree (docs, Low, executed, FIXED)

`docs/workflow/21-klein-image-handoff.md:22` — ``The research documents (14, 17, 18, 19, 20) are the **record of how this was learned** …``.
There is no `docs/workflow/20-*.md` (D16).

**Correction:** list 14, 17, 18, 19.

**Fixed:** the list is 14, 17, 18, 19

### D20, a stale `.gitignore` line reference (docs, Low, executed, FIXED)

`docs/workflow/21-klein-image-handoff.md:304` — ``| `salad_studio/studio-tokens.json` | provider keys, incl. Civitai, not git (`.gitignore:111`) |``.
`.gitignore` has 15 lines and the entry is line 2:
`git check-ignore -v salad_studio/studio-tokens.json` →
`.gitignore:2:salad_studio/studio-tokens.json`. `docs/history/57:470`
carries the same stale reference.

**Correction:** `.gitignore:2`.

**Fixed:** `.gitignore:2`, with the old number kept as the record in doc 57

### D21, two history documents give a suite command that discovers nothing (docs, Low, executed, FIXED)

`docs/history/58-salad-studio-audit-2026-09-22.md:326` and
`docs/history/59-salad-studio-audit-2026-09-26.md:19` (also `:243`) both give
`python -m unittest discover -s salad_studio -p "test_*.py"`, which the tests
leaving the package invalidated:

```
python -m unittest discover -s salad_studio -p "test_*.py"  ->  Ran 0 tests ... NO TESTS RAN
```

`docs/history/59:125` also describes `test_docs_match.py` as counting
`def test_` across `salad_studio/test_*.py`; it now globs
`tests/test_*.py` (`tests/test_docs_match.py:156`).

These are dated records, so the correction is a forward note rather than a
rewrite — but a reader who follows the command gets nothing.

**Correction:** a one-line note in each that the tests moved to `tests/` and
the command is `-s tests`.

**Fixed:** both records carry a forward note naming the command today

### D22, `docs/history/60` describes the pre-`d52907b` start behavior (docs, High, executed, FIXED)

`docs/history/60-salad-container-restart-2026-09-27.md:123` — ``POSTed `…/containers/flux2-klein2/start`. `salad_queue.py` logs that as "asked``.
Commit `d52907b` (2026-10-13) reversed this: the queue no longer starts a
container, and `salad_queue.ensure_container` only reads the state and returns
a refusal. The manual confirms it (`salad_studio/README.md:379`).

**Correction:** mark the document as describing the 2026-09-27 tree, and state
the current mechanism (refuse, never start) in a forward note. The
idle-stop/ownership analysis in the same document is still accurate.

**Fixed:** the document opens §3 with a forward note that `d52907b` removed the start path

### D23, `docs/history/60` names two tests that no longer exist (docs, Medium, executed, FIXED)

`docs/history/60-salad-container-restart-2026-09-27.md:234-235` names
``test_a_fresh_process_stops_the_container_the_app_started`` and
``test_a_stopped_container_is_started_then_waited_for_before_the_post``. The
current names are `test_a_stopped_container_is_refused_and_never_started`
(`tests/test_salad_queue.py:630`),
`test_a_running_container_is_not_started` (`:696`) and
`test_a_fresh_process_stops_the_container_an_older_session_started` (`:983`),
so the document's "Reproducing this" section cannot be run as written.

**Correction:** the current names.

**Fixed:** the two current test names

### D24, the civitai-verify skill attributes routing to the wrong module (docs, Medium, executed, FIXED)

`.claude/skills/civitai-verify/SKILL.md:60` — ``Routing and the container groups come from the metadata document (`salad_studio/studio-metadata.json`, ...), read through `studio_meta`; a graph whose checkpoint has no entry there is refused with a stated reason ...``.
`civitai_verify.py` never imports `studio_meta` (zero hits) and reads the
groups from the profile store (`profiles.load_all`,
`salad_studio/civitai_verify.py:215`); routing is `profiles.plan_route` over
each profile's `checkpoints` list. `tests/test_docs_match.py:402`
(`test_the_queue_facts_come_from_salad_queue`) asserts only that the literal
token `studio_meta` appears in that section (`:414`), so the false claim
passes.

**Correction:** "the container groups come from the profile store
(`profiles.load_all`); the metadata document supplies the family markers, the
seed unets and the image. A checkpoint no profile's list names is refused with
a stated reason." Then tighten the test to assert the claim, not the token.

**Fixed:** the skill says the groups come from the profile store and routing is `profiles.plan_route`

### D25, the manual's Prompt Settings labels are abbreviated and incomplete (docs, Low, executed, FIXED)

`salad_studio/README.md:133-135` — ``**Scheduler** (Flux2 / Simple), the **Checkpoint** (Base 9B / Distilled 9B) ...``.
The shipped labels are `Flux2 (Klein)` / `Simple (Civitai)`
(`salad_studio/app.py:687`), and the checkpoint combo has a third option,
`SNOFS 9B` (`request_json.UNET_LABELS`).

**Correction:** use the shipped label strings and add `SNOFS 9B`.

**Fixed:** the manual uses the shipped labels and names `SNOFS 9B`

### D26, the "image tag" field is labelled "Image" (docs, Low, executed, FIXED)

`salad_studio/README.md:47-49` and
`docs/workflow/23-salad-container-group-deployment.md:104` call it the **image
tag**; the shipped label is `Image` (`salad_studio/app.py:1001`).

**Correction:** call it the **Image** field.

**Fixed:** both documents call it the **Image** field

### P1, no presentation artifact exists in the tree (presentations, High, executed, DEFERRED)

The objective names "presentations". A tree-wide search for `*.pptx`, `*.ppt`,
`*.key`, `*.odp` and any marp / reveal / remark / slides source returns
nothing, and there is no `docs/` file that presents the work to an audience.
The presentation surfaces that do exist are: the three READMEs
(`README.md`, `salad_studio/README.md`, `salad_klein/README.md`), the nine
`docs/workflow/` playbooks, and the `graph_html/` viewer.

**Correction:** either state the objective's "presentations" as satisfied by
those surfaces (and fix D2, D3, D7, D8, D12, D16 in them), or make producing a
deck an explicit deliverable of the follow-up goal. This pass records the
absence; it does not produce a deck (see §5).

**Deferred:** there is still no slide deck. Reason: producing one is out of scope for this pass (the plan's non-goals); the presentation surface that exists — the three READMEs, `docs/workflow/` and the `graph_html/` viewer — is corrected above (D2–D8, P3, P4)

### P2, the `graph_html/` viewer surface is correct (presentations, clean, executed, FIXED)

`salad_studio/graph_html/VENDOR.txt` pins `@joint/core 4.2.5` (MPL-2.0) and
`litegraph.js 0.7.18` (MIT) with their upstream URLs and says which one is the
live pane; `viewer.html` and `litegraph.html` are tracked; the two generated
files (`_current.html`, `_litegraph.html`) are excluded by
`salad_studio/graph_html/.gitignore` and are not tracked (`git ls-files`
returns only the seven source files). `docs/workflow/16` matches the code:
`prompt_to_joint`, the `GraphPane`/tkwry embed, the `%LOCALAPPDATA%` user-data
dir, and the statement that the Graphviz/grandalf stack is gone.

**Fixed:** re-confirmed: `VENDOR.txt` pins both libraries and the two generated files are untracked; nothing to correct

### P3, the playbook a reader would present from is stale (presentations, Medium, executed, FIXED)

`docs/workflow/15-salad-flux2-klein-group.md` is the Klein group playbook the
root README points at (`README.md:51`), and its tab table (D7), its image tags
(D8), its group name (D9), its probe delay (D11) and its test count (D12) are
all wrong. A reader presenting from it describes an app with a Policy tab and
an image three revisions old.

**Correction:** D7–D12.

**Fixed:** the playbook's tab table, image tags, group name, probe delay and test count are all corrected (D7–D12)

### P4, the build-context README's two references are broken (presentations, Medium, executed, FIXED)

`salad_klein/README.md` is the short form a reader uses to build and present
the image. Its prompt-catalog link (D2) 404s and its test command (D3) runs
zero tests. Its image tags, ports, build args and unet sets are otherwise
correct against the shipped metadata document.

**Correction:** D2, D3.

**Fixed:** the two references are corrected (D2, D3)

### P5, `docs/workflow/16` and `docs/workflow/22` are clean (presentations, clean, executed, FIXED)

Doc 16 (the graph-pane decision record) matches `graph_view.py` and
`VENDOR.txt` on every checkable claim, and all its links resolve. Doc 22 is an
external research record whose repo-internal claims (port 3000, one unet family
per group, the two group names, `before_start: []`) match the code and the
other documents.

## 3. Doc-vs-source verdicts

| Document | Verdict |
|---|---|
| `README.md` | Test count right (917), duration wrong (X4), layout table wrong (D5), history list stops at 59 (D6) |
| `salad_studio/README.md` | The real manual; drifted in three places (D1, D4, D25, D26) and its Prompt Assist / layer-map / tab-list sections are machine-checked and correct |
| `salad_klein/README.md` | Image tags, ports and unet sets correct; the prompt-catalog link (D2) and the test command (D3) are wrong |
| `docs/workflow/14` | Group name stale (D10) |
| `docs/workflow/15` | Dated status block is a record and stays; the tab table, image tags, group name, probe delay, test count and commands are stale (D7–D12) |
| `docs/workflow/16` | Correct (P5) |
| `docs/workflow/17` | `generator.warm_loras` does not exist (D13); old test count (D14) |
| `docs/workflow/18` | `src/tools` suite path (D15) |
| `docs/workflow/19` | Points at a document that is not in the repo (D16) |
| `docs/workflow/21` | A deleted metadata key (D17), a misattributed refusal rule (D18), a missing document (D19), a stale line reference (D20) |
| `docs/workflow/22` | Correct (P5) |
| `docs/workflow/23` | Probe delay 600 vs 1200 (D11); "image tag" label (D26) |
| `docs/history/57` | Dated record; carries the shared stale `.gitignore:111` (D20) |
| `docs/history/58` | Dated record; suite command (D21) |
| `docs/history/59` | Dated record; suite command and `test_docs_match` description (D21) |
| `docs/history/60` | Dated record; the start behavior it describes was reversed (D22) and two test names moved (D23) |
| `.claude/skills/civitai-verify/SKILL.md` | Flags, retry cap, ablation order, journal strings and `BUSY_CODES` are machine-checked and correct; the routing attribution is not (D24) |

## 4. Observed test state

```
python -m unittest discover -s tests -p "test_*.py"
Ran 917 tests in 1253.590s
OK
```

917 matches the count both manuals state. The run's 9 564 lines include 2 129
Tcl teardown errors and 52 `RuntimeError` tracebacks from worker threads
(T1); the suite is green regardless.

**After the fix pass (2026-10-14):** `Ran 966 tests in 1080.892s` / `OK`, with
**0** `invalid command name` lines, 0 worker-thread tracebacks, and the count
both manuals now state (966). Captured twice after the last change, to
`{SCRATCH}/suite2.log` and `{SCRATCH}/suite3.log`.

```
python test_salad_comfy_live_findings.py   ->  exit 0 (passes)
python -m unittest discover -s salad_studio -p "test_*.py"  ->  Ran 0 tests (D21)
cd salad_klein; python -m unittest test_prefetch          ->  Ran 15 tests, OK
cd salad_klein; python -m unittest test_hf_gated_access   ->  Ran 1 test, OK
cd salad_klein; python -m unittest test_http              ->  Ran 0 tests (T3)
```

## 5. Out of scope and deliberately deferred

- **The deferrals are C23 and P1**, and nothing else: C23 (three shipped scripts
  still import two modules that stayed in the Eldermark repo) and P1 (no slide
  deck). Each names its reason in §2. The four clean verdicts (U2, U3, P2, P5)
  are not deferrals: they were re-driven in this pass and needed no change.
- **No Salad-side work**: no image rebuild, no group or container changes, no
  live render POSTs.
- **The dated `docs/history/` records (57–60) are not rewritten.** D20–D23 ask
  for forward notes on the documents that predate the change, not edits to the
  record.
- **The dated status blocks in `docs/workflow/15` (`:1-10`) stay** — audit 59's
  D7 set that precedent. D8 covers the instructions below them.
- **No deck is produced** (P1). This pass records that the tree has no
  presentation artifact; producing one is a follow-up decision.
- **`salad_catalog_faces.py`, `salad_probe_ages.py` and `salad_probe_sdxl.py`
  stay broken** (C23) — the README documents it and the root structural check
  asserts it. Whether to vendor `paperdoll_mask` / `regen_faces` or delete the
  three scripts is a follow-up decision.
- **`generator.generate()`** (prompt text plus knobs, no shipped caller) is
  kept, as audit 59's L4 decided.
- **`salad_queue`'s in-flight abort limit** (a POST the container accepted
  cannot be cancelled) is unchanged, as audit 59's U4 decided.


## 6. How the closure was verified

The fix pass re-captured every observation it relies on into its own scratch
directory (`C:\Users\vkozy\AppData\Local\Temp\grok-goal-b2a9e525583e\implementer\`),
because the audit's directory had been deleted:

| Capture | What it shows |
|---|---|
| `closure.log` | the parse of this document: 71 findings, all six areas, 69 FIXED and 2 DEFERRED, each deferral naming a reason and listed in §5; then `test_docs_match`'s audit-artifact check, 8 tests OK, including the four that drive the rule with a document that breaks it |
| `code-findings.log` | each behaviour fix driven against the module **as HEAD had it** and as it ships now: C2 `JSONDecodeError` → `{}`, C3 `JSONDecodeError` → 22 rows, C4 `None` → the plate, C5 `{'api': 0, 'comfy': 0}` → `{'api': 3000, 'comfy': 8188}`, C10 no flag → `True`, C11 `UnboundLocalError` → `SystemExit(gateway not ready after 0s)`; then the tests that drive the same shipped functions, 28 tests OK |
| `press.log` | the press driven both ways (badge Stopped, and badge Ready with the group down): no POST, `Refused: …` on the status line, the dialog carrying the queue's own sentence, the refusal in the Logs exactly once, and not reported as a failure. The manual's four sentences checked against the same run |
| `docs.log`, `linkcheck.log` | 63 relative links, all resolving; the image tags, group name, probe delay, tab list and suite commands matching `studio-metadata.json`, `app.TAB_ORDER` and the suite |
| `suite.log`, `suite2.log`, `suite3.log`, `docs-match.log` | the discover run and the doc check. The last two discover runs: `Ran 966 tests … OK` with **0** `invalid command name` lines each, against 2 129 in the audit's run |
| `launch.log` | `python -m salad_studio` alive after 15 s with nothing on stderr, and two windows built in one process showing the same tabs, status and scroll region |
| `ui.log` | the Queue, Prompt History, Prompt Catalog and history-strip empty states, read off the widgets with empty stores |

The first discover run after the fixes (`suite.log`) still carried 5
`invalid command name` lines from the graph pane's own `after_idle` redraw; that
is fixed (`GraphPane._soon` tracks its callbacks and `destroy` cancels them), and
the runs captured after it have none.

## 7. Index for the follow-up goal

| Severity | Findings |
|---|---|
| High | C1, C2, D1, D3, D4, D13, D17, D22, P1, X1 |
| Medium | C3, C4, C5, C6, C7, C8, D2, D5, D7, D8, D11, D12, D16, D18, D23, D24, P3, P4, T1, T2, T3, T4, T5, X2 |
| Low | C9, C10, C11, C12, C13, C14, C15, C16, C17, C18, C19, C20, C21, C22, C23, D6, D9, D10, D14, D15, D19, D20, D21, D25, D26, T6, T7, T8, T9, T10, U1, X3, X4 |
| clean (no issue found; marked FIXED because nothing needed correcting) | U2, U3, P2, P5 |
| DEFERRED (the reasons are in §5) | C23, P1 |

Every finding above names its artifact (file and line), its category and
severity, and the correction it implies. No item raised in this document is
left unclassified.

**Fixed:** re-confirmed against `graph_view.py`, `VENDOR.txt` and the other documents; nothing to correct
