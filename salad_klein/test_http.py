"""Local HTTP smoke of the Klein ComfyUI-API wrapper (no GPU required).

Starts the image with MANIFEST/WARMUP unset so it does not pull 18 GB.
Probes 127.0.0.1:PORT /health and /ready. Wrapper may still fail later
when Comfy CUDA is missing; a 200 on /health is the HTTP check.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
import urllib.error
import urllib.request

IMAGE = "vkozyrev0/eldermark-klein:comfy0.35-api1.19.2-nowarm"
NAME = "eldermark-klein-http-test"


def curl_code(url: str, timeout: int = 5) -> int:
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return int(resp.status)
    except urllib.error.HTTPError as e:
        return int(e.code)
    except Exception:
        return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--image", default=IMAGE)
    p.add_argument("--port", type=int, default=3000)
    p.add_argument("--seconds", type=int, default=90)
    args = p.parse_args()
    subprocess.run(["docker", "rm", "-f", NAME], capture_output=True)
    run = subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            NAME,
            "-p",
            f"{args.port}:3000",
            "-e",
            "MANIFEST=",
            "-e",
            "WARMUP_PROMPT_FILE=",
            "-e",
            "HOST=0.0.0.0",
            "-e",
            "PORT=3000",
            "-e",
            "STARTUP_CHECK_MAX_TRIES=8",
            "-e",
            "STARTUP_CHECK_INTERVAL_S=2",
            args.image,
        ],
        capture_output=True,
        text=True,
    )
    if run.returncode != 0:
        print("docker run failed", run.stderr)
        return 1
    health = ready = 0
    deadline = time.time() + args.seconds
    try:
        while time.time() < deadline:
            health = curl_code(f"http://127.0.0.1:{args.port}/health")
            ready = curl_code(f"http://127.0.0.1:{args.port}/ready")
            print(f"health={health} ready={ready}")
            if health == 200:
                print("OK wrapper HTTP /health 200")
                return 0
            time.sleep(3)
        print(f"no /health 200 in {args.seconds}s last health={health} ready={ready}")
        logs = subprocess.run(
            ["docker", "logs", "--tail", "120", NAME],
            capture_output=True,
            text=True,
        )
        blob = (logs.stdout or "") + (logs.stderr or "")
        print(blob[-3500:])
        if "Starting ComfyUI API" in blob and "Found no NVIDIA driver" in blob:
            print("OK wrapper booted; Comfy CUDA missing on this host (expected)")
            return 0
        print("FAIL wrapper HTTP never answered and logs are not the no-GPU path")
        return 1
    finally:
        subprocess.run(["docker", "rm", "-f", NAME], capture_output=True)


if __name__ == "__main__":
    sys.exit(main())
