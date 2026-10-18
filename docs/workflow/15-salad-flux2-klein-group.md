# 15. Custom Salad container group for Flux.2 Klein 9B

> **Current tags:** the Live groups table below lists the shipped
> `...-prefetch6-klein` and `...-prefetch6-snofs` tags. The notes below record
> the 2026-09-21 PATCH.
>
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
| Portal / API name | `flux2-klein2` | `flux2-klein-5090` |
| Display | Flux2 Klein | Flux2 Klein 5090 |
| Studio profile | `klein` | `klein5090` |
| Image (showing) | `…-prefetch6-klein` | `…-prefetch6-snofs` |
| Image (patched) | `docker.io/vkozyrev0/eldermark-klein:comfy0.35-api1.19.2-prefetch6-klein` | `…-prefetch6-snofs` |
| Gateway DNS | `apple-gadogado-5d0vs4l8x0j51hwy.salad.cloud` | `beet-ginger-cdz8ko9ehhmh4703.salad.cloud` |
| GPU classes | RTX **4090**, **3090 Ti**, **3090** (24 GB) | RTX **5090** (32 GB) + **5090 Laptop** (24 GB) |
| High $/hr | 0.33 / 0.19 / 0.17 | 0.50 / 0.235 |
| CUDA note | Ada/Ampere; known working | Blackwell test; the host needs CUDA 13.0 and driver 580+ (this image is **cuda13.0**) |
| Startup | `GET /health` :3000, delay 1200, period 120, fail 20 (~60 min) | same |
| Readiness | `GET /ready` :3000 | same |
| Created | 2026-09-18; **v7** 2026-09-20 | 2026-09-20 **v1** |

Do **not** mix 5090 into `flux2-klein2` until `flux2-klein-5090` has
`/ready` 200. First boot still downloads the tag's weights in parallel after
the 12 GB image pull: ~28 GB for `…-prefetch6-klein`, ~18 GB for
`…-prefetch6-snofs`.

---

## Matching Civitai on-site quality

Civitai's website generator is **not** Comfy: a plate with "Sampler: Euler, CFG 5, 40 steps, same seed"
will **not** pixel-match Salad even when those knobs are copied, because the hosted path is
`engine: "flux2"` / `model: "klein"` with LoRAs as `{ airUrn: strength }` and default **simple**
schedule, while Salad POSTs a Comfy 0.35 graph.

| Job | Civitai on-site | Salad Comfy (`/prompt`) |
|---|---|---|
| Sampler | their euler (flux2 or sdcpp) | `KSamplerSelect` euler → `SamplerCustomAdvanced` |
| Schedule | **simple** (API default) | `Flux2Scheduler` (resolution-aware shift) **or** `BasicScheduler` `simple` |
| CFG | `cfgScale` | `CFGGuider` |
| LoRA | native AIR map into their unet | stock `LoraLoader`. Studio **Convert still expands** `Power Lora Loader (rgthree)` → `LoraLoader`. The **current images** (`-prefetch6-klein` / `-prefetch6-snofs`) carry rgthree, so `/prompt` can instantiate `Power Lora Loader (rgthree)` and `Image Comparer (rgthree)` if left unexpanded; an **older replica** (prefetch3 and earlier) does not have rgthree, which is why Generate omits the comparer from the POST. Studio has no comparer slider (headless API); `SaveImage` is the plate. |
| Seed | their RNG | `RandomNoise`. Same integer is **not** the same noise tensor |
| Output | their encoder | `VAEDecode` + JPEG quality 90 |

**What actually closes most of the oil-vs-ink gap** is the LoRA sitting in the unet (Logs: HTTP **200**
on the Civitai download URL, not 401), not Euler/CFG/steps. Aged Art **1449678 @ 2795018** author range
**0.4–0.6**. Do not **Rebuild from Config** before Generate (it can swap in Detail Slider). A pixel
clone of Civitai requires **their** engine (Orchestration API or the website); Studio **Import** still
runs **our** sampler stack ([`salad_studio/README.md`](../../salad_studio/README.md)).

---

## Two-body plate recipe (SNOFS distilled + anatomy stack)

> **SUPERSEDED 2026-09-23** — the verified operating point is [doc 21 §1](21-klein-image-handoff.md); the recipe, its weights and the prompt-architecture claim below are the record of what was tried.

