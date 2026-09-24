# 58 — Salad Studio audit, 2026-09-22/23 (incremental)

> **Scope:** `salad_studio/` — the Windows Tk helper, *not* `eldermark`
> / `lifesim_core` — in its working-tree state on 2026-09-22/23.
> **Kind:** audit plus the fixes it found. Unlike
> [`57`](57-salad-studio-audit-2026-09.md), this pass **edited** the app: seven
> defects it records were fixed in the same session, and each carries the
> regression test that now pins it.
> **Companion docs:** [`21`](../workflow/21-klein-image-handoff.md) (the image
> handoff), [`15`](../workflow/15-salad-flux2-klein-group.md),
> [`16`](../workflow/16-salad-studio-prompt-graph.md),
> [`../../salad_studio/README.md`](../../salad_studio/README.md).

## 0. How this audit was run (and what is proven vs inferred)

Three evidence classes, kept distinct:

- **executed** — the code path was run (the suite, a repro script driving the
  shipped function, or a live POST to a Salad replica) and the output is quoted.
- **read-from-source** — a static property of the code. No run can reach it, so
  no run is needed.
- **suspicion** — plausible, not demonstrated.

**This is an incremental pass.** [`57`](57-salad-studio-audit-2026-09.md) audited
the tree on 2026-09-21 and its §9 records every finding it closed. §6 below
re-confirms that closure against the *current* source rather than trusting the
record, and names what has changed since. Three modules are new to the coverage
table (`ai_helper`, `prompt_catalog`, `ref_check`); the tree has grown from 18
non-test modules to 21.

Raw evidence, captured in the audit scratch dir:

| Evidence | What it shows |
|---|---|
| `salad_studio_suite_final.log` | Full `unittest` discover: **562 tests, OK** |
| `catalog_check.log` | `test_klein_prompt_catalog`: 15 tests, OK, 1 catalogued entry |
| `catalog_mutation.log` | The catalog check fails on two mutations, green when restored |
| `recipe_test_mutation.log` | The recipe tests fail on two recipe mutations, green when restored |
| `audit_scan.log` | The mechanical scan: per-module sizes, `sys.path` mutation, `except: pass`, untested public names |
| `external_verify*.log` | The external re-fetches behind doc 21 §8 |

---

## 1. Verdict per app module

All **21** non-test modules are covered. "Worst" is the highest-severity finding
recorded for that module in this report.

| Module | Lines | Verdict | Worst finding |
|---|---|---|---|
| `__init__.py` | 2 | Clean — a docstring | — |
| `__main__.py` | 5 | Clean; entry point pinned by `test_entrypoint.py` | — |
| `ai_helper.py` | 1129 | Sound; the largest untested-by-name surface | L4 |
| `app.py` | 3425 | **Needs work** — routing guard never fired; stale status after an error | **N1** |
| `civitai_verify.py` | 2040 | Sound; 18 public names no test references | L4 |
| `comfy_import.py` | 3036 | **Needs work** — Import destroyed a Civitai URL in `lora_name` | **N2** |
| `generator.py` | 425 | **Needs work** — the LoRA probe called live LoRAs dead | **N4** |
| `graph_view.py` | 1523 | Sound; the Graphviz stack stays deleted (M7) | L1 |
| `history_strip.py` | 195 | Clean; covered since M17 | — |
| `json_highlight.py` | 114 | Clean | — |
| `lora_store.py` | 1772 | Sound; H1 stays fixed | L1 |
| `profiles.py` | 385 | Sound; routing helpers were exercised only indirectly | L5 |
| `prompt_catalog.py` | 191 | Clean (new since 57); dedicated test module | — |
| `prompt_history.py` | 333 | Sound | L4 |
| `ref_check.py` | 344 | Sound (new since 57); dedicated test module | L4 |
| `request_json.py` | 921 | **Needs work** — token coverage skipped `LoraLoaderModelOnly` | **N3** |
| `salad_status.py` | 664 | **Needs work** — a dead origin reported as "Starting" | **N5** |
| `studio_log.py` | 153 | Sound; the POST summary missed a LoRA node class | N3 |
| `theme.py` | 444 | Clean | L4 |
| `tokens.py` | 273 | Sound; `read_token` still writes on read | L2 |
| `ui_state.py` | 29 | Clean; covered since M18 | — |

