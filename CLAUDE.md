# salad-studio

Windows tooling for SaladCloud ComfyUI image generation: an Angular page served
by a Python server on 127.0.0.1 that builds, validates, and POSTs Comfy `/prompt`
graphs, plus the container image and prompt recipes they run on. `README.md` is
the orientation; `salad_studio/README.md` is the server manual.

## Commands

`unittest`, on Python 3.14.7. Run the three suites separately:

```
python -m unittest discover -s tests -p "test_*.py"           # ~1177 tests, ~60 s
python test_salad_comfy_live_findings.py                      # root structural checks
cd salad_klein && python -m unittest discover -p "test_*.py"  # ~18 tests
```

The page builds itself when `python -m salad_studio` finds `ui/dist/` missing or
stale; `cd ui && npx ng build` is the same build by hand. CI is
`.github/workflows/checks.yml`.

## Background removal

`salad_studio/cutout.py` cuts a finished plate through [rembg](https://github.com/danielgatis/rembg)
on the `u2net` model, pinned in `requirements.txt` with `onnxruntime`. The
"Remove background" box on Prompt Settings is per run and not a profile field.
The model lives in `~/.rembg/models/u2net` and downloads on first use, so
`python -m salad_studio --prefetch-cutout` fetches it ahead of time. A cut is
additive: when it cannot run, the render keeps its plate and says why. The
model name is a parameter, so raising quality is a one-line change.
