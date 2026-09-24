"""Download both gated Klein unets locally with the Studio HF token.

Does not print the token. Dest: ~/.cache/eldermark-klein-hf/
"""
from __future__ import annotations

import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
for p in (str(TOOLS), str(TOOLS / "salad_studio")):
    if p not in sys.path:
        sys.path.insert(0, p)

os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

from huggingface_hub import hf_hub_download  # noqa: E402

DEST = Path.home() / ".cache" / "eldermark-klein-hf"
JOBS = (
    {
        "repo": "black-forest-labs/FLUX.2-klein-base-9b-fp8",
        "file": "flux-2-klein-base-9b-fp8.safetensors",
    },
    {
        "repo": "black-forest-labs/FLUX.2-klein-9b-fp8",
        "file": "flux-2-klein-9b-fp8.safetensors",
    },
)


def _token() -> str:
    from salad_studio import tokens

    return (tokens.read_token("huggingface") or "").strip()


def _one(job: dict[str, str], token: str) -> str:
    name = Path(job["file"]).name
    dest = DEST / name
    if dest.is_file() and dest.stat().st_size > 1_000_000_000:
        return f"HAVE {name} {dest.stat().st_size / 1e9:.2f} GB"
    print(f"START {name} repo={job['repo']} token=set dest={dest}", flush=True)
    tmp = dest.parent / (name + ".hfdir")
    tmp.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    got = hf_hub_download(
        repo_id=job["repo"],
        filename=job["file"],
        local_dir=str(tmp),
        token=token,
    )
    os.replace(got, dest)
    dt = time.monotonic() - t0
    size = dest.stat().st_size
    return f"DONE {name} {size / 1e9:.2f} GB in {dt / 60:.1f} min"


def main() -> int:
    token = _token()
    if not token:
        print("FAIL no Hugging Face token in studio-tokens.json / ~/.config/huggingface/token")
        return 1
    if not token.startswith("hf_"):
        print("FAIL token does not look like hf_…")
        return 1
    DEST.mkdir(parents=True, exist_ok=True)
    print(f"local Klein download dir={DEST} token=set jobs={len(JOBS)}", flush=True)
    failed = 0
    with ThreadPoolExecutor(max_workers=2) as pool:
        futs = {pool.submit(_one, job, token): job for job in JOBS}
        for fut, job in futs.items():
            name = Path(job["file"]).name
            try:
                print(fut.result(), flush=True)
            except Exception as exc:
                print(f"FAILED {name}: {type(exc).__name__}: {exc}", flush=True)
                failed += 1
    if failed:
        print(f"aborted — {failed}/{len(JOBS)} download(s) failed")
        return 1
    print("ok both unets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
