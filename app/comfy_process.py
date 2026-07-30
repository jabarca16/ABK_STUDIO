"""Start/stop the ComfyUI process from ABK Studio, mirroring start.ps1's launch."""
import subprocess

from . import config


def _find_pid_on_port(port: int) -> int | None:
    result = subprocess.run(
        ["netstat", "-ano"], capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW
    )
    for line in result.stdout.splitlines():
        if f":{port} " in line and "LISTENING" in line:
            return int(line.split()[-1])
    return None


def is_running() -> bool:
    return _find_pid_on_port(config.COMFY_PORT) is not None


def start() -> bool:
    if is_running():
        return False
    comfy_start = config.COMFY_ROOT / "start.ps1"
    subprocess.Popen(
        [
            "powershell", "-NoExit", "-Command",
            f"$Host.UI.RawUI.WindowTitle = 'ComfyUI'; & '{comfy_start}'",
        ],
        creationflags=subprocess.CREATE_NEW_CONSOLE,
    )
    return True


def stop() -> bool:
    pid = _find_pid_on_port(config.COMFY_PORT)
    if pid is None:
        return False
    subprocess.run(
        ["taskkill", "/PID", str(pid), "/F", "/T"], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW
    )
    return True
