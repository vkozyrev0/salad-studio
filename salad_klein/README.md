# Salad Flux.2 Klein 9B custom group

Build files for a separate ComfyUI API container group, not the live
loganberry Flux.1-Dev recipe.

Read: [doc 23](../docs/workflow/23-salad-container-group-deployment.md)
(build and call the container) and
[doc 21](../docs/workflow/21-klein-image-handoff.md) (the Klein handoff).

The verified recipe is `prompt_snofs_distilled_v12.json`: the SNOFS distilled
v1.2 unet (not a LoRA), Qwen fp8 CLIP, flux2 VAE, euler, 4 steps, CFG 1,
832x1216, no LoRAs, and a 779-char four-section prompt. Acceptable at 2 of 7
seeds, so batch seeds and select. The only human-judged recipe
(`prompt_ledger.json` `verdicts`). Superseded: doc 15.

`prompt_catalog.json` lists the successful prompts;
`tests/test_klein_prompt_catalog.py` keeps it honest. Recipe module, from the
repo root:

```
python -m unittest discover -s tests -p "test_klein_recipes.py"
```

Container-side modules:

```
cd salad_klein && python -m unittest discover -p "test_*.py"   # 18 tests
```

Build and push both tags with doc 23 §1.2's `docker build` and `docker push`
lines. One Dockerfile makes both images, one per unet family;
`KLEIN_UNET_SET` decides what `prefetch.py` downloads on first boot, so one
container holds one family in VRAM. The live tags `...-prefetch6-klein` and
`...-prefetch6-snofs` are one per group; doc 21 §2 is the authority.
Build args, ports, entrypoint, contents, downloads, and staging are doc 23
§1.2 to §1.4.

Either tag also runs as a vast.ai instance image. Current images instantiate
`Image Comparer (rgthree)` and `Power Lora Loader (rgthree)`; Convert expands
Power Lora to stock `LoraLoader`.

On first boot, `prefetch.py` inflates a sidecar or misnamed zip. Otherwise it
downloads the tag's unet set, CLIP, and VAE in parallel, then `exec`s
`comfyui-api`. The image stays the Salad runtime with no unet, CLIP, VAE, or
`RUN unzip` in it (doc 23 section 1.3).

This machine caches the same files in gitignored `art/model-cache/hf/`; Salad
never sees it:

```
python model_catalog.py fetch-klein --stage
```

Do not `FROM` a `flux1dev` Salad tag. Do not POST this graph at loganberry.
`HF_TOKEN` and the Civitai token stay in `~/.config/`,
`salad_studio/studio-tokens.json`, and the Salad environment, not in git.
