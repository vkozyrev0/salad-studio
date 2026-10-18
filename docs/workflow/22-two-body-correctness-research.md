# 22. Can we get anatomically correct two-body scenes *every time*?

**Status: an external research record, not a decision.** Two independent
deep-research passes ran on **2026-09-23** against the question *"we need our sex
scenes to be perfect, anatomically correct, every time"*. Both returned
**Partial**. Coverage gaps remain and are listed in §7. This document records
what they found, with the sources they cite, so the next session does not
re-derive it.

Companions: [`21`](21-klein-image-handoff.md) (what we run today),
[`§9`](#9-anatomy-research) (why Klein fails at two-body acts),
[`§10`](#10-the-sdxl-migration-premise) (the SDXL premise), [`21 §9`](21-klein-image-handoff.md#9-two-body-prompt-playbook).

**Scope:** 18+ adults only, two adults, no minors, nothing illegal.

**Citation convention:** every `[n]` resolves to §8. The two source reports used
overlapping `[S…]` labels for *different* sources, so this document renumbers
everything into one sequence.

---

## 1. The headline

Three findings, and both passes converge on all three.

1. **No diffusion configuration in either family is documented as guaranteeing
   anatomically correct two-body interlock.** No source either pass inspected
   publishes a measured per-scene seed hit rate or a two-body anatomy benchmark.
   The numbers that circulate, *"~20 % unwanted second male"*, *"vaginal ~50 %
   of the time when anal was requested"*, are author and user anecdotes, not
   measurements, and the passes say so.
2. **The only route where interlocked anatomy is correct *by construction* is
   3D**. A DAZ figure taken through Blender (geograft weld → render →
   composite), or an engine with hand-keyed penetration. Diffusion is then
   reserved for styling and aftereffects.
3. **The one code-verified mechanism for keeping two partners' features from
   bleeding together targets our current family, not SDXL.** Masking each
   regional LoRA's activation delta to its own box, so it multiplies to zero
   everywhere else, is implemented for **Krea 2 / Flux.2-Klein** and explicitly
   refuses adapters trained for a different base architecture [18]. An
   SDXL/Illustrious stack therefore **cannot** use it and is left with regional
   prompting, which reduces cross-contamination rather than eliminating it.

The practical reading for this repo: the answer to "every time" is not a better
diffusion config. It is either *accept the seed lottery and select* (what doc 21
§1 already does, 2 of 7 seeds), or *move the anatomy to 3D*.

---

## 3. The SDXL / Illustrious route

### 3.1 Salad Cloud does not stock the models this route needs

What Salad stocks and the custom-image escape hatch: the official Comfy recipe list is doc 14 §1 —
the `Official Salad Comfy recipes` row at `docs/workflow/14-salad-comfy-live-findings.md:37`
(Dreamshaper 8, FLUX.1-Dev, FLUX.1-Schnell, SDXL, SD 3.5 Medium, **not** Krea 2); the custom image
that carries the rest is doc 23 §1.

### 3.2 Illustrious-family reliability for two-body scenes

- **NoobAI-XL** is an Illustrious-family fine-tune (from Illustrious-xl-early-release-v0, trained
  on full Danbooru + e621), not a separate architecture [1]. A dedicated two-person LoRA for
  Illustrious exists with trigger `2people`, but its author warns weights **above 0.8 fall apart**
  (especially alongside other LoRAs) and recommends **0.25–0.75** [2]. The **"Anatomy Helper"**
  fixer is trained on 333 images of women and improves hands, feet and pose variety — a
  **single-body** enhancer, not a two-body interlock guarantee [3].
- **Hassaku XL v3 (WIP)**, an Illustrious/WAI-based checkpoint, is documented by its author and
  users as unreliable for two-body scenes: extra people appear, `hugging` produces "sandwich
  hugging", **~20 % of couple generations gain an unwanted second male**, the second character is
  cut off even with `FULL BODY`, and extra or deformed limbs appear [6].
- **Orifice placement is a known base-model failure**: without a helper LoRA, SDXL-family
  checkpoints return vaginal anatomy when anal was requested **about half the time** — why
  genital/pose LoRAs exist (Subtle Poses AnalSex XL3; Anus/Vulva Helper XL, best at LoRA 0.2 then
  img2img at 0.5–0.8) [4].

### 3.3 Separating two partners

Two character LoRAs stacked normally blend into "one face that's a blend of both, in both spots";
the fix (per-region delta masking, §1 finding 3) is unavailable on SDXL [18]. SDXL's equivalent is
**regional conditioning**, with three documented implementations — **Forge Couple** (Attention
Couple port, SD1/SDXL only), **Regional Prompter** (only its Latent mode separates LoRAs to a
region, at areas × single-image time, with a documented latent-mode LoRA corruption issue), and
**Latent Couple** (SD 1.5-era) [19][20][21]. Identity injection is **PuLID** SDXL and **IP-Adapter**
(whose SDXL FaceID variants are experimental), **neither a spatial or pose controller** [22]. The
research-grade answer for two personalized subjects **in physical contact** is **OMG** (ECCV 2024),
a two-stage occlusion-friendly framework whose designed noise-blending timestep is the key to
identity and layout; it combines with LoRA or InstantID without extra tuning [23].

### 3.4 Pose control and interlock

- **No concrete two-skeleton OpenPose recipe for SDXL at 1024 was verified** by either pass — no
  node pack, preprocessor, handler, or documented limit for overlapping interlocked bodies. Both
  passes name this the single highest-value unanswered operational question [13].
- What does exist: an SDXL ControlNet trained on **DWPose** conditioning at 1024 for 15,000 steps
  [14]; preprocessors that emit **multi-skeleton** hints, returning a list of poses in an OpenPose
  JSON `people` list [15]; an editor node pack with documented multi-person support, a configurable
  **person index**, and per-person scaling [16]; and a two-character workflow that claims
  interaction works "very consistently" but **whose author deprecates it** in favour of "Latent
  Couple Pose", saying the best results need a pre-made pose from an OpenPose editor that no one
  seems to maintain [17].
- **xinsir's OpenPose SDXL ControlNet** reports mAP **0.357** vs thibaud's **0.209**, but flags
  instability from the default pose-line drawing. NoobAI-XL's ControlNet ships canny and depth
  variants that must be matched to their preprocessor, with OpenPose in a separate repo [5].
- **No candidate SDXL model page evaluates interlocked two-body anatomy.** The two pages checked in
  full (JANKU, HomoSimile XL) contain none; the only anatomy statement found is the untested
  promotional line *"Better anatomy (yes, even in complicated poses)"* [33].

### 3.5 What SDXL has no verified answer for

Per-partner DNA/identity, camera angle, style aftereffects, and
medieval/other backgrounds. This document's §3.5 already recorded four of the nine
required
outputs as having zero surviving evidence; both passes re-confirm the negative
stands and is *"no verified tool"*, not *"verified to be none"* [13][34][35].

---

## 4. The 3D route: anatomy by construction

### 4.1 DAZ → Blender

- Genitals are added in DAZ Studio as a **geograft** plus shell and material, exported as a DBZ, and
  **Merge Geografts** welds the hidden body vertices into a single seamless mesh — a literal weld,
  not a generated approximation [24][28].
- The cost: the operation is **vertex-number-based and destructive** — morphs can no longer be
  imported afterwards, **all geografts must be merged in one pass**, and the non-destructive
  Geometry Nodes alternative **cannot be exported** to game engines. The documented correct order is
  to transfer the body's shape keys onto the geograft **before** merging (geografts first, then the
  body, then Transfer Morphs), save a `(CharacterName)BeforeFuse.blend`, run Merge Geografts from the
  Finishing tab with **Rig Type MHX**, and fix clothing poke-through in Sculpt Mode [24][26][28].
- **Rig choice matters for export:** Rigify is a full IK rig for original Blender animation but poor
  at importing Daz poses; MHX is the compromise; **Simple IK** uses the Daz rig as its base for a
  100 % match and exports better to game engines [25].
- **Community still pipeline:** pose and export from Daz, import with Easy Import (BSDF, Cycles),
  light with an HDRI, then Film → Transparent so the render carries alpha; **8K stills took roughly
  34 minutes to 2 hours on a 6 GB RTX 3060** [26]. Isolation for compositing comes from
  **Cryptomatte** (ID mattes with motion blur, transparency and depth-of-field) [27].
- **Penetration mechanics:** a developer thread converges on **hand-keying** penetration in the
  Maya/Blender rig, *"by far the best results"*, with the same poster reporting his procedural
  attempts *"never came close to just manually animated scenes"* [30].

### 4.2 Engine route

Two viable engine paths: a **procedural** one (penis-tip bone depth/direction mapped to morph shapes, plus an IK system on the penis) and an **animation-sync** one (the Unity VAM plugin **"naturalis"**); exporting DAZ genitals to Unreal is unsolved (DazToUnreal loses genital morphs, fallback **DAZ → Blender (Diffeomorphic) → Unreal**). Detail and sources: §8 [29]–[32]; the conclusion is §1 finding 2 and §4.2.

---

## 5. Operational constraints that apply whichever route is chosen

- Gateway and control-plane behaviour, including what cannot be changed after creation: §10, its §3's table and doc 23 §2.2/§3. Salad's product default is **3 replicas** [9]. This repo's group recipe is **1 replica** until `/ready` is green (doc 23 §2.2). At least 3 for testing and **at least 5 for production**, since nodes are **interruptible without warning** [9].
- Hardware sizing as published for this family (generic model-class figures, not two-body measurements):

  | Target | Min VRAM | GPU class | System RAM |
  |---|---|---|---|
  | SDXL | 12 GB | RTX 4070 Ti | 24 GB |
  | SDXL + Refiner | 24 GB | RTX 4090 | 30 GB |
  | Flux (fp8) | 16 GB | RTX 4090 | 24 GB |

  Published SDXL figures: 5–15 s/image at 12 GB, 15–30 s at 24 GB with refiner; the SDXL-with-Refiner recipe is benchmarked at ~**3,405 images/$** (~$0.000294/image, ~9.6 s at 18 virtual users, 1024×1024, 20 base + 5 refiner steps, single-person workload), so it does not price the target workload [12].
- The manifest downloads models **before** the instance serves traffic (`/ready` 503 until the warmup workflow completes); recipe images range 6 GB (Dreamshaper 8) to 16 GB (Flux) and can take tens of minutes to pull [9].
- **Repo rule still applies:** one unet family per container group, so repurposing `flux2-klein2`/`flux2-klein-5090` for SDXL may be an operational no-go and a new group is the practical choice [34].

---

## 6. What would change the answer

1. **A measured two-skeleton OpenPose recipe for SDXL at 1024**, including control weights and behaviour on overlapping interlocked bodies. Both passes name this the highest-value gap.
2. **Per-region LoRA-delta masking that accepts SDXL/Illustrious adapters.** Today the implementations refuse them.
3. **Any published per-scene seed hit rate** for a diffusion configuration on two-body interlock, from any family. Nothing measured exists.
4. **A head-to-head of the three routes** — SDXL/Illustrious (§3), 3D (§4: DAZ/Blender, Unreal+MetaHuman, Unity/Unreal procedural) and the current family (§1 finding 3), the third route in the comparison — on still quality, cost and complexity. No source ranks them; the 3D evidence is per-technique testimony from individual developers, not a benchmark.

---

## 7. Coverage gaps the passes themselves recorded

Both reports returned **Partial**. The gaps that matter here:

- No primary-source quantified two-body reliability report for realistic SDXL merges (Juggernaut XL, RealVisXL); **WAI-Illustrious-SDXL v17 and Pony Diffusion V6** not verified from their own model cards; `dw_openpose_full` / DWPose as *the* full-body preprocessor appeared only in secondary guides; and no dedicated benchmark for "penetration in the wrong orifice" exists.
- Salad sources are master-branch files and docs pages dated 2026-01-08 with **no live API call**; only the five recipe Dockerfiles/manifests in `salad-recipes/recipes/comfyui` were enumerated; and `salad.com/models` omits flux1dev and stablediffusion35medium that the docs recipe page lists.
- **No Reddit source was inspected** (r/adultgamedev, r/nsfwdev), so no Reddit recommendation is claimed; `docs.blender.org` was **Cloudflare-blocked** (the Cryptomatte standard was used instead); the Diffeomorphic addon's own wiki rendered only a navigation stub; and cloth/soft-body coupling and genital physics in engines had no inspected source.
- One claim was **excluded by verification** (camera angle on Qwen-Image-Edit-2509; §10, its §2.2).

Full gap list of the two passes: retained above in condensed form; the binding ones are §1 finding 1 and §6 item 3.

---

## 8. Sources

Numbered in citation order. All fetched **2026-09-23**.

| # | Source |
|---|---|
| 1 | NoobAI-XL 1.0. https://huggingface.co/Laxhar/noobai-XL-1.0 |
| 2 | Multiple People / (2) Two People or more, for Illustrious. https://civitai.com/models/2124063/multiple-people-2-two-people-or-more-for-illustrious |
| 3 | Anatomy Helper. https://civitai.com/models/1171869/anatomy-helper |
| 4 | Subtle Poses AnalSex XL3; Anus/Vulva Helper XL. https://civarchive.com/models/1444070?modelVersionId=1919016 |
| 5 | xinsir/controlnet-openpose-sdxl-1.0; NoobAI-XL ControlNet. https://huggingface.co/xinsir/controlnet-openpose-sdxl-1.0 ; https://civitai.com/models/929685 |
| 6 | Hassaku XL (Illustrious) v3 WIP. https://civarchive.com/models/140272?modelVersionId=2010753 |
| 7 | Salad recipe `form.json` + `manifests/sdxl-with-refiner.yml`; ComfyUI API Recipes. https://raw.githubusercontent.com/SaladTechnologies/salad-recipes/master/recipes/comfyui/form.json ; https://raw.githubusercontent.com/SaladTechnologies/salad-recipes/master/recipes/comfyui/manifests/sdxl-with-refiner.yml ; https://docs.salad.com/container-engine/reference/recipes/comfyui |
| 8 | Recipes & Models. https://salad.com/models |
| 9 | Deploy Image and Video Generation with ComfyUI. https://docs.salad.com/container-engine/how-to-guides/ai-machine-learning/deploy-stable-diffusion-comfy |
| 10 | In-repo: `salad_klein/manifest.yaml`; `salad_klein/test_prefetch.py`; §10, its §3.1 |
| 11 | Salad. Load Balancing Options; Long-Running Tasks. https://docs.salad.com/container-engine/explanation/gateway/load-balancer-options ; https://docs.salad.com/container-engine/explanation/job-processing/long-running-tasks |
| 12 | Salad SDXL benchmark; hardware table from [9]. https://blog.salad.com/sdxl-benchmark/ |
| 13 | §10, its §2.3 (two-person pose conditioning: unverified but not unavailable) |
| 14 | dimitribarbot/controlnet-dwpose-sdxl-1.0. https://huggingface.co/dimitribarbot/controlnet-dwpose-sdxl-1.0 |
| 15 | Fannovel16/comfyui_controlnet_aux (DWPose source + README). https://github.com/Fannovel16/comfyui_controlnet_aux |
| 16 | westNeighbor/ComfyUI-ultimate-openpose-editor. https://github.com/westNeighbor/ComfyUI-ultimate-openpose-editor |
| 17 | ComfyUI Multi-Subject Workflows (Latent Couple Pose). https://civitai.com/models/21100/comfyui-multi-subject-workflows |
| 18 | RegioCraft README + Guide (EN); Nougan_Nodes regional-character-lora; CliffNodes Krea2-Multi-Character-Lora-Node. https://raw.githubusercontent.com/zeus-onl/RegioCraft/main/README.md ; https://raw.githubusercontent.com/Winnougan/Nougan_Nodes/main/docs/regional-character-lora.md ; https://github.com/CliffNodes/Krea2-Multi-Character-Lora-Node-w-bounding-box |
| 19 | sd-forge-couple (SD Forge Attention Couple). https://github.com/Haoming02/sd-forge-couple |
| 20 | sd-webui-regional-prompter. https://github.com/hako-mikan/sd-webui-regional-prompter |
| 21 | Latent Couple (two-shot diffusion port). https://github.com/opparco/stable-diffusion-webui-two-shot |
| 22 | PuLID (arXiv:2404.16022); PuLID repo; IP-Adapter. https://arxiv.org/abs/2404.16022 ; https://github.com/ToTheBeginning/PuLID ; https://github.com/tencent-ailab/IP-Adapter |
| 23 | OMG: Occlusion-friendly Personalized Multi-concept Generation (arXiv:2403.10983). https://arxiv.org/abs/2403.10983 |
| 24 | Diffeomorphic import_daz. Setup_Finishing_Merge_Geografts. https://raw.githubusercontent.com/wiki/Diffeomorphic/import_daz/Setup_Finishing_Merge_Geografts.md |
| 25 | Diffeomorphic import_daz. Setup_Rigging. https://raw.githubusercontent.com/wiki/Diffeomorphic/import_daz/Setup_Rigging.md |
| 26 | F95zone. "DAZ to BLENDER basic setup + guide (feat. Diffeomorphic)". https://f95zone.to/threads/daz-to-blender-basic-setup-guide-feat-diffeomorphic.201085/ |
| 27 | Psyop/Cryptomatte. https://github.com/Psyop/Cryptomatte |
| 28 | LoversLab. "Daz to Blender with Gens using Diffeomorphic (The Correct Way)", Nuverotic. https://www.loverslab.com/topic/240639-daz-to-blender-with-gens-using-diffeomorphic-the-correct-way/ |
| 29 | Eroticissima. LoveTriggerSDK. https://www.eroticissima.wtf/sdk.html |
| 30 | F95zone. "How do we do penetration mechanics in 3D games?" (Jun 2024). https://f95zone.to/threads/how-do-we-do-penetration-mechanics-in-3d-games.210650/ |
| 31 | F95zone. "About DazToUnreal workflow (+ gens tests)". https://f95zone.to/threads/about-daztounreal-workflow-gens-tests.135115/ |
| 32 | PRIMAL BONE MetaHuman nude female / bundle; Lewd Metahuman Creator. https://primalbone.itch.io/metahuman-nude-female ; https://primalbone.itch.io/metahuman-nude-male-and-female ; https://fireblade185.itch.io/lewd-metahuman-creator |
| 33 | JANKU (Civitai 1277670); HomoSimile XL (Civitai 964011). https://civitai.com/models/1277670 ; https://civitai.com/models/964011 |
| 34 | In-repo: `salad_studio/salad_status.py`; doc 15 (group facts, one unet family per group) |
| 35 | this document's §3.5 (style aftereffects, genital-act correctness, camera control, medieval backgrounds: zero surviving evidence) |

## 9. Anatomy research

*Consolidated from `docs/workflow/17-klein-two-body-anatomy-research.md` on 2026-10-17. Subsection numbers below are the source document's own.*

**Written 2026-09-22**, after a `/deep-research` fan-out (103 agents, 21 sources fetched,
100 claims extracted, 25 adversarially verified → 19 confirmed / 6 refuted) plus our own
measured render grid from the same night.

Companion documents:

- `docs/workflow/15-salad-flux2-klein-group.md`, the group overview; its "Two-body plate recipe" is superseded — [doc 21](21-klein-image-handoff.md) is the operating point.
- `salad_klein/README.md`; `tests/test_klein_recipes.py`, 20 tests asserting the verified entry.

**Scope:** 18+ adults only, two nude adults, no minors, nothing illegal. That is the
whole content domain here and nothing outside it is considered.

---

### 1. Executive summary, what changed

Three things we believed last session did not survive verification, and two things we had
never suspected turned out to be the actual cause.

**Our hypotheses that were refuted:** the 5049-char prompt is over budget (**refuted 0-3** — prompt
*length* is not why the missionary plate failed); "FLUX does not support negative prompts at all"
(**refuted 1-2** — negatives demonstrably bite on the *undistilled base* at ~CFG 4.5 / ~50 steps and
via NAG, so read BFL's guidance as the rule for the distilled CFG-1 regime, not a law of the model);
and LoRA stack ceilings (3-LoRA limit; distillation LoRAs must go upstream) (**refuted 0-3 / 1-2** —
only the optimizer-blindness mechanism survived, and it does not apply to our plain sequential chain).

**What actually causes the extra leg:**

1. **It is a known model- and pose-level defect on SNOFS, not our prompt.** Community
   reports on this exact model line: missionary *"like 95% chance of body horror"*,
   cowgirl *"95% chance of getting reverse"*, spooning *"nothing but amputee body horrors"*.
   Other reports on the same model: a doubled object in the mouth of an oral scene,
   anatomy emerging from the navel or knee, feet deforming (see §4).
The position blacklist and why it was inert at CFG 1: doc 21 §4.

**Our own best measured result, corrected.** A short affirmative
`doggystyle, rear entry, seen from the side` **rendered the act** at two seeds where the
over-specified missionary prompt failed at six seeds, at CFG 1.2–1.5, and at anatomy-fixer 2.0
and 3.0, which is real, and points at composition rather than wording. But it was **not clean**:
the user's verdict on one of those two plates is **"he has extra left arm"** (§3.1). So the
position matters and is not a cure.

**Still-true finding, restated:** at `CFGGuider.cfg = 1` the negative prompt is mathematically inert (`pred = cond`), so node 67's anti-artifact lines have never done anything; see §3 layer 2.

#### 1.1 The LoRA-stack hypothesis, tested and falsified, and the resulting conclusion

The SNOFS author explicitly advises *"try SNOFS by itself before you go adding a bunch of other
general NSFW loras or models to it that screw up anatomy"* (§2.6). That was testable cheaply and
it was tested: `full` (all four LoRAs) vs `alone` (none), 3 seeds each, every other variable
held.

**Result: no improvement.** Both arms are bad; the user's verdict on all six unique plates is
*"none of the rendered plates are good."* Two useful by-products:

- **Renders are *usually* reproducible. Not guaranteed.** This section originally claimed renders
  were "fully deterministic" on the strength of `full` at seed 610296 being byte-identical
  (`md5 2c5065ff…`) across three batches. **That claim is retracted.** Re-checking every repeated
  render after a later run: **5 of 6 pairs are byte-identical, 1 is not.** `full_s610296` came back
  as `31b8671c…`, a different image from the same graph, seed and recipe. The outlier was the first
  render after a replica restart (a different VRAM/execution path is a plausible but *unconfirmed*
  cause). **Practical consequences:** a repeated seed is *evidence* of reproducibility but not
  proof; a "byte-identical hash" is a **soft** verification check, not a hard one; and the earlier
  "26 files, 16 unique images" finding is still explained by dedup, since most repeats do match.
The 524 story and the shipped URL check: §10, its §3.2. The "22 judged, zero good" tally: doc 21 §9, its §1.

---

### 2. Model inventory (verified)

#### 2.1 The SNOFS-baked-in checkpoint is real, and we are already on that route

We are *not* loading the SNOFS LoKr. Verified in-repo: node 70 of every SNOFS recipe loads

```
snofsSexNudesAndOther_distilledV12KleinFp8.safetensors
```

i.e. the SNOFS-distilled full checkpoint at **v1.2, fp8**. There is no SNOFS LoRA weight in
the chain (nodes 80→81→82→83 are detail slider −1.5, impressionism 0.8, anatomy fixer 2.0,
FLUX_NSFW_Fix 1.0), so the user's "SNOFS weight should not overpower the other LoRAs"
concern is already moot, and the inverse concern applies instead: the SNOFS **unet** is
v1.2 while most public anatomy evidence is attached to v1.3/v1.4.

The current published build (Civitai model `2416142`, derived version `2985440`, author Ashen3,
updated **2026-09-22, the day of this research**) has a moving download count — a 17,166 snapshot
re-fetched 2026-09-23 as 55,187, so do not quote it — and three **Krea 2** versions have since been
published on the same model page.

Version / fileId / sha256 for v1.4 bf16, v1.4 fp8, v1.4 Base and our v1.2: doc 21 §8, "Re-verified 2026-09-23".

It is an explicit merge, *"so users can generate without using the SNOFS lokr"*, which is
exactly the shape we already run. **Upgrade path: v1.2-fp8 → v1.4, and fp8 → bf16.**

Catalog status: the v1.2 unet row was **missing entirely** from `model_catalog.py`
and was added on 2026-09-22 as `civitai:2416142@2786085` (kind `checkpoint`, status
`on-klein-group`, `use: ["bodies","sex"]`), cross-referenced bidirectionally with the SNOFS
LoKr row `civitai:1972981@2960556`. The v1.4 build is **deliberately not catalogued yet.**
Nothing has A/B'd it (see Step 1).

#### 2.2 fp8 is a named cause of anatomy degradation

fp8 vs bf16: doc 21 §6.2 (open) and §8, "Not re-verified".

#### 2.3 The plain-Klein + SNOFS-LoKr route is the broken one (outside ComfyUI)

The diffusers LoKr bug and its PRs: doc 21 §8, "Re-verified 2026-09-23". ComfyUI reads LoKr natively, so this only matters on a diffusers/PEFT path — do not plan one.

#### 2.4 The anatomy fixer LoRA, already in our stack, correctly weighted

`klein_slider_anatomy.safetensors` (Civitai `2324991`, version `2615554` = "Klein 9B v1.5",
24,815 downloads) is a **concept slider, not a trigger-word LoRA.** No trigger words exist;
weight alone drives it. Author guidance: *"Weight 2.0 mostly keeps the seed intact and can
be used to fix minor glitches, 3.0 fixes some more prominent artifacts."* Our node 82 uses
exactly this version at 2.0. **We have never tried 3.0 with a trimmed prompt** (the earlier
3.0 sweep ran on the bad missionary prompt, so it was measuring the prompt).

Caveats to carry: multiple users report no effect at 1.0–3.0 at all, and v1.5 is reported to drift faces; it is a bidirectional slider, so negative weight would theoretically behave as a defect injector (author self-report only; no commenter has run it negative).
The old doc claim "Every weight held at every seed… The fixer's effect here is preventive, not visible" is replaced by **"the seeds did not fix it"** — the audit could **not** reproduce an extra foot in any of the six seed-sweep plates (§3.1), so the extra-limb count claim is unsupported by our own sample.

#### 2.5 Other Klein 9B anatomy candidates worth a look

- **DPO (Klein 9B base).** LoRA trained on DPO preference pairs explicitly to steer away
  from "the waxy skin and arm/leg/hand issues". Base-specific, so not a drop-in for the
  distilled cut.
- **PornMaster Flux2 Klein 9B base t2i workflow.** A published workflow for this content
  class on the *base* model.

Neither is a verified fix; both are cheap to test once the ladder in §6 is past step 2.

**A negative result worth recording:** a search for hands/limb-specific Flux.2 Klein 9B LoRAs
found **none.** Only SDXL/Illustrious hand fixers. The Klein Anatomy/Quality Fixer (`2615554`)
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
Deliberately **not** changed. The lowercase spelling is also in the local
`~/.config/salad/studio-loras.json` extras row and is asserted by
`test_request_json.py:138`, so the catalog, extras and test must change together or not at all.

#### 2.6 The author's own guidance (from the model descriptions, 2026-09-22)

Pulled from the Civitai API (the web pages now redirect to a mature-content site; the API
descriptions are intact). Three findings that revise the plan.

**There is no "v1.3 distilled". v1.3 shipped base-only.** Klein versions of the merged checkpoint
(`2416142`), complete: `2985440` **v1.4 Klein 9b Distilled** (Flux.2 Klein 9B), `2967967` v1.4 Klein
9b Base, `2836812` **v1.3 Klein 9b Base**, `2786085` Distilled v1.2 Klein fp8 ← what we run,
`2746781` Distilled Klein 9b v1, `2716480` v1.0 Klein 9b (base). The distilled line is **v1 → v1.2 →
v1.4**; v1.3 was skipped for distilled. Cross-confirmed by the HF mirror `edwixx/Flux2Klein9B_SNOFS`,
which carries exactly two weights, `…distilledV12Fp8.safetensors` and `…v13Base_BF16.safetensors`. So
the community report "v1.4 has an inverted penis head, 1.3 better" concerns the **LoKr** (`2818111`,
`klein_snofs_v1_3.safetensors`, ~1.02 GB), **not** a checkpoint; the v1.3 behaviour is reachable
**only** through the LoKr route (plain Klein unet + LoKr), which is open to us precisely because
ComfyUI reads LoKr natively (§2.3). Our one test of that route (`target/klein_ab/verify2.py` arms
c/d) ran **4 steps at CFG 1 on a BASE model**, mis-parameterised (base wants ~50 steps), so that
route is **untested, not disproven**.

**v1.4 was depth-trained specifically for two people intermingled** — the strongest signal in this
document pointing at any single version. Verbatim, on the Klein v1.4 LoKr: *"training against depth.
Considering how much of SNOFS is two people intermingled with close skin colors, it seemed like a
novel idea. It did seem to rapidly help with that sort of thing."* (with the caveat of *"a bit of a
texture issue on very close up images"*). That is our exact failure class. Counterweight, same
author: *"I had versions that took it further but it tended to have more broken anatomy"*. Newer is
not monotonically better, so v1.4 still has to be measured.

**The author documents a mechanism for making negative prompts work**, cheaper than NAG: a staged
sampler. *"generate without the turbo lora for the first bit, which helps with variation and prompt
adherence, and then bump to a second stage with the turbo lora to keep things fast. For the
three-stage variation, you can then bump back to doing it without the turbo lora for the last bit
**if you want to use a negative prompt**."* Dropping the distillation LoRA for the final steps
escapes the CFG-1 regime where the negative is inert (§3, layer 3). This belongs alongside NAG in
Step 3. The author's "try SNOFS by itself" advice: §1.1 above; doc 21 §9, its §6.2.

---

### 3. Prompt craft (for the distilled CFG-1 regime)

Black Forest Labs' own skills repo (`black-forest-labs/skills`, pushed 2026-09-09) states the
rule and the rewrite recipe: *"FLUX does NOT support negative prompts. Always describe what you
WANT, not what you don't want"* — `"a portrait of a woman, no glasses, no hat, no makeup"` →
`"a portrait of a woman with natural skin, clear face, bare head, visible eyes"` — with the
companion rule *"Negative prompts can actually make models focus MORE on unwanted elements."*
This is a strong default for CFG-1 distilled sampling, not an absolute.

**Is the negative prompt actually supported?** Do not read the vendor line as a technical spec:
`core-principles.md` mentions **no CFG, no guidance scale, no distilled-vs-base distinction, no
mechanism and no citation**, and the companion `negative-prompt-alternatives.md` offers only the
attention-drift rationale without a technical condition. Adversarial verification **refuted the
absolutist reading 1-2.** The mechanism (naming a defect makes the model attend to it) is asserted
by the vendor but **not empirically demonstrated**, and our own plates contradict it: our positive
prompt's `LIMB OWNERSHIP: four legs and four feet … no more and no fewer` (with node 67 enumerating
`extra knee, third foot, two feet growing from one leg`) is the strongest available anecdote for it,
yet limb counting appears in **16/16** plates, good and bad alike, with the strongest form only in
the four plates that work (§3.1). Treat the deletion as a cheap, harmless simplification, **not**
the identified cause — the best correlate is framing. Keep three layers apart:

1. **Plumbing, supported.** The graph wires a real negative encode (node 67) into a
   `CFGGuider` (node 63). Whenever `cfg > 1` the negative term is live; at cfg 1.5 it carries a
   third of the effective delta. The field is functional.
2. **Operating point, dead.** The recommended regime for the *distilled* cut is CFG 1 at 4
   steps, where the expression collapses to `pred = cond` and the negative contributes exactly
   zero. **The folk claim describes the recommended setting, not the architecture.**
3. **Efficacy, the layer that matters, and the one we measured wrong.** Our CFG grid ran
   1.2/1.3/1.5 and the artifact survived, but **those runs carried the position blacklist**,
   so at cfg > 1 the negative was *live and actively pushing away from cowgirl, doggystyle and
   spooning*, the positions that render. The grid is evidence that **that** negative was
   useless-or-harmful, **not** that negative text cannot help; a CFG sweep above 1 with the
   negative trimmed is an open experiment, not a settled one. NAG remains the way to make
   negatives bite without leaving the few-step regime.

The meme most likely originates with FLUX.1 dev, which is guidance-distilled and driven by a
`FluxGuidance` scalar with **no negative text input at all** — a design Klein-in-ComfyUI does
not share, since it takes a CFG pair. **Untested by us:** how far above 1.5 the *distilled* cut
tolerates CFG before quality collapses, the degradation that motivates NAG in the first place.

#### Rules to adopt

The rules are the checklist in doc 21 §3; the medieval-background caution is doc 21 §4.

#### 3.1 What our own plate audit found, and where it contradicts this doc

An audit of every retained plate (full table **`target/klein_ab/taxonomy.md`**, 310 lines,
gitignored) landed after §2–§3 were written. Method: plate `studio_<ms>.jpg` pairs to the history
row at `ts ≈ ms/1000 − 6s` (offset **+5.6…+7.4 s** held for 19 plates); plates hashed, the 26
files in `art/salad_studio/` are only **16 unique images**. The four counts: `ACT0` **11/16** (the
*dominant* failure), `OWN0` **16/16**, extra foot **0/16 confirmed**, `no more and no fewer`
**only 4/16** — and those four are the plates that **work**.

**What actually tracks the failures is framing, not limb counting.** Failures cluster on the long
bullet-listed scene-heavy rewrite (7/7 fail) and a castle/medieval setting block (6/6 fail); the
proposed mechanism is shot scale — the castle plates render the figures at **25–30 % of frame**
against **40–53 %** in the legible plates, converging with the step-count guidance.

**Both defect classes are real and distinct** (user verdicts, 2026-09-22): `studio_1790054858096`
(= `pose_grid/doggystyle_s610296`) is **"he has extra left arm"** (an extra limb, arms/hands), and
`studio_1790050883681` is **"she has wrong right leg"** (the ownership/attachment class, `OWN0`,
not an extra-limb count). **Nothing in our sample is a duplicated foot.** The same numbers are
tabulated in doc 21 §9, its §3 and doc 21 §4–§5.

---

### 4. Known failure modes on this model line (community-confirmed)

The position and body-part reports (missionary / cowgirl / spooning, the mouth, navel,
knee and foot failures) are §1. The rest, on the same checkpoint and the sibling v1.4 LoRA page:

- Inverted penis head on v1.4 (one user reports **v1.3 works better.** Relevant because we
  run v1.2).
- "Hard whitewashed skin and faces that override character LoRAs"; dirty colours / yellow
  tint / excessive moles (a LoRA-conflict signature, not an anatomy one).

The practical reading: **the canonical positions are not equally hard.** Doggystyle rendered
for us; missionary-in-profile is the worst case. That is consistent, not contradictory, with
the community reports.

---

### 5. Auto-detecting distorted plates (the QC gate)

**Nothing shipped does limb QC.** `ComfyUI-QualityGate`'s only body-structure signal is a
head-width-to-shoulder-width ratio from four MediaPipe Pose keypoints (ears 7,8; shoulders
11,12), geometrically **invariant to an extra limb**, and the node **fails open** — a body it
cannot detect passes through unmodified. Its VLM prompt-adherence check is an unimplemented
roadmap item (last commit 2026-07-08). Credible **components** exist to build our own gate
from, but no validated anatomy head does; a prototype failed at 25 % TPR / 33 % FPR (§5.1) —
do not rebuild it (doc 21 §6.7).

#### 5.1 Tested prototype, measured negative result

A prototype was scored against a **labelled set of 15 plates (12 BAD, 3 GOOD)** (one entry a
byte-identical duplicate, so 12 distinct BAD). Deliverable: `target/klein_ab/qc/anatomy_qc.py`,
raw per-plate JSON `target/klein_ab/qc/eval_*.jsonl`. The label set was miscalibrated; rebuild it
before scoring again — §10, its §5.

| Backend | TPR | FPR | Verdict |
| --- | --- | --- | --- |
| VLM (local Ministral-3-8B, 156 grounded questions) | **25 %** | **33 %** | unusable |
| Heuristic (no model) | **0 %** | **33 %** | unusable |

**Asking a VLM to count or trace limbs does not work.** Both an 8B and a 27B returned *"4 limbs,
no extra limb, 9/10, defect: none"* on the leg-over-the-shoulder plate **and** on the missionary
extra-leg plate, matching the published finding that GPT-4o and LLaVA score ≈50 % AUC on this task
and **rationalize instead of detecting**. Two further failure modes: a **fail-open** path, 9 of 156
questions returned an *empty* reply because the reasoning model exhausted its token budget and
those silently became "no defect", which is how the clearest bad plate (`studio_1790051031898`)
escaped; and **false positives on good plates** (one clean doggystyle plate flagged by both
backends). **A warned-against trap we fell into:** a 4-image probe of the one question that seemed
to work scored **4/4** and was nearly reported as a working detector; on the full set it scored
**3/12**. The small sample lied — do not calibrate this on a handful of plates.

**The right architecture is a pose model, not a VLM**, and we do not have one. The cheapest real
path is `rtmlib` RTMPose/DWPose ONNX (~25–55 MB, Apache-2.0, ~17–30 ms/image), needing a heuristic
layer over the skeleton (per-instance bone-length ratios, cross-instance bbox IoU as a fusion
signal, low-confidence hand/foot keypoints). Two constraints: its opencv-contrib dependency is a
risk against the ambient `cv2` 5.0 (which lacks `ximgproc`), and **pose skeletons are
fixed-cardinality — they cannot report "three arms" directly**, only via derived signals.
`ultralytics` YOLO-pose needs the ComfyUI venv's torch and is AGPL. The paper that is *exactly*
this task (HADM: 37.5k images, 84.8k limb labels) needs Detectron2 + torch 1.12 + Python 3.8 with
no ONNX export and is therefore unusable, **but its dataset is the best available calibration
set.** SAM2 / GroundingDINO / CLIPSeg can verify a region, not count limbs.

**Recommendation: do not wire this as auto-reject.** At 25 % TPR / 33 % FPR it would throw away one
clean plate in three while passing three quarters of the broken ones. Wire it as a **ranking**
signal only, the top-N plates of a batch go to a human, and spend the effort on the pose backbone
instead; reject-and-retry should follow the shape of `regen_bodies.py:cutout_ok`, not a one-shot
report.

**Environment facts (measured).** A cv2-based detector costs **zero install** on the gatekeeper
interpreter (numpy / cv2 / onnxruntime / PIL are present), but there is **no pose or anatomy ONNX
anywhere on disk**, and the only local vision weights are the two LM Studio VLMs that failed the test
above. 32 cores, 102 GB RAM, no CUDA.

---

### 6. Next-session plan, the ordered ablation ladder

Each step is **single-variable** against a held baseline (seed, graph, LoRA chain, 832×1216,
euler, 4 steps, CFG 1 unless the step says otherwise); do them in order, stop at the first step
that clears the artifact rate, and re-shoot the position matrix at the end regardless. The
still-open ladder is doc 21 §6, one item per step here; harnesses are
`target/klein_ab/{pose_grid,seed_sweep,cfg_grid,lora_ablation}.py`.

**Step 4. Weights, once the prompt is clean.** Anatomy fixer 2.0 vs 3.0 with the trimmed prompt
(the earlier 3.0 sweep was measuring the bad prompt). Separately, test the detail slider's **−1.5
inversion** — node 80 runs a concept slider at negative weight, which inverts whatever the slider
encodes and has never been justified.

**Discipline that made the difference, keep it:** one plate per config is a lottery, and a third
leg is per-seed. Score with a **6-seed labelled contact sheet** and **present the sheet to the
user**; do not sign off on anatomy from my own read (it has already passed both a missing act and
a third leg).

**Constraints for next session:** generation requires the Salad GPU up (it was shut down
deliberately for the night); the harness is `salad_studio.generator.generate_from_payload(...)`
with gateway/key read from `~/.config/salad/` — never print, echo or commit those. Do not download
weights without asking; do not commit images (no `.jpg/.png/.webp/.gif/.pak`) — keep renders under
gitignored `target/`.

---

### 7. Work that this doc invalidates

- Every site this section named is listed, with its correction, in doc 21's "What this supersedes" table and §7. Commit `1c1ac38a` on `salad-studio-audit-catalog-assist` is **wrong on the branch** (cuddle prompt, penis LoRA at 81, 6 steps); PR #61's §4 body describes the disproven recipe and needs a third rewrite.

---

### 8. Gaps and open questions

The other gaps are doc 21 §6 (bf16 §6.2, v1.4 §6.3, NAG §6.5) and §4 (medieval).

- **Is there a position-specific Klein 9B LoRA or checkpoint** trained on
  missionary/cowgirl/spooning compositions, rather than a generic anatomy slider? And is
  there any Klein NSFW checkpoint whose comments do **not** carry the 95%-body-horror
  missionary reports?
- ~~Which VLM configuration is the best auto-reject head?~~ **Answered. None** (§5.1); the open question is now which **pose backbone** (`rtmlib`/DWPose vs YOLO-pose) and which derived skeleton signals best rank a batch, and how to calibrate on the HAD dataset without Detectron2.

---

### 9. Sources

Primary:

- SNOFS merged checkpoint, `https://civarchive.com/models/2416142/...?modelVersionId=2985440` (and `https://civitai.com/models/2416142`)
- SNOFS v1.4 LoRA page, `https://civarchive.com/models/1972981`. **Corrected 2026-09-23:** this page is a **list of trigger terms that work** (missionary / doggystyle / cowgirl / prone / reverse cowgirl / spooning position), with **no per-position failure rates**; it was previously labelled here "(position failure reports)", which it is not.
- Klein Anatomy / Quality Fixer, `https://civitai.com/models/2324991/klein-anatomy-quality-fixer`
- BFL prompt-craft rules, `black-forest-labs/skills` → `flux-best-practices/rules/` (`core-principles.md`, `negative-prompt-alternatives.md`), `https://docs.bfl.ml/guides/prompting_guide_t2i_negative`
- ComfyUI Klein guide, `https://docs.comfy.org/tutorials/flux/flux-2-klein.md`
- NAG, `https://github.com/ChenDarYen/ComfyUI-NAG`, `https://arxiv.org/abs/2505.21179`, fork `https://github.com/BigStationW/ComfyUI-NAG-Extended`
- diffusers LoKr bug, `https://github.com/huggingface/diffusers/issues/13261`, PRs `#13997` (closed unmerged), `#14163` (open)
- fp8 anatomy reports, `https://huggingface.co/black-forest-labs/FLUX.2-klein-9b-fp8/discussions`
- QC tooling, `https://github.com/nobu1990/ComfyUI-QualityGate`, `https://huggingface.co/Shimin/qwen3_vl_8b_foreagent`, `https://arxiv.org/abs/2510.10231`, `https://github.com/opendatalab/FakeVLM`
- LoRA optimizer stacking hazard, `https://github.com/ethanfel/ComfyUI-LoRA-Optimizer`
- `https://myaiforce.com/flux-2-klein-anatomy-horror/` (step-count guidance; secondary)
- Our own artifacts behind the measurements, all gitignored: `target/klein_ab/` (the harnesses, `sheets/`, `qc/`) and the plate ids in §3.1 / §5.1

## 10. The SDXL migration premise

*Consolidated from `docs/workflow/18-sdxl-migration-brief.md` on 2026-10-17. Subsection numbers below are the source document's own.*

**Written 2026-09-22** from a second `/deep-research` pass (110 agents, 25 claims adversarially
verified → **18 confirmed, 7 refuted, 0 unverified**). Companion to
§9 of this document, which documents the Klein conclusion.

**Scope:** 18+ adults only, two adults, no minors, nothing illegal. Research only. No images
were generated.

---

### 1. Headline: the hypothesis this pass was built to test failed to be confirmed

We asked it to test this claim, which I had asserted confidently:

> *"The mature ecosystem for this content is SDXL-family … a search for hand/limb fixers found
> only SDXL/Illustrious models, none Klein-native."*

**Verdict: not tested, and not supported.** No claim in the pass measures anatomy quality in
**multi-person interlocked compositions** for any Illustrious, NoobAI, Pony or other SDXL finetune.
The two SDXL-family pages surfaced as candidates, **HomoSimile XL** and **JANKU**, were checked in
full and contain **zero** multi-person anatomy evaluation — their only anatomy material is
negative-prompt boilerplate plus one untested promotional line (*"Better anatomy (yes, even in
complicated poses)"*) — and full-text searches return **zero** hits for `2girl / plural /
two-person / interlock` and **zero** for `missionary / cowgirl / doggy / spooning / prone`. So the
premise, "SDXL-family is where the mature two-person ecosystem lives", remains an **inference
imported from a fixer-LoRA search**, not a verified finding. That inference was mine, and I should
not have stated it as fact.

**And the base architecture has peer-reviewed evidence against it.** On the HumanRefiner study
(ECCV 2024, arXiv 2407.06937), frozen **SDXL 1.0 was the worst entry on abnormal-anatomy severity**
of the whole comparison except HumanSD, on the HumanArt hard split (Abnormal Score **0.857** vs
SSD-1B 0.832, Pose-T2I-Adapter 0.807, HumanSD 0.801), with the worst LAION FID among non-HumanSD
entries (30.024 vs 16.465). It measures **base SDXL 1.0, not a finetune**, on **single-person
prompts**, so it does not settle the question — but it does falsify "SDXL lineage is anatomy-safe by
itself", corroborated by WACV 2026 *"We Still See Broken Limbs"* and an ICLR 2025 submission also
reporting SDXL limb-placement defects.

> Method note: **6 of the 18 confirmed claims are scoped negatives about web pages** ("this page
> contains no X"), not about the world. They license *"no evidence for SDXL anatomy quality was
> found"*, never *"SDXL anatomy quality is bad."* Read §1 accordingly.

---

### 2. What it DID establish, and two of these are blockers, not open questions

#### 2.1 Per-partner DNA control has a verified failure mode (blocker for requirement 5)

Stacking **two character LoRAs without regional masking blends both identities into one face
appearing in both positions.** Independently corroborated, and attributed by commenters to LoRA
technology generally rather than to any one architecture. A HF discussion puts the limit
plainly: *"It works reasonably for side-by-side non-interacting characters but breaks down
quickly with physical contact/interactions."*

The only **code-verified** fix is hard spatial masking of each LoRA's activation delta against a
box-derived mask (`delta = (xf @ down.T) @ up.T` → `masked = full_mask(...) * delta`, all regions
summed in one forward pass, smoothstep mask exactly 0 outside its box). Two implementations
exist: `zeus-onl/RegioCraft` and `CliffNodes/Krea2-Multi-Character-Lora-Node...` (plus
`lokitsar/ComfyUI-Krea2-MultiLoRA-Composer`).

**Both are Krea-2 only and explicitly refuse mismatched adapters**: *"Format support does not
make a FLUX/SDXL LoRA into a Krea 2 LoRA."* So **an SDXL/Illustrious stack cannot use the only
working regional-identity tool.** And neither tool addresses anatomy at all. RegioCraft's
documentation contains **no** anatomy, limb, genital or two-body-correctness feature; its only
multi-person guidance is box positioning to avoid merged-looking characters.

Note the irony: the regional-masking technique that would solve *our* identity problem is built
for **Krea 2**, the base the SNOFS author migrated to, not for SDXL, and not for Klein.

#### 2.2 Camera angle has no SDXL path (blocker for requirement 6)

The only camera-control node found emits camera-*movement* instructions for an image-to-image
LoRA that exists **solely for Qwen-Image-Edit-2509**; its shipped workflow contains no SDXL,
Flux, Illustrious, Pony or Klein checkpoint string anywhere. Requirement 6 has no verified answer
**in either family**.

#### 2.3 Two-person pose conditioning: unverified, but NOT unavailable

No concrete two-skeleton OpenPose recipe for SDXL 1024 was verified in this pass, no node pack,
no preprocessor, no handler, no documented limits for overlapping interlocked bodies. **This is
the single highest-value unanswered operational question.**

Important scope correction from the verifiers: the most-cited large NSFW pose pack (525 poses) is
**solo-only and SD 1.5** (512×768 / 768×512, ships JSON keypoints, no SDXL version), but
dedicated **couple pose packs do exist** (`couplePose1_v10`, `couplesPoses2_v10`, Qpipi
couple/multi-character packs), and Illustrious-XL ControlNet OpenPose exists (users report
matching-preprocessor requirements, prompt-adherence problems, black previews). So the correct
statement is *"no verified recipe"*, **not** *"two-person pose conditioning is unavailable."*

The four zero-evidence outputs (fixer LoRAs, genital-act correctness, camera control, style aftereffects): doc 22 §3.5; the ControlNet-Tile recipe was refuted 1-2.

### 3. Salad Cloud, fully answered, and directly actionable

| Fact | Value |
| --- | --- |
| Container Gateway server-response cap | **100 seconds**, a Cloudflare hard limit, returns **524**. Not 120. |
| Client Request Timeout | defaults to and caps at 100 s; **neither can be changed after the container group is created** |
| Docs' own framing | the gateway "isn't built for long jobs" |
| **Job Queue path** | **no timeout**, handles multi-minute generation |
| Async option | **webhooks** while still using the gateway |

This **fully explains our production failure**: any ComfyUI graph whose handler must download a
LoRA at request time cannot be relied on to return inside 100 s, which is exactly what broke
every LoRA-bearing graph after the replica restart. Our 120 s figure is a separate client/proxy
read timeout, not a Salad value.

#### 3.1 But do NOT reach for `models.before_start`, our repo already rejected it, for a reason

The research recommends `manifest.yaml` `models.before_start` (vendor-documented, and the
`comfyui-api` OSS README numbers it as startup steps 4/5). **Our repo deliberately keeps it
empty**, `salad_klein/manifest.yaml`:

> `# Empty: Salad's wrapper downloads before_start files one-by-one and that is what the startup probe was killing. prefetch.py pulls all three in parallel, then execs comfyui-api.` `# Civitai LoRAs stay URL-loaded.`, `models:` / `before_start: []`

Salad's **sequential** `before_start` download is what caused a 25-minute startup (doc 15,
"Startup-probe death loop"), and `test_prefetch.py:32` asserts the file stays `before_start: []`.
**Putting URLs back there would reintroduce a bug we already fixed.**

