# 22. Can we get anatomically correct two-body scenes *every time*?

**Status: an external research record, not a decision.** Two independent
deep-research passes ran on **2026-09-23** against the question *"we need our sex
scenes to be perfect, anatomically correct, every time"*. Both returned
**Partial**. Coverage gaps remain and are listed in §7. This document records
what they found, with the sources they cite, so the next session does not
re-derive it.

Companions: [`21`](21-klein-image-handoff.md) (what we run today),
[`17`](17-klein-two-body-anatomy-research.md) (why Klein fails at two-body acts),
[`18`](18-sdxl-migration-brief.md) (the SDXL premise), [`19`](19-two-body-prompt-playbook.md).

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

## 2. Route A. What we already run (Klein / SNOFS)

- Per-partner separation by **per-region LoRA-delta masking** is the only
  code-verified technique. Implementations: **RegioCraft** and the **Nougan
  regional-character node**, both scoped to Krea 2 / Flux.2-Klein, both refusing
  mismatched adapters [18].
- This is the family our verified recipe uses. It is *not* a guarantee: doc 21 §1
  records 2 of 7 seeds acceptable on the judged prompt.
- Nothing either pass found changes the operating point in doc 21.

---

## 3. Route B. SDXL / Illustrious

### 3.1 Salad Cloud does not stock the models this route needs

- The portal ComfyUI recipe enumerates exactly **Dreamshaper 8, Stable Diffusion
  XL, FLUX.1-Schnell, FLUX.1-Dev, SD 3.5 Medium, and `custom`**. No Illustrious,
  NoobAI, WAI-Illustrious, Pony, or Lustify [7]. The public catalog lists the same
  six recipes and offers "bring any Docker image" as the escape hatch [8].
- The SDXL manifest downloads **only** Stability AI's base 1.0 and refiner 1.0.
  The manifests directory holds only dreamshaper8, flux1dev, flux1schnell,
  sd3.5-medium and sdxl-with-refiner [7][9].
- The escape hatch is the **custom** recipe: a Dockerfile
  `FROM ghcr.io/saladtechnologies/comfyui-api:<comfy>-api<api>-torch<torch>-cuda<cuda>-<runtime|devel>`
  plus a `manifest.yaml` whose `models.before_start` / `after_start` entries are
  `{url, local_path}`, or dynamic loading by putting an `https://` / `s3://` URL
  in a loader node, or `POST /download` with `model_type` in {checkpoints, loras,
  vae, controlnet} and `wait:true`, with disk bounded by `LRU_CACHE_SIZE_GB` [9].

> **The catch is one this repo already paid for.** Salad's wrapper downloads
> `before_start` files **one at a time**, which caused the 25-minute startup in
> our Klein deployment. `salad_klein/manifest.yaml` therefore keeps
> that list **empty** and pulls everything in parallel via `prefetch.py` before
> exec-ing `comfyui-api`, with Civitai LoRAs left URL-loaded [10]. Any SDXL
> custom image must do the same.

### 3.2 Illustrious-family reliability for two-body scenes

- **NoobAI-XL** is an Illustrious-family fine-tune (from
  Illustrious-xl-early-release-v0, trained on full Danbooru + e621), not a
  separate architecture [1].
- A dedicated two-person LoRA for Illustrious exists with trigger `2people`, but
  its author warns weights **above 0.8 fall apart** (especially alongside other
  LoRAs) and recommends **0.25–0.75** [2].
- The **"Anatomy Helper"** fixer is trained on 333 images of women and improves
  hands, feet and pose variety, a **single-body** enhancer, not a two-body
  interlock guarantee [3].
- **Hassaku XL v3 (WIP)**, an Illustrious/WAI-based checkpoint, is documented by
  its author and users as unreliable for two-body scenes: extra people appear,
  `hugging` produces "sandwich hugging", **~20 % of couple generations gain an
  unwanted second male**, the second character is cut off even with `FULL BODY`,
  and extra or deformed limbs appear [6].
- **Orifice placement is a known base-model failure**: without a helper LoRA,
  SDXL-family checkpoints return vaginal anatomy when anal was requested **about
  half the time**. This is why genital/pose LoRAs exist (Subtle Poses AnalSex
  XL3; Anus/Vulva Helper XL, best at LoRA 0.2 then img2img at 0.5–0.8) [4].

### 3.3 Separating two partners

- Two character LoRAs stacked normally blend into "one face that's a blend of
  both, in both spots". A LoRA stack applies every adapter uniformly. The fix
  (per-region delta masking, §2) is unavailable on SDXL [18].
