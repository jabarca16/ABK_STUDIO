// ---- theme menu ----
const root = document.documentElement;
const themeToggle = document.getElementById('themeToggle');
const themeMenu = document.getElementById('themeMenu');
const themeMenuWrap = document.getElementById('themeMenuWrap');

function applyTheme(name) {
  root.setAttribute('data-theme', name);
  localStorage.setItem('abkTheme', name);
  themeMenu.querySelectorAll('.theme-menu-item').forEach(el => {
    el.classList.toggle('active', el.dataset.themeChoice === name);
  });
}

applyTheme(localStorage.getItem('abkTheme') ||
  (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'));

themeToggle.addEventListener('click', (e) => {
  e.stopPropagation();
  themeMenu.classList.toggle('open');
});
themeMenu.querySelectorAll('.theme-menu-item').forEach(btn => {
  btn.addEventListener('click', () => {
    applyTheme(btn.dataset.themeChoice);
    themeMenu.classList.remove('open');
  });
});
document.addEventListener('click', (e) => {
  if (!themeMenuWrap.contains(e.target)) themeMenu.classList.remove('open');
});

// ---- toast ----
function showToast(msg, isError = false) {
  const t = document.getElementById('toast');
  t.querySelector('.msg').textContent = msg;
  t.classList.toggle('error', isError);
  t.classList.add('show');
  clearTimeout(showToast._timer);
  showToast._timer = setTimeout(() => t.classList.remove('show'), 3200);
}

async function api(path, opts) {
  const resp = await fetch(path, opts);
  if (!resp.ok) {
    let detail = resp.statusText;
    try { detail = (await resp.json()).detail || detail; } catch (e) {}
    throw new Error(detail);
  }
  return resp.status === 204 ? null : resp.json();
}

// ================= SERVER STATUS =================
async function pollHealth() {
  const tag = document.getElementById('serverStatus');
  try {
    const res = await api('/api/health');
    tag.dataset.state = res.status;
    tag.querySelector('.status-label').textContent = res.status;
  } catch (e) {
    tag.dataset.state = 'down';
    tag.querySelector('.status-label').textContent = 'down';
  }
}
pollHealth();
setInterval(pollHealth, 4000);

// ================= SIZE PRESETS =================
const SIZE_TIERS = {
  low: [
    { label: '1:1', w: 1024, h: 1024 },
    { label: '3:4', w: 896, h: 1152 },
    { label: '2:3', w: 832, h: 1216 },
    { label: '7:4', w: 1344, h: 768 },
  ],
  high: [
    { label: '1:1', w: 1536, h: 1536 },
    { label: '3:4', w: 1152, h: 1536 },
    { label: '2:3', w: 1024, h: 1536 },
    { label: '16:9', w: 1536, h: 864 },
  ],
};
const TIER_TITLE = { low: 'Low-Res', high: 'High-Res' };
let currentTier = 'high';
let selectedSizeIdx = 2;
let customSizeActive = false;

function swatchDims(w, h) {
  const maxSide = 30;
  if (w >= h) return { sw: maxSide, sh: Math.round(maxSide * h / w) };
  return { sw: Math.round(maxSide * w / h), sh: maxSide };
}

function applySize(w, h) {
  document.getElementById('width').value = w;
  document.getElementById('height').value = h;
  const tag = customSizeActive ? 'Custom' : TIER_TITLE[currentTier];
  document.getElementById('sizeHint').textContent = `${w} × ${h} · ${tag}`;
  document.getElementById('sizeMeta').textContent = `${w}×${h}`;
}

function renderTierToggle() {
  const wrap = document.getElementById('tierToggle');
  wrap.innerHTML = `
    <div class="tier-btn ${currentTier === 'low' ? 'active' : ''}" data-tier="low">Low-Res</div>
    <div class="tier-btn ${currentTier === 'high' ? 'active' : ''}" data-tier="high">High-Res</div>
  `;
  wrap.querySelectorAll('.tier-btn').forEach(b => {
    b.addEventListener('click', () => {
      currentTier = b.dataset.tier;
      customSizeActive = false;
      document.getElementById('customSizeRow').classList.remove('open');
      renderTierToggle();
      renderSizeGrid();
      const p = SIZE_TIERS[currentTier][selectedSizeIdx];
      applySize(p.w, p.h);
    });
  });
}

function renderSizeGrid() {
  const grid = document.getElementById('sizeGrid');
  grid.innerHTML = '';
  SIZE_TIERS[currentTier].forEach((p, i) => {
    const { sw, sh } = swatchDims(p.w, p.h);
    const opt = document.createElement('div');
    opt.className = 'size-opt' + (!customSizeActive && i === selectedSizeIdx ? ' selected' : '');
    opt.innerHTML = `
      <div class="swatch" style="width:${sw}px;height:${sh}px;"></div>
      <span class="ratio-label">${p.label}</span>
      <span class="dims">${p.w}×${p.h}</span>
    `;
    opt.addEventListener('click', () => {
      selectedSizeIdx = i;
      customSizeActive = false;
      document.getElementById('customSizeRow').classList.remove('open');
      applySize(p.w, p.h);
      renderSizeGrid();
    });
    grid.appendChild(opt);
  });

  const customOpt = document.createElement('div');
  customOpt.className = 'size-opt custom-opt' + (customSizeActive ? ' selected' : '');
  customOpt.innerHTML = `
    <div class="swatch" style="width:30px;height:30px;">+</div>
    <span class="ratio-label">Custom</span>
    <span class="dims">manual</span>
  `;
  customOpt.addEventListener('click', () => {
    customSizeActive = true;
    document.getElementById('customSizeRow').classList.add('open');
    renderSizeGrid();
    applySize(document.getElementById('width').value, document.getElementById('height').value);
    document.getElementById('width').focus();
  });
  grid.appendChild(customOpt);
}
renderTierToggle();
renderSizeGrid();
applySize(SIZE_TIERS[currentTier][selectedSizeIdx].w, SIZE_TIERS[currentTier][selectedSizeIdx].h);

['width', 'height'].forEach(id => {
  document.getElementById(id).addEventListener('input', () => {
    applySize(document.getElementById('width').value, document.getElementById('height').value);
  });
});

// ================= BATCH (clamped 1-4) =================
const batchInput = document.getElementById('batchSize');
const canvasArea = document.getElementById('canvasArea');
const framesGrid = document.getElementById('framesGrid');

function clampBatch(v) {
  let n = parseInt(v, 10);
  if (isNaN(n)) n = 1;
  return Math.max(1, Math.min(4, n));
}

function renderFrames(count) {
  canvasArea.className = 'canvas-area count-' + count;
  framesGrid.innerHTML = '';
  for (let i = 0; i < count; i++) {
    const f = document.createElement('div');
    f.className = 'frame';
    f.innerHTML = `
      <div class="sprockets left"></div>
      <div class="sprockets right"></div>
      <span class="placeholder-icon">◍</span>
    `;
    framesGrid.appendChild(f);
  }
}
renderFrames(clampBatch(batchInput.value));

batchInput.addEventListener('input', () => renderFrames(clampBatch(batchInput.value)));
batchInput.addEventListener('change', () => {
  const n = clampBatch(batchInput.value);
  batchInput.value = n;
  renderFrames(n);
});

// ================= PROJECTS =================
let PROJECTS = ['(root)'];
let currentProject = '(root)';

function pathFor(project) {
  return project === '(root)' ? 'output/' : `output/${project}/`;
}

function renderProjectSelect() {
  const sel = document.getElementById('projectSelect');
  sel.innerHTML = '';
  PROJECTS.forEach(p => {
    const opt = document.createElement('option');
    opt.value = p;
    opt.textContent = p === '(root)' ? '— root (sin proyecto) —' : p;
    if (p === currentProject) opt.selected = true;
    sel.appendChild(opt);
  });
  document.getElementById('pathMeta').textContent = pathFor(currentProject);
}

async function loadProjects() {
  try {
    PROJECTS = await api('/api/projects');
    if (!PROJECTS.includes(currentProject)) currentProject = '(root)';
    renderProjectSelect();
  } catch (e) {
    showToast('No se pudieron cargar los proyectos: ' + e.message, true);
  }
}

document.getElementById('projectSelect').addEventListener('change', e => {
  currentProject = e.target.value;
  document.getElementById('pathMeta').textContent = pathFor(currentProject);
  renderHistoryFilter();
  loadHistory();
});

const newProjectRow = document.getElementById('projectNewRow');
const newProjectWrap = document.getElementById('projectSelectWrap');
document.getElementById('newProjectBtn').addEventListener('click', () => {
  newProjectRow.classList.add('open');
  newProjectWrap.style.display = 'none';
  document.getElementById('newProjectInput').focus();
});
function closeNewProjectRow() {
  newProjectRow.classList.remove('open');
  newProjectWrap.style.display = 'flex';
  document.getElementById('newProjectInput').value = '';
}
document.getElementById('cancelNewProject').addEventListener('click', closeNewProjectRow);
async function confirmNewProject() {
  const input = document.getElementById('newProjectInput');
  const name = input.value.trim();
  if (!name) { closeNewProjectRow(); return; }
  try {
    const created = await api('/api/projects', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    });
    currentProject = created.name;
    await loadProjects();
    renderHistoryFilter();
    loadHistory();
  } catch (e) {
    showToast('No se pudo crear el proyecto: ' + e.message, true);
  }
  closeNewProjectRow();
}
document.getElementById('confirmNewProject').addEventListener('click', confirmNewProject);
document.getElementById('newProjectInput').addEventListener('keydown', e => {
  if (e.key === 'Enter') confirmNewProject();
  if (e.key === 'Escape') closeNewProjectRow();
});

// ================= LORA LIBRARY =================
let LORA_LIBRARY = [];
let loraStack = [];
let selectedLoraFolder = null; // null = all folders
let expandedLoraIdx = new Set();

function findLora(name) {
  return LORA_LIBRARY.find(l => l.name === name);
}

function loraCompatible(lib) {
  if (!lib || !lib.base_model) return true;
  const ckpt = findCkpt(document.getElementById('checkpoint').value);
  if (!ckpt || !ckpt.base_model) return true;
  return ckpt.base_model === lib.base_model;
}

function loraThumbHtml(lib, className) {
  if (!lib.preview_url) return `<div class="${className}"></div>`;
  if (lib.preview_type === 'video') {
    return `<video class="${className}" src="${lib.preview_url}" autoplay loop muted playsinline></video>`;
  }
  return `<div class="${className}" style="background-image:url('${lib.preview_url}')"></div>`;
}

function renderLoraStack() {
  const el = document.getElementById('loraStack');
  el.innerHTML = '';
  loraStack.forEach((s, idx) => {
    const lib = findLora(s.name) || { display_name: s.name, triggers: [], preview_url: '' };
    const expanded = expandedLoraIdx.has(idx);
    const compatible = loraCompatible(lib);
    const card = document.createElement('div');
    card.className = 'lora-card' + (compatible ? '' : ' incompatible');
    card.innerHTML = `
      <div class="lora-card-row">
        ${loraThumbHtml(lib, 'lora-thumb')}
        <div class="lora-meta">
          <div class="name"><span class="name-text">${lib.display_name}</span>${compatible ? '' : `<span class="compat-badge" title="Base model del LoRA (${lib.base_model || '?'}) no coincide con el checkpoint activo">⚠ ${lib.base_model || '?'}</span>`}</div>
          <div class="lora-strength">
            <input type="range" min="0" max="1.5" step="0.01" value="${s.strength}" data-idx="${idx}" class="strength-input">
            <span class="val">${s.strength.toFixed(2)}</span>
          </div>
        </div>
        <div class="lora-actions">
          <button class="icon-btn remove-btn" data-idx="${idx}" title="Remove">✕</button>
          <button class="icon-btn lora-resync-btn" data-idx="${idx}" title="Re-agregar trigger word al positive">↻</button>
          <button class="icon-btn lora-expand-btn${expanded ? ' open' : ''}" data-idx="${idx}" title="Ver keywords">▾</button>
        </div>
      </div>
      ${expanded ? `
        <div class="lora-keywords">
          ${lib.triggers.length ? lib.triggers.map(t => `
            <button class="keyword-chip" data-word="${t}">${t} <span class="plus">+</span></button>
          `).join('') : `<span class="empty-note">sin keywords registrados</span>`}
        </div>
      ` : ''}
    `;
    el.appendChild(card);
  });
  document.getElementById('loraCount').textContent = `${loraStack.length} active`;

  el.querySelectorAll('.strength-input').forEach(inp => {
    inp.addEventListener('input', e => {
      const i = +e.target.dataset.idx;
      loraStack[i].strength = parseFloat(e.target.value);
      e.target.nextElementSibling.textContent = loraStack[i].strength.toFixed(2);
    });
  });
  el.querySelectorAll('.remove-btn').forEach(btn => {
    btn.addEventListener('click', e => {
      const i = +e.currentTarget.dataset.idx;
      loraStack.splice(i, 1);
      expandedLoraIdx.delete(i);
      renderLoraStack();
      renderLoraGrid(document.getElementById('loraSearch').value);
    });
  });
  el.querySelectorAll('.lora-resync-btn').forEach(btn => {
    btn.addEventListener('click', e => {
      const i = +e.currentTarget.dataset.idx;
      const s = loraStack[i];
      const lib = findLora(s.name);
      if (lib && lib.triggers.length) addTriggerWordToPositive(lib.triggers[0]);
    });
  });
  el.querySelectorAll('.lora-expand-btn').forEach(btn => {
    btn.addEventListener('click', e => {
      const i = +e.currentTarget.dataset.idx;
      expandedLoraIdx.has(i) ? expandedLoraIdx.delete(i) : expandedLoraIdx.add(i);
      renderLoraStack();
    });
  });
  el.querySelectorAll('.keyword-chip').forEach(chip => {
    chip.addEventListener('click', e => {
      addTriggerWordToPositive(e.currentTarget.dataset.word);
    });
  });
}

// ---- generic folder-tree helpers (reused by LoRA + Checkpoint pickers) ----
function buildFolderTree(items) {
  const root = {};
  items.forEach(it => {
    if (!it.folder) return;
    const parts = it.folder.split('/');
    let node = root;
    let pathAcc = '';
    parts.forEach(p => {
      pathAcc = pathAcc ? `${pathAcc}/${p}` : p;
      if (!node[p]) node[p] = { name: p, path: pathAcc, children: {} };
      node = node[p].children;
    });
  });
  return root;
}

function itemInFolder(it, folderPath) {
  if (folderPath === null) return true;
  if (folderPath === '') return !it.folder;
  return it.folder === folderPath || it.folder.startsWith(folderPath + '/');
}

function renderFolderTreeNodes(nodes, selectedFolder) {
  return Object.values(nodes)
    .sort((a, b) => a.name.localeCompare(b.name))
    .map(node => {
      const childrenHtml = renderFolderTreeNodes(node.children, selectedFolder);
      return `
        <div class="tree-item${selectedFolder === node.path ? ' active' : ''}" data-path="${node.path}">${node.name}</div>
        ${childrenHtml ? `<div class="tree-children">${childrenHtml}</div>` : ''}
      `;
    })
    .join('');
}

function renderFolderTree(elId, items, selectedFolder, onPick) {
  const el = document.getElementById(elId);
  const tree = buildFolderTree(items);
  const hasRootItems = items.some(it => !it.folder);
  el.innerHTML = `
    <div class="tree-item${selectedFolder === null ? ' active' : ''}" data-path="__all__">All</div>
    ${hasRootItems ? `<div class="tree-item${selectedFolder === '' ? ' active' : ''}" data-path="">Root</div>` : ''}
    ${renderFolderTreeNodes(tree, selectedFolder)}
  `;
  el.querySelectorAll('.tree-item').forEach(item => {
    item.addEventListener('click', () => onPick(item.dataset.path === '__all__' ? null : item.dataset.path));
  });
}

function renderLoraTree() {
  renderFolderTree('loraTree', LORA_LIBRARY, selectedLoraFolder, (path) => {
    selectedLoraFolder = path;
    renderLoraTree();
    renderLoraGrid(document.getElementById('loraSearch').value);
  });
}

function addTriggerWordToPositive(trigger, { silent = false } = {}) {
  if (!trigger) return;
  const el = document.getElementById('positive');
  const current = el.value;
  if (current.toLowerCase().includes(trigger.toLowerCase())) {
    if (!silent) showToast(`Trigger word "${trigger}" ya está en el positive`);
    return;
  }
  el.value = current.trim() ? `${current.trim()}, ${trigger}` : trigger;
  el.scrollTop = el.scrollHeight;
  showToast(`Trigger word "${trigger}" agregado al positive`);
}

function renderLoraGrid(filter = '') {
  const grid = document.getElementById('loraGrid');
  grid.innerHTML = '';
  const q = filter.trim().toLowerCase();
  const filtered = LORA_LIBRARY.filter(l =>
    itemInFolder(l, selectedLoraFolder) &&
    (!q ||
      l.name.toLowerCase().includes(q) ||
      l.display_name.toLowerCase().includes(q) ||
      l.triggers.some(t => t.toLowerCase().includes(q)))
  );
  if (!filtered.length) {
    grid.innerHTML = `<div class="empty-note">sin resultados</div>`;
    return;
  }
  filtered.sort((a, b) => {
    if (!!a.favorite !== !!b.favorite) return a.favorite ? -1 : 1;
    return loraCompatible(a) === loraCompatible(b) ? 0 : (loraCompatible(a) ? -1 : 1);
  });
  filtered.forEach(l => {
    const isSelected = loraStack.some(s => s.name === l.name);
    const compatible = loraCompatible(l);
    const card = document.createElement('div');
    card.className = 'lora-pick' + (isSelected ? ' selected' : '') + (compatible ? '' : ' incompatible');
    card.innerHTML = `
      <div class="art-wrap">
        ${loraThumbHtml(l, 'art')}
        <button class="lora-fav-btn${l.favorite ? ' active' : ''}" title="${l.favorite ? 'Quitar de favoritos' : 'Marcar como favorito'}">${l.favorite ? '★' : '☆'}</button>
        <div class="art-caption">${l.base_model || 'base model desconocido'}</div>
      </div>
      <div class="info">
        <div class="name"><span class="name-text">${l.display_name}</span>${compatible ? '' : `<span class="compat-badge" title="Base model del LoRA (${l.base_model || '?'}) no coincide con el checkpoint activo">⚠ ${l.base_model || '?'}</span>`}</div>
        <div class="trig">${l.triggers.join(', ') || l.name}</div>
      </div>
    `;
    card.addEventListener('click', () => {
      if (isSelected) {
        loraStack = loraStack.filter(s => s.name !== l.name);
      } else {
        loraStack.push({ name: l.name, strength: l.suggested_strength || 0.8 });
        addTriggerWordToPositive(l.triggers[0]);
      }
      renderLoraStack();
      renderLoraGrid(document.getElementById('loraSearch').value);
    });
    card.querySelector('.lora-fav-btn').addEventListener('click', async (e) => {
      e.stopPropagation();
      const nextFavorite = !l.favorite;
      try {
        await api('/api/library/loras/favorite', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name: l.name, favorite: nextFavorite }),
        });
        l.favorite = nextFavorite;
        renderLoraGrid(document.getElementById('loraSearch').value);
      } catch (err) {
        showToast('No se pudo actualizar favorito: ' + err.message, true);
      }
    });
    grid.appendChild(card);
  });
}

