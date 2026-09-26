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

Layout: **top action bar** (Generate + live generation status every 2s, and a
compact container strip with the Salad probe, right-aligned: a green dot with
the number of ready containers, an amber dot with the number still starting and
a red dot with the number not started, separated by `|`; a press made while a
render is in flight is queued, not dropped), **vertical tabs** on the left
(**Config**, **Prompt Settings**, **Tokens**, **LoRAs**,
**Prompt Editor**, **Prompt Assist**, **Prompt Catalog**, **Import**,
**Prompt History**, **Queue**, **Logs**).
Bottom (always visible) = horizontal history strip with a tall button on
the left and right.

- **Config**. The profiles this app can render on, and what each one serves.
  The **Active profile** box lists every profile the store holds; type a name and
  press **Add profile** to create one (it is seeded from the metadata document's
  family list and starts with the typed **Gateway URL**), **Save profile** writes
  the selected one back, and **Delete profile** removes it (removing the last one
  recreates a default, so the app stays usable). Below that, **Checkpoints this
  profile serves** is the list routing reads: type a checkpoint filename or pick a
  label, press **Add**, and select a row and press **Remove selected**. A profile's
  list must stay in one unet family — one container holds one unet in VRAM, so
  adding a checkpoint of another family is refused with the reason — and adding a
  checkpoint makes a graph that loads it routable with no code edit. Every profile
  is probed, and the three counts in the action bar's strip are sums over all of
  them: ready instances, instances that exist but are not serving yet, and the
  configured replica count minus the instances that exist. The prompt knobs live on
  **Prompt Settings**.

  The same page owns each config's **Salad policy**: the group's **image tag**,
  **GPU classes**, **US-only** country codes, the startup and readiness probe
  fields, and **Reallocate** (confirm). The policy belongs to the selected
  config — **Load from Salad** reads that config's group, **Apply to Salad**
  PATCHes that config's group (Salad, not a Docker rebuild), and **Save
  profile** stores the fields with that config, so selecting another config
  swaps them for that config's own policy. **Selecting a config re-reads its
  group**, the same fresh GET the button makes, so the fields show that group's
  current image, GPU classes, country codes and probes instead of whatever the
  last config left behind; the read fills the fields only and never rewrites a
  stored record, and a read that fails (no key, no network, no matching group)
  leaves what is on screen standing. Every field follows that order — the image
  and all twelve probe fields — so the page shows a complete policy the moment
  the window opens: the config's own stored policy where it has a value, the
  metadata document's documented settings for its family where it does not
  (its per-family `image`, `startup_probe` and `readiness_probe`), and a fresh
  read of that config's group where the group answers. A live group's value wins
  over the document's, and a blank or whitespace-only value counts as absent, so
  a field saved empty cannot hide the one behind it. The window's saved state
  names the config it was last on, and that config's policy and checkpoints are
  what the page shows even when the store's active config is a different one.
  There is one policy per config; no window-wide copy is kept.
- **Prompt Settings**. **Width**, **Height**, **Steps**, **CFG**, **Seed**,
  **Graph** (Flux.2 Klein / Flux.1 Dev), **Scheduler** (Flux2 / Simple), the
  **Checkpoint** (Base 9B / Distilled 9B) and the **LoRA** checkboxes. These are
  the values the Prompt Editor's JSON is rebuilt from.
- **Tokens**. Salad / Hugging Face / Civitai / DeepSeek keys in
  `studio-tokens.json` (gitignored). Empty slots copy from `~/.config`; the
  DeepSeek slot also reads `DEEPSEEK_API_KEY` from the environment when no
  file has one (that value is never copied into the store).
  Generate sends the Salad key as `Salad-Api-Key` and appends Civitai
  `?token=` on LoRA URLs at POST time. Each slot carries a validity dot:
  **green** only when a real provider call accepted the key, **red** when the
  provider rejected it, **grey** when it could not be confirmed. **Check keys**
  re-probes every slot (the page also probes when you open it, and a freshly
  saved key is probed on the spot).
