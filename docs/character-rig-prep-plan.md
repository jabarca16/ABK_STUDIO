# Character Rig Prep — plan de implementación

Módulo nuevo dentro de ABK Studio: toolbox para generar los insumos de imagen
(personaje base + capas separadas y alineadas) que alimentan el rigging en
Live2D Cubism / Spine. Vive como módulo aparte — no modifica el generador
estándar existente (Standard_V37 + `workflow_builder.py`).

Prototipo de UI discutido y aprobado (referencia visual, no funcional):
`docs/character-rig-prep-prototype.html` — 2 pantallas (Diseño base /
Separación de capas), tabs, layers strip con toggle de visibilidad, editor
de máscara a mano alzada. Ábrelo directo en el navegador para revisar el
flujo antes de implementar.

> **Estado**: plan revisado contra el código real y contra los custom_nodes
> instalados en `C:/CodesA/Comfy/ComfyUI`. Las secciones marcadas
> «⚠ verificar en Fase N» son las que no se pudieron confirmar sin ejecutar
> ComfyUI. Todo lo demás está comprobado.
>
> **Actualización — Fases 0 a 3 implementadas y probadas de punta a punta
> en esta rama** (`app/character_rig/`, `static/character-rig/`). Ver §12
> para el resumen de qué se validó, qué bugs reales se encontraron y
> corrigieron durante la prueba, y qué queda pendiente para la siguiente
> etapa (Fase 3b/4, más el hallazgo sobre precisión de la segmentación
> automática en arte anime).
>
> **Actualización 2 — se probó reemplazar `Human Parts Ultra` por
> `Florence2 Ultra`** (segmentación por texto) esperando mejor precisión en
> anime. Falla en este entorno: `transformers==5.12.1` instalado es
> demasiado nuevo para el código `trust_remote_code` de Florence2 (el
> `processor` carga como `None`). No se investigó más a fondo porque bajar
> la versión de `transformers` globalmente arriesga romper otros nodos que
> sí dependen de la versión nueva — **queda fuera de esta etapa, es trabajo
> de entorno aparte, no de este módulo**. Decisión: seguir con el flujo
> "propuesta automática (aunque venga vacía) + corrección manual con el
> pincel", que ya se probó y funciona bien (ver §12, capa `bottom_clothes`
> generada correctamente tras corrección manual).
>
> **Actualización 3 — Fase 3b (relleno de oclusión) implementada y probada
> contra ComfyUI real.** `workflow_builder.build_part_extract_occluded_graph`
> + endpoint `POST .../layers/{id}/generate-occluded` + reordenamiento de
> capas (▲▼) en el panel derecho del frontend. Probado con `bottom_clothes`
> ocluido por `top_clothes`: 28.521 píxeles cambiaron respecto al recorte
> simple (zona de solape real entre falda y torso), el relleno generativo
> se ve coherente (sin costuras visibles, hasta agregó detalles de botones
> consistentes con la prenda). Detalle importante: el `order_index` que se
> asigna al aprobar la base **no refleja apilamiento real** — es el orden
> fijo de `PART_KEYS`, por eso ahora hay que reordenar a mano con las
> flechas antes de generar con relleno. Ver §13 para el detalle completo.
>
> **Actualización 4 — Fase 4 (export) implementada: carpeta de PNGs en
> .zip, sin dependencias nuevas** (`zipfile` de la librería estándar, no
> `psd-tools`). Endpoint `GET /projects/{id}/export` junta cada capa con
> `image_path` (o sea, ya generada), la renombra `{order_index:02d}_
> {part_key}.png` para que un explorador de archivos cualquiera las liste
> en el orden de apilamiento correcto, agrega la imagen base como
> referencia y un `manifest.txt`. Probado con `TestClient` contra un
> proyecto real: 8 archivos, 11.6 MB, orden y nombres correctos. Botón
> "⬇ Exportar capas (.zip)" en el panel de Layers del frontend. De paso se
> encontró y corrigió un bug real en el polling: `layer_status` buscaba
> el resultado siempre en el nodo `"5"` (válido solo para el recorte
> simple) — el grafo de oclusión nombra su nodo de guardado `"save"`, así
> que el polling nunca lo iba a encontrar. Ahora escanea cualquier nodo de
> salida con imágenes, ya que cada grafo solo tiene uno.
>
> **Pendiente real de esta fase**: no se probó importar el .zip resultante
> en Live2D Cubism o Spine de verdad — se validó que el archivo se arma
> bien, no que el rigger lo abre sin problemas. Si el paso manual de
> arrastrar cada PNG resulta muy tedioso con muchas capas, un export a PSD
> multicapa (via `psd-tools`, agregando esa dependencia) sería el siguiente
> nivel — evaluarlo después de probar el flujo manual primero.

