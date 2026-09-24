# 14 — SaladCloud Comfy live findings (faces / bodies / events / sex)

> **Status: LIVE OPS + PROBE LOG (2026-09-18).** This is the load-first
> artifact for the **running** Salad Flux.1-dev Comfy group. Do **not**
> re-run the Civitai/Salad investigations below.
>
> Host-ranking research (Vast/RunPod ToS, fal 422 overreach) still lives
> in [`13-gpu-host-catalog-plans.md`](C:/Users/vkozy/repos/lifesim-design/docs/workflow/13-gpu-host-catalog-plans.md). That
> file’s old “RESEARCH / no pods / live T2I is banana-pro only” banner is
> **stale** for Salad: a Comfy group is deployed and was used for probes.
>
> **Mass catalog freeze.** Batch face regen is **stopped** until faces,
> bodies, events, and sex each have an **explicit chosen model**. Do not
> run `salad_catalog_faces.py --generate` (or mass `regen_faces.py`) until
> those four picks exist. Pause sentinel:
> `art/catalog/face/salad_PAUSE.txt`. Chosen models stay **TBD** except
> this freeze.

Sex in the sim is **18+ only**. Infant/child plates are non-sexual DNA
portraits. Salad’s container does **not** 422 those infant DNA plates
(the fal banana-pro IMAGE_SAFETY overreach does). CSAM/illegal stay
banned in Salad ToS.

Secrets stay **out of git**: Salad key `~/.config/salad/key`, gateway
`~/.config/salad/gateway`, Civitai token `~/.config/civitai/token`.

---

## 1. Salad Comfy as actually used