Test modules present: **23**. `test_prompt_catalog.py` (the runtime store) and
`test_klein_prompt_catalog.py` (the in-repo Klein artifact) are different
subjects and must not be merged — see N12.

---

## 2. Findings

### N1 — the Generate routing guard could never fire (High, executed, FIXED)

`app._on_generate` chose a container group by comparing the graph's unet family
to **the form's** unet:

```python
want = profiles.unet_family(payload_unets(payload)[0])
if want and want != profiles.serving_family(p):   # p.unet == the form's unet
```

`p` comes from `_profile_from_form()`, and `_rebuild_from_json()`
(`app.py`, the "Rebuild from JSON" action) **overwrites `var_unet` from the
graph**. So the two sides always agreed and the guard short-circuited.
Reproduced on the real profiles file and a real SNOFS graph:

```
graph loads   : snofsSexNudesAndOther_distilledV12KleinFp8.safetensors  (snofs)
form gateway  : https://apple-gadogado-…  (the klein group)
form unet     : snofsSexNudesAndOther_distilledV12KleinFp8.safetensors  (snofs)
old guard     : want='snofs' vs serving_family(form)='snofs' -> routes? False
route_payload : klein5090 / beet-ginger   (correct, and never consulted)
```

A SNOFS graph therefore POSTed to the klein group, where two unet families
cannot both be resident.

**Fixed.** The guard now asks which group the form's **gateway** belongs to
(`profiles.profile_for_gateway` + `profiles.same_gateway`) and compares the
graph's family to *that*. A hand-typed gateway that is not a saved profile is
left alone. Pinned by
`test_app_layout.NewPagesAndPlacement.test_generate_routes_a_snofs_graph_off_the_klein_group`,
`…test_generate_keeps_a_klein_graph_on_the_klein_group`,
`…test_generate_leaves_an_unknown_gateway_alone` — all three drive the real
`_on_generate` with an inline thread and assert the gateway the render was
POSTed to.

### N2 — Import reduced a Civitai URL in `lora_name` to its trailing id (High, executed, FIXED)

`comfy_import._widget_inputs` ran every weight widget through `salad_filename`,
which keeps only the text after the last `/`:

| incoming `lora_name` | before | after |
|---|---|---|
| `klein_slider_detail.safetensors` | resolves to a Civitai URL ✓ | unchanged ✓ |
| `…/download/models/2625692` | **`2625692`** — not a URL; no token attached, nothing to load | URL preserved ✓ |
| `…/2625692?token=…` | **`2625692?token=…`** — URL destroyed, token kept | URL + token preserved ✓ |

Basenaming is right for `unet_name` / `clip_name` / `vae_name` / `ckpt_name`
(those widgets hold filenames). For `lora_name` a Civitai URL **is** the Studio
convention — `resolve_local_lora_nodes` explicitly skips names starting with
`http` for that reason — so the pass contradicted its own neighbour.

**Fixed** at `comfy_import.py` `_widget_inputs`: an http(s) `lora_name` is left
alone. Pinned by
`test_comfy_import.ComfySubgraphUuid.test_lora_widget_keeps_a_civitai_url_but_basenames_a_local_path`.

### N3 — every Civitai-token path skipped `LoraLoaderModelOnly` (High, executed, FIXED)

Five call sites each did their own `class_type == "LoraLoader"` filter:
`request_json.payload_has_civitai_download` (does this need a token?),
`request_json.civitai_lora_urls` (the pre-flight probe),
`request_json.authorize_civitai_urls` (the attach step),
`studio_log.summarize_payload` (the POST log line), and
`comfy_import.resolve_local_lora_nodes` (local filename → URL).

`LoraLoaderModelOnly` carries `lora_name` too. A gated Civitai file in that node
therefore reached the replica **unauthenticated** — no `?token=`, no probe, no
log entry — and the LoRA never loaded. `ref_check.py` already knew the node type,
which is how the inconsistency survived.

**Fixed** by keying on the *input* rather than the node class:
`request_json.lora_name_inputs(prompt)` returns every `(node, lora_name)` and
backs all five sites. Pinned by
`test_request_json.BuildRequest.test_a_model_only_lora_node_is_authenticated_too`
and `…test_a_url_that_already_has_a_file_id_keeps_it`.

### N4 — the LoRA pre-flight called live LoRAs "unconfirmed" (Medium, executed, FIXED)

