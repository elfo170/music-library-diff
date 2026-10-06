const CATEGORY_LABELS = {
  all: "Todas",
  IDENTICAL: "Em ambas",
  ONLY_A: "Apenas A",
  ONLY_B: "Apenas B",
  POSSIBLE_DUPLICATE: "Duplicatas",
  SAME_SONG_DIFFERENT_FILE: "Arquivos diferentes",
};

const CATEGORY_COLORS = {
  IDENTICAL: "var(--identical)",
  ONLY_A: "var(--lib-a)",
  ONLY_B: "var(--lib-b)",
  POSSIBLE_DUPLICATE: "var(--duplicate)",
  SAME_SONG_DIFFERENT_FILE: "var(--same-song)",
};

const SUMMARY_ORDER = ["IDENTICAL", "ONLY_A", "ONLY_B", "POSSIBLE_DUPLICATE", "SAME_SONG_DIFFERENT_FILE"];
const TAB_ORDER = ["all", ...SUMMARY_ORDER];
const PAGE_SIZE = 100;

const state = {
  scanId: null,
  pollTimer: null,
  category: "all",
  matches: [],
  selected: new Set(),
  limit: PAGE_SIZE,
  filtered: [],
};

const $ = (id) => document.getElementById(id);
const els = {
  libraryA: $("library-a"),
  libraryB: $("library-b"),
  analyzeBtn: $("analyze-btn"),
  formError: $("form-error"),
  progressPanel: $("progress-panel"),
  progressMessage: $("progress-message"),
  progressFill: $("progress-fill"),
  progressCount: $("progress-count"),
  resultsPanel: $("results-panel"),
  summaryRow: $("summary-row"),
  tabs: $("tabs"),
  resultsList: $("results-list"),
  errorsBanner: $("errors-banner"),
  resultCount: $("result-count"),
  showMore: $("show-more"),
  selectAll: $("select-all"),
  selectionCount: $("selection-count"),
  modal: $("modal"),
  modalBox: $("modal-box"),
};

/* ---------- utilidades ---------- */

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function formatBytes(bytes) {
  if (bytes === null || bytes === undefined) return "";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let i = 0;
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024;
    i += 1;
  }
  return `${value.toFixed(1)} ${units[i]}`;
}

