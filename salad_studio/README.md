# Salad Studio (not Eldermark)

Windows helper for SaladCloud ComfyUI image generation and preview, separate
from `eldermark`. Run `python -m salad_studio`: it starts a local server on
127.0.0.1 and opens the page in your browser. The page is Angular, served from
`ui/dist/`; the Python side is the server and the stores.

Every action is one `POST /api/action` naming a page and an action; the reply
carries that page's whole state. The 15 s probe, the 2 s generation tick, log
lines and finished background actions arrive on `GET /api/events` as
server-sent events. The server binds loopback and refuses a request whose
`Origin` is another site.

**Top action bar**: a rose **Generate**, **Clean gallery**, **Check Salad
status**, live status every 2 s, and ready
(green), starting (amber) and not-started (red) container counts in one recessed
panel; a press during a render queues.
**Left tabs**, numbered under a `Pages` label, in order: (**Config**, **Prompt Settings**, **Tokens**, **LoRAs**, **Prompt Editor**, **Prompt Assist**, **Prompt Catalog**, **Import**, **Prompt History**, **Queue**, **Logs**). Each
page opens on a title capsule carrying that same number. **Bottom**: status
line, then the history strip with a tall button each side. The strip's thumb is
ringed after a click there or after the first arrow press; Left and Right walk
the ring, Home and End take its ends, and Enter or a double-click opens the plate.
While the strip holds the keys, the arrows walk the ring. A table's own arrow
keys move through its cells, and a click selects the row.

