# 19 — Two-body prompt playbook (what produces a usable plate)

**Started 2026-09-22.** Companion to doc 17 (why Klein failed for two-body acts) and doc 18 (the
SDXL question). The machine-readable form is **`salad_klein/prompt_ledger.json`** —
that file is canonical for the prompt text; this doc explains what the entries have in common.

**Scope:** 18+ adults only, two adults, no minors, nothing illegal.

---

## 1. Why this exists

Everything before tonight produced **zero** acceptable two-body plates — 22 judged, none good — and
the cause was misdiagnosed four times (LoRA stack, LoRA download, prompt enumeration, prompt
length). Two things were actually wrong, and neither was the wording:

1. **Three unets in one container group thrashed VRAM**, turning 3-second renders into 240–576 s
   that no gateway would wait for. Fixed by routing one unet family per group (doc 17 §1.1).
2. **A template shipped as a prompt.** `prompt_snofs_distilled_v12.json` carried the literal
   `REPLACE_THIS_PROMPT`, so a "successful" 0.9 s render was a picture of that word.

With both fixed, renders are **1–4 s** and acceptable plates arrive at roughly **2 in 7 seeds**.
So the work now is not "find a working prompt" — it is **collecting which prompts work and
knowing that selection, not wording, is what you spend effort on.**

## 2. The verified configuration

`salad_klein/prompt_snofs_distilled_v12.json`, run on the **SNOFS group**
(`flux2-klein-5090`, image `…prefetch6-snofs`):

| | |
| --- | --- |
| unet | `snofsSexNudesAndOther_distilledV12KleinFp8.safetensors` |
| clip / vae | `qwen_3_8b_fp8mixed.safetensors` (flux2) / `flux2-vae.safetensors` |
| sampler / steps / CFG | euler / **4** / **1** |
| size | 832 × 1216, batch 1 |
| LoRAs | **none** |
| prompt / negative | 779 chars / 111 chars |

**Acceptable seeds: `323175253610296`, `610044882331`.** Five others judged bad
(`114772190455233`, `924411309871006`, `782300144559`, `555100233771`, `410299187654`).

### The replacement, stated explicitly

`prompt_snofs_distilled_v12.json` node **74** previously contained the literal string
**`REPLACE_THIS_PROMPT`** — so every render of that recipe drew the word, not a scene. Node 74 now
contains the prompt quoted below, and node **67** (previously empty) holds the negative below. That
text produced these two user-approved plates:

| plate | seed | user's verdict |
| --- | --- | --- |
| `target/snofs_variants/V1_knees/studio_1790112819749.jpg` | `323175253610296` | *"v1_knees is the best — all other are bed"* |
| `target/snofs_v1_seeds/s882331/studio_1790113204549.jpg` | `610044882331` | *"s882331 — is the best; all others are bed"* |

Both are recorded under `replacements` in `prompt_ledger.json`, where the `now` field is copied
from the recipe so it cannot drift from what was actually run.

### The prompt, verbatim

```
STYLE: ArsMJStyle, Impressionism, oil painting on canvas, visible expressive brushstrokes,
dappled natural light, soft impressionist colour, crisp readable painted detail, clean edges
on the figures.

SUBJECTS: exactly two nude figures, one woman and one man, two clearly separate bodies, both
fully in frame.

POSE: missionary position, clean side view in profile. She lies on her back, head on a pillow,
knees bent and drawn up, thighs open to either side of his hips, feet on the mattress. He lies
over her between her thighs, chest low over hers, weight on his forearms beside her shoulders,
hips between her thighs. His knees rest on the mattress between her thighs, his shins flat
behind him.

INTIMACY: penis inside her vagina, his hips against hers, joined at the pelvis.
```

Negative (short, style-only — inert at CFG 1, and that is fine):

```
NEGATIVE: blurry, low detail, distorted anatomy, fused bodies, censored, watermark, text,
signature, 3d render.
```

## 3. What leads to a prompt like this — each rule and the evidence for it

**State the act directly.** `INTIMACY: penis inside her vagina, his hips against hers`. The plate
audit found **`ACT0` — act not depicted — in 11 of 16** earlier plates. That was the *dominant*
failure all along, not limbs, and it is a wording problem: nothing in those 5,049-char prompts said
what the bodies were doing together.

**Name the canonical position rather than describing geometry.** `missionary position, clean side
view in profile` — the model has these compositions; prose geometry does not substitute. SNOFS's
own model page lists the position terms that work (`missionary` / `doggystyle` / `cowgirl` /
`prone` / `reverse cowgirl` / `spooning position`), which is why naming the position is worth doing.