#### 3.2 DECIDED (2026-09-22). Verify the LoRA URL; do not download

**The user's call, and it overrides the designs below:** LoRAs must **not** be downloaded anywhere
by us. The replica loads each one **from its URL** when the Comfy graph runs, so the only thing
worth checking is that the URL is correct. Local mirroring is pointless, and a container-side
pre-fetch is unnecessary machinery.

**Implemented:**

- `generator.check_lora_urls(prompt)` runs after the Civitai token is attached and before
  `POST /prompt`. For each Civitai LoRA URL it issues a `HEAD`, falling back to a one-byte ranged
  `GET` when a CDN refuses `HEAD` (400/405/501).
- A **definitive** answer fails the render with a clear message naming the LoRA, `401/403/404/410`
  raises `RuntimeError` ("Civitai LoRA URL does not resolve: civitai:2615554"). Anything else
  (timeout, 5xx, transport error) is logged and the render proceeds: the replica may reach a host
  this machine cannot.
- Logging uses `request_json.lora_url_label` (`civitai:2615554`), never the URL. It carries
  `?token=`.
- `model_catalog.should_autodownload` now refuses `kind == "lora"` outright, so nothing new lands
  on local disk; a deliberate local copy still uses `--force`. Five pre-existing Flux.1 LoRAs
  remain in `art/model-cache/loras/` (kept, not deleted).

