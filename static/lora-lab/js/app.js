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

  (async function pollHealth() {
    const tag = document.getElementById("serverStatus");
    try {
      const res = await fetch("/api/health").then((r) => r.json());
      tag.dataset.state = res.status;
      tag.querySelector(".status-label").textContent = res.status;
    } catch (e) {
      tag.dataset.state = "down";
      tag.querySelector(".status-label").textContent = "down";
    }
  })();

  const API = "/api/lora-lab";
  const $ = (id) => document.getElementById(id);

  async function api(path, options) {
    const resp = await fetch(API + path, options);
    if (!resp.ok) {
      const text = await resp.text().catch(() => "");
      throw new Error(`${resp.status} ${text}`);
    }
    return resp.json();
  }

  const state = {
    jobs: [],
    currentJob: null,
    presets: {},
    checkpoints: [],
    selectedPreset: "balanceado",
    pollTimer: null,
  };

  function showToast(msg) {
    console.log("[lora-lab]", msg);
  }

  // ---------- screens ----------
  function goToScreen(name) {
    document.querySelectorAll(".lab-screen").forEach((s) => s.classList.toggle("active", s.id === name));
  }

  function goToStep(stepId) {
    document.querySelectorAll(".lab-stage").forEach((s) => s.classList.toggle("active", s.dataset.target === stepId));
    document.querySelectorAll(".lab-step").forEach((s) => s.classList.toggle("active", s.id === stepId));
  }

  document.querySelectorAll(".lab-stage").forEach((btn) => {
    btn.addEventListener("click", () => goToStep(btn.dataset.target));
  });

  function markRailDone(...ids) {
    document.querySelectorAll(".lab-stage").forEach((s) => {
      s.classList.toggle("done", ids.includes(s.dataset.target));
    });
  }

  // ---------- job list ----------
  async function loadJobs() {
    state.jobs = await api("/jobs");
    renderJobGrid();
  }

  function statusLabel(status) {
    return (
      {
        dataset: "armando dataset",
        captioning: "etiquetando…",
        ready: "listo para entrenar",
        training: "entrenando",
        done: "LoRA listo",
        error: "error",
        cancelled: "cancelado",
      }[status] || status
    );
  }

  function renderJobGrid() {
    const grid = $("jobGrid");
    grid.innerHTML = "";
    $("jobsEmpty").hidden = state.jobs.length > 0;
    for (const job of state.jobs) {
      const card = document.createElement("div");
      card.className = "lab-job-card";
      card.innerHTML = `
        <span class="pill" data-status="${job.status}">${statusLabel(job.status)}</span>
        <h3>${escapeHtml(job.name)}</h3>
        <div class="meta">${job.image_count} imágenes · trigger: ${escapeHtml(job.trigger_word)}</div>
      `;
      card.addEventListener("click", () => openJob(job.id));
      grid.appendChild(card);
    }
  }

  function escapeHtml(s) {
    const div = document.createElement("div");
    div.textContent = s || "";
    return div.innerHTML;
  }

  $("btnNewJob").addEventListener("click", () => {
    $("newJobName").value = "";
    $("newJobTrigger").value = "";
    $("newJobBackdrop").hidden = false;
  });
  $("btnCancelNewJob").addEventListener("click", () => ($("newJobBackdrop").hidden = true));
  $("btnCreateJob").addEventListener("click", async () => {
    const name = $("newJobName").value.trim();
    const trigger = $("newJobTrigger").value.trim();
    if (!name || !trigger) return alert("Completá nombre y trigger word.");
    try {
      const job = await api("/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, trigger_word: trigger }),
      });
      $("newJobBackdrop").hidden = true;
      await loadJobs();
      openJob(job.id);
    } catch (e) {
      alert("No se pudo crear el job: " + e.message);
    }
  });

  // ---------- open job / wizard ----------
  async function openJob(jobId) {
    const job = await api(`/jobs/${jobId}`);
    state.currentJob = job;
    goToScreen("screenWizard");
    renderDatasetStep();
    renderCaptionStep();
    await renderConfigStep();
    if (job.status === "training") {
      goToStep("stTrain");
      startPolling();
    } else if (job.status === "done" || job.status === "error" || job.status === "cancelled") {
      renderResultStep();
      goToStep("stResult");
    } else if (job.status === "ready") {
      markRailDone("stDataset", "stCaption");
      goToStep("stConfig");
    } else {
      goToStep("stDataset");
    }
  }

  document.querySelectorAll(".lab-btn-secondary#btnBackToDataset, #btnBackToDataset").forEach(() => {});
  $("btnBackToDataset")?.addEventListener("click", () => goToStep("stDataset"));
  $("btnBackToCaption")?.addEventListener("click", () => goToStep("stCaption"));

  // ---------- step 1: dataset ----------
  function renderDatasetStep() {
    const job = state.currentJob;
    $("thumbRow").innerHTML = "";
    for (const img of job.images) {
      addThumb(img.filename);
    }
    updateDatasetGate();
  }

  function addThumb(filename) {
    const div = document.createElement("div");
    div.className = "lab-thumb";
    div.dataset.filename = filename;
    div.innerHTML = `<img src="/lora-jobs/${state.currentJob.id}/images/${encodeURIComponent(filename)}" loading="lazy"><button title="Eliminar">×</button>`;
    div.querySelector("button").addEventListener("click", async (e) => {
      e.stopPropagation();
      await api(`/jobs/${state.currentJob.id}/images/${encodeURIComponent(filename)}`, { method: "DELETE" });
      state.currentJob = await api(`/jobs/${state.currentJob.id}`);
      renderDatasetStep();
    });
    $("thumbRow").appendChild(div);
  }

  function updateDatasetGate() {
    $("railDatasetHint").textContent = `${state.currentJob.image_count} imágenes`;
    $("btnToCaption").disabled = state.currentJob.image_count === 0;
  }

  const dropzone = $("dropzone");
  const fileInput = $("fileInput");
  dropzone.addEventListener("click", (e) => {
    if (e.target !== fileInput) fileInput.click();
  });
  ["dragover", "dragleave", "drop"].forEach((evt) => {
    dropzone.addEventListener(evt, (e) => {
      e.preventDefault();
      dropzone.classList.toggle("dragover", evt === "dragover");
    });
  });
  dropzone.addEventListener("drop", (e) => uploadFiles(e.dataTransfer.files));
  fileInput.addEventListener("change", () => uploadFiles(fileInput.files));

  async function uploadFiles(fileList) {
    if (!fileList.length) return;
    const form = new FormData();
    for (const f of fileList) form.append("files", f);
    try {
      state.currentJob = await api(`/jobs/${state.currentJob.id}/images`, { method: "POST", body: form });
      renderDatasetStep();
    } catch (e) {
      alert("No se pudieron subir las imágenes: " + e.message);
    }
    fileInput.value = "";
  }

  $("btnToCaption").addEventListener("click", () => {
    markRailDone("stDataset");
    renderCaptionStep();
    goToStep("stCaption");
  });

  // ---------- step 2: captioning ----------
  function renderCaptionStep() {
    const job = state.currentJob;
    const list = $("captionList");
    list.innerHTML = "";
    for (const img of job.images) {
      const row = document.createElement("div");
      row.className = "lab-caption-row";
      row.innerHTML = `
        <img src="/lora-jobs/${job.id}/images/${encodeURIComponent(img.filename)}" loading="lazy">
        <div>
          <div class="filename">${escapeHtml(img.filename)}</div>
          <textarea>${escapeHtml(img.caption)}</textarea>
        </div>
      `;
      const textarea = row.querySelector("textarea");
      textarea.addEventListener("change", async () => {
        await api(`/jobs/${job.id}/images/${encodeURIComponent(img.filename)}/caption`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ caption: textarea.value }),
        });
      });
      list.appendChild(row);
    }
    $("railCaptionHint").textContent = job.status === "ready" || job.status === "captioning" ? "revisado" : "pendiente";
  }

  $("btnRunTagger").addEventListener("click", async () => {
    const statusEl = $("captionStatus");
    statusEl.hidden = false;
    statusEl.dataset.tone = "";
    statusEl.textContent = "Etiquetando con WD14… puede tardar uno o dos minutos, especialmente la primera vez (descarga el modelo tagger).";
    $("btnRunTagger").disabled = true;
    try {
      state.currentJob = await api(`/jobs/${state.currentJob.id}/caption`, { method: "POST" });
      statusEl.textContent = "Etiquetado listo. Revisá las tags antes de continuar.";
      renderCaptionStep();
    } catch (e) {
      statusEl.dataset.tone = "error";
      statusEl.textContent = "Falló el etiquetado: " + e.message;
    } finally {
      $("btnRunTagger").disabled = false;
    }
  });

  $("btnToConfig").addEventListener("click", () => {
    markRailDone("stDataset", "stCaption");
    goToStep("stConfig");
  });

  // ---------- step 3: config ----------
  async function renderConfigStep() {
    const job = state.currentJob;
    $("configTrigger").value = job.trigger_word;

    if (state.checkpoints.length === 0) {
      try {
        state.checkpoints = await api("/checkpoints");
      } catch (e) {
        state.checkpoints = [];
      }
    }
    const select = $("checkpointSelect");
    select.innerHTML = state.checkpoints.map((c) => `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`).join("");
    if (job.checkpoint && state.checkpoints.includes(job.checkpoint)) select.value = job.checkpoint;

    state.presets = await api(`/presets?image_count=${job.image_count}`);
    renderPresetGrid();
  }

  function renderPresetGrid() {
    const grid = $("presetGrid");
    grid.innerHTML = "";
    for (const [key, preset] of Object.entries(state.presets)) {
      const card = document.createElement("div");
      card.className = "lab-preset" + (key === state.selectedPreset ? " selected" : "");
      const steps = preset.estimated_steps || "—";
      card.innerHTML = `
        <h3>${escapeHtml(preset.label)}</h3>
        <p>${escapeHtml(preset.description)}</p>
        <div class="stat"><span>Epochs</span><span>${preset.epochs}</span></div>
        <div class="stat"><span>Pasos aprox.</span><span>~${steps}</span></div>
        <div class="stat"><span>Resolución</span><span>${preset.resolution}px</span></div>
      `;
      card.addEventListener("click", () => {
        state.selectedPreset = key;
        renderPresetGrid();
      });
      grid.appendChild(card);
    }
  }

  $("btnStartTraining").addEventListener("click", async () => {
    const checkpoint = $("checkpointSelect").value;
    if (!checkpoint) return alert("Elegí un checkpoint base.");
    try {
      state.currentJob = await api(`/jobs/${state.currentJob.id}/train`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ preset: state.selectedPreset, checkpoint }),
      });
      markRailDone("stDataset", "stCaption");
      renderTrainStep();
      goToStep("stTrain");
      startPolling();
    } catch (e) {
      alert("No se pudo iniciar el entrenamiento: " + e.message);
    }
  });

  // ---------- step 4: training ----------
  function renderTrainStep() {
    const job = state.currentJob;
    $("trainSubtitle").textContent = `${job.name} · preset ${state.presets[job.preset]?.label || job.preset} · sobre ${job.checkpoint}`;
    updateTrainGauges();
  }

  function updateTrainGauges() {
    const job = state.currentJob;
    const total = job.total_steps || 0;
    const current = job.current_step || 0;
    $("gaugeSteps").textContent = `${current} / ${total || "?"}`;
    $("gaugeStepsFill").style.width = total ? `${Math.min(100, (current / total) * 100)}%` : "0%";
    $("gaugeEpoch").textContent = `${job.current_epoch || 0} / ${job.total_epochs || "?"}`;
    $("gaugeLoss").textContent = job.loss != null ? job.loss.toFixed(4) : "—";
    $("consoleLog").textContent = job.log_tail || "";
    $("consoleLog").scrollTop = $("consoleLog").scrollHeight;
    $("railTrainHint").textContent = statusLabel(job.status);
  }

  function startPolling() {
    stopPolling();
    state.pollTimer = setInterval(async () => {
      try {
        const job = await api(`/jobs/${state.currentJob.id}/status`);
        state.currentJob = job;
        if (goToScreen && document.getElementById("stTrain").classList.contains("active")) {
          updateTrainGauges();
        }
        if (job.status !== "training") {
          stopPolling();
          markRailDone("stDataset", "stCaption", "stTrain");
          renderResultStep();
          goToStep("stResult");
          loadJobs();
        }
      } catch (e) {
        console.error(e);
      }
    }, 3000);
  }

  function stopPolling() {
    if (state.pollTimer) clearInterval(state.pollTimer);
    state.pollTimer = null;
  }

  $("btnCancelTraining").addEventListener("click", async () => {
    if (!confirm("¿Cancelar este entrenamiento? El progreso no guardado se pierde.")) return;
    try {
      state.currentJob = await api(`/jobs/${state.currentJob.id}/cancel`, { method: "POST" });
      stopPolling();
      renderResultStep();
      goToStep("stResult");
      loadJobs();
    } catch (e) {
      alert("No se pudo cancelar: " + e.message);
    }
  });

  // ---------- step 5: result ----------
  function renderResultStep() {
    const job = state.currentJob;
    const card = $("resultCard");
    $("railResultHint").textContent = statusLabel(job.status);
    if (job.status === "done") {
      $("resultTitle").textContent = "LoRA listo";
      card.innerHTML = `
        <div>
          <h3>${escapeHtml(job.output_path)}</h3>
          <div class="path">ComfyUI/models/loras/${escapeHtml(job.output_path)}</div>
          <span class="lab-pill-ok">✓ ${job.total_epochs}/${job.total_epochs} epochs</span>
          ${job.loss != null ? `<span class="lab-pill-ok">✓ loss final ${job.loss.toFixed(4)}</span>` : ""}
        </div>
      `;
      $("btnUseInGeneration").hidden = false;
    } else {
      $("resultTitle").textContent = job.status === "cancelled" ? "Entrenamiento cancelado" : "Entrenamiento con error";
      card.innerHTML = `<div><h3>${statusLabel(job.status)}</h3><div class="path">${escapeHtml(job.error_message || "")}</div></div>`;
      $("btnUseInGeneration").hidden = true;
    }
  }

  // ---------- boot ----------
  loadJobs();
})();
