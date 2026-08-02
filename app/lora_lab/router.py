import shutil
import uuid

from fastapi import APIRouter, HTTPException, UploadFile

from .. import library
from . import dataset
from . import db as lab_db
from . import training
from .captioning import run_wd14_tagger
from .presets import PRESETS, estimate_steps
from .schemas import CaptionUpdateRequest, NewJobRequest, TrainRequest

router = APIRouter(prefix="/api/lora-lab", tags=["lora-lab"])


def _job_view(job: dict) -> dict:
    job = dict(job)
    job["images"] = dataset.list_images(job["id"])
    job["image_count"] = len(job["images"])
    return job


@router.get("/checkpoints")
async def list_checkpoints():
    try:
        return await library.get_checkpoints()
    except Exception as exc:
        raise HTTPException(502, f"No se pudo consultar ComfyUI: {exc}")


@router.get("/presets")
def list_presets(image_count: int = 0):
    out = {}
    for key, preset in PRESETS.items():
        out[key] = {**preset, "estimated_steps": estimate_steps(key, image_count) if image_count else None}
    return out


@router.get("/jobs")
def list_jobs():
    return [_job_view(j) for j in lab_db.list_jobs()]


@router.post("/jobs")
def create_job(req: NewJobRequest):
    name = req.name.strip()
    trigger = req.trigger_word.strip()
    if not name or not trigger:
        raise HTTPException(400, "Nombre y trigger word son obligatorios")
    job_id = str(uuid.uuid4())
    lab_db.create_job({"id": job_id, "name": name, "trigger_word": trigger, "checkpoint": req.checkpoint})
    dataset.job_dir(job_id)
    return _job_view(lab_db.get_job(job_id))


@router.get("/jobs/{job_id}")
def get_job(job_id: str):
    job = lab_db.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job no encontrado")
    return _job_view(job)


@router.delete("/jobs/{job_id}")
def delete_job(job_id: str):
    job = lab_db.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job no encontrado")
    if job["status"] == "training" and job["pid"] and training.is_pid_running(job["pid"]):
        training.cancel(job["pid"])
    shutil.rmtree(dataset.job_dir(job_id), ignore_errors=True)
    lab_db.delete_job(job_id)
    return {"deleted": True}


# ---------- images ----------

@router.post("/jobs/{job_id}/images")
async def upload_images(job_id: str, files: list[UploadFile]):
    job = lab_db.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job no encontrado")
    saved = []
    for f in files:
        data = await f.read()
        try:
            saved.append(dataset.save_image(job_id, f.filename or "image.png", data))
        except ValueError as exc:
            raise HTTPException(400, str(exc))
    lab_db.set_image_count(job_id, dataset.image_count(job_id))
    return _job_view(lab_db.get_job(job_id))


@router.delete("/jobs/{job_id}/images/{filename}")
def delete_image(job_id: str, filename: str):
    job = lab_db.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job no encontrado")
    dataset.delete_image(job_id, filename)
    lab_db.set_image_count(job_id, dataset.image_count(job_id))
    return _job_view(lab_db.get_job(job_id))


@router.put("/jobs/{job_id}/images/{filename}/caption")
def update_caption(job_id: str, filename: str, req: CaptionUpdateRequest):
    job = lab_db.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job no encontrado")
    try:
        dataset.write_caption(job_id, filename, req.caption)
    except FileNotFoundError:
        raise HTTPException(404, "Imagen no encontrada")
    return {"filename": filename, "caption": req.caption}


@router.post("/jobs/{job_id}/caption")
async def auto_caption(job_id: str):
    job = lab_db.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job no encontrado")
    if dataset.image_count(job_id) == 0:
        raise HTTPException(400, "Subí imágenes antes de etiquetar")
    lab_db.set_status(job_id, "captioning")
    try:
        await run_wd14_tagger(job_id, job["trigger_word"])
    except Exception as exc:
        lab_db.set_status(job_id, "dataset")
        raise HTTPException(502, f"El etiquetado automático falló: {exc}")
    lab_db.set_status(job_id, "ready")
    return _job_view(lab_db.get_job(job_id))


# ---------- training ----------

@router.post("/jobs/{job_id}/train")
def start_training(job_id: str, req: TrainRequest):
    job = lab_db.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job no encontrado")
    if job["status"] == "training":
        raise HTTPException(400, "Este job ya está entrenando")
    try:
        result = training.start_training(job_id, req.preset, req.checkpoint, job["name"], job["trigger_word"])
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    lab_db.start_training(
        job_id, req.preset, req.checkpoint, result["total_steps"], result["total_epochs"], result["pid"]
    )
    return _job_view(lab_db.get_job(job_id))


@router.post("/jobs/{job_id}/cancel")
def cancel_training(job_id: str):
    job = lab_db.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job no encontrado")
    if job["status"] != "training" or not job["pid"]:
        raise HTTPException(400, "Este job no está entrenando")
    training.cancel(job["pid"])
    lab_db.finish_job(job_id, "cancelled")
    return _job_view(lab_db.get_job(job_id))


@router.get("/jobs/{job_id}/status")
def job_status(job_id: str):
    job = lab_db.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job no encontrado")
    if job["status"] != "training":
        return _job_view(job)

    lines = training.read_log_tail(job_id)
    progress = training.parse_progress(lines)
    log_tail = "\n".join(lines[-15:])

    # The console window stays open after the pipeline ends (-NoExit, so the
    # user can read the output), so its process staying alive doesn't mean
    # training is still running — the exit-code file is the real signal.
    exit_code = training.read_exit_code(job_id)

    if exit_code is None:
        current_epoch = None
        if progress["current_step"] is not None and job["total_epochs"]:
            steps_per_epoch = max(1, round(job["total_steps"] / job["total_epochs"]))
            current_epoch = min(job["total_epochs"], progress["current_step"] // steps_per_epoch + 1)
        lab_db.update_progress(job_id, progress["current_step"], current_epoch, progress["loss"], log_tail)
        return _job_view(lab_db.get_job(job_id))

    # pipeline finished (window may still be open) — decide done vs error
    output_name = training.sanitize_output_name(job["name"])
    output_file = training.find_output_file(job_id, output_name)
    if exit_code == 0 and output_file is not None:
        published_name = training.publish_to_comfy(output_file)
        lab_db.update_progress(job_id, job["total_steps"], job["total_epochs"], job["loss"], log_tail)
        lab_db.finish_job(job_id, "done", output_path=published_name)
    else:
        tail_msg = "\n".join(lines[-6:]) or f"El proceso terminó con código {exit_code} sin generar un archivo de salida."
        lab_db.finish_job(job_id, "error", error_message=tail_msg)
    return _job_view(lab_db.get_job(job_id))
