# Salad Studio audit, 2026-09

> **Scope:** `salad_studio/` (the Windows Tk helper, *not*
> `eldermark` / `lifesim_core`) in its working-tree state on 2026-09-21.
> **Kind:** read-only audit. No file under `salad_studio/` was
> edited; the only repo change made by this audit is this report plus one
> `docs/00-INDEX.md` row.
> Companion docs: [`../workflow/16-salad-studio-prompt-graph.md`](../workflow/16-salad-studio-prompt-graph.md),
> [`../workflow/15-salad-flux2-klein-group.md`](../workflow/15-salad-flux2-klein-group.md),
> [`../../salad_studio/README.md`](../../salad_studio/README.md).

## 0. How this audit was run (and what is proven vs inferred)

Every claim below is anchored to a file and function/line. Three evidence
classes are kept distinct:

- **Proven.** The code path was executed (the suite, a repro script driving
  the shipped function, or a live Salad POST) and the output is quoted.
- **Read from source.** The defect is a static property of the code
  (unreachable statement, unassigned attribute, unused constant, dead call
  graph). No run can reach it, so no run is needed.
- **Suspicion.** Plausible but not demonstrated; listed separately in §6.

Two notes on the working tree. First, the app was **already mid-change** when
the audit began: `git status` showed 12 modified files plus the untracked
`ui_state.py`, and `docs/workflow/15` + `docs/workflow/16` were also already
modified. Those states are audited as the current source; the audit changed
none of them. Second, `AGENTS.md` §0 (metadata-only, no literals in `.rs`,
theme-in-CSS) governs `lifesim_core` and `lifesim_ui_dioxus`. Salad Studio is
a developer tool under ``, so hardcoded node-type lists, sampler
names, and hex colors in `salad_studio/*.py` are ordinary tool constants, not
Rule 0.1/0.5 violations. This report treats them as such.

Raw evidence captured in the audit scratch dir:

| Evidence | What it shows |
|---|---|
| `salad_studio_suite.log` | Full `unittest` discover run: 297 tests, 8 failures + 3 errors |
| `salad_studio_skill_prescribed_tests.log` | The subset `civitai-verify`'s SKILL.md prescribes: 99 tests, OK |
| `repro_lora_persist.log` | `lora_store.add_lora` returns an item but writes no extras row |
| `repro_tree_columns.log` | Prompt-history `Treeview` column→index mapping |
| `repro_profiles_ui_state.log` | `profiles.load_all` raises on a non-numeric field; `ui_state` corrupt-JSON path |
| `civitai-verify-135440425/journal.jsonl` | Import/Convert/inspect on a real Civitai image (`--no-post`) |
| `civitai-verify-live/journal.jsonl` + `out/studio_*.jpg` + `site_135440425.jpg` | Live Salad POST → JPEG, then `--record-compare` → `similar: true` |

---

## 1. Verdict per app module

All 18 non-test modules of `salad_studio/` are covered. "Worst" is
the highest-severity finding recorded for that module.

| Module | Lines | Verdict | Worst finding |
|---|---|---|---|
| `__init__.py` | 1 | Clean. A one-line docstring, no behavior |  |
| `__main__.py` | 4 | Clean but untested | M19 |
| `app.py` | 2723 | **Needs work**. One live crash, render-path I/O, dead tab reference | **H2** |
| `comfy_import.py` | 3016 | Sound, best-tested; one duplicated hardcoded list | M6 |
| `civitai_verify.py` | 2040 | Sound; writes shipped source by default | M16 |
| `generator.py` | 312 | Sound | L1 |
| `graph_view.py` | 1845 | **Needs work**. Dead Graphviz stack, unreachable fallback selection | M7, M8 |
| `history_strip.py` | 194 | Sound but has **no behavioral test at all** | M17 |
| `json_highlight.py` | 113 | Clean |  |
| `lora_store.py` | 1769 | **Needs work**. Silent persistence failure on Add | **H1** |
| `profiles.py` | 241 | Sound; unguarded field coercion crashes boot | L5 |
| `prompt_history.py` | 323 | Sound |  |
| `request_json.py` | 865 | Sound; its CLIP rule is what the docs and one test disagree with | M14 |
| `salad_status.py` | 664 | Sound; one unreachable duplicate function body | M3 |
| `studio_log.py` | 155 | Clean | L3 |
| `theme.py` | 439 | Clean. The only module with a dedicated live-window test |  |
| `tokens.py` | 130 | Sound; `read_token` writes on read | L9 |
| `ui_state.py` | 28 | Sound; new/untracked, no dedicated test | M18 |

Test modules present: 15 (`test_app_layout`, `test_civitai_verify`,
`test_comfy_import`, `test_generator`, `test_graph_view`, `test_json_editor`,
`test_lora_store`, `test_profiles`, `test_prompt_history`, `test_request_json`,
`test_salad_status`, `test_studio_log`, `test_theme`, `test_tokens`,
`test_watercolor_import`).

---

## 2. Defects proven from code or a reproduced run

### H1. `lora_store.add_lora` silently discards the row for local / HF / URL / bare-filename refs (High)

**Where.** `lora_store.py:1621` `add_lora`, specifically the tail at
`lora_store.py:1677-1681`:

```python
1677  if not str((item.get("source") or {}).get("version_name") or "").strip() and (
1678      verify or verified is True
1679  ):
1680      return ensure_civitai_version_name(item, extras_path=extras_path, live=True)
1681  return write_extra(item, extras_path)
```

`ensure_civitai_version_name` (`lora_store.py:739`) returns the item
**without persisting** whenever it cannot resolve a Civitai version id. See
the early returns at `lora_store.py:749-750` (a version name is already set)
and `lora_store.py:754-755`:

```python
754  if not vid or not live:
755      return item
```

`write_extra` (`lora_store.py:1684-1691`) is the only code path that saves an
extras row.

**Proven.** `{SCRATCH}/repro_lora_persist.log`, driving the shipped
`add_lora` with a temp `extras_path`:

```
add_lora returned id      : local:on_disk.safetensors
add_lora returned verified: True
extras file exists        : False
find_lora after add       : None
list_loras has the row    : False
verify=False -> file?     : True
```

