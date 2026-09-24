# Salad Studio (not Eldermark)

Windows helper for Salad Comfy image gen + preview. Separate from the
game binary `eldermark`. No sim state, no `lifesim_core`.

```
python -m salad_studio
```

Run from the repo root, or:

```
python salad_studio/app.py
```

Layout: **top action bar** (Generate + live generation status every 2s, and the
replica status badges with the Salad probe, right-aligned), **vertical tabs** on
the left (**Config**, **Prompt Settings**, **Policy**, **Tokens**, **LoRAs**,
**Prompt Editor**, **Prompt Assist**, **Prompt Catalog**, **Import**,
**Prompt History**, **Logs**).
Bottom (always visible) = horizontal history strip with a tall button on
the left and right.

- **Config** — the active profile (with **Save profile** / **Delete profile**)
  and the **Gateway URL**. Nothing else: the replica badges and the Salad probe
  live right-aligned in the top action bar, and every prompt knob is on
  **Prompt Settings**. Generate is disabled until the *active* gateway is Ready.
- **Prompt Settings** — **Width**, **Height**, **Steps**, **CFG**, **Seed**,
  **Graph** (Flux.2 Klein / Flux.1 Dev), **Scheduler** (Flux2 / Simple), the
  **Checkpoint** (Base 9B / Distilled 9B) and the **LoRA** checkboxes. These are
  the values the Prompt Editor's JSON is rebuilt from.
- **Policy** — probes, **image tag**, **GPU classes**, **US-only**, and
  **Reallocate** (confirm). Apply PATCHes Salad — not a Docker rebuild.
- **Tokens** — Salad / Hugging Face / Civitai / DeepSeek keys in
  `studio-tokens.json` (gitignored). Empty slots copy from `~/.config`; the
  DeepSeek slot also reads `DEEPSEEK_API_KEY` from the environment when no
  file has one (that value is never copied into the store).
  Generate sends the Salad key as `Salad-Api-Key` and appends Civitai
  `?token=` on LoRA URLs at POST time. Each slot carries a validity dot:
  **green** only when a real provider call accepted the key, **red** when the
  provider rejected it, **grey** when it could not be confirmed. **Check keys**
  re-probes every slot (the page also probes when you open it, and a freshly
  saved key is probed on the spot).
- **Logs** — Salad container log-entries for the active gateway, plus
  Studio/HTTP events (secrets redacted).
- **LoRAs** — known catalog LoRAs plus extras you add from a Civitai
  page / `civitai:id@version`, Hugging Face URL, local `.safetensors`
  path, or a direct download URL.
