"""Zip is transport only. Comfy/Salad must see raw ``*.safetensors``.

Never ``RUN unzip`` in the Dockerfile — that bakes the 17 GB files into an
image layer. Inflate at container start (prefetch) or when staging locally.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

ZIP_MAGIC = b"PK\x03\x04"


def is_zip_file(path: str | Path) -> bool:
    p = Path(path)
    if not p.is_file():
        return False
    try:
        with p.open("rb") as fh:
            return fh.read(4) == ZIP_MAGIC
    except OSError:
        return False


def zip_sidecar(dest: str | Path) -> Path | None:
    """``foo.safetensors.zip`` next to the Comfy path, if present."""
    p = Path(dest)
    for cand in (Path(str(p) + ".zip"), p.with_suffix(".zip")):
        if cand.is_file():
            return cand
    return None


def unzip_safetensors(archive: str | Path, dest: str | Path) -> Path:
    """Extract the ``.safetensors`` member to ``dest`` (Comfy's filename)."""
    dest_p = Path(dest)
    dest_p.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest_p.with_suffix(dest_p.suffix + ".unz")
    with zipfile.ZipFile(archive) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith(".safetensors") and not n.endswith("/")]
        if not names:
            names = [n for n in zf.namelist() if not n.endswith("/")]
        if not names:
            raise ValueError(f"{archive} has no files to extract")
        # Prefer a member whose basename matches the Comfy dest.
        want = dest_p.name.lower()
        member = next((n for n in names if Path(n).name.lower() == want), names[0])
        with zf.open(member) as src, tmp.open("wb") as out:
            while True:
                chunk = src.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
    if is_zip_file(tmp):
        tmp.unlink(missing_ok=True)
        raise ValueError(f"{archive} unzipped to another zip; refusing to install as {dest_p.name}")
    tmp.replace(dest_p)
    return dest_p


def zip_safetensors(src: str | Path, archive: str | Path | None = None) -> Path:
    """Store ``src`` as a zip named ``<src>.zip`` (Zip64 for >4 GB)."""
    src_p = Path(src)
    out = Path(archive) if archive is not None else Path(str(src_p) + ".zip")
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".part")
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
        zf.write(src_p, arcname=src_p.name)
    tmp.replace(out)
    return out


def ensure_safetensors(dest: str | Path) -> str:
    """Make ``dest`` a real safetensors file Comfy can load.

    Order: already a non-zip file → dest is a zip (misnamed) → sidecar zip.
    Does not download. Returns a short status.
    """
    dest_p = Path(dest)
    if dest_p.is_file() and not is_zip_file(dest_p):
        return "have"
    if dest_p.is_file() and is_zip_file(dest_p):
        # COPY foo.safetensors that is actually a zip — inflate in place.
        tmp_zip = dest_p.with_suffix(dest_p.suffix + ".zip.bak")
        dest_p.replace(tmp_zip)
        try:
            unzip_safetensors(tmp_zip, dest_p)
        finally:
            tmp_zip.unlink(missing_ok=True)
        return "unzipped-inplace"
    side = zip_sidecar(dest_p)
    if side is not None:
        unzip_safetensors(side, dest_p)
        return "unzipped-sidecar"
    return "missing"