`generator.check_lora_urls` accepted only `code == 200`. Cloudflare refuses the
probe's `HEAD` with 403, so it falls back to a ranged `GET` — and a ranged GET
answers **206 Partial Content** when the CDN honours `Range`. Civitai's does.
Every live LoRA was therefore warned about and reported unconfirmed:

```
https://civitai.com/api/download/models/2960556?token=<set>
    HEAD -> HTTP 403
    GET  -> 206 Partial Content   range=bytes 0-0/1090563760
    _probe_url says: (206, 'GET')
```

**Fixed** with `_LORA_OK_CODES = (200, 206)`. Live re-check on the same URL:
`[ok] LoRA civitai:2960556 OK`. Pinned by
`test_generator.CheckLoraUrls.test_a_ranged_get_206_counts_as_resolved`, which
also asserts no "unconfirmed" line is logged.

### N5 — a dead origin was reported as "Starting" (Medium, executed, FIXED)

With both groups refusing connections (Cloudflare **521** on `/health` and
`/ready`), Salad's API still said the group was `running` and the instance
`ready`. `short_status` mapped *any* non-200 `/ready` on such an instance to
`"Starting"`, and `generate_block_reason` then said:

```
Replica is up but Comfy is not ready (Starting). Hugging Face prefetch may still be running.
```

The replica was not up, and the badge hid the reason. The group-status branch
below it already classified the same codes as `Down`.

**Fixed** by factoring the Cloudflare origin-down codes (`0, 520–524`) into
`_ORIGIN_DOWN_CODES`, using them in both branches, and appending the probe's
explanation to `replica_detail` so the badge says *why*. Live, same moment:

```
ready_code/ok : 521 / False
-> word       : 'Down'
-> block      : 'Replica is Down. flux2-klein-5090 · v9 · GET …/ready — HTTP 521 — Cloudflare 521: origin (Salad Comfy) is down'
```

Pinned by `test_salad_status.FormatStatus.test_a_dead_origin_is_down_not_starting`,
`…test_a_booting_replica_is_still_starting`,
`…test_the_block_reason_for_a_dead_origin_says_down_and_why`.

### N6 — a failed render re-applied the cached status word (Medium, executed, FIXED)

`_on_generate`'s completion handler ran `_apply_generate_gate(self.var_salad_status.get())`
on the cached word before branching. A render that dies mid-job usually means the
replica went away, so the cache still held the `Ready` it had beforehand and the
badge and gate kept reporting a container that had already restarted as up.

**Fixed**: the failure branch now calls `_check_salad_status(silent=True)` and
lets a fresh probe decide. Pinned by
`test_app_layout.NewPagesAndPlacement.test_a_failed_generate_reprobes_the_replica_status`.

### N7 — a hand-written `LoraLoader` without `_meta` silently loses its CLIP half (Medium, executed, NOT fixed — by design)

`request_json.lora_is_klein_clip` decides where the two `CLIPTextEncode` nodes
run, matching Klein tokens in `_meta.title` / `_meta.tag` / `_meta.base` **or** in
`lora_name`. A node with a bare Civitai URL and no `_meta` is classified
**foreign**, and `wire_clip_encodes` moves both encodes back to the base
`CLIPLoader`. The editor file says `74.clip: ["80", 1]`; the POSTed copy says
`["71", 0]`.

Measured on a hand-authored graph: the posted plate differed from the intended
one (`sha256[:16] ae1b7e0403e8f20a` vs `62eeb2c611edf7e5` at the same seed), and
the same shape is present in the user's own `failed_prompt_style_s610296.json`
(node 81, `_meta: null`).

**Not fixed.** The classifier is behaving as designed — a foreign CLIP tensor on
Qwen corrupts the encoding — and the defect is the *silence*, not the rule. The
guidance is now in doc 21 §5: build the chain with
`request_json.build_request`, which stamps `_meta` through `attach_lora_chain` →
`weight_meta`, rather than by hand. A future pass could warn when a `LoraLoader`
carries a URL and no `_meta`.

### N8 — six modules mutate `sys.path` at import time (Medium-low, read-from-source, OPEN)

Doc 57's **L1**, still open and now in six modules: `app.py`,
`civitai_verify.py`, `comfy_import.py`, `generator.py`, `lora_store.py`,
`request_json.py`. It is why `test_profiles.py` cannot be run as
`salad_studio.test_profiles` (N12). A package-relative import would remove the
whole class.

