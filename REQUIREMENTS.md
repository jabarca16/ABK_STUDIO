# Requisitos de ComfyUI para ABK Studio

ABK Studio **no instala nada en ComfyUI** — solo envía un grafo a una instancia de ComfyUI que ya debe tener instalados los custom nodes y modelos que ese grafo usa. Si falta alguno de los siguientes, la generación falla con un error de "node type not found" o similar al ejecutar el prompt.

Esta lista se obtuvo inspeccionando los `class_type` presentes en el workflow `Standard_V37` original y contrastándolos contra los custom nodes instalados en esta máquina (`ComfyUI/custom_nodes`).

## El workflow NO viene incluido en este repo

`Workflow/*.json` está en `.gitignore` (ver [Origen del workflow](#origen-del-workflow) más abajo — es contenido de un tercero en Civitai, no lo redistribuimos). Antes de arrancar la app tienes que colocar tú mismo ahí los dos archivos que el backend espera, con estos nombres exactos:

- `Workflow/Standard_V37.json` — export en formato UI.
- `Workflow/Standard_V37.api.json` — export en formato API (el que realmente se envía a ComfyUI).

Puedes usar el workflow original de Civitai (link abajo) o el tuyo propio, siempre que cumpla el **contrato de nodos** de la siguiente sección.

## Contrato de nodos (si usas tu propio workflow)

`app/workflow_builder.py` edita el grafo por **ID de nodo fijo**, escribiendo campos concretos. Tu workflow — el de Civitai o uno propio — debe tener, en estos IDs exactos (o debes actualizar las constantes `NODE_*` en `workflow_builder.py` para que apunten a los IDs que uses), un nodo que acepte el campo indicado:

| ID | Constante | Campo(s) que se escriben | Tipo de nodo esperado |
|---|---|---|---|
| 1 | `NODE_WIDTH` | `value` | nodo primitivo (int) |
| 3 | `NODE_POSITIVE` | `wildcard_text`, `populated_text` | ImpactWildcardProcessor |
| 4 | `NODE_NEGATIVE` | `wildcard_text`, `populated_text` | ImpactWildcardProcessor |
| 5 | `NODE_LORA` | `loras` (lista `__value__`), `text` | Lora Loader (LoraManager) |
| 12 | `NODE_HEIGHT` | `value` | nodo primitivo (int) |
| 30 | `NODE_CHECKPOINT` | `ckpt_name` | CheckpointLoaderSimple |
| 32 | `NODE_SEED` | `seed` | Seed (rgthree) |
| 18 | `NODE_PARAMS` | `steps`, `cfg`, `sampler`, `scheduler` | KSampler |
| 29 | `NODE_BATCH` | `value` | nodo primitivo (int) |
| 54 | `NODE_SAVE` | `path` | Image Saver |

El **output** es flexible: `comfy_client.extract_output_images()` no depende de ningún ID, recorre todo el `/history` buscando cualquier nodo que produzca `images` — puedes tener el nodo de guardado/preview que quieras, donde quieras, sin tocar código.

## Custom nodes requeridos (vía ComfyUI-Manager)

| Custom node (repo) | Nodos usados por el workflow |
|---|---|
| **ComfyUI-Impact-Pack** | `FaceDetailerPipe`, `ToDetailerPipe`, `EditDetailerPipe`, `ImpactSwitch`, `ImpactWildcardProcessor` |
| **ComfyUI-Impact-Subpack** | `SAMLoader`, `UltralyticsDetectorProvider` |
| **ComfyUI-Easy-Use** | `easy int`, `easy showAnything` |
| **rgthree-comfy** | `Seed (rgthree)`, `Image Comparer (rgthree)` |
| **ComfyUI-Image-Saver** | `Image Saver`, `Input Parameters (Image Saver)` |
| **ComfyUI-LoRA-Manager** | `Lora Loader (LoraManager)`, `TriggerWord Toggle (LoraManager)` — además expone la API REST `/api/lm/*` que usa el backend de ABK Studio para listar LoRAs/checkpoints y servir previews |
| **ComfyUI-KJNodes** | `WidgetToString` — lee el export en formato UI (`Standard_V37.json`), por eso ABK Studio manda ambos archivos al ejecutar |

Todos se instalan desde **ComfyUI-Manager** (`Manager → Install Custom Nodes`, buscar por el nombre del repo) o clonándolos manualmente en `ComfyUI/custom_nodes/`. Después de instalar, reiniciar ComfyUI.

## Nodos que NO requieren nada extra (son core de ComfyUI)

`CheckpointLoaderSimple`, `CLIPSetLastLayer`, `CLIPTextEncode`, `EmptyLatentImage`, `KSampler`, `VAEDecode`, `PrimitiveBoolean`, `PrimitiveFloat`, `DifferentialDiffusion`, `RegexReplace`, `StringConcatenate` — vienen incluidos en cualquier instalación estándar de ComfyUI (algunos, como `RegexReplace`/`StringConcatenate`/`DifferentialDiffusion`, requieren una versión relativamente reciente de ComfyUI; si tu instalación es vieja, actualízala).

## Modelos requeridos

Estos nombres están *hardcodeados* como default en el grafo (`Standard_V37.api.json`); si no existen con ese nombre exacto en la carpeta de modelos de ComfyUI, el nodo correspondiente falla al cargar:

- **SAMLoader** → `models/sams/sam_vit_b_01ec64.pth`
- **UltralyticsDetectorProvider** → `models/ultralytics/bbox/face_yolov8m.pt`
- **Checkpoint** (`CheckpointLoaderSimple`, nodo `NODE_CHECKPOINT`) y **LoRAs** (`Lora Loader (LoraManager)`) — no vienen fijos: los elige el usuario desde la UI de ABK Studio, pero deben existir en `models/checkpoints/` y `models/loras/` respectivamente para aparecer en los selectores (la app los lista vía `/object_info` y la API de LoRA Manager).
  - El workflow está diseñado para checkpoints de la familia **Illustrious / SDXL / NoobAI** (Clip Skip = 2, nodo `CLIPSetLastLayer`). Usar un checkpoint de otra familia (SD1.5, FLUX, etc.) probablemente rompe proporciones/calidad aunque técnicamente cargue.

Los modelos de Impact Pack / SAM / Ultralytics normalmente se descargan automáticamente la primera vez que ComfyUI-Manager instala Impact Pack (tiene un instalador de modelos), o manualmente colocándolos en las rutas de arriba.

## Origen del workflow

`Standard_V37` (y las variantes `Advanced_V37`, `Basic_V37`, `Detailer_V37` que también están en `Workflow/` pero que ABK Studio no usa actualmente) provienen del paquete "ComfyUI Image Workflows V37" publicado en Civitai: https://civitai.com/models/1386234/comfyui-image-workflows

## Resumen para la guía de instalación

1. Instalar ComfyUI (si no está) + **ComfyUI-Manager**.
2. Desde Manager, instalar: `ComfyUI-Impact-Pack`, `ComfyUI-Impact-Subpack`, `ComfyUI-Easy-Use`, `rgthree-comfy`, `ComfyUI-Image-Saver`, `ComfyUI-LoRA-Manager`, `ComfyUI-KJNodes`.
3. Descargar el workflow (Civitai, link abajo, o el tuyo propio compatible) y colocar `Standard_V37.json` + `Standard_V37.api.json` en `Workflow/`.
4. Reiniciar ComfyUI y confirmar que `Standard_V37.json` carga sin nodos rojos ("missing node type") en el editor de ComfyUI.
5. Verificar que existan `sam_vit_b_01ec64.pth` (en `models/sams`) y `face_yolov8m.pt` (en `models/ultralytics/bbox`).
6. Poner al menos un checkpoint en `models/checkpoints` y (opcional) LoRAs en `models/loras`.
7. Arrancar ComfyUI, luego arrancar ABK Studio (ver `README.md`).
