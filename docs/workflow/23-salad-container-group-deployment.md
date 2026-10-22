# 23. Salad container groups: build the image, call the container

The single reference for **creating a Salad container image** and **calling into
a Salad container** (and its control-plane API). Everything operational that used
to be spread across the game repo's `docs/workflow/13-gpu-host-catalog-plans.md`
Plan D and this repo's `docs/workflow/15` now lands here.

> **Status:** consolidated 2026-09-24 from the game repo's Plan D (SaladCloud
> group mechanics, 2026-09-16/17) + this repo's doc 15 (§"Live groups" and
> §"Step-by-step (rebuild)", the runbook that was actually used) +
> `salad_studio/salad_status.py` (the API client).
>
> **Supersedes for operational depth:** `13-gpu-host-catalog-plans.md` Plan D in
> the game repo. That file stays as the **host ranking** (Salad vs RunPod / Vast
> / TensorDock / Massed / Hyperstack / AutoDL); it now carries one-line
> characterisations and points here.
>
> **Live-ops facts and the prompt recipe:** [`15`](15-salad-flux2-klein-group.md).
> **Where to start for image work:** [`21`](21-klein-image-handoff.md).

---

## 0. Two different "Salad APIs". Do not confuse them.

Control plane `https://api.salad.com/api/public` (`Salad-Api-Key: <key>`; client `salad_studio/salad_status.py`)
creates, patches and stops groups, reallocates replicas and reads status and logs; the container at
`https://<group>-<hash>.salad.cloud` is public by default and runs Comfy's `/prompt`, `/health`, `/ready`. The working callers are listed in §3.

A group's gateway DNS is the only handle the client keeps; the control plane is
how you find the group behind it (`find_group_by_gateway`).

---

## 1. Build the container image

### 1.1 The build tree

`salad_klein/` is a self-contained build context. Its own
[`README.md`](../../salad_klein/README.md) is the short form of this section and carries the build
and test commands (`cd salad_klein && python -m unittest discover -p "test_*.py"`).

`prefetch.py` is the ENTRYPOINT: it inflates a sidecar/misnamed zip, else downloads the weights in
parallel, then `exec`s `comfyui-api`. Beside it sit `Dockerfile`, `manifest.yaml`, `weights_zip.py`,
`check_hf_download.py`, `RGTHREE_COMMIT.txt`, `.dockerignore`, the `prompt_*.json` graphs,
`prompt_catalog.json` / `prompt_ledger.json`, `weights/.gitignore`,
`test_prefetch.py` / `test_hf_gated_access.py`, and `http_smoke.py` (a manual Docker smoke run).

### 1.2 The two images: one per unet family

One Dockerfile, built **twice**, once per unet family. The build arg `KLEIN_UNET_SET` decides what
the first boot downloads, and that is the only difference between the two images.

| Family | Tag | `KLEIN_UNET_SET` | Unets on disk after the first boot |
|---|---|---|---|
| `klein` | `docker.io/vkozyrev0/eldermark-klein:comfy0.35-api1.19.2-prefetch6-klein` | `base,distilled` | `flux-2-klein-base-9b-fp8.safetensors` (9.57 GB), `flux-2-klein-9b-fp8.safetensors` (9.43 GB), Qwen encoder (8.66 GB), VAE (0.34 GB) |
| `snofs` | `docker.io/vkozyrev0/eldermark-klein:comfy0.35-api1.19.2-prefetch6-snofs` | `snofs` | `snofsSexNudesAndOther_distilledV12KleinFp8.safetensors` (9.08 GB), Qwen encoder (8.66 GB), VAE (0.34 GB) |

The SNOFS unet downloads from
`https://huggingface.co/edwixx/Flux2Klein9B_SNOFS/resolve/main/snofsSexNudesAndOtherFunStuff_distilledV12Fp8.safetensors`.