- **Logs**. Salad container log-entries for the active gateway, plus
  Studio/HTTP events (secrets redacted).
- **LoRAs**. Known catalog LoRAs plus extras you add from a Civitai
  page / `civitai:id@version`, Hugging Face URL, local `.safetensors`
  path, or a direct download URL. The grid leads with **Verified**: a dot per
  row, green when the row is verified and red when it is not (the row's own tag
  carries the colour, since a `Treeview` colours a row and not a cell). Clicking
  a **heading** orders the grid by that column and clicking it again reverses the
  order, and **Find by name** narrows it to the rows whose name contains what you
  type — any part of the name, any case; **Clear** brings every row back, and a
  narrowed grid still sorts.
- **Prompt Editor**. The JSON body POSTed to Salad `/prompt`. The
  node graph is **JointJS in a WebView2 pane** (manhattan wires that
  route around cards; no Graphviz `dot`). WebView2 cache lives in
  `%LOCALAPPDATA%\SaladStudio\WebView2` (not next to `python.exe`).
  **Open in browser** if the embed is blank; **Open as Comfy** is
  LiteGraph (Comfy's engine, spline wires, can cross cards). See
  [`docs/workflow/16-salad-studio-prompt-graph.md`](../docs/workflow/16-salad-studio-prompt-graph.md).
  Selecting LoRAs on Prompt Settings rebuilds the `LoraLoader` chain here. **Rebuild from JSON**
  does the reverse (prompt, size, graph, selected LoRAs). **Validate** runs
  the same `parse_request_json` gate as Generate (plus Civitai-token check).
  Generate sends this JSON; Civitai download URLs get the Tokens-tab Civitai
  key appended so Salad can fetch gated LoRAs. The **Positive prompt** and
  **Negative prompt** boxes live here too, under the JSON/diagram pane,
  above the action buttons, positive on the left and negative on the right. Rebuild/Convert wire `CLIPTextEncode.clip` by
  stack: **Klein-native** LoRAs (Klein / Flux.2 / Artificeal / AgedArt)
  encode *after* the last such `LoraLoader`; **foreign** stacks
  (Illustrious / Anima / SDXL / Pony) keep both CLIP encodes on the base
  **CLIPLoader** (Qwen), not the last `LoraLoader`.
- **Import**. Paste Civitai generation data and/or Comfy `nodes`/`links`
  JSON. Convert **routes** on graph presence first (Comfy nodes vs no
  Comfy), then tooling (Draw Things / A1111 metadata). A Comfy paste whose
  graph has **no sampling path** — no sampler, no diffusion-model loader, no
  text encode, so an image-processing pass such as the SeedVR2 upscale
  workflow image 125073040 carries — is built from the generation data
  instead of being converted as a graph, because that graph cannot become a
  request; a paste with neither still converts as a graph. UUID subgraph
  flatten assigns unique link ids and skips muted (mode 4) copies;
  nodes not on the SaveImage path (notes, Fast Groups Bypasser,
  unused inlined loaders) are dropped as orphans. Local LoRA
  filenames are searched on Civitai (including ``_CE_`` trainer names
  and sibling versions on the same model); a miss is omitted from the
  graph so Convert still succeeds. Convert rewrites Salad-missing nodes:
  ``ReferenceLatent`` is dropped (CLIP encode → CFG positive),
  ``ConditioningZeroOut`` becomes
  an empty CLIP encode, ``full_encoder_small_decoder`` → ``flux2-vae``,
  and ``Color Correct GPU (mtb)`` is bypassed. The LoraManager pack
  (image 123550044) is rewritten the same way: its ``Lora Loader
  (LoraManager)`` becomes a stock ``LoraLoader`` chain carrying the stack from
  its own widget (name and strength per entry), its prompt / trigger-word /
  debug helpers are dropped, and the prompt text they fed is written onto the
  ``CLIPTextEncode`` they pointed at, from the generation data. Generate POSTs a
  copy with no pack type in it; a LoRA still holding a local filename after the
  Civitai lookup is omitted from that copy (the container loads LoRAs from
  Civitai URLs only) and the editor keeps it. Civitai
  ``flux-2-klein-9b-fp8mixed`` maps to replica ``flux-2-klein-9b-fp8``.
  KSampler ``control_after_generate`` (`randomize`/`fixed`) is not packed
  as steps. When a Civitai Comfy graph has no ``LoraLoader`` but Resources
  list a LoRA (image 134347427 **MJ Style Distilled 206** / ``2912075``),
  Convert inserts that loader. Local ``LoadImage`` filenames stay in the
  editor; Generate omits them (Salad has no ``img_00069_.png``).
  **Fetch from Civitai** (`/images/{id}`) loads Copy All plus
  Resources-used. Convert **branches on Tools**: Comfy posts use the
  workflow graph as-is (sampler names unchanged); Draw Things posts
  have no Comfy nodes. Convert builds a Klein `/prompt` from prompt +
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
- **Prompt Catalog**. The prompts you keep, each with a **Short name** and a
  **Description**. **Copy from Prompt Editor** stores the editor's request JSON
  under the name in the form (the name is required, and a name already in the
  catalog is refused); **Update JSON** replaces the selected entry's request
  with the editor's; **Save name / description** edits the selected entry's
  labels; **Load into Prompt Editor** (or a double-click) puts an entry back in
  the editor. **Delete** asks first. Stored under
  `~/.config/salad/studio-prompt-catalog.json` (not git), with Civitai tokens
  stripped from the stored LoRA URLs. The table shows Added / Short name /
  Description / Prompt / Graph.
- **Prompt Assist**. Asks **DeepSeek** to improve a prompt pair. The top row
  mirrors the Prompt Editor's current **positive** and **negative** prompt
  (read-only, refreshed when you open the page or press **Refresh from Prompt
  Editor**); the second row is a pair of **adjusted** prompts you edit freely.
  They are independent of the editor, and typing in them never touches the
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
  `{...}` in it the best-scoring one wins. The object that fills both prompts
  and names them outright, so the schema or a first draft a reasoning model
  quotes in its trace is never mistaken for the answer, and the schema's
  `"..."` placeholders read as no answer at all. A model that answers a
  continuation by re-writing the object from the top (Ministral does) is still
  read: the restarted object is recovered from behind the cut-off head. A reply
  that arrives missing one of the two prompts leaves the box you typed in
  untouched and says so in the Logs tab, so a partial answer cannot wipe your
  own wording. The system prompt is `studio_meta.instruction()` over the
  metadata document's `prompt` section (`role`, `task`, `rules` and the
  `reply_contract`), so the house's Klein anatomy rules live in that document.
  The wording came from
  [`docs/workflow/19-two-body-prompt-playbook.md`](../docs/workflow/19-two-body-prompt-playbook.md):
  state the act directly, name the position in the model's own vocabulary,
  give each body its own limb posture, clinical anatomical words, a short
  style-only negative, the style block verbatim with no placeholder token, and
  no defect enumeration or limb counts. **Help (DeepSeek)** sends the editor's
  positive and negative, both adjusted prompts, the issue, the request JSON,
  the attached plate when ticked, and a resolved inventory of the checkpoints /
  LoRAs / CLIP / VAE the request
  loads; the reply's adjusted positive and negative replace the two boxes, what
  the model saw wrong with the image is reported next to the buttons, and the
  raw reply stays in the pane below. **Help (local)** does the same against an
  OpenAI-compatible server on your machine, LM Studio by default, using the
  URL in **Local LLM URL (LM Studio)** (`http://localhost:1234/v1`; a pasted
  `…/api/v1`, `…/api/v1/chat` or a full `…/v1/chat/completions` is reduced to
  that base). It asks LM Studio's native `/api/v1/models` first to choose the
  model, a **loaded** chat model wins and embedding models are skipped, then
  posts to `/v1/chat/completions`, so no key is needed. The server has to be
  running: in LM Studio open **Developer → Start Server** (loading a model in
  the chat UI does not start it), and the page says so when nothing answers on
  that URL. A reply with no usable prompts leaves the
  boxes alone and shows the model's own words instead. **Commit to Prompts +
  JSON** writes the adjusted pair back: it fills the Prompt Editor's **Positive
  prompt** / **Negative prompt** boxes and patches the `CLIPTextEncode` text in
  the editor JSON (if the JSON cannot take the text, unparseable, or no CLIP
  text encode, the graph is rebuilt from Prompt Settings and the page says so).
  Every referenced weight is resolved locally
  first (catalog, extras, replica disk, filename family) and then online
  (Civitai) if the local sources miss; anything still unknown is reported as
  **UNRESOLVED** to the model rather than dropped. Model id lives in
  `ai_helper.MODEL` (`deepseek-flash`).
