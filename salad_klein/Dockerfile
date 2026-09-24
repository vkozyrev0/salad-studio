# Flux.2 Klein 9B-Base custom image for Salad ComfyUI API.
# Do NOT start FROM a flux1dev / flux1schnell recipe image — those bake
# Flux.1 into VRAM and OOMs a 24 GB 4090 next to Klein.
#
# Secrets (HF_TOKEN, CIVITAI_API_TOKEN) are runtime env, never COPY'd.
FROM ghcr.io/saladtechnologies/comfyui-api:comfy0.35.0-api1.19.2-torch2.13.0-cuda13.0-runtime

# First-boot downloads ~10 GB+ of Klein weights; give the readiness
# probe time before Salad kills the replica.
ENV STARTUP_CHECK_MAX_TRIES=120
ENV MANIFEST=manifest.yaml
# Which unet(s) this container boots with. Bake it per image at build time, so a
# group only downloads what it will ever render (the boot fetch is ~15 min for the
# full set), and a group env can still override it at deploy time:
#
#   docker build --build-arg KLEIN_UNET_SET=snofs \
#     -t vkozyrev0/eldermark-klein:comfy0.35-api1.19.2-prefetch6-snofs salad_klein
#   docker build --build-arg KLEIN_UNET_SET=base,distilled \
#     -t vkozyrev0/eldermark-klein:comfy0.35-api1.19.2-prefetch6-klein salad_klein
#
# Values: base | distilled | snofs | "snofs,base" | all (default). A 24 GB card
# holds only ONE ~9 GB unet beside the 8.66 GB text encoder (~17.7 GB), and
# graphs that need different unets must therefore never share a group — Comfy
# then streams weights from host memory and a seconds-long render takes 240-576 s
# (measured 2026-09-22). prefetch.py reads this at start and logs the set chosen.
ARG KLEIN_UNET_SET=all
ENV KLEIN_UNET_SET=${KLEIN_UNET_SET}
# Do not bake WARMUP_PROMPT_FILE. Logs (2026-09-19 01:08:40): Comfy
# reached "GUI go to http://*:8188" then Instance Exited:1 in ~4s —
# too fast for a Klein render; wrapper dies on warmup parse/submit.
# /ready should follow Comfy /object_info, not a Klein graph.
# Official CMD uses --listen *; bind 0.0.0.0 so 8188 is reachable.
ENV CMD="comfy --workspace /opt/ComfyUI launch -- --listen 0.0.0.0 --port 8188"
# Runtime image ships huggingface_hub 1.16.1; its `hf` CLI exits 0
# (typer Exit) so the wrapper falls back to anonymous HTTP → 401 on
# the gated BFL Klein unet. Upgrade so `hf download` honors HF_TOKEN.
RUN pip install --no-cache-dir -U "huggingface_hub>=0.34.0" \
    && pip install --no-cache-dir "click==8.1.8"

# Do not COPY the ~17 GB Klein weights and do not RUN unzip here — that
# would still bake uncompressed tensors into an image layer. prefetch.py
# inflates a sidecar/misnamed zip (if any) then downloads in parallel.
COPY weights_zip.py /weights_zip.py
COPY prefetch.py /prefetch.py
COPY manifest.yaml .
# rgthree-comfy (Image Comparer + Power Lora Loader). Clone locally:
#   git clone --depth 1 https://github.com/rgthree/rgthree-comfy.git custom_nodes/rgthree-comfy
# Do not git clone at Salad boot. Tiny source tree — not Klein weights.
COPY custom_nodes/rgthree-comfy /opt/ComfyUI/custom_nodes/rgthree-comfy
ENTRYPOINT ["python", "/prefetch.py"]
CMD ["./comfyui-api"]
