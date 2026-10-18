# 22. Can we get anatomically correct two-body scenes *every time*?
## 1. Status, scope, and the citation convention
**Status: an external research record, not a decision.** Two independent deep-research passes
ran on **2026-09-22**, and both returned **Partial**. Their source lists were re-fetched on
2026-09-23. This document records what they found and what we measured ourselves, so the next
session does not re-derive it. Coverage gaps are in §10.

Companions: [doc 21](21-klein-image-handoff.md) is what we run today;
[§4](#4-the-current-klein-family) covers the current Klein family;
[§5](#5-the-sdxlillustrious-route) covers the SDXL premise.

**Scope:** 18+ adults only, two adults, no minors, nothing illegal.

**Citation convention:** every `[n]` resolves to Appendix A1. The two reports used overlapping
`[S…]` labels for different sources, so this document renumbers them into one sequence.

## 2. The answer in brief
Three findings. Both passes converge on all three.

1. **No diffusion configuration in either family is documented as guaranteeing
anatomically correct two-body interlock.** No inspected source publishes a measured per-scene
seed hit rate or a two-body anatomy benchmark. The circulating figures, *"~20 % unwanted second
male"* and *"vaginal ~50 % of the time when anal was requested"*, are user reports, not
measurements.
2. **The only route where interlocked anatomy is correct by construction is
3D.** A DAZ figure taken through Blender (geograft weld, render, composite), or an engine with
hand-keyed penetration, has correct geometry because a person placed it. Diffusion is then
reserved for styling and aftereffects.
3. **The only code-verified mechanism for keeping two partners' features from
bleeding together is Krea 2 only.** It masks each regional LoRA's activation delta to its own
box, so the delta multiplies to zero everywhere else, and it refuses SDXL and Klein adapters
[1]. An SDXL/Illustrious stack therefore cannot use it and is left with regional prompting,
which reduces cross-contamination rather than eliminating it.

The practical reading is either accept the seed lottery and select (doc 21 §1 gets 2 of 7
seeds), or move the anatomy to 3D.

## 3. What we measured ourselves
### 3.1 The plate audit
An audit of every retained plate landed after the prompt research was written. The full table
is `target/klein_ab/taxonomy.md`, which is gitignored.

| Count | Result |
| --- | --- |
| `ACT0`, act not depicted | **11/16**, the dominant failure |
| `OWN0`, wrong limb ownership | **16/16** |
| Extra foot | **0/16 confirmed** |
| `no more and no fewer` | **4/16**, and those four are the plates that work |

Framing tracks failure, not limb counting. Failures cluster on the long bullet-listed scene
rewrite (**7/7**) and a castle or medieval setting block (**6/6**). The proposed mechanism is
shot scale: the castle plates render figures at **25 to 30 % of frame**, against **40 to 53 %**
in the legible plates.

Both defect classes are real and distinct. `studio_1790054858096` (=
`pose_grid/doggystyle_s610296`) is **"he has extra left arm"**, an extra-limb failure.
`studio_1790050883681` is **"she has wrong right leg"**, the ownership failure class. A short
`doggystyle, rear entry, seen from the side` rendered the act at two seeds where the missionary
prompt failed at six, at CFG 1.2 to 1.5, and at anatomy-fixer 2.0 and 3.0, but one plate still
drew an extra left arm. Position matters and is not a cure.

### 3.2 Determinism is soft
Five of six repeated pairs are byte-identical; one is not. `full_s610296` came back as
`31b8671c…`, a different image from the same graph, seed, and recipe, after the earlier run
produced `md5 2c5065ff…` across three batches. The outlier was the first render after a replica
restart, an unconfirmed cause. A repeated seed is evidence, not proof.

### 3.3 The LoRA-stack ablation
The SNOFS author advises *"try SNOFS by itself before you go adding a bunch of other general
NSFW loras or models to it that screw up anatomy"* (doc 21 §9, its §6.2). The stack was tested:
`full` (all four LoRAs) against `alone` (none), three seeds each, every other variable held.
Both arms were bad, and the user's verdict on all six unique plates was *"none of the rendered
plates are good."*

### 3.4 The QC gate
Nothing shipped does limb QC. `ComfyUI-QualityGate` uses a head-width-to-shoulder-width ratio
from four MediaPipe Pose keypoints, which is geometrically invariant to an extra limb, and the
node fails open [2].

A prototype was scored against **15 labelled plates: 12 BAD and 3 GOOD**. One GOOD entry
duplicates another, so the set holds **12 distinct BAD and 2 distinct GOOD**.

| Backend | TPR | FPR | Verdict |
| --- | --- | --- | --- |
| VLM (local Ministral-3-8B, 156 grounded questions) | **25 %** | **33 %** | unusable |
| Heuristic (no model) | **0 %** | **33 %** | unusable |

Asking a VLM to count or trace limbs does not work. An 8B and a 27B model both returned *"4
limbs, no extra limb, 9/10, defect: none"* on broken plates, and GPT-4o and LLaVA score about
**50 % AUC** and rationalize instead of detecting. Nine of 156 questions returned an empty
reply and silently became "no defect". One four-image probe scored **4/4**, then **3/12** on
the full set.

The right architecture is a pose model, and we do not have one. The cheapest path is `rtmlib`
RTMPose/DWPose ONNX at **25 to 55 MB**, Apache-2.0, **17 to 30 ms/image**, with a heuristic
over the skeleton. Its opencv-contrib dependency conflicts with the ambient `cv2` 5.0, and
skeletons are fixed-cardinality. HADM (**37.5k images, 84.8k limb labels**) is the best
calibration set but needs Detectron2 and torch 1.12.

**Recommendation: do not wire this as auto-reject.** At 25 % TPR and 33 % FPR it would discard
one clean plate in three while passing three quarters of the broken ones. Use it as a ranking
signal only. The label set was miscalibrated; rebuild it before scoring again.

**Environment facts.** There is no pose or anatomy ONNX on disk, and the only local vision
weights are the two LM Studio VLMs that failed. The machine has **32 cores and 102 GB RAM, with
no CUDA**.
## 4. The current Klein family
<a id="9-anatomy-research"></a>

### 4.1 The SNOFS checkpoint
We run the SNOFS-distilled full checkpoint at **v1.2, fp8**, not the SNOFS LoKr. Node 70 of
every SNOFS recipe loads `snofsSexNudesAndOther_distilledV12KleinFp8.safetensors`. The LoRA
chain 80 to 81 to 82 to 83 is detail slider **-1.5**, impressionism **0.8**, anatomy fixer
**2.0**, and FLUX_NSFW_Fix **1.0**. There is no SNOFS LoRA weight in the chain, so the
overpowering concern is moot; the inverse applies, since our v1.2 unet is older than the v1.3
and v1.4 evidence.

The latest published build is Civitai model `2416142`, version `2985440`. Its download count
moves, so do not quote it. The Klein versions: `2985440` **v1.4 Distilled**, `2967967` v1.4 Base,
`2836812` **v1.3 Base**, `2786085` v1.2 Distilled fp8 (ours), `2746781` v1, and `2716480` v1.0
base. The distilled line is **v1 to v1.2 to v1.4**; v1.3 was skipped.

The report "v1.4 has an inverted penis head, 1.3 better" concerns the **LoKr** (`2818111`,
about 1.02 GB), not a checkpoint. The v1.3 behaviour is reachable only through the plain Klein
unet plus LoKr route, which ComfyUI reads natively. Our one test ran **4 steps at CFG 1 on a
base model** that wants about 50 steps, so it is untested, not disproven. fp8 is a named cause
of degradation, and the author recommends bf16; the diffusers LoKr path has a known bug, so do
not plan one (doc 21 §6.2 and §8).

**v1.4 was depth-trained for two people intermingled.** The author wrote: *"training against
depth. Considering how much of SNOFS is two people intermingled with close skin colors, it
seemed like a novel idea. It did seem to rapidly help with that sort of thing."* The caveat was
*"a bit of a texture issue on very close up images"*. The counterweight: *"I had versions that
took it further but it tended to have more broken anatomy"*. That is the strongest signal for
any single version, and newer is not monotonically better. The upgrade path is **v1.2 fp8 to
v1.4**, and **fp8 to bf16**. Nothing has A/B'd v1.4 here.

### 4.2 The anatomy fixer and the LoRA inventory
`klein_slider_anatomy.safetensors` (Civitai `2324991`, version `2615554`, "Klein 9B v1.5") is a
**concept slider, not a trigger-word LoRA**. The author's guidance: *"Weight 2.0 mostly keeps
the seed intact and can be used to fix minor glitches, 3.0 fixes some more prominent
artifacts."* Our node 82 runs it at 2.0. We have never tried 3.0 with a trimmed prompt; the
earlier sweep ran on the bad missionary prompt. Users report no effect at 1.0 to 3.0, and v1.5
drifts faces. The audit could not reproduce an extra foot in the six seed-sweep plates, so the
count claim is unsupported by our own sample.

No hands- or limb-specific Flux.2 Klein 9B LoRAs exist; only SDXL/Illustrious fixers. The Klein
Anatomy / Quality Fixer remains the only limb fixer for this base, newest v1.5. No newer Klein
SNOFS LoKr exists than `2960556`; later versions target Krea 2. Two cheap tests remain: a
**DPO** LoRA for waxy skin and limb issues, and a **PornMaster Flux2 Klein 9B base workflow**.
Neither is a verified fix.

### 4.3 Negative prompts at CFG 1
Black Forest Labs states that *"FLUX does NOT support negative prompts. Always describe what
you WANT, not what you don't want"*. That is a strong default for CFG-1 distilled sampling, not
an absolute [3]. The vendor line is not a technical spec, and adversarial verification refuted
the absolutist reading 1-2.

Our plates contradict the mechanism. The positive prompt's `LIMB OWNERSHIP: four legs and four
feet … no more and no fewer`, with node 67 enumerating `extra knee, third foot, two feet
growing from one leg`, is the strongest available anecdote, yet limb counting appears in
**16/16** plates, good and bad alike, with the strongest form only in the four that work.

1. **Plumbing, supported.** Node 67 wires a real negative encode into a
`CFGGuider` (node 63). At `cfg > 1` the negative is live; at 1.5 it carries a third of the
delta.
2. **Operating point, dead.** The distilled recommendation is CFG 1 at 4 steps,
where `pred = cond` and the negative contributes zero.
3. **Efficacy, measured wrong.** Our CFG grid ran 1.2, 1.3, and 1.5 and the
artifact survived, but those runs carried the position blacklist, so the negative was pushing
away from cowgirl, doggystyle, and spooning. The grid tests that negative, not negative text in
general. NAG remains the way to make negatives bite at few steps [4]. The author's
staged-sampler advice is cheaper: drop the turbo LoRA for the final steps so a negative can
bite.

### 4.4 Known failure modes
Community reports: missionary *"like 95% chance of body horror"*, cowgirl *"95% chance of
getting reverse"*, spooning *"nothing but amputee body horrors"*. Other reports: a doubled
object in the mouth, anatomy from the navel or knee, feet deforming. On v1.4, an inverted penis
head with v1.3 better; that is the LoKr route.

Two causes survived our own work, and neither is the prompt. The extra leg is a known model-
and pose-level defect on SNOFS. Shot scale is the other: plates that rendered put the figures
at 40 to 53 % of frame, and failing ones at 25 to 30 %. The canonical positions are not equally
hard. Doggystyle rendered for us; missionary-in-profile is the worst case.
## 5. The SDXL/Illustrious route
<a id="10-the-sdxl-migration-premise"></a>

### 5.1 Salad does not stock the models this route needs
The official Comfy recipe list is doc 14 §1, the `Official Salad Comfy recipes` row at
`docs/workflow/14-salad-comfy-live-findings.md:37`. It covers Dreamshaper 8, FLUX.1-Dev,
FLUX.1-Schnell, SDXL, and SD 3.5 Medium, but not Krea 2 [5]. The custom image that carries the
rest is doc 23 §1.

### 5.2 Illustrious-family reliability
**NoobAI-XL** is an Illustrious-family fine-tune, not a separate architecture [6]. A dedicated
two-person LoRA exists with trigger `2people`, but its author warns that weights **above 0.8
fall apart** and recommends **0.25 to 0.75** [7]. The **"Anatomy Helper"** fixer, trained on
333 images of women, is a single-body enhancer, not a two-body interlock guarantee [8].

**Hassaku XL v3 (WIP)** is unreliable for two-body scenes by its author's and users' reports:
extra people appear, `hugging` produces "sandwich hugging", **about 20 % of couple generations
gain an unwanted second male**, the second character is cut off even with `FULL BODY`, and
extra limbs appear [9].

Users report that without a helper LoRA, SDXL-family checkpoints return vaginal anatomy when
anal was requested **about half the time**. That is why genital and pose LoRAs exist, such as
Subtle Poses AnalSex XL3 and Anus/Vulva Helper XL [10].

### 5.3 Separating two partners
Two character LoRAs stacked normally blend into "one face that's a blend of both, in both
spots". The fix, per-region delta masking from §2 finding 3, is unavailable on SDXL because it
is Krea 2 only [1]. SDXL's equivalent is **regional conditioning**: **Forge Couple** [11],
**Regional Prompter** (only its Latent mode separates LoRAs) [12], and **Latent Couple** [13].
Identity injection is **PuLID** and **IP-Adapter**, neither a spatial or pose controller [14].
The research-grade answer for two personalized subjects in physical contact is **OMG** (ECCV
2024), a two-stage occlusion-friendly framework [15].

### 5.4 Pose control and interlock
**No concrete two-skeleton OpenPose recipe for SDXL at 1024 was verified** by either pass. No
node pack, preprocessor, handler, or documented limit for overlapping interlocked bodies was
found. Both passes name this the single highest-value unanswered operational question.

What does exist: an SDXL ControlNet trained on **DWPose** at 1024 for 15,000 steps [16];
preprocessors that emit multi-skeleton hints [17]; an editor with multi-person support [18];
and a two-character workflow whose author deprecates it [19]. **xinsir's OpenPose SDXL
ControlNet** reports mAP **0.357** against thibaud's **0.209**, but flags instability from the
default pose-line drawing [20].

No candidate SDXL model page evaluates interlocked two-body anatomy. JANKU and HomoSimile XL
were checked in full and contain none. The only anatomy statement found is the untested
promotional line *"Better anatomy (yes, even in complicated poses)"* [21]. Two-person pose
conditioning is **unverified, not unavailable**: couple pose packs exist, and Illustrious-XL
ControlNet OpenPose exists.

### 5.5 What SDXL has no verified answer for
Four of the nine required outputs have zero surviving evidence: **fixer LoRAs (requirement 3),
genital-act correctness (requirement 4), camera control (requirement 6), and style aftereffects
(requirement 7)**. Both passes re-confirm the finding as *"no verified tool"*, not *"verified to
be none"*. Per-partner identity (requirement 5) is not in that set: it has a verified failure
mode and a Krea-2-only fix, described in §5.3.

Camera angle has no SDXL path. The only camera-control node found emits camera-movement
instructions for an image-to-image LoRA that exists solely for **Qwen-Image-Edit-2509**; its
workflow contains no SDXL, Flux, Illustrious, Pony, or Klein checkpoint string. Requirement 6
has no verified answer in either family.

Peer-reviewed evidence also argues against the base architecture. On the HumanRefiner study
(ECCV 2024), frozen **SDXL 1.0 was the worst entry on abnormal-anatomy severity** except
HumanSD, on the HumanArt hard split: Abnormal Score **0.857** against SSD-1B 0.832,
Pose-T2I-Adapter 0.807, and HumanSD 0.801, with the worst LAION FID among non-HumanSD entries
(**30.024** against 16.465) [22]. It measures base SDXL 1.0 on single-person prompts, so it
does not settle the question, but it falsifies "SDXL lineage is anatomy-safe by itself".

A method note: **6 of the 18 confirmed claims are scoped negatives about web pages**. They
license *"no evidence for SDXL anatomy quality was found"*, never *"SDXL anatomy quality is
bad."*

## 6. The 3D route: anatomy by construction
### 6.1 DAZ to Blender
Genitals are added in DAZ Studio as a **geograft** plus shell and material, exported as a DBZ,
and **Merge Geografts** welds the hidden body vertices into a single seamless mesh. It is a
literal weld, not a generated approximation [23][24].

The operation is **vertex-number-based and destructive**. Morphs can no longer be imported
afterwards, all geografts must be merged in one pass, and the non-destructive Geometry Nodes
alternative cannot be exported to game engines. The documented order is to transfer the body's
shape keys onto the geograft before merging, save a `(CharacterName)BeforeFuse.blend`, run
Merge Geografts with **Rig Type MHX**, and fix clothing poke-through in Sculpt Mode
[23][24][25].

Rigify is poor at importing Daz poses. MHX is the compromise. **Simple IK** uses the Daz rig as
its base for a **100 %** match and exports better to game engines [26].

The community still pipeline is pose and export from Daz, import with Easy Import (BSDF,
Cycles), light with an HDRI, and set Film to Transparent. **8K stills took roughly 34 minutes
to 2 hours on a 6 GB RTX 3060** [25]. **Cryptomatte** supplies ID mattes with motion blur,
transparency, and depth of field [27].

**Penetration mechanics** are hand-keyed in the Maya or Blender rig. A developer thread
converges on hand-keying, *"by far the best results"*, with the same poster reporting that his
procedural attempts *"never came close to just manually animated scenes"* [28].

### 6.2 Engine route
Two engine paths are viable: a **procedural** one that maps penis-tip bone depth and direction
to morph shapes and adds an IK system, and an **animation-sync** one, the Unity VAM plugin
**"naturalis"** [29]. Exporting DAZ genitals to Unreal is unsolved because DazToUnreal loses
genital morphs; the fallback is **DAZ to Blender (Diffeomorphic) to Unreal** [30].

## 7. Operational constraints, whichever route is chosen
Salad's Container Gateway caps the server response at **100 seconds**, a Cloudflare hard limit,
and returns **524** [31]. The Client Request Timeout defaults to and caps at 100 seconds, and
neither can be changed after the container group is created. The Job Queue path has no timeout,
and webhooks are the async option on the gateway [32]. Our 120-second figure is a client or
proxy read timeout, not a Salad value.

Salad's product default is **3 replicas**. This repo's group recipe is **1 replica** (doc 23 §2.2)
until `/ready` is green. Use at least 3 for testing and at least 5 for production, since nodes
are interruptible without warning [31].

Hardware sizing as published for this family, generic model-class figures rather than two-body
measurements:

| Target | Min VRAM | GPU class | System RAM |
| --- | --- | --- | --- |
| SDXL | 12 GB | RTX 4070 Ti | 24 GB |
| SDXL + Refiner | 24 GB | RTX 4090 | 30 GB |
| Flux (fp8) | 16 GB | RTX 4090 | 24 GB |

Published SDXL figures are 5 to 15 s/image at 12 GB and 15 to 30 s at 24 GB with a refiner. The
SDXL-with-Refiner recipe is benchmarked at about **3,405 images/$** (about $0.000294/image,
about 9.6 s at 18 virtual users, 1024×1024, 20 base plus 5 refiner steps, single-person
workload), so it does not price the target workload [33].

The manifest downloads models before the instance serves traffic: `/ready` returns 503 until
the warmup workflow completes. Recipe images range from **6 GB** (Dreamshaper 8) to **16 GB**
(Flux) and can take tens of minutes to pull [31].

**One unet family per container group.** Repurposing `flux2-klein2` or `flux2-klein-5090` for
SDXL may be an operational no-go, and a new group is the practical choice.

## 8. Decisions this record produced
**Verify the LoRA URL; do not download.** A replica loads each LoRA from its URL when the Comfy
graph runs, so the only thing worth checking is that the URL is correct.
`generator.check_lora_urls(prompt)` runs after the Civitai token is attached and
before `POST /prompt`. It issues a `HEAD`, falling back to a one-byte ranged `GET` when a CDN refuses
`HEAD`. A definitive `401`, `403`, `404`, or `410` raises `RuntimeError` and names the LoRA. A
timeout, a 5xx, or a transport error is logged and the render proceeds. Logging uses
`request_json.lora_url_label` (`civitai:2615554`), never the URL, which carries `?token=`.
`model_catalog.should_autodownload` refuses `kind == "lora"`, so nothing new lands on local
disk.

The 100-second cap is **consistent with the 524 we reproduced**: a graph that must download a
LoRA at request time cannot be relied on to return inside 100 s. The URL check does not remove
that risk. All four house LoRA URLs resolve HTTP 200, so it would not have caught the 524; that
failure was duration inside the render. The LoRA fetch is also probably not the dominant cost. The catalog's 22 LoRA rows have a
**median of 165.7 MB**, and our four are **21, 21, 83, and 331 MB, 456 MB in total**. At the
**8 MB/s** seen on a slow node, that is roughly **3, 3, 10, and 41 s, about 57 s for all
four**, not the minutes implied by the 2.14 GB `UltraRealPhoto` file used for the cold-path
test. The better-supported reading is that the render sat near the cap already and the fetch
was the marginal extra. A smoke render with the LoRAs warm took **119.6 s**. If it recurs,
`POST /download` with `wait: true` measured **29.7 s** for a 2.14 GB cold file and
`completed in 0.0s` when cached. The cheaper thing to check first is whether the replica is being
restarted mid-session.

**Do not use `models.before_start`.** The research recommended it, but our repo deliberately
keeps it empty. `salad_klein/manifest.yaml` says:

> Empty: Salad's wrapper downloads `before_start` files one-by-one and that is
> what the startup probe was killing. `prefetch.py` pulls every selected unet
> plus the CLIP and VAE in parallel, then execs `comfyui-api`. Civitai LoRAs stay
> URL-loaded.

Salad's sequential `before_start` download caused a 25-minute startup (doc 15, "Startup-probe
death loop"), and `salad_klein/test_prefetch.py` asserts the manifest stays empty. Putting URLs
back would reintroduce a bug we already fixed.

**Rejected designs, one line.** Design 1 pre-checked `GET /models`, whose content-addressed
hashes never match a filename, so it polled 40 times 8 seconds, 320 seconds. Design 2 read
`/download`'s filename without `wait: true`, which returns the version id even when cached. The
contract was at `GET <gateway>/docs/json`.

## 9. What would change the answer
1. **A measured two-skeleton OpenPose recipe for SDXL at 1024**, including
control weights and behaviour on overlapping interlocked bodies. Both passes name this the
highest-value gap.
2. **Per-region LoRA-delta masking that accepts SDXL/Illustrious adapters.**
Today the implementations refuse them, and they also refuse Klein.
3. **Any published per-scene seed hit rate** for a diffusion configuration on
two-body interlock, from any family.
4. **A head-to-head of the three routes** on still quality, cost, and complexity:
SDXL/Illustrious (§5), 3D (§6: DAZ and Blender, Unreal plus MetaHuman, Unity and Unreal
procedural) [36], and the current Klein family (doc 21). No source ranks them, and the 3D
evidence is per-technique testimony, not a benchmark.

## 10. Coverage gaps and confidence
Both reports returned **Partial**. The gaps that matter here:

- No primary-source quantified two-body reliability report for realistic SDXL
merges such as Juggernaut XL or RealVisXL. WAI-Illustrious-SDXL v17 and Pony Diffusion V6 were
not verified from their own model cards. `dw_openpose_full` and DWPose as *the* full-body
preprocessor appeared only in secondary guides. No benchmark for "penetration in the wrong
orifice" exists.
- Salad sources are master-branch files and docs pages dated 2026-01-08, with no
live API call. Only the five recipe Dockerfiles and manifests in
`salad-recipes/recipes/comfyui` were enumerated, and `salad.com/models` omits flux1dev and
stablediffusion35medium that the docs page lists [34].
- **No Reddit source was inspected** (r/adultgamedev, r/nsfwdev). `docs.blender.org` was
Cloudflare-blocked, so Cryptomatte was used instead. The Diffeomorphic wiki was a navigation
stub, and cloth, soft-body coupling, and engine genital physics had no inspected source.
- One claim was excluded by verification: camera angle on Qwen-Image-Edit-2509,
in §5.5.
- No multi-person, interlocked, or human-human-interaction anatomy benchmark
exists anywhere. AbHuman (**56K images, 147K bounding-box anomalies, 18 detection classes**)
and HAD/HADM, Distortion-5K, BACON, and MagicBench are all built from single-subject images.
AbHuman's scorer should not be assumed to transfer to two-body plates [35]. The `rtmlib` route
was neither confirmed nor refuted.
- The source pool skews weak: most claims rest on Civitai pages or a 12-star
single-maintainer README, and only three on peer-reviewed papers. Krea 2 is about 3 months old,
so version specifics will decay in weeks.
- The coupling that is the whole migration premise remains unverified. "SDXL has
hand fixers" was never connected to "SDXL has interlocked anatomy".

The evidence does not support the migration, and it does not refute it either. What it
demolishes is the inference that SDXL-family is the mature answer. Nobody, including either
pass, has measured it for interlocked two-body anatomy. Meanwhile the two hard blockers
appeared: regional identity masking exists only for Krea 2 and refuses SDXL and Klein adapters,
and there is no SDXL camera-control path.

## Appendix A1. Sources
Numbered in the order they are first cited. External sources only; in-repo artifacts are named
in the text. All checked on 2026-09-22 and re-fetched on 2026-09-23.

| # | Source |
| --- | --- |
| 1 | RegioCraft; Nougan_Nodes; CliffNodes Krea2-Multi-Character-Lora-Node. https://raw.githubusercontent.com/zeus-onl/RegioCraft/main/README.md ; https://raw.githubusercontent.com/Winnougan/Nougan_Nodes/main/docs/regional-character-lora.md ; https://github.com/CliffNodes/Krea2-Multi-Character-Lora-Node-w-bounding-box |
| 2 | ComfyUI-QualityGate; Qwen3-VL; FakeVLM. https://github.com/nobu1990/ComfyUI-QualityGate ; https://huggingface.co/Shimin/qwen3_vl_8b_foreagent ; https://arxiv.org/abs/2510.10231 ; https://github.com/opendatalab/FakeVLM |
| 3 | BFL prompt rules. `black-forest-labs/skills`; https://docs.bfl.ml/guides/prompting_guide_t2i_negative |
| 4 | NAG. https://github.com/ChenDarYen/ComfyUI-NAG ; https://arxiv.org/abs/2505.21179 ; https://github.com/BigStationW/ComfyUI-NAG-Extended |
| 5 | Official Salad Comfy recipes. https://docs.salad.com/container-engine/reference/recipes/comfyui |
| 6 | NoobAI-XL 1.0. https://huggingface.co/Laxhar/noobai-XL-1.0 |
| 7 | Multiple People / (2) Two People or more, for Illustrious. https://civitai.com/models/2124063/multiple-people-2-two-people-or-more-for-illustrious |
| 8 | Anatomy Helper. https://civitai.com/models/1171869/anatomy-helper |
| 9 | Hassaku XL (Illustrious) v3 WIP. https://civarchive.com/models/140272?modelVersionId=2010753 |
| 10 | Subtle Poses AnalSex XL3; Anus/Vulva Helper XL. https://civarchive.com/models/1444070?modelVersionId=1919016 |
| 11 | sd-forge-couple. https://github.com/Haoming02/sd-forge-couple |
| 12 | sd-webui-regional-prompter. https://github.com/hako-mikan/sd-webui-regional-prompter |
| 13 | Latent Couple. https://github.com/opparco/stable-diffusion-webui-two-shot |
| 14 | PuLID (arXiv:2404.16022); IP-Adapter. https://arxiv.org/abs/2404.16022 ; https://github.com/ToTheBeginning/PuLID ; https://github.com/tencent-ailab/IP-Adapter |
| 15 | OMG (arXiv:2403.10983). https://arxiv.org/abs/2403.10983 |
| 16 | dimitribarbot/controlnet-dwpose-sdxl-1.0. https://huggingface.co/dimitribarbot/controlnet-dwpose-sdxl-1.0 |
| 17 | Fannovel16/comfyui_controlnet_aux. https://github.com/Fannovel16/comfyui_controlnet_aux |
| 18 | westNeighbor/ComfyUI-ultimate-openpose-editor. https://github.com/westNeighbor/ComfyUI-ultimate-openpose-editor |
| 19 | ComfyUI Multi-Subject Workflows. https://civitai.com/models/21100/comfyui-multi-subject-workflows |
| 20 | xinsir/controlnet-openpose-sdxl-1.0; NoobAI-XL ControlNet. https://huggingface.co/xinsir/controlnet-openpose-sdxl-1.0 ; https://civitai.com/models/929685 |
| 21 | JANKU; HomoSimile XL. https://civitai.com/models/1277670 ; https://civitai.com/models/964011 |
| 22 | HumanRefiner (ECCV 2024, arXiv:2407.06937). https://arxiv.org/abs/2407.06937 |
| 23 | Diffeomorphic import_daz, Setup_Finishing_Merge_Geografts. https://raw.githubusercontent.com/wiki/Diffeomorphic/import_daz/Setup_Finishing_Merge_Geografts.md |
| 24 | LoversLab, "Daz to Blender with Gens using Diffeomorphic (The Correct Way)". https://www.loverslab.com/topic/240639-daz-to-blender-with-gens-using-diffeomorphic-the-correct-way/ |
| 25 | F95zone, "DAZ to BLENDER basic setup + guide (feat. Diffeomorphic)". https://f95zone.to/threads/daz-to-blender-basic-setup-guide-feat-diffeomorphic.201085/ |
| 26 | Diffeomorphic import_daz, Setup_Rigging. https://raw.githubusercontent.com/wiki/Diffeomorphic/import_daz/Setup_Rigging.md |
| 27 | Psyop/Cryptomatte. https://github.com/Psyop/Cryptomatte |
| 28 | F95zone, "How do we do penetration mechanics in 3D games?" (Jun 2024). https://f95zone.to/threads/how-do-we-do-penetration-mechanics-in-3d-games.210650/ |
| 29 | Eroticissima, LoveTriggerSDK. https://www.eroticissima.wtf/sdk.html |
| 30 | F95zone, "About DazToUnreal workflow (+ gens tests)". https://f95zone.to/threads/about-daztounreal-workflow-gens-tests.135115/ |
| 31 | Deploy Image and Video Generation with ComfyUI. https://docs.salad.com/container-engine/how-to-guides/ai-machine-learning/deploy-stable-diffusion-comfy |
| 32 | Salad load balancing; long-running tasks. https://docs.salad.com/container-engine/explanation/gateway/load-balancer-options ; https://docs.salad.com/container-engine/explanation/job-processing/long-running-tasks |
| 33 | Salad SDXL benchmark. https://blog.salad.com/sdxl-benchmark/ |
| 34 | Recipes and Models. https://salad.com/models |
| 35 | AbHuman: 56K images, 147K bounding-box anomalies, 18 detection classes. https://huggingface.co/datasets/Enderfga/HumanRefiner |
| 36 | PRIMAL BONE; Lewd Metahuman Creator. https://primalbone.itch.io/metahuman-nude-female ; https://primalbone.itch.io/metahuman-nude-male-and-female ; https://fireblade185.itch.io/lewd-metahuman-creator |
