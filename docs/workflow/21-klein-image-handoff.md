# 21. Flux.2 Klein image generation: the handoff

**This is the single entry point for the Klein image work.** Started 2026-09-23.
Read this first; it names the operating point, the container groups and how
routing picks one, what to do, what not to do, the known failure modes, the open
questions, and where each load-bearing claim came from.

**Scope:** 18+ adults only, two adults, no minors, nothing illegal.

**Audience:** a reader who has never seen this work and needs to continue it
without re-deriving it.

**What this supersedes.** Three older statements were wrong and were corrected
in place, each pointing here:

| Site | Was | Now |
| --- | --- | --- |
| `docs/workflow/15-salad-flux2-klein-group.md` → "Two-body plate recipe" | presented the 4-LoRA / 6-step / sectioned-prompt stack as *the* shipped plate recipe | marked superseded; points here |
| `salad_klein/README.md` → recipe paragraph | same claim, plus "the prompt architecture is the quality lever" | corrected; points here |
| `tests/test_klein_recipes.py` → module docstring | asserted "the prompt architecture is the quality lever" as the module's subject | rewritten against the verified entry (§2) |

The research documents (14 and 22) are the **record of how this was
learned**, not the current state. Where they disagree with this document, this
document wins, and §8 says which of their claims re-verified.

---

## 1. The operating point (verified)

One recipe has a **human verdict**. Everything else is a candidate.

| Knob | Value |
| --- | --- |
| recipe file | `salad_klein/prompt_snofs_distilled_v12.json` |
| unet (node 70) | `snofsSexNudesAndOther_distilledV12KleinFp8.safetensors` |
| clip (node 71) | `qwen_3_8b_fp8mixed.safetensors`, `type: flux2` |
| vae (node 72) | `flux2-vae.safetensors` |
| sampler (node 61) | `euler` |
| steps (node 62) | **4** |
| CFG (node 63) | **1** |
| size (node 66 / 62) | 832 × 1216, batch 1. Latent and scheduler **must agree** |
| LoRAs | **none** |
| positive (node 74) | 779 chars, four sections: `STYLE:` / `SUBJECTS:` / `POSE:` / `INTIMACY:` |
| negative (node 67) | 111 chars, style-only |
| group | `flux2-klein-5090`, the SNOFS group |

**Acceptable seeds: `323175253610296`, `610044882331`.** Five others were judged
bad: `114772190455233`, `924411309871006`, `782300144559`, `555100233771`,
`410299187654`. **Hit rate: 2 of 7 seeds.** The prompt text, the seeds and the
user's own verdict words are in `salad_klein/prompt_ledger.json`
(`verdicts[0]`, id `snofs-missionary-v1`).

**Where the LoRAs went.** The verified entry has none. The older
`prompt_snofs_distilled_anatomy*.json` files carry a four-LoRA stack and a
5,049-char sectioned prompt; that stack has **no human verdict in the ledger**
and is superseded for the record. See §4, the `Stripping the LoRA stack` row.

The prompt text is canonical in `salad_klein/prompt_ledger.json` (`verdicts[0]`, id `snofs-missionary-v1`)
and copied into [`../../salad_klein/prompt_catalog.json`](../../salad_klein/prompt_catalog.json);
it is not reproduced here. The catalog is machine-checked against the recipe files it quotes (§7).

---

## 2. Container groups, and how a graph picks one

Two Salad container groups, one unet family each. This is not tidiness. It is
the difference between a 3-second render and a 524.

| Group | Gateway file | Serves | Image tag |
| --- | --- | --- | --- |
| `flux2-klein2` | `~/.config/salad/gateway-klein` | plain Klein (base / distilled) | `…prefetch6-klein` |
| `flux2-klein-5090` | `~/.config/salad/gateway-klein-5090` | the SNOFS merged cut | `…prefetch6-snofs` |

**Why one family per group.** A 24 GB card (4090 / 3090) holds one ~9 GB unet
plus the 8.66 GB Qwen text encoder, about 17.7 GB. When a second unet is needed,
the pair does not fit and Comfy falls back to streaming weights from host
memory:

```
Model Flux2 prepared for dynamic VRAM loading. 8658MB Staged. 112 patches
attached. Force pre-loaded 80 weights      (measured 2026-09-22)
```

