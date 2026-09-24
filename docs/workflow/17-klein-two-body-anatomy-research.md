# 17 — Flux.2 Klein two-body plates: anatomy research & next-session plan

**Written 2026-09-22**, after a `/deep-research` fan-out (103 agents, 21 sources fetched,
100 claims extracted, 25 adversarially verified → 19 confirmed / 6 refuted) plus our own
measured render grid from the same night.

Companion documents:

- `docs/workflow/15-salad-flux2-klein-group.md` — the group overview. **Its "Two-body
  plate recipe" section is stale and must be rewritten from this doc.**
- `salad_klein/README.md` — also describes the old recipe.
- `salad_studio/test_klein_recipes.py` — 24 tests asserting the old recipe.

**Scope:** 18+ adults only, two nude adults, no minors, nothing illegal. That is the
whole content domain here and nothing outside it is considered.

---

## 1. Executive summary — what changed

Three things we believed last session did not survive verification, and two things we had
never suspected turned out to be the actual cause.

**Our hypotheses that were refuted:**

| Hypothesis | Verdict | Consequence |
| --- | --- | --- |
| The 5049-char prompt is over budget (30–80 word optimum, ~512-token ceiling) | **refuted 0-3** | Prompt *length* is not why the missionary plate failed. Stop tuning length. |
| "FLUX does not support negative prompts at all" | **refuted 1-2** | Negatives demonstrably bite on the *undistilled base* at ~CFG 4.5 / ~50 steps, and via NAG. Read BFL's guidance as the rule for the distilled CFG-1 regime, not a law of the model. |
| LoRA stack ceilings (3-LoRA limit; distillation LoRAs must go upstream) | **refuted 0-3 / 1-2** | Only the optimizer-blindness mechanism survived (not applicable to us — we use a plain sequential chain). |

**What actually causes the extra leg:**

1. **It is a known model- and pose-level defect on SNOFS, not our prompt.** Community
   reports on this exact model line: missionary *"like 95% chance of body horror"*,
   cowgirl *"95% chance of getting reverse"*, spooning *"nothing but amputee body horrors"*.
   Other reports on the same model: a doubled object in the mouth of an oral scene,
   anatomy emerging from the navel or knee, feet deforming (see §4).
2. **Our own negative prompt was forbidding the positions that actually work.**
   Verified verbatim in `prompt_snofs_distilled_anatomy.json` node 67:

   > `woman on top, cowgirl position, doggy style, rear entry, spooning, side by side, lying face down, legs closed, thighs pressed together.`

   This was written to *force* missionary. It suppressed cowgirl / doggystyle / rear entry /
   spooning — the three positions the community reports as rendering — and demanded the one
   that fails. And at CFG 1 it suppressed nothing anyway.

**Our own best measured result, corrected.** A short affirmative
`doggystyle, rear entry, seen from the side` **rendered the act** at two seeds where the
over-specified missionary prompt failed at six seeds, at CFG 1.2–1.5, and at anatomy-fixer 2.0
and 3.0 — which is real, and points at composition rather than wording. But it was **not clean**:
the user's verdict on one of those two plates is **"he has extra left arm"** (§3.1). So the
position matters and is not a cure.

**Still-true finding, restated:** at `CFGGuider.cfg = 1` the negative prompt is
mathematically inert (`pred = uncond + cfg·(cond − uncond)` collapses to `pred = cond`), so
every anti-artifact line in node 67 has never done anything. That is why the *enumeration*
hurt and the *suppression* did not help — all the live text was in the positive node.

### 1.1 The LoRA-stack hypothesis, tested and falsified — and the resulting conclusion

The SNOFS author explicitly advises *"try SNOFS by itself before you go adding a bunch of other
general NSFW loras or models to it that screw up anatomy"* (§2.6). That was testable cheaply and
it was tested: `full` (all four LoRAs) vs `alone` (none), 3 seeds each, every other variable
held.

**Result: no improvement.** Both arms are bad; the user's verdict on all six unique plates is
*"none of the rendered plates are good."* Two useful by-products:

- **Renders are *usually* reproducible — not guaranteed.** This section originally claimed renders
  were "fully deterministic" on the strength of `full` at seed 610296 being byte-identical
  (`md5 2c5065ff…`) across three batches. **That claim is retracted.** Re-checking every repeated
  render after a later run: **5 of 6 pairs are byte-identical, 1 is not** — `full_s610296` came back
  as `31b8671c…`, a different image from the same graph, seed and recipe. The outlier was the first
  render after a replica restart (a different VRAM/execution path is a plausible but *unconfirmed*
  cause). **Practical consequences:** a repeated seed is *evidence* of reproducibility but not
  proof; a "byte-identical hash" is a **soft** verification check, not a hard one; and the earlier
  "26 files, 16 unique images" finding is still explained by dedup, since most repeats do match.
- **Operational blocker found, then FIXED (2026-09-22).** After the replica restarted, **every
  LoRA-bearing graph** timed out with Cloudflare 524: the replica fetches a LoRA from Civitai
  *inside* the render request, Salad's Container Gateway caps a response at **100 s**, and because
  our retry re-POSTs the same graph blob each attempt restarts the download from zero — so
  retrying never converges. Only the LoRA-free arm rendered; `style` and `anat` were lost.
  **The fix is a warm-up, not a preload:** `POST /download` on our image (`api1.19.2`) is
  asynchronous — 202, returned at once — so `generator.warm_loras` fetches the graph's Civitai
  LoRAs *before* the render (`/models` pre-check → async `/download` → bounded poll), and the
  render then finds them local. Graphs keep their URLs; recipes are untouched. See
  `docs/workflow/18-sdxl-migration-brief.md` §3.2.

**User's conclusion (2026-09-22), recorded as the project's working position:**
*"none of the rendered plates are good — Klein is only good for rendering single bodies or
faces."*

