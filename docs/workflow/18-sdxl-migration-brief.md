# 18. The SDXL migration premise is UNVERIFIED (and one real bug fix)

**Written 2026-09-22** from a second `/deep-research` pass (110 agents, 25 claims adversarially
verified → **18 confirmed, 7 refuted, 0 unverified**). Companion to
`docs/workflow/17-klein-two-body-anatomy-research.md`, which documents the Klein conclusion.

**Scope:** 18+ adults only, two adults, no minors, nothing illegal. Research only. No images
were generated.

---

## 1. Headline: the hypothesis this pass was built to test failed to be confirmed

We asked it to test this claim, which I had asserted confidently:

> *"The mature ecosystem for this content is SDXL-family … a search for hand/limb fixers found
> only SDXL/Illustrious models, none Klein-native."*

**Verdict: not tested, and not supported.** No claim in the pass measures anatomy quality in
**multi-person interlocked compositions** for any Illustrious, NoobAI, Pony or other SDXL
finetune. The two SDXL-family pages surfaced as candidates, **HomoSimile XL** and **JANKU**,
were checked in full and contain **zero** multi-person anatomy evaluation. Their only anatomy
material is negative-prompt boilerplate plus one untested promotional line (*"Better anatomy
(yes, even in complicated poses)"*); full-text searches return **zero** hits for
`2girl / plural / two-person / interlock` and **zero** for `missionary / cowgirl / doggy /
spooning / prone`.

So the premise, "SDXL-family is where the mature two-person ecosystem lives", remains an
**inference imported from a fixer-LoRA search**, not a verified finding. That inference was mine,
and I should not have stated it as fact.

**And the base architecture has peer-reviewed evidence against it.** On the HumanRefiner study
(ECCV 2024, arXiv 2407.06937), frozen **SDXL 1.0 was the worst entry on abnormal-anatomy
severity** of the whole comparison except HumanSD, on the HumanArt hard split (Abnormal Score
**0.857** vs SSD-1B 0.832, Pose-T2I-Adapter 0.807, HumanSD 0.801), with the worst LAION FID among
non-HumanSD entries (30.024 vs 16.465). Scope limits that keep this from settling the question:
it measures **base SDXL 1.0, not a finetune**, on **single-person prompts**. But it does falsify
"SDXL lineage is anatomy-safe by itself". Corroborated by WACV 2026 *"We Still See Broken Limbs"*
and an ICLR 2025 submission also reporting SDXL limb-placement defects.

> Method note: **6 of the 18 confirmed claims are scoped negatives about web pages** ("this page
> contains no X"), not about the world. They license *"no evidence for SDXL anatomy quality was
> found"*, never *"SDXL anatomy quality is bad."* Read §1 accordingly.

---

## 2. What it DID establish, and two of these are blockers, not open questions

### 2.1 Per-partner DNA control has a verified failure mode (blocker for requirement 5)

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

### 2.2 Camera angle has no SDXL path (blocker for requirement 6)

The only camera-control node found emits camera-*movement* instructions for an image-to-image
LoRA that exists **solely for Qwen-Image-Edit-2509**; its shipped workflow contains no SDXL,
Flux, Illustrious, Pony or Klein checkpoint string anywhere. Requirement 6 has no verified answer
**in either family**.

### 2.3 Two-person pose conditioning: unverified, but NOT unavailable

No concrete two-skeleton OpenPose recipe for SDXL 1024 was verified in this pass, no node pack,
no preprocessor, no handler, no documented limits for overlapping interlocked bodies. **This is
the single highest-value unanswered operational question.**

Important scope correction from the verifiers: the most-cited large NSFW pose pack (525 poses) is
**solo-only and SD 1.5** (512×768 / 768×512, ships JSON keypoints, no SDXL version), but
dedicated **couple pose packs do exist** (`couplePose1_v10`, `couplesPoses2_v10`, Qpipi
couple/multi-character packs), and Illustrious-XL ControlNet OpenPose exists (users report
matching-preprocessor requirements, prompt-adherence problems, black previews). So the correct
statement is *"no verified recipe"*, **not** *"two-person pose conditioning is unavailable."*

### 2.4 Four of the nine required outputs have ZERO surviving evidence

Fixer LoRAs with weights/ranges/triggers/conflicts (3); genital-act correctness and the wrong-act
failure mode (4); SDXL camera control (6); style aftereffects (7). The ControlNet-Tile
structure-preserving recipe that would have covered style, `denoise 0.3–0.4`, control mode
*"My prompt is more important"*, preprocessor `none`, was **refuted 1-2** in verification, as was
the claim that the official SDXL ControlNet Tile card forbids adult content (**refuted 0-3**).
Medieval backgrounds remain unverified. **Any recommendation in these areas would be fabrication
from this evidence base.**

---

## 3. Salad Cloud, fully answered, and directly actionable

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

### 3.1 But do NOT reach for `models.before_start`, our repo already rejected it, for a reason

The research recommends `manifest.yaml` `models.before_start` (vendor-documented, and the
`comfyui-api` OSS README numbers it as startup steps 4/5). **Our repo deliberately keeps it
empty**, `salad_klein/manifest.yaml`:

> `# Empty: Salad's wrapper downloads before_start files one-by-one and that is what the startup`
> `# probe was killing. prefetch.py pulls all three in parallel, then execs comfyui-api.`
> `# Civitai LoRAs stay URL-loaded.`, `models:` / `before_start: []`

Salad's **sequential** `before_start` download is what caused a 25-minute startup (doc 15 §261,
§280, §338, §441, §519), and `test_prefetch.py:32` asserts the file stays `before_start: []`.
**Putting URLs back there would reintroduce a bug we already fixed.**

### 3.2 DECIDED (2026-09-22). Verify the LoRA URL; do not download

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

> **Be clear about what this does not do.** It does **not** remove the 100 s-cap risk. All four
> house LoRA URLs resolve HTTP 200, so a URL check would not have caught the 524 we reproduced,
> that failure was **duration inside the render**, not an invalid URL. The URL check turns a
> *wrong* URL into a clear early error; it does not make a *correct* URL faster.
>
> **But the LoRA download is probably not the dominant cost, and this section previously
> overstated it using an atypical file.** Real LoRA sizes (22 rows in the catalog): **median
> 165.7 MB**; our four are **21, 21, 83 and 331 MB, 456 MB total**. At the ~8 MB/s seen on a slow
> node that is roughly **3 s, 3 s, 10 s and 41 s, ~57 s for all four**, not the minutes implied
> by the 2.14 GB file used for the cold-path test. That file (`UltraRealPhoto`) is the **single
> largest row in the catalog** and was a poor choice of example.
>
> The better-supported reading is that the render sat **near the cap already**, and the LoRA fetch
> was the **marginal extra** that tipped LoRA-bearing graphs over while the LoRA-free arm squeaked
> under. Nothing enormous is required: our four LoRAs total ~456 MB, which is ~57 s at a slow
> node's 8 MB/s, easily enough to push a 60–90 s render past 100 s.
>
> **Why a LoRA fetch is the only download a render can contain.** Everything else is prefetched:
> `prefetch.py` is the container ENTRYPOINT, pulls the two Klein unets, the SNOFS unet, the Qwen
> CLIP and the VAE **in parallel** to disk, and **aborts startup** (`will not start Comfy`) rather
> than serve without them. So there is no unet download inside a render. What a cold container
> *does* pay inside its first render is **loading** those weights into memory, disk → RAM/VRAM,
> one-off, and not something `prefetch.py` can pre-empt, since it only places files on disk. (The
> smoke render with LoRAs already warm took **119.6 s**, consistent with that load.)
>
> So the LoRA fetch is the sole *download* that can occur mid-render, and the sole variable with
> both the right size and the right timing to explain LoRA-bearing graphs failing while the
> LoRA-free arm passed. It is still **not isolated**: nothing measured yet separates load time from
> fetch time within a render.
>
> If it recurs, the mechanisms already scoped are `POST /download` with `wait: true` (measured:
> **29.7 s** for a 2.14 GB cold file, and `completed in 0.0s` when cached) or Salad's **Job
> Queue**, which has no timeout. The cheaper thing to check first is whether the replica is being
> restarted mid-session, since that is what makes the unet cold.

#### Superseded designs, and the trap they exposed

Both earlier attempts downloaded via `POST /download` and tried to detect when the file was ready.
Both were wrong, and one would have been harmful, worth recording so it is not re-attempted:

1. **Design 1** mapped URL → catalog filename and pre-checked `GET /models` for that name.
   `GET /models` does **not** list Civitai filenames: it reports **content-addressed hashes**
   (`AC8AL9XQqXifmNOh9Hgf2hwlxqDLvMVX.safetensors`). The name could never match, so every render
   would have skipped the cached fast path *and then polled 40 × 8 s = **320 s** for a file that
   had been there all along*, a regression disguised as a fix.
2. **Design 2** polled for the filename `/download` reports. Without `wait: true` that reply gives
   the **version id** (`2615554`) and `status: "started"` **even for a cached file**, so there was
   nothing to correlate.

The lesson is not "poll better". The contract was **documented at `GET <gateway>/docs/json`**
(request *and* response schemas) the whole time. Reading it beat reasoning about it, twice. It
also showed `POST /download` exists on our image after all: doc 14 marked it absent, but that was
the API **1.10** Flux.1 image, while ours is **`api1.19.2`**.

### 3.3 (superseded) the async warm-up design

> The first version of this section recommended preloading LoRAs into the container's `loras/`
> directory and referencing them **by filename instead of by URL**. **That was wrong**, and the
> user's constraint killed it: the container cannot resolve a bare local filename from a graph,
> and LoRAs must stay downloadable at runtime for arbitrary picks. Superseded by what follows.

Doc 14 recorded `POST /download` as **absent**, but that was the API **1.10** Flux.1 image. Our
Klein image is **`api1.19.2`**, and `GET <gateway>/docs/json` on the live replica returns six
paths: `/download`, `/health`, `/interrupt`, `/models`, `/prompt`, `/ready`. The contract,
verbatim from that OpenAPI document:

> *"Download a model from a URL to the appropriate model directory. By default, the download runs
> **asynchronously and returns immediately with a 202 status**. Set `wait: true` to hold the
> request open until the download completes."*
> Body: `{url, model_type, filename?, wait?, auth?}`, **`model_type` includes `loras`**.

The decisive field is **`wait`**, and the decisive property is that it is *only slow when there
is genuinely something to download*:

1. Collect the graph's Civitai LoRA URLs, `request_json.civitai_lora_urls`.
2. `POST /download {url, model_type: "loras", "wait": true}` for each. With `wait: true` the call
   returns once the file is on disk; a cached LoRA comes back `status: "completed"`,
   `duration: 0.0`, measured at **~1.4 s per LoRA** on the live replica, four LoRAs in 5.7 s.
3. POST the render. No download happens inside it, so it returns well inside the 100 s cap.

The client timeout is **90 s, deliberately below the gateway's 100 s cap**, so we decide the
outcome rather than being cut off mid-request. A 331 MB LoRA on a slow node can still exceed that;
that case logs and renders anyway, exactly the old behaviour, so the change can only help.

Implemented in `generator.warm_loras`, called from `generate_from_payload` immediately after
`wait_gateway_ready`. It **never raises**.

> **⚠ Two traps, both found by testing against the live replica rather than reasoning.**
>
> **1. Without `wait: true`, `status` is useless.** An async `POST /download` returns
> `status: "started"` **even for a file the replica already holds**, and its `filename` is the
> *version id* (`2615554`), while `GET /models` lists **content-addressed hashes**
> (`AC8AL9XQqXifmNOh9Hgf2hwlxqDLvMVX.safetensors`). So there is no name to correlate and no
> status to trust: **nothing to poll for.**
>
> **2. The first two designs were therefore wrong, and one was actively harmful.** Design one
> looked the expected name up in the catalog and pre-checked `GET /models` for it. That name
> could never match, so it would have skipped the cached fast path *and then polled 40 × 8 s =
> **320 s per render** for a file that had been there all along*. Design two polled for the
> `/download` filename, which matched nothing for the same reason. Only design three, read the
> **response contract**, use `wait: true`, and drop polling altogether, is correct.
>
> The lesson is not "poll better". It is that the contract was **documented at
> `GET <gateway>/docs/json`** the whole time, and reading it beat reasoning about it twice.

**Why `before_start` and filenames are still not the answer.** A fixed preload cannot serve
arbitrary LoRAs chosen at runtime, and the container cannot resolve a bare filename from a graph,
so `lora_name` stays a Civitai URL and the four `prompt_*.json` recipes are **untouched**. That
also keeps `test_klein_recipes::test_lora_refs_resolve_in_the_catalog` and the URL assertions in
`test_request_json` green; a filename-based rewrite would have broken five of them.

**Status:** implemented and unit-tested. 8 new tests in `test_generator.py` (21 total there, all
passing), and the full `src/tools` suite is 540 tests with the **same 9 failures / 2 errors as
before the change**, all pre-existing from the dirty regenerated recipe files.

### 3.3 Still unverified: does Salad ship any of these models prebuilt?

The one claim asserting the prebuilt `comfyui-api` images bundle no checkpoints was **refuted
1-2**, and nothing else tested Salad's prebuilt catalogue. **Open gap.** Must be checked against
Salad's recipe registry and the `comfyui-api` tag list before any migration plan assumes a
download step. Candidate base surfaced: **WAI-illustrious SDXL** (blog review + model page).

---

## 4. Auto-QC, the one area where the state of the art moved

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

## 5. The honest state of the decision

The evidence **does not support the migration**, and it does not refute it either. What we have
is a **demolished inference**: I claimed SDXL-family was the mature answer; nobody, including
this pass, has measured it for interlocked two-body anatomy. Meanwhile two hard blockers appeared
that would have hurt the migration anyway. Regional identity masking exists only for Krea 2 and
refuses SDXL adapters, and there is no SDXL camera-control path.

**Recommended order of work:**

1. **Fix the LoRA preload** (§3.2), ours, concrete, fixes a production bug, unblocks the lost
   A/B arms. Do this regardless of the model decision.
2. **A targeted research pass on the four empty requirements**, leading with the two-skeleton
   OpenPose recipe for SDXL 1024, the single highest-value unanswered operational question.
   Also: genital-act correctness, fixer inventory, style pass, and whether Salad ships anything
   prebuilt.
3. **A bounded, seed-controlled A/B** rather than a migration. The literature cannot answer this
   question; only our own plates can. Renders are **usually reproducible but not deterministic**
   (doc 17 §1.1, 5 of 6 repeated renders matched byte-for-byte, one did not), so a fixed-seed
   matrix is cheap to interpret but a single repeated hash is **soft** evidence, not proof. Take
   one SDXL-family base (WAI-illustrious
   or another) plus a couple pose pack, render a fixed-seed matrix, and **rebuild the ground-truth
   label set first**, the existing one contained a mislabelled GOOD plate, so any scoring against
   it is optimistic.

**Caveats to carry:** the source pool for this pass skews weak (several claims rest on Civitai
marketing pages or on a 12-star single-maintainer README; only three rest on peer-reviewed
papers). The window is fast-moving. Krea 2 is ~3 months old and its multi-character tooling
weeks; version specifics here will decay in weeks. And one coupling we still cannot verify:
*"SDXL has hand fixers"* was never actually connected to *"SDXL has correct interlocked
anatomy"*, the fixer inventory was never enumerated in the confirmed set. **That unverified
coupling is the whole migration premise.**
