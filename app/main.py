import asyncio
import json
import uuid

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from . import comfy_client, config, db, library, ollama_client, workflow_builder
from .schemas import (
    DeleteHistoryRequest,
    EnhancePromptRequest,
    GenerateRequest,
    LoraFavoriteRequest,
    NewProjectRequest,
    RenameProjectRequest,
    SaveRecipeRequest,
)

app = FastAPI(title="ABK Studio")


_ui_workflow_cache: dict | None = None

# gen_id -> most recent raw ComfyUI console log line seen for that generation
_last_log: dict[str, str] = {}
# gen_id -> background task streaming that generation's log lines
_progress_tasks: dict[str, asyncio.Task] = {}


async def _track_progress(gen_id: str, client_id: str) -> None:
    try:
        async for line in comfy_client.stream_log_lines(client_id):
            _last_log[gen_id] = line
    except Exception:
        pass  # progress tracking is best-effort, never affects the generation itself


def _stop_tracking(gen_id: str) -> None:
    task = _progress_tasks.pop(gen_id, None)
    if task:
        task.cancel()
    _last_log.pop(gen_id, None)


def _apply_history_entry(gen_id: str, entry: dict | None) -> dict:
    """Given a gen's raw ComfyUI /history entry (or None if ComfyUI has no
    record of it), updates the DB row accordingly and returns the fresh row."""
    if entry is None:
        return db.get_generation(gen_id)
    status_info = entry.get("status", {})
    if status_info.get("completed"):
        image_paths = comfy_client.extract_output_images(entry)
        db.update_generation_status(gen_id, "done", image_paths)
        _stop_tracking(gen_id)
    elif status_info.get("status_str") == "error":
        db.update_generation_status(gen_id, "error", [])
        _stop_tracking(gen_id)
    else:
        db.update_generation_status(gen_id, "running")
    return db.get_generation(gen_id)


async def _reconcile_pending_loop() -> None:
    """Backend-side safety net: if a tab closes/refreshes mid-generation, nobody
    ever calls /api/status again to persist the final result. This periodically
    checks ComfyUI's own history for every still-queued/running DB row so the
    SQLite record catches up with reality even with no client watching."""
    while True:
        await asyncio.sleep(15)
        try:
            pending = db.list_pending_generations()
            if not pending:
                continue
            history = await comfy_client.get_full_history()
            for gen in pending:
                entry = history.get(gen["prompt_id"])
                if entry is not None:
                    _apply_history_entry(gen["id"], entry)
        except Exception:
            pass  # best-effort; try again on the next tick


@app.on_event("startup")
async def on_startup():
    global _ui_workflow_cache
    db.init_db()
    _ui_workflow_cache = workflow_builder.load_ui_template()
    asyncio.create_task(_reconcile_pending_loop())


# ---------- static site ----------