async function loadLoras() {
  LORA_LIBRARY = await api('/api/library/loras');
  renderLoraStack();
}

document.getElementById('openLoraModal').addEventListener('click', () => {
  document.getElementById('loraModalBackdrop').classList.add('open');
  renderLoraTree();
  renderLoraGrid(document.getElementById('loraSearch').value);
});
document.getElementById('closeLoraModal').addEventListener('click', () => {
  document.getElementById('loraModalBackdrop').classList.remove('open');
});
document.getElementById('loraModalBackdrop').addEventListener('click', (e) => {
  if (e.target.id === 'loraModalBackdrop') e.target.classList.remove('open');
});
document.getElementById('loraSearch').addEventListener('input', e => renderLoraGrid(e.target.value));

// ---- settings modal (general + workflow tabs) ----
let DETECTOR_MODELS = null;
let OLLAMA_MODELS = null;

document.querySelectorAll('.settings-tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.settings-tab').forEach(t => t.classList.toggle('active', t === tab));
    document.querySelectorAll('.settings-panel').forEach(p => {
      p.style.display = p.dataset.panel === tab.dataset.panel ? '' : 'none';
    });
  });
});

document.getElementById('openSettingsModal').addEventListener('click', async () => {
  document.getElementById('settingsModalBackdrop').classList.add('open');
  try {
    if (!DETECTOR_MODELS) DETECTOR_MODELS = await api('/api/library/detector-models');
    const settings = await api('/api/settings');
    document.querySelectorAll('#settingsList input[data-toggle]').forEach(input => {
      input.checked = !!settings[input.dataset.toggle];
    });
    document.querySelectorAll('[data-panel="workflow"] select[data-model]').forEach(select => {
      const current = settings[select.dataset.model];
      select.innerHTML = DETECTOR_MODELS.map(m =>
        `<option value="${m}" ${m === current ? 'selected' : ''}>${m}</option>`
      ).join('');
      if (current && !DETECTOR_MODELS.includes(current)) {
        select.insertAdjacentHTML('afterbegin', `<option value="${current}" selected>${current} (no instalado)</option>`);
      }
    });
    try {
      if (!OLLAMA_MODELS) OLLAMA_MODELS = await api('/api/library/ollama-models');
      const select = document.getElementById('ollamaModelSelect');
      const current = settings.ollama_model;
      select.innerHTML = OLLAMA_MODELS.map(m =>
        `<option value="${m}" ${m === current ? 'selected' : ''}>${m}</option>`
      ).join('');
      if (current && !OLLAMA_MODELS.includes(current)) {
        select.insertAdjacentHTML('afterbegin', `<option value="${current}" selected>${current} (no instalado)</option>`);
      }
    } catch (e) {
      showToast('No se pudo conectar con Ollama: ' + e.message, true);
    }
  } catch (e) {
    showToast('No se pudieron cargar los ajustes: ' + e.message, true);
  }
});
document.getElementById('closeSettingsModal').addEventListener('click', () => {
  document.getElementById('settingsModalBackdrop').classList.remove('open');
});
document.getElementById('settingsModalBackdrop').addEventListener('click', (e) => {
  if (e.target.id === 'settingsModalBackdrop') e.target.classList.remove('open');
});
document.querySelectorAll('#settingsList input[data-toggle]').forEach(input => {
  input.addEventListener('change', async () => {
    try {
      await api('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ [input.dataset.toggle]: input.checked }),
      });
    } catch (e) {
      input.checked = !input.checked;
      showToast('No se pudo guardar el ajuste: ' + e.message, true);
    }
  });
});
document.querySelectorAll('#settingsList select[data-model]').forEach(select => {
  select.addEventListener('change', async () => {
    try {
      await api('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ [select.dataset.model]: select.value }),
      });
    } catch (e) {
      showToast('No se pudo guardar el modelo: ' + e.message, true);
    }
  });
});