---

## 1. El problema central: oclusión (leer antes que nada)

Esta es la parte que define si el módulo sirve o no, y que la primera versión
del plan trataba de más. **Separar capas no es recortar.**

Cuando aíslas «pelo trasero» como capa, la porción que estaba *detrás de la
cabeza* no existe en la imagen base — nunca se dibujó. Si solo recortas por
máscara, al riggear y mover esa capa aparece un hueco. Lo mismo con el brazo
que tapa el torso, la falda que tapa las piernas, o el flequillo que tapa la
frente.

Entonces cada capa se compone de dos regiones distintas, con tratamiento
distinto:

| Región | Origen | Denoise |
|---|---|---|
| **Visible** — lo que sí se ve en la imagen base | píxeles originales, sin tocar | 0 (copiar tal cual) |
| **Ocluida** — lo que estaba tapado por capas de encima | inpaint generativo | alto |

Consecuencias de diseño que se derivan de esto:

- **La región visible NO debe regenerarse.** Si se pasa por el sampler aunque
  sea con denoise bajo, cada capa deriva un poco y los bordes dejan de casar
  entre sí. El workflow tiene que componer explícitamente:
  `original × máscara` (intacto) `+` `inpaint` (solo en la zona ocluida).
- **Hace falta una segunda máscara por capa**, no una: la máscara de la parte
  (qué es esta capa) y la máscara de extensión (hasta dónde inventar lo
  ocluido). En la práctica la de extensión se puede derivar dilatando la de
  la parte y restando las capas que van encima — pero es una decisión a
  tomar, no un detalle de implementación.
- **El orden de capas sí importa** (responde una de las preguntas abiertas):
  se necesita saber qué tapa a qué para calcular la zona ocluida. Live2D
  redefinirá el orden después, pero aquí es un input, no un adorno.

Recomendación: **Fase 3 se implementa primero con el caso trivial** (capa =
recorte por máscara, sin relleno de oclusión) para validar el circuito
completo, y el relleno de oclusión se aborda como Fase 3b una vez que la
tubería funciona end-to-end.

---

## 2. Principio de aislamiento

No tocar: `app/workflow_builder.py`, `static/index.html`, `static/js/app.js`,
`static/css/style.css`, `Workflow/Standard_V37*.json`, ni las tablas
existentes.

Puntos de contacto con el código actual — **tres líneas en `main.py`**, no dos
(la primera versión del plan olvidó el `init_db` del módulo):

```python
from .character_rig import router as rig_router      # 1
app.include_router(rig_router.router)                 # 2
# dentro de on_startup(): character_rig.db.init_db()  # 3
```

Estructura:

```
app/character_rig/
  __init__.py
  router.py           # APIRouter propio
  db.py               # tablas propias; reusa db.get_conn() (es un contextmanager reutilizable)
  schemas.py          # Pydantic models del módulo
  workflow_builder.py # mapeo de nodos propio + validate_template() propio
Workflow/
  CharacterBase_V1.json / .api.json
  PartExtract_V1.json / .api.json
static/character-rig/
  index.html · js/app.js · css/style.css
```

**Reuso confirmado:**
- `comfy_client.py` es genérico (`queue_prompt(graph, client_id)`) — sirve tal cual.
- `db.get_conn()` es un `@contextmanager` reutilizable desde otro módulo.
- `/outputs` ya está montado como `StaticFiles(COMFY_OUTPUT_DIR)` en
  `main.py:107` → todo lo que se escriba bajo `output/character_rig/...` es
  servible al navegador **sin plomería nueva**. Escribir ahí, no en otro lado.

---

## 3. Nodos ya instalados que cambian el enfoque

Revisión de `ComfyUI/custom_nodes` — hay mucho más disponible de lo que
asumía la primera versión del plan:

