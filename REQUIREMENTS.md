# ComfyUI requirements for ABK Studio

ABK Studio **doesn't install anything in ComfyUI** — it just sends a graph to a ComfyUI instance that must already have the custom nodes and models that graph uses installed. If any of the following is missing, the generation fails with a "node type not found" error (or similar) when the prompt runs.

This list was obtained by inspecting the `class_type`s present in the original `Standard_V37` workflow and matching them against the custom nodes installed on this machine (`ComfyUI/custom_nodes`).

## The workflow is NOT included in this repo

`Workflow/*.json` is in `.gitignore` (see [Workflow origin](#workflow-origin) below — it's third-party content from Civitai, we don't redistribute it). Before starting the app you need to place the two files the backend expects there yourself, with these exact names:

- `Workflow/Standard_V37.json` — UI format export.
- `Workflow/Standard_V37.api.json` — API format export (the one actually sent to ComfyUI).

You can use the original Civitai workflow (link below) or your own, as long as it satisfies the **node contract** in the next section.

## Node contract (if you use your own workflow)

`app/workflow_builder.py` edits the graph by **fixed node ID**, writing specific fields. Your workflow — the Civitai one or your own — must have, at these exact IDs (or you must update the `NODE_*` constants in `workflow_builder.py` to point to whatever IDs you use), a node that accepts the listed field:

| ID | Constant | Field(s) written | Expected node type |
|---|---|---|---|
| 1 | `NODE_WIDTH` | `value` | primitive node (int) |
| 3 | `NODE_POSITIVE` | `wildcard_text`, `populated_text` | ImpactWildcardProcessor |
| 4 | `NODE_NEGATIVE` | `wildcard_text`, `populated_text` | ImpactWildcardProcessor |
| 5 | `NODE_LORA` | `loras` (`__value__` list), `text` | Lora Loader (LoraManager) |
| 12 | `NODE_HEIGHT` | `value` | primitive node (int) |
| 30 | `NODE_CHECKPOINT` | `ckpt_name` | CheckpointLoaderSimple |
| 32 | `NODE_SEED` | `seed` | Seed (rgthree) |
| 18 | `NODE_PARAMS` | `steps`, `cfg`, `sampler`, `scheduler` | KSampler |
| 29 | `NODE_BATCH` | `value` | primitive node (int) |
| 54 | `NODE_SAVE` | `path` | Image Saver |

The **output** side is flexible: `comfy_client.extract_output_images()` doesn't depend on any ID — it scans the whole `/history` response for any node that produces `images`. You can have whatever save/preview node you want, wherever you want, without touching code.

## Required custom nodes (via ComfyUI-Manager)

| Custom node (repo) | Nodes used by the workflow |
|---|---|
| **ComfyUI-Impact-Pack** | `FaceDetailerPipe`, `ToDetailerPipe`, `EditDetailerPipe`, `ImpactSwitch`, `ImpactWildcardProcessor` |
| **ComfyUI-Impact-Subpack** | `SAMLoader`, `UltralyticsDetectorProvider` |
| **ComfyUI-Easy-Use** | `easy int`, `easy showAnything` |
| **rgthree-comfy** | `Seed (rgthree)`, `Image Comparer (rgthree)` |
| **ComfyUI-Image-Saver** | `Image Saver`, `Input Parameters (Image Saver)` |
| **ComfyUI-LoRA-Manager** | `Lora Loader (LoraManager)`, `TriggerWord Toggle (LoraManager)` — also exposes the `/api/lm/*` REST API that ABK Studio's backend uses to list LoRAs/checkpoints and serve previews |
| **ComfyUI-KJNodes** | `WidgetToString` — reads the UI format export (`Standard_V37.json`), which is why ABK Studio sends both files when running |

All of these install from **ComfyUI-Manager** (`Manager → Install Custom Nodes`, search by repo name) or by cloning them manually into `ComfyUI/custom_nodes/`. Restart ComfyUI after installing.

## Nodes that need nothing extra (ComfyUI core)

`CheckpointLoaderSimple`, `CLIPSetLastLayer`, `CLIPTextEncode`, `EmptyLatentImage`, `KSampler`, `VAEDecode`, `PrimitiveBoolean`, `PrimitiveFloat`, `DifferentialDiffusion`, `RegexReplace`, `StringConcatenate` — included in any standard ComfyUI install (some, like `RegexReplace`/`StringConcatenate`/`DifferentialDiffusion`, require a reasonably recent ComfyUI version; update if yours is old).

## Required models

These names are *hardcoded* as defaults in the graph (`Standard_V37.api.json`); if they don't exist under that exact name in ComfyUI's models folder, the corresponding node fails to load:

- **SAMLoader** → `models/sams/sam_vit_b_01ec64.pth`
- **UltralyticsDetectorProvider** → `models/ultralytics/bbox/face_yolov8m.pt`
- **Checkpoint** (`CheckpointLoaderSimple`, `NODE_CHECKPOINT` node) and **LoRAs** (`Lora Loader (LoraManager)`) — not fixed: chosen by the user from ABK Studio's UI, but they must exist in `models/checkpoints/` and `models/loras/` respectively to show up in the selectors (the app lists them via `/object_info` and LoRA Manager's API).
  - The workflow is designed for checkpoints of the **Illustrious / SDXL / NoobAI** family (Clip Skip = 2, `CLIPSetLastLayer` node). Using a checkpoint from another family (SD1.5, FLUX, etc.) will likely break proportions/quality even if it technically loads.

Impact Pack / SAM / Ultralytics models are usually downloaded automatically the first time ComfyUI-Manager installs Impact Pack (it has a model installer), or you can place them manually at the paths above.

## Workflow origin

`Standard_V37` (and the `Advanced_V37`, `Basic_V37`, `Detailer_V37` variants also present in `Workflow/` but not currently used by ABK Studio) come from the "ComfyUI Image Workflows V37" package published on Civitai: https://civitai.com/models/1386234/comfyui-image-workflows

## Installation checklist summary

1. Install ComfyUI (if not already) + **ComfyUI-Manager**.
2. From Manager, install: `ComfyUI-Impact-Pack`, `ComfyUI-Impact-Subpack`, `ComfyUI-Easy-Use`, `rgthree-comfy`, `ComfyUI-Image-Saver`, `ComfyUI-LoRA-Manager`, `ComfyUI-KJNodes`.
3. Download the workflow (Civitai, link above, or your own compatible one) and place `Standard_V37.json` + `Standard_V37.api.json` in `Workflow/`.
4. Restart ComfyUI and confirm `Standard_V37.json` loads without red nodes ("missing node type") in ComfyUI's editor.
5. Verify `sam_vit_b_01ec64.pth` (in `models/sams`) and `face_yolov8m.pt` (in `models/ultralytics/bbox`) exist.
6. Place at least one checkpoint in `models/checkpoints` and (optionally) LoRAs in `models/loras`.
7. Start ComfyUI, then start ABK Studio (see `README.md`).
