# salad-studio

Windows tooling for SaladCloud ComfyUI image generation: a Tkinter studio that
builds, validates, and POSTs Comfy `/prompt` graphs, plus the container image
and prompt-recipe pipeline those graphs run on.

The repo is three things sharing one workflow:

- **`salad_studio/`**. The desktop app. Prompt and LoRA knobs, a JointJS node
  graph over the request JSON, Civitai and Comfy workflow import, a prompt
  catalog, and DeepSeek-assisted prompt rewriting.
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

Tests are `unittest`, and there are two commands. The second is not part of
the first:

```
python -m unittest discover -s salad_studio -p "test_*.py"   # 566 tests, ~3 min
python test_salad_comfy_live_findings.py                     # root structural checks
```

## Requirements

Python 3.14 with `pillow`, `requests`, and `tkinterweb` (plus `tkinterweb-tkhtml`),
and Tk from the standard library. The app is Windows-only: it uses WebView2 for
the graph pane, `%LOCALAPPDATA%\SaladStudio\WebView2` for the browser cache, and
`os.startfile` to open plates.

Generation needs a running SaladCloud ComfyUI container group and a Salad API
key. Building the container needs Docker.

## Layout

| Path | What it is |
|---|---|
| `salad_studio/` | The Tkinter app and its test suite. [`salad_studio/README.md`](salad_studio/README.md) is the real manual, tabs, knobs, and the import rules in detail. |
| `salad_klein/` | Docker image, `prefetch.py` entrypoint, and Klein prompt recipes. [`salad_klein/README.md`](salad_klein/README.md) is the build-context short form. |
| `docs/workflow/` | The build and generation playbooks. Start at [23](docs/workflow/23-salad-container-group-deployment.md) for deployment, [21](docs/workflow/21-klein-image-handoff.md) for the Klein handoff, [16](docs/workflow/16-salad-studio-prompt-graph.md) for the graph pane. |
| `docs/history/` | Dated audits of the studio ([57](docs/history/57-salad-studio-audit-2026-09.md), [58](docs/history/58-salad-studio-audit-2026-09-22.md)). |
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
| `ELDERMARK_REPO` | `C:\Users\vkozy\repos\lifesim-design` | Checkout the root structural test reads docs and skills from. |
| `SALAD_STUDIO_HOME` | This folder | Where `model_catalog.py` stages Klein weights for the Docker build. |

The defaults name one machine's paths. Set the variables, or change the
defaults, anywhere else.

Keys and state stay out of git: `salad_studio/studio-tokens.json` is gitignored,
and gateway files, profiles, LoRA extras, prompt history, and the prompt catalog
live under `~/.config/salad/`. Generate sends the Salad key as `Salad-Api-Key`
and appends the Civitai `?token=` to LoRA URLs at POST time.

## Known limitations

The studio package and its suite are standalone. Three Eldermark catalog helpers
are not: `salad_catalog_faces.py`, `salad_probe_ages.py`, and
`salad_probe_sdxl.py` import `paperdoll_mask` and `regen_faces`, which stayed in
the Eldermark repo, so they fail on import here. `test_salad_comfy_live_findings.py`
asserts that documented failure rather than reporting a false pass, and starts
exercising the real freeze path as soon as the gap is closed.

## Content note

The Klein prompt recipes (`salad_klein/prompt_*.json`) and several playbooks in
`docs/` describe explicit adult content, since that is what this pipeline
generates. They are checked in as the working record of what has been tried and
what a human has judged.
