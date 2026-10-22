# The studio page

The Angular page the Python server serves. Run it through the server, not the
Angular dev server, so `/api` answers:

```powershell
python -m salad_studio
```

The server serves `ui/dist/ui/browser`, which is committed. After changing
anything under `ui/src`, rebuild and commit the output:

```powershell
cd ui
npx ng build
```

`npx ng test` runs the Vitest specs. `ui/audit.cjs` checks template bindings
against the components; it is a static check, not a test.