| Necesidad | Nodo real disponible |
|---|---|
| Segmentación anatómica automática | **`LayerMask: Human Parts Ultra`** (`comfyui_layerstyle`) |
| Recorte de fondo / matte fino | `LayerMask: BiRefNet Ultra V2`, `LayerMask: Ben Ultra`, `InspyrenetRembg` |
| Segmentación por texto | `LayerMask: Florence2 Ultra`, `LayerMask: EVF-SAM Ultra`, `GroundingDinoSAM2Segment` (`comfyui-sam2`) |
| Ajuste de máscara | `LayerMask: Mask Grow`, `Mask Edge Ultra Detail`, `MaskByColor` |
| Componer RGBA | `LayerUtility: ImageCombineAlpha` |
| Guardar en ruta arbitraria | `LayerUtility: SaveImage Plus` (tiene `custom_path`, formato png) |

**`Human Parts Ultra` reconoce 12 partes** (verificado en
`py/human_parts_ultra.py`): `face`, `hair`, `glasses`, `top_clothes`,
`bottom_clothes`, `torso_skin`, `left_arm`, `right_arm`, `left_leg`,
`right_leg`, `left_foot`, `right_foot`.

**Esto responde la pregunta abierta sobre asistencia del pincel:** no hay que
dibujar desde cero. El flujo correcto es **proponer y corregir**:

1. Al aprobar la base, se corre `Human Parts Ultra` una sola vez → 12 máscaras
   candidatas prellenadas en el strip de capas.
2. El usuario corrige con el pincel lo que el modelo no puede saber.

**Lo que el auto-segmentado NO resuelve** (y por eso el pincel sigue siendo
obligatorio): `hair` sale como **una sola máscara**. La separación
pelo-delantero / pelo-trasero — que es justamente la más importante para que
un rig 2.5D se vea bien — es una decisión de diseño, no un resultado de
segmentación. Igual pasa con accesorios sueltos (moños, aretes) y con
subdividir un brazo en segmentos para articulación.

⚠ Verificar en Fase 0: `Human Parts Ultra` descarga un modelo ONNX
(`deeplabv3p-resnet50-human`) la primera vez. Confirmar que baja bien y que
funciona con arte anime, no solo con fotos.

---

## 4. Transporte de la máscara hacia ComfyUI

Gap real del plan anterior: **`comfy_client.py` no tiene ninguna función de
upload**, y el plan asumía un `POST .../mask` que subiera el PNG.

Como el backend y ComfyUI corren en la misma máquina, la vía limpia es
**escribir el PNG de máscara directo en `ComfyUI/input/`** (la carpeta existe)
y referenciarlo con un nodo `LoadImage` normal. No hace falta endpoint de
upload en ComfyUI ni función nueva en `comfy_client`.

Implica:
- Añadir `COMFY_INPUT_DIR = COMFY_ROOT / "input"` a `config.py` (una línea,
  es aditiva y no rompe nada).
- Nombrar los archivos de forma única por proyecto+capa para que dos
  proyectos abiertos no se pisen: `rigprep_<project_id>_<part_key>.png`.
- El front manda el trazo como **base64 (`canvas.toDataURL()`) en JSON**, no
  como `multipart`. Motivo: `UploadFile` de FastAPI requiere
  `python-multipart`, que **no está en `requirements.txt`** hoy; base64 se
  decodifica con `base64.b64decode` y se escribe con `open(...,'wb')`, sin
  dependencias nuevas.

---

## 5. Modelo de datos

```sql
CREATE TABLE IF NOT EXISTS character_projects (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  created_at TEXT NOT NULL,
  base_image_path TEXT,        -- null hasta aprobar el paso 1
  base_prompt TEXT,
  base_params_json TEXT,       -- checkpoint/loras/seed/pose/paleta al aprobar
  status TEXT NOT NULL         -- 'drafting_base' | 'separating_layers' | 'ready'
);

CREATE TABLE IF NOT EXISTS character_layers (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES character_projects(id),
  part_key TEXT NOT NULL,      -- 'hair_back' | 'torso_skin' | ... | custom
  display_name TEXT NOT NULL,
  order_index INTEGER NOT NULL,-- input real del pipeline: define qué ocluye a qué (§1)
  mask_path TEXT,              -- máscara de la parte
  image_path TEXT,             -- PNG RGBA resultante
  status TEXT NOT NULL,        -- 'pendiente' | 'trazada' | 'generada'
  prompt_id TEXT,              -- job de ComfyUI en curso para esta capa
  job_status TEXT              -- 'queued' | 'running' | 'done' | 'error'
);
```

