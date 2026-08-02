import re
from pathlib import Path

from .. import config

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def job_dir(job_id: str) -> Path:
    d = config.LORA_JOBS_DIR / job_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def images_dir(job_id: str) -> Path:
    d = job_dir(job_id) / "images"
    d.mkdir(parents=True, exist_ok=True)
    return d


def logs_dir(job_id: str) -> Path:
    d = job_dir(job_id) / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def output_dir(job_id: str) -> Path:
    d = job_dir(job_id) / "output"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_stem(filename: str) -> str:
    stem = Path(filename).stem
    stem = re.sub(r"[^A-Za-z0-9_-]", "_", stem)[:80]
    return stem or "image"


def save_image(job_id: str, filename: str, data: bytes) -> str:
    ext = Path(filename).suffix.lower()
    if ext not in IMAGE_EXTENSIONS:
        raise ValueError(f"Formato no soportado: {ext}")
    stem = _safe_stem(filename)
    target_dir = images_dir(job_id)
    candidate = f"{stem}{ext}"
    n = 1
    while (target_dir / candidate).exists():
        candidate = f"{stem}_{n}{ext}"
        n += 1
    (target_dir / candidate).write_bytes(data)
    return candidate


def delete_image(job_id: str, filename: str) -> None:
    target_dir = images_dir(job_id)
    (target_dir / filename).unlink(missing_ok=True)
    (target_dir / f"{Path(filename).stem}.txt").unlink(missing_ok=True)


def list_images(job_id: str) -> list[dict]:
    target_dir = images_dir(job_id)
    items = []
    for path in sorted(target_dir.iterdir()):
        if path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        caption_path = path.with_suffix(".txt")
        items.append(
            {
                "filename": path.name,
                "caption": caption_path.read_text(encoding="utf-8") if caption_path.exists() else "",
            }
        )
    return items


def write_caption(job_id: str, filename: str, caption: str) -> None:
    target_dir = images_dir(job_id)
    image_path = target_dir / filename
    if not image_path.exists():
        raise FileNotFoundError(filename)
    image_path.with_suffix(".txt").write_text(caption.strip(), encoding="utf-8")


def image_count(job_id: str) -> int:
    return len(list_images(job_id))
