"""Klein image stays small: parallel prefetch, no baked safetensors."""
from __future__ import annotations

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from weights_zip import ensure_safetensors, is_zip_file, unzip_safetensors, zip_safetensors  # noqa: E402


class ImageStaysSmall(unittest.TestCase):
    def test_dockerfile_does_not_copy_weights(self) -> None:
        text = (HERE / "Dockerfile").read_text(encoding="utf-8")
        self.assertNotIn(".safetensors", text)
        self.assertIn("prefetch.py", text)
        self.assertIn("ENTRYPOINT", text)
        self.assertIn("rgthree-comfy", text)
        self.assertIn("COPY custom_nodes/rgthree-comfy /opt/ComfyUI/custom_nodes/rgthree-comfy", text)
        self.assertNotIn("RUN git clone", text)

    def test_prefetch_does_not_clone_rgthree(self) -> None:
        src = (HERE / "prefetch.py").read_text(encoding="utf-8")
        self.assertNotIn("rgthree", src.lower())
        self.assertNotIn("git clone", src)

    def test_manifest_has_no_before_start_urls(self) -> None:
        text = (HERE / "manifest.yaml").read_text(encoding="utf-8")
        self.assertNotIn("huggingface.co", text)
        self.assertIn("before_start: []", text)

    def test_prefetch_pulls_jobs_in_parallel(self) -> None:
        src = (HERE / "prefetch.py").read_text(encoding="utf-8")
        self.assertIn("ThreadPoolExecutor", src)
        self.assertIn("max_workers=len(JOBS)", src)
        self.assertIn("flux-2-klein-base-9b-fp8.safetensors", src)
        self.assertIn("flux-2-klein-9b-fp8.safetensors", src)
        self.assertIn("FLUX.2-klein-9b-fp8", src)
        self.assertIn("edwixx/Flux2Klein9B_SNOFS", src)
        self.assertIn(
            "https://huggingface.co/edwixx/Flux2Klein9B_SNOFS/resolve/main/"
            "snofsSexNudesAndOtherFunStuff_distilledV12Fp8.safetensors",
            src,
        )
        self.assertIn("snofsSexNudesAndOther_distilledV12KleinFp8.safetensors", src)
        self.assertIn("token=", src)
        self.assertIn("def hf_token", src)
        self.assertIn("qwen_3_8b_fp8mixed.safetensors", src)
        self.assertIn("flux2-vae.safetensors", src)
        self.assertIn("os.execvp", src)
        self.assertIn("prefetch aborted", src)
        self.assertIn("FAILED", src)
        self.assertIn("will not start Comfy", src)
        self.assertIn("ensure_safetensors", src)
        self.assertIn("PROGRESS_EVERY_S", src)
        self.assertIn("MinuteTqdm", src)
        docker = (HERE / "Dockerfile").read_text(encoding="utf-8")
        run_lines = [
            ln.strip()
            for ln in docker.splitlines()
            if ln.strip().startswith("RUN ")
        ]
        self.assertTrue(any("huggingface_hub" in ln for ln in run_lines))
        self.assertFalse(any("unzip" in ln.lower() for ln in run_lines))
        self.assertFalse(any("prefetch" in ln.lower() for ln in run_lines))


