# 15. Custom Salad container group for Flux.2 Klein 9B

> **Status:** **prefetch5** is pushed and both Klein groups were PATCHed
> (2026-09-21, HTTP 200, `pending_change: true`). Until **version** bumps,
> GET still shows
> `docker.io/vkozyrev0/eldermark-klein:comfy0.35-api1.19.2-prefetch4`.
> Do not PATCH again while pending. prefetch5 adds the SNOFS distilled
> v1.2 fp8 UNET to the boot download. **prefetch4** remains the rgthree
> recipe those groups were running:
> `rgthree-comfy` is cloned **on this machine** and `COPY`'d into
> `/opt/ComfyUI/custom_nodes/rgthree-comfy` at **local `docker build`**,
> pin `2c5342a8cb0eaecaabf61435a5f37dd594c510ba`
> (`salad_klein/RGTHREE_COMMIT.txt`). `prefetch.py` stays
> **weights-only** (both Klein unets + CLIP + VAE; **no** `git clone`).
> Do **not** `FROM` a flux1dev tag and do **not** POST Klein graphs at
> loganberry. Mass catalog freeze in
> [`14-salad-comfy-live-findings.md`](14-salad-comfy-live-findings.md)
> still holds. Studio:
> [`salad_studio/README.md`](../../salad_studio/README.md).
>
> Liked style: https://civitai.com/images/135504982 =
> Klein 9B-Base **2322332@2612548** + Detail Slider **2334190@2625692**
> + Impressionism Klein9B **545264@2763568** (`ArsMJStyle, Impressionism`),
> Euler, 832×1216.

Secrets stay **out of git**: `~/.config/huggingface/token`,
`~/.config/civitai/token`, `~/.config/salad/key`. Those were passed as
Salad group env at create time, never into `Dockerfile` / `manifest.yaml`.

---

## Live groups

Org / project **`life-sim` / `default`**. Same prefetch image and probes
on both. Loganberry (`~/.config/salad/gateway`) is Flux.1. Do **not**
POST Klein graphs there.

Salad Studio Config profiles: **`klein`** and **`klein5090`** (seeded on
launch; gateway files `~/.config/salad/gateway-klein` and
`gateway-klein-5090`).

| | **Flux2 Klein** | **Flux2 Klein 5090** |
|---|---|---|
| Portal / API name | `flux2-klein` | `flux2-klein-5090` |
| Display | Flux2 Klein | Flux2 Klein 5090 |
| Studio profile | `klein` | `klein5090` |
| Image (showing) | `…-prefetch4` until pending clears | same |
| Image (patched) | `docker.io/vkozyrev0/eldermark-klein:comfy0.35-api1.19.2-prefetch5` | same |
| Gateway DNS | `apple-gadogado-5d0vs4l8x0j51hwy.salad.cloud` | `beet-ginger-cdz8ko9ehhmh4703.salad.cloud` |
| GPU classes | RTX **4090**, **3090 Ti**, **3090** (24 GB) | RTX **5090** (32 GB) + **5090 Laptop** (24 GB) |
| High $/hr | 0.33 / 0.19 / 0.17 | 0.50 / 0.235 |
| CUDA note | Ada/Ampere; known working | Blackwell test; Salad wants CUDA ≥ 12.8 (this image is **cuda13.0**) |
| Startup | `GET /health` :3000, delay 600, period 120, fail 20 (~50 min) | same |
| Readiness | `GET /ready` :3000 | same |
| Created | 2026-09-18; **v7** 2026-09-20 | 2026-09-20 **v1** |

Do **not** mix 5090 into `flux2-klein` until `flux2-klein-5090` has
`/ready` 200. First boot on either group still downloads ~17 GB HF
weights in parallel after the 12 GB image pull.

---

## Matching Civitai on-site quality

Civitai's website generator is **not** Comfy. A Civitai plate with
"Sampler: Euler, CFG 5, 40 steps, same seed" will **not** pixel-match
Salad even when those knobs are copied. The hosted path is
`engine: "flux2"` / `model: "klein"` with LoRAs as `{ airUrn: strength }`
and default **simple** schedule. Salad POSTs a Comfy 0.35 graph.

| Job | Civitai on-site | Salad Comfy (`/prompt`) |
|---|---|---|
| Sampler | their euler (flux2 or sdcpp) | `KSamplerSelect` euler → `SamplerCustomAdvanced` |
| Schedule | **simple** (API default) | `Flux2Scheduler` (resolution-aware shift) **or** `BasicScheduler` `simple` |
| CFG | `cfgScale` | `CFGGuider` |
| LoRA | native AIR map into their unet | stock `LoraLoader`. Studio **Convert still expands** `Power Lora Loader (rgthree)` → `LoraLoader`. On **prefetch4**, `/prompt` can instantiate `Power Lora Loader (rgthree)` and `Image Comparer (rgthree)` if left unexpanded. **LIVE prefetch3** does **not** have rgthree (Generate omits comparer from the POST). Studio has no comparer slider (headless API); `SaveImage` is the plate. |
| Seed | their RNG | `RandomNoise`. Same integer is **not** the same noise tensor |
| Output | their encoder | `VAEDecode` + JPEG quality 90 |