- SDXL's equivalent is **regional conditioning**:
  - **Forge Couple** (Attention Couple port, SD1/SDXL only). Basic mode maps
    each prompt line to a tile, Advanced gives 0.0–1.0 x/y boxes and per-region
    weights, Mask mode for hand-drawn regions, and a first/last "Global Effect"
    line for background or style tags [19].
  - **Regional Prompter**. Attention mode is the default; **Latent mode is the
    only mode that separates LoRAs to a region**, at a cost of areas × single-image
    time, and carries a documented latent-mode LoRA corruption issue whose
    remedies run from lowering CFG/LoRA weight and raising steps, through
    per-LoRA TE/UNet weights and LoRA block weight, to "if all else fails,
    inpaint" [20].
  - **Latent Couple**. Splits the latent space (divisions, positions, weights,
    "end at this step", e.g. base region 0.2 and each character region 0.8) with
    subprompts joined by `AND`; its documented examples are SD 1.5-era [21].
- Identity injection: **PuLID** SDXL (v1, v1.1) pairs a Lightning T2I branch with
  contrastive alignment so background/lighting/composition/style stay consistent
  around the inserted ID; **IP-Adapter** is a 22M-parameter image-prompt adapter
  whose SDXL FaceID variants are labelled experimental. **Neither is a spatial or
  pose controller** [22].
- The research-grade answer for two personalized subjects **in physical contact**
  is **OMG** (ECCV 2024): a two-stage occlusion-friendly framework, layout
  generation plus visual-comprehension collection for occlusions, then designed
  noise blending whose initiation denoising timestep is the key to identity
  preservation and layout. It combines with LoRA or InstantID without extra
  tuning, including Civitai LoRAs used directly [23].

### 3.4 Pose control and interlock

- **No concrete two-skeleton OpenPose recipe for SDXL at 1024 was verified** by
  either pass. No node pack, preprocessor, handler, or documented limit for
  overlapping interlocked bodies. Both passes name this the single highest-value
  unanswered operational question [13].
- What does exist: an SDXL ControlNet trained on **DWPose** conditioning at 1024
  for 15,000 steps [14]; preprocessors that emit **multi-skeleton** hints.
  DWPose uses a YOLO bbox detector plus a whole-body estimator, returns a list of
  poses, encodes OpenPose JSON with a `people` list, and draws every detected
  pose on one canvas [15]; and an editor node pack with documented multi-person
  support, a configurable **person index**, and per-person scaling [16].
- One published two-character workflow claims ControlNet OpenPose interaction
  works "very consistently", but **its author deprecates it** in favour of
  "Latent Couple Pose", says the best results need a pre-made pose from an
  OpenPose editor, and notes no such editor seems properly maintained [17].
- **xinsir's OpenPose SDXL ControlNet** reports mAP **0.357** vs thibaud's
  **0.209**, but flags instability from the default pose-line drawing because
  training used thicker lines. NoobAI-XL's ControlNet ships canny and depth
  variants (eps-canny, eps-depth_midas) that must be matched to their
  preprocessor, with OpenPose in a separate repo [5].
- **No candidate SDXL model page evaluates interlocked two-body anatomy.** The
  two pages checked in full (JANKU, HomoSimile XL) contain none; the only anatomy
  statement found is the untested promotional line *"Better anatomy (yes, even in
  complicated poses)"* [33].

### 3.5 What SDXL has no verified answer for

Per-partner DNA/identity, camera angle, style aftereffects, and
medieval/other backgrounds. Doc 18 §2 already recorded four of the nine required
outputs as having zero surviving evidence; both passes re-confirm the negative
stands and is *"no verified tool"*, not *"verified to be none"* [13][34][35].

---

## 4. Route C. 3D: anatomy by construction

### 4.1 DAZ → Blender

- Genitals are added in DAZ Studio as a **geograft** plus shell and genital
  material, exported as a DBZ [28].
- **Merge Geografts** removes the body vertices hidden beneath the anatomy piece
  and merges boundary vertices into a single seamless mesh, a literal **weld**,
  not a generated approximation [24].
- The cost: the operation is **vertex-number-based and destructive**. Morphs can
  no longer be imported afterwards, **all geografts must be merged in one pass**,
  and the non-destructive Geometry Nodes alternative **cannot be exported** to
  game engines [24].
- **Documented correct order** for genital geografts: transfer the body's shape
  keys/morphs onto the geograft **before** merging (select geografts first, then
  the body, then Transfer Morphs), save a `(CharacterName)BeforeFuse.blend`, run
  Merge Geografts from the Finishing tab with **Rig Type MHX**, and fix clothing
  poke-through in Sculpt Mode [28][26].
- **Rig choice matters for export:** Rigify is a full IK rig for original Blender
  animation but poor at importing Daz poses (hip, head, elbow/knee offsets); MHX
  is the compromise; **Simple IK** uses the Daz rig as its base for a 100 % match
  and exports better to game engines [25].