document.getElementById('syncLoras').addEventListener('click', async (e) => {
  const btn = e.currentTarget;
  if (btn.classList.contains('spinning')) return;
  btn.classList.add('spinning');
  try {
    await loadLoras();
    renderLoraTree();
    renderLoraGrid(document.getElementById('loraSearch').value);
    showToast(`Biblioteca LoRA sincronizada · ${LORA_LIBRARY.length} disponibles`);
  } catch (e2) {
    showToast('Sync de LoRAs falló: ' + e2.message, true);
  } finally {
    btn.classList.remove('spinning');
  }
});

// ================= CHECKPOINTS + SAMPLING =================
async function loadCheckpoints(preserveSelection = true) {
  const sel = document.getElementById('checkpoint');
  const prev = preserveSelection ? sel.value : null;
  const list = await api('/api/library/checkpoints');
  sel.innerHTML = '';
  list.forEach(name => {
    const opt = document.createElement('option');
    opt.value = name;
    opt.textContent = name;
    sel.appendChild(opt);
  });
  if (prev && list.includes(prev)) sel.value = prev;
  return list;
}

document.getElementById('syncCheckpoints').addEventListener('click', async (e) => {
  const btn = e.currentTarget;
  if (btn.classList.contains('spinning')) return;
  btn.classList.add('spinning');
  try {
    const list = await loadCheckpoints();
    showToast(`Checkpoints sincronizados · ${list.length} disponibles`);
  } catch (e2) {
    showToast('Sync de checkpoints falló: ' + e2.message, true);
  } finally {
    btn.classList.remove('spinning');
  }
});