**What actually closes most of the oil-vs-ink gap** is the LoRA sitting
in the unet (Logs: HTTP **200** on the Civitai download URL, not 401),
not Euler/CFG/steps. Aged Art **1449678 @ 2795018** author range
**0.4–0.6**. Do not **Rebuild from Config** before Generate (it can swap
in Detail Slider).

Closest Comfy stand-in for Civitai's schedule: `BasicScheduler` with
`scheduler: "simple"` feeding `SamplerCustomAdvanced`'s `sigmas`.
`Flux2Scheduler` is the Comfy/BFL Klein default; it is "more correct"
for Klein and **not** what Civitai used.

Pixel clone of Civitai requires **their** engine (Orchestration API or
the website). Salad Studio **Import** converts a Civitai Comfy
`nodes`/`links` export + generation-data text into `/prompt` JSON;
that still runs **our** sampler stack.

---

## Two-body plate recipe (SNOFS distilled + anatomy stack)

> **SUPERSEDED 2026-09-23. Read [`21-klein-image-handoff.md`](21-klein-image-handoff.md) instead.**
> This section presents a 4-LoRA / 6-step / 5,049-char sectioned-prompt stack as
> *the* shipped plate recipe, and states that "the prompt architecture is the
> quality lever". Both are wrong as of the 2026-09-22 session:
>
> - The only recipe a **human has judged** is the one
>   `salad_klein/prompt_ledger.json` records under `verdicts`,
>   `prompt_snofs_distilled_v12.json`, **no LoRAs**, 4 steps, CFG 1, and a
>   **779-char** prompt, not 5,049.
> - The measured finding is that the **seed dominates** (2 of 7 seeds
>   acceptable), not the wording. A 4-LoRA stack was tested against no LoRAs
>   (`full` vs `alone`) and **both were bad**. The stack was never the lever.
> - `prompt_snofs_distilled_anatomy*.json` remain on disk as the record of what
>   was tried; no human verdict covers them.
>
> What still holds below: the **group setup**, the prefetch design, the startup
> probe, and the `_meta`-on-`LoraLoader` rule. What does not: the recipe, its
> weights, and the prompt-architecture claim.

`salad_klein/prompt_snofs_distilled_anatomy.json` (euler, 6 steps)
and `prompt_snofs_distilled_anatomy_resms.json` (res_multistep, 12 steps) are
the shipped two-body plates: **18+ only**, adults. Same graph, same LoRA stack,
two sampler knobs. Both were rendered end-to-end on the Klein group before
shipping (see **How these numbers were settled** below). This section is a
measurement report, not a recipe handed down from a model card.

| Knob | Value | Why |
|---|---|---|
| unet | `snofsSexNudesAndOther_distilledV12KleinFp8.safetensors` | **SNOFS is the unet on this group**, not a LoRA. Its distilled v1.2 cut is the checkpoint the plate look was built on |
| steps | 6 (euler) / 12 (res_multistep) | Distilled cut: more steps add time, not anatomy. 4 is the floor, 6–12 the working band |
| CFG | 1 (`CFGGuider`) | Guidance-distilled. CFG 5–7 on this graph is not a style choice, it is a broken render |
| size | 832×1216 portrait | `EmptyFlux2LatentImage` and `Flux2Scheduler` must **agree**, or the schedule is wrong for the latent |
| sampler | `KSamplerSelect` euler / res_multistep → `SamplerCustomAdvanced` | euler 6 is the fast check; res_multistep 12 the keeper |
| seed | `823441907752101` | Same seed in both files, so the two files differ only in the sampler knobs |

**The stack** (`LoraLoader` chain 70→80→81→82→83; each `lora_name` is a Civitai
download URL, so the Tokens tab's `?token=` is appended at POST. Logs show
HTTP **200** vs **401**; all four resolve 200 on the live group):

| Node | LoRA | Weight | Role |
|---|---|---|---|
| 80 | Klein Detail Slider (`civitai:2334190@2625692`) | **-1.5** | Pushes texture away from the 3D-render look |
| 81 | Klein Fixes NSFW (`civitai:2482439@2790993`) | **1.0** | Vulva / anus / pubic-hair fixes |
| 82 | Klein Anatomy / Quality Fixer v1.5 (`civitai:2324991@2615554`) | **2.0** | Extra limbs, fused legs, glitches (3.0 for prominent artifacts) |
| 83 | General Penis LoRA v1.0 (`civitai:2333479@2624854`) | **0.8** | Male anatomy. Trained words: penis / erect / flaccid / foreskin / hung / uncircumcised. **Name the type in the prompt** |

