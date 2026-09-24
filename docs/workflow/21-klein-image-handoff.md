# 21. Flux.2 Klein image generation: the handoff

**This is the single entry point for the Klein image work.** Started 2026-09-23.
Read this first; it names the operating point, the container groups and how
routing picks one, what to do, what not to do, the known failure modes, the open
questions, and where each load-bearing claim came from.

**Scope:** 18+ adults only, two adults, no minors, nothing illegal.

**Audience:** a reader who has never seen this work and needs to continue it
without re-deriving it.

**What this supersedes.** Three older statements are now wrong and have been
corrected in place, each pointing here:

| Site | Was | Now |
| --- | --- | --- |
| `docs/workflow/15-salad-flux2-klein-group.md` → "Two-body plate recipe" | presented the 4-LoRA / 6-step / sectioned-prompt stack as *the* shipped plate recipe | marked superseded; points here |
| `salad_klein/README.md` → recipe paragraph | same claim, plus "the prompt architecture is the quality lever" | corrected; points here |
| `salad_studio/test_klein_recipes.py` → module docstring | asserted "the prompt architecture is the quality lever" as the module's subject | rewritten against the verified entry (§2) |

The research documents (14, 17, 18, 19, 20) are the **record of how this was
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
and is superseded for the record. See §8 note on `full` vs `alone`.

### The prompt, verbatim

```
STYLE: ArsMJStyle, Impressionism, oil painting on canvas, visible expressive brushstrokes, dappled natural light, soft impressionist colour, crisp readable painted detail, clean edges on the figures.

SUBJECTS: exactly two nude figures, one woman and one man, two clearly separate bodies, both fully in frame.

POSE: missionary position, clean side view in profile. She lies on her back, head on a pillow, knees bent and drawn up, thighs open to either side of his hips, feet on the mattress. He lies over her between her thighs, chest low over hers, weight on his forearms beside her shoulders, hips between her thighs. His knees rest on the mattress between her thighs, his shins flat behind him.

INTIMACY: penis inside her vagina, his hips against hers, joined at the pelvis.
```

```
NEGATIVE: blurry, low detail, distorted anatomy, fused bodies, censored, watermark, text, signature, 3d render.
```

The same text, with the seeds and verdicts, is in the catalog:
[`../../salad_klein/prompt_catalog.json`](../../salad_klein/prompt_catalog.json).
The catalog is machine-checked against the recipe files it quotes (§7).

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

A 3 s render becomes 240–576 s, and every one of them 524s. `prefetch.py` takes a
build-time `KLEIN_UNET_SET` so each image ships only its own unets
(`prefetch6-klein` = base + distilled, `prefetch6-snofs` = SNOFS).

**How routing decides.** Salad Studio routes at **Generate**, from the graph's
`UNETLoader.unet_name`, before the POST:

```
profiles.unet_family(unet_name)     -> "snofs" if "snofs" is in the name, else "klein"
profiles.route_payload(payload)     -> the profile whose group serves that family
profiles.profile_for_gateway(gw)    -> the group the form would POST to
```

The guard compares the graph's family to **the family the current gateway's group
serves**. If they differ it swaps the profile and logs
`Routed to profile 'klein5090' (gateway …)`. A hand-typed gateway that is not one
of the saved profiles is left alone.

> **Fixed 2026-09-22.** The guard used to compare the graph's family to the
> **form's** unet. Loading a JSON into the Prompt Editor rewrites that field from
> the graph, so the two sides always agreed and the guard could never fire, a
> SNOFS graph rendered on the klein group. Regression tests:
> `test_app_layout.NewPagesAndPlacement.test_generate_routes_a_snofs_graph_off_the_klein_group`
> and its two siblings.

**Practical consequence.** A graph's unet decides its group; the profile dropdown
does not. If a SNOFS graph renders on the klein group, routing is broken. Check
the Logs tab for the `Routed to profile` line.

---

## 3. What to do

1. **Batch seeds; do not tweak prose.** ~3 s per plate once the model is
   resident, so a 12-seed sheet costs ~40 s. Review it as a labelled contact
   sheet.
2. **A human judges.** Measured on 2026-09-22: a VLM asked to check anatomy
   scored 25 % TPR / 33 % FPR and called broken plates clean, and the session's
   own reads missed a missing act, a third leg, an extra arm and a wrong leg. At
   3 s per plate, a person picking from a sheet wins.