@app.get("/")
def index():
    return FileResponse(config.STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")
app.mount("/outputs", StaticFiles(directory=config.COMFY_OUTPUT_DIR), name="outputs")


# ---------- server status ----------

@app.get("/api/health")
async def api_health():
    try:
        queue = await comfy_client.get_queue()
    except Exception:
        return {"status": "down"}
    busy = bool(queue.get("queue_running")) or bool(queue.get("queue_pending"))
    return {"status": "working" if busy else "up"}


# ---------- library ----------

@app.get("/api/library/checkpoints")
async def api_checkpoints():
    try:
        return await library.get_checkpoints()
    except Exception as exc:
        raise HTTPException(502, f"No se pudo consultar ComfyUI: {exc}")


@app.get("/api/library/loras")
async def api_loras():
    try:
        return await library.get_loras(db.get_favorite_loras())
    except Exception as exc:
        raise HTTPException(502, f"No se pudo consultar LoRA Manager: {exc}")


@app.post("/api/library/loras/favorite")
def api_toggle_lora_favorite(req: LoraFavoriteRequest):
    db.set_lora_favorite(req.name, req.favorite)
    return {"favorites": sorted(db.get_favorite_loras())}


@app.get("/api/library/checkpoint-gallery")
async def api_checkpoint_gallery():
    try:
        return await library.get_checkpoint_library()
    except Exception as exc:
        raise HTTPException(502, f"No se pudo consultar LoRA Manager: {exc}")


@app.get("/api/library/preview")
async def api_library_preview(src: str):
    if not src.startswith("/api/lm/previews?"):
        raise HTTPException(400, "Ruta de preview inválida")
    try:
        content, content_type = await comfy_client.get_preview_bytes(src)
    except Exception as exc:
        raise HTTPException(502, f"No se pudo obtener el preview: {exc}")
    return Response(content=content, media_type=content_type)


@app.get("/api/library/sampling")
async def api_sampling():
    try:
        return await library.get_samplers_schedulers()
    except Exception as exc:
        raise HTTPException(502, f"No se pudo consultar ComfyUI: {exc}")


@app.get("/api/library/detector-models")
async def api_detector_models():
    try:
        info = await comfy_client.get_object_info("UltralyticsDetectorProvider")
        return info["UltralyticsDetectorProvider"]["input"]["required"]["model_name"][0]
    except Exception as exc:
        raise HTTPException(502, f"No se pudo consultar ComfyUI: {exc}")


@app.get("/api/library/ollama-models")
async def api_ollama_models():
    try:
        return await ollama_client.list_models()
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Ollama unreachable: {exc}")


# ---------- recipes ----------

@app.get("/api/recipes")
def api_list_recipes():
    return db.list_recipes()


@app.post("/api/recipes")
def api_save_recipe(req: SaveRecipeRequest):
    name = req.name.strip()
    if not name:
        raise HTTPException(400, "Nombre de receta vacío")
    recipe = req.model_dump()
    recipe["name"] = name
    recipe["loras_json"] = json.dumps(recipe.pop("loras"))
    db.save_recipe(recipe)
    return {"saved": name}


@app.delete("/api/recipes/{name}")
def api_delete_recipe(name: str):
    db.delete_recipe(name)
    return {"deleted": name}


# ---------- projects ----------

@app.get("/api/projects")
def api_list_projects():
    return db.list_projects()


@app.post("/api/projects")
def api_create_project(req: NewProjectRequest):
    name = req.name.strip().lower().replace(" ", "-")
    if not name:
        raise HTTPException(400, "Nombre de proyecto vacío")
    db.create_project(name)
    return {"name": name}


@app.post("/api/projects/rename")
def api_rename_project(req: RenameProjectRequest):
    if req.old_name == "(root)":
        raise HTTPException(400, "No se puede renombrar el proyecto root")
    new_name = req.new_name.strip().lower().replace(" ", "-")
    if not new_name:
        raise HTTPException(400, "Nombre de proyecto vacío")
    projects = db.list_projects()
    if req.old_name not in projects:
        raise HTTPException(404, "Proyecto no encontrado")
    if new_name != req.old_name and new_name in projects:
        raise HTTPException(400, f"Ya existe un proyecto llamado '{new_name}'")

    old_dir = config.COMFY_OUTPUT_DIR / req.old_name
    new_dir = config.COMFY_OUTPUT_DIR / new_name
    if new_name != req.old_name and old_dir.is_dir():
        if new_dir.exists():
            raise HTTPException(400, f"Ya existe una carpeta '{new_name}' en disco")
        old_dir.rename(new_dir)

    db.rename_project(req.old_name, new_name)
    return {"name": new_name}


# ---------- settings ----------

@app.get("/api/settings")
def api_get_settings():
    return db.get_settings()


@app.post("/api/settings")
def api_set_settings(req: dict):
    for key, value in req.items():
        if key in db.ALL_SETTINGS_DEFAULTS:
            db.set_setting(key, value)
    return db.get_settings()


# ---------- prompt enhancement ----------

@app.post("/api/enhance-prompt")
async def api_enhance_prompt(req: EnhancePromptRequest):
    if not req.prompt.strip():
        raise HTTPException(400, "Prompt is empty")
    try:
        model = db.get_settings().get("ollama_model")
        enhanced = await ollama_client.enhance_prompt(req.prompt, model)
    except httpx.HTTPError as e:
        raise HTTPException(502, f"Ollama unreachable: {e}")
    return {"prompt": enhanced}


# ---------- generation ----------

@app.post("/api/generate")
async def api_generate(req: GenerateRequest):
    params = req.model_dump()
    params["loras"] = [l for l in params["loras"]]
    graph, resolved_seed = workflow_builder.build_prompt_graph(params, db.get_settings())

    client_id = str(uuid.uuid4())
    try:
        result = await comfy_client.queue_prompt(graph, client_id, _ui_workflow_cache)
    except Exception as exc:
        raise HTTPException(502, f"ComfyUI rechazó el job: {exc}")

    prompt_id = result.get("prompt_id")
    if not prompt_id:
        raise HTTPException(502, f"Respuesta inesperada de ComfyUI: {result}")

    gen_id = str(uuid.uuid4())
    db.insert_generation(
        {
            "id": gen_id,
            "project": params["project"] or "(root)",
            "prompt_id": prompt_id,
            "status": "queued",
            "positive_prompt": params["positive_prompt"],
            "negative_prompt": params["negative_prompt"],
            "seed": resolved_seed,
            "width": params["width"],
            "height": params["height"],
            "batch_size": params["batch_size"],
            "steps": params["steps"],
            "cfg": params["cfg"],
            "sampler": params["sampler"],
            "scheduler": params["scheduler"],
            "checkpoint": params["checkpoint"],
            "loras_json": __import__("json").dumps(params["loras"]),
            "image_paths_json": "[]",
        }
    )
    db.create_project(params["project"] or "(root)")

    _progress_tasks[gen_id] = asyncio.create_task(_track_progress(gen_id, client_id))

    return {"generation_id": gen_id, "prompt_id": prompt_id, "seed": resolved_seed}


@app.get("/api/status/{generation_id}")
async def api_status(generation_id: str):
    gen = db.get_generation(generation_id)
    if not gen:
        raise HTTPException(404, "Generación no encontrada")

    if gen["status"] in ("done", "error"):
        _stop_tracking(generation_id)
        gen["last_log"] = ""
        return gen

    try:
        history = await comfy_client.get_history(gen["prompt_id"])
    except Exception as exc:
        raise HTTPException(502, f"No se pudo consultar el historial de ComfyUI: {exc}")

    entry = history.get(gen["prompt_id"])
    if not entry:
        gen["last_log"] = _last_log.get(generation_id, "")
        return gen  # still queued/running, no history entry yet

    gen = _apply_history_entry(generation_id, entry)
    gen["last_log"] = "" if gen["status"] in ("done", "error") else _last_log.get(generation_id, "")
    return gen


# ---------- history ----------

@app.get("/api/history")
def api_history(project: str = "__all__", limit: int = 60, offset: int = 0):
    return db.list_generations(project, limit, offset)


@app.post("/api/history/sync")
def api_history_sync():
    """Reconciles DB rows against files actually present on disk (e.g. after manual deletes)."""
    rows = db.list_generations("__all__", limit=100000)
    checked = 0
    updated = 0
    deleted = 0
    for g in rows:
        paths = json.loads(g["image_paths_json"] or "[]")
        if not paths:
            continue
        checked += 1
        existing = [p for p in paths if (config.COMFY_OUTPUT_DIR / p).is_file()]
        if len(existing) == len(paths):
            continue
        if existing:
            db.update_generation_status(g["id"], g["status"], existing)
            updated += 1
        else:
            db.delete_generation(g["id"])
            deleted += 1
    return {"checked": checked, "updated": updated, "deleted": deleted}


@app.get("/api/generation/{generation_id}")
def api_generation(generation_id: str):
    gen = db.get_generation(generation_id)
    if not gen:
        raise HTTPException(404, "Generación no encontrada")
    return gen


def _delete_generation_and_files(gen_id: str) -> bool:
    """Deletes a generation's row and any output files it references. Returns
    False if the row didn't exist."""
    gen = db.get_generation(gen_id)
    if not gen:
        return False
    for path in json.loads(gen["image_paths_json"] or "[]"):
        (config.COMFY_OUTPUT_DIR / path).unlink(missing_ok=True)
    db.delete_generation(gen_id)
    _stop_tracking(gen_id)
    return True


@app.delete("/api/history/{generation_id}")
def api_delete_generation(generation_id: str):
    if not _delete_generation_and_files(generation_id):
        raise HTTPException(404, "Generación no encontrada")
    return {"deleted": 1}


@app.post("/api/history/delete")
def api_delete_generations(req: DeleteHistoryRequest):
    deleted = sum(1 for gen_id in req.ids if _delete_generation_and_files(gen_id))
    return {"deleted": deleted}