class TokenIsPassed(unittest.TestCase):
    def test_fetch_passes_hf_token_kwarg(self) -> None:
        import os
        from unittest.mock import patch

        import prefetch as pf

        calls: list[dict] = []

        def fake_dl(**kwargs):
            calls.append(kwargs)
            dest_dir = Path(kwargs["local_dir"])
            dest_dir.mkdir(parents=True, exist_ok=True)
            path = dest_dir / Path(kwargs["filename"]).name
            path.write_bytes(b"x" * 64)
            return str(path)

        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "diffusion_models" / "flux-2-klein-9b-fp8.safetensors"
            job = {
                "repo": "black-forest-labs/FLUX.2-klein-9b-fp8",
                "file": "flux-2-klein-9b-fp8.safetensors",
                "dest": str(dest),
            }
            env = {k: v for k, v in os.environ.items() if k not in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN")}
            env["HF_TOKEN"] = "hf_testtoken_not_real"
            with patch.dict(os.environ, env, clear=True):
                with patch.object(pf, "hf_hub_download", side_effect=fake_dl):
                    with patch.object(pf, "_have", return_value=False):
                        with patch.object(pf, "ensure_safetensors", return_value="missing"):
                            pf._fetch(job)
        self.assertTrue(calls)
        self.assertEqual(calls[0].get("token"), "hf_testtoken_not_real")
        self.assertEqual(calls[0].get("repo_id"), "black-forest-labs/FLUX.2-klein-9b-fp8")

    def test_fetch_omits_token_kwarg_when_env_empty(self) -> None:
        import os
        from unittest.mock import patch

        import prefetch as pf

        calls: list[dict] = []

        def fake_dl(**kwargs):
            calls.append(kwargs)
            dest_dir = Path(kwargs["local_dir"])
            dest_dir.mkdir(parents=True, exist_ok=True)
            path = dest_dir / Path(kwargs["filename"]).name
            path.write_bytes(b"x" * 64)
            return str(path)

        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "u.safetensors"
            job = {
                "repo": "black-forest-labs/FLUX.2-klein-9b-fp8",
                "file": "flux-2-klein-9b-fp8.safetensors",
                "dest": str(dest),
            }
            env = {k: v for k, v in os.environ.items() if k not in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN")}
            with patch.dict(os.environ, env, clear=True):
                with patch.object(pf, "hf_hub_download", side_effect=fake_dl):
                    with patch.object(pf, "_have", return_value=False):
                        with patch.object(pf, "ensure_safetensors", return_value="missing"):
                            pf._fetch(job)
        self.assertTrue(calls)
        self.assertNotIn("token", calls[0])


class ProgressLines(unittest.TestCase):
    def test_minute_tqdm_emits_start_and_done(self) -> None:
        import prefetch as pf

        bar = pf.MinuteTqdm(desc="flux2-vae.safetensors", total=1000, initial=0)
        bar.update(10)
        bar.update(10)
        bar.close()
        self.assertGreaterEqual(bar.n, 20)

    def test_progress_interval_is_one_minute(self) -> None:
        import prefetch as pf

        self.assertEqual(pf.PROGRESS_EVERY_S, 60.0)


class ZipIsTransportOnly(unittest.TestCase):
    def test_sidecar_zip_inflates_to_comfy_filename(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw = root / "flux2-vae.safetensors"
            payload = b"fake-safetensors-bytes-not-a-zip"
            raw.write_bytes(payload)
            archive = zip_safetensors(raw)
            raw.unlink()
            dest = root / "models" / "vae" / "flux2-vae.safetensors"
            unzip_safetensors(archive, dest)
            self.assertEqual(dest.read_bytes(), payload)
            self.assertFalse(is_zip_file(dest))
            self.assertEqual(dest.name, "flux2-vae.safetensors")

    def test_misnamed_zip_at_safetensors_path_is_inflated(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "flux-2-klein-base-9b-fp8.safetensors"
            inner = Path(td) / "inner.safetensors"
            inner.write_bytes(b"unet-bytes")
            with zipfile.ZipFile(dest, "w") as zf:
                zf.write(inner, arcname="flux-2-klein-base-9b-fp8.safetensors")
            self.assertTrue(is_zip_file(dest))
            self.assertEqual(ensure_safetensors(dest), "unzipped-inplace")
            self.assertEqual(dest.read_bytes(), b"unet-bytes")
            self.assertFalse(is_zip_file(dest))


class UnetSetSelection(unittest.TestCase):
    """One unet per image: a 24 GB card holds ONE ~9 GB unet plus the 8.66 GB
    text encoder (~17.7 GB). Two unets is ~27 GB, so Comfy streams weights from
    host memory and a render that should take seconds takes minutes."""

    def _names(self, raw: str | None) -> list[str]:
        import prefetch as pf  # imported here, like the other tests in this file

        return [Path(j["dest"]).name for j in pf.selected_jobs(raw)]

    def test_default_is_every_unet(self) -> None:
        for raw in (None, "", "all", "*"):
            names = self._names(raw)
            self.assertIn("flux-2-klein-base-9b-fp8.safetensors", names)
            self.assertIn("snofsSexNudesAndOther_distilledV12KleinFp8.safetensors", names)
            self.assertIn("flux-2-klein-9b-fp8.safetensors", names)

    def test_a_single_set_fetches_only_its_unet(self) -> None:
        for name, unet in (
            ("base", "flux-2-klein-base-9b-fp8.safetensors"),
            ("distilled", "flux-2-klein-9b-fp8.safetensors"),
            ("snofs", "snofsSexNudesAndOther_distilledV12KleinFp8.safetensors"),
        ):
            names = self._names(name)
            self.assertIn(unet, names, name)
            others = [n for n in names if n.endswith(".safetensors") and n.startswith(("flux-2-klein", "snofs"))]
            self.assertEqual(others, [unet], name)

    def test_the_encoder_and_vae_are_always_fetched(self) -> None:
        for raw in ("base", "snofs", None):
            names = self._names(raw)
            self.assertIn("qwen_3_8b_fp8mixed.safetensors", names)
            self.assertIn("flux2-vae.safetensors", names)

    def test_an_unknown_set_falls_back_to_everything(self) -> None:
        names = self._names("nonsense")
        self.assertIn("flux-2-klein-base-9b-fp8.safetensors", names)
        self.assertIn("snofsSexNudesAndOther_distilledV12KleinFp8.safetensors", names)

    def test_a_comma_list_fetches_both_named(self) -> None:
        names = self._names("snofs,base")
        self.assertIn("snofsSexNudesAndOther_distilledV12KleinFp8.safetensors", names)
        self.assertIn("flux-2-klein-base-9b-fp8.safetensors", names)
        self.assertNotIn("flux-2-klein-9b-fp8.safetensors", names)


if __name__ == "__main__":
    unittest.main()
