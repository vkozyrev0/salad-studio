# Salad Flux.2 Klein 9B custom group

Build files for a separate ComfyUI API container group. This is not the live
loganberry Flux.1-Dev recipe. The reference for building this image and calling
the container is
[`docs/workflow/23-salad-container-group-deployment.md`](../docs/workflow/23-salad-container-group-deployment.md).
Read it first; this file is the build-context short form.
[`docs/workflow/21-klein-image-handoff.md`](../docs/workflow/21-klein-image-handoff.md)
is the entry point for the Klein handoff.

The verified recipe is `prompt_snofs_distilled_v12.json`: the SNOFS distilled
v1.2 unet (SNOFS is the unet on this group, not a LoRA), Qwen fp8 CLIP, flux2
VAE, euler, 4 steps, CFG 1, 832x1216, no LoRAs, and a 779-char four-section
prompt. It produced an acceptable plate at 2 of 7 seeds, so batch seeds and
select. It is the only recipe a human has judged (`prompt_ledger.json`
`verdicts`).

Superseded recipes, kept as the record: `prompt_snofs_distilled_anatomy.json`
(euler) and `prompt_snofs_distilled_anatomy_resms.json` (res_multistep), plus
the older 4-LoRA stack with 5,049-char prompts. The claim that prompt
architecture was the quality lever came from that era. The controlled test that
mattered, 4 LoRAs against none, found both bad.

`prompt_catalog.json` lists the successful prompts, and
`tests/test_klein_prompt_catalog.py` keeps it honest. The recipe module runs
from the repo root:

```
python -m unittest discover -s tests -p "test_klein_recipes.py"
```

The container-side modules run with:

```
cd salad_klein && python -m unittest discover -p "test_*.py"   # 18 tests
```

Build and push both tags with the two `docker build` and `docker push` lines in
doc 23 section 1.2. One Dockerfile makes both images, one per unet family.
`KLEIN_UNET_SET` is the only difference, and it decides what `prefetch.py`
downloads on the first boot, so one container holds one unet family in VRAM.
The live tags `...-prefetch6-klein` and `...-prefetch6-snofs` are one per group;
doc 21 section 2 is the authority. Build args, ports, entrypoint, contents,
first-boot downloads, and local weight staging are doc 23 sections 1.2 to 1.4.

Either tag also runs as a vast.ai instance image. The older `prefetch3` and
`prefetch4` tags record how the rgthree COPY was introduced; prefetch stays
weights-only, with no `git clone` on Salad. On the current images `/prompt` can
instantiate `Image Comparer (rgthree)` and `Power Lora Loader (rgthree)`. Studio
Convert still expands Power Lora to stock `LoraLoader`.

On the first boot, `prefetch.py` inflates a sidecar or misnamed zip. Otherwise
it downloads the tag's unet set, CLIP, and VAE in parallel, then `exec`s
`comfyui-api`. The image stays the Salad runtime with no unet, CLIP, VAE, or
`RUN unzip` in it (doc 23 section 1.3).

This machine can cache the same files in gitignored `art/model-cache/hf/`.
Salad never sees that cache.

```
python model_catalog.py fetch-klein --stage
```

Do not `FROM` a `flux1dev` Salad tag. Do not POST this graph at loganberry.
`HF_TOKEN` and the Civitai token stay in `~/.config/` and the Salad
environment, not in git.