> **Be clear about what this does not do.** It does **not** remove the 100 s-cap risk. All four house LoRA URLs
> resolve HTTP 200, so a URL check would not have caught the 524 we reproduced, that failure was **duration
> inside the render**, not an invalid URL. The URL check turns a *wrong* URL into a clear early error; it does
> not make a *correct* URL faster.
>
> **But the LoRA download is probably not the dominant cost, and this section previously overstated it using an
> atypical file.** Real LoRA sizes (22 rows in the catalog): **median 165.7 MB**; our four are **21, 21, 83 and
> 331 MB, 456 MB total** — at the ~8 MB/s seen on a slow node, roughly **3 s, 3 s, 10 s and 41 s, ~57 s for all
> four**, not the minutes implied by the 2.14 GB `UltraRealPhoto` file used for the cold-path test (the **single
> largest row in the catalog**, and a poor example). The better-supported reading is that the render sat **near
> the cap already**, and the LoRA fetch was the **marginal extra** that tipped LoRA-bearing graphs over while the
> LoRA-free arm squeaked under. The LoRA fetch is the only *download* a render can contain — everything else is
> prefetched at first boot ([doc 15 §Image prefetch](15-salad-flux2-klein-group.md)) — and a cold container's
> one-off **loading** of those weights into memory, disk → RAM/VRAM, is not something `prefetch.py` can pre-empt
> (the smoke render with LoRAs already warm took **119.6 s**); nothing measured yet separates load time from
> fetch time within a render. If it recurs, the mechanisms already scoped are `POST /download` with `wait: true`
> (measured: **29.7 s** for a 2.14 GB cold file, `completed in 0.0s` when cached) or Salad's **Job Queue**, which
> has no timeout; the cheaper thing to check first is whether the replica is being restarted mid-session, since
> that is what makes the unet cold.

