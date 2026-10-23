# salad-studio

Windows tooling for SaladCloud ComfyUI image generation: a local studio that
builds, validates, and POSTs Comfy `/prompt` graphs, plus the container image
and prompt-recipe pipeline they run on. The studio is an Angular page served by
a Python server on 127.0.0.1.

## Quick start

Install the one dependency once:

```
python -m pip install -r requirements.txt
```

Then start the studio:

```
python -m salad_studio
```

Run from the repo root. It serves on a free loopback port and opens the page
there; `python -m salad_studio 8765` pins the port and `--no-open` keeps the
browser closed. The page opens on Config; paste provider keys on Tokens before
the first render.

Tests are `unittest`. Run the commands separately:

```
python -m unittest discover -s tests -p "test_*.py"    # 1082 tests, ~35 s
python test_salad_comfy_live_findings.py               # root structural checks
cd salad_klein && python -m unittest discover -p "test_*.py"   # 18 tests
```

## Requirements

Tested on Python 3.14.7 with `pillow==12.3.0` (see `requirements.txt`), and the standard library's `http.server`.
The page is built with Angular 22 and AG Grid Community; `ui/dist/` is committed,
so running the studio needs no Node. Windows still opens a plate with
`os.startfile`.

Generation needs a SaladCloud ComfyUI container group and a Salad API key, or a
vast.ai instance selected on the Config page and a Vast.ai key. Building the
container needs Docker.

## Layout

| Path | What it is |
|---|---|
| `salad_studio/` | The server, the stores and the page controllers; [`salad_studio/README.md`](salad_studio/README.md) is the manual. |
| `ui/` | The Angular page. `cd ui && npx ng build` after changing it. |
| `tests/` | The suite, one module per area. |
| `salad_klein/` | Docker image, `prefetch.py`, and Klein recipes; [`salad_klein/README.md`](salad_klein/README.md) is the short form. |
| `docs/workflow/` | Five playbooks: [23](docs/workflow/23-salad-container-group-deployment.md) deployment, [21](docs/workflow/21-klein-image-handoff.md) the Klein handoff, [15](docs/workflow/15-salad-flux2-klein-group.md) the 2026-09-21 Klein group record, [14](docs/workflow/14-salad-comfy-live-findings.md) live findings, [22](docs/workflow/22-two-body-correctness-research.md) anatomy research. The graph pane is in [the manual](salad_studio/README.md#prompt-graph-pane-drawn-from-the-model). |
| `model_catalog.py` | Local LoRA and checkpoint cache. `fetch-klein --stage` warms the Docker build. |
| `salad_gen.py` | One-shot SaladCloud ComfyUI Flux generate. |
| `salad_probe_klein.py`, `salad_probe_sdxl.py`, `salad_probe_ages.py`, `salad_age_review.py`, `salad_catalog_faces.py` | Probes and the Eldermark face catalog. |
| `face_prompt.py`, `face_prompt_pack.json` | Age-locked, DNA-aware face prompts. |
| `test_salad_comfy_live_findings.py` | Structural checks on the live-findings doc. |
| `.github/workflows/checks.yml` | CI: the Python suite, the queue check, the Klein suite, the page build, the dist drift check, Vitest, and the binding audit. |
| `.claude/skills/civitai-verify/` | A skill that replays a Civitai link through Studio import and a live container POST. |
| `.claude/skills/queue-submission-safety/` | A formal check that the queue never POSTs an accepted request twice. |

The `docs/` numbering starts at 14 and skips 16 through 20; the gaps are not
missing work.

## Configuration

| Setting | Default | Purpose |
|---|---|---|
| `ELDERMARK_ART` | `C:\Users\vkozy\repos\lifesim-design\art` | Art tree the tool writes plates into. |
| `ELDERMARK_REPO` | `C:\Users\vkozy\repos\lifesim-design` | Checkout the root structural test reads. **The second test command needs this checkout**; without it the command exits 0. |
| `SALAD_STUDIO_HOME` | the repo root | Where `model_catalog.py` stages Klein weights. |

The defaults name one machine's paths; set the variables elsewhere.

Keys and state stay out of git: `salad_studio/studio-tokens.json` is gitignored.
The studio's stores live under `~/.config/salad/`: profiles, LoRAs, prompt
history and thumbs, the prompt catalog, images, vast.ai instances and rental
criteria, the queue ledger, UI state, and the metadata document. Generate sends
the Salad key as `Salad-Api-Key` and appends the Civitai `?token=` to LoRA URLs
at POST time.

## Known limitations

The studio package and suite are standalone. `salad_catalog_faces.py` imports
`paperdoll_mask` and `regen_faces`, which stayed in the Eldermark repo, and its
two probes fail here. `test_salad_comfy_live_findings.py` asserts that failure
rather than a false pass, and exercises the real freeze path once the gap
closes.

## Content note

The Klein recipes (`salad_klein/prompt_*.json`) and several playbooks in `docs/`
describe explicit adult content, since that is what this pipeline generates.
