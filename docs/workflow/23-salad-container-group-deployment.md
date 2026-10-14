# 23. Salad container groups: build the image, call the container

The single reference for **creating a Salad container image** and **calling into
a Salad container** (and its control-plane API). Everything operational that used
to be spread across the game repo's `docs/workflow/13-gpu-host-catalog-plans.md`
Plan D and this repo's `docs/workflow/15` now lands here.

> **Status:** consolidated 2026-09-24 from the game repo's Plan D (SaladCloud
> group mechanics, 2026-09-16/17) + this repo's doc 15 §0–6 (the runbook that
> was actually used) + `salad_studio/salad_status.py` (the API client).
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

| | Control plane | The running container |
|---|---|---|
| Base | `https://api.salad.com/api/public` | `https://<group>-<hash>.salad.cloud` |
| Auth | `Salad-Api-Key: <key>` | none by default (the gateway is public) |
| What it does | create/patch/stop/start groups, reallocate replicas, read status and logs | run the workload: Comfy's `/prompt`, `/health`, `/ready` |
| Client | `salad_studio/salad_status.py` | `salad_gen.py`, `salad_probe_*.py`, `salad_catalog_faces.py` |
| Portal equivalent | portal.salad.com | the group's access domain |

A group's gateway DNS is the only handle the client keeps; the control plane is
how you find the group behind it (`find_group_by_gateway`).

---

## 1. Build the container image

### 1.1 The build tree

`salad_klein/` is a self-contained build context. Its own
[`README.md`](../../salad_klein/README.md) is the short form of this section.

| File | Role |
|---|---|
| `Dockerfile` | the image recipe; `FROM ghcr.io/saladtechnologies/comfyui-api:comfy0.35.0-api1.19.2-torch2.13.0-cuda13.0-runtime` |
| `manifest.yaml` | the build manifest |
| `prefetch.py` | the ENTRYPOINT: inflates a sidecar/misnamed zip, else downloads the weights in parallel, then `exec`s `comfyui-api` |
| `weights_zip.py` | sidecar-zip detection and inflation (used by `prefetch.py`) |
| `check_hf_download.py` | gated-HF reachability check |
| `RGTHREE_COMMIT.txt` | the pinned `rgthree-comfy` commit |
| `.dockerignore` | keeps weights out of the context |
| `prompt_*.json` | the Comfy graphs the container is asked to run |
| `prompt_catalog.json`, `prompt_ledger.json` | successful-prompt catalog + human verdicts |
| `weights/.gitignore` | the staging target for local builds (weights themselves are not committed) |
| `test_prefetch.py`, `test_http.py`, `test_hf_gated_access.py` | tests for the above |

### 1.2 The two images: one per unet family

One Dockerfile, built **twice** — once per unet family — and each family's group
runs its own tag. The build arg `KLEIN_UNET_SET` decides what the first boot
downloads, and that is the only difference between the two images.

| Family | Tag | `KLEIN_UNET_SET` | Unets on disk after the first boot |
|---|---|---|---|
| `klein` | `docker.io/vkozyrev0/eldermark-klein:comfy0.35-api1.19.2-prefetch6-klein` | `base,distilled` | `flux-2-klein-base-9b-fp8.safetensors`, `flux-2-klein-9b-fp8.safetensors` |
| `snofs` | `docker.io/vkozyrev0/eldermark-klein:comfy0.35-api1.19.2-prefetch6-snofs` | `snofs` | `snofsSexNudesAndOther_distilledV12KleinFp8.safetensors` |

The family-to-image mapping is shipped in
[`salad_studio/studio-metadata.json`](../../salad_studio/studio-metadata.json)
(`routing.families.<family>.image`), which is what the Config page's **image
tag** field is seeded from; `tests/test_docs_match.py` fails if this table stops
naming an image, a unet or the build arg the document ships.

Build and push both (`RGTHREE_COMMIT.txt` pins the node copy; weights are never
baked):

