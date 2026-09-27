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

const state = {
  scanId: null,
  pollTimer: null,
  currentCategory: "all",
};

const els = {
  libraryA: document.getElementById("library-a"),
  libraryB: document.getElementById("library-b"),
  analyzeBtn: document.getElementById("analyze-btn"),
  formError: document.getElementById("form-error"),
  progressPanel: document.getElementById("progress-panel"),
  progressMessage: document.getElementById("progress-message"),
  progressFill: document.getElementById("progress-fill"),
  progressCount: document.getElementById("progress-count"),
  resultsPanel: document.getElementById("results-panel"),
  summaryRow: document.getElementById("summary-row"),
  tabs: document.getElementById("tabs"),
  resultsList: document.getElementById("results-list"),
  errorsBanner: document.getElementById("errors-banner"),
};

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

function trackLabel(trackA, trackB) {
  const track = trackA || trackB;
  if (!track) return "(sem informação)";
  const artist = track.artist || "Artista desconhecido";
  const title = track.title || "(sem título)";
  return `${artist} - ${title}`;
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
    const response = await fetch("/api/scans", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ library_a: libraryA, library_b: libraryB }),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || "Não foi possível iniciar a análise.");
    }
    state.scanId = data.scan_id;
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
      const response = await fetch(`/api/scans/${state.scanId}`);
      const data = await response.json();
      renderProgress(data);

      if (data.phase === "done") {
        els.analyzeBtn.disabled = false;
        showResults(data);
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
  const phaseLabels = {
    pending: "Preparando...",
    scanning_a: "Escaneando Biblioteca A...",
    scanning_b: "Escaneando Biblioteca B...",
    comparing: "Comparando bibliotecas...",
    done: "Análise concluída.",
    error: "Erro na análise.",
  };
  els.progressMessage.textContent = phaseLabels[data.phase] || data.message || "";
  els.progressFill.style.width = `${data.percent || 0}%`;
  els.progressCount.textContent = data.total ? `${data.current} / ${data.total} arquivos` : "";
}

function showResults(data) {
  els.resultsPanel.hidden = false;
  renderSummary(data.summary || {});
  renderTabs();

  if (data.errors && data.errors.length) {
    els.errorsBanner.hidden = false;
    els.errorsBanner.textContent = `${data.errors.length} arquivo(s) não puderam ser analisados e foram ignorados.`;
  } else {
    els.errorsBanner.hidden = true;
  }

  loadCategory("all");
}

function renderSummary(summary) {
  els.summaryRow.innerHTML = SUMMARY_ORDER.map(
    (key) => `
      <div class="summary-item" style="--item-color: ${CATEGORY_COLORS[key]}">
        <span class="summary-count">${summary[key] ?? 0}</span>
        <span class="summary-label">${CATEGORY_LABELS[key]}</span>
      </div>`
  ).join("");
}

function renderTabs() {
  els.tabs.innerHTML = TAB_ORDER.map(
    (cat) =>
      `<button class="tab ${cat === state.currentCategory ? "active" : ""}" data-category="${cat}">${CATEGORY_LABELS[cat]}</button>`
  ).join("");

  els.tabs.querySelectorAll(".tab").forEach((btn) => {
    btn.addEventListener("click", () => loadCategory(btn.dataset.category));
  });
}

async function loadCategory(category) {
  state.currentCategory = category;
  els.tabs.querySelectorAll(".tab").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.category === category);
  });

  const response = await fetch(`/api/scans/${state.scanId}/matches?category=${encodeURIComponent(category)}`);
  const data = await response.json();
  renderMatches(data.matches || []);
}

function renderMatches(matches) {
  if (!matches.length) {
    els.resultsList.innerHTML = `<li class="empty">Nenhum item nesta categoria.</li>`;
    return;
  }

  els.resultsList.innerHTML = matches
    .map((match) => {
      const rows = [
        match.track_a ? { track: match.track_a, libClass: "lib-a" } : null,
        match.track_b ? { track: match.track_b, libClass: "lib-b" } : null,
      ]
        .filter(Boolean)
        .map(
          ({ track, libClass }) => `
          <div class="track-detail ${libClass}">
            <span class="track-pc">PC ${track.library}</span>
            <span class="track-path">${track.path}</span>
            <span class="track-tech">${techSummary(track)}</span>
          </div>`
        )
        .join("");

      return `
        <li class="result-item">
          <div class="result-title">${trackLabel(match.track_a, match.track_b)}</div>
          ${rows}
        </li>`;
    })
    .join("");
}

els.analyzeBtn.addEventListener("click", startAnalysis);