- **Prompt History**. Stores the full request JSON (prompt column for
  skim, Graph column for node/LoRA/size stats). A successful Generate
  writes a 48×48 thumbnail in the first column. Double-click restores
  JSON + prompt.
- **Queue**. The Salad request queue, rendered from `salad_queue`'s own
  records: one row per request with its **Profile** (the container profile it is
  dispatched to), **State** — the human word for the request's stage: **waiting**
  (queued, not submitted yet), **in progress** (submitted and running), **done**,
  **failed**, **cancelled** — **Attempts**, **Last status**, **Reason**,
  **Request** (gateway host and POST size, never a token) and **Finished** (the
  time it finished), plus a summary of the states and an explicit empty
  state when nothing is queued. The rows refresh on the existing 15 s tick and on
  every queue event, so a render in flight and its recorded outcome both show up
  without a manual refresh, and the word on a row changes as the request moves.
  **A finished request stays on the page for four hours**
  (`salad_queue.FINISHED_RETENTION_S`), including after the window is closed and
  reopened: the queue writes a finished request's row (id, profile, state,
  status, reason and finish time) beside its container record in
  `~/.config/salad/studio-queue.json` and drops it once it is older than that
  window, so the next request keeps the id numbering and a kept row is never
  overwritten. A request that has not finished is never in that record, so the
  window can never drop one; **Clear finished** clears the page and the kept
  rows together. There is **one line per profile**: a request waits
  behind the other requests for *its* container, and runs beside a request for a
  different profile, because one container runs one Comfy instance. **Cancel
  selected** drops a request that has **not been submitted yet** (a request the
  container has already accepted keeps rendering, and a job that has been sent
  once cannot be cancelled); **Retry selected** re-runs a failed request on a
  worker thread, on its own profile's line, so the window stays live while it
  retries; a request the container already accepted is never re-POSTed, so it is
  not retryable; **Clear finished** drops the terminal rows.

  **Generate is never disabled by the queue or by the status word**: a request
  already queued or in flight, a stopped container and a booting replica all
  leave the button live, and the press queues behind the first request instead of
  being blocked. The press is the gate — a replica that is gone is refused with
  its reason when the press is made, not by greying the button out. A press that
  repeats the request at the **head** of the queue adds nothing: the app digests
  the request it is about to submit and, when the queue's first item carries the
  same digest, it reports that the identical request is already queued (naming
  that row, and pointing at **Retry selected** or **Clear finished** when that
  row is finished). The identical request is still accepted when it is not the
  head, so a second copy can be queued behind a different request.

  The queue also owns the containers' **lifecycle**, so nothing has to be started
  or stopped by hand. Before a request's first attempt, the queue asks Salad to
  **start** the group behind that profile's gateway when the group is stopped
  (`POST …/containers/{name}/start`): a container that is already running is
  left alone, an unknown state is left alone rather than guessed at, and a start
  Salad rejects fails that request with the control plane's own reason instead
  of hanging. One request asks at most once — the generator asks before its own
  readiness wait, and the dispatch that follows does not ask again.
  The start uses the Salad token the app already stores. **Generate is not
  refused for a stopped group**: the request is dispatched, the queue starts the
  container it routes to, and the render waits for that container's `/ready`
  before it POSTs — a cold start is minutes (allocate, pull, boot Comfy, finish
  the prefetch; a replica has been seen still prefetching ten minutes in, and a
  spawn has been seen to run past an hour), so the wait covers about ninety
  minutes, asking every 10 s at first, then every 30 s, then every 60 s
  (`generator.ready_sleep_s`). That is 118 requests for the whole window, where a
  flat 10 s wait would be 540 — while the container has no ready replica every
  answer is the same 503 page, and the status line says so in one line: the
  gateway's HTML error page is never pasted into a log. A container
  that never answers fails the request naming the profile, the gateway and the
  last status it saw. Only a replica that is *gone* — failed, or an origin that
  does not answer — is refused up front, because no start can fix it. The state
  is read again at every dispatch, so a container stopped since the last render
  (the idle stop, the Salad console, a crash) is started for the next request.
  When a profile's last request has finished, the queue **stops** its group once
  it has been idle for the `queue.idle_stop_s` timeout in the metadata document
  (3600 seconds, one hour, by default), from the app's existing 15 s tick: a
  profile with a request queued or in flight is never stopped, a stopped
  container leaves the idle set so a second check cannot stop it twice, and a
  stop Salad rejects is retried only after another full timeout. The record of which containers the app owns
  and when each last had work is written to `~/.config/salad/studio-queue.json`,
  so **closing and reopening Studio does not forget a container**: the idle hour
  still arrives, and the first tick past it asks for the stop. **The app stops
  only containers it asked Salad to start.** Salad does not report who started a
  container, so the record carries that fact itself (`started_by_app`): it is
  written where the app asks for a start, and it is what a later session reads to
  decide whether the stop is its to make. A record that cannot say so — one
  written before this field existed, or one that says the app did not start that
  container — is dropped at load with a line in the log, and its container is
  left running, so **opening Studio never shuts down a container you started by
  hand**. The status probe may only *follow* a container the record already owns
  (`SaladQueue.refresh`), never claim one: finding a group running is not
  evidence that this app started it. A request the app dispatches claims its
  container for that session only (the app has used it, so it may stop it once it
  idles), and a container the app started stays the app's to stop across
  restarts. A request that runs through the queue claims its container whatever
  the group-state read said, and a container with a request queued or in flight
  is never stopped. The check runs off the
  Tk thread, so the window never freezes while the control plane is called.