The family-to-image mapping is shipped in
[`salad_studio/studio-metadata.json`](../../salad_studio/studio-metadata.json)
(`routing.families.<family>.image`), which is what the Config page's **Image**
field is seeded from; `tests/test_docs_match.py` fails if this table stops
naming an image, a unet or the build arg the document ships.

Build and push both (`RGTHREE_COMMIT.txt` pins the node copy; weights are never baked):

```bash
git clone https://github.com/rgthree/rgthree-comfy.git salad_klein/custom_nodes/rgthree-comfy
git -C salad_klein/custom_nodes/rgthree-comfy checkout 2c5342a8cb0eaecaabf61435a5f37dd594c510ba
docker build --build-arg KLEIN_UNET_SET=base,distilled \
  -t vkozyrev0/eldermark-klein:comfy0.35-api1.19.2-prefetch6-klein salad_klein
docker push vkozyrev0/eldermark-klein:comfy0.35-api1.19.2-prefetch6-klein
docker build --build-arg KLEIN_UNET_SET=snofs \
  -t vkozyrev0/eldermark-klein:comfy0.35-api1.19.2-prefetch6-snofs salad_klein
docker push vkozyrev0/eldermark-klein:comfy0.35-api1.19.2-prefetch6-snofs
```

The `rgthree-comfy` clone must be pinned to the commit in `RGTHREE_COMMIT.txt`
and `COPY`d into `/opt/ComfyUI/custom_nodes/rgthree-comfy` at build time.

What either image is, inside:

| Piece | Value |
|---|---|
| Base | `ghcr.io/saladtechnologies/comfyui-api:comfy0.35.0-api1.19.2-torch2.13.0-cuda13.0-runtime` |
| ComfyUI | `--listen 0.0.0.0 --port 8188`, its own UI and API |
| Salad wrapper | `comfyui-api` on port **3000**: `/health`, `/ready`, and `POST /prompt` answering `images[]` as base64 JPEG (`convert_output`) |
| ENTRYPOINT | `python /prefetch.py` runs the parallel weight download, then `exec ./comfyui-api` |
| Custom nodes | `rgthree-comfy` (Image Comparer, Power Lora Loader) at the pinned commit |
| Weights | none in any layer: the first boot fetches 18 GB for `snofs` or 28 GB for `klein` |
| Size | ~12 GB image; a new replica re-downloads, because node storage is ephemeral |

Both tags work as a container image for a Salad group or a **vast.ai instance**. What a group may render is decided by the family its tag bakes, not by the tag's name. See [`§5`](#5-vastai-instances) for the host, the port choice and the failure modes. The Config page's **Container images** section shows each tag's fields and copies the build, run and `vastai create` commands from `routing.families.<family>.deployment` in
[`salad_studio/studio-metadata.json`](../../salad_studio/studio-metadata.json).

### 1.3 The two hard rules

- **Do not `COPY` the unet / CLIP / VAE into the image**, and **do not
  `RUN unzip`** in the Dockerfile. That writes uncompressed tensors into an
  image layer (~30 GB). Zip is transport only; the image stays ~12 GB.
- **Do not `FROM` a `flux1dev` Salad tag.** It OOMs or 524s on a 24 GB card for
  Klein graphs.

`manifest.yaml` sets `before_start: []`; do not put sequential HF URLs back.

`prefetch.py` is the only thing that puts weights on disk, at **first boot**, not at build:

1. If a `.zip` sits next to the Comfy path, or a zip was misnamed
   `*.safetensors`, inflate it to the real `.safetensors` filename.
2. Otherwise download the unet set the tag was built for (`KLEIN_UNET_SET`, see
   §1.2), the CLIP and the VAE **in parallel**.
3. `exec` `comfyui-api`. Comfy only ever sees raw `.safetensors`.

### 1.4 Staging weights locally (optional)

`python model_catalog.py fetch-klein --stage` caches the same files in the gitignored `art/model-cache/hf/` and hardlinks them into `$SALAD_STUDIO_HOME/salad_klein/weights/`. Salad never sees that cache; the container URL-loads on a new replica, and the LoRA URLs carry the Civitai token at POST time. Also in [doc 15](15-salad-flux2-klein-group.md).