An earlier group held three unets and ran a 3 s render for 239 to 576 s, ending
in a 524; that group no longer exists. Each image now carries only its own unets.
The Docker build bakes a `KLEIN_UNET_SET` build arg into the image, and
`prefetch.py` reads it at first boot to decide what to download
(`prefetch6-klein` = base + distilled, `prefetch6-snofs` = SNOFS).

**How routing decides.** Salad Studio routes at **Generate**, from the graph's
`UNETLoader.unet_name`, before the POST. The family table itself is the
**metadata document** (`salad_studio/studio-metadata.json`, or your copy at
`~/.config/salad/studio-metadata.json`), not code:

```
studio_meta.family_for_unet(unet_name, doc)  -> the family whose unets/markers match
profiles.plan_route(payload, form_profile, all_profiles)
                                            -> (Route | None, refusal reason)
profiles.profile_for_gateway(gateway, all_profiles)
                                            -> the group the form would POST to
```

`plan_route` reads the graph's checkpoint and finds the profile whose own
`checkpoints` list names it, edited on the Config page. One profile listing it
is the route. If the profile the form's gateway belongs to is that profile, the
graph is sent where the form points. Otherwise it swaps the profile and logs
`Routed to profile 'klein5090' (gateway …)`. A checkpoint **no profile's list
names** is **refused with a stated reason**, and so is one that **two profiles
list**, rather than sent to a group that cannot serve it. A hand-typed gateway
that is not one of the saved profiles is left alone. The family only labels the
route: `plan_route` looks it up in the metadata document, where a checkpoint the
document does not classify is its own family, so a checkpoint that does not exist
yet is routable with no document edit. The document's `unets` and `markers` say
what a family *is* (`group` and `gateway` are gone).

> **Fixed 2026-09-22.** The guard used to compare the graph's family to the **form's** unet, which
> loading a JSON into the Prompt Editor rewrites from the graph, so it could never fire: a SNOFS graph
> rendered on the klein group. Regression tests: the `plan_route` cases in `tests/test_profiles.py` (`test_a_snofs_graph_routes_off_the_klein_group` and its siblings).

**Practical consequence.** A graph's unet decides its group; the profile dropdown
does not. If a SNOFS graph renders on the klein group, routing is broken. Check
the Logs tab for the `Routed to profile` line.

---

## 3. What to do

The prompt rules are §9, its §3, with their evidence; the workflow is §9, its §5. Keep `_meta` if the node has one (§5). Watch the preconditions: one unet family per group (§2), correct routing, and a replica that is actually Ready. Without them the prompt question is moot.

---

## 4. What NOT to do

Measured dead ends. Do not retry these.

| Approach | Result |
| --- | --- |
| Enumerating defects in the positive prompt (`four legs and four feet … no more and no fewer`) | Present in **16/16** plates, good and bad alike; the strongest form appeared only in the plates that *worked*. Not the cause. |
| Enumerating defects in the negative (3,649 chars) | **Proven inert** at CFG 1, and it listed `cowgirl, doggy style, rear entry, spooning` as suppressed, forbidding the positions that render. |
| Raising CFG to 1.2 / 1.3 / 1.5 to make the negative bite | Artifact survived. (Those runs also carried the position blacklist, so they are not evidence about negatives in general.) |
| Anatomy fixer LoRA at 2.0 / 3.0 | 2.0 did not help. 3.0 ran only on the bad missionary prompt; it is untested with the trimmed prompt. |
| Stripping the LoRA stack (`full` 4 LoRAs vs `alone` none) | **Both bad.** Not the cause. |
| Longer, more detailed prompts (5,049 chars, bullet sections) | The bullet-format, scene-heavy rewrite is where failures clustered (7/7), collinear with a castle setting block (6/6) and with shot scale. Plates that rendered put the figures at 40–53 % of frame, failing ones at 25–30 %. |
| Adding a **medieval setting clause** to the verified prompt | User verdict 2026-09-22: *"medievil is disterted - two knees on the left and missing part of the leg on the right"*. Added last, everything else held, same seeds as the control which was not flagged. |
| Leaving a placeholder token in the text (`REPLACE_THIS_PROMPT`) | The model reads an unknown all-caps token mid-sentence and adherence collapses. A shipped recipe rendered a picture of that word for a whole session. |
| Describing his legs generically (*"His legs stretch back behind him…"*) | **Broke her legs** at both seeds. The *posture wording* matters, not merely mentioning his limbs. Stripping both leg descriptions broke her too. |
| Applying the SNOFS LoKr on top of the SNOFS-merged unet | Redundant. The unet already is SNOFS. Safe but pointless; it belongs to the *plain* Klein route. |
| Retrying a 524 in a loop | A 524 means Cloudflare gave up at ~100 s but the job is still running, so a retry submits a **duplicate**. Studio's client retry is 1 attempt by design. |