> **Corrected 2026-09-23.** This paragraph previously claimed that "community reports on this
> model line rate the positions very differently (**missionary worst, doggystyle best-rendered**)".
> That claim had **no source**: it is not in either SNOFS model description, and the Civitai
> comments endpoints are refused to an unauthenticated fetch. Do not cite it. The verifiable
> statement is only that the SNOFS page publishes a list of position terms it was trained on.

**Describe BOTH bodies' limbs, each with a specific posture.**
This is where the one measurable prompt win came from. The control described her legs in three
clauses and said **nothing** about his; his left leg split at the knee. Adding one clause —
*"His knees rest on the mattress between her thighs, his shins flat behind him."* — was judged
**"the best"** of five variants at a fixed seed.

**But the posture wording matters, not merely "mention his legs."** The first attempt at the same
idea — *"His legs stretch back behind him along the mattress, knees and shins resting flat, one leg
to either side of her hips."* — **broke her legs** at both seeds. Stripping both leg descriptions
broke her too. So: a specific, physically coherent posture per body; not a generic "his legs are
also there", and not less description.

**Keep it short and affirmative, and never enumerate.** No limb counts, no defect words, in either
polarity. Caveat on the evidence: our own plate audit found limb counting in 16/16 plates and the
strongest counting language in the *only four that worked*, so this rule is **not** proven to fix
anything — it is cheap, it follows the vendor's guidance, and it removes a confound. Treat it as
hygiene, not as the cure.

**Always carry the style block.** `ArsMJStyle, Impressionism, oil painting on canvas…` was held
constant across every good plate; it costs nothing and it is what makes the output the house look.

**Negative prompt: short, style-only.** At CFG 1 the negative is mathematically inert
(`pred = uncond + cfg·(cond − uncond)` collapses to `pred = cond`), so the old 3,649-char defect
list did nothing — while listing `cowgirl, doggy style, rear entry, spooning` as *suppressed*,
i.e. forbidding the positions that render. Keep it short; revisit only if CFG is ever raised.

**Expect the seed to dominate — roughly 2 in 7.** This is the most important practical finding.
The winning prompt produced acceptable plates at 2 of 7 seeds, and the *same* prompt at seed
`455233` failed differently (her leg plus crossed palms). **Do not iterate wording looking for a
cure.** Batch seeds and select.

## 4. What does NOT work — do not retry

| Approach | Result |
| --- | --- |
| Enumerating defects in the positive prompt (`four legs and four feet … no more and no fewer`) | Present in **16/16** plates, good and bad alike; strongest form appeared only in the plates that *worked*. Not the cause. |
| Enumerating defects in the negative | **Proven inert** at CFG 1, with a natural control (one plate without a defect list, the next with a long one — structurally identical). |
| Raising CFG to 1.2 / 1.3 / 1.5 to make the negative bite | Artifact survived. (Note those runs carried the position blacklist, so they are not evidence about negatives in general.) |
| Anatomy fixer LoRA at 2.0 and 3.0 | Artifact survived. |
| Stripping the LoRA stack (author's own advice: "try SNOFS by itself") | `full` (4 LoRAs) vs `alone` (none): **both bad**. Not the cause. |
| Longer / more detailed prompts (5,049 chars, bullet sections) | The bullet-format, scene-heavy rewrite is where the failures clustered (7/7), collinear with a castle setting block (6/6) and with shot scale — the plates that rendered put the figures at 40–53 % of frame, the failing ones at 25–30 %. |
| Changing wording to chase a clean plate | Prompt fixed after one controlled win; 5 of 7 seeds still bad. Selection beats iteration. |

## 5. The workflow

1. **Batch seeds, don't tweak prose.** Generate ~12 seeds on a settled prompt (~3 s each, so ~40 s
   for a sheet) and review it as a labelled contact sheet.
2. **A human judges.** This session's own QC work showed why: a VLM asked to check anatomy scored
   25 % TPR / 33 % FPR and called broken plates clean, and my own reads missed a missing act, a
   third leg, an extra arm and a wrong leg. At 3 s per plate, a person picking from a sheet is
   strictly better than any detector we measured.
3. **Record the verdict in the ledger, good or bad.** A prompt is only "good" because a human said so.
4. **Watch the operational preconditions** (§2 graph, one unet family per group, routing in Studio).
   Without them plates 524 and the prompt question is moot.

**Known hazard:** `comfyui-api` (the HTTP wrapper) **wedges on `/prompt` after a run of renders**
while still answering `/ready` 200. Observed after ~8 sequential renders: Comfy logged nothing for
the new requests and the client timed out. Recovery is an instance reallocate. So keep batches
modest, and never trust `/ready` alone as "can serve a prompt".

