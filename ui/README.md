# The studio page

The Angular page the Python server serves. Run it through the server, not the
Angular dev server, so `/api` answers:

```powershell
python -m salad_studio
```

The server serves `ui/dist/`, which is not committed. It builds the page itself
when the build is missing or its source changed, so a change under `ui/src`
needs no separate step: restart `python -m salad_studio`. To make the build by
hand:

```powershell
cd ui
npx ng build
```

`npx ng test` runs the Vitest specs. CI runs `npx ng build` first, so a build
error fails before the specs run. `node audit.cjs` checks template bindings
against the components; it is a static check, not a test.