**Impact.** In the LoRAs tab, Add reports success. `app.py:1739-1746`
appends the id to the pending selection, sets `Added LoRA <id>`, logs `ok`,
and the row is listed until the next `_refresh_lora_lists`
(`app.py:1620-1673`). On the next launch the row is gone, because nothing was
written. `edit_lora` (`lora_store.py:1726`) then raises
`ValueError: unknown LoRA <id>` at `lora_store.py:1739`, which is exactly the
error the suite reports for
`test_add_and_edit_family_name_filename_strength`.

**Remediation.** Persist on both branches, e.g.

```python
item = ensure_civitai_version_name(item, extras_path=extras_path, live=True)
return write_extra(item, extras_path)
```

**Blast radius in the suite.** 7 of the 11 non-passing tests trace here
(§4). Three sibling tests (`test_add_huggingface_url`,
`test_add_direct_download_url`, `test_add_civitai_short_ref`) pass only
because they assert on the returned dict and never check the file. The bug
is masked, not absent.

### H2. `_reuse_prompt_history` dereferences the removed Prompt tab (High, live crash)

**Where.** `app.py:1483`, inside `SaladStudio._reuse_prompt_history`
(`app.py:1463`): `self.nb.select(self._prompt)`.

`self._prompt` is never assigned anywhere in `app.py`. The notebook panes are
added at `app.py:92-101` (`_config`, `_policy`, `_tokens`, `_loras`,
`_editor`, `_import`, `_prompt_hist`, `_logs`), and `TAB_ORDER`
(`app.py:28-37`) contains no "Prompt" entry.

**Proven.** Suite error:

```
AttributeError: '_tkinter.tkapp' object has no attribute '_prompt'
  File ".../app.py", line 1483, in _reuse_prompt_history
```

**Impact.** The text-only branch of Reuse / double-click (a history row with
no stored request JSON) loads the text into the positive-prompt box
(`app.py:1479-1481`) and then throws inside the Tk callback. The
request-JSON branch returns earlier (`app.py:1471-1478`) and is unaffected.

**Remediation.** `self.nb.select(self._editor)`, or delete the line.

### M3. `salad_status._api_get` is dead after its first statement (Medium)

**Where.** `salad_status.py:73-94`. Line 74 is
`return _api_request("GET", url, key)`; lines 75-94 are a second, hand-rolled
GET implementation that can never execute (the next `def` is at
`salad_status.py:97`).

**Read from source.** Not reachable by any test or call.

**Remediation.** Delete `salad_status.py:75-94`.

### M6. Two overlapping hardcoded lists of replica-missing node types (Medium)

**Where.** `comfy_import.py:26-36` `SALAD_MISSING_TYPES` versus the inline
tuple at `comfy_import.py:2694-2704` inside `prompt_for_salad_replica`
(`comfy_import.py:2669`):

- only in the inline tuple: `POWER_LORA` (also `comfy_import.py:37`),
  `Fast Groups Bypasser (rgthree)`, `easy cleanGpuUsed`, `ColorNoiseComfy`;
- only in `SALAD_MISSING_TYPES`: `ReferenceLatent`, `ConditioningZeroOut`,
  `Color Correct GPU (mtb)`, handled by a *third* block
  (`comfy_import.py:2726-2745`) that rewires instead of dropping.

**Corroborated by the tool that has to patch both.**
`civitai_verify.add_salad_missing_type` (`civitai_verify.py:1247-1266`)
inserts a new class into `SALAD_MISSING_TYPES` *and* into the
`if _is_uuid_type(cls) or cls in (` tuple, i.e. the duplication is already
load-bearing for the auto-fix and will silently drift when only one list is
edited.

**Remediation.** Build the omit tuple from `SALAD_MISSING_TYPES` plus the
explicit pass-through set, so there is one list.

### M7. Graphviz/grandalf layout stack is dead on the live path, and one docstring asserts the opposite (Medium)

**Where.** `graph_view.py`:
- module docstring, `graph_view.py:5`: "Graphviz helpers remain unused on the
  live path";
- `resolve_layout` (`graph_view.py:1250`) whose docstring at
  `graph_view.py:1260` says "Live layout is Graphviz. Never silently fall back
  to `layout_xy`.". **false**: the live pane renders through
  `prompt_to_joint` (`graph_view.py:479`) → `_place_joint_columns`
  (`graph_view.py:426`);
- `prompt_to_dot` (`graph_view.py:1315`), `run_dot` (`1436`),
  `graphviz_layout` (`1454`), `find_dot` (`1281`), `parse_dot_plain`
  (`1397`), `grandalf_resolve` (`1120`).

**Read from source.** Call-graph check over the whole package: these
functions are referenced only from tests, `test_graph_view.py:89`
(`grandalf_resolve`), `:96` (`resolve_layout`), `:219` (`prompt_to_dot`),
`:234` (`graphviz_layout`), and `test_app_layout.py:62-65` asserts their
source strings. `GraphPane` (`graph_view.py:1621-1807`) never calls
`resolve_layout` or `graphviz_layout`.

**Remediation.** Delete the stack with its tests, or retag the
`resolve_layout` docstring and the `workflow/16` claim (§3.2, W8/W9).

### M8. The Tk fallback canvas cannot select a card; Swap is unreachable without WebView2 (Medium)

**Where.** `graph_view.py:1629` creates `self._boxes`;
`graph_view.py:1772` resets it to `{}` inside `_redraw` and nothing ever fills
it; the only reader is `_on_click` (`graph_view.py:1715-1728`). When the embed
fails (`_on_web_fail`, `graph_view.py:1687-1693`) the canvas fallback draws
only a text hint (`graph_view.py:1797-1807`), no boxes, no hit targets.

**Read from source.** `_do_swap` (`graph_view.py:1746-1760`) requires
`len(self._selected) == 2`, which the fallback cannot produce.

**Remediation.** Either draw the boxes on the canvas fallback (and populate
`_boxes`), or remove the canvas click path and disable "Swap selected" when
the embed is down.

### M9. `app.log()` re-reads every token file on every log line (Medium)

**Where.** `app.py:1578` `log()` calls `self._log_secrets()`;
`app.py:1566-1576` `_log_secrets` calls `tokens.read_token(kind)` for all four
`TOKEN_SPECS`; `tokens.py:92` `read_token` calls `seed_from_defaults()` first
(`tokens.py:93`), which loads, and can write, `studio-tokens.json`
(`tokens.py:76-88`).