### N9 — `app.py` swallows 23 exceptions (Low, read-from-source, OPEN)

`except …: pass` appears 23 times in `app.py`, mostly around Tk widget
configuration. Defensible for teardown, but it is the mechanism by which a broken
callback becomes a silent no-op. Not individually triaged.

### N10 — `test_profiles.py` is not runnable by module path (Low, executed, OPEN)

The module uses flat imports (`from profiles import …`), so
`python -m unittest salad_studio.test_profiles` from the repo root reports one
error — the module fails to import — while `python -m unittest discover -s
salad_studio` from the repo root is fine (discover puts `salad_studio` on the
path). The audit's own first attempt at running it hit this.

### N11 — public names no test references (Low, read-from-source, OPEN)

A coverage *signal*, not proof of untestedness — many are exercised indirectly.
The largest surfaces: `salad_status` 8 (`apply_policy`, `find_group_by_gateway`,
`reallocate_instance`, `recent_log_lines`, `list_gpu_classes`, `replica_detail`,
`attach_last_log`, `pull_pct`), `civitai_verify` 18, `graph_view` 16,
`request_json` 14, `comfy_import` 13, `lora_store` 9, `ai_helper` 6.
The Policy / Reallocate path and the theme style helpers are the thinnest.

### N12 — two modules called `test_prompt_catalog` would collide (Low, executed, AVOIDED)

The runtime Prompt Catalog **store** (`salad_studio/prompt_catalog.py`, the
user's named request JSONs) already owns `test_prompt_catalog.py`. This session's
first draft of the Klein catalog check overwrote it. It was restored from HEAD
and the new check lives in `test_klein_prompt_catalog.py`, whose docstring says
which is which. Recorded here so a future pass does not repeat it.

---

## 3. Doc-vs-source verdicts

### 3.1 `salad_studio/README.md` — accurate

Checked bullet by bullet against the source. The Generate/routing, Tokens,
Import and Prompt Editor descriptions match the code as it now stands, including
the two behaviours this session changed:

- "Generate is disabled until the *active* gateway is Ready" — matches
  `_apply_generate_gate`.
- "appends Civitai `?token=` on LoRA URLs at POST time" — matches
  `authorize_civitai_urls`, and is now true for `LoraLoaderModelOnly` too (N3).
- The Import bullet's account of local LoRA filename resolution matches
  `resolve_local_lora_nodes`; it does not mention the URL case, which is now
  handled (N2).

No correction needed.

### 3.2 `docs/workflow/15-salad-flux2-klein-group.md` — one section superseded

The "Two-body plate recipe" section presented a 4-LoRA / 6-step / 5,049-char
sectioned stack as *the* shipped plate recipe and stated "the prompt architecture
is the quality lever". Both are superseded: the only human-judged recipe is the
one `prompt_ledger.json` records, and the measured finding is that the **seed**
dominates (2 of 7 seeds). The section now carries a superseded banner pointing at
doc 21. The rest of doc 15 (group creation, prefetch, probes) still matches the
tree.

### 3.3 `docs/workflow/16-salad-studio-prompt-graph.md` — accurate

Its "Decision (2026-09-20)" and the removal note match `graph_view.py`, whose
module docstring now states plainly that "No Graphviz / grandalf path exists".
Doc 57's M7 closure holds.

### 3.4 The Klein workflow docs' external claims — see doc 21 §8

Doc 17's source list and doc 19's position-ranking sentence were checked against
their sources on 2026-09-23. Two corrections are recorded there and applied in
place: doc 17's "SNOFS v1.4 LoRA page (position failure reports)" label (the page
is a list of terms that work), and doc 19's "community reports rate the positions
very differently" (no source found). Doc 17's download count is stale.

---

## 4. Observed test state

**Command**, from the repo root:

```
python -m unittest discover -s salad_studio -p "test_*.py"
```

**Result** (captured to `salad_studio_suite_final.log` in the audit's scratch dir,
which is transient — re-run the command to reproduce):

```
Ran 565 tests in 180.534s

OK
```

The suite is **green**. For comparison, the baseline this pass started from —
recorded in the goal plan and reproduced before any change — was:

```
Ran 554 tests in 117.890s

FAILED (failures=9, errors=2)
```