`base_params_json` debe guardar **el seed y el checkpoint exactos** de la
imagen aprobada: las capas se generan después y tienen que casar en estilo con
la base.

Nota de concurrencia: el `_reconcile_pending_loop` y `_progress_tasks` de
`main.py` están atados a la tabla `generations`; no cubren estas filas. Por eso
`character_layers` lleva su propio `prompt_id`/`job_status` y el módulo hace su
propio polling contra `/history` (misma mecánica que `api_status`, código
distinto). ComfyUI tiene **una sola cola**: generar 8 capas son 8 jobs
secuenciales, la UI debe reflejar eso (progreso por capa, no barra global).

---

## 6. Endpoints (`/api/character-rig/...`)

| Método | Ruta | Qué hace |
|---|---|---|
| `POST` | `/projects` | crea proyecto (nombre, estilo, descripción, pose, paleta) |
| `POST` | `/projects/{id}/generate-base` | encola `CharacterBase_V1` |
| `POST` | `/projects/{id}/approve-base` | fija base + seed, corre auto-segmentado, crea filas `character_layers` |
| `PUT` | `/projects/{id}/layers/{lid}/mask` | guarda máscara (base64 → `ComfyUI/input/`) |
| `POST` | `/projects/{id}/layers/{lid}/generate` | encola `PartExtract_V1` |
| `GET` | `/projects/{id}` | estado completo (base + capas) para repintar al recargar |
| `GET` | `/projects/{id}/layers/{lid}/status` | polling del job de esa capa |
| `PATCH` | `/projects/{id}/layers/{lid}` | renombrar / reordenar / eliminar |
| `GET` | `/projects` | listado para el selector de proyectos |

---

## 7. Workflows de ComfyUI

Se diseñan y exportan a mano en el editor (igual que Standard_V37), luego se
transcribe el mapa de node IDs en `character_rig/workflow_builder.py` con su
propio `validate_template()` como tripwire — el mismo patrón que ya salvó al
Standard.

**`CharacterBase_V1`** — checkpoint + LoRA + prompt/pose/paleta → imagen.
Variante reducida del Standard, sin los toggles de ADetailer/HiresFix.

**`PartExtract_V1`** — el corazón del módulo:

```
LoadImage(base) ─┬─────────────────────────────┐
                 │                             ▼
LoadImage(mask) ─┴─► [dilatar/restar] ─► inpaint (zona ocluida, denoise alto)
                 │                             │
                 └─► región visible (denoise 0)┤
                                               ▼
                                    componer visible + ocluido
                                               ▼
                              ImageCombineAlpha (RGBA con la máscara)
                                               ▼
                        SaveImage Plus (custom_path, format=png)
```

⚠ Verificar en Fase 3: que `SaveImage Plus` preserve el canal alfa al
guardar (recibe `IMAGE`; en ComfyUI eso suele ser RGB de 3 canales). Si lo
aplasta, la alternativa es guardar con el nodo de guardado que sí respete
RGBA, o componer el alfa en Python al recibir el resultado. **`format` debe
ser `png` siempre — `jpg` destruye el alfa.**

---

## 8. Frontend

Vanilla JS, sin framework — mismo enfoque que el resto de ABK Studio, para no
meter una segunda stack de UI. Página independiente en `/toolbox/character-rig`.

Cambio respecto al prototipo, derivado de §3: la pantalla 2 ya no arranca en
blanco. Al entrar, el strip de capas viene **prellenado con las partes
detectadas automáticamente**, y el pincel pasa a ser herramienta de
*corrección* (añadir/quitar de una máscara existente), no de creación desde
cero. Conviene reflejar eso en el prototipo antes de implementar: un estado
«propuesta» además de pendiente/trazada/generada.

---

## 9. Dependencias nuevas

`requirements.txt` hoy tiene solo: fastapi, uvicorn, httpx, pydantic, websockets.

- **Fases 0–3**: ninguna dependencia nueva (base64 es stdlib).
- **Fase 4 (export PSD)**: `psd-tools` — o mejor `pytoshop`/`psd-tools` para
  *escritura*. Ojo: LayerStyle tiene `LayerUtility: Load PSD` pero **no existe
  un nodo de guardar PSD**, así que el empaquetado PSD es código Python del
  lado de ABK Studio, no un nodo de ComfyUI.

