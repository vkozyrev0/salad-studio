# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

One operator: the repo owner, on their own Windows machine, working at `127.0.0.1`. They start the studio with `python -m salad_studio`, open the URL it prints, and drive one page at a time. There are no accounts, roles, or shared deployment; the loopback binding and the per-run token exist so that the operator is the only caller.

The job: turn an idea, a reference image, or a pasted Civitai/Comfy graph into a request the rented container accepts, then land the rendered plates in the Eldermark art tree.

## Product Purpose

Salad Studio builds, validates, and POSTs ComfyUI `/prompt` graphs to a SaladCloud container group or a vast.ai instance, and writes the resulting plates into a game's art tree. It also carries the container image and prompt recipes those renders run on.

A session succeeds when a correct graph is accepted and a plate is on disk, without hand-editing JSON.

## Positioning

The studio is the local bridge between the graph formats people copy around and one rented container. It converts Civitai, Draw Things, A1111, and Comfy pastes into a Klein-native request, validates against the same gate Generate uses, rewrites the nodes the Salad replica cannot run while keeping the editor's copy intact, owns the queue and container lifecycle, and names the plate's destination in the art tree. A general ComfyUI client stops at "submit a workflow"; a cloud GPU console stops at "rent a machine".

## Operating Context

- Windows, run from the repo root. Python 3.14.7 serves the page; Angular 22 with AG Grid Community is built into `ui/dist/` on demand and is not committed.
- Eleven numbered pages in the left rail, in order: Config, Prompt Settings, Tokens, LoRAs, Prompt Editor, Prompt Assist, Prompt Catalog, Import, Prompt History, Queue, Logs.
- Every action is one `POST /api/action` naming a page and an action; the reply carries that page's whole state. Status, generation ticks, log lines, dialogs, and shell state arrive on `GET /api/events` as server-sent events.
- Renders are long and asynchronous: a boot can take minutes, the readiness wait covers about ninety minutes, the status probe runs every 15 s, and the generation tick every 2 s. The queue runs one line per profile and stops a container after an hour idle.
- Plates are written under `ELDERMARK_ART` (default `C:\Users\vkozy\repos\lifesim-design\art`). The root structural test reads the `ELDERMARK_REPO` checkout.
- Provider keys come from local files and environment: `salad_studio/studio-tokens.json` (gitignored), `~/.config`, `DEEPSEEK_API_KEY`, `~/.config/vast/key`.
- The Klein recipes and several playbooks describe explicit adult content, because that is what this pipeline generates.

## Capabilities and Constraints

Confirmed functionality: profiles with checkpoint-to-family routing; container image selection, environment editing, and deploy command copies; Salad group read and apply; vast.ai instance listing and rent-a-machine; prompt settings and LoRA chain rebuild; per-provider token checks; a LoRA catalog with Civitai, Hugging Face, local, and URL sources; a prompt editor with a read-only graph pane and a validate gate; Civitai/Comfy import and conversion; a prompt catalog; prompt assist through DeepSeek or a local LM Studio server; prompt history with ratings and thumbnails; a queue with retry, cancel, and clear-finished; container logs; background removal through rembg `u2net`.

Technical constraints: the server binds loopback and refuses a foreign `Origin`; every request needs the run token, sent as `X-Studio-Token`, with the event stream taking `?token=`. Handlers run on one thread. No module in the Python package may import a UI toolkit (`tests/test_layers.py`). Stores live under `~/.config/salad/`.

Terminology is part of the product's surface: **plate**, **render**, **profile**, **family**, **gateway**, **Klein**, **cutout**, **request JSON**, **prompt**.

Multi-user operation is out of scope.

## Brand Commitments

The name is **Salad Studio**. The palette and type tokens are a single tested source in `ui/src/styles.css`; a new colour is a new token there, never a literal in a component, and `tests/test_theme.py` holds the page to WCAG AA contrast.

## Evidence on Hand

- Test suites: 1162 Python tests, the root structural checks, 18 Klein tests, and the page's Vitest suite; CI is `.github/workflows/checks.yml`.
- Playbooks in `docs/workflow/`: deployment (23), the Klein handoff (21), the 2026-09-21 Klein group record (15), live findings (14), and two-body anatomy research (22).
- Shipped defaults in `salad_studio/studio-metadata.json`; face prompts in `face_prompt_pack.json`; the local model cache in `model_catalog.py`.

Absent, and not to be fabricated: customers, testimonials, benchmarks, pricing, licensing claims, and marketing copy. The art tree itself lives outside this repo.

## Product Principles

1. One press, one correct request. Validation and dispatch share the same gate, and a refusal explains itself in words rather than greying the button out.
2. The local machine is the trust boundary. Loopback binding, a per-run token, and keys in local files are the access model.
3. Never surprise the operator's infrastructure. The queue starts nothing and stops only containers it can prove the app started.
4. Every long wait is named. A boot wait, a provider check, and a refusal all say what they are waiting on.
5. The plate is the artifact. A render that cannot cut out still finishes with its plate and a note saying why.

## Accessibility & Inclusion

WCAG AA text contrast is enforced by `tests/test_theme.py`. The history strip and the tables have keyboard paths: arrows move, Home and End take the ends, Enter opens. No product-specific assistive-technology requirement has been stated beyond these.