- **Config**. Sub-tabs in order: **Profile**, **Images**, **Salad group**,
  **Vast.ai**; each scrolls alone. A save writes only the section it sits on.

  **Profile.** **Active profile** lists stored profiles; **Add profile** (name,
  seeds the metadata family list and typed URL), **Save profile**, **Delete
  profile** (the last recreates a default). **Target**: Salad gateway or vast.ai
  instance; URL label `Gateway URL` / `Instance URL`. **Use the selected
  instance** fills the URL from the Vast.ai active row; Generate uses the
  target, and the tab is an instance list, not a second engine switch.
  **Checkpoints this profile serves**: filename or label, **Add**,
  **Remove selected** (which removes the row you picked, not the text you
  typed); a list may span families (the image must carry all), and listing a
  checkpoint routes it.

  **Images.** **Container images** lists deployable images and host needs from
  `routing.families.<family>.deployment` (doc 23 §1.2). **Image** picks one.
  **Environment** shows documented entries (`HF_TOKEN`,
  `CIVITAI_API_TOKEN` from Tokens slots; literals such as
  `STARTUP_CHECK_MAX_TRIES=120`), secrets masked until **show token values**.
  **Add env**, **Remove selected** and **Save environment** edit extras (a
  documented name is overridden) in `~/.config/salad/studio-images.json`.
  **Deploy** shows `docker build` with the build arg (`KLEIN_UNET_SET` sets the
  first-boot download; no baked weights), `docker push`, `docker
  run`, and `vastai create instance` (ports and environment in `--env`; the
  ENTRYPOINT downloads on first boot, so no `--onstart-cmd`), plus the **Salad
  portal fields**. **Copy commands** copies them (secrets as `${NAME}` unless
  **show token values**). The image list is read-only here; a custom tag is a
  store operation, not a page control. See
  [doc 23](../docs/workflow/23-salad-container-group-deployment.md).

  **Salad group.** Per config: **Image**, **GPU classes**, **US-only**, the
  startup and readiness probes, and **Reallocate instance**
  (confirm). **Image** offers
  the two tags and stays editable. **Load from Salad** reads the config's group;
  **Apply to Salad** PATCHes it (not a rebuild); **Save profile** stores the
  fields with the config. Probe fields fill immediately from the stored policy,
  else the metadata's per-family settings, then a scheduled live read replaces
  them. A fresh group value wins; a blank is absent; the read never rewrites a
  stored record; a failed read leaves the fields. One policy per config; saved
  state names the last.

  **Vast.ai.** **Vast.ai instances** lists the instances a profile may render
  on. Type one or several comma-separated addresses, pick **Image**, **Add
  instance**; Label and Image apply to the first only. **Fetch instances**
  reads the account with the stored Bearer key from
  `https://console.vast.ai/api/v1/instances/` and reconciles. A record mapping
  no ComfyUI port (loading, stopped) is still a row, `#<id>` in Address plus
  state. An id-bearing row absent from a complete listing becomes **destroyed**
  (id and image kept); a truncated listing destroys nothing. Selecting a row
  with an endpoint points Generate at it when the target is **Vast.ai
  instance**; no endpoint means it cannot be the target and says why. **Set
  image** records the image; **New profile for instance**
  creates a profile with that target and the image's checkpoint family
  (documented tags only); **Remove**; **Save list** writes
  `~/.config/salad/studio-vast.json`.

  **Rent a machine** searches those offers. **GPU models** defaults to
  `RTX 5090, RTX 4090` in preference order; empty restores those two, not "any
  GPU". Floors: max $/hr, download/upload Mbps, CUDA, reliability, 24 GB VRAM,
  140 GB disk. **Find offers** posts to
  `https://console.vast.ai/api/v0/bundles/`, ordered by `dlperf_per_dphtotal`
  descending; the table re-sorts by images per dollar
  (`dlperf_per_dphtotal`, else `dlperf` / $/hr), then GPU preference, price,
  download, upload. **Create instance** issues one `PUT`; the
  image is the Vast.ai **Image** box or, when empty, the profile's policy image. A mapped endpoint returns a
  live row; a contract with no mapped port appears as **creating**, and Fetch
  promotes it when its port maps, unless another instance is active. A
  vast-mode profile holding a destroyed address is repointed or cleared. The
  create and endpoint wait run on a worker, bounded at about five minutes,
  polling for an endpoint, not `/ready`; press Generate again once reachable.

  The key authenticates the control API only. A render queues on the profile's
  line and POSTs to the instance's `/prompt`. Wrapper **3000** returns base64
  JPEGs in `images[]`; plain ComfyUI **8188** returns a `prompt_id` (poll
  `/history/<id>`, fetch `/view`). **18188**, or the instance's only other
  non-ssh port, is the fallback; **3000** wins when mapped. A `LoraLoader` URL
  on 8188 fails with `value_not_in_list`; see
  [doc 23 §5](../docs/workflow/23-salad-container-group-deployment.md#5-vastai-instances)
  for host choice, CUDA, failures and cost. An accepted POST with no plate is
  reported by name. **Replace if destroyed** rents the
  best-value offer that clears the criteria (RTX 5090 before RTX 4090 on a tie).
- **Prompt Settings**. **Width**, **Height**, **Steps**, **CFG**, **Seed**,
  **Graph** (Flux.2 Klein / Flux.1 Dev), **Scheduler** (Flux2 (Klein) / Simple
  (Civitai)), the **Checkpoint** (Base 9B / Distilled 9B / SNOFS 9B) and the
  **LoRA** checkboxes. **Save to profile** writes the form. The Prompt Editor's
  JSON is rebuilt from these values.
- **Tokens**. Salad, Hugging Face, Civitai, DeepSeek and Vast.ai keys in
  `studio-tokens.json` (gitignored). Empty slots copy from `~/.config`; DeepSeek
  also reads `DEEPSEEK_API_KEY` when no file has one (never copied in). Vast.ai
  has no standard provider file; Studio reads `~/.config/vast/key` when the
  store is empty, and the Config Vast.ai section reads the store. Generate sends
  the Salad key as `Salad-Api-Key` and appends Civitai `?token=` to LoRA URLs at
  POST time. Dots: **green** only on an accepted provider call, **red** on
  rejection, **grey** when unconfirmed, each with its word under the name. The
  **Check** beside a slot asks that provider alone, so one hanging provider does
  not hold up the others; the page probes nothing on open. **Save keys** writes
  the fields, then **Check** confirms the saved key.
- **Logs**. Salad container logs for the active gateway; Studio/HTTP events
  redacted.
- **LoRAs**. Catalog LoRAs plus extras from a Civitai page or
  `civitai:id@version`, a Hugging Face URL, a local `.safetensors` path, or a
  download URL. **Verified** leads the grid: a dot per row, green when verified,
  red when not (the row tag carries the colour). Clicking a **heading** sorts by it, again reverses. **Find by name**
  narrows to names containing the text, any case; **Clear** restores all, and a
  narrowed grid still sorts.
- **Prompt Editor**. The JSON body POSTed to the target's `/prompt`. The graph
  is **drawn from the request** beside it, and the pane is read-only apart from
  selection: two same-class cards can be swapped. Selecting
  LoRAs on Prompt Settings rebuilds the `LoraLoader` chain here; **Rebuild from
  JSON** reverses it. **Validate** runs the same `parse_request_json` gate as
  Generate, and also fails on a missing Civitai token or an unverified weight
  URL. Generate sends this JSON and appends the Tokens-tab Civitai key to
  download URLs. **Positive prompt** and **Negative prompt** live here.
  Rebuild/Convert wire `CLIPTextEncode.clip` by stack:
  **Klein-native** LoRAs (Klein / Flux.2 / Artificeal / AgedArt) encode after the
  last such `LoraLoader`; **foreign** stacks (Illustrious / Anima / SDXL / Pony)
  keep both CLIP encodes on the base **CLIPLoader** (Qwen).
- **Import**. Paste Civitai generation data and Comfy `nodes`/`links` JSON.
  Convert **routes** on graph presence first (Comfy nodes or none), then tooling
  (Draw Things / A1111 metadata). A Comfy paste with **no sampling path** builds
  from the generation data instead; a paste with neither converts as a graph.
  UUID subgraph flatten assigns unique link ids and skips muted (mode 4) copies;
  off-path nodes are dropped as orphans. Local LoRA filenames are searched on
  Civitai (including `_CE_` trainer names and sibling versions); a miss is
  omitted. Convert rewrites Salad-missing nodes: `ReferenceLatent` dropped,
  `ConditioningZeroOut` becomes an empty CLIP encode,
  `full_encoder_small_decoder` becomes `flux2-vae`, `Color Correct GPU (mtb)`
  bypassed. The LoraManager pack becomes a stock `LoraLoader` chain with its own
  widget's stack; its helpers are dropped and their text written onto the
  `CLIPTextEncode` they fed. Generate POSTs a copy with no pack type; a LoRA
  still holding a local filename is omitted there and kept in the editor.
  Civitai `flux-2-klein-9b-fp8mixed` maps to replica `flux-2-klein-9b-fp8`.
  KSampler `control_after_generate` is not packed as steps. A Civitai Comfy
  graph with no `LoraLoader` but a Resource LoRA gets one inserted. Local
  `LoadImage` filenames stay in the editor and are omitted from the POST.
  **Fetch from Civitai** (`/images/{id}`) loads Copy All plus Resources-used.
  Convert branches on Tools: Comfy posts use the graph as-is; Draw Things posts
  build a Klein `/prompt` from prompt and LoRAs and map samplers to `euler` plus
  `Flux2Scheduler`. A1111-style data (no Tools) stays on the metadata path:
  Resources-used LoRA **order** (`modelVersionIds` or chips) is the chain order,
  and extra `<lora:name:weight>` tags are resolved and appended (unknown LoRAs
  skipped). Draw Things and External Generator posts often carry empty
  `modelVersionIds`, so Fetch fills LoRAs and checkpoint from tRPC
  `image.getGenerationData` (Civitai token) or the public image page. Generation
  data may be prompt, **Negative prompt**, `Steps:`, CFG, width and height, with
  A1111 samplers and LoRA tags, or **Sampler / Seed / Model only** (no
  `Steps:`). Distilled Klein graphs keep CFG **1** and 4 steps; CFG 5 only when
  the paste says so. **Graph knobs** empty means from the paste; a filled value
  overrides. **Fill knobs from paste** reads CFG, seed and size; Convert must
  not be followed by Rebuild from Config. **Clear Import** drops both pastes and
  knobs. Workflow JSON is stashed in memory; Convert drops the stash. Distilled
  Klein graphs with `flux-2-klein-9b-fp8`, a small-decoder VAE, `ReferenceLatent`
  or local LoRA filenames are **not blocked**: Convert succeeds, the **Salad
  replica issues** pane notes them under `Warnings:`, and Generate strips or
  rewires them on the POST copy. Restore a CFG 5 or base-9b job from Prompt
  History instead.
- **Prompt Catalog**. Kept prompts, each with **Short name** and
  **Description**. **Copy from Prompt Editor** stores the editor request under
  the form name (required; duplicates refused); **Update JSON** replaces the
  selected entry's request; **Save name / description** edits labels; **Load
  into Prompt Editor** restores it; **Delete** asks first.
  Entries live in `~/.config/salad/studio-prompt-catalog.json` (not git), with
  Civitai tokens stripped from LoRA URLs. The table shows Added, Short name,
  Description, Prompt, Graph, and an empty state.
- **Prompt Assist**. **Help (DeepSeek)** uses the DeepSeek API; **Help (local)**
  an OpenAI-compatible server you run, LM Studio by default. **Image issue /
  problem** is the **highest priority** instruction. **Send the latest generated
  image** attaches the newest plate from `art/salad_studio/`, downscaled to 1024
  px. A reply cut at the token limit (`finish_reason: "length"`) is asked
  for again and stitched on, up to `ai_helper.CONTINUE_ATTEMPTS` (the Logs tab
  reports the rounds). A trace that spent the budget with nothing written is
  answered by a demand for the JSON. A body that streams despite
  `stream: false` is assembled from its frames. A budget that still runs out
  fails the press, naming max_tokens. The reply is read as a whole: the
  best-scoring complete `{...}` wins (it fills both prompts and names them);
  `"..."` is no answer. A continuation that rewrites the object from the top is
  still read; a reply missing one prompt leaves the box untouched and says so in
  the Logs tab. The system prompt is `studio_meta.instruction()` over the
  metadata's `prompt` section. **Help (DeepSeek)** sends the editor's prompts,
  both adjusted prompts, the issue, the request JSON, the attached plate when
  ticked, and a resolved inventory of the checkpoints, LoRAs, CLIP and VAE
  loaded. Its pair replaces the boxes; the raw reply stays below. **Help
  (local)** uses **Local LLM URL (LM Studio)** (`http://localhost:1234/v1`; a
  pasted `…/api/v1`, `…/api/v1/chat` or full `…/v1/chat/completions` reduces to
  that base). It asks `/api/v1/models` first (a **loaded** chat model wins;
  embeddings skipped), then posts to `/v1/chat/completions`, so no key is
  needed. In LM Studio open **Developer → Start Server** (loading a chat model
  does not start it); the page says so when nothing answers. A reply with no
  usable prompts shows the model's own words. **Commit to Prompts + JSON** fills
  the editor's **Positive prompt** and **Negative prompt** boxes and patches the
  `CLIPTextEncode` text; if the JSON cannot take it, is unparseable, or has no
  CLIP text encode, the graph is rebuilt from Prompt Settings and the page says
  so. Every referenced weight resolves locally first (catalog, extras, replica
  disk, filename family), then online (Civitai); still-unknown ones are reported
  as **UNRESOLVED** to the model. The DeepSeek id is `ai_helper.MODEL`
  (`deepseek-flash`); **Help (local)** uses the server-reported model.
- **Prompt History**. One row per request with **When**, **Prompt**, **Graph**,
  **Rating** and **Plate**. A successful Generate writes a 48×48 JPEG and the
  Plate cell shows it at 36×36. **Reuse** restores the JSON and prompt, the
  stars rate the render, and **Delete** asks first. Empty state.
- **Queue**. From `salad_queue`'s records: one row per request with **Profile**,
  **State** (**waiting**, **in progress**, **done**, **failed**, **cancelled**),
  **Attempts**, **Last status**, **Reason**, **Request** (gateway host and POST
  size, never a token) and **Finished**. Rows refresh on
  the 15 s tick and every queue event. **A finished request stays four hours**
  (`salad_queue.FINISHED_RETENTION_S`): the queue
  writes its row (id, profile, state, status, reason, finish time) beside its
  container record in `~/.config/salad/studio-queue.json` and drops it when
  older, so the next request keeps the id numbering and a kept row is never
  overwritten. An unfinished request is never in that record. **Clear finished**
  clears the page and the kept rows. There is **one line per profile**: a
  request waits behind the others for its container and runs beside one for a
  different profile. **Cancel selected** drops a request not yet submitted; an
  accepted request keeps rendering and cannot be cancelled. **Retry selected**
  re-runs a failed request on a worker thread, on its own profile's line; an
  accepted request is never re-POSTed and is not retryable.

  A gone replica and a group the badge says is **stopped** are refused with
  their reason when the press is made, not by greying the button: the Logs line,
  the status line (`Refused: …`) and the dialog carry one sentence, and nothing
  is queued. A press repeating the request at the **head** adds nothing: the app
  digests it, reports the identical request as already queued, and names the row
  (pointing at **Retry selected** or **Clear finished** when it is finished).
  The same request is accepted when it is not the head.

  The queue owns the **lifecycle**, and it never **starts** a container. Before
  a first attempt it reads the group state behind the profile's gateway: a
  running or unknown group is left alone; a group that is **not running** is
  refused with the press's own message (a group that stopped between the badge
  read and the dispatch), never a failed render. `ContainerLifecycle.stop` is
  the only control-plane call. A container that is up but not serving is
  dispatched, and the render waits for `/ready` before the POST. A boot is
  minutes, so the wait covers about ninety minutes, asking every 10 s at first,
  then every 30 s, then every 60 s (`generator.ready_sleep_s`). While no replica
  is ready every answer is the same 503 page, never pasted into a log, and the
  status line says so. A container that never answers fails the request naming
  the profile, the gateway and the last status; only a gone replica and a
  badge-stopped group are refused up front, and the state is read at every
  dispatch. When a profile's last request finishes, the queue **stops** its
  group after `queue.idle_stop_s` idle (3600 seconds, one hour, by default),
  from the 15 s tick. A profile with a request queued or in flight is never
  stopped; a stopped container leaves the idle set. A rejected stop is retried
  only after another full timeout. The containers the app owns are written to
  `~/.config/salad/studio-queue.json`, so a reopen does not forget a container.
  The app stops only containers it may stop, through the record's own
  `started_by_app`; a record that cannot say the app started it is dropped at
  load with a log line and left running, so opening Studio never shuts down a
  container you started by hand. The status probe may only **follow** a
  container the record already owns (`SaladQueue.refresh`); a dispatched request
  claims its container for that session only, and the check runs off the UI
  thread.