The last loader takes both `CLIPTextEncode` nodes, so the tail of the chain is
where new LoRAs go.

### How these numbers were settled

The first version of this recipe followed the usual advice. Klein 9B **base**,
12–20 steps, CFG 1.3, SNOFS LoKr 0.3–0.7, a short photographic prompt. It
rendered plaster mannequins: no heads, limbs fused into single tubes, no
genitalia, an overall 3D-render look. Eight renders isolated the cause
(`target/klein_ab/ab.py`, gitignored scratch):

| Render | Graph | Prompt | Result |
|---|---|---|---|
| control | house distilled graph, 4 steps | house sectioned prompt | the painted plate (baseline) |
| **c1** | **house distilled graph** | **short photographic prompt** | **plaster, headless, fused limbs** |
| c2 | base unet, 12 steps, cfg 1.3 | house sectioned prompt | painterly, but limbs mushy and the man's head missing |
| c3 | distilled, 6 steps, cfg 1, anatomy + male LoRA | house sectioned prompt | clean plate |
| c4 | c3 + detail slider + NSFW fix | house sectioned prompt | clean plate, best of the five |
| c5 | c4 on res_multistep / 12 | house sectioned prompt | clean plate |

Two conclusions, both measured rather than argued:

1. **The prompt architecture is the quality lever, and the graph is not.**
   c1 has the *proven* graph and still produced the failure. The only
   difference from the control is the prompt text. A short photographic
   paragraph with a placeholder token left in it is not a prompt this stack can
   render. The house prompt is **sectioned**, `STYLE:` / `SUBJECTS:` /
   `WOMAN:` / `MAN:` / `LIMB OWNERSHIP:` / `INTIMACY:` / `ANATOMY:` /
   `DETAIL:` on the positive side, `STYLE:` / `DETAIL FAILURE:` /
   `POSE FAILURES:` / `LEG SIDE ERRORS:` / `LEG ERRORS:` / `LIMB ERRORS:` /
   `BODY FUSION:` / `SEX ACT ERRORS:` on the negative, and it spells out
   *whose limb is where*, names heads, and counts feet and toes. Both files
   ship that text verbatim, because paraphrasing it is how this went wrong.
2. **Base 9B is not the better cut for this group.** c2 (base, CFG 1.3, the
   SNOFS LoKr's plain-Klein route) is visibly worse than every distilled
   render. To try the base route anyway: set node 70's `unet_name` to
   `flux-2-klein-base-9b-fp8.safetensors`, add the SNOFS LoKr
   (`civitai:1972981@2960556`) at 0.5, and raise steps to 12–20 at CFG 1.3.

### LoRA weights: what the sweep found

One render per weight is not evidence, so the weights in the research's ranges
were swept twice, once at the recipe seed (`target/klein_ab/sweep.py`) and
then across two fresh seeds (`target/klein_ab/seeds.py`), changing one weight
at a time.

| Knob | Range swept | Finding |
|---|---|---|
| Anatomy fixer | 1.5 / **2.0** / 3.0 | Every weight held at every seed. The fixer's effect here is *preventive*, not visible: at these seeds the prompt already prevented the failures it repairs. Keep 2.0; reach for 3.0 when a plate actually shows an artifact, and then expect a slightly smoother, less painted surface |
| Male LoRA | 0.6 / **0.8** / 1.0 | All three render clean genitals. 0.8 is the middle of the trained range and the shipped default; 1.0 is a fine alternative, not an overdrive |
| Detail slider | **-1.5** | Negative weight is deliberate: it is what keeps the surface off the 3D-render look |
| SNOFS LoKr | absent / 0.3 / 0.6 | At 0.3 on top of the SNOFS-distilled unet the render is fine (subtly different texture), so it is **safe but redundant**. The unet already is SNOFS. The LoKr belongs to the *plain* Klein unet route above |

Honest limit: the sweep tests a favourable pose at three seeds, so it establishes
"these weights do not break the plate", not "2.0 measures better than 1.5".
Failure-rate claims need artifact-prone seeds, and the cheapest way to get one
is to rerun a bad plate's seed with the fixer at 3.0.

### The pose block, and the rule about placeholders

`WOMAN:` / `MAN:` / `INTIMACY:` are one block: the pose. The shipped text is the
missionary plate that rendered the reference images, so the file works pasted
as-is. For another position, rewrite those three sections, and name the
position in SNOFS's own vocabulary (**missionary / doggystyle / cowgirl /
spooning / prone**), because that is what it was trained on. "She lies on her
back with her left thigh lifted over his right hip" is a description; the
position name is the trigger.

