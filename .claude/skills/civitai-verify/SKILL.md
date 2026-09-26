---
name: civitai-verify
description: >
  Verify Civitai image URL(s) through Salad Studio import and a live Salad
  container POST, then describe the site plate vs the generated JPEG and
  backtrack JSON→import when those descriptions differ. Invoke with
  /civitai-verify and one or more links such as
  https://civitai.com/images/123566519. Use when the user asks to check a
  Civitai link, replay Studio Import against klein/klein5090, opt in to a
  mechanical conversion patch with `--edit-import`, or compare the Civitai
  original to the Salad result.
---

# /civitai-verify

Headless Salad Studio Import + Generate for Civitai image URLs. Converts with
`comfy_import.import_to_request`, POSTs via `generator.generate_from_payload`
when the picked group is Ready, and journals every step.

## Run

From the repo root (`PYTHONPATH` is set by the script):

```bash
python .claude/skills/civitai-verify/verify.py \
  "https://civitai.com/images/123566519" \
  --journal <journal-dir-or-jsonl>
```

That invocation is read-only on conversion sources: on inspect/POST failure
it journals the diagnosis and halts. Add **`--edit-import`** to opt in to
applying known mechanical conversion patches (`missing_node_type` →
`SALAD_MISSING_TYPES` and the replica omit list in `comfy_import.py`) and
re-running convert/POST.

Multiple URLs are allowed. Tokens come from the same places Studio reads
(`studio-tokens.json` / `~/.config/salad/key` / Civitai token).

| Flag | Meaning |
|---|---|
| `--journal PATH` | Required. Directory (`journal.jsonl` inside) or a `.jsonl` file. Append-only. |
| `--out PATH` | JPEG output dir (default: journal dir `/out`) |
| `--no-post` | Convert/inspect only |
| `--edit-import` | Opt in to patching conversion sources (`comfy_import.py`) on a mechanical failure, then retry. Default **off**. |
| `--no-edit-import` | Never patch conversion sources; journal the diagnosis and halt. Already the default (accepted for compatibility). |
| `--record-compare` | Finish compare from `--site-description` and `--generated-description` of the local JPEGs |
| `--ablate` | After a successful POST, drop one node at a time in this order: LoRAs, then CLIP encodes, then UNET/VAE/sampler/…; `SaveImage` stays. POST again per trial. |
| `--max-ablate N` | Cap on ablation trials (default 24) |
| `--fixture PATH` | JSON `{metadata, workflow}` if Civitai fetch fails |
| `--no-fallback` | Do not use the bundled metadata fixture when fetch fails |
| `--max-attempts N` | Import-code retry cap (default **5**) plus fingerprint stop |
| `--source-root PATH` | Directory holding `comfy_import.py` / `request_json.py` |
| `--extras PATH` | LoRA extras JSON the `audit-loras` step compares against (default: the Studio store) |
| `--allow-prompt-edit` | Opt-in CLIP overlay. Default off. Use when the author left generation-data with no prompt. |
| `--prompt-positive TEXT` | With `--allow-prompt-edit`, set positive CLIP before POST (e.g. site-plate caption). |
| `--prompt-negative TEXT` | With `--allow-prompt-edit`, set negative CLIP before POST. |

## What the POST meets

Routing and the container groups come from the metadata document
(`salad_studio/studio-metadata.json`, or your copy at
`~/.config/salad/studio-metadata.json`), read through `studio_meta`; a graph
whose checkpoint has no entry there is refused with a stated reason rather than
sent to a group that cannot serve it.

The POST itself goes through the shared queue (`salad_queue.shared()`), the same
line Studio's Generate button uses. While another render holds the line the
request waits its turn, so a verify run can sit behind an in-flight Studio
render. A container that is not available yet (`502`, `503`, `520`, `521`,
`522`, `523`, or a transport that never answered) is retried automatically, up
to `MAX_ATTEMPTS` attempts with `RETRY_SLEEP_S` seconds between them. A `504` or
`524` is terminal, because Cloudflare returns those after giving up on a job the
container may still be running, and a request the container has already accepted
is never POSTed twice. A run that meets an unavailable container therefore
reports its failure after those retries rather than immediately.

