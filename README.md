# ABK Studio

Web para el workflow `Standard_V37` de ComfyUI: prompts, LoRAs (LoRA Manager), proyectos, tamaños, historial persistente.

Licencia: [PolyForm Noncommercial 1.0.0](LICENSE) — uso y modificación libres, uso comercial no permitido.

## Requisitos

- ComfyUI corriendo en `127.0.0.1:8188` (como siempre lo arrancas).
- Python 3.10+.
- ComfyUI debe tener instalados los custom nodes y modelos que usa el workflow `Standard_V37`, y el workflow mismo debe colocarse en `Workflow/` (no viene incluido en este repo) — ver [REQUIREMENTS.md](REQUIREMENTS.md).

## Primer arranque

```
cd C:\CodesA\Comfy\ComfyUI_ABKSTUDIO
venv\Scripts\python -m pip install -r requirements.txt   # solo la primera vez
```

## Arrancar el sitio

```
cd C:\CodesA\Comfy\ComfyUI_ABKSTUDIO
venv\Scripts\python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

- `--host 0.0.0.0` expone el sitio en tu red local (para verlo desde el celular u otro dispositivo): entra a `http://<IP-de-esta-PC>:8000`.
- Desde esta misma PC: `http://localhost:8000`.

## Estructura

- `Workflow/Standard_V37.api.json` — export en **formato API** del workflow (el que se envía a ComfyUI). Es el que usa la app; no editar a mano salvo que sepas lo que haces. **No está incluido en el repo** (ver [REQUIREMENTS.md](REQUIREMENTS.md)) — hay que colocarlo antes de arrancar.
- `Workflow/Standard_V37.json` — export en formato UI (el que abre el editor de ComfyUI). Se manda junto al anterior porque algunos nodos (ej. `WidgetToString` de KJNodes) lo necesitan para no truncar la ejecución. Tampoco está incluido en el repo.
- `app/` — backend FastAPI.
- `static/` — sitio (HTML/CSS/JS).
- `data/abkstudio.sqlite3` — historial persistente (se crea solo al primer arranque).

## Si actualizas el workflow en ComfyUI

Si cambias el grafo `Standard_V37` dentro de ComfyUI (nuevo nodo, reconexión, etc.), tienes que re-exportar **ambos** archivos y reemplazarlos en `Workflow/`:

1. Menú de ComfyUI → Workflow → Export (guarda el formato UI) → sobrescribe `Standard_V37.json`.
2. Menú de ComfyUI → Workflow → Export (API) → sobrescribe `Standard_V37.api.json`.

Si además cambian los IDs de los nodos que la app edita (prompt, LoRA, seed, tamaño, checkpoint, sampling, ruta de guardado), hay que actualizar los `NODE_*` en `app/workflow_builder.py` para que apunten a los nuevos IDs.