---

## 10. Fases

| Fase | Entregable | Riesgo |
|---|---|---|
| **0 — Andamiaje** | `app/character_rig/` con router montado, tablas creadas, página estática navegable sin lógica. Confirma aislamiento. | bajo |
| **1 — Diseño base** | `CharacterBase_V1` + `generate-base` + pantalla 1 real (generar, iterar, aprobar). | bajo |
| **2 — Máscaras** | Auto-segmentado con `Human Parts Ultra` al aprobar + canvas de corrección + persistencia en `ComfyUI/input/`. Sin generar capas aún. | medio — validar el modelo ONNX con arte anime |
| **3 — Extracción simple** | `PartExtract_V1` en modo recorte (sin oclusión) → PNGs RGBA reales, strip funcional. Valida la tubería completa. | medio — alfa en el guardado |
| **3b — Oclusión** | Relleno generativo de zonas tapadas (§1). El paso que hace las capas realmente riggeables. | **alto — es el corazón del problema** |
| **4 — Export** | Nomenclatura + estructura de carpetas para Live2D/Spine; opcionalmente PSD multicapa vía `psd-tools`. | medio |

Cada fase es demostrable por separado y no depende de tener las siguientes
diseñadas en detalle.

---

## 11. Preguntas abiertas

1. ~~¿El pincel necesita asistencia?~~ **Resuelto** (§3): auto-segmentado con
   `Human Parts Ultra` + corrección manual.
2. ~~¿El orden de capas importa o lo define Live2D?~~ **Resuelto** (§1): es
   input del pipeline, se necesita para calcular oclusión.
3. **¿Partes fijas o libres?** Recomendación: partir de las 12 de
   `Human Parts Ultra` como base fija, más partes custom añadibles por el
   usuario (pelo delantero/trasero y accesorios *tienen* que ser custom —
   ninguna sale del auto-segmentado).
4. **¿Cuerpo completo o busto?** El prototipo asume busto. Cuerpo completo
   multiplica las capas (piernas, pies) y la superficie de oclusión. Sugiero
   fijar busto para las Fases 0–3 y evaluar cuerpo completo después.
5. **¿Resolución de trabajo?** Live2D suele pedir assets grandes (2K+) porque
   el rig deforma píxeles. Generar a 1024 y escalar degrada. Definir antes de
   la Fase 1, porque condiciona el workflow base.

---

## 12. Implementación Fases 0–3 (hecha y probada en esta rama)

Código: `app/character_rig/{router,db,workflow_builder,schemas}.py`,
`static/character-rig/{index.html,js/app.js,css/style.css}`, 3 líneas de
contacto en `app/main.py` (import + `include_router` + `init_db` + la ruta
`GET /toolbox/character-rig`, que en la práctica fueron 4 líneas, no 3).

Se probó **de punta a punta con ComfyUI real corriendo**: crear proyecto →
generar imagen base (SDXL, 30 steps) → aprobar → segmentación automática
(12 pasadas de `Human Parts Ultra`) → generar una capa real con
`PartExtract_V1` → verificar el PNG resultante con canal alfa correcto
(`opaque_pct` medido con PIL/numpy, no solo "se ve bien").

### Grafos de ComfyUI: construidos en Python, no exportados del editor

A diferencia del Standard (que parte de un JSON exportado a mano desde el
editor), `CharacterBase_V1` y `PartExtract_V1`/segmentación se arman
directo como dicts API-format en `workflow_builder.py`, contra los schemas
reales consultados vía `/object_info/<ClassType>` en el ComfyUI de esta
máquina. Son grafos lineales simples — no hace falta la maqueta del editor
para estos dos. Checkpoint por defecto de prueba:
`Illustrious-XL-v0.1.safetensors` (SDXL).

### Tres bugs reales encontrados y corregidos durante la prueba

1. **Modelo ONNX de `Human Parts Ultra` no estaba instalado.** El nodo no
   lo descarga solo — falla con `NO_SUCHFILE` si falta. Se descargó a mano
   `deeplabv3p-resnet50-human.onnx` (~47 MB) a
   `ComfyUI/models/onnx/human-parts/`. **Esto es una dependencia de entorno
   que cualquier instalación nueva va a necesitar** — documentar en el
   README del módulo cuando se prepare para otra máquina.