// ================= CHECKPOINT GALLERY =================
let CKPT_LIBRARY = [];
let selectedCkptFolder = null;

function findCkpt(ckptName) {
  return CKPT_LIBRARY.find(c => c.ckpt_name === ckptName);
}

function updateCkptCurrentDisplay() {
  const ckptName = document.getElementById('checkpoint').value;
  const lib = findCkpt(ckptName);
  document.getElementById('ckptCurrentName').textContent = lib ? lib.display_name : (ckptName || '—');
  const thumb = document.getElementById('ckptCurrentThumb');
  thumb.innerHTML = '';
  thumb.style.backgroundImage = '';
  if (lib && lib.preview_url) {
    if (lib.preview_type === 'video') {
      thumb.appendChild(Object.assign(document.createElement('video'), {
        src: lib.preview_url, autoplay: true, loop: true, muted: true, playsInline: true, className: 'ckpt-thumb-media',
      }));
    } else {
      thumb.style.backgroundImage = `url('${lib.preview_url}')`;
    }
  }
  renderLoraStack();
  if (document.getElementById('loraModalBackdrop').classList.contains('open')) {
    renderLoraGrid(document.getElementById('loraSearch').value);
  }
}

function renderCkptTree() {
  renderFolderTree('ckptTree', CKPT_LIBRARY, selectedCkptFolder, (path) => {
    selectedCkptFolder = path;
    renderCkptTree();
    renderCkptGrid(document.getElementById('ckptSearch').value);
  });
}

function renderCkptGrid(filter = '') {
  const grid = document.getElementById('ckptGrid');
  grid.innerHTML = '';
  const q = filter.trim().toLowerCase();
  const current = document.getElementById('checkpoint').value;
  const filtered = CKPT_LIBRARY.filter(c =>
    itemInFolder(c, selectedCkptFolder) &&
    (!q || c.display_name.toLowerCase().includes(q) || c.ckpt_name.toLowerCase().includes(q))
  );
  if (!filtered.length) {
    grid.innerHTML = `<div class="empty-note">sin resultados</div>`;
    return;
  }
  filtered.forEach(c => {
    const isSelected = c.ckpt_name === current;
    const card = document.createElement('div');
    card.className = 'lora-pick' + (isSelected ? ' selected' : '');
    card.innerHTML = `
      ${loraThumbHtml(c, 'art')}
      <div class="info">
        <div class="name">${c.display_name}</div>
        <div class="trig">${c.base_model || c.ckpt_name}</div>
      </div>
    `;
    card.addEventListener('click', () => {
      document.getElementById('checkpoint').value = c.ckpt_name;
      updateCkptCurrentDisplay();
      document.getElementById('ckptModalBackdrop').classList.remove('open');
    });
    grid.appendChild(card);
  });
}