- **Community still pipeline:** pose and export from Daz, import with Easy Import
  (BSDF, Cycles), light with an HDRI, then Film → Transparent so the HDRI lights
  only and the render carries alpha for compositing. **8K stills took roughly
  34 minutes to 2 hours on a 6 GB RTX 3060** [26].
- Isolation for compositing comes from **Cryptomatte**, ID mattes generated
  automatically with motion blur, transparency and depth-of-field support, using
  organizational information already present at render time [27].
- **Penetration mechanics:** a developer thread converges on **hand-keying**
  penetration in the Maya/Blender rig alongside the rest of the animation,
  described as producing *"by far the best results"*, with the same poster
  reporting his procedural attempts *"never came close to just manually animated
  scenes"* [30].

### 4.2 Engine route

- The procedural alternative tracks the penis-tip bone's depth and direction past
  the vagina's entrance and maps it to morph shapes, plus an IK system on the
  penis with fixed control points on the vagina blended in on approach.
  Engine-side, penetration via many rigidbodies with Configurable Joints and a
  pseudo-soft-body solution is warned by its author to require *"a massive amount
  of work"* [30].
- A simpler approach is syncing the two characters' animations with no clipping,
  since the skeletal physics asset gives the opposite of clipping (its bodies are
  too large). Unreal's Rigid Body anim-BP node appears to **override** rather than
  stack physics assets; the working showcase of physics-driven penetration is the
  Unity VAM plugin **"naturalis"** [30].
- **Exporting DAZ characters with genitals to Unreal is itself a problem**: the
  official DazToUnreal bridge loses genital morphs (Shell), imports overlapping
  geometry (Merge Fitted), or drops the shell and genital UVs (Delete Overlapping
  Polygons), the last being the only variant whose vagina morphs export and work.
  The community fallback is **DAZ → Blender (Diffeomorphic) → Unreal**, or the
  ~$120 DazToHue + Houdini package that ships full ControlRigs for the Golden
  Palace and Dicktator genitals [31].
- **LoveTriggerSDK** is a Unity 2023 LTS framework (GNU GPL v3) built on Photon
  Fusion 2, FinalIK/VRIK and Cinemachine that enforces consent as a
  network-layer state machine; its "DAZ → Unity pipeline guide" and an
  avatar-customization deep dive are both still listed as **coming soon** [29].
- **MetaHuman nude assets are paid community packs, not Epic's:** PRIMAL BONE's
  nude-female pack (from $44.99; male+female bundle from $74.99) provides a
  rigged female genital model with a physics asset, morph targets for
  close-to-open transitions, and secondary physics on buttocks and thighs,
  optimized for MetaHuman 5.3+; **Lewd Metahuman Creator** (from $10, alpha) adds
  3D nipples and genitalia to a UE 5.6 MetaHuman but **every parametric body-shape
  slider breaks the pubic-hair groom binding** [32].

---

## 5. Operational constraints that apply whichever route is chosen

- The Container Gateway runs on **port 3000** with least-connection balancing,
  a startup probe on `GET /health` and readiness on `GET /ready` [9].
- **The gateway caps a server response at 100 seconds** (100000 ms) and surfaces
  overruns as Cloudflare **524**. Multi-minute generation must use the **Job
  Queue** path, documented as having no timeout limit [11].
- **Load-balancer settings cannot be changed after the container group is
  created**. Timeouts, algorithm and concurrency all require a **new group**.
  An existing group can be repurposed by PATCHing `container.image` [11][34].
- Default is **3 replicas**; at least 3 for testing and **at least 5 for
  production**, since nodes are **interruptible without warning** [9].
- Hardware sizing, as published for this family (generic model-class figures, not
  measurements of two-body interlocked renders):

  | Target | Min VRAM | GPU class | System RAM |
  |---|---|---|---|
  | SDXL | 12 GB | RTX 4070 Ti | 24 GB |
  | SDXL + Refiner | 24 GB | RTX 4090 | 30 GB |
  | Flux (fp8) | 16 GB | RTX 4090 | 24 GB |

  Published SDXL figures: 5–15 s/image at 12 GB, 15–30 s at 24 GB with refiner;
  the SDXL-with-Refiner recipe is benchmarked at ~**3,405 images/$**
  (~$0.000294/image, ~9.6 s average at 18 virtual users), **at 1024×1024, 20 base
  + 5 refiner steps, on a single-person workload**, so it does not price the
  target workload [12].
- The manifest downloads models **before** the instance serves traffic; the first
  request to a cold instance is slow while weights load, and a warmup workflow
  pre-loads them with `/ready` returning 503 until it completes. Recipe images
  range 6 GB (Dreamshaper 8) to 16 GB (Flux) and can take tens of minutes to
  pull [9].
- **Repo rule still applies:** one unet family per container group. Repurposing
  `flux2-klein2` / `flux2-klein-5090` for SDXL may be an operational no-go
  regardless of what the API permits; a new group is the practical choice [34].