---

## 5. Known failure modes

**Operational**

| Symptom | Cause | Recovery |
| --- | --- | --- |
| HTTP **521** on `/health` and `/ready` | Cloudflare edge up, replica origin down or being reallocated. Salad's API still reports the group `running` and the instance `ready`. | Wait. Do not retry the render. |
| HTTP **524** on `/prompt` | Response cut at the gateway's ~100 s read window. The job continues server-side, so resubmitting the same graph usually returns the cached plate in ~2 s. | Resubmit once, or reduce the work. |
| `comfyui-api` **hangs on `/prompt`** while still answering `/ready` 200 | Observed after ~8 sequential renders: Comfy logs nothing for new requests and the client times out. | Reallocate the instance. Keep batches modest; never trust `/ready` alone. |
| 3 s render becomes 239–576 s | Two unets resident in one group (§2). | Route by checkpoint. |
| Every render fails with `lora_name` errors | A LoRA URL the replica cannot fetch, usually a gated Civitai file with no `?token=`. | Studio appends it at POST; check the Logs tab's `loras:` line. |

**Graph-level traps**

- **`_meta` on `LoraLoader` is load-bearing.**
  `request_json.lora_is_klein_clip` decides where the two `CLIPTextEncode` nodes
  run, after the last Klein-native loader, or back on the base Qwen loader, by
  matching Klein tokens in `_meta.title` / `_meta.tag` / `_meta.base` **or** in
  `lora_name`. A hand-written node with a bare Civitai URL and no `_meta` is
  classified **foreign**, and the POST copy silently moves both encodes to the
  Qwen loader: the LoRA patches the model only and its trigger words do nothing.
  Measured on a hand-authored graph 2026-09-22. The posted wiring read
  `74.clip ['71', 0]` while the editor file said `['80', 1]`.
  Build the chain with `request_json.build_request` (which stamps `_meta` via
  `attach_lora_chain` → `weight_meta`) rather than by hand.
- **The CLIP-encode rule.** Klein-native LoRAs encode *after* the last such loader; foreign stacks stay on the base `CLIPLoader` (an SDXL CLIP tensor on Qwen corrupts the encoding). Its home is the manual's Prompt Editor bullet, [`salad_studio/README.md`](../../salad_studio/README.md). Do not fight it.
- **`LoraLoaderModelOnly` carries `lora_name` too.** The token attach, the pre-flight probe and the
  POST log keyed on `class_type == "LoraLoader"` until 2026-09-22, so a gated Civitai file there reached the replica unauthenticated; they now key on the input, `request_json.lora_name_inputs`.
- **The LoRA reachability probe accepts 200 and 206.** A ranged `GET` to a Civitai CDN
  answers **206 Partial Content**; a plain-200 test reported every live LoRA as
  "unconfirmed".
- **A dead origin is not "Starting".** `salad_status.short_status` now maps
  Cloudflare origin-down codes (0, 520–524) on a running instance to **Down**,
  and the block reason carries the HTTP explanation. Before 2026-09-22 it said
  "Replica is up but Comfy is not ready" for a replica that was gone.

**Quality-level**

- **The seed dominates.** ~2 in 7. The same prompt at another seed failed differently. Selection beats iteration.
- **Two similar-skinned bodies blend.** This is the "fused bodies" failure, and it is why SNOFS v1.4 was trained against depth.
- **Shot scale correlates with failure.** Figures at 40–53 % of frame rendered; 25–30 % failed. Pull the camera back.
- **4 steps is the anatomy-risky end of a named axis.** See §6 and §8. Two independent external sources name 4 steps as the regime where two-person interactions produce extra limbs. Our verified plate is a 4-step render, and it is one of 7 seeds.

---

## 6. Open questions

Documented, **not** resolved. Do not assume an answer.