##### Superseded designs, and the trap they exposed
Both earlier attempts downloaded via `POST /download` and tried to detect readiness; both were wrong, and one would have been harmful: **Design 1** mapped URL → catalog filename and pre-checked `GET /models`, which reports **content-addressed hashes**, so the name could never match and every render polled 40 × 8 s = **320 s**; **Design 2** polled for the filename `/download` reports, which without `wait: true` returns the **version id** (`2615554`) and `status: "started"` **even for a cached file**. The lesson is not "poll better": the contract was **documented at `GET <gateway>/docs/json`** the whole time. **Superseded by §3.2.** `GET <gateway>/docs/json` on the live `api1.19.2` replica lists six paths (`/download`, `/health`, `/interrupt`, `/models`, `/prompt`, `/ready`); `POST /download {url, model_type: "loras", wait: true}` holds the call open until the file is on disk, `status: "completed"`, `duration: 0.0` when cached — measured at **~1.4 s per LoRA**, four in 5.7 s, and `POST /download` exists on our image after all — doc 14 marked it absent, but that was the API **1.10** Flux.1 image, while ours is **`api1.19.2`**.

#### 3.3 Still unverified: does Salad ship any of these models prebuilt?

The one claim asserting the prebuilt `comfyui-api` images bundle no checkpoints was **refuted
1-2**, and nothing else tested Salad's prebuilt catalogue. **Open gap.** Must be checked against
Salad's recipe registry and the `comfyui-api` tag list before any migration plan assumes a
download step. Candidate base surfaced: **WAI-illustrious SDXL** (blog review + model page).