---

## 6. What would change the answer

1. **A measured two-skeleton OpenPose recipe for SDXL at 1024**, including
   control weights and behaviour on overlapping interlocked bodies. Both passes
   name this the highest-value gap.
2. **Per-region LoRA-delta masking that accepts SDXL/Illustrious adapters**.
   Today the implementations refuse them.
3. **Any published per-scene seed hit rate** for a diffusion configuration on
   two-body interlock, from any family. Nothing measured exists.
4. **A head-to-head of the three routes** (DAZ/Blender, Unreal+MetaHuman,
   Unity/Unreal procedural) on still quality, cost and complexity. No source
   ranks them; the 3D evidence is per-technique testimony from individual
   developers, not a benchmark.

---

## 7. Coverage gaps the passes themselves recorded

Both reports returned **Partial**. The gaps that matter here:

- No primary-source quantified two-body reliability report was located for
  realistic SDXL merges (Juggernaut XL, RealVisXL); only SEO/content-farm
  summaries assert figures like 20–50 % usable images, and those were not
  verified against the model pages.
- **WAI-Illustrious-SDXL v17 and Pony Diffusion V6** were not verified from their
  own model cards (Civitai is partly login-gated); their relative two-body
  behaviour rests on secondary comparisons. The WAI and Lustify pages now
  redirect to the mature-content mirror.
- `dw_openpose_full` / DWPose as *the* full-body preprocessor appeared only in
  secondary guides, not a fetched primary repo card.
- No dedicated benchmark for "penetration in the wrong orifice" exists; the only
  direct evidence is one pose-LoRA author's 50 %-vaginal anecdote.
- Salad sources are master-branch recipe files and docs pages dated 2026-01-08;
  **no live Salad API call was made**, so live portal state could differ. The
  repo's own group facts (names, image tags, port, creation dates) come from its
  docs, not a live read.
- Only the five recipe Dockerfiles/manifests in `salad-recipes/recipes/comfyui`
  were enumerated; not every tag in `ghcr.io/saladtechnologies/comfyui-api`, so a
  prebuilt SDXL/Illustrious image outside those recipes cannot be fully excluded.
- `salad.com/models` lists six recipes and **omits** flux1dev and
  stablediffusion35medium that appear in the docs recipe page. The catalog page
  is not a complete enumeration.
- **No Reddit source was inspected** (r/adultgamedev, r/nsfwdev): fetches
  returned no page content, so no Reddit recommendation is claimed.
- `docs.blender.org` was **Cloudflare-blocked** on every fetch, so the
  Blender-specific AOV/Cryptomatte node setup and the compositor oil-paint
  post-process are unverified; the Cryptomatte standard was used instead.
- The Diffeomorphic addon's own wiki pages rendered only a navigation stub, so
  the merge-geograft mechanics are sourced from the community tutorial rather
  than the addon's primary documentation.
- Cloth/soft-body coupling and genital physics in engines: no inspected source.
- One claim was **excluded by verification** in the first pass: it asserted
  camera angle has a verified tool on Qwen-Image-Edit-2509, but the cited doc
  says the opposite (doc 18 §2.2: "no verified answer in either family",
  describing the node only as the one *found*).

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
| 10 | In-repo: `salad_klein/manifest.yaml`; `salad_klein/test_prefetch.py`; doc 18 §3.1 |
| 11 | Salad. Load Balancing Options; Long-Running Tasks. https://docs.salad.com/container-engine/explanation/gateway/load-balancer-options ; https://docs.salad.com/container-engine/explanation/job-processing/long-running-tasks |
| 12 | Salad SDXL benchmark; hardware table from [9]. https://blog.salad.com/sdxl-benchmark/ |
| 13 | doc 18 §2.3 (two-person pose conditioning: unverified but not unavailable) |
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
| 35 | doc 18 §2.4 (style aftereffects, genital-act correctness, camera control, medieval backgrounds: zero surviving evidence) |

---

## 9. The one-paragraph version

Neither family guarantees anatomically correct two-body interlock, and no source
either pass inspected publishes a measured rate that says otherwise. The
circulating figures are anecdotes. The one code-verified way to stop two
partners' features bleeding together is per-region LoRA masking, which exists
only for Krea 2 / Flux.2-Klein and refuses SDXL adapters, so SDXL is left with
regional prompting that reduces rather than removes the problem. If "every time"
is a hard requirement, the documented answer is 3D, a DAZ geograft welded in
Blender and composited with Cryptomatte, or an engine with hand-keyed
penetration, with diffusion doing styling and aftereffects. What is missing
before any of this becomes a plan is a measured two-skeleton SDXL pose recipe, a
per-region masking implementation that accepts SDXL adapters, or any published
per-scene hit rate from any diffusion configuration.