**Read from source.** Every `log()` call therefore performs ≥4 file reads and
a possible write on the Tk main thread. The Logs tab is the app's default
diagnostic sink; `_tick_gen` is re-armed every 2 s while generating
(`app.py:376`), and the Salad poll every 15 s (`app.py:344`).

**Remediation.** Cache the redaction list on the instance and invalidate it in
`_save_token` (`app.py:812`).

### M14. The CLIP-encoding rule the docs state is not the rule the code implements (Medium)

**Where.** `request_json.wire_clip_encodes` (`request_json.py:280`): when any
Klein-native LoRA is present (`lora_is_klein_clip`, `request_json.py:224`,
tokens `klein` / `flux2` / `flux.2` / `artificeal` / `agedart`), both CLIP
encodes are rewired onto the **last Klein-native `LoraLoader`**
(`request_json.py:320`). The "encode on the CLIPLoader" rule is applied only
for foreign stacks, via `encode_prompts_before_loras`
(`request_json.py:156-178`).

`README.md:49-51` states the opposite for the general case. "Positive and
Negative text that CLIP encodes on the **CLIPLoader** (Qwen) *before* LoRAs
patch the UNET. Rebuild/Convert keep `CLIPTextEncode.clip` on the loader, not
the last `LoraLoader`". The same README later states the correct Klein rule
("Klein-native LoRAs encode CLIP **after** the last `LoraLoader`",
`README.md:86-87`), so the document contradicts itself.

**Corroborated by the stale test.** `test_watercolor_import.py:488-489`
asserts `prompt["74"]["inputs"]["clip"] == ["71", 0]` (the CLIPLoader); the run
produced `["89", 1]` (the last LoRA). The code's actual Klein behaviour.

**Remediation.** Rewrite the README bullet to state the split rule
(Klein-native → last LoRA; IL/Anima/SDXL → CLIPLoader) and update the test.

### M16. `civitai_verify` rewrites shipped app source by default (Medium, design risk)

**Where.** `civitai_verify.apply_known_import_fix` (`civitai_verify.py:1269`)
writes `comfy_import.py` to disk at `civitai_verify.py:1325`
(`path.write_text(updated, encoding="utf-8")`) and then re-binds modules via
`reload_conversion_modules` (`civitai_verify.py:1326`, `:1330`), which
replaces `sys.modules` entries. The CLI default is on:
`p.set_defaults(edit_import=True)` at `civitai_verify.py:1884`, and
`.claude/skills/civitai-verify/SKILL.md` line 24 documents the bare
invocation as the normal run.

**Read from source.** Consequence: the documented one-line verify command can
edit `salad_studio/comfy_import.py` in place whenever a
`missing_node_type` failure appears, which is exactly what a read-only audit
or an unrelated commit must not have happen. It also understands only
`missing_node_type`, and it must patch two lists (M6).

**Remediation.** Require an explicit `--edit-import` (invert the default), or
refuse to write when the working tree is dirty.

### M17. `history_strip.py` has no behavioral test (Medium)

**Where.** `history_strip.py`, `set_paths` (`:82`), `_rebuild` (`:87`),
`_photo_for` (`:111`), `_load_thumb` (`:119`), `_layout_thumbs` (`:134`),
`_scroll_left` (`:148`), `_scroll_right` (`:151`), `_scroll_pixels` (`:157`),
`_on_mousewheel` (`:167`), `_emit_open` (`:192`).

**Read from source.** A package-wide grep finds no test reference to
`set_paths`, `_load_thumb`, `_photo_for`, `_scroll_pixels`, or `_emit_open`.
The only test contact is construction plus palette assertions:
`test_theme.py:110-118` (`HistoryStrip(cls.root, thumb_size=(64, 64))`) and
`test_theme.py:158` (`test_history_strip_canvas_and_chevrons_use_palette`).

**Remediation.** Add a `test_history_strip.py` covering `set_paths` with a
real JPEG, a missing file (placeholder), the scroll region, and the `on_open`
callback.

### M18. `ui_state.py` has no dedicated test module (Medium-low)

**Where.** `ui_state.load_state` (`ui_state.py:14`), `ui_state.save_state`
(`ui_state.py:25`).

**Read from source.** Coverage is indirect only: `test_app_layout.py:394-395`
and `test_app_layout.py:713-731`
(`test_ui_state_roundtrip_restores_dropdowns_and_checks`) drive
`_save_ui_state` / `_restore_ui_state`. The corrupt/absent-state path was
probed manually and behaves (`{SCRATCH}/repro_profiles_ui_state.log`:
`corrupt ui_state -> None`), but no test pins it.

**Remediation.** Add `test_ui_state.py` for corrupt JSON, a non-dict payload,
and the round trip.

### M19. `__main__.py` is untested (Medium-low)

**Where.** `__main__.py:1-4`. The README's primary invocation is
`python -m salad_studio` (`README.md:6-8`), and no test imports
`salad_studio.__main__` or asserts that the `main` entry point resolves.

**Remediation.** One import-level test that `salad_studio.__main__` resolves
`salad_studio.app.main`.

### L1. Modules mutate `sys.path` at import time (Low)

**Where.** `generator.py:10-15`, `request_json.py:13`, `lora_store.py:18-21`,
`comfy_import.py:12-16`, `app.py:15-19` each insert `salad_studio/` and
`` into `sys.path` as an import side effect. It is what lets the
mixed `from salad_studio import …` / `import lora_store` styles coexist
(`generator.py:18-19`, `comfy_import.py:18-19`) and why
`civitai_verify.py:32` can do a bare `import salad_status`.

**Remediation.** Optional: normalise on package-relative imports and drop the
`sys.path` edits; at minimum keep them out of any new module.

### L3. `studio_log.LEVELS` is unused (Low)

**Where.** `studio_log.py:12` defines
`LEVELS = ("debug", "info", "ok", "warn", "error", "http")`; a package-wide
grep finds no other reference (`app.py:1546` iterates `LEVEL_COLORS` instead).

### L5. `profiles.load_all` raises on a non-numeric stored field (Low)

**Where.** `profiles._profile_from_dict` (`profiles.py:103`) calls
`int(data.get("width", 1024))` at `profiles.py:117`, plus `height`, `steps`,
`cfg`, and `seed` at `:118-121`, with no guard, while `_load_doc`
(`profiles.py:74`) *does* guard JSON errors.

**Proven.** `{SCRATCH}/repro_profiles_ui_state.log`:

```
non-numeric width -> ValueError: invalid literal for int() with base 10: 'wide'
```

**Impact.** A hand-edited or partially-written
`~/.config/salad/studio-profiles.json` propagates through
`ensure_builtin_profiles` (`profiles.py:182`) → `_load_profiles_into_ui`
(`app.py:2526`) and aborts `SaladStudio.__init__`: the app will not start.

**Remediation.** Coerce with a default on `(TypeError, ValueError)` per field.

### L9. `tokens.read_token` writes on read (Low)

**Where.** `tokens.read_token` (`tokens.py:92`) calls `seed_from_defaults()`
at `tokens.py:93`; `seed_from_defaults` (`tokens.py:76-88`) writes
`studio-tokens.json` when it copies a slot from `~/.config`. This is the
amplifier behind M9.

### L10. `app.py:428` sets "Down" for an empty gateway and then probes anyway (Low)

**Where.** `app.py:428-431`:

```python
428  if not gw:
429      self._set_salad_word("Down")
430  if self._salad_check_busy:
431      return
```

There is no `return` after the empty-gateway branch, so execution continues
into the threaded probe with `active_gw = ""`. Either the branch is intended
to fall through (the dual replica badges are filled from the profile gateways,
`app.py:412-423`), in which case it is a no-op worth a comment, or the
`return` is missing.

### L11. Latent `IndexError` on an empty status word (Low)

**Where.** `app.py:402` `ready = (word or "").split()[0] == "Ready"` and
`app.py:2655` `if word.split()[0] != "Ready":` both index `[0]` of a possibly
empty list. Today `var_salad_status` is seeded to `"…"` (`app.py:243`) and
`_set_salad_word` is always handed a non-empty word from
`salad_status.short_status` (`salad_status.py:440`), so it is latent.

**Remediation.** `(word or "").split()[:1] == ["Ready"]`.

### L12. `Clean gallery` also deletes the Klein probe rasters (Low)

**Where.** `_history_paths` (`app.py:2578`) appends `ART/salad_probe_klein_*.jpg`
(`app.py:25-27`) after the Studio plates; `_on_clean_gallery`
(`app.py:2600-2624`) unlinks every returned path after a confirm dialog that
only says "Delete N image(s) from disk and clear the gallery?".

**Remediation.** Either exclude the probe glob from the destructive path or
name both sets in the dialog.

### L13. `graph_view.lora_symbolic_name` re-reads the LoRA store per rendered card (Low)

**Where.** `graph_view.lora_symbolic_name` (`graph_view.py:539`) calls
`ls.find_by_loader_name(...)` twice with no `extras_path`, which resolves to
`lora_store.EXTRAS_PATH` (`lora_store.py:24`, `_resolve_extras` at `:80`,
`list_loras` at `:224`, `find_lora` at `:238`), a file read plus catalog
build. It is reached from `node_rows` (`graph_view.py:571`), which
`_joint_prepare` (`graph_view.py:385`) calls via `joint_fields`
(`graph_view.py:326`) and `joint_card_title` (`graph_view.py:311`), several
times per LoRA node per `prompt_to_joint`, and `prompt_to_joint` runs on every
`_redraw`.

### L14. `_redraw` rewrites the HTML page even when the in-place JS path is taken (Low)

**Where.** `graph_view.py:1770-1781`: `write_graph_page(prompt)` runs at
`graph_view.py:1774` before the `eval_js` branch returns at `:1781`; in that
branch the written `graph_html/_current.html` is unused.

### L15. `test_app_layout` pins implementation strings, including the dead Graphviz stack (Low)

**Where.** `test_app_layout.py:40`
(`test_tab_order_config_loras_prompt_editor_prompt`) asserts source
substrings: `:62` `prompt_to_dot`, `:63` `rankdir=LR`, `:64`
`graphviz_layout`, `:65` `find_dot`, `:67` `SLOT_COLOR`, `:71`
`_sync_editor`.

**Impact.** These cannot fail on a behavior regression, and they actively pin
M7's dead code in place. The method name also still reads
`…_prompt_editor_prompt` after the Prompt tab was removed.

**Remediation.** Keep the tab-order assertions (they are real UI contract);
drop the string-presence assertions in favour of the behavioural tests that
already exist (`test_graph_view.LivePaneExport`, `test_theme`).

---

## 3. Doc-vs-source verdicts

### 3.1 `salad_studio/README.md`

