"""Background removal for a finished plate, through rembg.

A plate Generate or Retry writes can be cut out once it is on disk: the
subject stays, the rest becomes transparent, and the result is an RGBA PNG
named ``<plate stem>-cutout.png`` beside the plate. The original is never
touched, so turning the option off leaves every earlier plate as it was.

rembg is imported only when a cut is asked for, so a machine without it still
starts the studio. Its model is a download of its own, which is why the
caller gets :class:`RemovalUnavailable` with the command that fetches it
rather than a stack trace.
"""
from __future__ import annotations

import os
import tempfile
import threading
from pathlib import Path

DEFAULT_MODEL = "u2net"
MODEL_PATH = Path.home() / ".rembg" / "models" / DEFAULT_MODEL

_SESSIONS: dict[str, object] = {}
_SESSION_LOCK = threading.Lock()


class RemovalUnavailable(Exception):
    """rembg is not installed, or its model has not been downloaded."""


def model_ready(model: str = DEFAULT_MODEL) -> bool:
    """Whether the model's files are on disk, so a cut needs no download."""
    folder = MODEL_PATH if model == DEFAULT_MODEL else MODEL_PATH.parent / model
    try:
        return folder.is_dir() and any(folder.iterdir())
    except OSError:
        return False


def _session(model: str) -> object:
    """The session for ``model``, built once. Building it downloads the model."""
    with _SESSION_LOCK:
        if model not in _SESSIONS:
            try:
                import rembg
            except ImportError as exc:
                raise RemovalUnavailable(
                    "Background removal needs rembg, which is not installed. Install "
                    "it with `python -m pip install -r requirements.txt`, then run "
                    "`python -m salad_studio --prefetch-cutout`."
                ) from exc
            try:
                _SESSIONS[model] = rembg.new_session(model)
            except Exception as exc:  # noqa: BLE001 - the model's own words name the failure
                raise RemovalUnavailable(
                    f"could not load the background-removal model {model!r} ({exc}). "
                    "Check the network, then run `python -m salad_studio --prefetch-cutout`."
                ) from exc
        return _SESSIONS[model]


def prefetch(model: str = DEFAULT_MODEL) -> Path:
    """Download ``model`` now by building its session; returns the folder it lands in."""
    _session(model)
    return MODEL_PATH if model == DEFAULT_MODEL else MODEL_PATH.parent / model


def remove_background(plate: Path, *, model: str = DEFAULT_MODEL,
                      session: object | None = None) -> Path:
    """Cut the background from ``plate`` and write ``<stem>-cutout.png`` beside it.

    A second call cuts the original again and replaces the file, so one plate
    always has one cutout. The cutout keeps the plate's size and its pixels, so
    it lines up with the image it came from.
    """
    plate = Path(plate)
    out = plate.with_name(f"{plate.stem}-cutout.png")
    try:
        if out.is_file() and out.stat().st_mtime_ns > plate.stat().st_mtime_ns:
            return out
    except OSError:
        pass
    if session is None and not model_ready(model):
        raise RemovalUnavailable(
            f"the background-removal model {model!r} is not downloaded. Run "
            "`python -m salad_studio --prefetch-cutout`, then Generate again."
        )
    from PIL import Image

    with Image.open(plate) as img:
        img.load()
        source = img.convert("RGBA")
    if session is None:
        session = _session(model)
    # rembg's remove() would also clear faint specks and soften the edge; the
    # mask is the part that decides what is subject.
    source.putalpha(session.predict(source)[0])
    fd, tmp = tempfile.mkstemp(prefix=out.name + ".", suffix=".tmp", dir=str(out.parent))
    os.close(fd)
    try:
        source.save(tmp, "PNG")
        os.replace(tmp, out)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return out
