#!/usr/bin/env python3
"""Ensure Klein unet / CLIP / VAE exist as raw .safetensors, then exec the API.

Unzip happens here at *container start*, not as a Dockerfile RUN (that would
bake 17 GB into the image). Comfy never loads a .zip.

Salad logs have no TTY, so Hugging Face tqdm bars are silent. We print one
progress line per file about every PROGRESS_EVERY_S seconds.
"""
from __future__ import annotations

import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# Force HTTP+tqdm path so we can hook byte counts (xet is quiet in logs).
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "0")

from huggingface_hub import hf_hub_download  # noqa: E402


def hf_token() -> str:
    """Salad sets HF_TOKEN; huggingface_hub also reads HUGGING_FACE_HUB_TOKEN."""
    return (
        os.environ.get("HF_TOKEN")
        or os.environ.get("HUGGING_FACE_HUB_TOKEN")
        or ""
    ).strip()

from weights_zip import ensure_safetensors  # noqa: E402

PROGRESS_EVERY_S = 60.0

# One unet per image, selected at build/deploy time via KLEIN_UNET_SET.
#
# Why the split exists: a 4090/3090 has 24 GB of VRAM and the Qwen text encoder
# alone is 8.66 GB, so ONE ~9 GB unet plus the encoder is ~17.7 GB, most of the
# card. Two unets is ~27 GB and cannot fit, at which point Comfy streams weights
# from host memory instead of holding them resident:
#
#   Model Flux2 prepared for dynamic VRAM loading. 8658MB Staged. 112 patches
#   attached. Force pre-loaded 80 weights      (measured 2026-09-22)
#
# and a render that should take seconds takes 239-576 s. That is the real cost of
# shipping every unet in one image and then alternating between them: a Klein-base
# import after a SNOFS plate forces the SNOFS unet out and the base unet back in.
#
#   KLEIN_UNET_SET=base       flux-2-klein-base-9b-fp8      (Civitai imports)
#   KLEIN_UNET_SET=distilled  flux-2-klein-9b-fp8           (4-step cut)
#   KLEIN_UNET_SET=snofs      SNOFS distilled v1.2          (two-body plates)
#   KLEIN_UNET_SET=snofs,base both, for a group that must serve both
#   unset / "all"             all three, the historical behaviour, the default
#
# The text encoder and VAE are needed by every graph, so they are always fetched.
UNET_JOBS = {
    "base": {
        "repo": "black-forest-labs/FLUX.2-klein-base-9b-fp8",
        "file": "flux-2-klein-base-9b-fp8.safetensors",
        "dest": "/opt/ComfyUI/models/diffusion_models/flux-2-klein-base-9b-fp8.safetensors",
    },
    "distilled": {
        "repo": "black-forest-labs/FLUX.2-klein-9b-fp8",
        "file": "flux-2-klein-9b-fp8.safetensors",
        "dest": "/opt/ComfyUI/models/diffusion_models/flux-2-klein-9b-fp8.safetensors",
    },
    # Same bytes as Civitai model version 2786085
    # (snofsSexNudesAndOther_distilledV12KleinFp8.safetensors, sha256
    # 8f14f15040c2e041de87058e29317663338bb6b77054d224c1bfccffcfeb1e35).
    # Resolve URL:
    # https://huggingface.co/edwixx/Flux2Klein9B_SNOFS/resolve/main/snofsSexNudesAndOtherFunStuff_distilledV12Fp8.safetensors
    "snofs": {
        "repo": "edwixx/Flux2Klein9B_SNOFS",
        "file": "snofsSexNudesAndOtherFunStuff_distilledV12Fp8.safetensors",
        "dest": (
            "/opt/ComfyUI/models/diffusion_models/"
            "snofsSexNudesAndOther_distilledV12KleinFp8.safetensors"
        ),
    },
}

SHARED_JOBS = (
    {
        "repo": "Comfy-Org/flux2-klein-9B",
        "file": "split_files/text_encoders/qwen_3_8b_fp8mixed.safetensors",
        "dest": "/opt/ComfyUI/models/text_encoders/qwen_3_8b_fp8mixed.safetensors",
    },
    {
        "repo": "Comfy-Org/flux2-dev",
        "file": "split_files/vae/flux2-vae.safetensors",
        "dest": "/opt/ComfyUI/models/vae/flux2-vae.safetensors",
    },
)


def selected_unets(raw: str | None = None) -> tuple[str, ...]:
    """Which unet jobs to fetch. Unknown names fall back to every unet."""
    text = (raw if raw is not None else os.environ.get("KLEIN_UNET_SET", "")).strip().lower()
    if not text or text in ("all", "*"):
        return tuple(UNET_JOBS)
    wanted = tuple(name for name in (p.strip() for p in text.split(",")) if name in UNET_JOBS)
    if not wanted:
        print(f"prefetch: KLEIN_UNET_SET={text!r} names no known unet, fetching all", flush=True)
        return tuple(UNET_JOBS)
    return wanted