Klein group, prefetch image, Civitai-vs-Comfy quality, and startup probes:
[doc 21](../docs/workflow/21-klein-image-handoff.md) and
[doc 23](../docs/workflow/23-salad-container-group-deployment.md); doc 15 is
the 2026-09-21 record.

Stores (none in git): `salad_studio/studio-tokens.json` (seeded from
`~/.config` if empty). `~/.config/salad/` holds gateway files,
`studio-profiles.json`, `studio-loras.json`, `studio-prompt-history.json` with
`studio-prompt-thumbs/`, `studio-prompt-catalog.json`, `studio-images.json`,
`studio-vast.json` (instances and rental criteria; its `mode` is not the engine
switch),
`studio-queue.json` (queue ledger and container ownership),
`studio-metadata.json`.

## Layers

The page is an Angular app in `ui/`, built to `ui/dist/`. The server in `web/`
is the only thing it talks to: `server.py` serves the page and three routes,
`engine.py` turns one request into one reply, `core.py` runs every handler on
one thread, `shell.py` holds the shell state, and `pages/` holds one
controller per page. No module in this package imports a UI toolkit, and
`tests/test_layers.py` is the tripwire if one creeps back.

| Layer | Modules |
|---|---|
| Server | `server.py`, `engine.py`, `core.py`, `actions.py`, `events.py`, `shell.py`, `services.py`, `form.py`, `registry.py`, `app.py`, `controllers.py`, `__main__.py`; one controller per page in `web/pages/` |
| Page | `ui/src/app/` (Angular); `ui/src/styles.css` owns the palette and type tokens |
| Import | `comfy_import.py`, `civitai_verify.py`, `request_json.py`, `graph_model.py` |
| Persistence | `atomic.py`, `tokens.py`, `prompt_history.py`, `prompt_catalog.py`, `lora_store.py`, `profiles.py`, `hostings.py`, `studio_meta.py` |
| Logging | `studio_log.py` |
| Salad communication | `generator.py`, `salad_status.py`, `salad_queue.py`, `salad_gen.py` (repo root) |
| Vast.ai communication | `vast.py` |
| Image deployment | `image_deploy.py` |
| AI communication | `ai_helper.py`, `ref_check.py` |

