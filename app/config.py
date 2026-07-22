from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

COMFY_HOST = "127.0.0.1"
COMFY_PORT = 8188
COMFY_BASE_URL = f"http://{COMFY_HOST}:{COMFY_PORT}"

COMFY_ROOT = Path("C:/CodesA/Comfy/ComfyUI")
COMFY_OUTPUT_DIR = COMFY_ROOT / "output"

WORKFLOW_DIR = PROJECT_ROOT / "Workflow"
DEFAULT_WORKFLOW = WORKFLOW_DIR / "Standard_V37.api.json"

DB_PATH = PROJECT_ROOT / "data" / "abkstudio.sqlite3"

STATIC_DIR = PROJECT_ROOT / "static"

MAX_BATCH_SIZE = 4

OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_MODEL = "llama3.1:8b"