```bash
git clone --depth 1 https://github.com/rgthree/rgthree-comfy.git salad_klein/custom_nodes/rgthree-comfy
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
| ENTRYPOINT | `python /prefetch.py` — parallel weight download, then `exec ./comfyui-api` |
| Custom nodes | `rgthree-comfy` (Image Comparer, Power Lora Loader) at the pinned commit |
| Weights | none in any layer: the first boot fetches the set this tag was built for (~10 GB+) |
| Size | ~12 GB image; a new replica re-downloads, because node storage is ephemeral |

Both tags are interchangeable as a container **image**: the Config page's
**image tag** (a Salad group policy) takes either one, and so does a **vast.ai
instance** — see the Config page's Vast.ai instances section in
[`salad_studio/README.md`](../../salad_studio/README.md). What a group may render
is decided by the family its tag bakes, not by the tag's name.

**The app renders all of this**: the Config page's **Container images** section
shows these fields for each tag (context, base image, build arg, ports, GPU,
disk, environment) and copies the build, run and `vastai create` commands, so the
deploy parameters live in one place instead of in this document alone. The page
reads them from `routing.families.<family>.deployment` in
[`salad_studio/studio-metadata.json`](../../salad_studio/studio-metadata.json);
the values below are the same ones.

### 1.3 The two hard rules

- **Do not `COPY` the unet / CLIP / VAE into the image**, and **do not
  `RUN unzip`** in the Dockerfile. That writes uncompressed tensors into an
  image layer (~30 GB). Zip is transport only; the image stays ~12 GB.
- **Do not `FROM` a `flux1dev` Salad tag.** It OOMs or 524s on a 24 GB card for
  Klein graphs.

`prefetch.py` is the only thing that puts weights on disk, at **first boot**, not
at build:

1. If a `.zip` sits next to the Comfy path, or a zip was misnamed
   `*.safetensors`, inflate it to the real `.safetensors` filename.
2. Otherwise download the unet set the tag was built for (`KLEIN_UNET_SET`, see
   §1.2), the CLIP and the VAE **in parallel**.
3. `exec` `comfyui-api`. Comfy only ever sees raw `.safetensors`.

### 1.4 Staging weights locally (optional)

`model_catalog.py` can cache the same files in the gitignored
`art/model-cache/hf/` and hardlink them into the build tree:

```bash
python model_catalog.py fetch-klein --stage
```

`--stage` targets `$SALAD_STUDIO_HOME/salad_klein/weights/` (this repo by
default). Salad never sees that cache. The container URL-loads on a new replica
instead, and the LoRA URLs carry the Civitai token at POST time.

> **Known duplication:** `model_catalog.py` exists in **both** repos. The game
> repo keeps a copy because it manages `art/model-cache/` there and its own test
> asserts that repo's ignore rules. This repo's copy is the one the Studio
> package imports (`salad_studio/lora_store.py`). Edit both, or delete the game
> repo's copy once nothing there uses it.

---

## 2. Create the container group

### 2.1 What a Salad group is (the host-side mechanics)

- **Product shape, Salad Container Engine.** You push a Docker image, set a GPU
  class + priority and N replicas. Interruptible community nodes; **Salad
  Dedicated** is reserved DC hardware. Container-first, not SSH-first.
- **GPU classes.** RTX 3060 up to **RTX 4090 24 GB** and **RTX 5090 32 GB** on
  Community. No H100/A100 there; a 48 GB+ card means Dedicated or another host.
  A class is identified by a UUID. The docs example for a 4090 is
  `ed563892-aacd-40f5-80b7-90c9be6c759b`. `salad_status.list_gpu_classes()` reads
  the live list.
- **Priority.** `high` or `batch`/lowest. Preemption hurts a one-shot catalog, so
  use High for a full run and Lowest for probes.
- **Storage is ephemeral.** Nodes do not persist `/opt/ComfyUI/models`; every new
  instance re-downloads. Keep progress files (`regen_progress.json`) on the
  Windows side, never only on the node.
- **Billing is prepaid, per-second while running.** Allocation, image pull and
  cold start are not billed, but a huge pull still costs wall-clock.
- **No per-image safety classifier** on the container path: your image runs
  Comfy. The residual filter is the ToS (CSAM/illegal-content clause, any-reason
  refusal) plus chef/node disconnects, not a Google `IMAGE_SAFETY` 422.
- **Adult workloads are a chef preference**, not an "anything goes" promise.
  Chefs in anti-porn jurisdictions are excluded from those jobs.
- ToS: <https://salad.com/terms/saladcloud>.

### 2.2 Portal fields

https://portal.salad.com, create a **new** group; never edit an unrelated one.

| Field | Set |
|---|---|
| Image | the family's tag from §1.2: `vkozyrev0/eldermark-klein:comfy0.35-api1.19.2-prefetch6-klein` for a Klein group, `…-prefetch6-snofs` for the SNOFS one (private registry: add pull credentials) |
| GPU | RTX 4090 (24 GB). Lowest priority is fine for probes |
| vCPU / RAM | 4+ / **30 GB** |
| Replicas | **1** until `/ready` is green |
| Container gateway | **On**, port **3000**, least-connection |
| Auth | **On** (`Salad-Api-Key`) |
| Startup probe | `GET /health`, delay **600**, period **120**, fail **20** (~50 min). `timeout_seconds` is per-GET, not the boot window |
| Readiness probe | `GET /ready` |
| Env | `HF_TOKEN`; `CIVITAI_API_TOKEN` if Civitai 401s; `STARTUP_CHECK_MAX_TRIES=120` (already in the Dockerfile, keep it) |

### 2.3 Move steps, condensed

1. Prepaid org in the Salad portal.
2. Build and push the image (§1).
3. Create the group with §2.2's fields; scale replicas 1→N.
4. Wait for `/ready` 200 (first replica pulls ~12 GB, then prefetch ~17 GB).
5. Point the caller at the group's gateway DNS; keep progress local.
6. Scale to 0 when done.

### 2.4 Risks

- Home GPUs: variable actual VRAM, driver oddities, random disconnects. High
  priority is still "subject to node disconnection".
- The image must be self-contained; the first replica pays wall-clock for a huge
  pull even when Salad does not bill it.
- 24 GB is tight for Flux-dev but standard; there is no 48 GB Community card.

---

## 3. Call into a running container

The gateway is `<group>-<hash>.salad.cloud`, saved to a per-group file
(`~/.config/salad/gateway-klein`), never over the Flux.1 `gateway` file.

| Purpose | Request |
|---|---|
| Liveness | `GET /health` on port 3000 |
| Readiness | `GET /ready` on port 3000. 503 until Comfy listens |
| Run a graph | `POST /prompt` with the Comfy API body (the `prompt_*.json` files) |
| Result | `GET /history/<prompt_id>` then `/view` for the image |

`salad_gen.py`, `salad_probe_klein.py`, `salad_probe_ages.py`,
`salad_probe_sdxl.py`, `salad_catalog_faces.py` and `salad_age_review.py` are the
working callers. Studio's **Ready** badge and Generate's `/ready` pre-probe use
the same path, and Studio skips the `/ready` probe while a replica is still
pulling so a stale 200 cannot be trusted.

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

Practical notes:

- A group's `startup_probe` / `readiness_probe` are readable and patchable;
  `explain_probe()` turns them into the "Salad waits {delay}s, then GET {path}"
  explanation the Studio shows.
- **Do not DELETE a group.** Salad does not reuse the name or gateway DNS; a
  delete mints a new group and DNS. Stop/start, reallocate, and image PATCH only.
- `_ORIGIN_DOWN_CODES = (0, 520, 521, 522, 523, 524)` marks an origin that is
  down rather than still starting.
- Never log `networking.auth` or the container's `environment_variables`.

---

## 5. Where the knowledge lives

| Subject | File |
|---|---|
| Build context + short build how-to | `salad_klein/README.md` |
| Image recipe, prefetch, manifest | `salad_klein/Dockerfile`, `prefetch.py`, `manifest.yaml`, `weights_zip.py` |
| Live groups, probes, recipe, rebuild runbook | [`15`](15-salad-flux2-klein-group.md) |
| Operating point + group→graph routing + failure modes | [`21`](21-klein-image-handoff.md) |
| Studio-side group/policy UI, gateway files | [`../salad_studio/README.md`](../../salad_studio/README.md) |
| Control-plane + gateway client | `salad_studio/salad_status.py` |
| Weights bake/stage tool | `model_catalog.py` |
| Host comparison and why Salad was chosen | game repo `docs/workflow/13-gpu-host-catalog-plans.md` |

## 6. Sources, with dates

| Claim | Source | Checked |
|---|---|---|
| Pricing (4090 High $0.330 / Lowest $0.160; 5090 High $0.500) | <https://blog.salad.com/saladcloud-price-changes-september-2026/> + <https://salad.com/pricing> | 2026-09-16 |
| ToS / content-restriction language | <https://salad.com/terms/saladcloud> (last updated 2024-12-09) | 2026-09-16 |
| Workload preferences (chef opt-in) | <https://support.salad.com/guides/getting-jobs/workload-preferences/> | 2026-09-16 |
| Container Engine product shape, API base, org/project | <https://docs.salad.com/container-engine/reference/recipes/comfyui> + `salad_status.py` | 2026-09-24 |
| Portal field values, probe timings, group names | this repo's doc 15 §4 and §"Live groups" | 2026-09-23 |