1. **Base vs the SNOFS-merged distilled cut.** The researched candidate claims
   Klein 9B **Base** (30–50 steps, CFG 4–5) has far fewer anatomy horrors and that
   distilled is for edits. This contradicts the verified entry. It is a
   `candidates` entry with **no human verdict**, and its own test run produced
   plates that did not match its prompt. Routing note: Base is family `klein`, so
   those plates belong on the **klein** group.
2. **bf16 vs fp8.** The SNOFS author is quoted as recommending bf16 for fingers;
   an independent thread suspects fp8 and reports 40 steps also failing. **The
   author's quote could not be re-verified on 2026-09-23** (see §8). We run fp8.
3. **v1.4 vs our v1.2.** v1.4 exists (bf16 and fp8) and adds depth training. Nothing has A/B'd it here.
4. **Step count / sampler / CFG above 1.** External evidence says more steps, `res 2s` and CFG slightly above 1 each reduce anatomy errors on this model line, and that 4 steps is where two-person interactions break. Our verified recipe sits at 4 / euler / 1.0. Untested here.
5. **NAG (Normalized Attention Guidance).** Unverified on our image.
6. **The position matrix.** Only missionary has a human verdict. Doggystyle, cowgirl and blowjob are candidate prompts with no plate judged.
7. **An automatic anatomy QC gate.** A prototype scored 25 % TPR / 33 % FPR, measured negative. A person on a contact sheet is currently better.
8. **The SDXL migration question.** See doc 22 §5; premise unverified.
9. **Does the `comfyui-api` hang depend on batch size?** Observed after ~8 sequential renders; not characterised.
10. **Can any diffusion configuration give anatomically correct two-body interlock *every time*?** As of 2026-09-23, no: two independent passes found no published measured rate from either family, and the only route with correctness *by construction* is 3D (DAZ → Blender geograft weld, or an engine with hand-keyed penetration). Krea 2 / Flux.2-Klein masking refuses SDXL adapters. [22](22-two-body-correctness-research.md).

**Session discipline.** Test one variable per run against the held baseline
(seed, graph, LoRA chain, 832x1216, euler, 4 steps, CFG 1) and stop at the
first step that clears the artifact rate. Score a 6-seed labelled contact sheet
and show it to the user; do not sign off on anatomy from your own read. The
harness is `salad_studio.generator.generate_from_payload`, with the gateway and
key read from `~/.config/salad/`; never print or commit them. Do not download
weights without asking. A Studio render writes to `%ELDERMARK_ART%\salad_studio`,
outside this repo, and is never committed.

---

## 7. Where things live

| Path | What |
| --- | --- |
| `salad_klein/prompt_ledger.json` / `prompt_catalog.json` / `prompt_snofs_distilled_v12.json` / `prompt_snofs_distilled_anatomy*.json` | **canonical** prompt text + human verdicts (append, never overwrite); the catalog of successful prompts (§1), machine-checked against the recipes; the verified recipe; the superseded 4-LoRA research stack |
| `tests/test_klein_prompt_catalog.py` / `tests/test_klein_recipes.py` | the catalog drift / well-formedness check; the verified operating point |
| `~/.config/salad/studio-profiles.json` | profiles (gateways, unet per group), not git |
| `~/.config/salad/gateway-klein`, `gateway-klein-5090` | gateway URLs, not git |
| `salad_studio/studio-tokens.json` | provider keys, incl. Civitai, not git (`.gitignore:2`) |

**Token handling.** Civitai `?token=` is appended to LoRA download URLs **at POST
time**, onto a deep copy (`request_json.authorize_civitai_urls`). The editor JSON,
the prompt history and the catalog keep the bare URL, so a saved or shared graph
carries no secret. A URL that already has a token is left alone; one that already
has parameters gets `&token=` appended, via `urllib.parse` rather than string
concatenation.

---

## 8. Sources, with the date each was checked