`model_catalog.py` exists in **both** repos; this repo's copy is the one `salad_studio/lora_store.py` imports. Edit both, or delete the game repo's copy once nothing there uses it.

---

## 2. Create the container group

### 2.1 What a Salad group is (the host-side mechanics)

- **Product shape.** Push a Docker image, set a GPU class + priority (`high` or `batch`/lowest, High for a full run, Lowest for probes) and N replicas. Interruptible community nodes; **Salad Dedicated** is reserved DC hardware. Container-first, not SSH-first. Storage is ephemeral, so every new instance re-downloads; keep progress files (`regen_progress.json`) on the Windows side. Billing is prepaid, per-second while running: allocation, image pull and cold start are not billed, but a huge pull still costs wall-clock.
- **GPU classes.** RTX 3060 up to **RTX 4090 24 GB** and **RTX 5090 32 GB** on Community. No H100/A100 there; a 48 GB+ card means Dedicated or another host. A class is a UUID; the docs example for a 4090 is `ed563892-aacd-40f5-80b7-90c9be6c759b`; `salad_status.list_gpu_classes()` reads the live list.
- **No per-image safety classifier.** Your image runs Comfy. The residual filter is the ToS (CSAM/illegal-content clause, any-reason refusal) plus chef/node disconnects, not a Google `IMAGE_SAFETY` 422.
- **Adult workloads are a chef preference**, not an "anything goes" promise. Chefs in anti-porn jurisdictions are excluded from those jobs. ToS: <https://salad.com/terms/saladcloud>.

### 2.2 Portal fields

https://portal.salad.com, create a **new** group; never edit an unrelated one.

| Field | Set |
|---|---|
| Image | the family's tag from §1.2: `vkozyrev0/eldermark-klein:comfy0.35-api1.19.2-prefetch6-klein` for a Klein group, `…-prefetch6-snofs` for the SNOFS one (private registry: add pull credentials) |
| GPU | RTX 4090 (24 GB). Lowest priority is fine for probes |
| vCPU / RAM | 4+ / **30 GB** |
| Replicas | **1** until `/ready` is green |
| Container gateway | **On**, port **3000**, least-connection; its timeouts, algorithm and concurrency cannot be changed after the group is created |
| Auth | **On** (`Salad-Api-Key`) |
| Startup probe | `GET /health`, delay **1200**, period **120**, fail **20** (~60 min). `timeout_seconds` is per-GET, not the boot window |
| Readiness probe | `GET /ready` |
| Env | `HF_TOKEN`; `CIVITAI_API_TOKEN` if Civitai 401s; `STARTUP_CHECK_MAX_TRIES=120` (already in the Dockerfile, keep it) |

### 2.3 Create and scale

Create a prepaid org in the Salad portal, build and push the image (§1), create the group with §2.2's fields, scale replicas 1→N, wait for `/ready` 200 (the first replica pulls the ~12 GB image, then prefetches 28 GB for `…-prefetch6-klein` or 18 GB for `…-prefetch6-snofs`), point the caller at the group's gateway DNS, keep progress local, and scale to 0 when done.

### 2.4 Risks

Home GPUs have variable actual VRAM, driver oddities and random disconnects; High priority is still subject to node disconnection. The image must be self-contained, and a 24 GB card is tight for Flux-dev but standard: there is no 48 GB Community card.

---

## 3. Call into a running container

The gateway is `<group>-<hash>.salad.cloud`, saved to a per-group file
(`~/.config/salad/gateway-klein`), never over the Flux.1 `gateway` file.

| Purpose | Request |
|---|---|
| Liveness | `GET /health` on port 3000 |
| Readiness | `GET /ready` on port 3000. 503 until Comfy listens |
| Run a graph | `POST /prompt` with the Comfy API body (the `prompt_*.json` files) |
| Result | Wrapper `POST /prompt` returns `images[]`. Native Comfy 8188 returns a `prompt_id`. GET `/history/<prompt_id>` then `/view` is the fallback when `images[]` is empty |

