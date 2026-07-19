# ABK Studio

Web app for ComfyUI's `Standard_V37` workflow: prompts, LoRAs (LoRA Manager), projects, sizes, persistent history.

License: [PolyForm Noncommercial 1.0.0](LICENSE) — free to use and modify, commercial use not permitted.

## Requirements

- ComfyUI running on `127.0.0.1:8188` (start it however you normally do).
- Python 3.10+.
- ComfyUI must have the custom nodes and models used by the `Standard_V37` workflow installed, and the workflow itself must be placed in `Workflow/` (not included in this repo) — see [REQUIREMENTS.md](REQUIREMENTS.md).

## First run

```
cd C:\CodesA\Comfy\ComfyUI_ABKSTUDIO
venv\Scripts\python -m pip install -r requirements.txt   # first time only
```

## Starting the site

```
cd C:\CodesA\Comfy\ComfyUI_ABKSTUDIO
venv\Scripts\python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

- `--host 0.0.0.0` exposes the site on your local network (to view it from your phone or another device): go to `http://<this-PC-IP>:8000`.
- From this same PC: `http://localhost:8000`.

## Structure

- `Workflow/Standard_V37.api.json` — the workflow's **API format** export (the one sent to ComfyUI). This is the one the app uses; don't edit it by hand unless you know what you're doing. **Not included in this repo** (see [REQUIREMENTS.md](REQUIREMENTS.md)) — you need to place it yourself before starting.
- `Workflow/Standard_V37.json` — UI format export (the one ComfyUI's editor opens). Sent alongside the previous one because some nodes (e.g. KJNodes' `WidgetToString`) need it to avoid truncating execution. Also not included in this repo.
- `app/` — FastAPI backend.
- `static/` — the site (HTML/CSS/JS).
- `data/abkstudio.sqlite3` — persistent history (created automatically on first run).

## If you update the workflow in ComfyUI

If you change the `Standard_V37` graph inside ComfyUI (new node, rewiring, etc.), you need to re-export **both** files and replace them in `Workflow/`:

1. ComfyUI menu → Workflow → Export (saves UI format) → overwrite `Standard_V37.json`.
2. ComfyUI menu → Workflow → Export (API) → overwrite `Standard_V37.api.json`.

If the IDs of the nodes the app edits also change (prompt, LoRA, seed, size, checkpoint, sampling, save path), you need to update the `NODE_*` constants in `app/workflow_builder.py` to point to the new IDs.
