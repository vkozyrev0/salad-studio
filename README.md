# salad-studio

Windows tooling for SaladCloud ComfyUI image generation: a Tkinter studio that
builds, validates, and POSTs Comfy `/prompt` graphs, plus the container image
and prompt-recipe pipeline those graphs run on.

The repo is three things sharing one workflow:

- **`salad_studio/`**. The desktop app. Prompt and LoRA knobs, a JointJS node
  graph over the request JSON, Civitai and Comfy workflow import, a prompt
  catalog, and prompt rewriting assisted by DeepSeek or a local LM Studio
  server.
- **`salad_klein/`**. The Docker build for a separate ComfyUI API container
  group (Flux.2 Klein 9B), its `prefetch.py` first-boot entrypoint, and the
  Klein prompt recipes.
- **Top-level scripts**. The Eldermark face/plate catalog helpers, a local
  model cache, and one-shot generators and probes.

## Quick start

```
python -m salad_studio
```

Run from the repo root. `python salad_studio/app.py` also works.

Tests are `unittest`. Three commands, and the later ones are not part of the
first:

```
python -m unittest discover -s tests -p "test_*.py"    # 1217 tests, ~15-30 min
python test_salad_comfy_live_findings.py               # root structural checks
cd salad_klein && python -m unittest discover -p "test_*.py"   # 18 tests
```

## Requirements

Python 3.14 with `pillow` and `tkwry` (the WebView2 embed the graph pane
uses), and Tk from the standard library. The app is Windows-only: it uses
WebView2 for the graph pane, `%LOCALAPPDATA%\SaladStudio\WebView2` for the
browser cache, and `os.startfile` to open plates.

Generation needs a running SaladCloud ComfyUI container group and a Salad API
key. Building the container needs Docker.

## Layout

| Path | What it is |
|---|---|
| `salad_studio/` | The Tkinter app. [`salad_studio/README.md`](salad_studio/README.md) is the real manual, tabs, knobs, and the import rules in detail. |
| `tests/` | The suite, one module per area, run from the repo root. |
| `salad_klein/` | Docker image, `prefetch.py` entrypoint, and Klein prompt recipes. [`salad_klein/README.md`](salad_klein/README.md) is the build-context short form. |
| `docs/workflow/` | Five playbooks: [23](docs/workflow/23-salad-container-group-deployment.md) deployment (containers and vast.ai), [21](docs/workflow/21-klein-image-handoff.md) the Klein handoff and two-body prompt playbook, [15](docs/workflow/15-salad-flux2-klein-group.md) the Klein group, [14](docs/workflow/14-salad-comfy-live-findings.md) live findings, and [22](docs/workflow/22-two-body-correctness-research.md) the anatomy and SDXL research. The graph pane is in [the manual](salad_studio/README.md#prompt-graph-pane-jointjs-in-webview2). |
| `docs/history/` | Dated records of the studio: audits [57](docs/history/57-salad-studio-audit-2026-09.md), [58](docs/history/58-salad-studio-audit-2026-09-22.md), [59](docs/history/59-salad-studio-audit-2026-09-26.md), [61](docs/history/61-salad-studio-audit-2026-10-13.md), [62](docs/history/62-salad-studio-audit-2026-10-14.md), [63](docs/history/63-salad-studio-audit-2026-10-16.md), the [2026-10-17 issue pass](docs/history/64-salad-studio-issue-pass-2026-10-17.md), and the container-restart investigation [60](docs/history/60-salad-container-restart-2026-09-27.md). |
| `docs/` | The consolidated issue record for [2026-10-14 to 2026-10-16](docs/issue-records.md): the two top-five lists and the four sweeps, each with the drive and the check that keeps it fixed. |
| `model_catalog.py` | Local LoRA/checkpoint cache with Civitai provenance. `fetch-klein --stage` warms the Docker build. |
| `salad_gen.py` | One-shot SaladCloud ComfyUI Flux generate. |
| `salad_probe_klein.py`, `salad_probe_sdxl.py` | Probe faces, bodies, pregnancies, and events on a Salad group. |
| `salad_probe_ages.py`, `salad_age_review.py`, `salad_catalog_faces.py` | Eldermark face catalog: per-age plates, review, and a resumable rebuild. |
| `face_prompt.py`, `face_prompt_pack.json` | Compose age-locked, DNA-aware face prompts. |
| `test_salad_comfy_live_findings.py` | Structural checks on the live-findings doc. |
| `.claude/skills/civitai-verify/` | A Claude Code skill that replays a Civitai link through Studio import and a live container POST. |

The `docs/` numbering starts at 14 and skips 20 because those files came from a
larger docs tree; the gaps are not missing work.

## Configuration

| Setting | Default | Purpose |
|---|---|---|
| `ELDERMARK_ART` | `C:\Users\vkozy\repos\lifesim-design\art` | Art tree the tool writes plates into (`art/salad_studio/`, `art/model-cache/`). |
| `ELDERMARK_REPO` | `C:\Users\vkozy\repos\lifesim-design` | Checkout the root structural test reads docs and skills from. **The second test command needs this checkout**; without it the command prints that and exits 0. |
| `SALAD_STUDIO_HOME` | This folder | Where `model_catalog.py` stages Klein weights for the Docker build. |

The defaults name one machine's paths. Set the variables, or change the
defaults, anywhere else.

Keys and state stay out of git: `salad_studio/studio-tokens.json` is gitignored,
and gateway files, profiles, LoRA extras, prompt history, and the prompt catalog
live under `~/.config/salad/`. Generate sends the Salad key as `Salad-Api-Key`
and appends the Civitai `?token=` to LoRA URLs at POST time.

## Known limitations

The studio package and its suite are standalone. Three Eldermark catalog helpers are not:
`salad_catalog_faces.py` imports `paperdoll_mask` and `regen_faces`, which stayed in the Eldermark
repo, and the two probes that import it fail on import here. `test_salad_comfy_live_findings.py`
asserts that documented failure rather than reporting a false pass, and starts exercising the real
freeze path as soon as the gap is closed.

## Content note

The Klein prompt recipes (`salad_klein/prompt_*.json`) and several playbooks in
`docs/` describe explicit adult content, since that is what this pipeline
generates. They are checked in as the working record of what has been tried and
what a human has judged.
