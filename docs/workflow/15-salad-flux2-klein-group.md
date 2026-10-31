# 15. Custom Salad container group for Flux.2 Klein 9B

> **Superseded for the current groups.** Doc [21](21-klein-image-handoff.md)
> and doc [23](23-salad-container-group-deployment.md) carry the shipped
> prefetch6 tags and the current routing. Keep this as the 2026-09-21 record.
>
> **Status (2026-09-21).** Both Klein groups were PATCHed to **prefetch5**
> (HTTP 200, `pending_change: true`). Until **version** bumps, GET still shows
> `docker.io/vkozyrev0/eldermark-klein:comfy0.35-api1.19.2-prefetch4`. Do not
> PATCH again while pending. The shipped tags are `...-prefetch6-klein` and
> `...-prefetch6-snofs`. `rgthree-comfy` is cloned **on this machine** and
> `COPY`'d into `/opt/ComfyUI/custom_nodes/rgthree-comfy` at **local
> `docker build`**, pin `2c5342a8cb0eaecaabf61435a5f37dd594c510ba`
> (`salad_klein/RGTHREE_COMMIT.txt`). `prefetch.py` stays **weights-only**
> (both Klein unets + CLIP + VAE; **no** `git clone`). Do **not** `FROM` a
> flux1dev tag and do **not** POST Klein graphs at loganberry. Mass catalog
> freeze: [doc 14](14-salad-comfy-live-findings.md). Studio:
> [`salad_studio/README.md`](../../salad_studio/README.md).
>
> Liked style: Klein 9B-Base **2322332@2612548** + Detail Slider **2334190@2625692** + Impressionism Klein9B **545264@2763568** (`ArsMJStyle, Impressionism`), Euler, 832×1216. Reference: https://civitai.com/images/135504982.

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
| Studio profile | `klein` | `klein5090` |
| Image (showing / patched) | `…-prefetch6-klein` / `docker.io/vkozyrev0/eldermark-klein:comfy0.35-api1.19.2-prefetch6-klein` | `…-prefetch6-snofs` |
| Gateway DNS | `apple-gadogado-5d0vs4l8x0j51hwy.salad.cloud` | `beet-ginger-cdz8ko9ehhmh4703.salad.cloud` |
| GPU classes | RTX **4090**, **3090 Ti**, **3090** (24 GB) | RTX **5090** (32 GB) + **5090 Laptop** (24 GB) |
| High $/hr | 0.33 / 0.19 / 0.17 | 0.50 / 0.235 |
| CUDA note | Ada/Ampere; known working | Blackwell test; the host needs CUDA 13.0 and driver 580+ (this image is **cuda13.0**) |
| Startup | `GET /health` :3000, delay 1200, period 120, fail 20 (~60 min) | same |
| Readiness | `GET /ready` :3000 | same |
| Created | 2026-09-18; **v7** 2026-09-20 | 2026-09-20 **v1** |

Do **not** mix 5090 into `flux2-klein2` until `flux2-klein-5090` has
`/ready` 200. Both images build on
`ghcr.io/saladtechnologies/comfyui-api:comfy0.35.0-api1.19.2-torch2.13.0-cuda13.0-runtime`
(`salad_klein/Dockerfile`). First boot still downloads the tag's weights in
parallel after the 12 GB image pull: ~28 GB for `…-prefetch6-klein`, ~18 GB
for `…-prefetch6-snofs`.

---

## Matching Civitai on-site quality

Civitai's website generator is **not** Comfy. Copying "Sampler: Euler, CFG 5, 40 steps, same seed" will **not** pixel-match Salad, because the hosted path is `engine: "flux2"` / `model: "klein"` with LoRAs as `{ airUrn: strength }` and the default **simple** schedule, while Salad POSTs a Comfy 0.35 graph.

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
**0.4–0.6**. **Rebuild from Config** in the Prompt Editor
(`salad_studio/web/pages/editor.py` `rebuild_from_config`) replaces the editor's
request with `request_json.build_request` built from the profile's graph, size,
steps, seed, CFG and selected LoRAs, and keeps the current prompt text. The old
warning that it can swap in Detail Slider was checked against the retired Tk
button and has not been re-checked against this one, so treat it as the current
behaviour only after you see it. A pixel
clone of Civitai requires **their** engine (Orchestration API or the website); Studio **Import** still
runs **our** sampler stack ([`salad_studio/README.md`](../../salad_studio/README.md)).