**Never leave a placeholder token in the text.** `REPLACE_THIS_POSE` inline in
the middle of the sentence was part of what produced the plaster render: the
model reads an unknown all-caps token mid-sentence and adherence collapses. A
half-filled pose line is worse than a full one. `test_klein_recipes.py` fails
on `REPLACE_THIS`, `TODO`, `TBD`, `XXX`, `FIXME` and angle brackets for exactly
this reason.

### The Back Pose Enhancer (sitting / back-facing only)

`civitai:2335408@2627022` (`1A_Back_Pose_Enhancer.safetensors`) is the cowgirl
weak spot: sitting with a back to the camera. **1A** is the author's general
default, 1C is `2627093`, the MLX builds are for Mac. Splice it in at **~1.0**
at the tail. New node `84`, and rewire `63.model` to `["84", 0]`:

```json
"84": {
  "class_type": "LoraLoader",
  "inputs": {
    "model": ["83", 0], "clip": ["83", 1],
    "lora_name": "https://civitai.com/api/download/models/2627022",
    "strength_model": 1.0, "strength_clip": 1.0
  },
  "_meta": { "title": "1A_Back_Pose_Enhancer.safetensors", "base": "Flux.2 Klein 9B" }
}
```

It is **not** in the shipped files: the template is pose-agnostic.

### `_meta` on every `LoraLoader`

Keep the `_meta.title` / `_meta.base` blocks when you edit these files. They are
not decoration: `request_json.lora_is_klein_clip` decides where the two
`CLIPTextEncode` nodes run, after the **last Klein-native** loader, or on the
base Qwen loader, and it matches Klein tokens in `_meta` *or* in `lora_name`.
A bare `https://civitai.com/api/download/models/<id>` URL matches neither, so
without `_meta` the POST copy moves both encodes back to the Qwen loader at
`["71", 0]`.

What that is worth, measured: the house plates have always been made that way
(four bare-URL LoRAs, no `_meta`), and the control render is one of them, so
the dropped CLIP-side weights are **not** what made the bad plates. It is a
latent correctness issue. The LoRAs' text-side contribution silently does not
apply, not a proven regression. `_meta` costs nothing and makes the intent
explicit, so it stays.

### Pose control is not available on the replica

`ReferenceLatent` is dropped/rewired by Generate, local `LoadImage` files are
omitted, and there is no OpenPose / DWPose / ControlNet in the repo or the
image, so the `refcontrol-FLUX.2-Klein-9B-reference-pose` route cannot run
here. Pose is controlled by the prompt block above and by regenerating at a new
seed, not by a pose graph. Hard insertion plates are still Lustify/SDXL work,
not Klein.

`python -m unittest test_klein_recipes` from `salad_studio` drives
both files through the Studio Validate gate and the POST copy (24 tests).

---

## Image prefetch (keep the Docker image small)

Do **not** `COPY` the ~17 GB Klein weights and do **not** `RUN unzip`
in the Dockerfile. That bakes uncompressed tensors into a ~30 GB
layer. fp8 `.safetensors` barely shrink when zipped.

**Image (12 GB):** Salad Comfy runtime + `prefetch.py` + empty
`manifest.yaml` `before_start: []` + **prefetch4** `COPY` of
`rgthree-comfy` (cloned **locally**, pin
`2c5342a8cb0eaecaabf61435a5f37dd594c510ba`; not a Salad `git clone`).

**First boot (ENTRYPOINT, not a build step). Weights only, no custom-node clone:**

1. If a sidecar `.zip` exists, or a zip was misnamed `*.safetensors`,
   inflate to the real Comfy filename (`weights_zip.ensure_safetensors`).
   Comfy never loads a `.zip`.
2. Else `huggingface_hub` downloads **five files in parallel**:
   - `flux-2-klein-base-9b-fp8.safetensors` → `diffusion_models/`
   - `flux-2-klein-9b-fp8.safetensors` → `diffusion_models/` (distilled)
   - `snofsSexNudesAndOther_distilledV12KleinFp8.safetensors` →
     `diffusion_models/` (SNOFS distilled v1.2 fp8, from
     `https://huggingface.co/edwixx/Flux2Klein9B_SNOFS/resolve/main/snofsSexNudesAndOtherFunStuff_distilledV12Fp8.safetensors`)
   - `qwen_3_8b_fp8mixed.safetensors` → `text_encoders/`
   - `flux2-vae.safetensors` → `vae/`
3. `exec` `./comfyui-api`. `/health` stays down until this finishes.

Salad's old sequential `before_start` list is what the **25-minute**
startup probe was killing (unet 19 min at 8 MB/s, then CLIP, then
interrupt). Parallel is about **max(unet, CLIP)** on that node. The
live startup window is **~50 min** (delay 600 + 20×120).
`timeout_seconds` (10) is only how long **one** GET `/health` may hang.

This PC can cache the same files in gitignored `art/model-cache/hf/`:

```
python model_catalog.py fetch-klein --stage
```

Salad never sees that folder. Zip/unzip there is **local disk only**.