3. **Record the verdict, good or bad, in `prompt_ledger.json`.** Put the prompt
   in a recipe file first and let the ledger copy it, so the recorded text cannot
   drift from what ran. An entry needs the graph, the verbatim prompt and
   negative, the seeds judged, and the **user's own words**. If nobody looked at
   the plate, it is not an entry.
4. **State the act directly.** `INTIMACY: penis inside her vagina, his hips
   against hers`. The plate audit found *act not depicted* in **11 of 16** earlier
   plates. The dominant failure was never limbs.
5. **Name the canonical position** (`missionary`, `doggystyle`, `cowgirl`,
   `spooning`, `prone`) rather than describing geometry. SNOFS's own page lists
   these as the terms that work (§8).
6. **Give both bodies a specific, physically coherent posture.** The one
   measurable prompt win was adding
   *"His knees rest on the mattress between her thighs, his shins flat behind him."*,
   judged "the best" of five variants at a fixed seed.
7. **Always carry the style block.** It was constant across every good plate and
   it is what makes the output the house look.
8. **Keep the negative short and style-only.** At CFG 1 it is mathematically
   inert (`pred = uncond + cfg·(cond − uncond)` collapses to `pred = cond`).
9. **Keep `_meta` on every `LoraLoader`.** See §5. It is load-bearing.
10. **Watch the preconditions.** One unet family per group; routing correct;
    replica actually Ready. Without them the prompt question is moot.

---

## 4. What NOT to do

Measured dead ends. Do not retry these.

| Approach | Result |
| --- | --- |
| Enumerating defects in the positive prompt (`four legs and four feet … no more and no fewer`) | Present in **16/16** plates, good and bad alike; the strongest form appeared only in the plates that *worked*. Not the cause. |
| Enumerating defects in the negative (3,649 chars) | **Proven inert** at CFG 1, and it listed `cowgirl, doggy style, rear entry, spooning` as suppressed, forbidding the positions that render. |
| Raising CFG to 1.2 / 1.3 / 1.5 to make the negative bite | Artifact survived. (Those runs also carried the position blacklist, so they are not evidence about negatives in general.) |
| Anatomy fixer LoRA at 2.0 / 3.0 | Artifact survived. |
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
| HTTP **524** on `/prompt` | Response cut at the gateway's ~120 s read window. The job continues server-side, so resubmitting the same graph usually returns the cached plate in ~2 s. | Resubmit once, or reduce the work. |
| `comfyui-api` **hangs on `/prompt`** while still answering `/ready` 200 | Observed after ~8 sequential renders: Comfy logs nothing for new requests and the client times out. | Reallocate the instance. Keep batches modest; never trust `/ready` alone. |
| 3 s render becomes 240–576 s | Two unet families resident in one group (§2). | Route by unet family. |
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
- **The CLIP-encode rule.** Klein-native LoRAs encode *after* the last such
  loader; foreign stacks (Illustrious / Anima / SDXL / Pony) keep both encodes on
  the base `CLIPLoader`. Do not fight it. An SDXL CLIP tensor on Qwen corrupts
  the encoding.
- **`LoraLoaderModelOnly` carries `lora_name` too.** Until 2026-09-22 the token
  attach, the pre-flight probe and the POST log all filtered on
  `class_type == "LoraLoader"`, so a gated Civitai file in that node reached the
  replica unauthenticated. Fixed by keying on the input
  (`request_json.lora_name_inputs`).
- **The `/ready` probe accepts 200 and 206.** A ranged `GET` to a Civitai CDN
  answers **206 Partial Content**; a plain-200 test reported every live LoRA as
  "unconfirmed".
- **A dead origin is not "Starting".** `salad_status.short_status` now maps
  Cloudflare origin-down codes (0, 520–524) on a running instance to **Down**,
  and the block reason carries the HTTP explanation. Before 2026-09-22 it said
  "Replica is up but Comfy is not ready" for a replica that was gone.

**Quality-level**

- **The seed dominates.** ~2 in 7. The same prompt at another seed failed
  differently. Selection beats iteration.
- **Two similar-skinned bodies blend.** This is the "fused bodies" failure, and
  it is why SNOFS v1.4 was trained against depth.
- **Shot scale correlates with failure.** Figures at 40–53 % of frame rendered;
  25–30 % failed. Pull the camera back.
- **4 steps is the anatomy-risky end of a named axis.** See §6 and §8. Two
  independent external sources name 4 steps as the regime where two-person
  interactions produce extra limbs. Our verified plate is a 4-step render, and it
  is one of 7 seeds.

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
3. **v1.4 vs our v1.2.** v1.4 exists (bf16 and fp8) and adds depth training.
   Nothing has A/B'd it here.
