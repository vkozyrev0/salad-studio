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

- **Config**. The deployment page, in four sub-tabs in the order a deployment
  runs them: **Profile**, **Images**, **Salad group**, **Vast.ai**. Each sub-tab
  scrolls on its own when its content is taller than the window.

  **Profile**. The **Active profile** box lists every profile the store holds: type a name and press **Add profile** to create one (seeded
  from the metadata document's family list, starting with the typed URL), **Save profile** writes the selected one
  back, and **Delete profile** removes it (removing the last one recreates a default, so the app stays usable). A profile names
  its **Target** — a Salad gateway or a vast.ai instance — and the URL field's label follows that target (`Gateway URL` or
  `Instance URL`); the list is a table a new hosting joins. **Use the selected instance** fills the URL from the Vast.ai
  sub-tab's active row when the target has one to pick from. The active profile's target is what **Generate** uses; the
  Vast.ai sub-tab is the instance list, not a second engine switch. **Checkpoints
  this profile serves** is the list routing reads: type a checkpoint filename or pick a label, press **Add**, and select a row
  and press **Remove selected**. A profile's list may span more than one unet family; the page adds it and warns that the
  image must carry every family, since one image can serve a mixed list only when it does. A checkpoint in the list makes a
  graph that loads it routable with no code edit. Every profile is probed, and the
  action bar's three counts (ready, up-but-not-serving, configured minus existing) are sums over all of them. The prompt knobs
  live on **Prompt Settings**.

  **Images**. **Container images**: the images this app deploys and what a host needs for
  each, read from the metadata document's `routing.families.<family>.deployment` — the fields are
  doc 23 §1.2's. The **Image** picker selects one (the two built images, plus any you add); the
  **Environment** tree shows the documented entries (`HF_TOKEN` and `CIVITAI_API_TOKEN` from their
  Tokens-tab slots, plus literals such as `STARTUP_CHECK_MAX_TRIES=120`), a secret's value masked
  until **show token values** is ticked, and **Add env** / **Remove selected** / **Save
  environment** editing your own extra entries (a row for a documented name overrides its value),
  kept in `~/.config/salad/studio-images.json`. **Deploy** shows that image's commands —
  `docker build` with the build arg, `docker push`, a `docker run`, and the `vastai create instance`
  line whose `--env` carries the ports and the environment (the image's own ENTRYPOINT does the
  first-boot download, so no `--onstart-cmd` is needed) — plus the **Salad portal fields** to create
  a group with; **Copy commands** puts what is shown on the clipboard, a secret staying a `${NAME}`
  placeholder unless **show token values** is ticked. **Your own image** adds a tag of your own
  (name, tag, build arg, context, and the two ports it publishes), and removing it takes its extra
  environment with it. This section is the app's half of
  [`docs/workflow/23-salad-container-group-deployment.md`](../docs/workflow/23-salad-container-group-deployment.md).

  **Salad group**. Each config's **Salad policy**: the group's **Image**,
  **GPU classes**, **US-only** country codes, the startup and readiness probe
  fields, and **Reallocate** (confirm). The **Image** field offers the tags
  of the two images on **Images** (still editable, so a group running a tag this app has
  never been told about is fine). The two images built from `salad_klein/`, their
  build args, ports, and entrypoint are in
  [`docs/workflow/23-salad-container-group-deployment.md`](../docs/workflow/23-salad-container-group-deployment.md)
  §1.2. Either one also runs as a vast.ai instance image (see **Vast.ai**). The policy belongs to the selected
  config: **Load from Salad** reads that config's group, **Apply to Salad**
  PATCHes that config's group (Salad, not a Docker rebuild), and **Save
  profile** stores the fields with that config, so selecting another config swaps them for that config's own policy.
  The page fills all twelve probe fields in this order: a fresh read of the
  selected config's group where it has a value, else the config's stored policy,
  else the metadata document's per-family settings. A blank or whitespace-only
  value counts as absent, so a field saved empty cannot hide the one behind it.
  Selecting a config re-reads its group with the same GET the button uses. The
  read fills the fields only and never rewrites a stored record; a failed read
  leaves the fields standing. There is one policy per config, and the saved
  state names the config the window was last on.

  **Vast.ai**. **Vast.ai instances**: the vast.ai instances a profile may render on. Type one
  address (`http://1.2.3.4:31234`, or several comma-separated), pick the **Image** the instance
  runs, and press **Add instance**. **Fetch instances from Vast.ai** reads the account with the
  stored Bearer key from `https://console.vast.ai/api/v1/instances/` and reconciles the list. A
  record that maps no ComfyUI port (loading, stopped) is still a row, with `#<id>` in Address and
  its state. An id-bearing row the account no longer lists becomes **destroyed**, keeps its id and
  image, and loses its address. A truncated listing marks nothing destroyed. Selecting a row with an
  endpoint points Generate at it; a row with no endpoint cannot be the target and says why. **Set
  image for selected** records the image, **New profile for this instance** creates a profile with
  that target and the image's checkpoint family, **Remove selected** drops one, and **Save list**
  writes to `~/.config/salad/studio-vast.json`. Nothing about the account lands in the repo.

  **Rent a machine** searches the same offer list. **GPU models** defaults to `RTX 5090, RTX 4090`
  in preference order. An empty box restores those two, not "any GPU", because the measured
  unfiltered search's cheapest 24 GB offer is a Tesla P40 at $0.108/hr. The floors are max $/hr,
  download and upload Mbps, CUDA, and reliability. **Find offers** posts to
  `https://console.vast.ai/api/v0/bundles/` ordered by `dlperf_per_dphtotal` descending. The table
  re-sorts by images per dollar (`dlperf` divided by $/hr), then GPU preference, then price. Select
  a row and press **Create instance on selected offer** for one `PUT` to that ask. The contract
  appears immediately as a **creating** row; Fetch promotes it to the active target when its
  ComfyUI port maps. No separate pending slot exists. A vast-mode profile that held a destroyed
  instance's address is repointed at the new active endpoint or cleared, so Generate refuses rather
  than POSTing to a dead host.

  The key authenticates the vast.ai control API only and is never sent to an instance. A render is
  queued on the profile's line and POSTs to the instance's `/prompt`, so the plate lands in the
  gallery and prompt history. Both answers are handled. The Salad wrapper on port **3000** returns
  base64 JPEGs in `images[]`; a plain ComfyUI on **8188** returns a `prompt_id`, so the app polls
  `/history/<id>` and fetches the plate from `/view`. The wrapper resolves Civitai LoRA URLs, so the
  app prefers its **3000** whenever the instance maps it and falls back to 8188. A `LoraLoader` URL
  on 8188 fails with `value_not_in_list`. An accepted POST with no plate is reported by name, not
  retried. See [the deployment guide](../docs/workflow/23-salad-container-group-deployment.md#5-vastai-instances)
  for host choice, CUDA and driver requirements, and each failure. The plate's extension follows
  its bytes (`studio_<ms>.jpg` from a wrapper, PNG from native ComfyUI), and the gallery, history
  strip, and **Clean gallery** read both. When the selected instance is gone, **If the selected
  instance is destroyed** rents the best-value offer that clears the criteria, RTX 5090 before RTX
  4090 on a tie. The create and endpoint wait run off the Tk thread. Generate again when the new
  instance is ready.
- **Prompt Settings**. **Width**, **Height**, **Steps**, **CFG**, **Seed**,
  **Graph** (Flux.2 Klein / Flux.1 Dev), **Scheduler** (Flux2 (Klein) / Simple
  (Civitai)), the **Checkpoint** (Base 9B / Distilled 9B / SNOFS 9B) and the
  **LoRA** checkboxes. These are
  the values the Prompt Editor's JSON is rebuilt from.
- **Tokens**. Salad / Hugging Face / Civitai / DeepSeek / Vast.ai keys in
  `studio-tokens.json` (gitignored). Empty slots copy from `~/.config`; the
  DeepSeek slot also reads `DEEPSEEK_API_KEY` from the environment when no
  file has one (that value is never copied into the store). Vast.ai has no
  provider file convention, so the store is its only home: the **Config** page's
  Vast.ai instances section reads it from there.
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
  [the prompt graph pane](#prompt-graph-pane-jointjs-in-webview2).
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
  steps. Draw Things `DPM++ SDE` is remapped to Comfy **euler** on distilled Klein, and the CLIP-encode
  stack rule is the Prompt Editor's, above. Without the LoRA Salad only draws the graphite sketch layer. That image's
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
  Description / Prompt / Graph, and an explicit empty state when nothing is kept.
- **Prompt Assist**. Asks a model to improve a prompt pair: **Help (DeepSeek)**
  uses the DeepSeek API (the key lives on the Tokens tab) and **Help (local)**
  uses an OpenAI-compatible server you run yourself, LM Studio by default. The
  top row mirrors the Prompt Editor's current **positive** and **negative** prompt
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
  it is sent. Both backends are reasoning models, so a Help press waits for the **whole** answer: a reply the API cut off
  at the token limit (`finish_reason: "length"`) is asked for again and stitched on (up to `ai_helper.CONTINUE_ATTEMPTS`,
  the Logs tab saying how many rounds it took), a trace that used the whole budget with nothing written is answered by a
  demand for the JSON, and a body that streams despite `stream: false` is assembled from its frames; when the budget still
  runs out the press fails naming max_tokens rather than filling the boxes with the front of a reply. The reply is then read
  as a whole: of every complete `{...}` in it the best-scoring object wins — the one that fills both prompts and names them
  outright, so the schema or a first draft a reasoning model quotes in its trace is never mistaken for the answer, and the
  schema's `"..."` placeholders read as no answer at all. A model that answers a continuation by re-writing the object from
  the top (Ministral does) is still read; a reply that arrives missing one of the two prompts leaves the box you typed in
  untouched and says so in the Logs tab. The system prompt is `studio_meta.instruction()` over the metadata document's
  `prompt` section (`role`, `task`, `rules` and the `reply_contract`), so the house's Klein anatomy rules live in that
  document. The wording came from
  [`docs/workflow/21-klein-image-handoff.md`](../docs/workflow/21-klein-image-handoff.md#9-two-body-prompt-playbook):
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
  **UNRESOLVED** to the model rather than dropped. The DeepSeek backend's model
  id lives in `ai_helper.MODEL` (`deepseek-flash`); **Help (local)** uses the
  model its server reports.
- **Prompt History**. Stores the full request JSON (prompt column for
  skim, Graph column for node/LoRA/size stats). A successful Generate
  writes a 48×48 thumbnail in the first column. Double-click restores
  JSON + prompt. The page shows an explicit empty state when nothing has been
  generated.
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
  already queued or in flight and a booting replica both leave the button live,
  and the press queues behind the first request instead of
  being blocked. The press is the gate — a replica that is gone, and a group the
  badge says is **stopped**, are refused with their reason when the press is
  made, not by greying the button out: the Logs line, the status line
  (`Refused: …`) and the dialog all carry that one sentence, and nothing is
  queued. A press that
  repeats the request at the **head** of the queue adds nothing: the app digests
  the request it is about to submit and, when the queue's first item carries the
  same digest, it reports that the identical request is already queued (naming
  that row, and pointing at **Retry selected** or **Clear finished** when that
  row is finished). The identical request is still accepted when it is not the
  head, so a second copy can be queued behind a different request.

  The queue also owns the containers' **lifecycle**, and it never **starts** a container: before a request's first attempt it reads the state
  of the group behind that profile's gateway, leaves a group that is running or in an unknown state alone, and refuses a group that is
  **not running** with the same message the press would give (the case where the group stopped between the badge read and the dispatch) — a
  **refused** request (the Logs line, the status line's `Refused: …` and the dialog all carry the sentence), never a failed render.
  `ContainerLifecycle.stop` is the only control-plane call the app makes; nothing in it starts a container. **Generate is not refused for a
  container that is up but not serving yet**: the request is dispatched, the queue reads the state, and the render waits for that container's
  `/ready` before it POSTs — a boot is minutes, so the wait covers about ninety minutes, asking every 10 s at first, then every 30 s, then every 60 s
  (`generator.ready_sleep_s`). While the container has no ready replica every answer is the same 503 page (never pasted into a log; the status line says so in one line),
  and a container that never answers fails the request naming the profile, the gateway and the last status it saw; only a replica that is *gone* and a group the badge says is stopped are refused up front, with the badge's own reason, and
  the state is read again at every dispatch. When a profile's last request has finished, the queue **stops** its group once it has been idle
  for the `queue.idle_stop_s` timeout in the metadata document (3600 seconds, one hour, by default), from the app's existing 15 s tick: a
  profile with a request queued or in flight is never stopped, a stopped container leaves the idle set so a second check cannot stop it
  twice, and a stop Salad rejects is retried only after another full timeout. Which containers the app owns and when each last had work is
  written to `~/.config/salad/studio-queue.json`, so **closing and reopening Studio does not forget a container**: the idle hour still
  arrives and the first tick past it asks for the stop. **The app stops only containers it may stop**, via the record's own `started_by_app`:
  a record that cannot say the app started that container is dropped at load with a line in the log and its container left running, so
  **opening Studio never shuts down a container you started by hand**. The status probe may only *follow* a container the record already owns
  (`SaladQueue.refresh`), never claim one; a request the app dispatches claims its container for that session only, a container with a request
  queued or in flight is never stopped, and the check runs off the Tk thread, so the window never freezes while the control plane is called.

Klein group, prefetch image, Civitai-vs-Comfy quality, and startup
probes: [`docs/workflow/15-salad-flux2-klein-group.md`](../docs/workflow/15-salad-flux2-klein-group.md).

Stores (none in git): `salad_studio/studio-tokens.json` (seeded from `~/.config`
if empty); `~/.config/salad/` holds the gateway files, `studio-profiles.json`,
`studio-loras.json` (LoRA extras), `studio-prompt-history.json` (full `/prompt`
JSON), `studio-prompt-catalog.json` (named request JSON), `studio-images.json`
(your own images and their extra deployment environment) and `studio-vast.json`
(vast.ai instances and the engine choice).

## Layers

Eight layers, one seam. `app.py` owns the window, the tab wiring and the thread
starts; every module outside the UI layer imports and runs in a process where
`tkinter` is never loaded. `tests/test_layers.py` drives one real call per non-UI
layer in a subprocess and asserts exactly that, and a second test keeps the
window in `app.py`.

| Layer | Modules | What a caller gets |
|---|---|---|
| UI | `app.py`, `__main__.py`, `graph_view.py`, `theme.py`, `ui_state.py`, `history_strip.py`, `json_highlight.py` | the window, the tabs, the prompt graph pane |
| Import | `comfy_import.py`, `civitai_verify.py`, `request_json.py` | a Comfy graph built from a Civitai page, a Comfy workflow, or the prompt knobs |
| Persistence | `tokens.py`, `prompt_history.py`, `prompt_catalog.py`, `lora_store.py`, `profiles.py`, `hostings.py`, `studio_meta.py` | stored tokens, prompts, configurations, LoRAs, model info, where a profile renders, and the metadata document |
| Logging | `studio_log.py` | formatted redacted log lines, and an explanation for an HTTP failure |
| Salad communication | `generator.py`, `salad_status.py`, `salad_queue.py`, `salad_gen.py` (repo root) | a routed, queued render request, the plate it wrote, and the container lifecycle (never start, stop when idle) |
| Vast.ai communication | `vast.py` | the account's instance list behind the Bearer key, the endpoint each instance maps, the stored instance list, and the POST that renders on one |
| Image deployment | `image_deploy.py` | the tag, ports and environment each image needs, and the build, run and vast.ai commands that deploy it |
| AI communication | `ai_helper.py`, `ref_check.py` | the Prompt Assist request and its parsed reply |

`app.py` keeps the widgets and the wiring: the routing decision is `profiles.plan_route`,
the POST is `generator.generate_from_payload` through `salad_queue`, and the Prompt Assist
instruction is the metadata document.

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
  runs — the source a config's policy image is seeded from, and the fallback when
  neither its stored policy nor its live group names one. `startup_probe` and
  `readiness_probe` document the six settings each probe runs (`path`, `port`,
  `initial_delay_seconds`, `period_seconds`, `timeout_seconds`,
  `failure_threshold`), which a new config's policy and the Config page start from.
  `deployment` is what it takes to run that image on a host — the build
  `context`, `base_image` and `build_arg` (which unet set the tag bakes), the
  `ports` (`api` 3000 and `comfy` 8188), the `env` entries (each a Tokens-tab
  `token` slot or a literal `value`, with a `note`), and the `gpu` / `disk_gb` /
  `vcpu` / `memory_gb` — and the Config page's **Container images** section renders it.
  **Which profile serves which checkpoint is not here**: it is each profile's own
  `checkpoints` list, edited on the **Config** page, and routing sends a graph to
  the profile that lists the checkpoint it loads. A checkpoint in no profile's
  list is refused with a stated reason instead of being sent to a container that
  cannot serve it, and so is one two profiles list (the choice would be a coin
  toss). A profile whose list spans two families routes with a warning, because
  it works only when the image carries every family. A checkpoint the document
  does not classify is its own family, so a checkpoint that does not exist yet
  needs no document edit.
- `queue.idle_stop_s` is how long a container may sit idle before the queue stops
  it, in seconds (one hour by default); a hand-edited `0`, negative number or word
  reads as the default, so a typo cannot stop a container the moment it goes quiet.
- `prompt` holds the AI layer's instruction: `role`, `task`, `rules` and
  `reply_contract`. Prompt Assist sends what is written there, so the house
  Klein rules in [`docs/workflow/21-klein-image-handoff.md`](../docs/workflow/21-klein-image-handoff.md#9-two-body-prompt-playbook)
  are edited in the document, not in `ai_helper.py`.

## Settings

This folder was moved out of the Eldermark repo, so the paths that used to be relative walk-ups are environment settings with machine defaults; the three settings, their defaults and the Known-limitation paragraph beside them are in the root [`README.md`](../README.md) (Configuration, Known limitations).

Run the three commands separately:

```
python -m unittest discover -s tests -p "test_*.py"    # 1222 tests, ~15-30 min
python test_salad_comfy_live_findings.py               # root structural checks
cd salad_klein && python -m unittest discover -p "test_*.py"   # 18 tests
```

The tests live in `tests/` at the repo root, not in the package: `salad_studio/`
holds only the app's modules, and each test module puts the package directory and
the repo root on `sys.path` itself, so either of the first two commands runs from
the repo root. The third runs in `salad_klein/`, where the image's own two test
modules live.

## Container groups

Building the Salad container image, creating a group, and calling either the
control-plane API or a running container are documented in one place:
[`docs/workflow/23-salad-container-group-deployment.md`](../docs/workflow/23-salad-container-group-deployment.md).
`salad_status.py` is the client it describes; the Config page's policy section
is the UI over it (image PATCH, probes, GPU classes, US-only, Reallocate), one
policy per config.

## Prompt graph pane: JointJS in WebView2

*Consolidated from `docs/workflow/16-salad-studio-prompt-graph.md` on 2026-10-17. Subsection numbers below are the source document's own.*

> **Studio graph pane**, not eldermark. Code:
> [`graph_view.py`](graph_view.py).
> This manual describes the pane; the durable decision and library survey are below.
> Klein groups: [`15-salad-flux2-klein-group.md`](../docs/workflow/15-salad-flux2-klein-group.md).

This file is the durable copy of the 2026-09-20 diagram-library
research, plus what we actually shipped afterward.

### Decision (2026-09-20)

**Stay on JointJS + tkwry** (user, 2026-09-20): do not rewrite Salad
Studio in Qt for NodeGraphQt. NodeGraphQt is the best Python-native
node editor, but it is a second GUI toolkit and does not manhattan-route
around cards. Live pane stays HTML JointJS in WebView2.

**Live graph is JointJS** (`@joint/core` 4.2.5), served as local HTML
under `salad_studio/graph_html/` and embedded with **tkwry**
(WebView2 child HWND). No Graphviz `dot` on the live path. tkinterweb
`HtmlFrame` cannot run Canvas2D / SVG diagram JS (PythonMonkey, not a
browser).

Python places cards with Comfy columns sized to the JointJS card (`prompt_to_joint`); unknown classes are not forced into the sampler column. JointJS draws
rounded dark cards, left/right ports, and **manhattan** orthogonal
wires with **rounded** corners that **route around other cards**. The requirement was Comfy-style
left-to-right cards, side ports, wires that do not run through boxes, and **field text that stays inside**
the card (`name` / `lora_name`); no inspected Python widget is a drop-in for Tk Salad Studio.

| Piece | Where |
|---|---|
| Prompt → JointJS JSON | `prompt_to_joint` |
| HTML shell | `graph_html/viewer.html` + vendored `joint.min.js` |
| Pane | `GraphPane` → tkwry `WebView` (`app=_current.html`, `user_data_dir` under `%LOCALAPPDATA%\SaladStudio\WebView2`) |
| Fallback | **Open in browser** (same HTML). **Open as Comfy** = LiteGraph |
| Tests | `test_graph_view.py` class `JointGraphExport` |

LiteGraph.js (ComfyUI's editor) is also vendored. Spline links look
like Comfy; they do **not** pathfind around nodes. That is why it is
not the live pane.

The Graphviz/grandalf stack is gone; the helper list is in *What we tried before the live pane*.

### HTML / JS libraries

These run in a **browser or WebView2**, not in Tk Canvas.

| Library | Comfy-like? | Smooth wires | Avoid node overlap | Embed notes |
|---|---|---|---|---|
| **JointJS** (`manhattan` + `rounded`) | Dark cards + L/R ports if we style them | Orthogonal with circular fillets | **Yes.** Manhattan treats other elements as obstacles | One UMD file. **Live pick.** |
| **LiteGraph.js** | **Yes, ComfyUI's editor** | Bezier/spline | No; wires can cross cards (same as Comfy) | Vendored. **Open as Comfy** |
| **Drawflow** | HTML nodes, not Comfy cards | Curved SVG | No | Vanilla JS |
| **Rete.js** | Visual programming | Plugin renderers | No | Heavy, needs a renderer |
| **xyflow + SmartBezier / avoid-nodes-edge** | Customizable cards | Bezier or orthogonal | **Best "no intersection"** (libavoid WASM) | React, not a drop-in in Tk |
| **ELK.js** (`edgeRouting: SPLINES`, conservative) | Layout engine, we paint | Splines that hug a layered graph | Conservative mode routes around nodes; sloppy can clip | Needs a real JS engine; worker-based bundle is awkward in file:// |
| **nodegraph-js** | Dark cards, L/R slots | Bezier | Auto-arrange, not obstacle routing | Vanilla JS |
| **@gravity-ui/graph** | Node editor | Bezier | Canvas+HTML | Needs a bundler |
| **tkinterweb HtmlFrame** | Not a graph lib | n/a | n/a | HTML/CSS in Tk. JS is PythonMonkey and **cannot** run JointJS/LiteGraph |
| **tkwry (WebView2)** | Host for any JS graph | n/a | n/a | Real Edge in a Tk frame. **Live host.** |

The table above carries each rejection; the Graphviz stack is removed (see "What we tried").

Not a fit: Nodezator, NetworkX+Matplotlib, Qt/NodeGraphQt.

### What we tried before the live pane (both removed)

Two Tk attempts are gone with the dead layout stack: in-house Comfy columns with gutter polylines
(chamfered corners, not circular fillets; wires still crossed cards) and grandalf Sugiyama placement
(scattered nodes; rank-by-topology is not Comfy column order). The Graphviz attempt (`splines=true`,
HTML `<TABLE>` labels, compass `:e` → `:w` edges) went with them, and its helpers (`prompt_to_dot`,
`run_dot`, `graphviz_layout`, `find_dot`, `parse_dot_plain`, `grandalf_resolve`, `resolve_layout`)
were **removed** from `graph_view.py` — nothing on the shipped path called them.

**No `dot` dependency today.** The pane never invokes Graphviz; the live pane is JointJS HTML in
WebView2 and the fallback is **Open in browser** (the same HTML). There is no install message and no
`layout_xy` fallback because there is no `dot` path at all.

### Sources (survey)

- JointJS manhattan router + rounded connector (docs.jointjs.com); LiteGraph.js (github.com/jagenjo/litegraph.js, ComfyUI editor); tkwry WebView2 embed (pypi.org/project/tkwry)
- Graphviz `rankdir`, shapes, `splines`, `radius`, `fixedsize`, `dot` layout (graphviz.org docs); this repo's `salad_studio/graph_view.py`
