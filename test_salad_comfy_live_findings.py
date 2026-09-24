#!/usr/bin/env python3
"""Structural checks for the live Salad Comfy findings doc.

Drives the shipped markdown (docs/workflow/14-salad-comfy-live-findings.md)
and freeze pointers, not a re-implementation of Salad HTTP.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent  # this tool's root; salad_klein/ sits beside it
# The Eldermark repo (art tree, game docs, shared skills) lives outside this tool.
# ELDERMARK_REPO overrides the default when it is checked out elsewhere.
ELDERMARK = Path(
    os.environ.get("ELDERMARK_REPO", r"C:\Users\vkozy\repos\lifesim-design")
)
DOC = HERE / "docs" / "workflow" / "14-salad-comfy-live-findings.md"
INDEX = ELDERMARK / "docs" / "00-INDEX.md"
RANKING = ELDERMARK / "docs" / "workflow" / "13-gpu-host-catalog-plans.md"
CATALOG = ELDERMARK / "docs" / "systems" / "02-image-catalog.md"
KLEIN_DOC = HERE / "docs" / "workflow" / "15-salad-flux2-klein-group.md"
KLEIN_DIR = HERE / "salad_klein"
PAUSE = ELDERMARK / "art" / "catalog" / "face" / "salad_PAUSE.txt"
GENERATOR = HERE / "salad_catalog_faces.py"
FAL_REGEN = ELDERMARK / "src" / "tools" / "regen_faces.py"
SKILL = ELDERMARK / ".claude" / "skills" / "catalog-faces" / "SKILL.md"
FACE_PROMPT_SKILL = ELDERMARK / ".claude" / "skills" / "face-prompt" / "SKILL.md"

# Phrases that must appear in the findings doc (verification plan §1–§3).
REQUIRED_SNIPPETS = (
    "1.10",
    "/prompt",
    "/ready",
    "flux1-dev-fp8",
    "524",
    "100 s",
    "OOM",
    "24 GB",
    "CLIPVisionLoader",
    "IP-Adapter",
    "PuLID",
    "Krea 2",
    "Dreamshaper",
    "SD 3.5",
    "SDXL",
    "796382",
    "978314",
    "618692",
    "691639",
    "2433139",
    "573152",
    "2155386",
    "768",
    "1408",
    "phenotype",
    "insertion",
    "salad_probe_klein_event",
    "salad_PAUSE.txt",
    "salad_catalog_faces.py --generate",
    "Do not re-download",
    "562604",
    "Civitai token",
    "IMAGE_SAFETY",
    "2322332",
    "2612548",
    "2334190",
    "2625692",
    "2763568",
    "2760271",
    "2725918",
    "2748101",
    "EmptyFlux2LatentImage",
    "Flux2Scheduler",
    "qwen_3_8b_fp8mixed",
    "UNETLoader",
)


def main() -> int:
    assert DOC.is_file(), f"missing findings artifact {DOC}"
    text = DOC.read_text(encoding="utf-8")
    missing = [s for s in REQUIRED_SNIPPETS if s not in text]
    assert not missing, f"findings doc missing required facts: {missing}"

    low = text.lower()
    assert "frozen" in low or "freeze" in low
    assert "tbd" in low
    assert "do not run `python salad_catalog_faces.py --generate`" in low or (
        "do **not** run `python salad_catalog_faces.py --generate`" in low
    )
    assert "lustify" in low
    assert "ultrarealphoto" in low or "796382" in text
    assert "golden hour" in low
    assert "sean archer" in low or "1632416" in text
    assert "pony" in low
    assert "wai-illustrious" in low or "827184" in text
    events_head = text.find("### Events")
    assert events_head != -1, "missing ### Events heading"
    events_chunk = text[events_head : events_head + 800].lower()
    assert (
        "not probed" in events_chunk
        or "salad_probe_klein_event" in events_chunk
        or "klein 9b" in events_chunk
    ), "events section must record unset or Klein probes"

    assert INDEX.is_file()
    index = INDEX.read_text(encoding="utf-8")
    # Docs 14 and 15 moved into this repo with the Studio, so the Eldermark index
    # no longer lists them by name; it points here instead. Assert that pointer,
    # and that both docs exist here (they are read above and below).
    assert "salad-studio" in index, "Eldermark index must point at the Salad Studio repo"
    assert DOC.is_file() and KLEIN_DOC.is_file()

    assert KLEIN_DOC.is_file(), f"missing Klein howto {KLEIN_DOC}"
    klein = KLEIN_DOC.read_text(encoding="utf-8")
    for s in (
        "comfy0.35.0-api1.19.2",
        "cuda13.0-runtime",
        "EmptyFlux2LatentImage",
        "Flux2Scheduler",
        "qwen_3_8b_fp8mixed",
        "2322332",
        "2612548",
        "Do **not** POST a Klein graph at loganberry",
        "flux1dev",
        "flux2-klein",
        # Live gateways (profiles.py owns these two; persimmon is gone).
        "apple-gadogado-5d0vs4l8x0j51hwy.salad.cloud",
        "beet-ginger-cdz8ko9ehhmh4703.salad.cloud",
        "vkozyrev0/eldermark-klein:comfy0.35-api1.19.2",
        "life-sim",
        "docker build",
        "docker push",
        # Two-body plate recipe (SNOFS distilled + anatomy stack).
        "prompt_snofs_distilled_anatomy.json",
        "prompt_snofs_distilled_anatomy_resms.json",
        "REPLACE_THIS_POSE",
        "snofsSexNudesAndOther_distilledV12KleinFp8.safetensors",
        "snofsSexNudesAndOther_distilledV12KleinFp8",
        "2960556",
        "2625692",
        "2790993",
        "2615554",
        "2624854",
        "2627022",
        "_meta",
        "Base 9B is not the better cut",
        "missionary / doggystyle / cowgirl",
    ):
        assert s in klein, f"Klein howto missing {s!r}"
    dockerfile = (KLEIN_DIR / "Dockerfile").read_text(encoding="utf-8")
    from_lines = [
        ln for ln in dockerfile.splitlines() if ln.strip().upper().startswith("FROM ")
    ]
    assert from_lines, "Dockerfile missing FROM"
    assert all("flux1dev" not in ln.lower() for ln in from_lines)
    assert "comfy0.35.0-api1.19.2-torch2.13.0-cuda13.0-runtime" in dockerfile
    assert "huggingface_hub" in dockerfile
    assert not any(
        ln.strip().startswith("ENV WARMUP_PROMPT_FILE=") for ln in dockerfile.splitlines()
    )
    assert "0.0.0.0" in dockerfile
    # The manifest stays weights-free on purpose (Salad's before_start pulls
    # one file at a time and the startup probe killed it), prefetch.py is what
    # names the weights, in parallel, at first boot.
    manifest = (KLEIN_DIR / "manifest.yaml").read_text(encoding="utf-8")
    assert "before_start: []" in manifest
    assert "after_start" not in manifest
    assert "safetensors" not in manifest, "weights must not be baked into the manifest"
    assert "2625692" not in manifest and "2763568" not in manifest
    prefetch = (KLEIN_DIR / "prefetch.py").read_text(encoding="utf-8")
    for s in (
        "flux-2-klein-base-9b-fp8.safetensors",
        "qwen_3_8b_fp8mixed.safetensors",
        "flux2-vae.safetensors",
        "/opt/ComfyUI/models/diffusion_models/",
        "/opt/ComfyUI/models/text_encoders/",
        "/opt/ComfyUI/models/vae/",
    ):
        assert s in prefetch, f"prefetch.py missing {s!r}"
    prompt = (KLEIN_DIR / "prompt_liked_style.json").read_text(encoding="utf-8")
    assert "EmptyFlux2LatentImage" in prompt
    assert "Flux2Scheduler" in prompt
    assert '"type": "flux2"' in prompt
    assert "832" in prompt and "1216" in prompt
    assert "ArsMJStyle, Impressionism" in prompt
    warmup = (KLEIN_DIR / "warmup_prompt.json").read_text(encoding="utf-8")
    assert "UNETLoader" in warmup and "SamplerCustomAdvanced" in warmup
    import re

    token_re = re.compile(r"hf_[A-Za-z0-9]{8,}")
    for blob in (dockerfile, manifest, prompt, warmup, klein):
        assert not token_re.search(blob), "HF token leaked into Klein recipe"

    ranking = RANKING.read_text(encoding="utf-8")
    assert "14-salad-comfy-live-findings.md" in ranking
    assert "no longer \u201cplans only\u201d" in ranking or "no longer" in ranking.lower()

    catalog = CATALOG.read_text(encoding="utf-8")
    assert "14-salad-comfy-live-findings.md" in catalog

    assert PAUSE.is_file(), "mass-gen pause sentinel missing"
    pause = PAUSE.read_text(encoding="utf-8")
    assert "14-salad-comfy-live-findings.md" in pause or "chosen model" in pause.lower()

    gen = GENERATOR.read_text(encoding="utf-8")
    assert "salad_PAUSE.txt" in gen
    assert "FROZEN" in gen or "PAUSE" in gen
    assert "--ignore-pause" in gen

    fal = FAL_REGEN.read_text(encoding="utf-8")
    assert "salad_PAUSE.txt" in fal
    assert "14-salad-comfy-live-findings.md" in fal
    assert "--ignore-pause" in fal
    assert "FROZEN" in fal

    skill = SKILL.read_text(encoding="utf-8")
    assert "14-salad-comfy-live-findings.md" in skill
    assert "salad_PAUSE.txt" in skill
    assert "Mass-gen freeze" in skill
    # Must not present --generate as the recommended daily session.
    assert "recommended daily session" not in skill.lower()

    fps = FACE_PROMPT_SKILL.read_text(encoding="utf-8")
    assert "14-salad-comfy-live-findings.md" in fps
    assert "salad_PAUSE.txt" in fps
    assert "--generate --limit 50" not in fps

    import subprocess

    # salad_catalog_faces.py imports paperdoll_mask and regen_faces, which stayed
    # in the Eldermark repo, so in this repo it is not standalone. Assert whichever
    # state holds: runnable here means the freeze must really be honoured;
    # otherwise the failure must be exactly that documented missing import, so this
    # check starts testing the real path the moment the gap is closed.
    probe = subprocess.run(
        [sys.executable, "-c", "import salad_catalog_faces"],
        cwd=str(HERE), capture_output=True, text=True,
    )
    if probe.returncode == 0:
        salad = subprocess.run(
            [sys.executable, str(GENERATOR), "--generate", "--limit", "1"],
            cwd=str(HERE),
            capture_output=True,
            text=True,
        )
        assert salad.returncode == 2, (
            f"salad_catalog_faces --generate must exit 2 while paused, got {salad.returncode}\n"
            f"{salad.stdout}\n{salad.stderr}"
        )
        assert "paused" in (salad.stdout + salad.stderr).lower()
    else:
        assert "paperdoll_mask" in probe.stderr or "regen_faces" in probe.stderr, (
            "salad_catalog_faces.py fails to import for an undocumented reason:\n"
            f"{probe.stderr}"
        )
        print(
            "  [skip] salad_catalog_faces.py is not standalone here "
            "(imports paperdoll_mask/regen_faces from Eldermark) - freeze checked "
            "via the source assertions above and via regen_faces below"
        )

    fal_run = subprocess.run(
        [sys.executable, str(FAL_REGEN), "--generate", "--limit", "1"],
        cwd=str(HERE),
        capture_output=True,
        text=True,
    )
    assert fal_run.returncode == 2, (
        f"regen_faces --generate must exit 2 while paused, got {fal_run.returncode}\n"
        f"{fal_run.stdout}\n{fal_run.stderr}"
    )
    assert "paused" in (fal_run.stdout + fal_run.stderr).lower()

    sys.path.insert(0, str(HERE))
    import salad_probe_klein as klein_probe  # noqa: E402

    src = (HERE / "salad_probe_klein.py").read_text(encoding="utf-8")
    assert "def _klein_body_prompt" in src
    assert "FACE_ON_BODY" in src
    body_jobs = 0
    for text, name, _w, _h, lora in klein_probe.jobs():
        if "_body_" not in name:
            continue
        body_jobs += 1
        low = text.lower()
        assert "head completely above the frame" not in low, name
        assert "out-of-frame head" not in low, name
        assert "#FF00FF" not in text, name
        assert "ArsMJStyle" in text, name
        assert "painted human face" in low, name
        assert "not headless" in low, name
        assert "paperdoll" not in low, name
        assert "not a doll" in low, name
        if "_infants_" in name:
            assert "standing figure" not in low, name
        assert lora is False, name
    assert body_jobs > 20, body_jobs

    print("ok", DOC.relative_to(HERE), "snippets", len(REQUIRED_SNIPPETS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