`salad_klein/prompt_snofs_distilled_anatomy.json` (euler, 4 steps) and `prompt_snofs_distilled_anatomy_resms.json`
(res_multistep, 12 steps) are the two-body plates on disk — **18+ only**, adults — same graph, same LoRA stack, two
sampler knobs: unet `snofsSexNudesAndOther_distilledV12KleinFp8.safetensors`, CFG 1 (`CFGGuider`), 832×1216, seed
`323175253610296` in both files. Node 70 loads the unet, then the `LoraLoader` chain 80→81→82→83 (each `lora_name` a Civitai URL, so the
Tokens tab's `?token=` is appended at POST; all four resolve HTTP **200**) is Detail Slider
`civitai:2334190@2625692` −1.5, Impressionism Klein9B `civitai:545264@2763568` 0.8, Klein Anatomy / Quality Fixer v1.5
`civitai:2324991@2615554` 2.0, Klein Fixes NSFW `civitai:2482439@2790993` 1.0; the last loader takes both
`CLIPTextEncode` nodes. The General Penis LoRA v1.0 `civitai:2333479@2624854` is in `model_catalog.py` but in
neither shipped file. Optional, for sitting / back-facing poses only: the Back Pose Enhancer
`civitai:2335408@2627022` (`1A_Back_Pose_Enhancer.safetensors`) splices in at the tail at **~1.0**, and is **not**
in the shipped files (the template is pose-agnostic). Verified operating point and knobs:
[doc 21 §1](21-klein-image-handoff.md).

### How these numbers were settled

Eight renders probed the failure (`target/klein_ab/ab.py`, gitignored scratch): the **c1** render put a
short photographic prompt on the *proven* distilled graph and still produced plaster mannequins, and c2
(base, CFG 1.3, the SNOFS LoKr's plain-Klein route) was visibly worse than every distilled render.
**Base 9B is not the better cut for this group.** To try the base route anyway: set node 70's `unet_name`
to `flux-2-klein-base-9b-fp8.safetensors`, add the SNOFS LoKr (`civitai:1972981@2960556`) at 0.5, and
raise steps to 12–20 at CFG 1.3.

### LoRA weights: what the sweep found

The weight sweep and its retracted "preventive, not visible" reading, plus the redundant SNOFS LoKr:
[doc 22 §9](22-two-body-correctness-research.md#9-anatomy-research), [doc 21 §4](21-klein-image-handoff.md).

### The pose block, and the rule about placeholders

`WOMAN:` / `MAN:` / `INTIMACY:` are one block: the pose; name another position in SNOFS's own vocabulary (**missionary / doggystyle / cowgirl**) rather than as geometry ([doc 21 §3](21-klein-image-handoff.md)). **Never leave a placeholder token in the text**: `REPLACE_THIS_POSE` mid-sentence produced the plaster render, and `test_klein_recipes.py` fails on `REPLACE_THIS`, `TODO`, `TBD`, `XXX`, `FIXME`.

### `_meta` on a `LoraLoader`

The Studio adds a `_meta.title` / `_meta.base` block when it **writes** a recipe; the shipped recipes carry none, so keep the block **if** the node has one — a hand-built node with a bare Civitai URL and no `_meta` is classified **foreign**: [doc 21 §5](21-klein-image-handoff.md).

### Pose control is not available on the replica

`ReferenceLatent` is dropped/rewired by Generate and local `LoadImage` files are omitted; there is no OpenPose / DWPose / ControlNet in the image, so pose comes from the prompt block above and a new seed, not a pose graph. Hard insertion plates are still Lustify/SDXL work, not Klein ([`salad_studio/README.md`](../../salad_studio/README.md)).

`python -m unittest discover -s tests -p "test_klein_recipes.py"` from the
repo root drives both files through the Studio Validate gate and the POST copy
(20 tests).

---

## Image prefetch (keep the Docker image small)

Do **not** `COPY` the ~17 GB Klein weights and do **not** `RUN unzip`: that bakes uncompressed tensors into a ~30 GB layer, and fp8 `.safetensors` barely shrink when zipped. The ~12 GB image, its empty `manifest.yaml` `before_start: []` and the **prefetch6** `COPY` of `rgthree-comfy` (cloned locally at pin `2c5342a8cb0eaecaabf61435a5f37dd594c510ba`) are [doc 23 §1.2–§1.3](23-salad-container-group-deployment.md).

**First boot (ENTRYPOINT, not a build step). Weights only, no custom-node clone:** `weights_zip.ensure_safetensors` inflates a sidecar or misnamed zip; else `huggingface_hub` downloads the tag's unets — the SNOFS one is `snofsSexNudesAndOther_distilledV12KleinFp8.safetensors` from `https://huggingface.co/edwixx/Flux2Klein9B_SNOFS/resolve/main/snofsSexNudesAndOtherFunStuff_distilledV12Fp8.safetensors` — plus `qwen_3_8b_fp8mixed.safetensors` and `flux2-vae.safetensors`, in parallel, then `exec`s `./comfyui-api`; `/health` stays down until it finishes. The per-tag unet sets are [doc 23 §1.2](23-salad-container-group-deployment.md); why the parallel fetch exists is **Startup-probe death loop** below.

`python model_catalog.py fetch-klein --stage` caches the same files in gitignored `art/model-cache/hf/`, local disk only: [doc 23 §1.4](23-salad-container-group-deployment.md).

Rebuild + push (**the klein recipe**; the two live tags are `-prefetch6-klein` / `-prefetch6-snofs`, the second build is [doc 23 §1.2](23-salad-container-group-deployment.md)):

```powershell
docker build --build-arg KLEIN_UNET_SET=base,distilled -t vkozyrev0/eldermark-klein:comfy0.35-api1.19.2-prefetch6-klein salad_klein
docker push vkozyrev0/eldermark-klein:comfy0.35-api1.19.2-prefetch6-klein
```

Then set the group Image Source to that tag (portal **Edit**, or PATCH `container.image`); a PATCH may return 200 with the old tag still showing until `pending_change` clears and **version** bumps — do not PATCH again while pending.

---

## Salad Studio

Windows helper `python -m salad_studio` from the repo root (not `eldermark`); the app, its tabs, its
knobs and the Config page's policy section (probe timing, replica count, env, `/prompt` JSON — rebuild
the replica **only** for new files or custom nodes): [`salad_studio/README.md`](../../salad_studio/README.md).

---

## Startup-probe death loop (why prefetch exists)

Sequential `before_start` downloads, not the window, were the cause: the unet alone took **~19 min at 8 MB/s** and the old **300 + 20×60 = 25 min** window killed the replica (**Instance Interrupted (Startup Probe Failure)**). Live startup is delay **1200**, period **120**, fail 20 → **~60 min** (the **Startup** row in **Live groups**; `failure_threshold` max **20**, `period_seconds` max **120**) — do not raise `timeout_seconds` expecting a longer boot. Probe fields: [doc 23 §2.2](23-salad-container-group-deployment.md), cause: [doc 22 §10](22-two-body-correctness-research.md#10-the-sdxl-migration-premise).

### First-boot logs (CSV + container stdout)

Downloaded system events `Downloads/flux2-klein-logs-9_18_2026, 8_12_34 PM.csv` (**instance controller only**, `Text Log`
empty); timeline on machine `40624151-…` (RTX 4090): image downloading 00:00:14, Running 00:11:26, **Instance Exited:1** 00:11:42, crash loop after.

Portal "dying in Starting" is that loop; `/ready` stayed 503 (gateway: "Your Container / Error").
Container stdout (Salad log-entries, not in the CSV), one line per failed image:
1. **`Failed to start server: Download failed (401)`** — the wrapper fell back to **HTTPStorageProvider** for the gated BFL unet URL, which sends no `HF_TOKEN` (CDN redirects also strip `Authorization`).
2. **v2 (`…-hf`, 2026-09-19):** the `hf` CLI returned `Error: Access denied. This repository requires approval.` — the **BFL gated license was not accepted** on https://huggingface.co/black-forest-labs/FLUX.2-klein-base-9b-fp8 for that Hugging Face account; `/ready` 404.
3. **v2 after license accept:** the download worked and Comfy 0.35.0 started on a 4090, then **`Instance Exited:1` ~4 s later** — the wrapper **exits 1 whenever Comfy exits**, and image `…-nowarm` drops baked warmup and sets `--listen 0.0.0.0`, so local `/health` cannot pass on this box (no NVIDIA driver).

---

Salad's official Comfy recipes have no Klein entry, and a second ~12–17 GB unet next to baked Flux.1 **OOMs** a 24 GB 4090. Do **not** POST a Klein graph at loganberry — [doc 14 §4b](14-salad-comfy-live-findings.md).

---

## What you will run

| Piece | Value |
|---|---|
| Base image | `ghcr.io/saladtechnologies/comfyui-api:comfy0.35.0-api1.19.2-torch2.13.0-cuda13.0-runtime` |
| LoRAs | **Not** baked. Job JSON `LoraLoader` Civitai URLs (Aged Art **2795018**, etc.) |
| GPU | **1× RTX 4090 24 GB**, 30 GB RAM. Not shared with Flux.1 |

The two image tags, the unets each first boot fetches, the org/project, the group name, the ports and
the replica count: [doc 23 §1.2/§2.2/§4](23-salad-container-group-deployment.md) and
[doc 21 §2](21-klein-image-handoff.md).

This machine has **Docker Desktop 29.8** (~47 GB RAM, nvidia runtime
registered) but **no `nvidia-smi`**. Use Docker to **build and push**.
Do not expect `docker run --gpus all` to generate here; the 4090 on
Salad is the GPU test.

Build files: `salad_klein/` (`Dockerfile`, `manifest.yaml`,
`prefetch.py`, `weights_zip.py`, `prompt_liked_style.json`).
`before_start` is **empty**; do not put sequential HF URLs back.

---

Created with the Salad control-plane `POST …/organizations/life-sim/projects/default/containers` (org/project `life-sim` / `default`), not the Portal form; group mechanics: [doc 23 §2/§4](23-salad-container-group-deployment.md).

---

## Step-by-step (rebuild)

Full runbook: [doc 23 §1–§3](23-salad-container-group-deployment.md) — accounts (the BFL license and the
three `~/.config/` tokens), build, portal fields and wait-for-Ready; the short form is
[`salad_klein/README.md`](../../salad_klein/README.md). Leave loganberry running only if you still need Flux.1 probes.

### 1. Optional local API check (no GPU)

Without a local NVIDIA GPU you can still confirm the image starts far enough to print Comfy's boot log. A
24 GB local card adds `--gpus all -p 8188:8188` to the `docker run` below:

```powershell
docker run --rm -p 3000:3000 `
  -e HF_TOKEN=(Get-Content $HOME\.config\huggingface\token -Raw).Trim() `
  YOURUSER/eldermark-klein:comfy0.35-api1.19.2-prefetch6-klein
```

Expect a long first download or a CUDA error; either is fine for this box. Then `GET http://localhost:3000/ready`
until 200, and POST `prompt_liked_style.json` at `/prompt`. `/ready` going 200 is a **Salad 4090** check, not
this laptop.

### 2. Push

`docker login`, then `docker push` both tags built above: [doc 23 §1.2](23-salad-container-group-deployment.md).

### 3. Smoke the liked stack

The gateway file for this group is `~/.config/salad/gateway-klein`, never the Flux.1 `gateway` file (doc 23 §3).

```powershell
$gw = (Get-Content $HOME\.config\salad\gateway-klein -Raw).Trim()
$key = (Get-Content $HOME\.config\salad\key -Raw).Trim()
# edit node 74's positive prompt in prompt_liked_style.json before POST
curl.exe -sS -X POST "$gw/prompt" `
  -H "Content-Type: application/json" `
  -H "Salad-Api-Key: $key" `
  --data-binary "@salad_klein/prompt_liked_style.json" `
  -o klein-out.json
```

Decode `.images[0]` to a JPEG. Trigger words in the positive prompt: `ArsMJStyle, Impressionism`; sampler
Euler, 832×1216; public CivitAI meta on 135504982 is hidden. Cloudflare gateway timeout is still **~100 s**
(doc 21 §5): a 20-step 832×1216 Klein on a 4090 should fit, and if it 524s, drop steps on the first smoke.

### 4. After it works

- Scale replicas only if you will actually queue jobs.
- Do not load Flux.1 / Krea / SDXL checkpoints into this image. Keep `salad_PAUSE.txt` and keep `salad_catalog_faces.py` off this group until Klein is an explicit **chosen** house in doc 14 (freeze: [doc 14 §3](14-salad-comfy-live-findings.md)).

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

Image tags: https://github.com/SaladTechnologies/comfyui-api/pkgs/container/comfyui-api · Klein 9B template: https://github.com/Comfy-Org/workflow_templates/blob/main/templates/image_flux2_text_to_image_9b.json