2. **`SaveImageWithAlpha` (KJNodes) invierte la máscara**: calcula
   `alpha = 1 - mask`, porque asume la convención "mask=1 es agujero"
   (la de inpainting). Nuestras máscaras de parte usan la convención
   opuesta (1 = esto es lo que quiero conservar), así que sin corrección
   cada capa salía con la parte transparente y **todo lo demás opaco** —
   exactamente al revés. Fix: nodo `InvertMask` (core) entre la máscara y
   `SaveImageWithAlpha`, en `build_part_extract_graph`. Verificado
   numéricamente (`opaque_pct` pasó de 93.96% a 4.58%, coincidiendo con el
   área real de la máscara) — la inspección visual sola no lo detecta
   porque el visor de imágenes usado para revisar renderiza alfa=0 sobre un
   gris parecido al fondo original del personaje.
3. **`approve-base` no era idempotente** y el botón "Aprobar" del frontend
   nunca se reactivaba tras un error (`finally` faltante) — un reintento
   habría duplicado las 12 filas de `character_layers`. Corregido: el
   router ahora reutiliza las filas existentes por `part_key`
   (`reset_layer_for_resegment`) en vez de crear otro set, y el botón se
   reactiva siempre en `finally`.

### Hallazgo importante (no es un bug, es una limitación real del modelo)

`Human Parts Ultra` (DeepLabV3+ ResNet50 entrenado con **fotos reales**) no
generaliza bien a ilustración anime en un close-up extremo:

- `face`, `hair`, `torso_skin`, brazos/piernas/pies salieron **con máscara
  completamente vacía** (0 píxeles detectados) sobre un busto anime en
  primer plano.
- `top_clothes` sí produjo una máscara con contenido, pero **mal
  etiquetada** — el área detectada correspondía en realidad a un mechón de
  pelo suelto, no a la ropa.

Esto no invalida el enfoque (§3 ya anticipaba que el pincel de corrección
manual seguiría siendo obligatorio), pero sí baja las expectativas: para
arte anime, el auto-segmentado hoy funciona más como *ruido de partida*
que como propuesta confiable, especialmente en encuadres muy cerrados.
Antes de construir más UI alrededor de "propuesta automática", vale la
pena, en la siguiente etapa, probar `LayerMask: Florence2 Ultra` o
`LayerMask: EVF-SAM Ultra` (segmentación por texto/VLM en vez de
clasificador fijo entrenado con fotos) contra el mismo personaje y comparar
antes de invertir más tiempo en pulir el flujo de "propuesta + corrección"
sobre `Human Parts Ultra` tal cual.

### Gaps conocidos que quedaron para la siguiente etapa

- El frontend no persiste "proyecto actual" entre recargas de página más
  allá del selector manual de "proyectos existentes" — no bloquea el uso,
  pero conviene un `localStorage` con el último proyecto abierto.