---

### 4. Auto-QC, the one area where the state of the art moved

| Finding | Detail |
| --- | --- |
| **VLMs are confirmed near-random** at missing-body-part detection | LLaVA-34B **9.80 %**, InternVL2-26B **19.37 %**, CLIP-Large-14 25.82 %, in-paper described as *"accuracies close to random guesses"*. **Directly corroborates our own failed 25 % TPR / 33 % FPR limb-counting gate.** |
| **A public anatomy-defect benchmark exists** | **AbHuman**, 56K synthesized images, **147K bounding-box anomalies**, **18 detection classes**, detection- (YOLOv8/RT-DETR) rather than VLM-based. Public, ungated, MIT, ~6.86 GB: `huggingface.co/datasets/Enderfga/HumanRefiner` |
| **A purpose-built fine-tune beats the VLM baselines** | **HumanCalibrator** (fine-tuned LLaVA-1.5 7B): absent **80.69 %** / redundant **58.57 %** accuracy. Caveat: absent FDR 8.48 % is *worse* than LLaVA-34B's 2.34 %, and it was scored on the authors' own 1K hand-labelled set |
| **Localization is weak** | YOLOv8x **mAP50 0.426** / mAP50-95 0.235; RT-DETR 0.331 / 0.188 |

**The blocker for us:** every one of these benchmarks, AbHuman, HAD/HADM, Distortion-5K,
BACON, MagicBench, is built **entirely from single-subject images with single-person body-part
classes**. There is **no multi-person, interlocked, or human-human-interaction evaluation
anywhere**. Follow-up MPIE-Bench independently confirms prior anatomical metrics are scoped to a
single isolated person. So AbHuman's abnormal scorer **should not be assumed to transfer** to
two-body plates.