async function loadCkptGallery() {
  CKPT_LIBRARY = await api('/api/library/checkpoint-gallery');
  updateCkptCurrentDisplay();
}

document.getElementById('openCkptModal').addEventListener('click', () => {
  document.getElementById('ckptModalBackdrop').classList.add('open');
  renderCkptTree();
  renderCkptGrid(document.getElementById('ckptSearch').value);
});
document.getElementById('closeCkptModal').addEventListener('click', () => {
  document.getElementById('ckptModalBackdrop').classList.remove('open');
});
document.getElementById('ckptModalBackdrop').addEventListener('click', (e) => {
  if (e.target.id === 'ckptModalBackdrop') e.target.classList.remove('open');
});
document.getElementById('ckptSearch').addEventListener('input', e => renderCkptGrid(e.target.value));

document.getElementById('syncCkptGallery').addEventListener('click', async (e) => {
  const btn = e.currentTarget;
  if (btn.classList.contains('spinning')) return;
  btn.classList.add('spinning');
  try {
    await loadCkptGallery();
    renderCkptTree();
    renderCkptGrid(document.getElementById('ckptSearch').value);
    showToast(`Biblioteca de checkpoints sincronizada · ${CKPT_LIBRARY.length} disponibles`);
  } catch (e2) {
    showToast('Sync de checkpoints falló: ' + e2.message, true);
  } finally {
    btn.classList.remove('spinning');
  }
});

async function loadSampling() {
  const data = await api('/api/library/sampling');
  const samplerSel = document.getElementById('sampler');
  const schedulerSel = document.getElementById('scheduler');
  const prevSampler = samplerSel.value, prevScheduler = schedulerSel.value;
  samplerSel.innerHTML = data.samplers.map(s => `<option value="${s}">${s}</option>`).join('');
  schedulerSel.innerHTML = data.schedulers.map(s => `<option value="${s}">${s}</option>`).join('');
  if (data.samplers.includes(prevSampler)) samplerSel.value = prevSampler;
  else if (data.samplers.includes('euler_ancestral')) samplerSel.value = 'euler_ancestral';
  if (data.schedulers.includes(prevScheduler)) schedulerSel.value = prevScheduler;
  else if (data.schedulers.includes('normal')) schedulerSel.value = 'normal';
  return data;
}

document.getElementById('syncSampling').addEventListener('click', async (e) => {
  e.preventDefault();
  const btn = e.currentTarget;
  if (btn.classList.contains('spinning')) return;
  btn.classList.add('spinning');
  try {
    await loadSampling();
    showToast('Samplers/schedulers sincronizados');
  } catch (e2) {
    showToast('Sync falló: ' + e2.message, true);
  } finally {
    btn.classList.remove('spinning');
  }
});

['steps', 'cfg', 'sampler'].forEach(id => {
  document.getElementById(id).addEventListener('input', () => {
    document.getElementById('stepsMeta').textContent = document.getElementById('steps').value;
    document.getElementById('cfgMeta').textContent = document.getElementById('cfg').value;
    document.getElementById('samplerMeta').textContent = document.getElementById('sampler').value;
  });
  document.getElementById(id).addEventListener('change', () => {
    document.getElementById('stepsMeta').textContent = document.getElementById('steps').value;
    document.getElementById('cfgMeta').textContent = document.getElementById('cfg').value;
    document.getElementById('samplerMeta').textContent = document.getElementById('sampler').value;
  });
});

// ================= SEED =================
let seedLocked = false;
document.getElementById('randomSeed').addEventListener('click', () => {
  if (seedLocked) return;
  const v = Math.floor(Math.random() * 1e9);
  document.getElementById('seed').value = v;
  document.getElementById('seedMeta').textContent = v;
});
document.getElementById('lockSeed').addEventListener('click', (e) => {
  seedLocked = !seedLocked;
  e.currentTarget.classList.toggle('locked', seedLocked);
});
document.getElementById('seed').addEventListener('input', e => {
  document.getElementById('seedMeta').textContent = e.target.value;
});

// ================= CLEAR ALL =================
document.getElementById('clearAllBtn').addEventListener('click', () => {
  document.getElementById('positive').value = '';
  document.getElementById('negative').value = '';
  loraStack = [];
  renderLoraStack();
  if (!seedLocked) {
    document.getElementById('seed').value = -1;
    document.getElementById('seedMeta').textContent = -1;
  }
  showToast('Prompt y LoRA limpiados');
});

// ================= PROMPT TEMPLATE =================
const PROMPT_TEMPLATE = [
  'masterpiece, best quality, very aesthetic, absurdres,',
  '[1girl / 1boy / solo / 2girls / ...],',
  '[hair],',
  '[eyes],',
  '[outfit, body features],',
  '[pose / action or interaction clause],',
  '[background, setting, lighting],',
  '[camera, composition],',
  '[rating: safe / sensitive / nsfw / explicit]',
].join('\n');
document.getElementById('templatePromptBtn').addEventListener('click', () => {
  const field = document.getElementById('positive');
  if (field.value.trim() && !confirm('Esto reemplaza el texto actual del Positive con la plantilla. ¿Continuar?')) {
    return;
  }
  field.value = PROMPT_TEMPLATE;
  field.focus();
  showToast('Plantilla insertada — completá cada [placeholder]');
});

// ================= ENHANCE PROMPT (Ollama) =================
document.getElementById('enhancePromptBtn').addEventListener('click', async (e) => {
  const btn = e.currentTarget;
  if (btn.classList.contains('spinning')) return;
  const field = document.getElementById('positive');
  const current = field.value.trim();
  if (!current) {
    showToast('Escribí algo en Positive primero', true);
    return;
  }
  btn.classList.add('spinning');
  try {
    const res = await api('/api/enhance-prompt', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt: current }),
    });
    field.value = res.prompt;
    showToast('Prompt mejorado con IA');
  } catch (err) {
    showToast('No se pudo mejorar el prompt: ' + err.message, true);
  } finally {
    btn.classList.remove('spinning');
  }
});

// ================= HISTORY =================
let historyScope = 'current';
let historyImages = []; // flat {path, id, seed, project} across all rows currently loaded
function renderHistoryFilter() {
  const el = document.getElementById('historyFilter');
  el.innerHTML = `
    <span class="chip ${historyScope === 'current' ? 'active' : ''}" data-scope="current">${currentProject}</span>
    <span class="chip ${historyScope === 'all' ? 'active' : ''}" data-scope="all">todos los proyectos</span>
  `;
  el.querySelectorAll('.chip').forEach(c => {
    c.addEventListener('click', () => {
      historyScope = c.dataset.scope;
      renderHistoryFilter();
      loadHistory();
    });
  });
}
renderHistoryFilter();