Tally behind it: **22 unique plates judged, zero good** — 16 from the studio prompt, 6 from the
ablation, across two prompt regimes and two LoRA stacks. Consistent with the community reports
in §4 (95 % body horror on the canonical positions, multiple users) and with the author's own
concession of anatomy degradation. Note what this does *not* yet cover — bf16, steps above 12,
the undistilled Base at real CFG, v1.4, and the v1.3 LoKr remain untested — but those are
**incremental** levers (precision, step count, version), and none is structural. The failure
appears specific to **interlocked multi-body compositions**, not to single-subject competence.

---

## 2. Model landscape (verified)

### 2.1 The SNOFS-baked-in checkpoint is real — and we are already on that route

We are *not* loading the SNOFS LoKr. Verified in-repo: node 70 of every SNOFS recipe loads

```
snofsSexNudesAndOther_distilledV12KleinFp8.safetensors
```

i.e. the SNOFS-distilled full checkpoint at **v1.2, fp8**. There is no SNOFS LoRA weight in
the chain (nodes 80→81→82→83 are detail slider −1.5, impressionism 0.8, anatomy fixer 2.0,
FLUX_NSFW_Fix 1.0), so the user's "SNOFS weight should not overpower the other LoRAs"
concern is already moot — and the inverse concern applies instead: the SNOFS **unet** is
v1.2 while most public anatomy evidence is attached to v1.3/v1.4.

The current published build (Civitai model `2416142`, derived version `2985440`, author
Ashen3, updated **2026-09-22 — the day of this research**). *The download count
originally quoted here (17,166) was a snapshot; re-fetched 2026-09-23 the API
reports 55,187, so treat it as a moving number and do not quote it. Three **Krea 2**
versions have since been published on the same model page.*

| Build | Version / fileId | SHA256 |
| --- | --- | --- |
| **bf16** (author-recommended) | version `2985440`, fileId `2865386` | `E3A8C25C3FB17DC835EC046B5E1695DC8C08CC3C259EF8F26F855B4484BCE197` |
| fp8 | version `2985440`, fileId `2867344` | `3A403EB4F82868DE750CD15DD0BD38D99521B3F84544BAEAB786A1AF1A4CBC8D` |

Download form: `https://civitai.com/api/download/models/2985440?fileId=2865386`. **The two
hashes are cross-confirmed** by two independent passes (a research agent reading the model
page and a catalog agent reading `/api/v1`), which also agree on the 16.91 GB / 8.46 GB sizes.
The two passes reported **different filenames** for the same hashes (`…_full_bf16` vs
`…_2865386`), so **name the file by fileId and confirm the on-disk name at fetch time** rather
than trusting either string. Related versions: v1.4 Base = `2967967`; the v1.2 we run is
version `2786085` (fileId `2672539`, sha `8F14F150…`, 9.08 GB), now catalogued.

It is an explicit merge — *"so users can generate without using the SNOFS lokr"* — which is
exactly the shape we already run. **Upgrade path: v1.2-fp8 → v1.4, and fp8 → bf16.**

Catalog status: the v1.2 unet row was **missing entirely** from `model_catalog.py`
and was added on 2026-09-22 as `civitai:2416142@2786085` (kind `checkpoint`, status
`on-klein-group`, `use: ["bodies","sex"]`), cross-referenced bidirectionally with the SNOFS
LoKr row `civitai:1972981@2960556`. The v1.4 build is **deliberately not catalogued yet** —
nothing has A/B'd it (see Step 1).

### 2.2 fp8 is a named cause of anatomy degradation

The model author, on the fp8 build:

> "FP8 is up. I noticed significant degradation when it comes to things like fingers, so I'd
> recommend the bf16 version if possible, at least on some images" — and separately, that
> "the number of fingers it makes on a hand really struggle on the distilled model".

Independently corroborated on the upstream HF build
(`black-forest-labs/FLUX.2-klein-9b-fp8` discussions): *"3 arms or other horrors images many
time… increasing to eight steps seems to help"*. A torchao study that kept
embeddings/modulation/norms/output-head in BF16 while quantizing the rest measures only low
average drift — implying the breakage is **quantization-scheme dependent**, and that
selective precision may capture most of the gain at fp8 cost.

**This is the highest-value single-variable test we have not run.**

### 2.3 The plain-Klein + SNOFS-LoKr route is the broken one (outside ComfyUI)