function formatDuration(seconds) {
  if (seconds === null || seconds === undefined) return "";
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

function trackLabel(match) {
  const track = match.track_a || match.track_b;
  if (!track) return "(sem informação)";
  return `${track.artist || "Artista desconhecido"} - ${track.title || "(sem título)"}`;
}

function techSummary(track) {
  const parts = [track.format || ""];
  if (track.bitrate) parts.push(`${Math.round(track.bitrate / 1000)} kbps`);
  parts.push(formatBytes(track.size));
  if (track.duration) parts.push(formatDuration(track.duration));
  return parts.filter(Boolean).join("  ");
}

function showFormError(message) {
  els.formError.textContent = message;
  els.formError.hidden = false;
}

async function api(url, options) {
  const response = await fetch(url, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `Erro ${response.status}`);
  return data;
}

function postJson(url, body) {
  return api(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

/* ---------- análise ---------- */

async function startAnalysis() {
  els.formError.hidden = true;
  const libraryA = els.libraryA.value.trim();
  const libraryB = els.libraryB.value.trim();
  if (!libraryA || !libraryB) {
    showFormError("Informe as duas pastas antes de analisar.");
    return;
  }
  els.analyzeBtn.disabled = true;
  els.resultsPanel.hidden = true;
  try {
    const data = await postJson("/api/scans", { library_a: libraryA, library_b: libraryB });
    state.scanId = data.scan_id;
    state.selected.clear();
    els.progressPanel.hidden = false;
    pollProgress();
  } catch (err) {
    showFormError(err.message);
    els.analyzeBtn.disabled = false;
  }
}

function pollProgress() {
  clearTimeout(state.pollTimer);
  state.pollTimer = setTimeout(async () => {
    try {
      const data = await api(`/api/scans/${state.scanId}`);
      renderProgress(data);
      if (data.phase === "done") {
        els.analyzeBtn.disabled = false;
        await showResults(data);
      } else if (data.phase === "error") {
        els.analyzeBtn.disabled = false;
        showFormError(data.error_message || "Ocorreu um erro durante a análise.");
      } else {
        pollProgress();
      }
    } catch (err) {
      showFormError("Falha ao consultar o progresso da análise.");
      els.analyzeBtn.disabled = false;
    }
  }, 600);
}

function renderProgress(data) {
  const labels = {
    pending: "Preparando...",
    scanning_a: "Escaneando Biblioteca A...",
    scanning_b: "Escaneando Biblioteca B...",
    comparing: "Comparando bibliotecas...",
    done: "Análise concluída.",
    error: "Erro na análise.",
  };
  els.progressMessage.textContent = labels[data.phase] || data.message || "";
  els.progressFill.style.width = `${data.percent || 0}%`;
  els.progressCount.textContent = data.total ? `${data.current} / ${data.total} arquivos` : "";
}

async function showResults(data) {
  els.resultsPanel.hidden = false;
  if (data.errors && data.errors.length) {
    els.errorsBanner.hidden = false;
    els.errorsBanner.textContent = `${data.errors.length} arquivo(s) não puderam ser analisados e foram ignorados.`;
  } else {
    els.errorsBanner.hidden = true;
  }
  await reloadMatches();
}

async function reloadMatches() {
  const data = await api(`/api/scans/${state.scanId}/matches?category=all`);
  state.matches = data.matches || [];
  const existing = new Set(state.matches.map((m) => m.id));
  state.selected = new Set([...state.selected].filter((id) => existing.has(id)));
  populateFilterOptions();
  renderSummary();
  renderTabs();
  applyFilters(true);
}

/* ---------- resumo e abas ---------- */

function renderSummary() {
  const counts = Object.fromEntries(SUMMARY_ORDER.map((k) => [k, 0]));
  state.matches.forEach((m) => { counts[m.match_type] += 1; });
  els.summaryRow.innerHTML = SUMMARY_ORDER.map(
    (key) => `
      <div class="summary-item" style="--item-color: ${CATEGORY_COLORS[key]}">
        <span class="summary-count">${counts[key]}</span>
        <span class="summary-label">${CATEGORY_LABELS[key]}</span>
      </div>`
  ).join("");
}

function renderTabs() {
  els.tabs.innerHTML = TAB_ORDER.map(
    (cat) => `<button class="tab ${cat === state.category ? "active" : ""}" data-category="${cat}">${CATEGORY_LABELS[cat]}</button>`
  ).join("");
}

els.tabs.addEventListener("click", (event) => {
  const btn = event.target.closest(".tab");
  if (!btn) return;
  state.category = btn.dataset.category;
  renderTabs();
  applyFilters(true);
});

/* ---------- filtros ---------- */

const F = {
  text: $("f-text"), folder: $("f-folder"), side: $("f-side"), format: $("f-format"),
  sampleRate: $("f-samplerate"), bitDepth: $("f-bitdepth"),
  brMin: $("f-bitrate-min"), brMax: $("f-bitrate-max"),
  szMin: $("f-size-min"), szMax: $("f-size-max"),
  duMin: $("f-dur-min"), duMax: $("f-dur-max"),
  sort: $("f-sort"), dir: $("f-dir"),
};

function populateSelect(select, values, formatter = String) {
  const current = select.value;
  const first = select.options[0];
  select.innerHTML = "";
  select.appendChild(first);
  [...values].sort((a, b) => a - b || String(a).localeCompare(String(b))).forEach((v) => {
    const opt = document.createElement("option");
    opt.value = String(v);
    opt.textContent = formatter(v);
    select.appendChild(opt);
  });
  select.value = [...select.options].some((o) => o.value === current) ? current : "";
}

function populateFilterOptions() {
  const formats = new Set();
  const rates = new Set();
  const depths = new Set();
  state.matches.forEach((m) => [m.track_a, m.track_b].filter(Boolean).forEach((t) => {
    if (t.format) formats.add(t.format);
    if (t.sample_rate) rates.add(t.sample_rate);
    if (t.bit_depth) depths.add(t.bit_depth);
  }));
  populateSelect(F.format, formats);
  populateSelect(F.sampleRate, rates, (v) => `${v} Hz`);
  populateSelect(F.bitDepth, depths, (v) => `${v} bit`);
}

const num = (el) => (el.value === "" ? null : Number(el.value));

function readFilters() {
  return {
    words: F.text.value.toLowerCase().split(/\s+/).filter(Boolean),
    folder: F.folder.value.trim().toLowerCase(),
    side: F.side.value,
    format: F.format.value,
    sampleRate: F.sampleRate.value,
    bitDepth: F.bitDepth.value,
    brMin: num(F.brMin), brMax: num(F.brMax),
    szMin: num(F.szMin), szMax: num(F.szMax),
    duMin: num(F.duMin), duMax: num(F.duMax),
  };
}

function inRange(value, min, max) {
  if (min === null && max === null) return true;
  if (value === null || value === undefined) return false;
  return (min === null || value >= min) && (max === null || value <= max);
}

function trackPasses(t, f) {
  if (f.words.length) {
    const hay = [t.artist, t.title, t.album, t.album_artist, t.path].join(" ").toLowerCase();
    if (!f.words.every((w) => hay.includes(w))) return false;
  }
  if (f.folder && !t.path.toLowerCase().includes(f.folder)) return false;
  if (f.format && t.format !== f.format) return false;
  if (f.sampleRate && String(t.sample_rate) !== f.sampleRate) return false;
  if (f.bitDepth && String(t.bit_depth) !== f.bitDepth) return false;
  if (!inRange(t.bitrate === null ? null : t.bitrate / 1000, f.brMin, f.brMax)) return false;
  if (!inRange(t.size === null ? null : t.size / (1024 * 1024), f.szMin, f.szMax)) return false;
  if (!inRange(t.duration === null ? null : t.duration / 60, f.duMin, f.duMax)) return false;
  return true;
}

function rowPasses(m, f) {
  if (state.category !== "all" && m.match_type !== state.category) return false;
  const candidates = f.side === "A" ? [m.track_a] : f.side === "B" ? [m.track_b] : [m.track_a, m.track_b];
  return candidates.filter(Boolean).some((t) => trackPasses(t, f));
}

function sortValue(m, key) {
  const t = F.side.value === "B" ? (m.track_b || m.track_a) : (m.track_a || m.track_b);
  switch (key) {
    case "title": return (t.title || "").toLowerCase();
    case "artist": return (t.artist || "").toLowerCase();
    case "format": return t.format || "";
    case "bitrate": return t.bitrate ?? -1;
    case "size": return t.size ?? -1;
    case "duration": return t.duration ?? -1;
    default: return t.path.toLowerCase();
  }
}

function applyFilters(resetLimit = false) {
  const f = readFilters();
  const dir = F.dir.value === "desc" ? -1 : 1;
  state.filtered = state.matches
    .filter((m) => rowPasses(m, f))
    .sort((a, b) => {
      const va = sortValue(a, F.sort.value);
      const vb = sortValue(b, F.sort.value);
      return (va < vb ? -1 : va > vb ? 1 : 0) * dir;
    });
  if (resetLimit) state.limit = PAGE_SIZE;
  renderList();
}

Object.values(F).forEach((el) => {
  el.addEventListener(el.tagName === "SELECT" ? "change" : "input", () => applyFilters(true));
});

$("f-clear").addEventListener("click", () => {
  Object.values(F).forEach((el) => { if (el !== F.sort && el !== F.dir) el.value = ""; });
  F.side.value = "any";
  applyFilters(true);
});

/* ---------- lista e seleção ---------- */

function renderList() {
  const total = state.filtered.length;
  els.resultCount.textContent = `${total} item(ns) com os filtros atuais`;
  if (!total) {
    els.resultsList.innerHTML = `<li class="empty">Nenhum item com estes filtros.</li>`;
  } else {
    els.resultsList.innerHTML = state.filtered.slice(0, state.limit).map(rowHtml).join("");
  }
  els.showMore.hidden = total <= state.limit;
  updateSelectionUi();
}

function rowHtml(m) {
  const rows = [
    m.track_a ? { t: m.track_a, cls: "lib-a" } : null,
    m.track_b ? { t: m.track_b, cls: "lib-b" } : null,
  ].filter(Boolean).map(({ t, cls }) => `
      <div class="track-detail ${cls}">
        <span class="track-pc">PC ${esc(t.library)}</span>
        <span class="track-path">${esc(t.path)}</span>
        <span class="track-tech">${esc(techSummary(t))}</span>
      </div>`).join("");
  const compare = m.track_a && m.track_b ? `<button type="button" class="btn-secondary" data-compare="${m.id}">Comparar</button>` : "";
  return `
    <li class="result-item">
      <input type="checkbox" data-id="${m.id}" ${state.selected.has(m.id) ? "checked" : ""} />
      <div class="result-body">
        <div class="result-head">
          <div class="result-title">${esc(trackLabel(m))}<span class="kind" style="color: ${CATEGORY_COLORS[m.match_type]}">${esc(CATEGORY_LABELS[m.match_type])}</span></div>
          ${compare}
        </div>
        ${rows}
      </div>
    </li>`;
}

function updateSelectionUi() {
  const n = state.selected.size;
  els.selectionCount.textContent = n ? `${n} selecionado(s)` : "";
  document.querySelectorAll("[data-op]").forEach((b) => { b.disabled = n === 0; });
  const filteredIds = state.filtered.map((m) => m.id);
  els.selectAll.checked = filteredIds.length > 0 && filteredIds.every((id) => state.selected.has(id));
}

els.resultsList.addEventListener("change", (event) => {
  const box = event.target.closest("input[data-id]");
  if (!box) return;
  const id = Number(box.dataset.id);
  if (box.checked) state.selected.add(id); else state.selected.delete(id);
  updateSelectionUi();
});

els.resultsList.addEventListener("click", (event) => {
  const btn = event.target.closest("[data-compare]");
  if (btn) openCompare(Number(btn.dataset.compare));
});

els.selectAll.addEventListener("change", () => {
  state.filtered.forEach((m) => { if (els.selectAll.checked) state.selected.add(m.id); else state.selected.delete(m.id); });
  renderList();
});

els.showMore.addEventListener("click", () => { state.limit += PAGE_SIZE; renderList(); });

/* ---------- modal ---------- */

function openModal(html) {
  els.modalBox.innerHTML = html;
  els.modal.hidden = false;
}

function closeModal() {
  els.modal.hidden = true;
  els.modalBox.innerHTML = "";
}

els.modal.addEventListener("click", (event) => {
  if (event.target === els.modal && !els.modal.dataset.locked) closeModal();
});

const OPS = {
  "copy-ab": { type: "transfer", direction: "A_TO_B", title: "Copiar de A para B", verb: "Copiar" },
  "copy-ba": { type: "transfer", direction: "B_TO_A", title: "Copiar de B para A", verb: "Copiar" },
  "del-a": { type: "delete", sides: "A", title: "Apagar do lado A", verb: "Apagar" },
  "del-b": { type: "delete", sides: "B", title: "Apagar do lado B", verb: "Apagar" },
  "del-both": { type: "delete", sides: "both", title: "Apagar de ambos os lados", verb: "Apagar" },
};

document.querySelectorAll("[data-op]").forEach((btn) => {
  btn.addEventListener("click", () => {
    const op = OPS[btn.dataset.op];
    startOperation(op, [...state.selected]);
  });
});

function requestBody(op, ids) {
  const body = { type: op.type, match_ids: ids };
  if (op.direction) body.direction = op.direction;
  if (op.sides) body.sides = op.sides;
  return body;
}

async function startOperation(op, ids) {
  openModal(`<h2>${esc(op.title)}</h2><p class="muted">Calculando o plano...</p>`);
  let plan;
  try {
    plan = (await postJson(`/api/scans/${state.scanId}/operations/plan`, requestBody(op, ids))).items;
  } catch (err) {
    openModal(`<h2>${esc(op.title)}</h2><div class="warn-box">${esc(err.message)}</div><div class="modal-actions"><button class="btn-secondary" id="m-close">Fechar</button></div>`);
    $("m-close").addEventListener("click", closeModal);
    return;
  }
  renderPlan(op, ids, plan);
}

function renderPlan(op, ids, plan) {
  const runnable = plan.filter((i) => !i.skip_reason);
  const skipped = plan.filter((i) => i.skip_reason);
  const conflicts = runnable.filter((i) => i.conflict);
  const permanent = runnable.filter((i) => i.action === "delete" && i.permanent);
  const trash = runnable.filter((i) => i.action === "delete" && !i.permanent);

  let html = `<h2>${esc(op.title)}</h2>`;
  if (op.type === "delete") {
    if (permanent.length) {
      html += `<div class="warn-box"><strong>${permanent.length} arquivo(s) serão excluídos PERMANENTEMENTE</strong> (pasta de rede: o Windows não tem lixeira para compartilhamentos).${trash.length ? ` Outros ${trash.length} vão para a lixeira.` : ""}</div>`;
    } else {
      html += `<p class="muted">${trash.length} arquivo(s) serão enviados para a lixeira.</p>`;
    }
  } else {
    html += `<p class="muted">${runnable.length} arquivo(s) serão copiados, mantendo a subpasta relativa à raiz da biblioteca de destino. Cada cópia é verificada por hash.</p>`;
  }

  html += `<div class="plan-list">${runnable.map((i) => `<div>${esc(i.label)}<br>${esc(i.src_path)}${i.dest_path ? `<br>→ ${esc(i.dest_path)}` : ""}</div>`).join("") || "<div>Nada a executar.</div>"}</div>`;

  if (skipped.length) {
    html += `<p class="muted">${skipped.length} item(ns) serão ignorados: ${esc([...new Set(skipped.map((i) => i.skip_reason))].join("; "))}</p>`;
  }

  if (conflicts.length) {
    html += `<h2>${conflicts.length} conflito(s): o arquivo já existe no destino</h2>
      <div class="conflict-row"><span class="muted">Aplicar a todos</span>
        <select id="m-all"><option value="">Escolha...</option><option value="skip">Pular</option><option value="overwrite">Sobrescrever</option><option value="keep_both">Manter os dois</option></select></div>`;
    html += conflicts.map((i) => `
      <div class="conflict-row"><span>${esc(i.label)}<br><span class="muted">${esc(i.dest_path)} (${esc(formatBytes(i.conflict.size))})</span></span>
        <select data-key="${esc(i.key)}" class="m-res"><option value="">Escolha...</option><option value="skip">Pular</option><option value="overwrite">Sobrescrever</option><option value="keep_both">Manter os dois</option></select></div>`).join("");
  }

  const label = op.type === "delete" ? `Apagar ${runnable.length} arquivo(s)` : `Copiar ${runnable.length} arquivo(s)`;
  html += `<div class="modal-actions"><button class="btn-secondary" id="m-cancel">Cancelar</button>
    <button class="${op.type === "delete" ? "btn-danger" : "btn-secondary"}" id="m-confirm">${esc(label)}</button></div>`;
  openModal(html);

  const confirm = $("m-confirm");
  const selects = [...els.modalBox.querySelectorAll(".m-res")];
  const refresh = () => { confirm.disabled = runnable.length === 0 || selects.some((s) => !s.value); };
  refresh();
  selects.forEach((s) => s.addEventListener("change", refresh));
  const all = $("m-all");
  if (all) all.addEventListener("change", () => { if (all.value) { selects.forEach((s) => { s.value = all.value; }); refresh(); } });
  $("m-cancel").addEventListener("click", closeModal);
  confirm.addEventListener("click", () => {
    const resolutions = {};
    selects.forEach((s) => { resolutions[s.dataset.key] = s.value; });
    executeOperation(op, ids, resolutions);
  });
}

async function executeOperation(op, ids, resolutions) {
  els.modal.dataset.locked = "1";
  openModal(`<h2>${esc(op.title)}</h2><p id="m-progress">Executando...</p><div class="progress-track"><div id="m-fill" class="progress-fill"></div></div>`);
  let opId;
  try {
    opId = (await postJson(`/api/scans/${state.scanId}/operations`, { ...requestBody(op, ids), resolutions, confirm: true })).operation_id;
  } catch (err) {
    finishModal(op, null, err.message);
    return;
  }
  const tick = async () => {
    try {
      const data = await api(`/api/operations/${opId}`);
      const pct = data.total ? Math.round((data.done / data.total) * 100) : 100;
      const fill = $("m-fill");
      if (fill) fill.style.width = `${pct}%`;
      const label = $("m-progress");
      if (label) label.textContent = `${data.done} / ${data.total}`;
      if (data.status === "running") setTimeout(tick, 500);
      else finishModal(op, data, data.error_message);
    } catch (err) {
      finishModal(op, null, err.message);
    }
  };
  tick();
}

async function finishModal(op, data, error) {
  delete els.modal.dataset.locked;
  let html = `<h2>${esc(op.title)}: resultado</h2>`;
  if (error) html += `<div class="warn-box">${esc(error)}</div>`;
  if (data) {
    const c = data.counts || {};
    html += `<p>${c.ok || 0} concluído(s), ${c.skipped || 0} ignorado(s), ${c.failed || 0} com falha.</p>`;
    const problems = data.results.filter((r) => r.status !== "ok");
    if (problems.length) {
      html += `<div class="plan-list">${problems.map((r) => `<div>[${esc(r.status)}] ${esc(r.label)}<br>${esc(r.message)}</div>`).join("")}</div>`;
    }
  }
  html += `<div class="modal-actions"><button class="btn-secondary" id="m-close">Fechar</button></div>`;
  openModal(html);
  $("m-close").addEventListener("click", closeModal);
  state.selected.clear();
  try { await reloadMatches(); } catch (err) { /* a lista é recarregada na próxima análise */ }
}

/* ---------- comparação lado a lado (duplicatas) ---------- */

function openCompare(id) {
  const m = state.matches.find((x) => x.id === id);
  if (!m || !m.track_a || !m.track_b) return;
  const col = (t, name) => `
    <div class="compare-col">
      <h3>${name}</h3>
      <dl>
        <dt>Artista - título</dt><dd>${esc(t.artist || "?")} - ${esc(t.title || "?")}</dd>
        <dt>Álbum</dt><dd>${esc(t.album || "-")}</dd>
        <dt>Formato</dt><dd>${esc(t.format || "-")}</dd>
        <dt>Bitrate</dt><dd>${t.bitrate ? Math.round(t.bitrate / 1000) + " kbps" : "-"}</dd>
        <dt>Sample rate / bit depth</dt><dd>${t.sample_rate ? t.sample_rate + " Hz" : "-"} / ${t.bit_depth ? t.bit_depth + " bit" : "-"}</dd>
        <dt>Tamanho</dt><dd>${esc(formatBytes(t.size))}</dd>
        <dt>Duração</dt><dd>${esc(formatDuration(t.duration) || "-")}</dd>
        <dt>Caminho</dt><dd>${esc(t.path)}</dd>
      </dl>
    </div>`;
  openModal(`
    <h2>Comparar: ${esc(trackLabel(m))}</h2>
    <div class="compare-grid">${col(m.track_a, "PC A")}${col(m.track_b, "PC B")}</div>
    <div class="modal-actions">
      <button class="btn-secondary" id="c-close">Fechar</button>
      <button class="btn-danger" id="c-keep-a">Manter A (apagar B)</button>
      <button class="btn-danger" id="c-keep-b">Manter B (apagar A)</button>
    </div>`);
  $("c-close").addEventListener("click", closeModal);
  $("c-keep-a").addEventListener("click", () => startOperation({ type: "delete", sides: "B", title: "Manter A: apagar o arquivo de B" }, [id]));
  $("c-keep-b").addEventListener("click", () => startOperation({ type: "delete", sides: "A", title: "Manter B: apagar o arquivo de A" }, [id]));
}

els.analyzeBtn.addEventListener("click", startAnalysis);