## 6. The researched recipe — CANDIDATE, not yet verified

**Source: the user's own research, 2026-09-22** (model cards, working gallery metas, MyAIForce,
MatchingPose/RefControl, Ashen3's notes, depth-training notes, cinematography framing). Recorded
here verbatim where the wording matters, because the prompts are paste-ready. **Status: being
tested — no plate from this recipe has been judged by a human yet, so it is NOT in the
`verdicts` list of `prompt_ledger.json` (it sits under `candidates`).**

### 6.1 The framework

> Use full sentences, not tags. **Camera → who is who → named position** (`missionary position`,
> `doggystyle position`, …) → **one limb action each with left/right ownership** → **clinical
> genitals** (`penis` / `vagina`) → **light/setting**.

**This directly contradicts our verified operating point**: it says run **Klein 9B Base** for sex
T2I, *not* the distilled 4-step cut — *"distilled is for edits; author and testers both say Base has
far fewer anatomy horrors."* Our verified plates are the SNOFS-merged **distilled v1.2** unet at
CFG 1 / 4 steps. That is the contradiction the test run resolves. Note the routing consequence:
Base is family `klein`, so these plates belong on the **klein** group, not the SNOFS group.

### 6.2 Settings that work

| Knob | Aim |
| --- | --- |
| Model | **Base 9B** |
| SNOFS | **0.8–1.0** alone; if stacking realism/anatomy ~**0.3–0.5** |
| Steps | **30–50** (showcase often 50) |
| CFG | ~**4–5** on Base |
| Sampler | Euler + Flux2 scheduler; if melt → `res_2s` / `res_multistep` |
| Res | ~**1.0–1.5 MP** first (e.g. 1024×1536), then upscale |
| Helpers | Anatomy Fixer **2–3**; Male Anatomy + the word **`penis`** (never slang) |

### 6.3 The proposed template

```
A [CAMERA: side-view / high-angle / low-angle POV / three-quarter] photograph of [WHO_A] and
[WHO_B], both clearly separate adult bodies,
having sex in the [POSITION: missionary position | doggystyle position | cowgirl position |
spooning | blowjob].
[LIMBS: her L/R hand does X; his L/R hand does Y; knees/feet — one action per limb].
[ACT: his erect penis inserted into her vagina / in her mouth — clinical words].
[OCCLUSION: far-side limbs partially occluded but readable; one clear figure plane].
[FRAMING: medium / three-quarter / head-to-knees].
[SETTING + LIGHT]. Sharp focus, anatomically correct, no extra limbs.
```

### 6.4 Paste-ready prompts

**Missionary**

```
A high-angle photograph of two adults having sex in the missionary position on a bed with white
sheets. The woman lies on her back, holding her own knees apart so both of her legs are clearly
visible and separate. The man is between her legs, his hips between her thighs, one hand on the
bed beside her shoulder. His erect penis is inserted into her vagina. Camera looks down from above
their torsos so both bodies stay on one clear plane, natural window light, sharp focus on hips and
legs, no extra limbs.
```

**Doggy (side — safer than overhead)**

```
A side-view photograph of two adults having sex in the doggystyle position. The woman leans
forward over the edge of a sofa, back arched, knees on the cushion, both of her legs clearly
visible. The nude man kneels behind her, both hands gripping her hips, his erect penis penetrating
her vagina from behind. Three-quarter profile so the far-side limbs are partially occluded but
readable, one clear silhouette, soft daylight, full bodies from head to knees in frame.
```

**Cowgirl (low POV)**

```
A low-angle photograph from the man's perspective of a woman having sex in the cowgirl position.
She straddles him, knees planted on either side of his hips, both of her thighs clearly separate.
Her hands rest on his chest. His hands grip her buttocks. His erect penis is visible penetrating
her vagina. Paneled ceiling above her, sweat on her skin, sharp anatomy, no fused bodies.
```

**Blowjob (pause — fewer limbs)**

```
A close-up photograph of a topless adult woman pausing during a blowjob. She kneels on a bed,
mouth open, looking forward. Thick strands of saliva stretch from her extended tongue to the glans
of the man's erect penis in the foreground. Only one penis and two of her hands are visible; her
hands rest on his thighs. Soft bedroom light, sharp focus on mouth and penis.
```

### 6.5 Negatives and don'ts

```
extra limbs, fused bodies, merged torsos, twisted joints, bad anatomy, malformed hands,
duplicate limbs, intertwined bodies, body horror
```