4. **Step count / sampler / CFG above 1.** External evidence says more steps,
   `res 2s` and CFG slightly above 1 each reduce anatomy errors on this model
   line, and that 4 steps is where two-person interactions break. Our verified
   recipe sits at 4 / euler / 1.0. Untested here.
5. **NAG (Normalized Attention Guidance).** Unverified on our image.
6. **The position matrix.** Only missionary has a human verdict. Doggystyle,
   cowgirl and blowjob are candidate prompts with no plate judged.
7. **An automatic anatomy QC gate.** A prototype scored 25 % TPR / 33 % FPR,
   measured negative. A person on a contact sheet is currently better.
8. **The SDXL migration question.** See doc 18; premise unverified.
9. **Does the `comfyui-api` hang depend on batch size?** Observed after ~8
   sequential renders; not characterised.
10. **Can any diffusion configuration give anatomically correct two-body
    interlock *every time*?** As of 2026-09-23, no. Two independent deep-research
    passes found no published measured rate from either family, and the only
    route with correctness *by construction* is 3D (DAZ → Blender geograft weld,
    or an engine with hand-keyed penetration). The one code-verified per-partner
    separation technique, masking each regional LoRA's delta to its own box,
    exists for Krea 2 / Flux.2-Klein and refuses SDXL adapters. Full record with
    sources and its own coverage gaps:
    [`22-two-body-correctness-research.md`](22-two-body-correctness-research.md).

---

## 7. Where things live

| Path | What |
| --- | --- |
| `salad_klein/prompt_ledger.json` | **canonical** prompt text + human verdicts. Append, never overwrite |
| `salad_klein/prompt_catalog.json` | the catalog of successful prompts (§1), machine-checked against the recipes |
| `salad_klein/prompt_snofs_distilled_v12.json` | the verified recipe |
| `salad_klein/prompt_snofs_distilled_anatomy*.json` | superseded 4-LoRA research stack |
| `salad_studio/test_klein_prompt_catalog.py` | the catalog drift / well-formedness check |
| `salad_studio/test_klein_recipes.py` | asserts the verified operating point |
| `docs/history/58-salad-studio-audit-2026-09-22.md` | the current Studio audit |
| `~/.config/salad/studio-profiles.json` | profiles (gateways, unet per group), not git |
| `~/.config/salad/gateway-klein`, `gateway-klein-5090` | gateway URLs, not git |
| `salad_studio/studio-tokens.json` | provider keys, incl. Civitai, not git (`.gitignore:111`) |

**Token handling.** Civitai `?token=` is appended to LoRA download URLs **at POST
time**, onto a deep copy (`request_json.authorize_civitai_urls`). The editor JSON,
the prompt history and the catalog keep the bare URL, so a saved or shared graph
carries no secret. A URL that already has a token is left alone; one that already
has parameters gets `&token=` appended, via `urllib.parse` rather than string
concatenation.

---

## 8. Sources, with the date each was checked

### Re-verified 2026-09-23 (this document)

| Claim | Source | Result |
| --- | --- | --- |
| SNOFS v1.4 Klein 9b Distilled bf16 = version `2985440` fileId `2865386`, sha256 `E3A8C25C…4BCE197` | `https://civitai.com/api/v1/models/2416142` | **MATCH** |
| same version, fp8 = fileId `2867344`, sha256 `3A403EB4…A4CBC8D` | same | **MATCH** |
| v1.4 Klein 9b **Base** = version `2967967` | same | **MATCH** |
| our v1.2 = version `2786085` fileId `2672539`, sha256 `8F14F150…FEB1E35` | same | **MATCH** |
| the official ComfyUI Klein template ships **4B** filenames (`qwen_3_4b`, `flux-2-klein-4b-fp8`) so the 9B swap is manual | `https://docs.comfy.org/tutorials/flux/flux-2-klein.md` | **MATCH** |
| diffusers LoKr bug: issue `#13261` **open**, created 2026-03-12 | GitHub API | **MATCH** |
| first fix PR `#13997` **closed, merged=false** | GitHub API | **MATCH** |
| umbrella PR `#14163` **open** | GitHub API | **MATCH** |
| the SNOFS LoRA's Klein v1.4 build is version `2960556` | `https://civitai.com/api/v1/models/1972981` | **MATCH** |

### Corrected by this pass