Klein group, prefetch image, Civitai-vs-Comfy quality, and startup
probes: [`docs/workflow/15-salad-flux2-klein-group.md`](../docs/workflow/15-salad-flux2-klein-group.md).

Secrets: `salad_studio/studio-tokens.json` (not git; seeded from
`~/.config` if empty). Gateway files stay in `~/.config/salad/`.
Profiles: `~/.config/salad/studio-profiles.json`. User LoRA extras:
`~/.config/salad/studio-loras.json`. Prompt history (full `/prompt` JSON):
`~/.config/salad/studio-prompt-history.json`. Prompt catalog (named request
JSON): `~/.config/salad/studio-prompt-catalog.json`.

## Layers

Six layers, one seam. `app.py` owns the window, the tab wiring and the thread
starts; every module outside the UI layer imports and runs in a process where
`tkinter` is never loaded. `test_layers.py` drives one real call per non-UI
layer in a subprocess and asserts exactly that, and a second test keeps the
window in `app.py`.

| Layer | Modules | What a caller gets |
|---|---|---|
| UI | `app.py`, `__main__.py`, `graph_view.py`, `theme.py`, `ui_state.py`, `history_strip.py`, `json_highlight.py` | the window, the tabs, the prompt graph pane |
| Import | `comfy_import.py`, `civitai_verify.py`, `request_json.py` | a Comfy graph built from a Civitai page, a Comfy workflow, or the prompt knobs |
| Persistence | `tokens.py`, `prompt_history.py`, `prompt_catalog.py`, `lora_store.py`, `profiles.py`, `studio_meta.py` | stored tokens, prompts, configurations, LoRAs, model info and the metadata document |
| Logging | `studio_log.py` | formatted redacted log lines, and an explanation for an HTTP failure |
| Salad communication | `generator.py`, `salad_status.py`, `salad_queue.py`, `salad_gen.py` (repo root) | a routed, queued render request, the plate it wrote, and the container lifecycle (start on demand, stop when idle) |
| AI communication | `ai_helper.py`, `ref_check.py` | the Prompt Assist request and its parsed reply |