| # | Claim in README | Verdict | Anchor |
|---|---|---|---|
| R1 | `python -m salad_studio` from the repo root | **Holds** | `__main__.py:1-4`, `app.py:2717-2719` |
| R2 | Tab list includes **Prompt** | **DIVERGED**. 8 tabs, no Prompt; prompts live on Prompt Editor | `app.py:28-37` vs `README.md:18`; `app.py:946-971` |
| R3 | Config: profiles `klein`/`klein5090`, dual replica badges, Flux2 vs Simple | **Holds** | `profiles.py:182`, `app.py:253-273`, `app.py:301-312` |
| R4 | Generate disabled until the active gateway is Ready | **Holds** | `app.py:401-410` |
| R5 | Policy Apply PATCHes Salad, not a Docker rebuild | **Holds** | `salad_status.py:267` |
| R6 | Tokens in `studio-tokens.json` (gitignored) | **Holds**. `.gitignore:111`, file untracked | `git check-ignore -v` |
| R7 | Empty token slots copy from `~/.config` | **Holds** | `tokens.py:76-88` |
| R8 | Logs redact secrets | **Holds** | `studio_log.py:39`, `app.py:1579` |
| R9 | JointJS in a WebView2 pane; cache under `%LOCALAPPDATA%\SaladStudio\WebView2` | **Holds** | `graph_view.py:1669`, `graph_view.py:521` |
| R10 | "Open in browser" fallback; "Open as Comfy" = LiteGraph | **Holds** (but see M8 for the canvas-selection fallback) | `graph_view.py:1694`, `graph_view.py:1700` |
| R11 | Selecting LoRAs on Config rebuilds the LoraLoader chain | **Holds** | `app.py:1703-1722` |
| R12 | Rebuild from JSON restores prompt, size, graph, selected LoRAs | **Holds** | `app.py:2076` |
| R13 | Validate = the same `parse_request_json` gate plus Civitai-token check | **Holds** | `app.py:2437-2469` |
| R14 | Prompt text "CLIP encodes on the CLIPLoader (Qwen) before LoRAs" | **DIVERGED**. Klein-native LoRAs encode after the last LoRA | `README.md:49-51` vs `request_json.py:280`. See M14 |
| R15 | "Rebuild/Convert keep `CLIPTextEncode.clip` on the loader" | **DIVERGED** for Klein-native stacks | same anchors; failing `test_watercolor_import.py:488` |
| R16 | Convert routes on graph presence, then tooling | **Holds** | `comfy_import.py:395`, `comfy_import.py:2237` |
| R17 | UUID subgraph flatten assigns unique link ids, skips muted (mode 4) | **Holds** | `comfy_import.py:24`, `comfy_import.py:1127`, `comfy_import.py:1775` |
| R18 | Nodes off the SaveImage path drop as orphans | **Holds** | `comfy_import.py:2313` |
| R19 | Local LoRA filenames searched on Civitai; a miss is omitted so Convert still succeeds | **Holds** | `comfy_import.py:660`, `comfy_import.py:468` |
| R20 | Convert rewrites `ReferenceLatent`, `ConditioningZeroOut`, small-decoder VAE, `Color Correct GPU (mtb)` | **Holds**, with the nuance that the rewrite happens on the POST copy | `comfy_import.py:2669-2747`, `comfy_import.py:153-155` |
| R21 | `flux-2-klein-9b-fp8mixed` → replica `flux-2-klein-9b-fp8` | **Holds** | `comfy_import.py:156`, `comfy_import.py:186` |
| R22 | KSampler `control_after_generate` is not packed as steps | **Holds** | `comfy_import.py:75`, `comfy_import.py:2629` |
| R23 | No `LoraLoader` but Resources list a LoRA → Convert inserts it | **Holds** | `comfy_import.py:721` |
| R24 | Local `LoadImage` names stay in the editor; Generate omits them | **Holds** | `comfy_import.py:2472`, `comfy_import.py:2714-2721` |
| R25 | Fetch from Civitai loads Copy All plus Resources-used | **Holds** | `comfy_import.py:2008`, `app.py:1228` |
| R26 | Draw Things posts build a Klein `/prompt`; `DPM++ SDE` → euler + Flux2Scheduler | **Holds**. Live-verified | `comfy_import.py:2169`, `comfy_import.py:411`; `civitai-verify-live/journal.jsonl` |
| R27 | Workflow JSON stashed in memory so a long graph does not freeze Tk | **Holds** | `app.py:1145` |
| R28 | "Distilled Klein graphs … are **blocked** on Convert; the pane lists why" | **DIVERGED**. Noted, never blocked | `README.md:104`; `comfy_import.py:2544` returns `blocking=[]`; `app.py:1198`; live journal line 6: `"blocking": [], "runnable": true` |
| R29 | Generate writes a 48×48 thumbnail; double-click restores JSON + prompt | **Holds for the JSON branch**; the text-only branch throws (H2) | `prompt_history.py:270`, `app.py:2704-2709`, `app.py:1463-1485` |

### 3.2 `docs/workflow/16-salad-studio-prompt-graph.md`

| # | Claim | Verdict | Anchor |
|---|---|---|---|
| W1 | Live graph is JointJS `@joint/core` 4.2.5 | **Holds** | `graph_html/VENDOR.txt:3-6` |
| W2 | No Graphviz `dot` on the live path | **Holds** | `graph_view.py:510`, `graph_view.py:1621-1807` |
| W3 | Unknown classes are not forced into the sampler column | **Holds** | `graph_view.py:292-293`, `graph_view.py:377-382`; note `_SAMPLER_COLUMNS` is now read only by `test_graph_view.py:451` |
| W4 | Manhattan orthogonal wires with rounded corners that route around cards | **Holds** (in the vendored page) | `graph_html/viewer.html`, `VENDOR.txt:3-6` |
| W5 | Pane = `GraphPane` → tkwry `WebView` (`app=_current.html`, user-data dir) | **Holds** | `graph_view.py:1669-1687`, `graph_view.py:521-529` |
| W6 | Fallback: Open in browser; Open as Comfy = LiteGraph | **Holds**, except the canvas *selection* fallback (M8) | `graph_view.py:1687-1704`, `graph_view.py:1715-1728` |
| W7 | Tests live in `test_graph_view.py` class `JointGraphExport` | **Holds** | `test_graph_view.py:175` |
| W8 | Graphviz remains as unused helpers (`prompt_to_dot`, `graphviz_layout`) | **Holds**. And `resolve_layout`'s docstring contradicts it | `graph_view.py:5` vs `graph_view.py:1260`. M7 |
| W9 | "If `dot` is missing, the pane shows an install message. It does not fall back to `layout_xy`." | **DIVERGED**. No such message exists; the pane has no `dot` path at all | `graph_view.py:1436-1440` raises; no caller in `GraphPane` or `app.py` |
| W10 | `grandalf_resolve` remains as an unused helper | **Holds** | `graph_view.py:1120`; only `test_graph_view.py:89` calls it |
| W11 | LiteGraph.js is vendored; its splines do not pathfind around nodes | **Holds** | `VENDOR.txt:9-12` |
| W12 | Graphviz "ports" are record/HTML fields or compass points; the visual match is approximate | **Moot**. A statement about the abandoned path; accurate as written | `graph_view.py:1315-1365` |

### 3.3 The three further caveats the audit brief named

| Caveat | Verdict | Anchor |
|---|---|---|
| Port / socket-row mismatch (JointJS ports not aligned with card rows) | **Addressed in the working tree**. Per-port `y` is emitted from `joint_row_center` and asserted | `graph_view.py:296`, `graph_view.py:397`, `graph_view.py:408`; `test_graph_view.py:419-423` |
| Lost card drag / zoom | **Still present, by design**. A `position` message is accepted and discarded, so drags are never written back to the prompt JSON; pan/zoom live only inside the page | `graph_view.py:1582-1604`; `graph_html/viewer.html:293-309` |
| Editor focus vs WebView2 | **Still present**. Handled explicitly by `_lift_editor_over_webview` / `_release_graph_keyboard` / the `_graph_stale` deferral | `app.py:2268-2353`, `graph_view.py:1770-1781` |

---

## 4. Observed test state