The `rtmlib` RTMPose/DWPose skeleton-signal route our prior plan named was **neither confirmed
nor refuted** by any claim.

---

### 5. The honest state of the decision

The evidence **does not support the migration**, and it does not refute it either. What we have
is a **demolished inference**: I claimed SDXL-family was the mature answer; nobody, including
this pass, has measured it for interlocked two-body anatomy. Meanwhile two hard blockers appeared
that would have hurt the migration anyway. Regional identity masking exists only for Krea 2 and
refuses SDXL adapters, and there is no SDXL camera-control path.

The remaining work is doc 21 §6; renders are usually but not always reproducible (§9, its §1.1) — rebuild the ground-truth label set before scoring again, the existing one contained a mislabelled GOOD plate.

**Caveats to carry:** the source pool for this pass skews weak (several claims rest on Civitai
marketing pages or on a 12-star single-maintainer README; only three rest on peer-reviewed
papers). The window is fast-moving. Krea 2 is ~3 months old and its multi-character tooling
weeks; version specifics here will decay in weeks. And one coupling we still cannot verify:
*"SDXL has hand fixers"* was never actually connected to *"SDXL has correct interlocked
anatomy"*, the fixer inventory was never enumerated in the confirmed set. **That unverified
coupling is the whole migration premise.**