| Field | Live value |
|---|---|
| Recipe | Salad **ComfyUI API Flux.1 Dev** (portal recipe), not a custom Krea image |
| Comfy API | **~1.10** (`/docs/json` reports 1.10.0). Newer 1.16 `/download` is **absent** |
| Endpoints | `GET /ready`, `POST /prompt` (graph JSON in, base64 JPEG out). `GET /models` lists cached files |
| Auth | Header `Salad-Api-Key` |
| GPUs | **2× RTX 4090** High, ~$0.66/hr combined when both Ready |
| Baked checkpoint | `flux1-dev-fp8.safetensors` already on the recipe (CheckpointLoaderSimple) |
| Timeout | Salad gateway / Cloudflare **~100 s** (HTTP **524**). First pull of a ~7 GB SDXL file can just make it; ~12 GB Flux extra often 524s mid-download |
| Queue | `--queue-depth 7` on two replicas; 502/503 retry, do not stall 180 s if the other replica serves |
| Infant plates | **No per-image IMAGE_SAFETY 422.** Newborn DNA T2I succeeded on this pod |
| Official Salad Comfy recipes | Dreamshaper 8, **FLUX.1-Dev**, FLUX.1-Schnell, **SDXL**, **SD 3.5 Medium**. **Not Krea 2** ([recipe list](https://docs.salad.com/container-engine/reference/recipes/comfyui)) |

### Architecture limits (do not re-discover)

- **VRAM.** The recipe already holds Flux-dev fp8 (~12 GB) in 24 GB 4090 VRAM. A **second ~12 GB Flux checkpoint** (UltraReal Fine-Tune, Civitai stock Flux-dev fp32) **OOMs** next to the baked weights (`HTTP 500` / “Failed to get prompt outputs”).
- **URL loads.** `CheckpointLoaderSimple` and `LoraLoader` accept `https://civitai.com/api/download/models/…` (token query + `credentials` Bearer). Hugging Face URLs on API 1.10 are **broken** (hf CLI 408 logs treated as a file path).
- **CLIPVisionLoader cannot URL-load** SigCLIP / Flux Redux. `clip_vision` dir is empty; the node validates `clip_name not in []` **before** download. **IP-Adapter, PuLID, InstantID nodes are absent.** Face-lock onto bodies needs a **new image** with Redux+SigCLIP baked in, not a prompt tweak.
- **Krea 2** (FasciumKROMA, KreaKult, latest Sean Archer Krea variants) needs a **separate** Comfy group (Krea 2 Turbo + Qwen3-VL + Qwen Image VAE). This Flux recipe cannot run them. Loading a Krea 2 LoRA on Flux-dev is a silent no-op (keys ignored).
- **Identity.** Without Redux/IP-Adapter, body T2I can match **phenotype** (fair / blonde / blue / age) only. Pipeline for same-person bodies: generate the **face plate first**, then feed it to Redux/IP-Adapter. That second step is **blocked** on this pod.

### Tools (probe only; mass gen frozen)

| Script | Role |
|---|---|
| `salad_gen.py` | `POST /prompt` Flux graph; optional `ckpt_name` / `lora_name` |
| `salad_catalog_faces.py` | Mass face catalog. **`--generate` exits if `salad_PAUSE.txt` exists** unless `--ignore-pause` |
| `salad_probe_ages.py` | Age×sex face probes (`--prefix`, `--ckpt`, `--lora`) |

HOUSE for Flux faces: photoreal DSLR 85mm string **first**, then `Portrait of a man/woman`, then age (sex-neutral). Do not put `TRUE woman/man` in the age line (CLIP latched onto **woman** for male thirties). Adult males get a short haircut + `woman, female` in the negative.

---

## 2. Probe outcomes by kind

**Chosen model for each kind: TBD.** The freeze exists *until* those four
picks are written here as chosen, not merely “working in a probe.”

### Faces

Working photoreal house on **this** pod: **Flux.1-dev fp8 + UltraRealPhoto LoRA**
(Civitai **796382**, version **1026423**, strength ~0.65). Age×sex probes:
`art/salad_probe_ultrareal_{sex}_{stage}.jpg`.

| Tried | Civitai | Result | Re-download? |
|---|---|---|---|
| Flux-dev fp8 (recipe) | — (baked `flux1-dev-fp8.safetensors`) | Photoreal HOUSE after prompt-order fix; infants OK; no 422 | Keep; already on pod |
| UltraRealPhoto LoRA | **796382** @ 1026423 | **Working photoreal house** on Flux-dev | No need to re-pull if cached |
| UltraReal Fine-Tune ckpt | **978314** @ 1413133 fp8 | Downloaded; **OOM** as second ~12 GB Flux | **Do not re-download** |
| Stock Flux Dev (Civitai) | **618692** @ **691639** | Same family as the recipe (fp32 16–23 GB). Not a new look | **Do not re-download** |
| Golden Hour (Illustrious) | **2433139** @ 3302765 | Semi-real illustration, sparkle, age collapse, androgynous males | Do not use as face house |
| PhotoStyle Sean Archer LoRA | **1632416** @ 2548590 (Flux.1 D only) | Glam female portraits; **male plates are women**; infants are toddlers | Not a DNA house |
| Art Nouveau LoRA | **562604** | MJ/Mucha **style** LoRA, not a face model. Flux variant exists (~18 MB) | **Do not use as face house** |
| KreaKult LoRA | **2758431** (Krea 2 only) | Silent no-op on Flux-dev | **Do not re-download on this Flux pod** |
| FasciumKROMA ckpt | **2888019** (Krea 2 ~12.5 GB) | Cannot load; would OOM even if forced | **Do not re-download on this Flux pod** |

### Bodies

Catalog spec (not yet met as a chosen house): front-facing, collarbone–mid-shin
**or** full figure head-to-feet if that is the signed crop; male = male;
pregnant bump; magenta; cream linen — **not** green gowns / back views.

| Tried | Civitai | Result | Re-download? |
|---|---|---|---|
| Golden Hour | **2433139** | **Failed** front/crop/male: back views, “male” is a woman, half-head + full-leg clip, green dress, interiors | Do not use for body plates |
| Flux-dev + UltraRealPhoto | **796382** | Front-facing, magenta, males are male, pregnant mid/late bump. **768×1024** still showed heads/feet. **768×1408 full-body** keeps **legs in frame**; identity is **phenotype-only** (not the face plate) | Working probe, not a chosen house |
| Sean Archer LoRA | **1632416** @ 2548590 | Female glamour/lingerie; male is a woman; pregnant legs cropped | Not a body house |

### Sex (18+ adults only)

| Tried | Civitai | Result | Re-download? |
|---|---|---|---|
| Flux-dev fp8 | baked | Adult nudes **without** visible insertion; host does **not** 422 | Wrong checkpoint for explicit plates |
| Pony Diffusion V6 XL | **257749** @ 290640 | Explicit genitals/insertion; illustrated; `source_pony` = MLP | Illustrated only |
| WAI-illustrious-SDXL v17 | **827184** @ 2883731 | Explicit, cleanest anatomy of the illustrated set; anime | Illustrated only |
| Illustrious Realism Enhancer LoRA | **1115090** @ 1253047 | Semi-real 3D on WAI; still not Lustify photoreal | Optional style LoRA |
| XXMix_9realistic SDXL | **124421** @ 163192 | Public photoreal SDXL; **refused sex** (clothed glamour) | Skip |
| Lustify V7 GGWP | **573152** / version **2155386** | **Draws explicit adult insertion** (doggy + missionary probes). Civitai **401** without token | Working sex probe; needs token. **Not a chosen house until signed off** |
| Lustify later (V8–V10) | same 573152 | V10 is **Krea 2**, not SDXL | Do not load V10 on this Flux/SDXL graph |

Grok Imagine **content-moderated** the same explicit doggy prompt (400). Salad did not.

### Events

**Not a chosen house.** Klein 9B event probes this session
(`salad_probe_klein.py` → `art/salad_probe_klein_event_*.jpg`):
wedding, funeral, harvest, tavern, storm, birth (non-sexual midwife).
Harvest is the strongest — painterly landscape, readable scene. Not
signed off as event house. Catalog/fal aquarelle path stays until chosen.

### Klein 9B probes (flux2-klein group, 2026-09-19)

Gateway `~/.config/salad/gateway-klein`. Graph: UNET 9B-Base fp8 +
Qwen3-8B CLIP type `flux2` + flux2 VAE + Detail Slider + Impressionism
Klein9B. **27/27 HTTP 200** in ~4 min. Prefix
`art/salad_probe_klein_`. Mass catalog still frozen.

| Kind | Files | Notes |
|---|---|---|
| Faces | 12 (sex × infants/children/minors/young_adult/adults/elderly) | Impressionist + pack magenta chroma. Adult male is male. Infant reads toddler more than newborn. Some signatures. |
| Bodies | 6 (sex × front/45/side, adults) | Magenta. Male front is male but cropped above the feet; older than thirties. |
| Pregnancies | 3 (late front/45/side) | Bump visible. Cropped (not head-to-feet). |
| Events | 6 | See ### Events. Harvest strongest. |

**Retry (prompt postfix cream paper / full-figure / newborn / thirties):**
27/27 again. Pack **magenta chroma still wins** on faces/bodies (compose
includes `#FF00FF` and Klein follows it). Events stay cream (no pack
chroma). Male adult face is male. Bodies still often crop head or feet.
Infant still reads older than 0–3 months. **Not chosen.**

**Bodies are unusable as catalog paperdolls (2026-09-19, 150-plate
batch).** Root cause: `compose_body_prompt` is **headless by design**
(`face_prompt_pack.json` `body_style.frame` = collarbone-to-shin, face
out of frame; `global_must` = “headless”). Stacking that with
Impressionism Klein9B + `FULL_FIG` (crown-to-soles) made Klein resolve
the contradiction as smeared/ghost faces, cropped skulls, white oval
faces on males, and pregnancy as a brown sphere on the dress. Infants
stood as toddlers.

A/B `art/salad_probe_klein_bodyfix_*.jpg`: **plain (no LoRA) female
thirties front is a usable full figure** with a painted face. LoRA
plates melt. Male plain still blanked the face because the pack still
said headless.

Round 2 (`art/salad_probe_klein_bodyfix2_*.jpg`, painted-face prompt,
LoRA off): male thirties **front** and female **seventies** work
(standing human, head-to-feet). The word **paperdoll** was taken
literally — female thirties front became a rag doll; infant a reborn
doll with white eyes; male side a bald mannequin. Pregnant late is a
real bump under a gown (no brown sphere).

Round 3 (`art/salad_probe_klein_bodyfix3_*.jpg`): dropped “paperdoll”,
kept `ArsMJStyle` **text** with LoRA off. Female thirties front and
male side are painted standing humans (best so far). Mid-pregnancy
still reads not-pregnant. Infant is a standing toddler — “standing
figure” overrode lying/newborn; prompt now branches infants off
standing. Do **not** mass-regen the 150 until a recipe is accepted.
**Not chosen.**

---

## 3. Mass-generation freeze (policy)

Until **faces, bodies, events, and sex** each have an explicit chosen
model recorded in §2 as **chosen** (not merely “worked in a probe”):

1. Do **not** run `python salad_catalog_faces.py --generate`.
2. Do **not** pass `--ignore-pause` unless the user explicitly resumes.
3. Keep `art/catalog/face/salad_PAUSE.txt`. The generator already exits 2
   when that file exists.
4. Do **not** start a 5-minute scheduler that relaunches catalog gen when
   the PID is dead (that already burned GPU against a review pause).
5. Probe scripts (`salad_probe_ages.py`, one-off `/prompt`) are allowed
   **only** when the user asks for a named model probe — not as catalog
   rebuild.

Stop condition for this freeze: four one-line **chosen** entries in §2.

### Liked Civitai Klein LoRAs (research, 2026-09-19)

Eight reference plates the user named all run on **FLUX.2 Klein 9B**.
Do **not** rewrite `face_prompt_pack.json` magenta knockout for these —
catalog PNG cutouts still need chroma. Probe via Salad Studio / Klein
group after the LoRA is on the container. Rows are in
`model_catalog.py` `KNOWN` as `listed` (not chosen).

| Job | LoRA | Version | Ref image | Prompt lead |
|---|---|---|---|---|
| Faces | Classic Oil Painting - CE V03a @ **0.2** | 637213@**2760271** | [123717470](https://civitai.com/images/123717470) | `Painting on canvas. Texture. Brushstrokes.` then the person. No magenta. |
| Faces (no LoRA) | Klein checkpoint only | — | [128534350](https://civitai.com/images/128534350) | Painterly portrait + abstract canvas (not a studio crop). |
| Pretty-paint body / event | Painterly - CE V01b | 957327@**2725918** | [122476755](https://civitai.com/images/122476755) | `Oil painting style. Bold brushstrokes. Daubs of paint, alive with light.` |
| Pregnancy full body | Vintage Drawing - CE V01a | 660535@**2748101** | [123309022](https://civitai.com/images/123309022) | `Detailed vintage drawing style.` + `Full body view` / `Side view` + `[[[[[baby bump]]]]]`. |
| Event, aged oil | Aged Art - CE V01a | 1449678@**2795018** | [125047656](https://civitai.com/images/125047656) | `Aged art. Oil painting style.` then a short scene. |
| Event, rustic | Medieval - CE V02 | 754926@**2767494** | [123970913](https://civitai.com/images/123970913) | `Medieval style.` then a short scene. |
| Event, graphite | Artificeal v1.0 | 2745770@**3088444** | [135440425](https://civitai.com/images/135440425) | `Artificeal style artwork. Graphite sketch layer and abstract color layer.` |
| Event, watercolor | YFG Grud F.2 Klein 9B | 2715533@**3051077** | [134526753](https://civitai.com/images/134526753) | `YFG-Grud style.` — outlier, not the oil house. |

CreativeEdge plates: Euler, cfg **5**, **40** steps. None of these LoRAs
are pre-pulled on `flux2-klein` (Detail Slider / Impressionism included).
Jobs that need them send a Civitai URL on `LoraLoader`. **Not chosen.**

Civitai **on-site** generation is a different sampler stack than Salad
Comfy (native `flux2` + AIR LoRAs + **simple** schedule vs
`Flux2Scheduler` / `LoraLoader`). Matching Euler/CFG/steps/seed is
**not** a pixel clone. Quality work (Aged Art in the unet, optional
`BasicScheduler` `simple`, Import tab) lives in
[`15-salad-flux2-klein-group.md`](15-salad-flux2-klein-group.md)
§Matching Civitai. Probe via **Salad Studio**
(`salad_studio/`).

---

## 4. Do not re-download on this Flux pod

| ID | Why |
|---|---|
| Civitai **618692** @ 691639 | Stock Flux.1-dev fp32; same family as baked fp8 |
| Civitai **978314** UltraReal Fine-Tune | Second Flux ckpt; OOM |
| Civitai **2758431** KreaKult | Krea 2 LoRA |
| Civitai **2888019** FasciumKROMA | Krea 2 ~12.5 GB ckpt |
| Civitai **562604** Art Nouveau as a **face house** | Style LoRA (Mucha/MJ), fights DNA plates |
| Hugging Face `huggingface.co/…` URLs on API 1.10 | Downloader bug; use Civitai HTTP + token |

Civitai **401 Unauthorized** on Lustify / some realism LoRAs without
`~/.config/civitai/token`. Pony / WAI / XXMix allowed anonymous GET.

---

## 4b. Flux.2 Klein — not a drop-in on this Flux.1 group

Salad’s official Comfy recipes list Dreamshaper 8, **FLUX.1-Dev**,
FLUX.1-Schnell, **SDXL**, **SD 3.5 Medium**. **Flux.2 Klein is not on
that list.** The live recipe graph is `CheckpointLoaderSimple`
(`flux1-dev-fp8.safetensors`) + `FluxGuidance` + `EmptySD3LatentImage`
+ `KSampler`. Klein T2I is a different graph: `UNETLoader` +
`CLIPLoader` type `flux2` (`qwen_3_8b_fp8mixed`) + `VAELoader` +
`EmptyFlux2LatentImage` + `Flux2Scheduler` + `SamplerCustomAdvanced`
(Comfy-Org `image_flux2_text_to_image_9b.json`).

Liked CivitAI style https://civitai.com/images/135504982 is **Flux.2
Klein 9B-Base** (**2322332** @ **2612548**, bf16 16.91 GB) + Klein
Detail Slider (**2334190** @ **2625692**) + Impressionism Klein9B
(**545264** @ **2763568**, trigger `ArsMJStyle, Impressionism`), Euler,
832×1216 — not Flux.1-dev / Inzaniak Light. Do not use Flux.1
Impressionism **545264@755598** as a stand-in.

Klein LoRAs on Flux.1-dev are the same class of silent no-op as Krea
LoRAs. A second ~12–17 GB unet next to baked Flux.1 **OOMs** a 24 GB
4090 / Cloudflare **524**. Salad-capable path: a **separate** Comfy
group with baked fp8 unet + Qwen3-8B + flux2 VAE. Do **not** POST a
Klein graph at the live Flux.1 replica. How to build that group
(Docker + Portal):
[`15-salad-flux2-klein-group.md`](15-salad-flux2-klein-group.md).
Files: `salad_klein/`.

---

## 5. Pointers

- Pause file: `art/catalog/face/salad_PAUSE.txt`
- Host ranking (still valid as research): [`13-gpu-host-catalog-plans.md`](C:/Users/vkozy/repos/lifesim-design/docs/workflow/13-gpu-host-catalog-plans.md)
- Catalog spec: [`02-image-catalog.md`](C:/Users/vkozy/repos/lifesim-design/docs/systems/02-image-catalog.md)
- Face compose: `salad_catalog_faces.py` `HOUSE` + `compose()`
- Body compose: `face_prompt.py` `compose_body_prompt`
- Local LoRA/checkpoint cache (gitignored): `art/model-cache/` — `python model_catalog.py seed` then `fetch-missing`. Each index row keeps Civitai page + version id + sha256. Salad still URL-loads on a new replica; this cache is this machine + a future custom image bake. UltraRealPhoto v2 is ~2 GB — metadata only unless `--force`.
- Flux.2 Klein custom group **`flux2-klein`** (`life-sim` / `default`,
  gateway `~/.config/salad/gateway-klein`):
  [`15-salad-flux2-klein-group.md`](15-salad-flux2-klein-group.md) +
  `salad_klein/`