**Command (as the plan's verification step 2 prescribes).** From
`salad_studio`, with `PYTHONPATH` =
`<repo>/src/tools;<repo>/salad_studio`:

```
python -m unittest discover -p "test_*.py" -v
```

**Result** (`{SCRATCH}/salad_studio_suite.log`, Python 3.14.7, exit 1):

```
Ran 297 tests in 106.167s

FAILED (failures=8, errors=3)
```

The suite is **red**. This matches the baseline the plan recorded (297 tests,
8 failures + 3 errors), no drift.

**The prescribed subset is green.** `.claude/skills/civitai-verify/SKILL.md`
step 7 prescribes, from the repo root with `PYTHONPATH=src/tools`:

```
python -m unittest salad_studio.test_comfy_import salad_studio.test_salad_status salad_studio.test_generator
```

`{SCRATCH}/salad_studio_skill_prescribed_tests.log`: `Ran 99 tests in 1.867s`.
`OK`. So the modules the conversion workflow leans on pass; the failures are
concentrated in the LoRA store, the prompt-history live tests, and two stale
assertions.

### Every non-passing test, named and traced

| Test | Kind | Root cause | Class |
|---|---|---|---|
| `test_lora_store.AddFromSources.test_add_local_path` | FAIL | **H1**. `add_lora` never persisted | Real code defect |
| `test_lora_store.AddFromSources.test_add_bare_safetensors_filename` | FAIL | **H1** | Real code defect |
| `test_lora_store.AddFromSources.test_remove_only_extras` | FAIL | **H1** (nothing to remove) | Real code defect |
| `test_lora_store.AddFromSources.test_never_writes_real_extras` | FAIL | **H1** | Real code defect |
| `test_lora_store.AddFromSources.test_add_civitai_url` | ERROR | **H1**. Reads a file that was never written | Real code defect |
| `test_lora_store.AddFromSources.test_add_and_edit_family_name_filename_strength` | ERROR | **H1**. `edit_lora` raises `unknown LoRA civitai:111@222` | Real code defect |
| `test_prompt_history.LivePromptHistory.test_reuse_fills_prompt_tab` | ERROR | **H2**. `app.py:1483` `self._prompt` | Real code defect |
| `test_prompt_history.LivePromptHistory.test_reuse_restores_request_json` | FAIL | Test bug. Asserts the prompt text in the *profile* column | Test harness defect |
| `test_request_json.BuildRequest.test_klein_selected_loras_appear_in_json` | FAIL | Test bug. Not hermetic; reads the developer's real extras file | Test harness defect |
| `test_app_layout.LiveFieldSync.test_import_issues_panel_flags_distilled_klein` | FAIL | Stale expectation. The panel now *does* name `ReferenceLatent` | Stale test |
| `test_watercolor_import.WatercolorConvert.test_whole_graph` | FAIL | Stale expectation. Klein-native LoRAs encode on the last LoRA | Stale test (see M14) |

Detail on the three non-code failures:

- **`test_reuse_restores_request_json`** (`test_prompt_history.py:257`)
  asserts `assertIn("history oil stallion", vals[1])`. `vals` is the
  `Treeview` `values` tuple, whose order is fixed by `app.py:1379`
  (`cols = ("when", "profile", "preview", "stats")`) and `app.py:1441-1451`
  (insert order `when, profile, preview, stats`).
  `{SCRATCH}/repro_tree_columns.log` proves the mapping directly:
  `vals[1]` = profile = `''`, `vals[2]` = `'history oil stallion'`.
  The assertion should target `vals[2]`.
- **`test_klein_selected_loras_appear_in_json`**
  (`test_request_json.py:89`) calls `rj.build_request(...)` with no
  `extras_path`, so `request_json.py:568` →
  `ls.specs_for_ids(ids, None, graph)` → `lora_store.find_lora(id, None)`
  (`lora_store.py:238`) → `list_loras(None)` (`:224`) → `_resolve_extras(None)`
  (`:80`) = the real `~/.config/salad/studio-loras.json` (`lora_store.py:24`).
  On this machine that file holds
  `civitai:2334190@2625692 -> …/2625692?fileId=2513322` and
  `civitai:545264@2763568 -> …/2763568?fileId=2649742`, and the failure message
  quotes exactly those two URLs against a test expecting the bare catalog
  URLs. The test is non-hermetic; the shipped `comfy_lora_name`
  (`lora_store.py:836`) is behaving as designed.
- **`test_import_issues_panel_flags_distilled_klein`**
  (`test_app_layout.py:784-786`) asserts `assertNotIn("ReferenceLatent", shown)`
  and the same for `ConditioningZeroOut`. `comfy_import.replica_issues`
  (`comfy_import.py:2450-2454`) now emits
  `"Warning: #<id> <cls> is not on Salad Comfy 0.35 (kept in the editor;
  Generate omits it from the POST)."` for both types, and
  `app._set_import_issues` renders notes under `Warnings:` (`app.py:1185`).
  The panel is behaving as the README describes (R20); the assertion is the
  stale half.

**Tk tests did run.** All `Live*` classes (which construct a real
`SaladStudio`) executed; the two failures above are behavioral, not
"Tk unavailable" skips.

---

## 5. Live end-to-end evidence (independent of the suite)

Because the app's own suite is partly red, the Import → Convert → Generate
path was exercised end to end through `.claude/skills/civitai-verify/verify.py`
(which drives the shipped `comfy_import.import_to_request` and
`generator.generate_from_payload`), against
`https://civitai.com/images/135440425`, the **Draw Things** example the
README documents (`README.md:80-89`).

**Read-only run** (`--no-post --no-edit-import`), journal
`{SCRATCH}/civitai-verify-135440425/journal.jsonl`:

```
container-list  ok=true   klein=Ready  klein5090=Stopped
fetch           ok=true   image_id=135440425
convert         ok=true   node_count=14  has_prompt=true
inspect         ok=true   runnable=true  blocking=[]  notes=[]  replica_issues=[]
audit-clip      ok=true   positive_match=true  negative_match=true  positive_len=408
audit-loras     ok=true   1 LoRA  civitai:2745770@3088444  family=Flux.2 Klein  in_extras=true
```

**Live run** (same URL, `--no-edit-import --max-attempts 1`), journal
`{SCRATCH}/civitai-verify-live/journal.jsonl`:

```
post            ok=true   image=…/civitai-verify-live/out/studio_1790033855893.jpg  (36 s)
compare         ok=false  skipped=pending_local_describe  (remote vision HTTP 403)
backtrack       reason=remote vision failed; local JPEGs saved
```

Following the skill's documented fallback, both JPEGs were read locally and
described, then `--record-compare` was run:

```
{"similar": true, "significantly_different": false}
```

The site plate and the generated JPEG agree on subject, pose, setting,
clothing, palette, and wordmark; the visible differences are the raised
painting arm and a lighter, letter-spaced wordmark. **This is the strongest
single piece of evidence in the audit: the shipped Import → Convert →
Generate path reproduces a documented Civitai image on the real replica.**

Note for anyone repeating this: the run performed no source edit
(`--no-edit-import`), and `git status --porcelain salad_studio`
afterwards showed exactly the dirty set that existed before the audit began.

---

## 6. Unverified suspicions (explicitly not defects)

1. **The `?fileId=`-bearing extras rows.** The real
   `~/.config/salad/studio-loras.json` overrides the catalog's `download` URLs
   for the two default Klein LoRAs with `?fileId=` variants. I verified the
   override exists and that it is what the test reads; I did **not** verify
   whether Salad accepts the `?fileId=` form on `/prompt` `lora_name`. The live
   POST above used a Draw Things graph whose LoRA resolved to the plain URL,
   so it does not settle this.
2. **`_api_request` vs the dead duplicate.** `salad_status._api_get`'s
   unreachable body (M3) differs from `_api_request` in that it does not send
   `content-type` for POSTs. Since it is unreachable, whether the two were ever
   behaviourally different is unverified.
3. **`civitai_verify`'s module reload.** `reload_conversion_modules`
   (`civitai_verify.py:1330`) rebinds `sys.modules` entries and
   `salad_studio.comfy_import`. I read the code and did not exercise the reload
   path (it needs a `missing_node_type` failure); a stale module object leaking
   into `app.py`'s already-imported `comfy_import` reference is plausible but
   unproven.
4. **`history_strip` thumbnail memory.** `_photos` is cleared and rebuilt on
   every `set_paths` (`history_strip.py:82-109`) with a comment about Tk
   dropping pixels; whether a long gallery leaks is unmeasured (no perf work in
   scope).
5. **The uncommitted `app.py` growth (+502 lines).** The diff adds the
   geometry-hold, sash placement, prompt-box layout, and WebView2 focus
   handling. I read all of it and found H2 inside it, but I did not review it
   line by line against its own intent. The tree is mid-change by design and
   this audit treats it as the current state, not a proposal.

---

## 7. Remediation queue (suggested order)

1. **H1**. Make `add_lora` persist on the `ensure_civitai_version_name`
   branch. One-line fix; clears 7 of the 11 red tests.
2. **H2**. `app.py:1483` → `self.nb.select(self._editor)`. One-line fix.
3. **M14 / R14 / R15**. Fix the README CLIP bullet and the
   `test_watercolor_import.py:488-489` expectation together.
4. **Test-hermeticity**. `test_request_json.py:89` must pass an isolated
   `extras_path`; `test_prompt_history.py:257` must assert `vals[2]`.
5. **Stale assertion**. `test_app_layout.py:784-786` should assert the
   warning *is* present, or assert on the blocking list only.
6. **M3, M7, M8, M19**. Delete dead code and its pinning tests; add the
   missing entry-point and `history_strip` tests.
7. **M6**. Collapse the two replica-missing-type lists into one.
8. **M9, L9, L13, L14**. Hoist the token/redaction and LoRA-store reads out of
   the render and log paths.
9. **L5**. Guard profile field coercion so a corrupt profiles file cannot stop
   the app from starting.
10. **M16**. Invert the `--edit-import` default in `civitai_verify`.

## 8. Out of scope (as the plan set it)

Fixing any of the above; `eldermark` / `lifesim_core`; the Salad cloud API and
the `salad_klein/` Docker image; the vendored JS in `graph_html/`
beyond version/provenance; interactive GUI verification of the Tk panes or the
WebView2 diagram; performance/GPU-cost benchmarking; third-party credential
security beyond confirming `studio-tokens.json` is gitignored
(`.gitignore:111`, untracked).

---

## 9. Status. What was fixed (2026-09-21)

A follow-up session worked §7. The findings above stand as written (they
describe the pre-fix tree); this section records the resolution of each.
**Suite after: `Ran 344 tests … OK`** (from 297 tests / 8 failures + 3
errors), with the prescribed `civitai-verify` subset still `OK`.

### Fixed

| Finding | Resolution |
|---|---|
| **H1** | `add_lora` (`lora_store.py`) now assigns the `ensure_civitai_version_name` result and always exits through `write_extra`, so every ref kind persists. Regression test `test_lora_store.AddFromSources.test_add_persists_row_for_every_source_kind` (local path, bare filename, HF URL, direct URL) fails pre-fix; `test_app_layout.LiveFieldSync.test_add_lora_button_persists_the_row_and_lists_it` drives the shipped Add button end to end and re-reads the store. |
| **H2** | `_reuse_prompt_history` selects the Prompt Editor instead of the removed `self._prompt`; `test_prompt_history.LivePromptHistory.test_reuse_fills_prompt_tab` now asserts no exception, the prompt text in the box, and the visible tab. |
| **M3** | The unreachable duplicate `_api_get` body is deleted; a test pins the delegation to `_api_request("GET", …)`. |
| **M6** | One `SALAD_MISSING_TYPES` (the four inline-only members moved into it); the omit step in `prompt_for_salad_replica` derives from it, and the three rewire cases moved to a separate `_rewrite_replica_missing_nodes` pass. `civitai_verify.add_salad_missing_type` now patches the single list. Per-type lock test + a "the omit step reads the shipped set" test (the latter fails pre-fix). |
| **M7** | The Graphviz/grandalf stack is deleted: `prompt_to_dot`, `run_dot`, `graphviz_layout`, `find_dot`, `parse_dot_plain`, `grandalf_resolve`, `resolve_layout`, `_xml_esc`, `_html_wrap`, `_plain_tokens`, `_DOT_DPI`, `_DOT_CANDIDATES`, `_SAMPLER_COLUMNS`, plus `port_positions` and `_nudge_off_boxes` (reachable only from the deleted roots) and the `shutil`/`subprocess` imports. The module docstring and its tests were updated in the same change. |
| **M8** | The unreachable canvas click/selection path and `_boxes` are gone; `_on_web_fail` disables "Swap selected" with a hint pointing at **Open in browser**, and `_do_swap` refuses without the embed instead of silently doing nothing. |
| **M9** | The redaction list is instance-cached (invalidated by `_save_token`). A call-count test patches the shipped `tokens.read_token` and asserts zero reads with a warm cache. |
| **M14** | README now states the split rule (Klein-native → last such `LoraLoader`; foreign stacks → base CLIPLoader), and `test_watercolor_import` asserts both halves, with the §5 live run named as the basis. |
| **M16** | `--edit-import` is an opt-in flag on the CLI *and* on `run_verify`; the bare invocation journals `skipped: "edit_import is off; conversion code was not modified"` and halts. `SKILL.md` was updated in the same change. A test drives a fabricated `missing_node_type` failure against an isolated copy of the sources and asserts the copy is byte-identical without the opt-in. |
| **M17** | New `test_history_strip.py`. 12 tests driving `set_paths`, placeholder/letterbox rendering, the scroll region and chevrons, the wheel/button handlers, and the `on_open` callback. A mutation check (6 injected regressions, all caught) shows the tests have teeth. |
| **M18** | New `test_ui_state.py`. 10 tests: missing file, directory, corrupt JSON, empty file, five non-object payloads, round trip, parent-dir creation, overwrite, and the default-path branch. |
| **M19** | New `test_entrypoint.py`. `salad_studio.__main__.main is salad_studio.app.main`. |
| **L3** | The unused `studio_log.LEVELS` constant is deleted. |
| **L5** | `profiles._profile_from_dict` routes `width`/`height`/`steps`/`cfg`/`seed` through a `_coerce` guard; a corrupt profiles file no longer stops the app from starting. |
| **L10** | The empty-gateway branch keeps its deliberate fall-through into the probe, now stated in code rather than left looking like a missing `return`. |
| **L11** | Both status-word sites compare `(word or "").split()[:1] == ["Ready"]`, so an empty word cannot raise. |
| **L13** | `lora_lookup` builds the `{key: label}` map once per `prompt_to_joint` and is threaded through the card builders (and the "Open as Comfy" path); call-count tests assert ≤1 store read per graph and 0 when a lookup is supplied. |
| **L14** | `_redraw` writes the HTML page only on the branch that loads it; a test asserts the in-place refresh path writes nothing. |
| **L15** | The source-string and AST-pinning assertions in `test_app_layout.py` are replaced with behaviour tests on the live window (tab labels, LoRA-tab controls driven with the store patched, checkbox state vs `compatible_with_graph`, editor scrollbars). |
| **R2 / R28 / W3 / W8 / W9** | README's tab list drops the removed **Prompt** tab (its content folded into the Prompt Editor bullet); the Import wording says the issues are *noted*, not blocking; `workflow/16` records that the Graphviz/grandalf helpers were **removed** and that the pane has no `dot` dependency at all. |

### Also changed (not an audit finding)

- **Hidden-window mode** (requested by the user mid-session, to stop the suite
  flashing windows on screen): `SaladStudio(show=False)` and the
  `SALAD_STUDIO_HIDDEN` environment variable build the full window without
  mapping it. All test constructions pass `show=False`; the shipped default
  still shows a window. `test_theme.WindowVisibility` pins both halves.
  `test_theme._isolate_studio_io` now also isolates the token store, prompt
  history and saved UI state, so the live-window tests no longer read the
  developer's real config.

### Follow-up (2026-09-22). Prompt Assist waits for the whole reply

Reported live: **Help (DeepSeek)** / **Help (local)** filled the boxes with a few
chunks of the reply as if they were the whole answer. Four causes, all the same
shape, a piece of the body taken for the reply: the parser took the first
balanced `{...}` (both backends reason, and a trace quotes this module's own
schema plus a first draft, so a fragment won); the schema's `"..."` placeholders
and a loose `"prompt"` alias counted as answers; `finish_reason: "length"` was
never inspected, so a reply cut at the token limit was parsed as complete; and a
streamed body, or one short of its own `Content-Length`, was read as final.

`ai_helper.py` now reads the whole body before answering, reports
`finish_reason`/`truncated`, continues a `length`-cut reply
(`CONTINUE_ATTEMPTS = 2`) and stitches it **before** parsing, fails naming
`max_tokens` when the budget still runs out (rather than filling the boxes with
the front of a reply), scores every complete `{...}` and takes the best, and
recovers an object a model restarts from the top behind a cut-off head
(Ministral does). `app.py` keeps what the artist typed in a box when the reply
arrives missing that prompt. Tests: `test_ai_helper.py` (parser, continuation,
streaming, short body) and `test_app_layout.py`. Repro: with `max_tokens=1000`
the local model returns `finish_reason: "length"` mid-JSON. The pre-fix code
parsed that head as the answer.

**Suite after: `Ran 496 tests … OK`** (125 s), `salad_klein` `Ran 11 tests … OK`.
Live through the shipped entry point at the shipped budget: `finish_reason=stop`,
7708 characters read whole, `continued=0`, positive 6964 ch / negative 573 ch,
the issue named in the negative.

### Not addressed (and why)

- **L1** (`sys.path` mutation at import time), an explicit plan non-goal.
- **L12** (`Clean gallery` also deletes the `art/salad_probe_klein_*.jpg`
  probe rasters), outside the plan's enumerated criteria; behaviour
  unchanged, so the finding still stands.
- **§6 suspicions**, all still open, as scoped.
- **Residual dead-ish code** noted while resolving M7: the in-house Tk canvas
  router family (`layout_xy`, `node_boxes`, `route_wire`,
  `separate_parallel_wires`, `chamfer_polyline`, …) and the unreferenced
  `GraphPane._draw_grid` / `_wrap` / `_rounded_rect` helpers remain. They are
  not the Graphviz/grandalf stack M7 named, and `layout_xy` is still live via
  the "Open as Comfy" path, so they were left in place rather than swept
  opportunistically.
- **Test-environment noise**: with no real `mainloop`, the status-probe worker
  thread's `self.after(0, done)` and the `_lift_editor_over_webview` /
  `_reapply_opened_size` `after` scripts print Tcl "invalid command name" /
  `RuntimeError: main thread is not in main loop` lines to stderr. This is
  pre-existing (it is in the baseline log too) and does not affect any test
  result; a real `mainloop` run is clean (verified by launching
  `python -m salad_studio` twice as a subprocess with no traceback on stderr).
