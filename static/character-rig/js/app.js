(function () {
  "use strict";

  // ---- theme menu (same behavior/localStorage key as the main Studio page) ----
  const root = document.documentElement;
  const themeToggle = document.getElementById("themeToggle");
  const themeMenu = document.getElementById("themeMenu");
  const themeMenuWrap = document.getElementById("themeMenuWrap");

  function applyTheme(name) {
    root.setAttribute("data-theme", name);
    localStorage.setItem("abkTheme", name);
    themeMenu.querySelectorAll(".theme-menu-item").forEach((el) => {
      el.classList.toggle("active", el.dataset.themeChoice === name);
    });
  }
  applyTheme(
    localStorage.getItem("abkTheme") ||
      (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")
  );
  themeToggle.addEventListener("click", (e) => {
    e.stopPropagation();
    themeMenu.classList.toggle("open");
  });
  themeMenu.querySelectorAll(".theme-menu-item").forEach((btn) => {
    btn.addEventListener("click", () => {
      applyTheme(btn.dataset.themeChoice);
      themeMenu.classList.remove("open");
    });
  });
  document.addEventListener("click", (e) => {
    if (!themeMenuWrap.contains(e.target)) themeMenu.classList.remove("open");
  });

  const API = "/api/character-rig";
  const state = {
    project: null,
    iterations: [],
    selectedIterationId: null,
    layers: [],
    activeLayerId: null,
  };

  const $ = (id) => document.getElementById(id);

  async function api(path, options) {
    const resp = await fetch(API + path, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
    if (!resp.ok) {
      const text = await resp.text().catch(() => "");
      throw new Error(`${resp.status} ${text}`);
    }
    return resp.json();
  }

  // ---------- tabs ----------
  document.querySelectorAll(".rig-tab").forEach((t) => {
    t.addEventListener("click", () => {
      document.querySelectorAll(".rig-tab").forEach((x) => x.classList.remove("active"));
      t.classList.add("active");
      document.querySelectorAll(".rig-screen").forEach((s) => s.classList.remove("active"));
      $(t.dataset.screen).classList.add("active");
    });
  });

  function goToScreen(name) {
    document.querySelectorAll(".rig-tab").forEach((x) => x.classList.toggle("active", x.dataset.screen === name));
    document.querySelectorAll(".rig-screen").forEach((s) => s.classList.toggle("active", s.id === name));
  }

  // ---------- server status (same status-tag component/markup as the main Studio page) ----------
  async function pollHealth() {
    const tag = $("serverStatus");
    try {
      const resp = await fetch("/api/health");
      const data = await resp.json();
      tag.dataset.state = data.status;
      tag.querySelector(".status-label").textContent = data.status;
    } catch {
      tag.dataset.state = "down";
      tag.querySelector(".status-label").textContent = "down";
    }
  }
  pollHealth();
  setInterval(pollHealth, 8000);

  // ---------- Screen 1: project + base image ----------
  async function loadCheckpoints() {
    try {
      const list = await (await fetch("/api/library/checkpoints")).json();
      const sel = $("fCheckpoint");
      sel.innerHTML = list.map((c) => `<option value="${c}">${c}</option>`).join("");
    } catch (e) {
      $("fCheckpoint").innerHTML = "<option value=''>(no se pudo cargar — ¿ComfyUI corriendo?)</option>";
    }
  }

  async function loadExistingProjects() {
    const projects = await api("/projects").catch(() => []);
    if (!projects.length) return;
    $("projectSelector").style.display = "block";
    $("fExistingProject").innerHTML = projects
      .map((p) => `<option value="${p.id}">${p.name} — ${p.status}</option>`)
      .join("");
  }

  $("createProjectBtn").addEventListener("click", async () => {
    const name = $("fProjectName").value.trim() || "sin_nombre";
    const description = $("fDescription").value.trim();
    const checkpoint = $("fCheckpoint").value;
    if (!checkpoint) return alert("No hay checkpoints disponibles — revisa que ComfyUI esté corriendo.");
    const project = await api("/projects", {
      method: "POST",
      body: JSON.stringify({
        name, description, checkpoint,
        art_style: $("fArtStyle").value, pose: $("fPose").value,
        seed: parseInt($("fSeed").value, 10) || -1,
      }),
    });
    setProject(project);
  });

  $("loadProjectBtn").addEventListener("click", async () => {
    const id = $("fExistingProject").value;
    if (!id) return;
    const project = await api(`/projects/${id}`);
    setProject(project);
  });

  function setProject(project) {
    state.project = project;
    state.iterations = project.base_iterations || [];
    state.layers = project.layers || [];
    $("projectHeading").textContent = project.name;
    $("generateBaseBtn").disabled = false;
    $("iterMeta").textContent = `proyecto: ${project.name} · estado: ${project.status}`;
    renderIterStrip();
    renderLayerList();
    renderLayersStrip();
    if (project.base_image_path) {
      $("baseImg").src = `/outputs/${project.base_image_path}`;
      $("stage1Hint").style.display = "none";
      $("approveBaseBtn").disabled = false;
    }
    if (project.status === "separating_layers" || project.status === "ready") {
      $("baseImg2").src = `/outputs/${project.base_image_path}`;
      goToScreen("screen2");
    }
  }

  function promptFromProject() {
    const p = state.project;
    return `${p.description}, ${p.art_style}, ${p.pose}`;
  }

  $("generateBaseBtn").addEventListener("click", async () => {
    if (!state.project) return;
    $("generateBaseBtn").disabled = true;
    $("stage1Hint").textContent = "Generando…";
    $("stage1Hint").style.display = "flex";
    try {
      const res = await api(`/projects/${state.project.id}/generate-base`, {
        method: "POST",
        body: JSON.stringify({
          positive_prompt: promptFromProject(),
          negative_prompt: "",
          checkpoint: state.project.checkpoint,
          seed: -1, width: 1024, height: 1024,
        }),
      });
      const iterId = res.iteration_id;
      state.iterations.push({ id: iterId, status: "queued", image_path: null });
      renderIterStrip();
      await pollIteration(iterId);
    } finally {
      $("generateBaseBtn").disabled = false;
    }
  });

  async function pollIteration(iterationId) {
    for (let i = 0; i < 120; i++) {
      const it = await api(`/projects/${state.project.id}/base-iterations/${iterationId}/status`);
      const idx = state.iterations.findIndex((x) => x.id === iterationId);
      if (idx >= 0) state.iterations[idx] = it;
      renderIterStrip();
      if (it.status === "done") {
        selectIteration(iterationId);
        return;
      }
      if (it.status === "error") {
        $("stage1Hint").textContent = "Error generando — revisa la consola de ComfyUI.";
        $("stage1Hint").style.display = "flex";
        return;
      }
      await new Promise((r) => setTimeout(r, 1500));
    }
  }

  function selectIteration(iterationId) {
    state.selectedIterationId = iterationId;
    const it = state.iterations.find((x) => x.id === iterationId);
    if (it && it.image_path) {
      $("baseImg").src = `/outputs/${it.image_path}`;
      $("stage1Hint").style.display = "none";
      $("approveBaseBtn").disabled = false;
    }
    renderIterStrip();
  }

  function renderIterStrip() {
    $("iterStrip").innerHTML = state.iterations
      .map((it, i) => {
        const selected = it.id === state.selectedIterationId ? " selected" : "";
        if (it.status === "done" && it.image_path) {
          return `<div class="rig-iter-thumb${selected}" data-id="${it.id}"><img src="/outputs/${it.image_path}"></div>`;
        }
        return `<div class="rig-iter-thumb pending${selected}" data-id="${it.id}">${it.status === "error" ? "✕" : "…"}</div>`;
      })
      .join("");
    document.querySelectorAll("#iterStrip .rig-iter-thumb").forEach((el) => {
      el.addEventListener("click", () => selectIteration(el.dataset.id));
    });
  }

  $("approveBaseBtn").addEventListener("click", async () => {
    const it = state.iterations.find((x) => x.id === state.selectedIterationId);
    if (!it || !it.image_path) return;
    $("approveBaseBtn").disabled = true;
    $("approveBaseBtn").textContent = "Segmentando…";
    try {
      const { project, segmentation_prompt_id } = await api(`/projects/${state.project.id}/approve-base`, {
        method: "POST",
        body: JSON.stringify({ iteration_image_path: it.image_path }),
      });
      state.project = project;
      $("baseImg2").src = `/outputs/${project.base_image_path}`;
      goToScreen("screen2");
      await pollSegmentation(segmentation_prompt_id);
    } catch (e) {
      alert("Error al aprobar/segmentar: " + e.message);
    } finally {
      $("approveBaseBtn").disabled = false;
      $("approveBaseBtn").textContent = "✓ Aprobar como base";
    }
  });

  async function pollSegmentation(promptId) {
    for (let i = 0; i < 180; i++) {
      const res = await api(`/projects/${state.project.id}/segmentation-status?prompt_id=${promptId}`);
      state.layers = res.layers;
      renderLayerList();
      renderLayersStrip();
      if (res.done) return;
      await new Promise((r) => setTimeout(r, 1500));
    }
  }

  // ---------- Screen 2: parts + mask editor ----------
  const canvas = $("maskCanvas");
  const ctx = canvas.getContext("2d");
  let drawing = false;
  let tool = "brush";

  document.querySelectorAll(".rig-tool-btn[data-tool]").forEach((b) => {
    b.addEventListener("click", () => {
      document.querySelectorAll(".rig-tool-btn[data-tool]").forEach((x) => x.classList.remove("active"));
      b.classList.add("active");
      tool = b.dataset.tool;
    });
  });

  function canvasPos(e) {
    const r = canvas.getBoundingClientRect();
    return {
      x: ((e.clientX - r.left) / r.width) * canvas.width,
      y: ((e.clientY - r.top) / r.height) * canvas.height,
    };
  }
  function strokeAt(e) {
    const p = canvasPos(e);
    ctx.lineWidth = parseInt($("brushSize").value, 10) * (canvas.width / 420);
    ctx.lineCap = "round";
    if (tool === "eraser") {
      ctx.globalCompositeOperation = "destination-out";
      ctx.strokeStyle = "rgba(255,255,255,1)";
    } else {
      ctx.globalCompositeOperation = "source-over";
      ctx.strokeStyle = "rgba(255,255,255,1)";
    }
    ctx.lineTo(p.x, p.y);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(p.x, p.y);
  }
  canvas.addEventListener("mousedown", (e) => {
    drawing = true;
    // Without this, the very first segment of a new stroke connects to
    // wherever the *previous* stroke happened to end (even after switching
    // tools), drawing an unwanted line from the old point to the new one.
    const p = canvasPos(e);
    ctx.beginPath();
    ctx.moveTo(p.x, p.y);
    strokeAt(e);
  });
  canvas.addEventListener("mousemove", (e) => { if (drawing) strokeAt(e); });
  window.addEventListener("mouseup", () => { drawing = false; ctx.beginPath(); });

  $("clearMaskBtn").addEventListener("click", () => {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
  });

  function renderLayerList() {
    $("partList").innerHTML = state.layers
      .map(
        (l) => `<div class="rig-part-item${l.id === state.activeLayerId ? " armed" : ""}" data-id="${l.id}">
          <span class="name">${l.display_name}</span>
          <span class="status rig-status ${l.status}">${l.status}</span>
        </div>`
      )
      .join("");
    document.querySelectorAll("#partList .rig-part-item").forEach((el) => {
      el.addEventListener("click", () => armLayer(el.dataset.id));
    });
    if (!state.activeLayerId && state.layers.length) armLayer(state.layers[0].id);
  }

  function armLayer(layerId) {
    state.activeLayerId = layerId;
    const layer = state.layers.find((l) => l.id === layerId);
    $("activePartLabel").textContent = layer ? layer.display_name : "—";
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (layer && layer.mask_path) {
      const img = new Image();
      img.crossOrigin = "anonymous";
      img.onload = () => ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
      img.src = `/outputs/${layer.mask_path}?t=${Date.now()}`;
    }
    renderLayerList();
  }

  $("saveMaskBtn").addEventListener("click", async () => {
    if (!state.activeLayerId) return;
    const dataUrl = canvas.toDataURL("image/png");
    $("saveMaskBtn").disabled = true;
    try {
      const layer = await api(
        `/projects/${state.project.id}/layers/${state.activeLayerId}/mask`,
        { method: "PUT", body: JSON.stringify({ mask_png_base64: dataUrl }) }
      );
      const idx = state.layers.findIndex((l) => l.id === layer.id);
      if (idx >= 0) state.layers[idx] = layer;
      renderLayerList();
    } finally {
      $("saveMaskBtn").disabled = false;
    }
  });

  $("generateLayerBtn").addEventListener("click", async () => {
    if (!state.activeLayerId) return;
    const layerId = state.activeLayerId;
    $("generateLayerBtn").disabled = true;
    $("jobMeta").textContent = "encolando…";
    try {
      const layer = await api(`/projects/${state.project.id}/layers/${layerId}/generate`, {
        method: "POST",
        body: JSON.stringify({ part_key: state.layers.find((l) => l.id === layerId).part_key }),
      });
      updateLayerInState(layer);
      await pollLayer(layerId);
    } catch (e) {
      $("jobMeta").textContent = "error: " + e.message;
    } finally {
      $("generateLayerBtn").disabled = false;
    }
  });

  $("generateOccludedBtn").addEventListener("click", async () => {
    if (!state.activeLayerId) return;
    const layerId = state.activeLayerId;
    $("generateOccludedBtn").disabled = true;
    $("jobMeta").textContent = "encolando (con relleno)…";
    try {
      const layer = await api(`/projects/${state.project.id}/layers/${layerId}/generate-occluded`, {
        method: "POST",
      });
      updateLayerInState(layer);
      await pollLayer(layerId);
    } catch (e) {
      $("jobMeta").textContent = "error: " + e.message;
    } finally {
      $("generateOccludedBtn").disabled = false;
    }
  });

  async function pollLayer(layerId) {
    for (let i = 0; i < 120; i++) {
      const layer = await api(`/projects/${state.project.id}/layers/${layerId}/status`);
      updateLayerInState(layer);
      $("jobMeta").textContent = `capa "${layer.display_name}": ${layer.job_status || layer.status}`;
      if (layer.job_status === "done" || layer.job_status === "error") return;
      await new Promise((r) => setTimeout(r, 1500));
    }
  }

  function updateLayerInState(layer) {
    const idx = state.layers.findIndex((l) => l.id === layer.id);
    if (idx >= 0) state.layers[idx] = layer;
    else state.layers.push(layer);
    renderLayerList();
    renderLayersStrip();
  }

  function renderLayersStrip() {
    $("layerCount").textContent = `${state.layers.length} capas — orden = qué tapa a qué (abajo tapa a arriba)`;
    const list = $("layersList");
    const ordered = state.layers.slice().sort((a, b) => a.order_index - b.order_index);
    list.innerHTML = ordered
      .map((l, i) => {
        const thumb = l.image_path
          ? `<img src="/outputs/${l.image_path}">`
          : l.mask_path
          ? `<img src="/outputs/${l.mask_path}" style="opacity:.5">`
          : "";
        return `<div class="rig-layer-row" data-id="${l.id}">
          <div class="rig-reorder-btns">
            <button class="rig-reorder-btn" data-dir="up" data-id="${l.id}" ${i === 0 ? "disabled" : ""} title="Sube en la pila (ocluye menos)">▲</button>
            <button class="rig-reorder-btn" data-dir="down" data-id="${l.id}" ${i === ordered.length - 1 ? "disabled" : ""} title="Baja en la pila (ocluye más)">▼</button>
          </div>
          <div class="rig-layer-thumb">${thumb}</div>
          <div class="rig-layer-info">
            <div class="name">${l.display_name}</div>
            <div class="sub">${l.part_key} · orden ${l.order_index}</div>
          </div>
        </div>`;
      })
      .join("");
    document.querySelectorAll(".rig-reorder-btn").forEach((btn) => {
      btn.addEventListener("click", () => reorderLayer(btn.dataset.id, btn.dataset.dir));
    });
  }

  async function reorderLayer(layerId, dir) {
    const ordered = state.layers.slice().sort((a, b) => a.order_index - b.order_index);
    const i = ordered.findIndex((l) => l.id === layerId);
    const j = dir === "up" ? i - 1 : i + 1;
    if (j < 0 || j >= ordered.length) return;
    const a = ordered[i], b = ordered[j];
    const [aIdx, bIdx] = [a.order_index, b.order_index];
    await api(`/projects/${state.project.id}/layers/${a.id}`, {
      method: "PATCH", body: JSON.stringify({ order_index: bIdx }),
    });
    const updatedB = await api(`/projects/${state.project.id}/layers/${b.id}`, {
      method: "PATCH", body: JSON.stringify({ order_index: aIdx }),
    });
    updateLayerInState({ ...a, order_index: bIdx });
    updateLayerInState(updatedB);
  }

  $("exportBtn").addEventListener("click", () => {
    if (!state.project) return;
    window.location.href = `${API}/projects/${state.project.id}/export`;
  });

  loadCheckpoints();
  loadExistingProjects();
})();
