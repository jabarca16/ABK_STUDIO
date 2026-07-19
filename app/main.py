import asyncio
import json
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from . import comfy_client, config, db, library, workflow_builder
from .schemas import GenerateRequest, NewProjectRequest

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


@app.on_event("startup")
def on_startup():
    global _ui_workflow_cache
    db.init_db()
    _ui_workflow_cache = workflow_builder.load_ui_template()


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
        return await library.get_loras()
    except Exception as exc:
        raise HTTPException(502, f"No se pudo consultar LoRA Manager: {exc}")


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


# ---------- generation ----------

@app.post("/api/generate")
async def api_generate(req: GenerateRequest):
    params = req.model_dump()
    params["loras"] = [l for l in params["loras"]]
    graph, resolved_seed = workflow_builder.build_prompt_graph(params)

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

    status_info = entry.get("status", {})
    if status_info.get("completed"):
        image_paths = comfy_client.extract_output_images(entry)
        db.update_generation_status(generation_id, "done", image_paths)
        gen = db.get_generation(generation_id)
        _stop_tracking(generation_id)
        gen["last_log"] = ""
    elif status_info.get("status_str") == "error":
        db.update_generation_status(generation_id, "error", [])
        gen = db.get_generation(generation_id)
        _stop_tracking(generation_id)
        gen["last_log"] = ""
    else:
        db.update_generation_status(generation_id, "running")
        gen = db.get_generation(generation_id)
        gen["last_log"] = _last_log.get(generation_id, "")

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