`app.py` keeps the widgets and the wiring and nothing else that belongs to a
layer: the routing decision is `profiles.plan_route`, the POST is
`generator.generate_from_payload` driven through `salad_queue`, and the Prompt
Assist instruction is assembled from the metadata document.

**Queue.** One container runs one Comfy instance, so `salad_queue` holds
requests in order: pressing **Generate** while a render is in flight queues the
request instead of dropping it, and it starts when the container is free. The
queue retries only when the container is *not available yet* (502, 503, 520,
521, 522, 523, or a transport that never answered), and treats 504/524 as
terminal, because Cloudflare returns those after giving up on a job the
container may still be running and a re-POST renders the plate twice. A request
the container has already accepted is never POSTed again.

### Metadata document

The routing table and the AI layer's instruction are data, not code:

| Path | Role |
|---|---|
| `salad_studio/studio-metadata.json` | the shipped default |
| `~/.config/salad/studio-metadata.json` | yours; it wins when it is present and readable |

`studio_meta.py` loads it, re-reading when the file's mtime moves, so an edit
takes effect with no code change and no restart. A hand-edited or half-written
file cannot abort startup: a broken user document falls back to the shipped one
and the reason is carried in the document's `error` field.

- `routing.families` says what a unet **family** is: the `unets` that belong to
  it (the seed list a new profile starts from and the exact names the family
  check matches), the `markers` that catch a variant, and the `image` that group
  runs. That image is the source a config's policy image is seeded from, and the
  fallback when neither its own stored policy nor its live group names one, so
  editing it here changes what a new config starts with. `startup_probe` and
  `readiness_probe` document the six settings each probe runs
  (`path`, `port`, `initial_delay_seconds`, `period_seconds`, `timeout_seconds`,
  `failure_threshold`): they are what a new config's policy starts from and what
  the Config page falls back to, so the page shows a full set of probe fields the
  moment the window opens instead of waiting for a read. **Which profile serves
  which checkpoint is not here**: it
  is each profile's own `checkpoints` list, edited on the **Config** page, and
  routing sends a graph to the profile that lists the checkpoint it loads. A
  checkpoint in no profile's list is refused with a stated reason instead of
  being sent to a container that cannot serve it, and so is one two profiles
  list (the choice would be a coin toss) and a profile whose list spans two
  families (one container holds one unet family in VRAM). A checkpoint the
  document does not classify is its own family, so a checkpoint that does not
  exist yet needs no document edit.
- `queue.idle_stop_s` is how long a container may sit idle before the queue stops
  it, in seconds (one hour by default). A hand-edited `0`, a negative number or a
  word reads as the default, so a typo cannot stop a container the moment it goes
  quiet.
- `prompt` holds the AI layer's instruction: `role`, `task`, `rules` and
  `reply_contract`. Prompt Assist sends what is written there, so the house
  Klein rules in [`docs/workflow/19-two-body-prompt-playbook.md`](../docs/workflow/19-two-body-prompt-playbook.md)
  are edited in the document, not in `ai_helper.py`.

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
python -m unittest discover -s salad_studio -p "test_*.py"   # 830 tests, ~6 min
python test_salad_comfy_live_findings.py                     # root structural checks
```

## Container groups

Building the Salad container image, creating a group, and calling either the
control-plane API or a running container are documented in one place:
[`docs/workflow/23-salad-container-group-deployment.md`](../docs/workflow/23-salad-container-group-deployment.md).
`salad_status.py` is the client it describes; the Config page's policy section
is the UI over it (image PATCH, probes, GPU classes, US-only, Reallocate), one
policy per config.