def selected_jobs(raw: str | None = None) -> tuple[dict[str, str], ...]:
    """Every job to fetch for `raw` (default: KLEIN_UNET_SET, then all unets)."""
    return tuple(UNET_JOBS[name] for name in selected_unets(raw)) + tuple(SHARED_JOBS)


_ACTIVE_UNETS = selected_unets()
JOBS = selected_jobs()


def _have(path: str) -> bool:
    try:
        return os.path.isfile(path) and os.path.getsize(path) > 1_000_000
    except OSError:
        return False


def _label(job: dict[str, str]) -> str:
    return Path(job["dest"]).name


class MinuteTqdm:
    """tqdm stand-in: newline progress about once a minute (Salad-log friendly)."""

    def __init__(self, *args, **kwargs):
        self.desc = str(kwargs.get("desc") or (args[0] if args else "") or "")
        self.total = float(kwargs.get("total") or 0) or 0.0
        self.n = float(kwargs.get("initial") or 0) or 0.0
        self._lock = threading.Lock()
        self._t0 = time.monotonic()
        self._last_emit = 0.0
        self._emitted_start = False
        self.disable = False

    def _line(self, tag: str) -> None:
        elapsed = max(time.monotonic() - self._t0, 0.001)
        mb = self.n / 1e6
        tot = self.total / 1e6 if self.total else 0.0
        pct = (100.0 * self.n / self.total) if self.total else 0.0
        rate = (self.n / elapsed) / 1e6
        if tot:
            msg = (
                f"prefetch {self.desc or tag} {pct:.0f}% "
                f"{mb:.0f}/{tot:.0f} MB {rate:.1f} MB/s"
            )
        else:
            msg = f"prefetch {self.desc or tag} {mb:.0f} MB {rate:.1f} MB/s"
        print(msg, flush=True)

    def update(self, n: float = 1) -> None:
        now = time.monotonic()
        with self._lock:
            self.n += float(n)
            if not self._emitted_start:
                self._emitted_start = True
                self._last_emit = now
                self._line("start")
                return
            if now - self._last_emit >= PROGRESS_EVERY_S:
                self._last_emit = now
                self._line("tick")

    def close(self) -> None:
        with self._lock:
            self._line("done")

    def __enter__(self) -> MinuteTqdm:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def set_postfix(self, *args, **kwargs) -> None:
        return None

    def set_description(self, desc: str | None = None, **kwargs) -> None:
        if desc:
            self.desc = str(desc)

    def refresh(self) -> None:
        return None


def _install_progress() -> None:
    try:
        from huggingface_hub.utils import enable_progress_bars
        from huggingface_hub.utils import tqdm as hf_tqdm_mod

        enable_progress_bars()
        hf_tqdm_mod.tqdm = MinuteTqdm  # type: ignore[misc, assignment]
    except Exception as exc:
        print(f"prefetch progress hook skipped: {exc}", flush=True)


def _fetch(job: dict[str, str]) -> str:
    dest = job["dest"]
    name = _label(job)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    zst = ensure_safetensors(dest)
    if zst != "missing":
        print(f"prefetch {name} {zst}", flush=True)
        return f"{zst} {dest}"
    if _have(dest):
        print(f"prefetch {name} have", flush=True)
        return f"have {dest}"
    tok = hf_token()
    print(
        f"prefetch {name} start repo={job['repo']} token={'set' if tok else 'MISSING'}",
        flush=True,
    )
    tmp_dir = dest + ".hfdir"
    os.makedirs(tmp_dir, exist_ok=True)
    t0 = time.monotonic()
    kwargs = {
        "repo_id": job["repo"],
        "filename": job["file"],
        "local_dir": tmp_dir,
    }
    if tok:
        kwargs["token"] = tok
    got = hf_hub_download(**kwargs)
    os.replace(got, dest)
    dt = time.monotonic() - t0
    size = os.path.getsize(dest)
    print(
        f"prefetch {name} done {size / 1e9:.2f} GB in {dt / 60:.1f} min",
        flush=True,
    )
    return f"ok {dest}"


def main(argv: list[str]) -> int:
    _install_progress()
    print(
        f"klein prefetch: {len(JOBS)} files in parallel "
        f"(progress every {int(PROGRESS_EVERY_S)}s) "
        f"unet_set={','.join(_ACTIVE_UNETS)}",
        flush=True,
    )
    failed: list[str] = []
    with ThreadPoolExecutor(max_workers=len(JOBS)) as pool:
        futs = {pool.submit(_fetch, job): job for job in JOBS}
        for fut, job in futs.items():
            name = _label(job)
            try:
                print(fut.result(), flush=True)
            except Exception as exc:
                print(f"prefetch {name} FAILED: {exc}", flush=True)
                failed.append(name)
    if failed:
        print(
            "prefetch aborted, missing "
            + ", ".join(failed)
            + " (will not start Comfy)",
            flush=True,
        )
        return 1
    if not argv:
        return 0
    os.execvp(argv[0], argv)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
