"""Live check: Studio HF token can HEAD both gated Klein unets.

Does not download the 9 GB files. Skips if no token is configured.
Never prints the token.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
for p in (str(TOOLS), str(HERE), str(TOOLS / "salad_studio")):
    if p not in sys.path:
        sys.path.insert(0, p)

GATED = (
    (
        "black-forest-labs/FLUX.2-klein-base-9b-fp8",
        "flux-2-klein-base-9b-fp8.safetensors",
    ),
    (
        "black-forest-labs/FLUX.2-klein-9b-fp8",
        "flux-2-klein-9b-fp8.safetensors",
    ),
)


def _token() -> str:
    try:
        from salad_studio import tokens
    except ImportError:
        return ""
    return (tokens.read_token("huggingface") or "").strip()


class HfGatedKleinAccess(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.token = _token()
        if not cls.token:
            raise unittest.SkipTest(
                "No Hugging Face token in studio-tokens.json or ~/.config/huggingface/token"
            )
        if not cls.token.startswith("hf_"):
            raise unittest.SkipTest("Hugging Face token does not look like hf_…")

    def test_token_heads_both_klein_unets(self) -> None:
        from huggingface_hub import HfApi, get_hf_file_metadata, hf_hub_url
        from huggingface_hub.utils import GatedRepoError, HfHubHTTPError

        api = HfApi(token=self.token)
        self.assertTrue(self.token.startswith("hf_"))
        for repo, filename in GATED:
            with self.subTest(repo=repo):
                try:
                    info = api.model_info(repo)
                except GatedRepoError as e:
                    self.fail(f"GATED 403 model_info {repo}: {e}")
                except HfHubHTTPError as e:
                    self.fail(f"HTTP {e.response.status_code if e.response else '?'} model_info {repo}: {e}")
                self.assertEqual(info.id, repo)
                url = hf_hub_url(repo_id=repo, filename=filename)
                try:
                    meta = get_hf_file_metadata(url, token=self.token)
                except GatedRepoError as e:
                    self.fail(f"GATED 403 file {repo}/{filename}: {e}")
                except HfHubHTTPError as e:
                    self.fail(
                        f"HTTP {e.response.status_code if e.response else '?'} "
                        f"file {repo}/{filename}: {e}"
                    )
                size = int(getattr(meta, "size", 0) or 0)
                self.assertGreater(size, 1_000_000_000, f"{filename} size={size}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