| Claim (re-verified 2026-09-23) | Source | Result |
| --- | --- | --- |
| SNOFS v1.4 Klein 9b Distilled bf16 = version `2985440` fileId `2865386`, sha256 `E3A8C25C…4BCE197` | `https://civitai.com/api/v1/models/2416142` | **MATCH** |
| same version, fp8 = fileId `2867344`, sha256 `3A403EB4…A4CBC8D` | same | **MATCH** |
| v1.4 Klein 9b **Base** = version `2967967` | same | **MATCH** |
| our v1.2 = version `2786085` fileId `2672539`, sha256 `8F14F150…FEB1E35` | same | **MATCH** |
| the official ComfyUI Klein template ships **4B** filenames (`qwen_3_4b`, `flux-2-klein-4b-fp8`) so the 9B swap is manual | `https://docs.comfy.org/tutorials/flux/flux-2-klein.md` | **MATCH** |
| diffusers LoKr bug: issue `#13261` **open**, created 2026-03-12; first fix PR `#13997` **closed, merged=false**; umbrella PR `#14163` **open** | GitHub API | **MATCH** |
| the SNOFS LoRA's Klein v1.4 build is version `2960556` | `https://civitai.com/api/v1/models/1972981` | **MATCH** |

The corrections listed here were applied at their source: doc 22 §4 and §3. **New since the docs were written:** the SNOFS **merged** model now publishes three **Krea 2** versions (`3333138` Turbo v1.4, `3333068` Raw v1.4, `3226711` Raw v1.3D) alongside the Klein ones, and the SNOFS **LoRA** model has six Krea 2 versions, so Klein is no longer the newest line on either page.

**Not re-verified, treat as unconfirmed:**

| Claim | Source as cited | Why not |
| --- | --- | --- |
| The SNOFS author's fp8 warning (*"FP8 is up. I noticed significant degradation … fingers … recommend bf16"*) | quoted in doc 22 §4.1 | The version descriptions come back **empty** from the Civitai API and the civarchive page does not carry the sentence. **As of 2026-09-23, not re-verified.** |
| "3 arms or other horrors images … increasing to eight steps seems to help" | doc 22 §4.1, cited to the HF fp8 discussions | The thread **is** real, discussion **#2, "4steps gives many 3 arms or other horrors images"**, opened 2026-01-16, open, but the wording differs and it is **about 4 steps**, not fp8: *"This fp8 version + default Comfyui workflow gives 3 arms or other horrors images many time. Giving 8steps seems to help…"*, answered by a report that **40 steps also fails** and that a q8 GGUF is better. Re-verified with that correction. |
| NAG, MatchingPose, RefControl, the `res_2s` class name, Male Anatomy's PromptHero host | doc 22 §4 / doc 21 §9 | Not re-fetched. Anything §9 marks *"verify in your build"* has **not** been checked against our image (`api1.19.2`). |

Corroboration for §6 item 4: <https://myaiforce.com/flux-2-klein-anatomy-horror/> (2026-09-23, single-author blog, no published methodology) names **4 steps** as the risky end for **two-person interactions**; one blog is not a controlled test.

## 9. Two-body prompt playbook

*Consolidated from `docs/workflow/19-two-body-prompt-playbook.md` on 2026-10-17. Subsection numbers below are the source document's own.*

**Started 2026-09-22.** Companion to doc 22 §4 (why Klein failed for two-body acts) and doc 22 §5 (the SDXL question). The machine-readable form is **`salad_klein/prompt_ledger.json`**. That file is canonical for the prompt text; this doc explains what the entries have in common.

**Scope:** 18+ adults only, two adults, no minors, nothing illegal.

### 1. Why this exists

Before 2026-09-22 the work produced **zero** acceptable two-body plates, 22 judged, none good, and the cause was misdiagnosed four times (LoRA stack, LoRA download, prompt enumeration, prompt length). Two things were wrong, and neither was the wording: a since-retired container group holding **three unets thrashed VRAM**, turning 3-second renders into 239–576 s no gateway would wait for (fixed by shipping one unet family per group, doc 22 §3.3); and a **template shipped as a prompt**, `prompt_snofs_distilled_v12.json` carried the literal `REPLACE_THIS_PROMPT`, so a "successful" 0.9 s render was a picture of that word. With both fixed, renders are **1–4 s** and acceptable plates arrive at roughly **2 in 7 seeds**. The work now is collecting which prompts work; selection, not wording, is what you spend effort on.

### 2. The verified configuration

`salad_klein/prompt_snofs_distilled_v12.json` on `flux2-klein-5090` is §1's table: euler, **4** steps, **CFG 1**, 832×1216, no LoRAs, the 779-char positive and 111-char negative, and the two acceptable seeds.

### 3. What leads to a prompt like this, each rule and the evidence for it