`huggingface/diffusers` issue **#13261** (open since 2026-03-12, still open 2026-09-22):
loading the SNOFS LoKr onto plain `FLUX.2-klein-9B` fails with a `ValueError` in
`_convert_non_diffusers_flux2_lora_to_diffusers` (`lora_conversion_utils.py:2435`) because
the converter pops only `lora_A/lora_B` and `lora_down/lora_up` suffixes while LoKr tensors
(`…img_attn.qkv.lokr_w1/lokr_w2/alpha`) survive. The first fix PR (#13997) was **closed
unmerged**; the umbrella (#14163) is still open. ComfyUI has native LoKr support, so this
only matters if we ever take a diffusers/PEFT path — **do not plan one.**

### 2.4 The anatomy fixer LoRA — already in our stack, correctly weighted

`klein_slider_anatomy.safetensors` (Civitai `2324991`, version `2615554` = "Klein 9B v1.5",
24,815 downloads) is a **concept slider, not a trigger-word LoRA** — no trigger words exist;
weight alone drives it. Author guidance: *"Weight 2.0 mostly keeps the seed intact and can
be used to fix minor glitches, 3.0 fixes some more prominent artifacts."* Our node 82 uses
exactly this version at 2.0. **We have never tried 3.0 with a trimmed prompt** (the earlier
3.0 sweep ran on the bad missionary prompt, so it was measuring the prompt).

Caveats to carry: multiple users report no effect at 1.0–3.0 at all, and v1.5 is reported to
drift faces. It is a bidirectional slider, so negative weight would theoretically behave as
a defect injector — author self-report only; no commenter has run it negative.

### 2.5 Other Klein 9B anatomy candidates worth a look

- **DPO (Klein 9B base)** — LoRA trained on DPO preference pairs explicitly to steer away
  from "the waxy skin and arm/leg/hand issues". Base-specific, so not a drop-in for the
  distilled cut.
- **PornMaster Flux2 Klein 9B base t2i workflow** — a published workflow for this content
  class on the *base* model.

Neither is a verified fix; both are cheap to test once the ladder in §6 is past step 2.

**A negative result worth recording:** a search for hands/limb-specific Flux.2 Klein 9B LoRAs
found **none** — only SDXL/Illustrious hand fixers. The Klein Anatomy/Quality Fixer (`2615554`)
remains the *only* limb fixer for this base, and its newest Klein 9B version is still v1.5
(no newer one exists from that author). Likewise no newer Klein SNOFS LoKr than `2960556`
(later SNOFS versions target Krea 2).

Same-author (Felldude, who made our house NSFW fix `2482439`) quality leads, **untested and
quality-flavoured rather than limb-specific**: "Real HD 2k" `2960420`, "Real HDR" `2900355`,
"Real Skin" `2848310`, checkpoint "Klein FinalCut" `3285291`. Alternative detail slider
(alcaitiff) `2741947` is a 5.4 MB substitute for node 80's 20 MB slider. Other Klein NSFW
checkpoints to compare against SNOFS Merged: KleiNova v5.3 `3272968`, Miraclein v4.3
`3272965`, Moody Desire Mix v3.0 `3063794`.

**One flag carried forward:** `impressionism_klein9b.safetensors` (catalog row
`civitai:545264@2763568`) is spelled `ImpressionismKlein9b.safetensors` in the Civitai API.
Deliberately **not** changed — the lowercase spelling is also in the local
`~/.config/salad/studio-loras.json` extras row and is asserted by
`test_request_json.py:138`, so the catalog, extras and test must change together or not at all.

### 2.6 The author's own guidance (from the model descriptions, 2026-09-22)

Pulled from the Civitai API (the web pages now redirect to a mature-content site; the API
descriptions are intact). Three findings that revise the plan.

**There is no "v1.3 distilled" — v1.3 shipped base-only.** Klein versions of the merged
checkpoint (`2416142`), complete:

| Version | Name | Base |
| --- | --- | --- |
| `2985440` | **v1.4 Klein 9b Distilled** | Flux.2 Klein 9B |
| `2967967` | v1.4 Klein 9b Base | Flux.2 Klein-9B-base |
| `2836812` | **v1.3 Klein 9b Base** | Flux.2 Klein-9B-base |
| `2786085` | Distilled v1.2 Klein fp8 | Flux.2 Klein 9B | ← what we run |
| `2746781` | Distilled Klein 9b v1 | Flux.2 Klein 9B |
| `2716480` | v1.0 Klein 9b | Flux.2 Klein-9B-base |

The distilled line is **v1 → v1.2 → v1.4**; v1.3 was skipped for distilled. Cross-confirmed by
the HF mirror `edwixx/Flux2Klein9B_SNOFS`, which carries exactly two weights —
`…distilledV12Fp8.safetensors` and `…v13Base_BF16.safetensors`. So the community report
"v1.4 has an inverted penis head, 1.3 better" concerns the **LoKr** (`2818111`,
`klein_snofs_v1_3.safetensors`, ~1.02 GB), **not** a checkpoint. The v1.3 behaviour is reachable
**only** through the LoKr route — plain Klein unet + LoKr — which is open to us precisely
because ComfyUI reads LoKr natively (§2.3). Note our one test of that route
(`target/klein_ab/verify2.py` arms c/d) ran **4 steps at CFG 1 on a BASE model**, which is
mis-parameterised — base wants ~50 steps — so that route is **untested, not disproven**.

**v1.4 was depth-trained specifically for two people intermingled** — the strongest signal in
this document pointing at any single version. Verbatim, on the Klein v1.4 LoKr: *"training
against depth. Considering how much of SNOFS is two people intermingled with close skin colors,
it seemed like a novel idea. It did seem to rapidly help with that sort of thing."* (with the
caveat of *"a bit of a texture issue on very close up images"*). That is our exact failure class.
Counterweight, same author: *"I had versions that took it further but it tended to have more
broken anatomy"* — newer is not monotonically better, so v1.4 still has to be measured.

**The author documents a mechanism for making negative prompts work**, and it is cheaper than
NAG: a staged sampler. *"generate without the turbo lora for the first bit, which helps with
variation and prompt adherence, and then bump to a second stage with the turbo lora to keep
things fast. For the three-stage variation, you can then bump back to doing it without the turbo
lora for the last bit **if you want to use a negative prompt**."* Dropping the distillation LoRA
for the final steps escapes the CFG-1 regime where the negative is inert (§3, layer 3). This
belongs alongside NAG in Step 3.

**He explicitly warns against our LoRA stack:** *"please, for the love of god try SNOFS by
itself before you go adding a bunch of other general NSFW loras or models to it that screw up
anatomy."* Our chain is four LoRAs deep on top of SNOFS — which is Step 0(c).

---

## 3. Prompt craft (for the distilled CFG-1 regime)

Black Forest Labs' own skills repo (`black-forest-labs/skills`, pushed 2026-09-09) states the
rule and the rewrite recipe:

> "FLUX does NOT support negative prompts. Always describe what you WANT, not what you don't
> want" — with the example `"a portrait of a woman, no glasses, no hat, no makeup"` →
> `"a portrait of a woman with natural skin, clear face, bare head, visible eyes"`.
> Companion rule: "Negative prompts can actually make models focus MORE on unwanted elements."

Read with the refutation in mind: this is a strong default for CFG-1 distilled sampling, not
an absolute. The mechanism (naming a defect makes the model attend to it) is asserted by the
vendor but **not empirically demonstrated** — and our own positive prompt is the strongest
available anecdote for it:

> `LIMB OWNERSHIP: four legs and four feet in the whole picture, two legs and two feet for
> each figure, no more and no fewer; … each leg running from its own hip through its own
> knee to its own foot`

with node 67 enumerating `extra knee, third foot, two feet growing from one leg` — the
enumeration the hypothesis indicts, live in the positive node and dead in the negative one.

> **⚠ Correction (added when the plate audit landed — see §3.1).** The "enumeration summons
> the artifact" story is the vendor's asserted mechanism, **not demonstrated**, and **our own
> plates contradict it.** Limb counting appears in **16/16** of our studio plates, good and
> bad alike, and the strongest form — `four legs and four feet … no more and no fewer` — appears
> **only in the four plates that work**. Treat the deletion below as a cheap, harmless
> simplification, **not** as the identified cause. The cause is not yet identified; the best
> correlate in our sample is framing and shot scale, not limb counting.

**Is the negative prompt actually supported?** Do not read the vendor line as a technical
spec. Quoted verbatim, `core-principles.md` says *"FLUX does NOT support negative prompts"* and
presents it as universal ("apply to all FLUX models") — but the file mentions **no CFG, no
guidance scale, no distilled-vs-base distinction, no mechanism and no citation**, and the
companion `negative-prompt-alternatives.md` offers only the attention-drift rationale without a
technical condition. Adversarial verification **refuted the absolutist reading 1-2.** Keep three
layers apart:

1. **Plumbing — supported.** The graph wires a real negative encode (node 67) into a
   `CFGGuider` (node 63). Whenever `cfg > 1` the negative term is live; at cfg 1.5 it carries a
   third of the effective delta. The field is functional.
2. **Operating point — dead.** The recommended regime for the *distilled* cut is CFG 1 at 4
   steps, where the expression collapses to `pred = cond` and the negative contributes exactly
   zero. **The folk claim describes the recommended setting, not the architecture.**
3. **Efficacy — the layer that matters, and the one we measured wrong.** Our CFG grid ran
   1.2/1.3/1.5, i.e. the negative *partially on*, and the artifact survived. But **those runs
   carried the position blacklist**, so at cfg > 1 the negative was *live and actively pushing
   away from cowgirl, doggystyle and spooning* — the very positions that render. The grid is
   therefore evidence that **that** negative was useless-or-harmful, **not** that negative text
   cannot help. With the negative trimmed (Step 0), a CFG sweep above 1 is an **open
   experiment**, not a settled one. NAG remains the way to make negatives bite without leaving
   the few-step regime.

The meme most likely originates with FLUX.1 dev, which is guidance-distilled and driven by a
`FluxGuidance` scalar with **no negative text input at all** — a design Klein-in-ComfyUI does not
share, since it takes a CFG pair. Positively confirmed: negatives **do** work on the undistilled
**Klein Base** at ~CFG 4.5 / ~50 steps. **Untested by us:** how far above 1.5 the *distilled* cut
tolerates CFG before quality collapses — the degradation that motivates NAG in the first place.

### Rules to adopt

1. **Name the position in the model's own vocabulary** — `missionary`, `doggystyle`,
   `cowgirl`, `spooning`, `prone`. Short, affirmative, no geometry lecture.
2. **Prefer affirmative description to defect description** (BFL's rule, and a live concern if
   CFG or NAG is ever raised so the negative stops being inert). Deleting the limb-count line
   is **not established as a fix** — see the correction above — but it costs nothing and the
   line has no measured benefit, so drop it while testing more likely levers.
3. **Never blacklist a position** to steer toward another. If we want missionary, we ask
   for missionary; we do not forbid the other four.
4. **Keep style separate from act.** The `STYLE:` / `SUBJECTS:` / `POSE:` / `ANATOMY:` block
   structure from `target/klein_ab/pose_grid.py` is the working template.
5. Medieval background was **not researched** — see §8. Treat any background language as
   untested, and note that our current negative actively suppresses stylistic alternatives,
   which is a no-op at CFG 1 but becomes a live constraint the moment CFG or NAG is raised.

### 3.1 What our own plate audit found — and where it contradicts this doc

An audit of every retained plate landed after §2–§3 were written. Full table:
**`target/klein_ab/taxonomy.md`** (310 lines, gitignored). Method: plate `studio_<ms>.jpg`
pairs to the history row at `ts ≈ ms/1000 − 6s` (offset **+5.6…+7.4 s** held for 19 plates);
plates hashed — the 26 files in `art/salad_studio/` are only **16 unique images**, one
repeated **7×**; each unique image judged whole and at 2×–6× on pelvis, foot cluster and face.

| Finding | Result |
| --- | --- |
| **Act not depicted** (`ACT0`) | **11/16** — the *dominant* failure, and it is the user's own second reported failure mode |
| Limb ownership unreadable (`OWN0`) | **16/16** (11 severe, 5 mild) |
| **Extra foot / extra lower limb** | **0/16 confirmed**, 1 unconfirmed candidate — *no counted extra-limb case anywhere in our own sample* |
| Anything clean | **0/16** |
| Limb-counting language present | **16/16** — good and bad plates alike |
| `no more and no fewer` present | **only 4/16** — and those are plates that **work** (p ≈ 0.003, n=4 vs 12) |
| Negative defect enumeration | **inert**, with a natural control: plate #8 has no defect list, #9 has a long one; at 4× the leg region is structurally identical. **Zero effect** |

**What actually tracks the failures: framing, not limb counting.** The failures cluster on the
long bullet-listed scene-heavy rewrite — bullet format **7/7 fail** (vs 4/9 inline), a
castle/medieval setting block **6/6 fail**, both p ≈ 0.034. Those two features are collinear
with each other and with prompt length, so **which one is responsible cannot be isolated from
this sample.** The proposed mechanism is shot scale: the castle plates render the figures at
**25–30 % of frame** against **40–53 %** in the legible plates, and at 4 steps a wide shot
leaves the genitals too few pixels to form at all — which is exactly `ACT0`. This converges
independently with the research's step-count guidance ("4 steps is often insufficient for
anatomy in two-person scenes").

**The controls, corrected.**

- `pose_grid` (short prompt, named position, no limb count): **7/8 clean** — the reported
  result holds, **but the report missed a defect**: `doggystyle_s610296` has **three hands on
  the woman's back** (two sharing an unresolvable wrist plus a third with five clear fingers)
  where the man has two arms. I called that plate clean.
- `seed_sweep` (six seeds, long enumerating prompt): **0/6 carry any extra foot or extra
  limb.** At 6× the raised leg ends in **one** foot with five toes; every plate has exactly two
  planted female feet. **The claim in §7 that "the artifact survived six seeds" is not
  reproducible and should not be relied on.** What 3/6 *do* share is a raised limb whose
  attachment is hidden behind the man's body — a real ownership defect, but not an extra limb.

**Conflict — RESOLVED by the user's adjudication (2026-09-22).** Both plates were opened for the
user; their verdicts:

| Plate | User's verdict | Which reading it confirms |
| --- | --- | --- |
| `studio_1790054858096` (= `pose_grid/doggystyle_s610296`) | **"he has extra left arm"** | The audit's `XHAND` catch was **right** — I had reported this plate clean. Note the audit attributed the extra hand to *the woman's back*; the user attributes the extra **arm** to **the man**. Same feature, and the **owner attribution differs** — itself a finding, since a detector that cannot say *whose* limb it is cannot drive a targeted fix. |
| `studio_1790050883681` (byte-identical dup of `studio_1790050804107`) | **"she has wrong right leg"** | The **ownership/attachment** class (`OWN0`), **not** an extra-limb count. The audit's "raised limb whose attachment is hidden" was the right description; the earlier "extra leg" framing was mine and was imprecise. |

**So both defect classes are real and they are distinct** — an extra limb (the man's extra left
arm) *and* a misattached/mispositioned limb (her right leg). But the second is not a counting
error, and the fixes are not the same: an extra limb is a prompt/sampler problem; a wrong or
hidden attachment is a **framing/occlusion** problem. **Nothing in our sample is a duplicated
foot** — the extra-limb cases we have are in the **arms/hands**.

**Corollary for the audit's numbers:** `studio_1790050883681` was carried in the QC labelled set
as a **GOOD** plate. Per the user it is **BAD**, so one of the detector's true negatives was a
defect it missed — the measured VLM numbers below are **optimistic, not pessimistic**, and the
labelled set must be rebuilt on the user's verdicts before any future scoring (see §5.1).

**Limits — do not over-read this audit.** It is not a controlled experiment: bullet format,
castle setting, prompt length and the limb-count line all changed together, and the sample is
~**4 prompt generations**, not 16 independent trials. The plates are the *retained* ones —
selected on the outcome by the operator — so this bounds no failure *rate*. Labels are a single
visual read. What it licenses: limb counting is not the cause, negative enumeration is proven
inert, and the failure we most need to fix is often **framing**, not limbs.

---

## 4. Known failure modes on this model line (community-confirmed)

Reported on the SNOFS merged checkpoint and the sibling v1.4 LoRA page:

- Missionary — "like 95% chance of body horror"; cowgirl — "95% chance of getting reverse";
  spooning — "nothing but amputee body horrors".
- Doubled object in the mouth on an oral scene.
- Anatomy emerging from the navel or knee; feet deforming often.
- Inverted penis head on v1.4 (one user reports **v1.3 works better** — relevant because we
  run v1.2).
- "Hard whitewashed skin and faces that override character LoRAs"; dirty colours / yellow
  tint / excessive moles (a LoRA-conflict signature, not an anatomy one).

The practical reading: **the canonical positions are not equally hard.** Doggystyle rendered
for us; missionary-in-profile is the worst case. That is consistent, not contradictory, with
the community reports.

---

## 5. Auto-detecting distorted plates (the QC gate)

**Nothing shipped does limb QC.** `ComfyUI-QualityGate`'s only body-structure signal is a
head-width-to-shoulder-width ratio from four MediaPipe Pose keypoints (ears 7,8; shoulders
11,12). That ratio is geometrically **invariant to an extra limb**, and the node **fails
open** — when MediaPipe cannot detect a body it passes the whole batch through unmodified.
Its VLM prompt-adherence check is an unimplemented roadmap item (last commit 2026-07-08).

Credible **components** to build our own gate from, none of them a validated anatomy head:

| Option | What it is | Fit |
| --- | --- | --- |
| `Shimin/qwen3_vl_8b_foreagent` | LoRA SFT (r=16, α=32) of Qwen3-VL-8B, Apache 2.0, emits `{conclusion, confidence, reasoning}`; rubric criterion 2 is literally "Anatomical Integrity — hand/finger correctness, facial symmetry, body proportions" | **Closest fit.** Caveat: binary verdict, **no localization** — it cannot say *which* limb is wrong, and its axis is real-vs-fake, which is orthogonal for us |
| ICLR 2026 Semantic Visual Anomaly Detection (`arXiv 2510.10231`) | Taxonomy covers "missing limbs, extra fingers, two left hands, misaligned joints"; multi-agent pipeline, SemAP/SemF1 metrics, AnomReasonor-7B | Best **taxonomy** to borrow for the prompt; ships as a benchmark + self-fine-tuning pipeline, not a node |
| `FakeVLM` (NeurIPS 2025) | Detects synthetic/DeepFake images with natural-language artifact explanations | Discriminative axis is real-vs-AI — **every plate we render would be flagged**. FakeClue categories are facial tells, not limb topology. **No licence stated.** |
| `evalmedia` / `Kinburg-Nodes` Vision LLM Judge | Local VLM judge returning structured pass/fail against a user-written rubric | The *harness* pattern to copy; the rubric is ours to write |

**Design for our gate** (build cost is real — budget it as its own step):

> **⚠ The VLM-gate plan below was tested and FAILED. See §5.1 before building anything here.**

- One VLM call per plate returning strict JSON: limb inventory (4 limbs / 4 feet), per-limb
  hip→knee→foot continuity, owner attribution (whose leg is this), fused/merged bodies,
  act-present bool.
- Reject-and-retry on artifact.
- **Calibrate against a labelled set of our own good and bad plates before trusting it** —
  we have both classes on disk already: the user's verdicts on
  `studio_1790051031898` (bodies merged), `studio_1790054262826` (blurry),
  `studio_1790054254196` / `studio_1790054245296` (extra leg, two places),
  `studio_1790050883681` (penis correct, extra leg from the knee). No public
  anatomy-QC benchmark exists for this content class, and the false-reject rate is what
  decides whether the gate is usable.

### 5.1 Tested prototype — measured negative result

A prototype was built and scored against a **labelled set of 15 plates (12 BAD, 3 GOOD)**
(one entry was a byte-identical duplicate, so 12 distinct BAD). Deliverable:
`target/klein_ab/qc/anatomy_qc.py`, raw per-plate JSON in `target/klein_ab/qc/eval_*.jsonl`.

**⚠ The ground truth for that scoring was itself partly wrong.** The label set was built by
visual read, and the user's adjudication (2026-09-22) found a **GOOD** plate in it —
`studio_1790050883681`, "she has wrong right leg" — that is actually **BAD**. So at least one of
the detector's true negatives is a defect it missed: the measured figures are **optimistic**,
and the negative verdict is if anything **understated**. The label set must be rebuilt on the
user's verdicts (now in `target/klein_ab/qc/ground_truth.md`) before this is scored again.
This is the same failure mode as the 4-image probe, one level up: the *ruler* was miscalibrated,
not just the sample small.

| Backend | TPR | FPR | Verdict |
| --- | --- | --- | --- |
| VLM (local Ministral-3-8B, 156 grounded questions) | **25 %** | **33 %** | unusable |
| Heuristic (no model) | **0 %** | **33 %** | unusable |

**Asking a VLM to count or trace limbs does not work.** Both an 8B and a 27B returned
*"4 limbs, no extra limb, 9/10, defect: none"* on the leg-over-the-shoulder plate **and** on
the missionary extra-leg plate. This matches the published finding that GPT-4o and LLaVA score
≈50 % AUC on this task and **rationalize instead of detecting**. Two further failure modes
worth knowing: a **fail-open** path — 9 of 156 questions returned an *empty* reply because the
reasoning model exhausted its token budget, and those silently became "no defect", which is
how the clearest bad plate in the set (`studio_1790051031898`) escaped — and **false
positives on good plates** (one clean doggystyle plate was flagged by both backends).

**A warned-against trap, recorded because we fell into it:** a 4-image probe of the one
question that seemed to work scored **4/4** and was nearly reported as a working detector; on
the full set it scored **3/12**. The small sample lied. Do not calibrate this on a handful of
plates.

**The right architecture is a pose model, not a VLM** — and we do not have one. The cheapest
real path is `rtmlib` RTMPose/DWPose ONNX (~25–55 MB, Apache-2.0, ~17–30 ms/image), needing a
heuristic layer over the skeleton (per-instance bone-length ratios, cross-instance bbox IoU as
a fusion signal, low-confidence hand/foot keypoints). Two constraints: its opencv-contrib
dependency is a risk against the ambient `cv2` 5.0 (which lacks `ximgproc`), and **pose
skeletons are fixed-cardinality — they cannot report "three arms" directly**, only via derived
signals. `ultralytics` YOLO-pose needs the ComfyUI venv's torch and is AGPL. The paper that is
*exactly* this task (HADM: 37.5k images, 84.8k limb labels) needs Detectron2 + torch 1.12 +
Python 3.8 with no ONNX export and is therefore unusable — **but its dataset is the best
available calibration set.** SAM2 / GroundingDINO / CLIPSeg can verify a region, not count limbs.

**Recommendation: do not wire this as auto-reject.** At 25 % TPR / 33 % FPR it would throw away
one clean plate in three while passing three quarters of the broken ones. Wire it as a
**ranking** signal only — the top-N plates of a batch go to a human — and spend the effort on
the pose backbone instead. Reject-and-retry should follow the shape of
`regen_bodies.py:cutout_ok`, not a one-shot report.

**Environment facts (measured, and they correct an earlier claim of mine).** The interpreter
`scripts/run-gates.sh` resolves from PATH is `C:\Python314\python.exe` (3.14.7) and it already
has **numpy 2.5.2, cv2 5.0.0, onnxruntime 1.29.0, PIL 12.3.0** — so a cv2-based detector costs
**zero install**. (The accurate statement is that no *repo file imports* them; they are
present regardless.) Missing there: `torch`, `ultralytics`, `mediapipe`, `scipy`, `skimage`.
Separately, `C:\Users\vkozy\Documents\ComfyUI\.venv` (Python 3.12.11) **does** have
`torch 2.9.1+rocm7.2.1`, torchvision, scipy, timm, onnxruntime 1.25.1 — but every model
directory is empty and there is **no pose or anatomy ONNX anywhere on disk**. The only usable
vision weights are the two local LM Studio VLMs, both of which failed the test above. 32 cores,
102 GB RAM, no CUDA.

---

## 6. Next-session plan — the ordered ablation ladder

Each step is **single-variable** against a held baseline (seed, graph, LoRA chain, 832×1216,
euler, 4 steps, CFG 1 unless the step says otherwise). Do them in order; stop at the first
step that clears the artifact rate, and re-shoot the position matrix at the end regardless.

**Step 0 — three free prompt/graph changes (do first).**
**(a) tighten the shot** — drop the castle/scene block and the bullet-list format so the two
figures fill **40–50 % of frame** instead of 25–30 %. That is the counted discriminator between
plates that render the act and plates that do not, and at 4 steps it is plausibly a
pixel-budget problem. **(b) trim** — delete every limb-count from node 74 and the position
blacklist from node 67 (cheap, not established as a fix; see §3.1). Templates:
`target/klein_ab/pose_grid.py` `STYLE`/`SUBJECTS`/`ANATOMY`/`NEGATIVE` — note those plates are
already tight-framed and setting-free, which is likely the real reason they rendered.
**(c) strip the LoRA stack — ✅ DONE, NEGATIVE. Not a cause; do not spend more on it.**
Harness: `target/klein_ab/lora_ablation.py`. `full` (4 LoRAs) vs `alone` (none) at 3 seeds each,
everything else held, baseline verified byte-identical to production. **Both arms bad** — the
user's verdict is "none of the rendered plates are good", so the author's "try it by itself"
remedy does not work here. (`style` and `anat` arms were lost to a replica 524, but they can
only refine *which* LoRA is at fault, and the answer is now "none of them individually matter
enough".) See §1.1.

**Step 1 — the unet upgrade, in two single-variable moves.**
Note the original form of this step bundled **two** changes (v1.2→v1.4 *and* fp8→bf16), which
violates the ladder's own discipline. Split it:

- **1a — v1.2 → v1.4 at fp8 held constant.** Swap node 70 from the v1.2 fp8 unet we run to
  **version `2985440` fileId `2867344`** (fp8, 8.46 GB — same size class, so it cannot be a
  container-budget story). This isolates the *version*.
- **1b — then fp8 → bf16.** Swap to **fileId `2865386`** (bf16, 16.91 GB). This isolates the
  *precision*, which is where the author's anatomy claim lives.

Hold seed, steps, sampler, LoRA chain and prompt; re-shoot the failing missionary seed each
time. **Check the bf16 build fits the Salad container budget alongside the 4-LoRA chain**
before 1b; if it does not, the fallback is the fp8 v1.4 result plus a decision on
selective-precision (embeddings/modulation/norms/output head in BF16).

**Step 2 — position matrix, two prompt regimes.**
Fixed seed × {doggystyle, cowgirl, missionary, spooning, prone} × {trimmed prompt, shipped
prompt}. This tests position-vs-prompt directly and produces the artifact *rate* table we
have never had. Harness exists: `target/klein_ab/pose_grid.py`.

**Step 3 — make negative text bite, cheapest thing first.**
**3a (cheap, do first):** with the negative *trimmed* (Step 0), sweep CFG **above** the 1.5 we
tested — 2.0, 3.0, 4.5 — and watch where image quality collapses. Our earlier 1.2–1.5 grid was
run with the position blacklist live and is therefore not evidence about negative text in
general (see §3, layer 3). This is a config change, not a new node.
**3b (only if 3a shows negatives help but CFG hurts):** `ComfyUI-NAG` (or the
`ComfyUI-NAG-Extended` fork, which explicitly supports Flux 2 Klein) restores negative
prompting in few-step/guidance-distilled models by attention-feature extrapolation
(`Z = Z+ + φ·(Z+ − Z−)`), **not** by raising CFG. Costs: flagged experimental, roughly
**double per-step cost** (disables the CFG-1 optimization), and published work reports
image-quality collapse under strong negation. Raise `nag_scale` from low, quality-watched. The
other alternative: the undistilled **base** model regains a real negative channel at ~CFG 4.5 /
~50 steps.

**Step 4 — weights, once the prompt is clean.**
Anatomy fixer 2.0 vs 3.0 with the trimmed prompt (the earlier 3.0 sweep was measuring the
bad prompt). Separately, test the detail slider's **−1.5 inversion** — node 80 runs a concept
slider at negative weight, which inverts whatever the slider encodes and has never been
justified.

**Step 5 — an anatomy QC gate, but a pose-model one, not a VLM one.**
The VLM route was tested and failed (§5.1: 25 % TPR / 33 % FPR; both local VLMs answered
"4 limbs, no extra limb, defect: none" on broken plates). Build instead on a pose backbone
(`rtmlib` RTMPose/DWPose ONNX) with a heuristic layer, calibrated on the HAD dataset, wired as
a **ranking** signal that surfaces the top-N plates for human review — **not** as auto-reject.
Budget real effort here; this is the least mature part of the stack.

**Discipline that made the difference, keep it:** one plate per config is a lottery — a third
leg is per-seed. Score with a **6-seed labelled contact sheet** and **present the sheet to
the user**; do not sign off on anatomy from my own read (it has already passed both a
missing act and a third leg).

**Constraints for next session:** generation requires the Salad GPU to be up (it was shut
down deliberately for the night). The render harness is
`salad_studio.generator.generate_from_payload(...)` with gateway/key read from
`~/.config/salad/` — never print, echo, or commit those. Do not download weights without
asking. Do not commit images (CI `.github/workflows/tier1.yml` rejects any
`.jpg/.png/.webp/.gif/.pak`); keep renders under gitignored `target/`.

---

## 7. Work that this doc invalidates

- `docs/workflow/15-salad-flux2-klein-group.md` §"Two-body plate recipe" — claims "the prompt
  architecture is the quality lever, and the graph is not" (wrong framing: the *position* is
  the lever), documents the 6-step config, the penis LoRA at node 81, and `_meta` retargeting
  the encodes. Rewrite from §2–§3 of this doc.
- `salad_studio/test_klein_recipes.py` — 24 tests asserting the old 6-step recipe,
  penis LoRA at 81, `_meta`, encodes on the tail. Must be rewritten.
- `salad_klein/README.md` — stale.
- `target/klein_ab/make_recipes.py` and the two regenerated-but-uncommitted recipe files
  (`prompt_snofs_distilled_anatomy.json`, `_resms.json`) — they carry the row-1790050878
  missionary prompt that the user has rejected for the extra leg. Superseded by Steps 0–2.
- Commit `1c1ac38a` on `salad-studio-audit-catalog-assist` is **wrong on the branch**
  (cuddle prompt, penis LoRA at 81, 6 steps). PR #61's §4 body describes the disproven
  recipe and needs a third rewrite.
- The old doc claim "Every weight held at every seed… The fixer's effect here is preventive,
  not visible" — replaced by **"the seeds did not fix it"**. Note the audit could **not**
  reproduce an extra foot in any of the six seed-sweep plates (§3.1), so the honest form of
  this claim is that the seeds did not fix the *ownership* defect — the extra-limb count claim
  is unsupported by our own sample.

---

## 8. Gaps and open questions

- **Medieval background: un-researched.** It was a stated deliverable of the research pass and
  **no claim about it survived verification.** Treat as open, not settled.
- **Does bf16 remove the *extra-leg* artifact, or only improve fingers?** The author's
  recommendation is about finger count; the extra-limb reports are attached to the fp8 build
  but this is inferred **by artifact class, not measured on our exact file.**
- **Version drift is a real hazard.** We run SNOFS distilled **v1.2** fp8 while most evidence
  is attached to v1.4 (fp8 caveat) and v1.3 (one user: inverted penis head on 1.4, "1.3 works
  better"). SNOFS merged checkpoint was updated **the day of this research**; the line is
  moving fast. **Re-verify model availability before the next session** rather than trusting
  this snapshot.
- **Is there a position-specific Klein 9B LoRA or checkpoint** trained on
  missionary/cowgirl/spooning compositions — rather than a generic anatomy slider? And is
  there any Klein NSFW checkpoint whose comments do **not** carry the 95%-body-horror
  missionary reports?
- **Does NAG actually reduce the extra-limb rate at 4 steps**, at what `nag_scale` does it
  start costing quality — and is the negative prompt even the right lever once position and
  bf16 are fixed?
- ~~Which VLM configuration is the best auto-reject head?~~ **Answered — none.** Both local
  VLMs failed to detect the defects at all (§5.1); the open question is now which **pose
  backbone** (`rtmlib`/DWPose vs YOLO-pose) and which derived skeleton signals best rank a
  batch, and how to calibrate on the HAD dataset without Detectron2.

---

## 9. Sources

Primary:

- SNOFS merged checkpoint — `https://civarchive.com/models/2416142/...?modelVersionId=2985440`
  (and `https://civitai.com/models/2416142`)
- SNOFS v1.4 LoRA page — `https://civarchive.com/models/1972981`. **Corrected
  2026-09-23:** this page is a **list of trigger terms that work** (missionary /
  doggystyle / cowgirl / prone / reverse cowgirl / spooning position, plus notes
  like *"cunnilingus (be specific and maybe put kissing in the negative prompt)"*).
  It reports **no per-position failure rates** — it was previously labelled here
  as "(position failure reports)", which it is not.
- Klein Anatomy / Quality Fixer — `https://civitai.com/models/2324991/klein-anatomy-quality-fixer`
- BFL prompt-craft rules — `black-forest-labs/skills` → `flux-best-practices/rules/`
  (`core-principles.md`, `negative-prompt-alternatives.md`), `https://docs.bfl.ml/guides/prompting_guide_t2i_negative`
- ComfyUI Klein guide — `https://docs.comfy.org/tutorials/flux/flux-2-klein.md`
- NAG — `https://github.com/ChenDarYen/ComfyUI-NAG`, `https://arxiv.org/abs/2505.21179`,
  fork `https://github.com/BigStationW/ComfyUI-NAG-Extended`
- diffusers LoKr bug — `https://github.com/huggingface/diffusers/issues/13261`,
  PRs `#13997` (closed unmerged), `#14163` (open)
- fp8 anatomy reports — `https://huggingface.co/black-forest-labs/FLUX.2-klein-9b-fp8/discussions`
- QC tooling — `https://github.com/nobu1990/ComfyUI-QualityGate`,
  `https://huggingface.co/Shimin/qwen3_vl_8b_foreagent`, `https://arxiv.org/abs/2510.10231`,
  `https://github.com/opendatalab/FakeVLM`
- LoRA optimizer stacking hazard — `https://github.com/ethanfel/ComfyUI-LoRA-Optimizer`
- `https://myaiforce.com/flux-2-klein-anatomy-horror/` (step-count guidance; secondary)

Our own artifacts behind the measurements:

- `target/klein_ab/cfg_grid.py`, `seed_sweep.py`, `pose_grid.py`, `verify2.py`, `make_recipes.py`
- contact sheets: `target/klein_ab/sheets/{shipped,poses}.jpg`
- user verdicts on the saved plates: `studio_1790051031898`, `studio_1790054262826`,
  `studio_1790054254196`, `studio_1790054245296`, `studio_1790050883681`
