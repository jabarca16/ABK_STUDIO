from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

COMFY_HOST = "127.0.0.1"
COMFY_PORT = 8188
COMFY_BASE_URL = f"http://{COMFY_HOST}:{COMFY_PORT}"

COMFY_ROOT = Path("C:/CodesA/Comfy/ComfyUI")
COMFY_OUTPUT_DIR = COMFY_ROOT / "output"
COMFY_LORA_DIR = COMFY_ROOT / "models" / "loras"

KOHYA_ROOT = Path("C:/CodesA/Comfy/Kohya_ss")
KOHYA_SD_SCRIPTS_DIR = KOHYA_ROOT / "sd-scripts"
KOHYA_PYTHON = KOHYA_ROOT / "venv" / "Scripts" / "python.exe"
KOHYA_ACCELERATE = KOHYA_ROOT / "venv" / "Scripts" / "accelerate.exe"

LORA_JOBS_DIR = PROJECT_ROOT / "data" / "lora_jobs"

WORKFLOW_DIR = PROJECT_ROOT / "Workflow"
DEFAULT_WORKFLOW = WORKFLOW_DIR / "Standard_V37.api.json"
UI_WORKFLOW = WORKFLOW_DIR / "Standard_V37.json"

DB_PATH = PROJECT_ROOT / "data" / "abkstudio.sqlite3"

STATIC_DIR = PROJECT_ROOT / "static"

MAX_BATCH_SIZE = 4

OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_MODEL = "llama3.1:8b"