**State the act directly.** `INTIMACY: penis inside her vagina, his hips against hers`. The plate audit found **`ACT0`, act not depicted, in 11 of 16** earlier plates. That was the *dominant* failure all along, not limbs, and it is a wording problem: nothing in those 5,049-char prompts said what the bodies were doing together.

**Name the canonical position rather than describing geometry.** `missionary position, clean side view in profile`. The model has these compositions; prose geometry does not substitute. SNOFS's own model page lists the position terms that work (`missionary` / `doggystyle` / `cowgirl` / `prone` / `reverse cowgirl` / `spooning position`). Do not repeat the old unsourced claim that community reports rate the positions; that claim had no source and the Civitai comments endpoints refuse an unauthenticated fetch.

**Describe BOTH bodies' limbs, each with a specific posture.** This is where the one measurable prompt win came from. The control described her legs in three clauses and said **nothing** about his; his left leg split at the knee. Adding one clause, *"His knees rest on the mattress between her thighs, his shins flat behind him."*, was judged **"the best"** of five variants at a fixed seed. The posture wording matters, not merely mentioning his legs: *"His legs stretch back behind him along the mattress, knees and shins resting flat, one leg to either side of her hips."* **broke her legs** at both seeds, and stripping both leg descriptions broke her too.

**Keep it short and affirmative, and never enumerate.** No limb counts, no defect words, in either polarity. Caveat: our own plate audit found limb counting in 16/16 plates and the strongest counting language in the *only four that worked*, so this rule is **not** proven to fix anything. Treat it as hygiene, not as the cure.

**Always carry the style block.** `ArsMJStyle, Impressionism, oil painting on canvas…` was held constant across every good plate; it costs nothing and it is what makes the output the house look.

**Negative prompt: short, style-only.** At CFG 1 the negative is mathematically inert (`pred = uncond + cfg·(cond − uncond)` collapses to `pred = cond`), so the old 3,649-char defect list did nothing, while listing `cowgirl, doggy style, rear entry, spooning` as *suppressed*, i.e. forbidding the positions that render. Keep it short; revisit only if CFG is ever raised.

**Expect the seed to dominate. Roughly 2 in 7.** The winning prompt produced acceptable plates at 2 of 7 seeds, and the *same* prompt at seed `455233` failed differently (her leg plus crossed palms). **Do not iterate wording looking for a cure.** Batch seeds and select. Measured dead ends: §4.

### 5. The workflow

1. **Batch seeds, don't tweak prose.** Generate ~12 seeds on a settled prompt (~3 s each, so ~40 s for a sheet) and review it as a labelled contact sheet.
2. **A human judges.** A VLM asked to check anatomy scored 25 % TPR / 33 % FPR and called broken plates clean; the session's own reads missed a missing act, a third leg, an extra arm and a wrong leg. At 3 s per plate, a person picking from a sheet is strictly better than any detector we measured.
3. **Record the verdict in the ledger, good or bad.** A prompt is only "good" because a human said so.
4. **Watch the operational preconditions** (§2 graph, one unet family per group, routing in Studio). Without them plates 524 and the prompt question is moot.

The `comfyui-api` `/prompt` hang and its recovery: §5.

### 6. The researched recipe. CANDIDATE, not yet verified

**Source: the user's own research, 2026-09-22.** No plate from this recipe has been judged by a human, so it is not in `prompt_ledger.json`'s `verdicts`; it sits under `candidates`.

The candidate is **Base 9B at 30–50 steps and CFG 4–5**, with SNOFS **0.8–1.0** alone or **0.3–0.5** stacked, Euler + Flux2 scheduler (fall back to `res_2s` / `res_multistep` if it melts), and about **1–1.5 MP** before upscale. This contradicts the verified operating point (§6 item 1). Its full framework, settings, negatives, and Comfy recipe cards are the research record in doc 22 §4; none of it is verified against our image (`api1.19.2`).

### 7. Adding to this playbook

Append to `prompt_ledger.json`, never overwrite: put the working prompt in a recipe file first and let the ledger copy it, so the recorded text cannot drift from what was run. An entry needs the graph, the verbatim prompt and negative, the seeds judged, and the **user's own verdict words**. Prompts judged bad go in the same ledger. The rejected list is what stops a future session retrying a dead end. An entry must say who judged it. If nobody has looked at the plate, it is not an entry.
