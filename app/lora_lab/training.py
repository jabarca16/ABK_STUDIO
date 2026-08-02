import re
import shutil
import subprocess
from pathlib import Path

from .. import config
from . import dataset
from .presets import PRESETS

STEP_RE = re.compile(r"steps:\s*\d+%\|.*?\|\s*(\d+)/(\d+)\s*\[.*?(?:avr_loss=([\d.eE+-]+))?\]?\s*$")


def _quote_ps(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _build_dataset_toml(job_id: str, trigger_word: str, preset: dict) -> Path:
    images_path = str(dataset.images_dir(job_id)).replace("\\", "\\\\")
    content = f"""[general]
caption_extension = ".txt"
shuffle_caption = false
keep_tokens = 1

[[datasets]]
resolution = {preset["resolution"]}
batch_size = 1
enable_bucket = true
min_bucket_reso = 512
max_bucket_reso = 2048

  [[datasets.subsets]]
  image_dir = "{images_path}"
  num_repeats = {preset["num_repeats"]}
"""
    toml_path = dataset.job_dir(job_id) / "dataset.toml"
    toml_path.write_text(content, encoding="utf-8")
    return toml_path


def _resolve_checkpoint_path(checkpoint: str) -> Path:
    return config.COMFY_ROOT / "models" / "checkpoints" / checkpoint


def sanitize_output_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", name)[:60] or "lora"


def start_training(job_id: str, preset_key: str, checkpoint: str, name: str, trigger_word: str) -> dict:
    if preset_key not in PRESETS:
        raise ValueError(f"Preset desconocido: {preset_key}")
    preset = PRESETS[preset_key]

    n_images = dataset.image_count(job_id)
    if n_images == 0:
        raise ValueError("El dataset no tiene imágenes todavía")

    checkpoint_path = _resolve_checkpoint_path(checkpoint)
    if not checkpoint_path.is_file():
        raise ValueError(f"No se encontró el checkpoint: {checkpoint_path}")

    dataset_toml = _build_dataset_toml(job_id, trigger_word, preset)
    out_dir = dataset.output_dir(job_id)
    log_path = dataset.logs_dir(job_id) / "train.log"
    exit_code_path = dataset.logs_dir(job_id) / "exit_code.txt"
    exit_code_path.unlink(missing_ok=True)
    output_name = sanitize_output_name(name)

    total_steps = n_images * preset["num_repeats"] * preset["epochs"]

    train_args = [
        "sdxl_train_network.py",
        "--pretrained_model_name_or_path", str(checkpoint_path),
        "--dataset_config", str(dataset_toml),
        "--output_dir", str(out_dir),
        "--output_name", output_name,
        "--save_model_as", "safetensors",
        "--save_precision", "fp16",
        "--save_every_n_epochs", str(preset["epochs"]),
        "--max_train_epochs", str(preset["epochs"]),
        "--network_module", "networks.lora",
        "--network_dim", str(preset["network_dim"]),
        "--network_alpha", str(preset["network_alpha"]),
        "--network_train_unet_only",
        "--learning_rate", str(preset["learning_rate"]),
        "--lr_scheduler", "cosine",
        "--optimizer_type", "AdamW8bit",
        "--mixed_precision", "fp16",
        "--gradient_checkpointing",
        "--cache_latents",
        # Text encoders are only used to compute the fixed captions' embeddings
        # once (we don't train them — see --network_train_unet_only above), so
        # caching those outputs lets sd-scripts drop both SDXL text encoders
        # from VRAM for the rest of the run. Without this, a 6GB card sits at
        # ~5.8/6GB and Windows silently pages VRAM to system RAM instead of
        # erroring, which tanked a real run to 86s/step (~50h) instead of a
        # few seconds/step.
        "--cache_text_encoder_outputs",
        # Even with text encoders off-GPU, the frozen SDXL U-Net itself (fp16)
        # plus its gradient-checkpointing activations were still enough to
        # pin a 6GB card at ~5.8/6GB and stall — fp8 for the frozen base
        # weights (LoRA itself still trains at the --mixed_precision above)
        # is the other half of the standard low-VRAM combo.
        "--fp8_base",
        "--sdpa",
        "--max_data_loader_n_workers", "0",
        "--seed", "42",
        "--console_log_simple",
    ]

    ps_lines = [
        f"$Host.UI.RawUI.WindowTitle = 'ABK LoRA Lab - {name}'",
        f"Set-Location {_quote_ps(str(config.KOHYA_SD_SCRIPTS_DIR))}",
        "$trainArgs = @(",
    ]
    ps_lines += [f"  {_quote_ps(a)}" for a in ["launch", "--num_cpu_threads_per_process", "2"] + train_args]
    ps_lines.append(")")
    ps_lines.append(
        f"& {_quote_ps(str(config.KOHYA_ACCELERATE))} @trainArgs 2>&1 "
        f"| Tee-Object -FilePath {_quote_ps(str(log_path))}"
    )
    # $LASTEXITCODE reflects accelerate.exe's own exit code even though it's
    # piped through Tee-Object (a cmdlet, which doesn't touch it). Written to
    # its own file so the backend can tell the run is over even while this
    # window stays open (-NoExit) for the user to read the output.
    ps_lines.append("$code = $LASTEXITCODE")
    ps_lines.append(f"Set-Content -Path {_quote_ps(str(exit_code_path))} -Value $code")
    ps_lines.append('Write-Host ""')
    ps_lines.append('if ($code -eq 0) { Write-Host "Entrenamiento finalizado. Podes cerrar esta ventana." }')
    ps_lines.append('else { Write-Host "El entrenamiento terminó con error (codigo $code). Revisa el log arriba." }')

    script_path = dataset.job_dir(job_id) / "run.ps1"
    script_path.write_text("\r\n".join(ps_lines), encoding="utf-8")

    proc = subprocess.Popen(
        ["powershell", "-NoExit", "-ExecutionPolicy", "Bypass", "-File", str(script_path)],
        creationflags=subprocess.CREATE_NEW_CONSOLE,
    )

    return {"pid": proc.pid, "total_steps": total_steps, "total_epochs": preset["epochs"], "output_name": output_name}


def is_pid_running(pid: int) -> bool:
    result = subprocess.run(
        ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
        capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return str(pid) in result.stdout


def read_exit_code(job_id: str) -> int | None:
    """None means the training pipeline hasn't finished yet — this is checked
    instead of (not just alongside) process liveness, since the console
    window stays open after training ends (-NoExit) and would otherwise look
    like it's still running forever."""
    path = dataset.logs_dir(job_id) / "exit_code.txt"
    if not path.is_file():
        return None
    try:
        return int(path.read_text(encoding="utf-8", errors="ignore").strip())
    except ValueError:
        return None


def cancel(pid: int) -> None:
    subprocess.run(
        ["taskkill", "/PID", str(pid), "/F", "/T"],
        capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW,
    )


def read_log_tail(job_id: str, max_lines: int = 25) -> list[str]:
    log_path = dataset.logs_dir(job_id) / "train.log"
    if not log_path.is_file():
        return []
    with open(log_path, "rb") as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - 20_000))
        raw = f.read()
    # Tee-Object -Encoding utf8 still leaves room for a stray null-riddled
    # chunk if the tail cut lands mid multi-byte run; fall back to utf-16-le
    # when the raw bytes are clearly interleaved with nulls (PowerShell's
    # historical default encoding for redirected output).
    if raw.count(b"\x00") > len(raw) // 4:
        text = raw.decode("utf-16-le", errors="ignore")
    else:
        text = raw.decode("utf-8", errors="ignore")
    lines = [ln.strip() for ln in re.split(r"[\r\n]+", text) if ln.strip()]
    return lines[-max_lines:]


def parse_progress(lines: list[str]) -> dict:
    current_step = None
    loss = None
    for line in reversed(lines):
        m = STEP_RE.search(line)
        if m:
            current_step = int(m.group(1))
            if m.group(3):
                try:
                    loss = float(m.group(3))
                except ValueError:
                    loss = None
            break
    return {"current_step": current_step, "loss": loss}


def find_output_file(job_id: str, output_name: str) -> Path | None:
    out_dir = dataset.output_dir(job_id)
    candidate = out_dir / f"{output_name}.safetensors"
    if candidate.is_file():
        return candidate
    matches = sorted(out_dir.glob("*.safetensors"))
    return matches[-1] if matches else None


def publish_to_comfy(src: Path) -> str:
    config.COMFY_LORA_DIR.mkdir(parents=True, exist_ok=True)
    dest = config.COMFY_LORA_DIR / src.name
    n = 1
    while dest.exists():
        dest = config.COMFY_LORA_DIR / f"{src.stem}_{n}{src.suffix}"
        n += 1
    shutil.copy2(src, dest)
    return dest.name
