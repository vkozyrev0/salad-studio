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
there; the URL it prints carries a token it mints for the run, and the server
refuses any request without it, so a local program cannot drive it. Open the
URL the server prints. `python -m salad_studio 8765` pins the port and
`--no-open` keeps the browser closed. The page opens on Config; paste provider keys on Tokens before
the first render. Background removal downloads its model when Generate first
asks for it, so run `python -m salad_studio --prefetch-cutout` once ahead of
time; it prints where the model landed and exits.

Tests are `unittest`. Run the commands separately:

```
python -m unittest discover -s tests -p "test_*.py"    # 1162 tests, ~35 s
python test_salad_comfy_live_findings.py               # root structural checks
cd salad_klein && python -m unittest discover -p "test_*.py"   # 18 tests
```

## Requirements

Tested on Python 3.14.7 with `pillow==12.3.0` and `rembg==2.0.86` (see `requirements.txt`), and the standard library's `http.server`.
rembg's `u2net` model (168 MB) is not in the repo; it lands in `~/.rembg/models/`
when first downloaded, and Generate cuts nothing until it is there.
The page is built with Angular 22 and AG Grid Community into `ui/dist/`, which
is not committed: `python -m salad_studio` builds it when it is missing or its
source changed, and keeps it when it is current. A build needs Node once; the
server rebuilds only when the page's source differs from the build on disk. Windows still opens a plate with
`os.startfile`.

Generation needs a SaladCloud ComfyUI container group and a Salad API key, or a
vast.ai instance selected on the Config page and a Vast.ai key. Building the
container needs Docker.

Post-processing: **Remove background** on Prompt Settings cuts the subject out
of every plate Generate or Retry writes, through rembg, and writes a
`-cutout.png` beside the plate. The original stays, and a render whose cut
cannot run still finishes with the original plate and a note saying why.

## Layout

| Path | What it is |
|---|---|
| `salad_studio/` | The server, the stores and the page controllers; [`salad_studio/README.md`](salad_studio/README.md) is the manual. |
| `ui/` | The Angular page. The server builds `ui/dist/` when its source changes; `cd ui && npx ng build` makes the same build by hand. |
| `tests/` | The suite, one module per area. |
| `salad_klein/` | Docker image, `prefetch.py`, and Klein recipes; [`salad_klein/README.md`](salad_klein/README.md) is the short form. |
| `docs/workflow/` | Five playbooks: [23](docs/workflow/23-salad-container-group-deployment.md) deployment, [21](docs/workflow/21-klein-image-handoff.md) the Klein handoff, [15](docs/workflow/15-salad-flux2-klein-group.md) the 2026-09-21 Klein group record, [14](docs/workflow/14-salad-comfy-live-findings.md) live findings, [22](docs/workflow/22-two-body-correctness-research.md) anatomy research. The graph pane is in [the manual](salad_studio/README.md#prompt-graph-pane-drawn-from-the-model). |
| `model_catalog.py` | Local LoRA and checkpoint cache. `fetch-klein --stage` warms the Docker build. |
| `salad_gen.py` | One-shot SaladCloud ComfyUI Flux generate. |
| `salad_probe_klein.py`, `salad_probe_sdxl.py`, `salad_probe_ages.py`, `salad_age_review.py`, `salad_catalog_faces.py` | Probes and the Eldermark face catalog. |
| `face_prompt.py`, `face_prompt_pack.json` | Age-locked, DNA-aware face prompts. |
| `test_salad_comfy_live_findings.py` | Structural checks on the live-findings doc. |
| `.github/workflows/checks.yml` | CI, two jobs. The Python job runs the suite, the queue check, then installs `salad_klein/requirements.txt` before the Klein suite. The `ui` job runs `npx ng build`, the check that the server builds a page missing from disk, Vitest, and `node audit.cjs`. |
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
| `ELDERMARK_MODEL_CACHE` | `$ELDERMARK_ART\model-cache` | Replaces the `model_catalog.py` cache root; the tests use it. |

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
two probes fail here. `test_salad_comfy_live_findings.py` accepts exactly that
import failure with a skip note, so its `salad_catalog_faces --generate` freeze
assertion does not run until the gap closes. `tests/test_salad_catalog_faces.py`
drives the same freeze check by exec'ing the shipped functions, and the
structural test still runs the `regen_faces` freeze check.

## Content note

The Klein recipes (`salad_klein/prompt_*.json`) and several playbooks in `docs/`
describe explicit adult content, since that is what this pipeline generates.