The working callers are `salad_gen.py`, `salad_probe_klein.py` and `salad_age_review.py`. `salad_probe_ages.py`, `salad_probe_sdxl.py` and `salad_catalog_faces.py` need the Eldermark checkout (`paperdoll_mask` / `regen_faces`) and fail on import here. Studio's **Ready** badge and Generate's `/ready` pre-probe use the same path, and Studio skips the `/ready` probe while a replica is still pulling so a stale 200 cannot be trusted.

Do not POST a Klein graph at the Flux.1 group. It OOMs or 524s on 24 GB.

---

## 4. Call the control-plane API

`salad_studio/salad_status.py` is the client. Base and scope:

```
API     = https://api.salad.com/api/public
ORG     = life-sim
PROJECT = default
```

| Operation | Request |
|---|---|
| List groups | `GET /organizations/{org}/projects/{project}/containers` |
| Get one group | `GET /organizations/{org}/projects/{project}/containers/{name}` |
| Patch a group | `PATCH …/containers/{name}` with `content-type: application/merge-patch+json` |
| Reallocate a replica | `POST …/containers/{name}/instances/{iid}/reallocate` |

Auth is the `Salad-Api-Key` header on every call. The PATCH body carries
`startup_probe` and `readiness_probe`, optionally `country_codes`, and
`container`, where an image change is
`{"container": {"image": "…"}}` and a GPU-class change rewrites
`container.resources.gpu_classes` while preserving the existing `cpu`, `memory`,
`shm_size` and `storage_amount`.

- A group's `startup_probe` / `readiness_probe` are readable and patchable;
  `explain_probe()` turns them into the "Salad waits {delay}s, then GET {path}"
  explanation the Studio shows.
- **Do not DELETE a group.** Salad does not reuse the name or gateway DNS; a
  delete mints a new group and DNS. Stop/start, reallocate, and image PATCH only.
- `_ORIGIN_DOWN_CODES = (0, 520, 521, 522, 523, 524)` marks an origin that is
  down rather than still starting.
- Never log `networking.auth` or the container's `environment_variables`.

Files named above are the map; `salad_klein/README.md` is the build short form, [doc 15](15-salad-flux2-klein-group.md) the live ops, [doc 21](21-klein-image-handoff.md) the Klein entry point.

## 5. Vast.ai instances

*Consolidated from `docs/workflow/24-vast-ai-image-deployment.md` on 2026-10-17.*

Rent the same container image the Salad group runs and point the app at it. The image is portable because it is an ordinary Docker image: it starts Comfy on `0.0.0.0:8188` and the Salad API wrapper on `3000`, and nothing in it asks Salad for anything at boot. The group policy, probes, replica counts, Reallocate and portal fields stay behind.

> **Status:** written 2026-10-17 from a live run of `docker.io/vkozyrev0/eldermark-klein:comfy0.35-api1.19.2-prefetch6-klein` on three vast.ai hosts. Numbers marked **measured** come from that run. The `--runtype` semantics come from the vast.ai CLI documentation, not from a controlled test.

---

### 5.1 What the image needs

| Requirement | Value | Why |
| --- | --- | --- |
| Host CUDA | `cuda_max_good` 13.0 or higher, driver 580 or higher | The base image is `cuda13.0-runtime` with torch 2.13. A 12.x driver cannot initialize it |
| VRAM | 24 GB | One 9 GB unet plus the 8.66 GB Qwen text encoder |
| Disk | 100 GB | The image, the unet set and the workspace |
| Link | 200 Mbps down or better | The first boot downloads the set |
| Registry | Public, or a token vast.ai can use | The image lives on Docker Hub |

The tokens go in the instance environment:

- `HF_TOKEN` for the gated Black Forest Labs unets. `prefetch.py` reads `HF_TOKEN`
  or `HUGGING_FACE_HUB_TOKEN`.