| Claim | Where it was | Correction |
| --- | --- | --- |
| "SNOFS v1.4 LoRA page **(position failure reports)**" | doc 17 §9 | The page is a **list of terms that work well** (missionary / doggystyle / cowgirl / prone / reverse cowgirl / spooning position, plus notes like *"cunnilingus (be specific and maybe put kissing in the negative prompt)"*). It reports no per-position failure rates. |
| "Community reports on this model line **rate the positions very differently (missionary worst, doggystyle best-rendered)**" | doc 19 §3 | **No source found.** Not in either SNOFS model description, and the Civitai comments endpoints are refused. Treat as unsourced; do not cite it. |
| SNOFS merged checkpoint "**17,166 downloads**" | doc 17 §2.1 | Stale. The API reports **55,187** on 2026-09-23. A download count is a moving number; do not quote it as a fact. |
| our v1.2 is "**9.08 GB**" | doc 17 §2.1 | Unit-dependent: the API's `sizeKB` gives **8.46 GiB** = 9.08 GB decimal. State the unit. |

### New since the docs were written

- The SNOFS **merged** model now publishes three **Krea 2** versions
  (`3333138` Turbo v1.4, `3333068` Raw v1.4, `3226711` Raw v1.3D) alongside the
  Klein ones, and the SNOFS **LoRA** model has six Krea 2 versions. Klein is no
  longer the newest line on either page.
- The merged model's own API description mentions bf16 / int8-convrot variants.

### Not re-verified, treat as unconfirmed

| Claim | Source as cited | Why not |
| --- | --- | --- |
| The SNOFS author's fp8 warning (*"FP8 is up. I noticed significant degradation … fingers … recommend bf16"*) | quoted in doc 17 §2.2 | The version descriptions come back **empty** from the Civitai API and the civarchive page does not carry the sentence. **As of 2026-09-23, not re-verified.** |
| "3 arms or other horrors images … increasing to eight steps seems to help" | doc 17 §2.2, cited to the HF fp8 discussions | The thread **is** real, discussion **#2, "4steps gives many 3 arms or other horrors images"**, opened 2026-01-16, open, but the wording differs and it is **about 4 steps**, not fp8: *"This fp8 version + default Comfyui workflow gives 3 arms or other horrors images many time. Giving 8steps seems to help…"*, answered by a report that **40 steps also fails** and that a q8 GGUF is better. Re-verified with that correction. |
| NAG, MatchingPose, RefControl, the `res_2s` class name, Male Anatomy's PromptHero host | doc 17 / 19 / 20 | Not re-fetched. Anything doc 20 marks *"verify in your build"* has **not** been checked against our image (`api1.19.2`). |

### Corroboration worth having

`https://myaiforce.com/flux-2-klein-anatomy-horror/`, fetched **2026-09-23**,
secondary source (single-author blog, no methodology published). It states:

- *"4 steps are sometimes not enough, especially for: Sitting poses / Complex
  body positions / **Two-person interactions** / Hands doing something specific."*
- *"A classic failure example at low steps: **At 4 steps, I got a man with three
  legs** … at 8 steps the result was dramatically better."*
- But *"more steps aren't always better"*. It also saw 4 steps produce correct
  bodies and 8 steps introduce an extra finger.
- `res 2s` *"can reduce anatomy errors in certain cases"* (it does 2 model calls
  per step, ~2× the compute).
- CFG has *"a narrow sweet spot"*: at 8 steps, CFG 1.0 merged fingers, **1.2
  separated them**, 1.5 broke them again.

**Why this matters here.** Our verified recipe is **4 steps / euler / CFG 1.0**,
the risky end of all three axes this source names, on the exact case it names
(two-person interaction). The plate is nonetheless good, because the seed lottery
landed well. This is corroboration for the open questions in §6.4, not a verdict:
one blog is not a controlled test, and our own A/B is the thing that would settle
it.

---

## 9. The one-paragraph version

Run `prompt_snofs_distilled_v12.json` on the SNOFS group, SNOFS-merged distilled
v1.2 fp8 unet, Qwen fp8 CLIP, flux2 VAE, euler, **4 steps**, **CFG 1**, 832×1216,
no LoRAs, with the four-section prompt in §1. Expect a good plate at roughly 2
in 7 seeds, so batch seeds and let a person pick rather than rewriting the prose.
Keep one unet family per container group and let Studio route on the graph's
`UNETLoader.unet_name`. Record every human verdict in `prompt_ledger.json`. The
open question is whether Base + more steps beats this; the external evidence says
it might, and nothing here has tested it.