document.getElementById('syncHistoryBtn').addEventListener('click', async (e) => {
  const btn = e.currentTarget;
  btn.classList.add('spinning');
  try {
    const res = await api('/api/history/sync', { method: 'POST' });
    showToast(`Sincronizado: ${res.updated} actualizadas, ${res.deleted} eliminadas`);
    loadHistory();
  } catch (err) {
    showToast('No se pudo sincronizar: ' + err.message, true);
  } finally {
    btn.classList.remove('spinning');
  }
});

function outputUrl(relPath) {
  return '/outputs/' + relPath.split('/').map(encodeURIComponent).join('/');
}

async function loadHistory() {
  const grid = document.getElementById('historyGrid');
  const scopeParam = historyScope === 'all' ? '__all__' : currentProject;
  let rows;
  try {
    rows = await api(`/api/history?project=${encodeURIComponent(scopeParam)}&limit=4`);
  } catch (e) {
    grid.innerHTML = `<div class="empty-note">no se pudo cargar el historial</div>`;
    return;
  }
  if (!rows.length) {
    grid.innerHTML = `<div class="empty-note">sin generaciones todavía en «${currentProject}»</div>`;
    return;
  }
  grid.innerHTML = '';
  historyImages = [];
  rows.forEach((h, i) => {
    const images = JSON.parse(h.image_paths_json || '[]');
    const startIndex = historyImages.length;
    images.forEach(p => historyImages.push({ path: p, id: h.id, seed: h.seed, project: h.project }));
    const item = document.createElement('div');
    item.className = 'history-item' + (h.status !== 'done' ? ' pending' : '');
    if (images.length) {
      item.style.backgroundImage = `url('${outputUrl(images[0])}')`;
    }
    item.innerHTML = `
      <span class="frame-no">${historyScope === 'all' ? h.project : '#' + String(rows.length - i).padStart(3, '0')}</span>
      ${images.length > 1 ? `<span class="img-count">1/${images.length}</span>` : ''}
      ${images.length ? `<button class="expand-btn" title="Ver imágenes">⤢</button>` : ''}
      ${(h.status === 'queued' || h.status === 'running') ? `<span class="pending-icon">⟳</span>` : ''}
      <div class="badge">
        <span>seed ${String(h.seed).slice(0, 8)}</span><span>${h.status}</span>
        <button class="delete-btn" title="Eliminar">🗑</button>
      </div>
    `;
    item.addEventListener('click', () => restoreGeneration(h.id));
    if (images.length) {
      item.querySelector('.expand-btn').addEventListener('click', (e) => {
        e.stopPropagation();
        openLightbox(historyImages.map(x => x.path), startIndex, historyImages);
      });
    }
    item.querySelector('.delete-btn').addEventListener('click', (e) => {
      e.stopPropagation();
      deleteSingleGeneration(h.id, loadHistory);
    });
    grid.appendChild(item);
  });
}

async function deleteSingleGeneration(id, onDeleted) {
  if (!confirm('¿Eliminar esta generación? Se borra también la imagen del disco. Esta acción no se puede deshacer.')) return;
  try {
    await api(`/api/history/${id}`, { method: 'DELETE' });
    showToast('Generación eliminada');
    if (onDeleted) onDeleted();
  } catch (e) {
    showToast('No se pudo eliminar: ' + e.message, true);
  }
}

async function restoreGeneration(id) {
  try {
    const g = await api(`/api/generation/${id}`);
    document.getElementById('positive').value = g.positive_prompt || '';
    document.getElementById('negative').value = g.negative_prompt || '';
    document.getElementById('seed').value = seedLocked ? g.seed : -1;
    document.getElementById('seedMeta').textContent = g.seed;
    document.getElementById('width').value = g.width;
    document.getElementById('height').value = g.height;
    customSizeActive = true;
    document.getElementById('customSizeRow').classList.add('open');
    applySize(g.width, g.height);
    renderSizeGrid();
    batchInput.value = g.batch_size;
    renderFrames(clampBatch(g.batch_size));
    document.getElementById('steps').value = g.steps;
    document.getElementById('cfg').value = g.cfg;
    document.getElementById('sampler').value = g.sampler;
    document.getElementById('scheduler').value = g.scheduler;
    document.getElementById('stepsMeta').textContent = g.steps;
    document.getElementById('cfgMeta').textContent = g.cfg;
    document.getElementById('samplerMeta').textContent = g.sampler;
    if ([...document.getElementById('checkpoint').options].some(o => o.value === g.checkpoint)) {
      document.getElementById('checkpoint').value = g.checkpoint;
      updateCkptCurrentDisplay();
    }
    loraStack = JSON.parse(g.loras_json || '[]');
    renderLoraStack();
    loraStack.forEach(s => {
      const lib = findLora(s.name);
      if (lib && lib.triggers.length) addTriggerWordToPositive(lib.triggers[0], { silent: true });
    });
    if (PROJECTS.includes(g.project)) {
      currentProject = g.project;
      renderProjectSelect();
      renderHistoryFilter();
    }
    const images = JSON.parse(g.image_paths_json || '[]');
    if (images.length) setFramesResult(images, false);
    showToast('Parámetros restaurados desde el historial');
  } catch (e) {
    showToast('No se pudo restaurar: ' + e.message, true);
  }
}

// ================= FULL HISTORY BROWSER =================
const HISTORY_PAGE_SIZE = 16;
let historyModalScope = '(root)';
let historyModalPage = 0;
let historyModalRows = [];
let modalHistoryImages = []; // flat {path, id, seed, project} for the modal's lightbox
let historySelectMode = false;
let historySelectedIds = new Set();
let historyModalHasMore = false;

function renderHistoryModalTree() {
  const el = document.getElementById('historyModalTree');
  el.innerHTML = `
    ${PROJECTS.map(p => `<div class="tree-item${historyModalScope === p ? ' active' : ''}" data-project="${p}">${p === '(root)' ? '— root —' : p}</div>`).join('')}
  `;
  el.querySelectorAll('.tree-item').forEach(item => {
    item.addEventListener('click', () => {
      historyModalScope = item.dataset.project;
      renderHistoryModalTree();
      loadHistoryModalPage(true);
    });
  });
}

async function loadHistoryModalPage(reset, page) {
  const grid = document.getElementById('historyModalGrid');
  if (reset) {
    historyModalPage = 0;
    grid.innerHTML = `<div class="empty-note">cargando…</div>`;
  } else if (typeof page === 'number') {
    historyModalPage = page;
    grid.innerHTML = `<div class="empty-note">cargando…</div>`;
  }
  let rows;
  try {
    rows = await api(`/api/history?project=${encodeURIComponent(historyModalScope)}&limit=${HISTORY_PAGE_SIZE}&offset=${historyModalPage * HISTORY_PAGE_SIZE}`);
  } catch (e) {
    grid.innerHTML = `<div class="empty-note">no se pudo cargar el historial</div>`;
    return;
  }
  if (!rows.length && historyModalPage > 0) {
    historyModalPage -= 1;
    return loadHistoryModalPage(false, historyModalPage);
  }
  if (!rows.length) {
    grid.innerHTML = `<div class="empty-note">sin generaciones todavía</div>`;
    renderHistoryPager();
    return;
  }
  historyModalRows = rows;
  historyModalHasMore = rows.length === HISTORY_PAGE_SIZE;
  renderHistoryModalGrid();
  renderHistoryPager();
}

