# Salad Flux.2 Klein 9B custom group

Build files for a **separate** ComfyUI API container group. This is not
the live loganberry Flux.1-Dev recipe.

**The consolidated reference for building this image and calling the container
(both APIs, group creation, portal fields, probes) is
[`docs/workflow/23-salad-container-group-deployment.md`](../docs/workflow/23-salad-container-group-deployment.md).**
Read it first; this file is the build-context short form.

Full steps: [`docs/workflow/15-salad-flux2-klein-group.md`](../docs/workflow/15-salad-flux2-klein-group.md)

**The verified plate recipe is `prompt_snofs_distilled_v12.json`**. The
**SNOFS distilled v1.2** unet (SNOFS is the unet on this group, not a LoRA),
Qwen fp8 CLIP, flux2 VAE, euler, **4 steps**, **CFG 1**, 832×1216, **no LoRAs**,
and a **779-char** four-section prompt. It is the only recipe a human has judged
(`prompt_ledger.json` → `verdicts`), and it produced an acceptable plate at
**2 of 7 seeds**, so batch seeds and select, rather than rewording.
**Start with [`docs/workflow/21-klein-image-handoff.md`](../docs/workflow/21-klein-image-handoff.md)**;
it is the single entry point for this work and it supersedes what this paragraph
used to say.

Superseded (kept as the record of what was tried, no human verdict covers them):
`prompt_snofs_distilled_anatomy.json` (euler) and
`prompt_snofs_distilled_anatomy_resms.json` (res_multistep). The older 4-LoRA
stack with 5,049-char sectioned prompts. The claim that "the prompt architecture
is the quality lever" came from that era and is **not** what the measurements
show: a short prompt on the same graph was one confounded A/B, while the
controlled test that mattered (4 LoRAs vs none) found **both bad**.

Catalog of successful prompts: [`prompt_catalog.json`](prompt_catalog.json),
kept honest by
[`test_klein_prompt_catalog.py`](../tests/test_klein_prompt_catalog.py).
Tests for the verified recipe: `python -m unittest discover -s tests -p "test_klein_recipes.py"`
from the repo root (the whole suite runs the same way with `-p "test_*.py"`, and
this directory's own two test modules with
`cd salad_klein && python -m unittest discover -p "test_*.py"`).

Build and push both tags (the `rgthree-comfy` clone, the two `docker build` / `docker push` lines): [doc 23 §1.2](../docs/workflow/23-salad-container-group-deployment.md).

**Two images, one per unet family**, one Dockerfile: `KLEIN_UNET_SET` is the only difference, and it
decides what `prefetch.py` downloads on the first boot, so one container holds one unet family in
VRAM. Both live tags (`…-prefetch6-klein` / `…-prefetch6-snofs`) are one per group, per
[doc 21 §2](../docs/workflow/21-klein-image-handoff.md), the entry point for this work and the
authority on the tags; build args, ports, entrypoint, what is inside, what each first boot fetches
and the local weight staging are [doc 23 §1.2/§1.3/§1.4](../docs/workflow/23-salad-container-group-deployment.md).

Either tag also runs as a **vast.ai instance** image (the app's Config page renders on one). The older
`prefetch3`/`prefetch4` tags record how the rgthree COPY was introduced; prefetch stays weights-only
(no `git clone` on Salad). On the current images `/prompt` can instantiate `Image Comparer (rgthree)`
and `Power Lora Loader (rgthree)`; Studio **Convert still expands** Power Lora → stock `LoraLoader`.

First boot `prefetch.py` inflates a sidecar or misnamed zip, else downloads the tag's unet set + CLIP + VAE
**in parallel**, then `exec`s `comfyui-api`; the image stays the Salad runtime with no unet/CLIP/VAE or `RUN unzip` in it — [doc 23 §1.3](../docs/workflow/23-salad-container-group-deployment.md).

This machine can still cache the same files in gitignored `art/model-cache/hf/` (Salad never sees that cache):

```
python model_catalog.py fetch-klein --stage
```

Do not `FROM` a `flux1dev` Salad tag. Do not POST this graph at loganberry.
HF_TOKEN / Civitai token stay in `~/.config/` and Salad env, not in git.