- `CIVITAI_API_TOKEN` for LoRA URLs the wrapper downloads.
- The vast.ai key stays in the app. It authenticates the control API and never
  goes to the container.

---

### 5.2 Pick an offer

Filter the offer list before you rent:

```
1 GPU, on-demand, rentable, verified, rented=false
gpu_name in RTX 5090, RTX 4090 (the app's default; add RTX A6000 or A100 PCIE)
gpu_ram >= 24000
cuda_max_good >= 13.0
reliability2 >= 0.95
disk_space >= 140
inet_down >= 200
inet_up >= 100
dph_total <= 0.50
limit 100
```

Sort by `dlperf_per_dphtotal`, not by price alone. Measured on 2026-10-17: an
RTX 5090 at $0.402/hr with `dlperf` 199 buys 495 Perf/$, while an RTX 4090 at
$0.376/hr with `dlperf` 97 buys 258 Perf/$. Price alone hides that difference.

The offer list does not say which container runtime the host uses. Some hosts run
GPU containers under gvisor, and gvisor cannot inject the GPU device. The failure
appears at container create, within a minute, and it is not the image's fault.
Destroy that instance and pick another host. §5.9 has the exact message.

---

### 5.3 Create the instance

The app's Deploy pane prints this line:

```
vastai create instance <offer> --image docker.io/vkozyrev0/eldermark-klein:comfy0.35-api1.19.2-prefetch6-klein \
  --disk 100 \
  --env '-p 3000:3000 -p 8188:8188 -e HF_TOKEN=${HF_TOKEN} -e CIVITAI_API_TOKEN=${CIVITAI_API_TOKEN} -e STARTUP_CHECK_MAX_TRIES=120'
```

Add three options for a vast.ai host:

- `--runtype args` so the image's own entrypoint runs. The vast.ai CLI's default
  launch mode injects its SSH wrapper, which replaces the entrypoint. `args`
  keeps the image's `ENTRYPOINT ["python", "/prefetch.py"]` and its
  `CMD ["./comfyui-api"]`.
- `-e HF_HUB_DOWNLOAD_TIMEOUT=120` and `-e HF_HUB_ETAG_TIMEOUT=60` inside the
  `--env` string. The library defaults are 10 seconds each, and a slow host
  spends them on retries.
- Nothing else. No `--onstart-cmd`: the entrypoint runs the prefetch and then
  starts the API.

The image tags bake a unet set (the sizes are in §1.2). Override it with `-e KLEIN_UNET_SET=base` to
drop the distilled unet and roughly a third of the download.

---

### 5.4 Replacing a destroyed instance

The app can rent a replacement when the profile's instance is gone. It is
opt-in, because it spends money: the Config page's **Vast.ai** sub-tab carries
**Create a replacement automatically when Generate finds it gone**. The same
**Rent a machine** criteria drive the automatic check, **Find offers**, and
**Create instance on selected offer**, so the manual and automatic paths cannot
disagree.

| Field | Default | Meaning |
| --- | --- | --- |
| GPU models | `RTX 5090, RTX 4090` | The `gpu_name` whitelist, in preference order. An empty box restores these two; it never means "any GPU" |
| Max $/hr | `0.50` | The offer's `dph_total` ceiling |
| Min down Mbps | `200` | The offer's `inet_down` floor |
| Min up Mbps | `100` | The offer's `inet_up` floor |
| CUDA at least | `13.0` | The offer's `cuda_max_good` floor |
| Reliability at least | `0.95` | The offer's `reliability2` floor; a record that omits it fails |

The GPU default matters: the measured unfiltered search's cheapest 24 GB offer
is a Tesla P40 at $0.108/hr, and it cannot run the image's CUDA 13 stack. Two
more floors are fixed: a 24 GB card (`gpu_ram`) and 140 GB of free disk
(`disk_space`), the image's own requirements.