---

## Two-body plate recipe (SNOFS distilled + anatomy stack)

> **SUPERSEDED 2026-09-23**. The verified operating point is [doc 21 §1](21-klein-image-handoff.md); the recipe, its weights and the prompt-architecture claim below are the record of what was tried.

`salad_klein/prompt_snofs_distilled_anatomy.json` (euler, 4 steps) and `prompt_snofs_distilled_anatomy_resms.json`
(res_multistep, 12 steps) are the two-body plates on disk, **18+ only**, adults: unet
`snofsSexNudesAndOther_distilledV12KleinFp8.safetensors`, CFG 1 (`CFGGuider`), 832×1216, seed
`323175253610296` in both files. Node 70 loads the unet; the `LoraLoader` chain 80→81→82→83 (each `lora_name` a Civitai URL, so the
Tokens tab's `?token=` is appended at POST; all four resolve HTTP **200**) is Detail Slider
`civitai:2334190@2625692` −1.5, Impressionism Klein9B `civitai:545264@2763568` 0.8, Klein Anatomy / Quality Fixer v1.5
`civitai:2324991@2615554` 2.0, Klein Fixes NSFW `civitai:2482439@2790993` 1.0; the last loader takes both
`CLIPTextEncode` nodes. The General Penis LoRA v1.0 `civitai:2333479@2624854` and the optional Back Pose Enhancer
`civitai:2335408@2627022` (`1A_Back_Pose_Enhancer.safetensors`, splice at **~1.0** for sitting or back-facing poses)
are catalog-only. The weight sweep and the redundant SNOFS LoKr: [doc 22 §9](22-two-body-correctness-research.md#9-anatomy-research), [doc 21 §4](21-klein-image-handoff.md).

`WOMAN:` / `MAN:` / `INTIMACY:` are one block: the pose; name another position in SNOFS's own vocabulary (**missionary / doggystyle / cowgirl**) rather than as geometry ([doc 21 §3](21-klein-image-handoff.md)). **Never leave a placeholder token in the text**: `REPLACE_THIS_POSE` mid-sentence produced the plaster render, and `test_klein_recipes.py` fails on `REPLACE_THIS`, `TODO`, `TBD`, `XXX`, `FIXME`. No code writes a recipe file. `request_json.build_request` stamps `_meta` on the request it builds, in the Studio and in the POST copy; the shipped recipes carry none, so keep the block **if** the node has one. A hand-built node with a bare Civitai URL and no `_meta` is classified **foreign**: [doc 21 §5](21-klein-image-handoff.md). `ReferenceLatent` is dropped/rewired by Generate and local `LoadImage` files are omitted; there is no OpenPose / DWPose / ControlNet in the image, so pose comes from the prompt block above and a new seed, not a pose graph. Hard insertion plates are still Lustify/SDXL work, not Klein ([`salad_studio/README.md`](../../salad_studio/README.md)).

`python -m unittest discover -s tests -p "test_klein_recipes.py"` from the repo root drives both files through the Studio Validate gate and the POST copy (20 tests).

---

## Image build and prefetch

Do **not** `COPY` the ~17 GB Klein weights and do **not** `RUN unzip`: that bakes uncompressed tensors into a ~30 GB layer, and fp8 `.safetensors` barely shrink when zipped. The ~12 GB image, its empty `manifest.yaml` `before_start: []`, the per-tag unet sets, the SNOFS HF URL, and the **prefetch6** `COPY` of `rgthree-comfy` (cloned locally at pin `2c5342a8cb0eaecaabf61435a5f37dd594c510ba`) are [doc 23 §1.2–§1.3](23-salad-container-group-deployment.md). `prefetch.py` is weights-only at first boot: it inflates a sidecar or misnamed zip, else downloads the tag's unets, CLIP, and VAE in parallel, then `exec`s `./comfyui-api`; `/health` stays down until it finishes.

Build and push the Klein tag (the SNOFS build and the full set are in doc 23 §1.2):

```powershell
docker build --build-arg KLEIN_UNET_SET=base,distilled -t vkozyrev0/eldermark-klein:comfy0.35-api1.19.2-prefetch6-klein salad_klein
docker push vkozyrev0/eldermark-klein:comfy0.35-api1.19.2-prefetch6-klein
```

Then set the group Image Source to that tag (portal **Edit**, or PATCH `container.image`); a PATCH may return 200 with the old tag still showing until `pending_change` clears and **version** bumps. Do not PATCH again while pending.

---

## Salad Studio

Windows helper `python -m salad_studio` from the repo root, not `eldermark`. The app, its tabs, its knobs, and the Config page's policy section (probe timing, replica count, env, `/prompt` JSON): [`salad_studio/README.md`](../../salad_studio/README.md). Rebuild the replica **only** for new files or custom nodes.

---

## Startup-probe death loop (why prefetch exists)

Sequential `before_start` downloads, not the window, were the cause: the unet alone took **~19 min at 8 MB/s** and the old **300 + 20×60 = 25 min** window killed the replica (**Instance Interrupted (Startup Probe Failure)**). Live startup is delay **1200**, period **120**, fail 20 → **~60 min** (the **Startup** row in **Live groups**; `failure_threshold` max **20**, `period_seconds` max **120**). Do not raise `timeout_seconds` expecting a longer boot. Probe fields: [doc 23 §2.2](23-salad-container-group-deployment.md), cause: [doc 22 §10](22-two-body-correctness-research.md#10-the-sdxl-migration-premise).

First boot failed three ways: **`Failed to start server: Download failed (401)`**, because the wrapper fell back to **HTTPStorageProvider** for the gated BFL unet URL and sent no `HF_TOKEN`; **`Error: Access denied. This repository requires approval.`** before the BFL gated license was accepted; then, after the license, **`Instance Exited:1`** about 4 s after Comfy started, because the wrapper exits 1 whenever Comfy exits. Downloaded system events for the first failure: `Downloads/flux2-klein-logs-9_18_2026, 8_12_34 PM.csv` (**instance controller only**, `Text Log` empty); timeline on machine `40624151-…` (RTX 4090): image downloading 00:00:14, Running 00:11:26, **Instance Exited:1** 00:11:42.

Salad's official Comfy recipes have no Klein entry, and a second ~12–17 GB unet next to baked Flux.1 **OOMs** a 24 GB 4090. Do **not** POST a Klein graph at loganberry: [doc 14 §4b](14-salad-comfy-live-findings.md).

---

## What runs locally

This machine has **Docker Desktop 29.8** (~47 GB RAM, nvidia runtime
registered) but **no `nvidia-smi`**. Build and push here; do not expect
`docker run --gpus all` to generate. The 4090 on Salad is the GPU test.
`before_start` is **empty**; do not put sequential HF URLs back.

Without a GPU, confirm the image starts far enough to print Comfy's boot log. A 24 GB local card adds `--gpus all -p 8188:8188`:

```powershell
docker run --rm -p 3000:3000 `
  -e HF_TOKEN=(Get-Content $HOME\.config\huggingface\token -Raw).Trim() `
  YOURUSER/eldermark-klein:comfy0.35-api1.19.2-prefetch6-klein
```

Expect a long download or a CUDA error; either is fine. Then `GET http://localhost:3000/ready` until 200, and POST `prompt_liked_style.json` at `/prompt`. `/ready` 200 is a **Salad 4090** check.

### Smoke the liked stack

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

Decode `.images[0]` to a JPEG. Trigger words in the positive prompt: `ArsMJStyle, Impressionism`; sampler Euler, 832×1216; public CivitAI meta on 135504982 is hidden. Cloudflare gateway timeout is still **~100 s** (doc 21 §5): a 20-step 832×1216 Klein on a 4090 should fit, and if it 524s, drop steps on the first smoke.

### After it works

Scale replicas only if you will actually queue jobs. Do not load Flux.1 / Krea / SDXL checkpoints into this image. Keep `salad_PAUSE.txt` and keep the Eldermark face catalog off this group until Klein is an explicit **chosen** house in doc 14 (freeze: [doc 14 §3](14-salad-comfy-live-findings.md)).

The Klein graph (`UNETLoader`, `CLIPLoader` type `flux2`, `VAELoader`, `EmptyFlux2LatentImage`, `Flux2Scheduler`, `SamplerCustomAdvanced`) and group routing are [doc 21 §1–§2](21-klein-image-handoff.md) and [doc 14 §4b](14-salad-comfy-live-findings.md).

---

## Pointers

Image tags: https://github.com/SaladTechnologies/comfyui-api/pkgs/container/comfyui-api · Klein 9B template: https://github.com/Comfy-Org/workflow_templates/blob/main/templates/image_flux2_text_to_image_9b.json