Rebuild + push (**recipe prefetch4**; live groups may still be prefetch3 until PATCH):

```powershell
git clone --depth 1 https://github.com/rgthree/rgthree-comfy.git salad_klein/custom_nodes/rgthree-comfy
docker build -t vkozyrev0/eldermark-klein:comfy0.35-api1.19.2-prefetch4 salad_klein
docker push vkozyrev0/eldermark-klein:comfy0.35-api1.19.2-prefetch4
```

Then set the group Image Source to that tag (portal **Edit**, or PATCH
`container.image`). A PATCH may return 200 with the old tag still
showing until `pending_change` clears and **version** bumps.
2026-09-20: `prefetch4` was **built and pushed**; PATCH on `flux2-klein-5090`
and `flux2-klein2` returned 200 with `pending_change: true` and GET still
listing **prefetch3** until that clears. Do not PATCH again while pending.

---

## Salad Studio

Windows helper `python -m salad_studio` from the repo root (not
`eldermark`). Tabs: **Config**, **Policy**, **Tokens**, **LoRAs**,
**Prompt Editor**, **Prompt**, **Import**, **Prompt History**, **Logs**.

| Tab | Role |
|---|---|
| Config | Gateway, graph, LoRA checkboxes. Salad status badge (one word; **only Ready is green**; poll ~15 s; instance pull/create beats a stale `/ready` 200) |
| Policy | Load live Salad probes (including portal edits); Apply PATCHes probes only, not the Docker image. Right-side blurbs inject delay/period/fail/~total seconds |
| Tokens | `studio-tokens.json` (gitignored). Generate appends Civitai `?token=` on LoRA URLs |
| LoRAs | Catalog + extras; wrapping checkboxes |
| Prompt Editor | Exact `/prompt` JSON. Graph pane: **JointJS HTML** in WebView2 ([`16-salad-studio-prompt-graph.md`](16-salad-studio-prompt-graph.md)). Validate. Rebuild from JSON. Do **not** Rebuild from Config if you pasted a custom graph |
| Prompt | CLIP text when Config rebuilds JSON |
| Import | Paste Civitai **generation data** and/or Comfy **workflow JSON**. Convert keeps site node ids. It still **expands** `Power Lora Loader (rgthree)` to stock `LoraLoader` (same id) so graphs run on **LIVE prefetch3**. Other replica-missing types (`Image Comparer (rgthree)`, `ReferenceLatent`, notes) stay as-is (**warnings**, not rewrites); Generate omits them from the Salad POST. **prefetch4** can instantiate `Image Comparer (rgthree)` and `Power Lora Loader (rgthree)` if left unexpanded; Studio has no comparer slider; `SaveImage` is the plate. **Clear Import** drops the paste; workflow JSON is held in memory. |
| Prompt History | Full request JSON on disk. Table: When / Prompt / Graph (node count, LoRAs, size, steps, cfg, sampler). Double-click restores JSON + prompt, no Config rebuild |
| Logs | HTTP; Cloudflare 521/522 called out; `/ready` pre-probe on Generate |

Rebuild the replica **only** for new files or custom nodes. Probe
timing, replica count, env, and `/prompt` JSON are portal / Policy /
Prompt Editor.

---

## Startup-probe death loop (why prefetch exists)

On a slow node the unet alone took **~19 min at 8 MB/s**. Sequential
`before_start` then started Qwen CLIP (~8 GB). The old window was
**300 + 20×60 = 25 min**. Salad **Instance Interrupted (Startup Probe
Failure)** at ~25 min, then `Cache populated with 0 files` and the
same three downloads started again, even on the **same** machine.

`failure_threshold` max is **20**, `period_seconds` max is **120**.
Live startup: delay **600**, period **120**, fail 20 → **~50 min**.
Do not raise `timeout_seconds` expecting a longer boot.

### First-boot logs (CSV + container stdout)

Downloaded system events:
`Downloads/flux2-klein-logs-9_18_2026, 8_12_34 PM.csv`. **Instance
controller only** (`Text Log` empty). Timeline on machine
`40624151-…` (RTX 4090):

| Time (UTC) | Event |
|---|---|
| 23:55:08 | Container Group Started |
| 00:00:11 | Instance Allocated |
| 00:00:14 | Instance Downloading (the 12 GB image) |
| 00:09:12 | Instance Starting |
| 00:11:26 | Instance Running |
| 00:11:42 | **Instance Exited:1 (Error)** (~16 s after Running) |
| 00:11:49–00:14:28 | crash loop: Exited:1, then Starting again |