The search is `POST /api/v0/bundles/` with those filters, ordered by
`dlperf_per_dphtotal` descending. The app then ranks by images per dollar
(`dlperf_per_dphtotal`, or `dlperf / dph_total` when the API omits it), then the
GPU preference order, then price. The cheapest offer is therefore not the pick.
A manual rent issues exactly one `PUT /api/v0/asks/{offer}/` (with `disk: 100`, `runtype: "args"`,
the selected row's image, and the `-p 3000:3000 -p 8188:8188` flags plus the saved tokens) and
never falls through to another; the automatic path keeps a short fallback queue.

When Generate runs in vast mode with the option on, the app lists the account. A listed instance is used as-is; a missing one is replaced, and the press reports the new instance instead of POSTing because the first boot still has to pull and prefetch, so Generate again when `/ready` is green. **Replace if destroyed now** runs the same check without waiting for a press; it acts on the row selected in the Instances table, so a destroyed row can be replaced too.

A row is an instance, not an endpoint. **Fetch instances from Vast.ai** reads
the unfiltered `/api/v1/instances/` records and reconciles the stored list:

- a record that maps no ComfyUI port is still a row, showing its real state
  (`loading`, `stopped`, …) with `#<id>` in the Address column;
- an id-bearing row absent from a complete listing becomes `destroyed`, keeps
  its id and image, and loses its address; a truncated listing destroys nothing;
- the endpoint-less row a create left behind becomes the active target when its
  ComfyUI port finally maps, unless another instance is already active; a
  vast-mode profile that held a gone address is repointed at the new active
  endpoint or cleared.

When the rent returns without a mapped port, the contract appears as a `creating`
row. There is no separate `pending` slot.

---

### 5.5 Wait for the first boot

The order is image pull, then the prefetch, then Comfy. Nothing listens until the
last file lands. A **measured** boot of the klein set took 36 minutes on a
4090 host with a link that kept stalling.

The prefetch logs one line a minute per file:

```
prefetch base start repo=black-forest-labs/FLUX.2-klein-base-9b-fp8 token=set
prefetch base 42% 4020/9570 MB 18.4 MB/s
prefetch base done 9.57 GB in 8.7 min
```

`Trying to resume download...` is normal. Hugging Face retries a stalled transfer from the partial file, up to five times. If the fifth fails, the prefetch prints `prefetch <name> FAILED`, then `prefetch aborted, missing ... (will not start Comfy)`, and the container exits. Raise the two timeouts above on a host that stalls.

The vast.ai log API returned an empty file for these instances in every request during the measured run, both the container log and the daemon log. Read the log pane in the vast.ai console, or use the endpoints in §5.6.

---

### 5.6 Check the instance

The wrapper answers `GET /health` and `GET /ready` on the mapped host port for container `3000` (a ready response is `{"version":"1.19.2","status":"ready"}`), and Comfy answers `/system_stats` and `/queue` on the mapped `8188` port. `/ready` on the wrapper is the single check that the whole image is up; it waits for Comfy, so it does not answer first.

---

### 5.7 Wire it into the app

On **Config**, **Vast.ai**, add the address or press **Fetch instances from Vast.ai**, then select the row (the dot in **Use** marks it). On **Config**, **Profile**, set the target to **Vast.ai instance**, set the URL, and press **Save profile**; **Use the selected instance** fills it from the active row. Press **Generate** and the request queues on the profile's line.

The app derives the endpoint from the mapped ports. It prefers the wrapper on 3000, which resolves Civitai LoRA URLs, and falls back to Comfy on 8188 or 18188, or to the instance's only other non-ssh port. §5.8 explains why.

---

### 5.8 Pick the port by what the graph needs

| Port | Process | Civitai LoRA URLs | Response | Speed |
| --- | --- | --- | --- | --- |
| 3000 | Salad API wrapper | Works. It downloads the LoRA with the token, then runs the graph | The image comes back in the POST response as base64 | Slower on the first render, cached after |
| 8188 | ComfyUI | Fails. `LoraLoader.lora_name` must be a file under `models/loras/` | `prompt_id`, then `/history`, then `/view` | Faster |

**Measured** on 2026-10-17, same graph, same 4090: the wrapper returned a
1568x1264 JPEG of 288,716 bytes in 126 seconds cold and 3.4 seconds with the
LoRA cached. Comfy on `8188` rejected the same graph with
`value_not_in_list ... lora_name: 'https://civitai.com/...' not in []`. With the
LoRA node removed, Comfy returned a 2.39 MB PNG in 88 seconds.

The wrapper is the right endpoint for this app's graphs, because the profiles
carry Civitai LoRA URLs. Keep the row on the wrapper port. `instance_endpoint`
prefers `3000` whenever the instance maps it, so a Salad image's row points at
the wrapper even when Comfy's `8188` is also mapped. A 200 answer with no plate
is reported by name, not retried.

---

### 5.9 Failure modes

| Symptom | Cause | Fix |
| --- | --- | --- |
| `unresolvable CDI devices .../gpu=1: unknown` at container create | That host's gvisor setup cannot inject the GPU device | Destroy the instance and rent from another host. Not the image |
| Comfy exits at startup and the log names an old CUDA driver | Host `cuda_max_good` below 13.0, usually a 535 driver | Pick a host with a 580 or newer driver |
| Both ports closed for a long time | The prefetch is still downloading | Check the set size in §1.2. Raise the HF timeouts on the next instance |
| `prefetch <name> FAILED`, then `prefetch aborted, missing` | A download failed, usually the token, the gated-model terms, or the link | Check `HF_TOKEN` and accept the model terms on Hugging Face. Recreate with longer timeouts |
| `401` or `403` from `huggingface.co` | The token lacks access, or the account has not accepted the gated terms | Fix the token on **Tokens**, or accept the terms |
| `value_not_in_list ... lora_name: 'https://...'` | The graph reached plain ComfyUI on `8188` | Point the row at the wrapper port, or bake the LoRA into the image |
| The vast.ai log pane is empty | The log API returned an empty file for these instances during the measured run | Use the endpoints in §5.6 |

Two of these deserve a note. The gvisor error is host-specific: host 53447 also listed `CONTAINER_RUNTIME=gvisor` and created the container without the error, so the runtime name alone does not predict the failure. The CUDA failure was diagnosed from the host record (`cuda_max_good` 12.2 against the image's 13.0 runtime); the user's console log named an old CUDA driver, which matches.

---

### 5.10 Cost and shutdown

A 4090 ran at **$0.363/hr measured**. The app does not stop a vast.ai instance.
Destroy it when you finish, from the vast.ai console or with
`vastai destroy instance <id>`. A stopped instance still bills for its disk.

---

### 5.11 What was measured, and where

The live run on 2026-10-17 used three hosts:

| Host | CUDA | Result |
| --- | --- | --- |
| 28421 | 13.1, RTX 4090 | Container create failed on the gvisor CDI error. The instance never started |
| 53447 | 12.2, RTX 4090 | The container ran but Comfy never served. The CUDA driver was older than the image's runtime |
| 134629 | 13.0, RTX 4090 | The container served. Both endpoints answered, and both render paths produced plates |

The set sizes are the Hugging Face file sizes from `salad_klein/prefetch.py`, and the deploy line
comes from `salad_studio/image_deploy.py` (`vast_create_command`).

## Appendix: sources, with dates

Pricing (4090 High **$0.330** / Lowest **$0.160**; 5090 High **$0.500**), checked 2026-09-16: <https://blog.salad.com/saladcloud-price-changes-september-2026/> + <https://salad.com/pricing>. Product shape, API base, org/project, checked 2026-09-24: <https://docs.salad.com/container-engine/reference/recipes/comfyui> + `salad_status.py`. ToS (last updated 2024-12-09) and chef workload preferences, checked 2026-09-16: <https://salad.com/terms/saladcloud>, <https://support.salad.com/guides/getting-jobs/workload-preferences/>. Portal field values and probe timings, checked 2026-09-23: this repo's doc 15 "Live groups" and "What you will run".
