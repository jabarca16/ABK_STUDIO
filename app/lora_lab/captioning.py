import asyncio
import subprocess

from .. import config
from . import dataset


async def run_wd14_tagger(job_id: str, trigger_word: str) -> None:
    """Auto-tags every image in the job's dataset with WD14 (anime tagger),
    then prepends the trigger word to each resulting caption — the tagger's
    vocabulary is fixed (danbooru tags), so it can never predict a custom
    trigger word on its own; we have to add it ourselves afterward."""
    images_path = dataset.images_dir(job_id)
    args = [
        str(config.KOHYA_PYTHON),
        "finetune/tag_images_by_wd14_tagger.py",
        "--onnx",
        "--caption_extension", ".txt",
        "--thresh", "0.35",
        "--batch_size", "4",
        "--remove_underscore",
        str(images_path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *args,
        cwd=str(config.KOHYA_SD_SCRIPTS_DIR),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    output_lines = []
    if proc.stdout:
        async for raw in proc.stdout:
            output_lines.append(raw.decode(errors="ignore"))
    returncode = await proc.wait()
    if returncode != 0:
        tail = "".join(output_lines[-40:])
        raise RuntimeError(f"WD14 tagger falló (código {returncode}):\n{tail}")

    prefix = f"{trigger_word}, "
    for caption_path in images_path.glob("*.txt"):
        existing = caption_path.read_text(encoding="utf-8").strip()
        if not existing.startswith(trigger_word):
            caption_path.write_text(prefix + existing, encoding="utf-8")
