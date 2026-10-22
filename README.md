# salad-studio

Windows tooling for SaladCloud ComfyUI image generation: a local studio that
builds, validates, and POSTs Comfy `/prompt` graphs, plus the container image
and prompt-recipe pipeline they run on. The studio is an Angular page served by
a Python server on 127.0.0.1.

## Quick start

```
python -m salad_studio
```

Run from the repo root. It serves on a free loopback port and opens the page
there; `python -m salad_studio 8765` pins the port and `--no-open` keeps the
browser closed.

Tests are `unittest`. Run the commands separately:

```
python -m unittest discover -s tests -p "test_*.py"    # 1062 tests, ~35 s
python test_salad_comfy_live_findings.py               # root structural checks
cd salad_klein && python -m unittest discover -p "test_*.py"   # 18 tests
```

## Requirements

Tested on Python 3.14.7 with `pillow`, and the standard library's `http.server`.
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
| `docs/workflow/` | Five playbooks: [23](docs/workflow/23-salad-container-group-deployment.md) deployment, [21](docs/workflow/21-klein-image-handoff.md) the Klein handoff, [15](docs/workflow/15-salad-flux2-klein-group.md) the Klein group, [14](docs/workflow/14-salad-comfy-live-findings.md) live findings, [22](docs/workflow/22-two-body-correctness-research.md) anatomy research. The graph pane is in [the manual](salad_studio/README.md#prompt-graph-pane-drawn-from-the-model). |
| `docs/history/` | Dated records: audits [57](docs/history/57-salad-studio-audit-2026-09.md), [58](docs/history/58-salad-studio-audit-2026-09-22.md), [59](docs/history/59-salad-studio-audit-2026-09-26.md), [61](docs/history/61-salad-studio-audit-2026-10-13.md), [62](docs/history/62-salad-studio-audit-2026-10-14.md), [63](docs/history/63-salad-studio-audit-2026-10-16.md), the [2026-10-17 issue pass](docs/history/64-salad-studio-issue-pass-2026-10-17.md), the [prompt-graph decision](docs/history/65-salad-studio-prompt-graph-decision-2026-10-17.md), the [2026-10-18 UI/UX audit](docs/history/65-salad-studio-ui-audit-2026-10-18.md), and the [container-restart investigation](docs/history/60-salad-container-restart-2026-09-27.md). |
| `docs/` | The [consolidated issue record](docs/issue-records.md) for 2026-10-14 to 2026-10-16. |
| `model_catalog.py` | Local LoRA and checkpoint cache. `fetch-klein --stage` warms the Docker build. |
| `salad_gen.py` | One-shot SaladCloud ComfyUI Flux generate. |
| `salad_probe_klein.py`, `salad_probe_sdxl.py`, `salad_probe_ages.py`, `salad_age_review.py`, `salad_catalog_faces.py` | Probes and the Eldermark face catalog. |
| `face_prompt.py`, `face_prompt_pack.json` | Age-locked, DNA-aware face prompts. |
| `test_salad_comfy_live_findings.py` | Structural checks on the live-findings doc. |
| `.claude/skills/civitai-verify/` | A skill that replays a Civitai link through Studio import and a live container POST. |

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
