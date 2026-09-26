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
[`test_klein_prompt_catalog.py`](../salad_studio/test_klein_prompt_catalog.py).
Tests for the verified recipe: `python -m unittest discover -s salad_studio -p "test_klein_recipes.py"`
from the repo root (the whole suite runs the same way with `-p "test_*.py"`).

```
git clone --depth 1 https://github.com/rgthree/rgthree-comfy.git salad_klein/custom_nodes/rgthree-comfy
docker build -t vkozyrev0/eldermark-klein:comfy0.35-api1.19.2-prefetch6-klein salad_klein
docker push vkozyrev0/eldermark-klein:comfy0.35-api1.19.2-prefetch6-klein
```

**The live image tags are `prefetch6-klein` (base + distilled) and
`prefetch6-snofs` (the SNOFS cut)**, one per group, per
[`docs/workflow/21-klein-image-handoff.md`](../docs/workflow/21-klein-image-handoff.md)
§2, which is the entry point for this work and the authority on the tags. The
older `prefetch3`/`prefetch4` tags below are kept as the record of how the
rgthree COPY was introduced. Prefetch stays weights-only —
do not `git clone` on Salad. On the current images, `/prompt` can instantiate
`Image Comparer (rgthree)` and `Power Lora Loader (rgthree)`. Studio
**Convert still expands** Power Lora → stock `LoraLoader` so an older replica
can run the graph. Studio has no comparer slider; `SaveImage`
is the plate.

The image stays the Salad runtime (~12 GB). Do **not** COPY the unet/CLIP/VAE
and do **not** `RUN unzip` in the Dockerfile. That writes uncompressed
tensors into an image layer (~30 GB). Zip is transport only.

First boot `prefetch.py` (ENTRYPOINT, not a build step):

1. If a `.zip` sits next to the Comfy path, or a zip was misnamed
   `*.safetensors`, inflate it to the real `.safetensors` filename.
2. Otherwise download **both** Klein unets, the SNOFS distilled v1.2 fp8
   UNET, CLIP, and VAE **in parallel**.
3. `exec` `comfyui-api`. Comfy only ever sees raw `.safetensors`.

This machine can still cache the same files in gitignored `art/model-cache/hf/`:

```
python model_catalog.py fetch-klein --stage
```

Salad never sees that cache. Zip/unzip is only useful here for *local* disk,
not for shrinking the Docker image.

Do not `FROM` a `flux1dev` Salad tag. Do not POST this graph at loganberry.
HF_TOKEN / Civitai token stay in `~/.config/` and Salad env, not in git.