function renderHistoryPager() {
  const pager = document.getElementById('historyPager');
  const hasRows = historyModalRows.length > 0;
  pager.style.display = hasRows ? 'flex' : 'none';
  document.getElementById('historyPagerLabel').textContent = `página ${historyModalPage + 1}`;
  document.getElementById('historyPagerPrev').disabled = historyModalPage === 0;
  document.getElementById('historyPagerNext').disabled = !historyModalHasMore;
}

function renderHistoryModalGrid() {
  const grid = document.getElementById('historyModalGrid');
  grid.innerHTML = '';
  modalHistoryImages = [];
  historyModalRows.forEach((h) => {
    const images = JSON.parse(h.image_paths_json || '[]');
    const startIndex = modalHistoryImages.length;
    images.forEach(p => modalHistoryImages.push({ path: p, id: h.id, seed: h.seed, project: h.project }));
    const item = document.createElement('div');
    item.className = 'history-item' + (h.status !== 'done' ? ' pending' : '') + (historySelectedIds.has(h.id) ? ' selected' : '');
    if (images.length) item.style.backgroundImage = `url('${outputUrl(images[0])}')`;
    item.innerHTML = `
      <span class="frame-no">${String(h.created_at).slice(0, 10)}</span>
      <span class="select-check"></span>
      ${images.length > 1 ? `<span class="img-count">1/${images.length}</span>` : ''}
      ${images.length ? `<button class="expand-btn" title="Ver imágenes">⤢</button>` : ''}
      ${(h.status === 'queued' || h.status === 'running') ? `<span class="pending-icon">⟳</span>` : ''}
      <div class="badge">
        <span>seed ${String(h.seed).slice(0, 8)}</span><span>${h.status}</span>
        <button class="delete-btn" title="Eliminar">🗑</button>
      </div>
    `;
    item.addEventListener('click', () => {
      if (historySelectMode) {
        toggleHistorySelection(h.id, item);
        return;
      }
      restoreGeneration(h.id);
      closeHistoryModal();
    });
    if (images.length) {
      item.querySelector('.expand-btn').addEventListener('click', (e) => {
        e.stopPropagation();
        openLightbox(modalHistoryImages.map(x => x.path), startIndex, modalHistoryImages);
      });
    }
    item.querySelector('.delete-btn').addEventListener('click', (e) => {
      e.stopPropagation();
      deleteSingleGeneration(h.id, () => loadHistoryModalPage(true));
    });
    grid.appendChild(item);
  });
}

function toggleHistorySelection(id, itemEl) {
  if (historySelectedIds.has(id)) {
    historySelectedIds.delete(id);
    itemEl.classList.remove('selected');
  } else {
    historySelectedIds.add(id);
    itemEl.classList.add('selected');
  }
  renderHistoryBulkBar();
}

function renderHistoryBulkBar() {
  const bar = document.getElementById('historyBulkBar');
  const count = historySelectedIds.size;
  document.getElementById('historyBulkCount').textContent = `${count} seleccionada${count === 1 ? '' : 's'}`;
  bar.classList.toggle('open', historySelectMode && count > 0);
}

function setHistorySelectMode(on) {
  historySelectMode = on;
  historySelectedIds.clear();
  document.getElementById('historyModalGrid').classList.toggle('select-mode', on);
  document.getElementById('historySelectToggle').classList.toggle('active', on);
  renderHistoryModalGrid();
  renderHistoryBulkBar();
}

document.getElementById('historySelectToggle').addEventListener('click', () => {
  setHistorySelectMode(!historySelectMode);
});
document.getElementById('historyBulkCancel').addEventListener('click', () => {
  setHistorySelectMode(false);
});
document.getElementById('historyBulkDelete').addEventListener('click', async () => {
  const ids = [...historySelectedIds];
  if (!ids.length) return;
  if (!confirm(`¿Eliminar ${ids.length} generación(es)? Se borran también las imágenes del disco. Esta acción no se puede deshacer.`)) return;
  try {
    const res = await api('/api/history/delete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids }),
    });
    showToast(`${res.deleted} generación(es) eliminadas`);
    setHistorySelectMode(false);
    loadHistoryModalPage(true);
  } catch (e) {
    showToast('No se pudo eliminar: ' + e.message, true);
  }
});

function openHistoryModal() {
  document.getElementById('historyModalBackdrop').classList.add('open');
  setHistorySelectMode(false);
  renderHistoryModalTree();
  loadHistoryModalPage(true);
}
function closeHistoryModal() {
  document.getElementById('historyModalBackdrop').classList.remove('open');
}
document.getElementById('openHistoryModal').addEventListener('click', openHistoryModal);
document.getElementById('historyPagerPrev').addEventListener('click', () => {
  if (historyModalPage > 0) loadHistoryModalPage(false, historyModalPage - 1);
});
document.getElementById('historyPagerNext').addEventListener('click', () => {
  if (historyModalHasMore) loadHistoryModalPage(false, historyModalPage + 1);
});
document.getElementById('closeHistoryModal').addEventListener('click', closeHistoryModal);
document.getElementById('historyModalBackdrop').addEventListener('click', (e) => {
  if (e.target.id === 'historyModalBackdrop') closeHistoryModal();
});

// ================= GENERATE =================
let polling = null;

let canvasImages = [];
function setFramesResult(images, isError) {
  const frames = [...document.querySelectorAll('.frame')];
  frames.forEach(f => f.classList.remove('generating'));
  if (isError) {
    frames.forEach(f => {
      f.classList.add('error');
      f.innerHTML = `<span class="error-icon">⚠</span>`;
    });
    canvasImages = [];
    return;
  }
  canvasImages = images || [];
  frames.forEach((f, i) => {
    const path = images[i];
    if (path) {
      f.innerHTML = `<img src="${outputUrl(path)}" alt="">`;
      f.dataset.index = i;
    }
  });
}

framesGrid.addEventListener('click', (e) => {
  const frame = e.target.closest('.frame');
  if (!frame || !frame.querySelector('img')) return;
  openLightbox(canvasImages, parseInt(frame.dataset.index, 10) || 0);
});

// ================= LIGHTBOX =================
let lightboxImages = [];
let lightboxMetaList = null; // parallel {path, id, seed, project}[], or null when browsing canvas-only images
let lightboxIndex = 0;