Plus SNOFS quirks: **`goosebumps`** in the negative if close-ups get weird texture (v1.4
depth-training artifact), and **`kissing`** if cunnilingus drifts.

**Avoid:** distilled 4-step for complex sex; slang-only tags; *intertwined / tangled*; conflicting
arm verbs; ultra-tight crops; starting above ~2 MP before anatomy locks.

### 6.6 Three finds worth keeping

- **Depth training.** SNOFS v1.4 was trained against depth *because two similar-skinned bodies
  blend* — which is exactly our "fused bodies" failure. (Consistent with doc 17 §2.6, where the
  author says v1.4's depth training "rapidly helped" with two people intermingled.)
- **Lock the pose first.** Mannequin → `matchingpose9b`: fix the pose, then describe sex/clothes in
  text and *do not re-describe the pose*. Add SNOFS on Base, or as an edit.
- **Film/photo language beats tag soup.** Pull the camera back, side or three-quarter, "one clear
  silhouette", **one verb per limb**. Same discipline as cinematography blocking — and it matches
  our own audit finding that shot scale was the best-supported correlate of failure.

### 6.7 Stack order for our plates

```
Base + SNOFS alone
  → if glitch: Fixer 2–3, or res_2s
  → male issues: Male Anatomy + the word "penis"
  → hard poses: mannequin/MatchingPose, or DWPose RefControl
  → then upscale
```

### 6.8 Comfy recipe cards — `docs/workflow/20-comfy-klein-snofs-recipe-cards.md`

The full write-up (21 KB, **copied verbatim into the repo**) adds four position cards — missionary,
doggy side, cowgirl low-POV, blowjob pause — plus an optional standing-doggy / prone mini-card.
Each carries its positive prompt, negative additions, LoRA weights, an *"if limbs broke"* fallback
ladder and a wiring checklist. It also has a ROCm/AMD section, a download table, and an explicit
uncertainties list.

**Its most useful part for us is the "corrections vs Flux.1 habits" table, because it validates our
plumbing:**

| Flux.1 habit | Klein (official) | us |
| --- | --- | --- |
| `DualCLIPLoader` (T5 + CLIP-L) | `CLIPLoader` with `type=flux2` + Qwen3-8B | already do ✓ |
| `EmptyLatentImage` | `EmptyFlux2LatentImage` | already do ✓ |
| `FluxGuidance` + KSampler CFG=1 | **`CFGGuider` holds CFG**, + `Flux2Scheduler` + `SamplerCustomAdvanced` | already do ✓ |
| `ModelSamplingFlux` | not used in the official T2I template | already do ✓ |
| distilled 4-step for everything | **BASE** for complex sex T2I; distilled for edits/previews | ← the one real divergence |

Four of the five corrections describe the graph we already run. **So none of this session's four
wrong diagnoses was a plumbing error** — the divergence is purely the operating point (Base vs the
SNOFS-merged distilled cut, CFG 4.5 vs 1, 40 steps vs 4). That is what the test run resolves.

**Shared defaults:** steps **40**, CFG **4.5**, SNOFS **0.9** alone (or **0.45** when stacking
Fixer **2.5** + Male **0.8**), batch 1, Stage-A ≈ 1–1.5 MP then upscale. Latent presets:
missionary/cowgirl `1024×1536`, doggy side `1280×960`, blowjob `1024×1280`.

**Its "limbs broke" cheat sheet:** euler → `res_2s` / `res_multistep`; SNOFS ↓ to 0.35–0.5 with
Fixer ↑ to 3.0; CFG **4.0** (not 6+); simpler camera / more body in frame; pose lock (MatchingPose
or RefControl DWPose); Stage-A at ~1 MP, fix, then upscale.

**Uncertainties to carry (its §7), not assume:** the official template ships **4B** filenames and
the 9B swap is manual; the `res_2s` class name varies by custom-node pack; MatchingPose's Mannequin
companion HF page appeared renamed when fetched; **Male Anatomy's primary host is PromptHero, not
Civitai**, and is alpha; SNOFS on Civitai may need `civitai.red` for mature files. Anything the
document marks *"verify in your build"* has **not** been checked against our Salad image
(`api1.19.2`), which is where these plates actually run.

## 7. Adding to this playbook

Append to `prompt_ledger.json`, never overwrite: put the working prompt in a recipe file first and
let the ledger copy it, so the recorded text cannot drift from what was run. An entry needs the
graph, the verbatim prompt and negative, the seeds judged, and the **user's own verdict words**.
Prompts judged bad go in the same ledger — the rejected list is what stops a future session
retrying a dead end.

An entry I add must say who judged it. If nobody has looked at the plate, it is not an entry.