- Las rutas relativas de ComfyUI en Windows mezclan `\` y `/`
  (`character_rig\<id>\base/...png`) porque el `subfolder` que devuelve
  `/history` usa el separador nativo del SO. Funciona porque cliente y
  servidor están en la misma máquina Windows, pero es una asunción frágil
  si el módulo se usara en otro SO.
- No se probó el editor de máscara (dibujar con el mouse en el `<canvas>`
  del navegador) con una interacción real de usuario — sí se probó el
  endpoint `PUT .../mask` mecánicamente. Sesión siguiente: abrir el
  navegador, dibujar de verdad sobre `face` o `hair` (que quedaron con
  máscara vacía) y confirmar que la corrección manual + generación de esa
  capa cierra el círculo.
- Fase 3b (relleno de oclusión) y Fase 4 (export) siguen sin empezar, tal
  como se planeó — son las de mayor riesgo/investigación y se dejaron
  fuera de esta etapa a propósito.

---

## 13. Implementación Fase 3b (hecha y probada contra ComfyUI real)

Se implementó exactamente el diseño de §1 (visible = original sin tocar,
ocluido = inpaint) usando operaciones de máscara del lado de ComfyUI
(`MaskComposite` con `and`/`or`/`subtract`), no en Python — mantiene el
principio de que ABK Studio nunca toca píxeles, solo orquesta grafos (no se
agregó Pillow/numpy al backend, que no los tenía instalados).

### Cómo funciona `build_part_extract_occluded_graph`

1. Carga la máscara de la parte (`part_mask`, la de siempre) y la de cada
   capa "ocluyente" (las que están por encima en `order_index`).
2. Une todas las máscaras ocluyentes con `MaskComposite(operation="or")`
   encadenados.
3. `occluded_mask = part_mask AND occluder_union` — la zona de esta parte
   que otra tapa.
4. `visible_mask = part_mask SUBTRACT occluded_mask` — el resto.
5. Corre un inpaint normal (`VAEEncodeForInpaint` → `KSampler` denoise=0.85
   → `VAEDecode`) sobre **toda** la imagen usando `occluded_mask`.
6. `ImageCompositeMasked` pisa el resultado del inpaint con los píxeles
   **originales** dondequiera que `visible_mask=1` — así la regla de §1
   ("la región visible no se regenera") se cumple aunque el sampler haya
   corrido sobre el cuadro completo.
7. El canal alfa final sigue siendo el `part_mask` completo (igual que en
   el recorte simple) — lo que cambia es el contenido debajo, no la forma
   recortada.

El prompt del inpaint reusa `description + art_style + pose` del proyecto
(la misma composición que ya arma el frontend para la base) — no hay campo
`base_prompt` separado, esa columna nunca se llena (se detectó y corrigió
al escribir esto: el código original leía `project["base_prompt"]`, que
siempre es `NULL`).

### Endpoint

`POST /projects/{id}/layers/{layer_id}/generate-occluded` — junta las
capas con `order_index` mayor que la seleccionada y que ya tengan máscara,
arma el grafo, lo encola. Si no hay ninguna capa por encima, responde 400
pidiendo usar el recorte simple (`/generate`) en su lugar — correr un
`KSampler` sobre una máscara vacía sería gasto de GPU sin ningún beneficio.

### El hallazgo importante: el orden de capas no era real

`order_index` se asigna al aprobar la base siguiendo el orden fijo de
`PART_KEYS` (face, hair, glasses, top_clothes...) — **no tiene ninguna
relación con qué tapa a qué** en el dibujo real. Sin arreglar esto, la
oclusión calcularía basura. Se agregó:

- Botones **▲▼** en cada fila del panel de Layers (frontend) que
  intercambian `order_index` con el vecino, vía el endpoint `PATCH` que ya
  existía pero no estaba conectado a ninguna UI.
- Convención: la lista se muestra ordenada por `order_index` ascendente;
  **una capa más abajo en la lista oculta a las de arriba** (mayor
  `order_index` = más al frente). El hint box de la pantalla lo explica.

Sigue siendo trabajo manual del usuario reordenar antes de generar con
relleno — no hay heurística automática de profundidad. Aceptable para esta
etapa; si se vuelve tedioso con muchas capas, se podría explorar más
adelante que Florence2/EVF-SAM (cuando se arregle el entorno) estime
profundidad relativa, pero no es un bloqueo hoy.

### Prueba real hecha

Grafo enviado directo a ComfyUI (sin pasar por ABK Studio, para aislar
errores de nodo) usando `bottom_clothes` (falda) ocluida por `top_clothes`
(torso) de un proyecto real. Resultado:

- Sin errores de ejecución (`node_errors: {}`, `status: success`).
- Diff píxel a píxel contra el recorte simple: 28.521 píxeles cambiaron de
  forma notoria (de ~1M totales) — confirma que el inpaint realmente actuó
  sobre la zona de solape, no que quedó en no-op.
- Inspección visual (compuesto sobre checkerboard): sin costuras visibles
  en el borde relleno, el modelo hasta agregó detalles de botones
  consistentes con la prenda en la zona rellenada.

### Pendiente de esta fase para cuando se retome

- No probado con una capa que tenga **oclusión grande** (ej. pelo trasero
  detrás de toda la cabeza) — el caso probado fue un solape chico
  (cintura). Zonas grandes ocluidas son más riesgosas para el inpaint
  (más superficie "inventada", más chance de que no combine con el resto).
- El seed usado es el de la imagen base (`project["seed"]`) — no hay control
  para variar el seed del inpaint en particular si el primer resultado no
  convence; podría agregarse como parámetro del endpoint.
- No se agregó UI para visualizar "qué ocluye a qué" antes de generar (ej.
  resaltar en el lienzo qué región va a rellenarse) — el usuario solo lo ve
  después, en el resultado.
