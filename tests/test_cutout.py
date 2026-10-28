"""Cutout: a plate goes in, an RGBA PNG with the subject's cut lands beside it.

The rembg session is a stand-in. A real one downloads a model and loads it
into onnxruntime, which CI must not do, so every test here passes a fake
whose ``predict`` returns a mask PNG of its own.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
PKG = TOOLS / "salad_studio"
for _p in (PKG, TOOLS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from PIL import Image  # noqa: E402

import cutout  # noqa: E402


def _plate(folder: Path, suffix: str = ".jpg") -> Path:
    path = folder / f"studio_1{suffix}"
    Image.new("RGB", (64, 48), (200, 120, 40)).save(path)
    return path


class FakeSession:
    """Stands in for a rembg session: the left half of every image is subject.

    Like a real session, it takes the plate's image and answers with a list of
    ``L`` masks the plate's size.
    """

    def __init__(self) -> None:
        self.seen: list[Image.Image] = []

    def predict(self, img: Image.Image) -> list[Image.Image]:
        self.seen.append(img)
        mask = Image.new("L", img.size, 0)
        mask.paste(255, (0, 0, img.size[0] // 2, img.size[1]))
        return [mask]


class RemoveBackground(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        self.session = FakeSession()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_writes_an_rgba_cutout_beside_the_plate(self) -> None:
        plate = _plate(self.folder)
        before = plate.read_bytes()
        out = cutout.remove_background(plate, session=self.session)

        self.assertEqual(out, self.folder / "studio_1-cutout.png")
        self.assertTrue(out.is_file())
        with Image.open(out) as img:
            self.assertEqual(img.mode, "RGBA")
            self.assertEqual(img.size, (64, 48), "the cut keeps the plate's size")
            self.assertEqual(img.getpixel((5, 5))[3], 255, "the subject stays opaque")
            self.assertEqual(img.getpixel((60, 5))[3], 0, "the background goes transparent")
        self.assertEqual(plate.read_bytes(), before, "the original is untouched")

    def test_a_second_call_converges_on_one_file(self) -> None:
        plate = _plate(self.folder)
        first = cutout.remove_background(plate, session=self.session)
        stamp = first.stat().st_mtime_ns
        second = cutout.remove_background(plate, session=self.session)

        self.assertEqual(first, second)
        self.assertEqual(sorted(p.name for p in self.folder.iterdir()),
                         ["studio_1-cutout.png", "studio_1.jpg"])
        self.assertEqual(second.stat().st_mtime_ns, stamp, "a current cutout costs no second cut")
        self.assertEqual(len(self.session.seen), 1)

    def test_a_newer_plate_gets_a_fresh_cutout(self) -> None:
        plate = _plate(self.folder)
        first = cutout.remove_background(plate, session=self.session)
        Image.new("RGB", (64, 48), (10, 10, 10)).save(plate)
        os.utime(plate, ns=(first.stat().st_mtime_ns + 1_000_000,) * 2)
        cutout.remove_background(plate, session=self.session)
        self.assertEqual(len(self.session.seen), 2, "a plate newer than its cutout is cut again")

    def test_a_png_plate_cuts_the_same_way(self) -> None:
        plate = _plate(self.folder, ".png")
        out = cutout.remove_background(plate, session=self.session)
        self.assertEqual(out.name, "studio_1-cutout.png")
        self.assertTrue(out.is_file())

    def test_a_missing_model_refuses_without_rembg(self) -> None:
        plate = _plate(self.folder)
        saved = cutout.MODEL_PATH
        cutout.MODEL_PATH = self.folder / "no-model"
        try:
            with self.assertRaises(cutout.RemovalUnavailable) as caught:
                cutout.remove_background(plate)
        finally:
            cutout.MODEL_PATH = saved

        self.assertIn("--prefetch-cutout", str(caught.exception))
        self.assertNotIn("rembg", sys.modules, "a missing model never imports rembg")
        self.assertEqual(sorted(p.name for p in self.folder.iterdir()), ["studio_1.jpg"])

    def test_model_ready_reads_the_models_folder(self) -> None:
        saved = cutout.MODEL_PATH
        cutout.MODEL_PATH = self.folder / cutout.DEFAULT_MODEL
        try:
            self.assertFalse(cutout.model_ready())
            cutout.MODEL_PATH.mkdir()
            self.assertFalse(cutout.model_ready(), "an empty folder is not a model")
            (cutout.MODEL_PATH / "model.onnx").write_bytes(b"x")
            self.assertTrue(cutout.model_ready())
        finally:
            cutout.MODEL_PATH = saved

    def test_the_session_is_built_once_per_model(self) -> None:
        built: list[str] = []
        saved_model, saved_sessions = cutout.MODEL_PATH, dict(cutout._SESSIONS)
        cutout.MODEL_PATH = self.folder / cutout.DEFAULT_MODEL
        cutout.MODEL_PATH.mkdir()
        (cutout.MODEL_PATH / "model.onnx").write_bytes(b"x")
        fake = FakeSession()
        try:
            import rembg

            saved_new = rembg.new_session
            rembg.new_session = lambda model: built.append(model) or fake
            try:
                plate = _plate(self.folder)
                cutout.remove_background(plate)
                cutout.remove_background(plate)
            finally:
                rembg.new_session = saved_new
        finally:
            cutout.MODEL_PATH = saved_model
            cutout._SESSIONS.clear()
            cutout._SESSIONS.update(saved_sessions)
        self.assertEqual(built, [cutout.DEFAULT_MODEL], "one session serves every plate")


if __name__ == "__main__":
    unittest.main()