- **Prompt Editor** — the JSON body POSTed to Salad `/prompt`. The
  node graph is **JointJS in a WebView2 pane** (manhattan wires that
  route around cards; no Graphviz `dot`). WebView2 cache lives in
  `%LOCALAPPDATA%\SaladStudio\WebView2` (not next to `python.exe`).
  **Open in browser** if the embed is blank; **Open as Comfy** is
  LiteGraph (Comfy's engine — spline wires, can cross cards). See
  [`docs/workflow/16-salad-studio-prompt-graph.md`](../docs/workflow/16-salad-studio-prompt-graph.md).
  Selecting LoRAs on Prompt Settings rebuilds the `LoraLoader` chain here. **Rebuild from JSON**
  does the reverse (prompt, size, graph, selected LoRAs). **Validate** runs
  the same `parse_request_json` gate as Generate (plus Civitai-token check).
  Generate sends this JSON; Civitai download URLs get the Tokens-tab Civitai
  key appended so Salad can fetch gated LoRAs. The **Positive prompt** and
  **Negative prompt** boxes live here too — under the JSON/diagram pane,
  above the action buttons, positive on the left and negative on the right. Rebuild/Convert wire `CLIPTextEncode.clip` by
  stack: **Klein-native** LoRAs (Klein / Flux.2 / Artificeal / AgedArt)
  encode *after* the last such `LoraLoader`; **foreign** stacks
  (Illustrious / Anima / SDXL / Pony) keep both CLIP encodes on the base
  **CLIPLoader** (Qwen), not the last `LoraLoader`.
- **Import** — paste Civitai generation data and/or Comfy `nodes`/`links`
  JSON. Convert **routes** on graph presence first (Comfy nodes vs no
  Comfy), then tooling (Draw Things / A1111 metadata). UUID subgraph
  flatten assigns unique link ids and skips muted (mode 4) copies;
  nodes not on the SaveImage path (notes, Fast Groups Bypasser,
  unused inlined loaders) are dropped as orphans. Local LoRA
  filenames are searched on Civitai (including ``_CE_`` trainer names
  and sibling versions on the same model); a miss is omitted from the
  graph so Convert still succeeds. Convert rewrites Salad-missing nodes: ``ReferenceLatent`` is
  dropped (CLIP encode → CFG positive), ``ConditioningZeroOut`` becomes
  an empty CLIP encode, ``full_encoder_small_decoder`` → ``flux2-vae``,
  and ``Color Correct GPU (mtb)`` is bypassed. Civitai
  ``flux-2-klein-9b-fp8mixed`` maps to replica ``flux-2-klein-9b-fp8``.
  KSampler ``control_after_generate`` (`randomize`/`fixed`) is not packed
  as steps. When a Civitai Comfy graph has no ``LoraLoader`` but Resources
  list a LoRA (image 134347427 **MJ Style Distilled 206** / ``2912075``),
  Convert inserts that loader. Local ``LoadImage`` filenames stay in the
  editor; Generate omits them (Salad has no ``img_00069_.png``).
  **Fetch from Civitai** (`/images/{id}`) loads Copy All plus
  Resources-used. Convert **branches on Tools**: Comfy posts use the
  workflow graph as-is (sampler names unchanged); Draw Things posts
  have no Comfy nodes — Convert builds a Klein `/prompt` from prompt +
  LoRAs and maps Draw Things samplers (`DPM++ SDE`, Euler A Trailing)
  to Salad `euler` + `Flux2Scheduler`. A1111-style generation data
  (no Tools) stays on the metadata path: Resources-used LoRA **order**
  (``modelVersionIds`` / page chips) is the chain order; extra
  ``<lora:…>`` names not on the chips are resolved and appended.
  Draw Things / External
  Generator posts often have empty `modelVersionIds` on the public
  images API; Fetch fills LoRAs and the checkpoint from tRPC
  `image.getGenerationData` (Civitai token) or the public image page.
  Example: [135440425](https://civitai.com/images/135440425)
  is **Draw Things** (not Comfy): distilled Klein + **Artificeal** `3088444` at 1344×1792, CFG 1, 5
  steps. Draw Things `DPM++ SDE` is remapped to Comfy **euler** on
  distilled Klein. Klein-native LoRAs encode CLIP **after** the last
  `LoraLoader`; Illustrious/Anima stacks still encode on the CLIPLoader.
  Without the LoRA Salad only draws the graphite sketch layer. That image's
  stored CLIP is only the Artificeal trigger + a stool sentence; Convert
  expands it to the cover scene (overalls, landscape, wordmark) so Fetch
  does not paint abstract washes. Generation data may be prompt + **Negative prompt** + `Steps:` /
  CFG / width / height, A1111 sampler strings (`DPM++ 2S a simple`), and
  `<lora:name:weight>` tags (unknown LoRAs skipped), or **Sampler /
  Seed / Model only** (no `Steps:`). Trailing extra JSON after the
  workflow (`Extra data: line 1 column …`) is ignored. Distilled Klein
  graphs keep CFG **1** and 4 steps; do not leave CFG at 5 unless the
  paste says so. **Graph knobs** empty = from paste; a filled value
  overrides. **Fill knobs from paste** reads CFG/seed/size from the
  workflow; Convert must not be followed by Rebuild from Config.
  **Clear Import** drops both pastes and knobs. Workflow JSON is stashed
  in memory (the box shows a short summary) so a long Civitai graph does
  not freeze Tk; Convert also drops the stash. Distilled Klein graphs
  (`flux-2-klein-9b-fp8`, small decoder VAE, `ReferenceLatent`, local
  LoRA filenames) are **not blocked**: Convert still succeeds, the Import
  **Salad replica issues** pane **notes** them under `Warnings:`, and
  Generate strips or rewires those nodes on the POST copy. Restore a
  CFG 5 / base-9b job from Prompt History instead.
- **Prompt Catalog** — the prompts you keep, each with a **Short name** and a
  **Description**. **Copy from Prompt Editor** stores the editor's request JSON
  under the name in the form (the name is required, and a name already in the
  catalog is refused); **Update JSON** replaces the selected entry's request
  with the editor's; **Save name / description** edits the selected entry's
  labels; **Load into Prompt Editor** (or a double-click) puts an entry back in
  the editor. **Delete** asks first. Stored under
  `~/.config/salad/studio-prompt-catalog.json` (not git), with Civitai tokens
  stripped from the stored LoRA URLs. The table shows Added / Short name /
  Description / Prompt / Graph.
- **Prompt Assist** — asks **DeepSeek** to improve a prompt pair. The top row
  mirrors the Prompt Editor's current **positive** and **negative** prompt
  (read-only, refreshed when you open the page or press **Refresh from Prompt
  Editor**); the second row is a pair of **adjusted** prompts you edit freely —
  they are independent of the editor, and typing in them never touches the
  editor's JSON. Below that, **Image issue / problem** is a free-text box for
  what went wrong with the last image (e.g. *head is missing*): it goes to the
  model as the **highest priority** instruction, so the rewritten prompts target
  that defect and its negative prompt names the failure. Tick **Send the latest
  generated image** to attach the newest plate from `art/salad_studio/` as well,
  so the model can look at the picture and name the defect itself (the label
  shows which file will ride along); the image is downscaled to 1024 px before
  it is sent. Both backends are reasoning models, so a Help press waits for the
  **whole** answer: a reply the API cut off at the token limit
  (`finish_reason: "length"`) is asked for again and stitched on (up to
  `ai_helper.CONTINUE_ATTEMPTS`, the Logs tab saying how many rounds it took),
  a trace that used the whole budget with nothing written is answered by a
  demand for the JSON, and a body that streams despite `stream: false` is
  assembled from its frames. When the budget still runs out, the press fails
  with a message naming max_tokens rather than filling the boxes with the
  front of a reply. The reply is then read as a whole: of every complete
  `{...}` in it the best-scoring one wins — the object that fills both prompts
  and names them outright — so the schema or a first draft a reasoning model
  quotes in its trace is never mistaken for the answer, and the schema's
  `"..."` placeholders read as no answer at all. A model that answers a
  continuation by re-writing the object from the top (Ministral does) is still
  read: the restarted object is recovered from behind the cut-off head. A reply
  that arrives missing one of the two prompts leaves the box you typed in
  untouched and says so in the Logs tab, so a partial answer cannot wipe your
  own wording. **Help (DeepSeek)** sends the editor's positive and negative, both
  adjusted prompts, the issue, the request JSON, the attached plate when ticked,
  and a resolved inventory of the checkpoints / LoRAs / CLIP / VAE the request
  loads; the reply's adjusted positive and negative replace the two boxes, what
  the model saw wrong with the image is reported next to the buttons, and the
  raw reply stays in the pane below. **Help (local)** does the same against an
  OpenAI-compatible server on your machine — LM Studio by default — using the
  URL in **Local LLM URL (LM Studio)** (`http://localhost:1234/v1`; a pasted
  `…/api/v1`, `…/api/v1/chat` or a full `…/v1/chat/completions` is reduced to
  that base). It asks LM Studio's native `/api/v1/models` first to choose the
  model — a **loaded** chat model wins and embedding models are skipped — then
  posts to `/v1/chat/completions`, so no key is needed. The server has to be
  running: in LM Studio open **Developer → Start Server** (loading a model in
  the chat UI does not start it), and the page says so when nothing answers on
  that URL. A reply with no usable prompts leaves the
  boxes alone and shows the model's own words instead. **Commit to Prompts +
  JSON** writes the adjusted pair back: it fills the Prompt Editor's **Positive
  prompt** / **Negative prompt** boxes and patches the `CLIPTextEncode` text in
  the editor JSON (if the JSON cannot take the text — unparseable, or no CLIP
  text encode — the graph is rebuilt from Prompt Settings and the page says so).
  Every referenced weight is resolved locally
  first (catalog, extras, replica disk, filename family) and then online
  (Civitai) if the local sources miss; anything still unknown is reported as
  **UNRESOLVED** to the model rather than dropped. Model id lives in
  `ai_helper.MODEL` (`deepseek-flash`).
- **Prompt History** — stores the full request JSON (prompt column for
  skim, Graph column for node/LoRA/size stats). A successful Generate
  writes a 48×48 thumbnail in the first column. Double-click restores
  JSON + prompt.

Klein group, prefetch image, Civitai-vs-Comfy quality, and startup
probes: [`docs/workflow/15-salad-flux2-klein-group.md`](../docs/workflow/15-salad-flux2-klein-group.md).

Secrets: `salad_studio/studio-tokens.json` (not git; seeded from
`~/.config` if empty). Gateway files stay in `~/.config/salad/`.
Profiles: `~/.config/salad/studio-profiles.json`. User LoRA extras:
`~/.config/salad/studio-loras.json`. Prompt history (full `/prompt` JSON):
`~/.config/salad/studio-prompt-history.json`. Prompt catalog (named request
JSON): `~/.config/salad/studio-prompt-catalog.json`.

## Settings (this repo is standalone; two things live elsewhere)

This folder was moved out of the Eldermark repo, so the paths that used to be
relative walk-ups are environment settings with machine defaults:

| Setting | Default | What it is |
|---|---|---|
| `ELDERMARK_ART` | `C:\Users\vkozy\repos\lifesim-design\art` | the Eldermark art tree this tool writes plates into (`art/salad_studio/`, `art/model-cache/`) |
| `ELDERMARK_REPO` | `C:\Users\vkozy\repos\lifesim-design` | the Eldermark checkout `test_salad_comfy_live_findings.py` reads docs and skills from |
| `SALAD_STUDIO_HOME` | this folder | where `model_catalog.py` stages Klein weights for the Docker build |

Known limitation: the three Eldermark catalog helpers that moved here
(`salad_catalog_faces.py`, `salad_probe_ages.py`, `salad_probe_sdxl.py`) still
import `paperdoll_mask` and `regen_faces`, which stayed in the Eldermark repo,
so they do not run standalone. The Studio package itself and its suite do not
depend on them. `test_salad_comfy_live_findings.py` at the repo root detects this
and asserts the documented failure instead of a false pass; it starts exercising
the real freeze path the moment that gap is closed.

Two test commands, and the second is not part of the first:

```
python -m unittest discover -s salad_studio -p "test_*.py"   # 566 tests, ~3 min
python test_salad_comfy_live_findings.py                     # root structural checks
```

## Container groups

Building the Salad container image, creating a group, and calling either the
control-plane API or a running container are documented in one place:
[`docs/workflow/23-salad-container-group-deployment.md`](../docs/workflow/23-salad-container-group-deployment.md).
`salad_status.py` is the client it describes; the **Policy** tab is the UI over
it (image PATCH, probes, GPU classes, US-only, Reallocate).

