# Presentations

`Salad-Studio-Features.pptx` explains what the studio is and what each page
does, in 17 slides.

## Rebuilding it

```
python -m pip install python-pptx
python presentations/build_deck.py
```

Run from the repo root. `build_deck.py` reads the page list from
`salad_studio/web/registry.py`, the queue constants from
`salad_studio/salad_queue.py`, and the image tags from
`salad_studio/studio-metadata.json`, so the deck follows the code instead of a
transcript of it. If a deck fact drifts, the script fails on the import or the
assert rather than printing a stale slide.

The script does not take screenshots. `shots/` holds them, and they were
captured from the running studio in headless Chromium, with keys, plate
thumbnails and prompt text blurred. To replace one, start
`python -m salad_studio --no-open`, load the URL it prints, capture that page
at 1600×1000, and overwrite the file in `shots/`. The deck needs no change
unless a filename moves.

`python-pptx` is not in `requirements.txt`. The deck is a document, not a
runtime dependency of the studio.