with **all 11** non-passing cases in `test_klein_recipes.py`. That module pinned a
superseded recipe (a 4-LoRA chain, 6 steps, 5,049-char sectioned prompts) while
the recipe file on disk held the ledger's verified entry (no LoRAs, 4 steps,
779 chars), so the module and its subject disagreed on every knob.

The arithmetic of 554 → 565 is +11, and it accounts exactly: the rewritten
`test_klein_recipes.py` has 17 test methods where the old had 24 (**−7**);
`test_klein_prompt_catalog.py` adds **+15**; three direct routing-helper tests in
`test_profiles.py` add **+3**. Everything else the suite gained this session
(routing, the failed-generate re-probe, the 206 probe, the status classifications,
the `LoraLoaderModelOnly` token coverage) was already inside the 554 baseline.

**The new checks have teeth.** Both were mutation-tested, and each mutation was
required to fail *for the right reason*:

| Check | Mutation | Observed |
|---|---|---|
| `test_klein_prompt_catalog` | one character inside the catalogued positive prompt | FAIL — "no longer matches node 74" |
| `test_klein_prompt_catalog` | entry pointed at a recipe lacking that text | FAIL |
| `test_klein_recipes` | node 74 `missionary position` → `doggystyle position` | FAIL — `test_the_positive_prompt_is_the_verified_text` |
| `test_klein_recipes` | an unrecorded LoRA spliced into the chain | FAIL — "no longer matches prompt_ledger.json's graph.loras" |

Each was restored afterwards and re-run green.

---

## 5. Remediation queue (suggested order)

1. **N8 / N10** — replace the flat `sys.path` inserts with package-relative
   imports. Clears the six-module import hazard and makes every test module
   runnable by path. One change, mechanical.
2. **N7** — warn at Generate when a `LoraLoader` holds an http(s) `lora_name`
   with no `_meta`, instead of silently moving the encodes. The user-visible
   symptom is a plate that does not match the graph.
3. **N11** — cover the `salad_status` Policy / Reallocate path
   (`apply_policy`, `reallocate_instance`, `find_group_by_gateway`) and the
   `theme` style helpers. These are the thinnest surfaces on a live UI.
4. **N9** — triage `app.py`'s 23 `except: pass` sites; keep the teardown ones,
   log the rest.
5. **Doc 17** — refresh the SNOFS download count and the v1.2 size units, or
   drop the moving numbers entirely (doc 21 §8 carries the corrections).

---

## 6. What doc 57 closed, re-confirmed against the current tree

Not taken on trust — each was re-checked in the source on 2026-09-23.

| Doc 57 finding | Re-check | State |
|---|---|---|
| **H1** `add_lora` dropped the row | `test_lora_store` passes in the green suite | closed |
| **H2** `_reuse_prompt_history` hit the removed Prompt tab | `grep 'self\._prompt\b' app.py` → no match | closed |
| **M3** `_api_get` dead after its first statement | one `def _api_get` in `salad_status.py` | closed |
| **M6** two replica-missing-type lists | one `SALAD_MISSING_TYPES` definition (`comfy_import.py:31`); `civitai_verify.py:1253` only holds the patch marker | closed |
| **M7** dead Graphviz/grandalf stack | no `prompt_to_dot` / `grandalf` / `graphviz_layout` / `parse_dot_plain`; `graph_view.py`'s docstring states their absence | closed |
| **L3** unused `studio_log.LEVELS` | no match | closed |
| **L5** unguarded profile coercion | `profiles._coerce` guards width/height/steps/cfg/seed | closed |
| **L1** modules mutate `sys.path` | **still open, now six modules** | see **N8** |

**New since doc 57.** The tree gained `ai_helper.py`, `prompt_catalog.py` and
`ref_check.py` (each with a dedicated test module), and the Studio gained
container-group routing, the dual replica badges, the token pre-flight and the
`LoraLoaderModelOnly` handling — which is where this pass found N1–N6.

---

## 7. Out of scope

As the goal set it: fixing anything beyond the seven defects above; `eldermark` /
`lifesim_core`; the Salad cloud API and the `salad_klein/` Docker image;
the vendored `graph_html/` JS; interactive GUI verification of the Tk panes or the
WebView2 diagram; performance benchmarking; new render experiments (the Klein
open questions are documented in doc 21 §6, not resolved).