Portal "dying in Starting" is that loop. It **did** reach Running;
Salad then respawns. `/ready` stayed 503 (gateway: "Your Container /
Error").

Container stdout (Salad log-entries, not in the CSV):

1. `hf` CLI traceback (`huggingface_hub` 1.16.1, `click.exceptions.Exit: 0`).
2. Wrapper fell back to **HTTPStorageProvider** for
   `https://huggingface.co/black-forest-labs/FLUX.2-klein-base-9b-fp8/resolve/main/flux-2-klein-base-9b-fp8.safetensors`.
3. **`Failed to start server: Download failed (401)`**. Gated BFL unet;
   HTTP fetch did not send `HF_TOKEN` (token was on the group env, but
   HTTP provider does not use it; CDN redirects also strip `Authorization`).

**v2 (`…-hf`, 2026-09-19):** `hf` CLI **did** run (`HFStorageProvider`).
New crash, still ~8 s after Running, still **Exited:1**:

> `hf download … black-forest-labs/FLUX.2-klein-base-9b-fp8`
> `Error: Access denied. This repository requires approval.`

Token is present; the **BFL gated license is not accepted** on
https://huggingface.co/black-forest-labs/FLUX.2-klein-base-9b-fp8
for that Hugging Face account. Group was **stopped** after the loop.
`/ready` 404.

**v2 after license accept (2026-09-19 ~01:03–01:08 UTC):** gated download
**worked**. Comfy 0.35.0 started on a 4090 (`To see the GUI go to:
http://*:8188`). **~4 s later `Instance Exited:1`**. Too fast for a
Klein render. Wrapper logs in that window are empty; local docker
repro: wrapper **exits 1 whenever Comfy exits**. Likely
`WARMUP_PROMPT_FILE` parse/submit right after listen. Image
`…-nowarm` drops baked warmup and sets `--listen 0.0.0.0`. Local HTTP
`/health` cannot pass on this box (no NVIDIA driver).

---

## Why a custom group

Salad's official Comfy recipes are Dreamshaper 8, FLUX.1-Dev,
FLUX.1-Schnell, SDXL, SD 3.5 Medium. **Klein is not on that list.**

The live Flux.1 graph is `CheckpointLoaderSimple` + `FluxGuidance` +
`EmptySD3LatentImage`. Klein T2I is `UNETLoader` + `CLIPLoader` type
`flux2` + `VAELoader` + `EmptyFlux2LatentImage` + `Flux2Scheduler` +
`SamplerCustomAdvanced`. A second ~12–17 GB unet next to baked Flux.1
**OOMs** a 24 GB 4090 / Cloudflare **524**.

Do **not** POST a Klein graph at loganberry. Do **not** `FROM` a
`…-flux1dev` Salad tag (that image already holds Flux.1-dev fp8).

---

## What you will run

| Piece | Value |
|---|---|
| Base image | `ghcr.io/saladtechnologies/comfyui-api:comfy0.35.0-api1.19.2-torch2.13.0-cuda13.0-runtime` |
| Published image (recipe) | `docker.io/vkozyrev0/eldermark-klein:comfy0.35-api1.19.2-prefetch4` (rgthree COPY at build; weights still not baked) |
| Published image (live) | `…-prefetch3` until the group Image is PATCHed |
| Salad org / project | `life-sim` / `default` |
| Group name | `flux2-klein` (gateway file `~/.config/salad/gateway-klein`) |
| Comfy | **0.35.0** (has `EmptyFlux2LatentImage` / `Flux2Scheduler`) |
| API wrapper | **1.19.2** (same family as loganberry's `/docs`) |
| Unet | `flux-2-klein-base-9b-fp8.safetensors` **and** `flux-2-klein-9b-fp8.safetensors` (BFL, gated) into `diffusion_models/` |
| CLIP | `qwen_3_8b_fp8mixed.safetensors`, type `flux2` |
| VAE | `flux2-vae.safetensors` |
| LoRAs | **Not** baked. Job JSON `LoraLoader` Civitai URLs (Aged Art **2795018**, etc.) |
| GPU | **1× RTX 4090 24 GB**, 30 GB RAM. Not shared with Flux.1 |
| Access | Container Gateway port **3000**, `Salad-Api-Key` |
| First replica | **1** (smoke). Salad's 3-replica advice is for uptime, not the first boot |

This machine has **Docker Desktop 29.8** (~47 GB RAM, nvidia runtime
registered) but **no `nvidia-smi`**. Use Docker to **build and push**.
Do not expect `docker run --gpus all` to generate here; the 4090 on
Salad is the GPU test.

Build files: `salad_klein/` (`Dockerfile`, `manifest.yaml`,
`prefetch.py`, `weights_zip.py`, `prompt_liked_style.json`).
`before_start` is **empty**; do not put sequential HF URLs back.

---

## How this group was created (this session)

Executed on the Windows box (Docker Desktop **29.8**, logged in as
Docker Hub **`vkozyrev0`**). No local NVIDIA GPU (`nvidia-smi`
missing). Docker was **build + push only**.

1. **Recipe files** in `salad_klein/`: `Dockerfile` (FROM the
   Salad **runtime** tag, not `flux1dev`), `manifest.yaml` (HF Klein
   fp8 unet + `qwen_3_8b_fp8mixed` + `flux2-vae` + Civitai LoRAs
   **2625692** / **2763568**), `warmup_prompt.json`,
   `prompt_liked_style.json`.
2. **Build** (image ~12 GB = Comfy runtime; Klein weights **not** baked).
   Clone `rgthree-comfy` locally first; current tag is **prefetch4**:
   ```
   git clone --depth 1 https://github.com/rgthree/rgthree-comfy.git salad_klein/custom_nodes/rgthree-comfy
   docker build -t vkozyrev0/eldermark-klein:comfy0.35-api1.19.2-prefetch4 salad_klein
   ```
   Base: `ghcr.io/saladtechnologies/comfyui-api:comfy0.35.0-api1.19.2-torch2.13.0-cuda13.0-runtime`.
3. **Push** (Docker Hub repo is **public**; Salad can pull without
   registry credentials):
   ```
   docker push vkozyrev0/eldermark-klein:comfy0.35-api1.19.2-prefetch4
   ```
4. **Create group via Salad API** (not the Portal form, not an edit of
   loganberry). Org/project `life-sim` / `default` (the public API does
   not list orgs; this pair was confirmed by listing existing groups).
   GPU class **RTX 4090 (24 GB)**
   `ed563892-aacd-40f5-80b7-90c9be6c759b`. `POST
   …/organizations/life-sim/projects/default/containers` with name
   `flux2-klein`, 1 replica, autostart on, gateway port **3000**, auth
   on, least-connection, 4 vCPU / 38912 MB RAM, env `HF_TOKEN` +
   `CIVITAI_API_TOKEN` from `~/.config/`. Startup `GET /health`,
   readiness `GET /ready`.
5. **Gateway file** (new, not overwriting loganberry):
   `~/.config/salad/gateway-klein` →
   `https://apple-gadogado-5d0vs4l8x0j51hwy.salad.cloud`.
6. **First boot** (portal): instance **DOWNLOADING** the 12 GB image on
   a residential 4090, 0/1 Ready. After the image pull, the replica
   still has to fetch Klein weights from Hugging Face (~10 GB) before
   `/ready` is 200.

Reuse the numbered recipe below to rebuild or clone. Do not `FROM` a
`…-flux1dev` tag.

---

## Step-by-step (rebuild)

### 0. One-time accounts

1. Hugging Face: open
   https://huggingface.co/black-forest-labs/FLUX.2-klein-base-9b-fp8
   and **accept the BFL license**. Without that, the unet URL 401s.
2. Confirm tokens exist (already on this box):
   `~/.config/huggingface/token`, `~/.config/civitai/token`,
   `~/.config/salad/key`.
3. Pick a container registry you can push to (Docker Hub or GHCR).
   Example below uses Docker Hub as `YOURUSER/eldermark-klein`.

### 1. Build the image (local Docker)

From the repo root (PowerShell):

```powershell
cd src\tools\salad_klein
git clone --depth 1 https://github.com/rgthree/rgthree-comfy.git custom_nodes/rgthree-comfy
docker build -t YOURUSER/eldermark-klein:comfy0.35-api1.19.2-prefetch4 .
```

The image stays small: Klein **weights are not baked**. `rgthree-comfy`
**is** `COPY`'d at this local build (pin
`2c5342a8cb0eaecaabf61435a5f37dd594c510ba`). `prefetch.py` (ENTRYPOINT)
downloads unet + CLIP + VAE **in parallel** when the replica starts
(`HF_TOKEN` in the group env). **No** `git clone` on Salad. Empty
`before_start`. Salad's sequential manifest download is what the
startup probe was killing.

Do not `COPY` or `RUN unzip` the tensors in the Dockerfile. Zip is
transport only; inflate at start to the real `.safetensors` path.

### 2. Optional local API check (no GPU)

Without a local NVIDIA GPU you can still confirm the image starts far
enough to print Comfy's boot log:

```powershell
docker run --rm -p 3000:3000 `
  -e HF_TOKEN=(Get-Content $HOME\.config\huggingface\token -Raw).Trim() `
  YOURUSER/eldermark-klein:comfy0.35-api1.19.2-prefetch4
```

Expect a long first download or a CUDA error. Either is fine for this
box. `/ready` going 200 is a **Salad 4090** check, not this laptop.

If you later have a 24 GB NVIDIA GPU:

```powershell
docker run --rm --gpus all -p 3000:3000 -p 8188:8188 `
  -e HF_TOKEN=(Get-Content $HOME\.config\huggingface\token -Raw).Trim() `
  YOURUSER/eldermark-klein:comfy0.35-api1.19.2-prefetch4
```

Then `GET http://localhost:3000/ready` until 200, and POST
`prompt_liked_style.json` at `/prompt`.

### 3. Push

```powershell
docker login
docker push YOURUSER/eldermark-klein:comfy0.35-api1.19.2-prefetch4
```

### 4. Create the Salad container group (Portal)

https://portal.salad.com. **New** group, not an edit of loganberry.

| Field | Set |
|---|---|
| Image | `YOURUSER/eldermark-klein:comfy0.35-api1.19.2-prefetch4` (private registry: add pull credentials) |
| GPU | RTX 4090 (24 GB). Priority Lowest is fine for probes |
| vCPU / RAM | 4+ / **30 GB** |
| Replicas | **1** until `/ready` is green |
| Container gateway | **On**, port **3000**, least-connection |
| Auth | **On** (`Salad-Api-Key`) |
| Startup probe | `GET /health`, delay **600**, period **120**, fail **20** (~50 min). `timeout_seconds` is per-GET, not the boot window |
| Readiness probe | `GET /ready` |
| Env | `HF_TOKEN` = Hugging Face token; `CIVITAI_API_TOKEN` if Civitai 401s; `STARTUP_CHECK_MAX_TRIES=120` (already in the Dockerfile, keep it) |

Leave loganberry (Flux.1-Dev) running if you still need Flux.1 probes.
Two groups = two GPU-hour bills.

### 5. Wait for Ready

First replica will pull the **12 GB image**, then `prefetch.py` (~17 GB
HF in **parallel**). That can take tens of minutes on a residential
node. `/ready` stays 503 until Comfy listens. Do not POST until Ready
is green. Studio's badge follows instance state (Downloading N%), not
a leftover `/ready` 200.

If the replica loops 503 / never Ready: Salad logs. Typical failures:
HF license not accepted, missing `HF_TOKEN`, OOM (you used a flux1dev
base image or a 12 GB GPU), Comfy missing Klein nodes (old `comfy0.7.0`
tag).

### 6. Smoke the liked stack

Save the group URL (Salad access domain) to a **new** file, not
`~/.config/salad/gateway` (that file is loganberry):

```
~/.config/salad/gateway-klein
```

```powershell
$gw = (Get-Content $HOME\.config\salad\gateway-klein -Raw).Trim()
$key = (Get-Content $HOME\.config\salad\key -Raw).Trim()
# edit prompt_liked_style.json: replace REPLACE_THIS_PROMPT
curl.exe -sS -X POST "$gw/prompt" `
  -H "Content-Type: application/json" `
  -H "Salad-Api-Key: $key" `
  --data-binary "@salad_klein/prompt_liked_style.json" `
  -o klein-out.json
```

Decode `.images[0]` to a JPEG. Trigger words in the positive prompt:
`ArsMJStyle, Impressionism`. Sampler Euler, 832×1216. Public CivitAI
meta on 135504982 is hidden. This stack is the public resource list,
not a pixel clone.

Cloudflare gateway timeout is still **~100 s**. 20-step 832×1216 Klein
on a 4090 should fit; if it 524s, drop steps on the first smoke or use
the Job Queue pattern in Salad's Comfy deploy guide.

### 7. After it works

- Scale replicas only if you will actually queue jobs.
- Keep `salad_PAUSE.txt`. Do not point `salad_catalog_faces.py` at this
  group until Klein is an explicit **chosen** house in doc 14.
- Do not load Flux.1 / Krea / SDXL checkpoints into this image.

---

## Graph (what `/prompt` must send)

Comfy-Org template `image_flux2_text_to_image_9b.json`, API-shaped:

- `UNETLoader` → `flux-2-klein-base-9b-fp8.safetensors`
- `CLIPLoader` → `qwen_3_8b_fp8mixed.safetensors`, **type `flux2`**
- `VAELoader` → `flux2-vae.safetensors`
- `LoraLoader` only when the job JSON asks for them (Civitai URL). Detail Slider / Impressionism are **not** pre-downloaded.
- `EmptyFlux2LatentImage` + `Flux2Scheduler` **or** `BasicScheduler`
  (`simple`, closer to Civitai) + `KSamplerSelect` euler + `CFGGuider`
  + `SamplerCustomAdvanced`

Not `CheckpointLoaderSimple`. Not `EmptySD3LatentImage`. Not
`FluxGuidance`.

---

## Pointers

- Live Flux.1 ops / freeze: [`14-salad-comfy-live-findings.md`](14-salad-comfy-live-findings.md)
- Salad Studio: [`salad_studio/README.md`](../../salad_studio/README.md)
- Salad custom Comfy: https://docs.salad.com/container-engine/how-to-guides/ai-machine-learning/deploy-stable-diffusion-comfy
- Image tags: https://github.com/SaladTechnologies/comfyui-api/pkgs/container/comfyui-api
- Klein 9B template: https://github.com/Comfy-Org/workflow_templates/blob/main/templates/image_flux2_text_to_image_9b.json