### Metadata document

| Path | Role |
|---|---|
| `salad_studio/studio-metadata.json` | the shipped default |
| `~/.config/salad/studio-metadata.json` | yours; wins when present and readable |

`studio_meta.py` re-reads when the mtime moves; a broken user document falls
back to the shipped one (`error` names the reason).

- `routing.families`: each unet **family**'s `unets`, `markers`, and `image`
  (policy-image seed and fallback). `startup_probe` / `readiness_probe`: the six
  probe settings. `deployment`: `context`, `base_image`, `build_arg`, `ports`
  (`api` 3000, `comfy` 8188), `env`, `gpu`, `disk_gb`, `vcpu`, `memory_gb`;
  **Container images** renders it. Each profile's `checkpoints` list is the
  routing list: a checkpoint in no profile, or in two, is
  refused with a reason; one spanning two families routes with a warning; an
  unclassified one is its own family.
- `queue.idle_stop_s`: idle seconds before a stop (3600 default); `0`, a
  negative or a word reads as the default.
- `prompt`: `role`, `task`, `rules`, `reply_contract`. Prompt Assist sends what
  is written there; the Klein anatomy rules come from
  [doc 21 §9](../docs/workflow/21-klein-image-handoff.md#9-two-body-prompt-playbook),
  recorded in `provenance`. Edit them here, not in `ai_helper.py`.

## Settings

The three environment settings (`ELDERMARK_ART`, `ELDERMARK_REPO`,
`SALAD_STUDIO_HOME`), their defaults and the Known-limitation paragraph are in
the root [`README.md`](../README.md) (Configuration, Known limitations).

Run the commands separately:

```
python -m unittest discover -s tests -p "test_*.py"    # 1097 tests, ~35 s
python test_salad_comfy_live_findings.py               # root structural checks
cd salad_klein && python -m unittest discover -p "test_*.py"   # 18 tests
```

Run from the repo root; the third command runs in `salad_klein/`.

The page is built once and committed: `cd ui && npx ng build` writes
`ui/dist/ui/browser`, and `tests/test_web_app.py` fails if a page the rail names
does not answer.

## Container groups

Building, creating a group, and calling the control-plane API or a running
container are in
[doc 23](../docs/workflow/23-salad-container-group-deployment.md).
`salad_status.py` is its client.

## Prompt graph pane: drawn from the model

`graph_model.py` lays the request out as data: one column per class, cards sized
to their rows, a right-angled wire from each output port to its input port. The
editor controller returns that model in the page state and
`ui/src/app/pages/editor/graph.ts` draws it. A drag moves a card on the page and
sends the final position, so the request JSON is never rewritten by a gesture.
Tests: `test_graph_model.py`.
[Decision record](../docs/history/65-salad-studio-prompt-graph-decision-2026-10-17.md).
