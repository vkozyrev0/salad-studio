"""Generate and Remove background: the cutout is the plate the history gets.

The render is faked at the engine's own entry points and answers with a real
small JPEG plate, so the rest of the press runs for real: the services cut it,
and the controller attaches the result to the row.
"""
from __future__ import annotations

import io
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT, ROOT / "salad_studio"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import generator  # noqa: E402
import profiles  # noqa: E402
import salad_queue  # noqa: E402
import prompt_history  # noqa: E402
from PIL import Image  # noqa: E402
from salad_studio import cutout  # noqa: E402
from tests import _stores  # noqa: E402
from tests._studio import studio  # noqa: E402

REAL_REMOVAL = cutout.remove_background


def setUpModule() -> None:
    """A studio built here builds a queue, and the queue writes its ledger."""
    _stores.keep_queue_ledger_off_the_user_store()


def tearDownModule() -> None:
    _stores.restore_queue_ledger()


class HalfSession:
    """A stand-in session: the left half of the plate is subject."""

    def __init__(self) -> None:
        self.calls = 0

    def predict(self, img: Image.Image) -> list[Image.Image]:
        self.calls += 1
        mask = Image.new("L", img.size, 0)
        mask.paste(255, (0, 0, img.size[0] // 2, img.size[1]))
        return [mask]


def _note(reply: dict) -> str:
    return str((reply.get("shell") or {}).get("note", {}).get("text", ""))


class GenerateCutoutTest(unittest.TestCase):
    def setUp(self) -> None:
        ctx = studio()
        self.made = ctx.__enter__()
        self.addCleanup(ctx.__exit__, None, None, None)
        self.studio = self.made.shell
        self.session = HalfSession()
        self._saved: list[tuple[object, str, object]] = []
        self.studio.apply_profile(profiles.SaladProfile(
            name="klein", gateway="http://203.0.113.9:8188", mode="vast"))
        # Gives the editor a prompt text and says nothing has been rendered under it, so the
        # press writes its own history row even when the server has a matching one.
        self.made.engine.handle({"page": "editor", "action": "set_prompt",
                                 "args": {"positive": f"a cut-out test {id(self)}", "negative": ""}})
        self._patch(generator, "generate_from_payload", self._render)
        self._patch(generator, "generate_from_vast", self._render)
        self._patch(cutout, "remove_background", self._cut)
        self._patch(cutout, "model_ready", lambda model=cutout.DEFAULT_MODEL: True)

    def tearDown(self) -> None:
        for module, name, value in reversed(self._saved):
            setattr(module, name, value)

    def _patch(self, module: object, name: str, value: object) -> None:
        self._saved.append((module, name, getattr(module, name)))
        setattr(module, name, value)

    def _render(self, **kwargs: object) -> Path:
        # A uniform plate would still cut to a hole, so the two halves differ:
        # only the mask's own half has to go transparent for the test to tell.
        plate = Path(str(kwargs["out_dir"])) / "jpeg-plate.jpg"
        image = Image.new("RGB", (64, 48))
        image.paste((200, 120, 40), (0, 0, 32, 48))
        image.paste((255, 255, 255), (32, 0, 64, 48))
        plate.parent.mkdir(parents=True, exist_ok=True)
        image.save(plate, "JPEG", quality=95)
        self.plate_name = plate.name
        return plate

    def _cut(self, plate: Path, **kwargs: object) -> Path:
        return REAL_REMOVAL(plate, session=self.session)

    def _press(self) -> None:
        """Generate, then wait for its ``action_done``: that reply carries the page's note."""
        hub = self.studio.hub
        real = hub.publish
        done: list[dict] = []

        def publish(kind: str, data: dict) -> None:
            if kind == "action_done":
                done.append(data["reply"])
            real(kind, data)

        hub.publish = publish
        try:
            status, _reply = self.made.engine.handle({"page": "shell", "action": "generate", "args": {}})
            self.assertEqual(status, 200)
            deadline = time.monotonic() + 5
            while not done and time.monotonic() < deadline:
                time.sleep(0.02)
        finally:
            hub.publish = real
        self.assertTrue(done, "the press reached generate_sync and finished")
        self.done_reply = done[0]

    def _row(self) -> dict:
        """The row this test's press gave a picture; later tests outrank it in the list."""
        rows = [r for r in prompt_history.list_prompts() if r.get("image")]
        self.assertTrue(rows, "the press attached a picture to its row")
        return rows[0]

    def test_the_history_gets_the_cutout_and_one_gallery_plate(self) -> None:
        self.studio.form.remove_bg = "on"
        self._press()

        cut = Path(self.made.tmp.name) / "art" / (Path(self.plate_name).stem + "-cutout.png")
        self.assertTrue(cut.is_file(), "the cutout landed beside the plate")
        self.assertEqual(len(self.studio.state_dict()["plates"]), 1)
        self.assertEqual(self.session.calls, 1)
        # The subject is the left half; the right half was plate that is now gone,
        # so the cutout narrows to 32 px and sits centred with canvas either side.
        with Image.open(self._row()["image"]) as thumb:
            left, middle, right = (thumb.getpixel((x, 24)) for x in (5, 20, 47))
        self.assertLess(left[0], 40, "no plate survives left of the subject")
        self.assertAlmostEqual(middle[0], 200, delta=8, msg="the history thumb is the cutout")
        self.assertLess(right[0], 40, "nor right of it")

    def test_a_gallery_thumbnail_shows_a_cutout_on_white(self) -> None:
        """Transparent pixels drawn as black would hide a dark subject."""
        self.studio.form.remove_bg = "on"
        self._press()
        cut = next((Path(self.made.tmp.name) / "art").glob("*-cutout.png"))
        with Image.open(io.BytesIO(self.studio.services.thumbnail(cut))) as thumb:
            y = thumb.height // 2
            kept = thumb.getpixel((thumb.width // 4, y))
            cut_away = thumb.getpixel((thumb.width * 3 // 4, y))
        self.assertAlmostEqual(kept[0], 200, delta=8, msg="the subject stays")
        self.assertEqual(cut_away, (255, 255, 255), "the cut half is white, not black")

    def test_with_the_box_off_nothing_is_cut(self) -> None:
        self.studio.form.remove_bg = ""
        self._press()

        self.assertFalse(list((Path(self.made.tmp.name) / "art").glob("*-cutout.png")))
        self.assertEqual(self.session.calls, 0)
        with Image.open(self._row()["image"]) as thumb:
            left, right = thumb.getpixel((0, 24)), thumb.getpixel((47, 24))
        self.assertAlmostEqual(left[0], 200, delta=8, msg="the whole original is kept")
        self.assertGreater(right[0], 240, "including the half a cutout would have dropped")

    def test_a_missing_model_keeps_the_render_and_says_why(self) -> None:
        self._patch(cutout, "remove_background", REAL_REMOVAL)
        self._patch(cutout, "model_ready", lambda model=cutout.DEFAULT_MODEL: False)
        self.studio.form.remove_bg = "on"
        self._press()

        self.assertTrue(self._row()["image"], "the original plate still gets a thumbnail")
        self.assertEqual(len(self.studio.state_dict()["plates"]), 1)
        self.assertIn("--prefetch-cutout", _note(self.done_reply))
        built: list[str] = []
        self._patch(cutout, "_session", lambda model: built.append(model))
        self.assertEqual(built, [], "a missing model never builds a session")

    def test_a_failing_cut_keeps_the_render_and_says_why(self) -> None:
        def broken(plate: Path, **kwargs: object) -> Path:
            raise RuntimeError("onnxruntime is unhappy")

        self._patch(cutout, "remove_background", broken)
        self.studio.form.remove_bg = "on"
        self._press()

        self.assertTrue(self._row()["image"])
        self.assertIn("No background removal: RuntimeError: onnxruntime is unhappy",
                      _note(self.done_reply))
        self.assertEqual(len(self.studio.state_dict()["plates"]), 1)


class RetryCutoutTest(unittest.TestCase):
    """Retry writes its own plate, outside Generate, so it reads the same box."""

    def setUp(self) -> None:
        ctx = studio()
        self.made = ctx.__enter__()
        self.addCleanup(ctx.__exit__, None, None, None)
        self.studio = self.made.shell
        self.addCleanup(setattr, cutout, "remove_background", cutout.remove_background)
        self.prompt = prompt_history.add_request({"prompt": {"1": {"class_type": "CLIPTextEncode",
                                                                  "inputs": {"text": f"retried {id(self)}"}}}})

    def _retry(self, replacement: object) -> tuple[salad_queue.Job, dict]:
        """Answer one Retry with a queue accepting a PNG; returns the job and its action_done."""
        import base64
        import io

        from PIL import Image

        buf = io.BytesIO()
        Image.new("RGB", (64, 48), (200, 120, 40)).save(buf, "PNG")
        png = base64.b64encode(buf.getvalue()).decode()
        queue = self.studio.services.gen_queue
        job = queue.enqueue({"profile": "klein", "ts": self.prompt["ts"], "history_key": self.prompt["key"]},
                            lambda _job: salad_queue.Attempt(), line="klein")
        job.state = salad_queue.FAILED
        job.reason = "boom"
        job.work = lambda _job: salad_queue.Attempt(status=200, accepted=True, result=png)
        self.studio.form.remove_bg = "on"
        cutout.remove_background = replacement
        events: dict[str, list[dict]] = {}
        self.studio.hub.publish = lambda name, data: events.setdefault(name, []).append(data)
        status, _reply = self.made.engine.handle({"page": "queue", "action": "select",
                                                  "args": {"key": str(job.id)}})
        self.assertEqual(status, 200)
        status, reply = self.made.engine.handle({"page": "queue", "action": "retry", "args": {}})
        self.assertEqual(status, 200)
        self.assertTrue(reply["pending"])
        deadline = time.monotonic() + 15
        while "action_done" not in events and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertTrue(events.get("action_done"), "the retry never answered")
        return job, events["action_done"][0]["reply"]

    def test_a_retry_with_remove_background_attaches_the_cutout(self) -> None:
        job, done = self._retry(lambda plate, **_: REAL_REMOVAL(plate, session=HalfSession()))

        self.assertEqual(job.state, salad_queue.ACCEPTED)
        self.assertEqual(len(list(self.studio.services.out_dir.glob("studio_*-cutout.png"))), 1,
                         "the retry cut its plate")
        row = next(r for r in prompt_history.list_prompts() if r.get("key") == self.prompt["key"])
        self.assertTrue(row.get("image"), "the retry's row shows the cutout")
        self.assertEqual(done["shell"]["note"]["level"], "ok")

    def test_a_retry_whose_cutout_fails_keeps_the_plate_and_says_why(self) -> None:
        def broken(plate, **_kwargs):
            raise cutout.RemovalUnavailable("the model is not downloaded. Run --prefetch-cutout.")

        job, done = self._retry(broken)

        self.assertEqual(job.state, salad_queue.ACCEPTED)
        self.assertEqual(len(list(self.studio.services.out_dir.glob("studio_*.png"))), 1)
        self.assertEqual(done["shell"]["note"]["level"], "warn")
        self.assertIn("No background removal: the model is not downloaded", done["shell"]["note"]["text"])


if __name__ == "__main__":
    unittest.main()