## Agent loop

1. Run the CLI. Read the journal (JSONL). Every step is one object with `step`.
2. Required steps: `container-list`, `fetch`/`convert`/`inspect`, **`audit-clip`**, **`audit-loras`**, then `post` or `post` skipped. After a JPEG: `compare` or `pending_local_describe` then `--record-compare`. Composition mismatches are `significantly_different`.
3. Fail-closed: a failed fetch/convert/inspect is `ok: false`. Do not treat it as a successful import. Do not invent a visual match when compare was skipped.
4. After POST, the driver downloads the Civitai site plate next to the Salad JPEG. Remote xAI vision is optional. **A 403 / missing key is not the end:** journal `pending_local_describe` with `site_image` and `generated` paths, plus an immediate JSON→import `backtrack`. **Read those two local files**, write 2–4 sentence descriptions (subject, pose, setting, clothing), then:

```bash
python .claude/skills/civitai-verify/verify.py --journal <same-journal> \
  --record-compare \
  --site-description "..." \
  --generated-description "..."
```

That journals `similar` / `significantly_different` from the local files. **Any composition difference is significant.** Put layout in the captions.

If they differ, identify the culprit **in the JSON request**:

1. **`audit-clip`**. Positive/negative `CLIPTextEncode` vs Civitai generation-data. Empty CLIP + no generation-data prompt often means the **author omitted the prompt on purpose**. Default: do not invent CLIP. With **`--allow-prompt-edit`**, re-run and set CLIP from the **site-plate caption** (and optional negative):

```bash
python .claude/skills/civitai-verify/verify.py "URL" --journal <same-journal> \
  --allow-prompt-edit \
  --prompt-positive "site caption: subject, pose, setting, clothing, layout" \
  --prompt-negative "..."
```

That overlays CLIP on the converted graph for this run only. It does **not**
change `comfy_import.py`, and it is the only path that touches prompt text:
without the flag, `CLIPTextEncode` `text` is left alone, the Civitai
generation-data is kept, and `/prompt` is not rewritten to force a match.
Journal `prompt-edit`. Then compare the new JPEG to the site plate.
2. **`audit-loras`**. Each `LoraLoader` vs Studio extras. Flag local filenames not in extras, and families that are not Flux.2 Klein.
3. **Node ablation**. `--ablate` (same journal): one node per trial, in the order the flag table gives. If dropping a node makes the gen closer to the site, that node is the culprit. Graph wiring only unless `--allow-prompt-edit` is on.

4. Other JSON checks (no extra POSTs): empty CLIP, local LoadImage omitted (img2img → txt2img), UNET mapped to replica Klein file, seed/size vs metadata.
5. If JSON is not runnable or POST/Comfy fails, the driver diagnoses the error. With **`--edit-import`**, mechanical `missing_node_type` failures may omit/stub **node types** and retry; without it the run journals `skipped: "edit_import is off; conversion code was not modified"` and halts. If the journal has `skipped: "no mechanical import-code fix for these issues"`, you may edit conversion **structure** only.
6. Re-run the same command with the **same `--journal`** after a manual conversion edit. The driver fingerprints those import sources. If a new fingerprint restores an earlier hash, it writes `step: loop`, `loop: true`, and **stops**. An unchanged mechanical patch is journaled as no-mechanical-fix; it is not a loop.
7. After an import-code edit, run the repo's suite from the repo root:
   `python -m unittest discover -s salad_studio -p "test_*.py"`
   If it fails, revert the edit, journal the revert by re-running (the loop detector will stop a ping-pong), and stop.
8. Cap: `MAX_ATTEMPTS` (`civitai_verify.py`); the driver stops itself at the cap and at a fingerprint loop.

Site-plate fetch uses the Civitai image API `url` field.

## Journal

Append-only JSONL. Fingerprints live on `import-code-baseline` / `import-code-change`. A later change that matches any earlier fingerprint is a loop.

Do not invent a successful live POST or a visual match. If Salad is not Ready or the key is missing, the `post` row must record `skipped`. If the site plate is missing, `compare` records `skipped`.