function renderLightbox() {
  document.getElementById('lightboxImg').src = outputUrl(lightboxImages[lightboxIndex]);
  let metaText = `${lightboxIndex + 1} / ${lightboxImages.length}`;
  const restoreBtn = document.getElementById('lightboxRestore');
  const m = lightboxMetaList && lightboxMetaList[lightboxIndex];
  if (m) {
    metaText += ` · seed ${String(m.seed).slice(0, 8)}`;
    if (historyScope === 'all') metaText += ` · ${m.project}`;
    restoreBtn.style.display = 'inline-flex';
  } else {
    restoreBtn.style.display = 'none';
  }
  document.getElementById('lightboxMeta').textContent = metaText;
  const multi = lightboxImages.length > 1;
  document.getElementById('lightboxPrev').style.visibility = multi ? 'visible' : 'hidden';
  document.getElementById('lightboxNext').style.visibility = multi ? 'visible' : 'hidden';
}

function openLightbox(images, index, metaList) {
  if (!images || !images.length) return;
  lightboxImages = images;
  lightboxMetaList = metaList || null;
  lightboxIndex = Math.max(0, Math.min(index, images.length - 1));
  renderLightbox();
  document.getElementById('lightboxBackdrop').classList.add('open');
}

function closeLightbox() {
  document.getElementById('lightboxBackdrop').classList.remove('open');
}

document.getElementById('closeLightbox').addEventListener('click', closeLightbox);
document.getElementById('lightboxBackdrop').addEventListener('click', (e) => {
  if (e.target.id === 'lightboxBackdrop') closeLightbox();
});
document.getElementById('lightboxPrev').addEventListener('click', () => {
  lightboxIndex = (lightboxIndex - 1 + lightboxImages.length) % lightboxImages.length;
  renderLightbox();
});
document.getElementById('lightboxNext').addEventListener('click', () => {
  lightboxIndex = (lightboxIndex + 1) % lightboxImages.length;
  renderLightbox();
});
document.getElementById('lightboxRestore').addEventListener('click', () => {
  const m = lightboxMetaList && lightboxMetaList[lightboxIndex];
  if (!m) return;
  restoreGeneration(m.id);
  closeLightbox();
});
document.addEventListener('keydown', (e) => {
  if (!document.getElementById('lightboxBackdrop').classList.contains('open')) return;
  if (e.key === 'Escape') closeLightbox();
  if (e.key === 'ArrowLeft') document.getElementById('lightboxPrev').click();
  if (e.key === 'ArrowRight') document.getElementById('lightboxNext').click();
});

async function pollStatus(generationId) {
  try {
    const g = await api(`/api/status/${generationId}`);
    if (g.status === 'done') {
      clearInterval(polling);
      polling = null;
      document.getElementById('batchProgress').classList.remove('active');
      document.getElementById('progressFill').classList.remove('indeterminate');
      document.getElementById('queueInfo').textContent = 'queue — idle';
      document.getElementById('logPeek').textContent = '';
      document.getElementById('generateBtn').disabled = false;
      const images = JSON.parse(g.image_paths_json || '[]');
      setFramesResult(images, false);
      loadHistory();
    } else if (g.status === 'error') {
      clearInterval(polling);
      polling = null;
      document.getElementById('batchProgress').classList.remove('active');
      document.getElementById('generateBtn').disabled = false;
      document.getElementById('queueInfo').textContent = 'queue — error';
      document.getElementById('logPeek').textContent = '';
      setFramesResult([], true);
      showToast('La generación falló en ComfyUI', true);
      loadHistory();
    } else {
      document.getElementById('progressLabel').textContent =
        g.status === 'running' ? 'Generando…' : 'En cola…';
      document.getElementById('logPeek').textContent = g.last_log || '';
    }
  } catch (e) {
    // transient network hiccup while polling — keep trying silently
  }
}

document.getElementById('generateBtn').addEventListener('click', async () => {
  const checkpoint = document.getElementById('checkpoint').value;
  if (!checkpoint) {
    showToast('No hay checkpoint seleccionado', true);
    return;
  }
  const incompatible = loraStack
    .map(s => findLora(s.name))
    .filter(lib => lib && !loraCompatible(lib));
  if (incompatible.length) {
    const names = incompatible.map(l => `${l.display_name} (${l.base_model})`).join('\n');
    const ckptBase = (findCkpt(checkpoint) || {}).base_model || '?';
    const proceed = confirm(
      `Estos LoRAs no son compatibles con el checkpoint activo (${ckptBase}):\n\n${names}\n\n¿Generar de todas formas?`
    );
    if (!proceed) return;
  }
  const payload = {
    project: currentProject,
    positive_prompt: document.getElementById('positive').value,
    negative_prompt: document.getElementById('negative').value,
    loras: loraStack,
    seed: parseInt(document.getElementById('seed').value, 10) || -1,
    width: parseInt(document.getElementById('width').value, 10),
    height: parseInt(document.getElementById('height').value, 10),
    batch_size: clampBatch(batchInput.value),
    steps: parseInt(document.getElementById('steps').value, 10),
    cfg: parseFloat(document.getElementById('cfg').value),
    sampler: document.getElementById('sampler').value,
    scheduler: document.getElementById('scheduler').value,
    checkpoint,
  };

  const btn = document.getElementById('generateBtn');
  btn.disabled = true;
  renderFrames(payload.batch_size);
  document.querySelectorAll('.frame').forEach(f => f.classList.add('generating'));
  document.getElementById('batchProgress').classList.add('active');
  document.getElementById('progressFill').classList.add('indeterminate');
  document.getElementById('progressLabel').textContent = 'Enviando a ComfyUI…';
  document.getElementById('logPeek').textContent = '';
  document.getElementById('queueInfo').textContent = `queue — running (${payload.batch_size} imagen${payload.batch_size > 1 ? 'es' : ''})`;

  try {
    const res = await api('/api/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    document.getElementById('seedMeta').textContent = res.seed;
    if (!seedLocked) {
      document.getElementById('seed').value = -1;
    }
    if (polling) clearInterval(polling);
    polling = setInterval(() => pollStatus(res.generation_id), 1200);
    pollStatus(res.generation_id);
  } catch (e) {
    btn.disabled = false;
    document.getElementById('batchProgress').classList.remove('active');
    setFramesResult([], true);
    showToast('No se pudo lanzar la generación: ' + e.message, true);
  }
});

// ================= INIT =================
(async function init() {
  try {
    const [checkpoints] = await Promise.all([
      loadCheckpoints(false),
      loadSampling(),
      loadProjects(),
    ]);
    const defaultCkpt = checkpoints.find(c => c.includes('veteDuskroseILL_v3'));
    if (defaultCkpt) document.getElementById('checkpoint').value = defaultCkpt;

    await loadLoras();
    await loadCkptGallery();

    document.getElementById('stepsMeta').textContent = document.getElementById('steps').value;
    document.getElementById('cfgMeta').textContent = document.getElementById('cfg').value;
    document.getElementById('samplerMeta').textContent = document.getElementById('sampler').value;

    renderHistoryFilter();
    loadHistory();
  } catch (e) {
    showToast('No se pudo inicializar: ' + e.message + ' — ¿ComfyUI está corriendo en 8188?', true);
  }
})();
