/*
Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\apps\indflow\static\dashboard.ui.js
Último recode: 2026-08-21 06:43 (America/Bahia)
Motivo: Migrar para a estrutura consolidada GESTFLOW + INDFLOW na branch DEV, preservando o conteúdo funcional validado.
*/

function fmt(n){
  const x = Number(n);
  if(!Number.isFinite(x)) return "0";
  return x.toLocaleString("pt-BR", { maximumFractionDigits: 2 });
}

function setText(id, txt){
  const el = document.getElementById(id);
  if(el) el.textContent = txt;
}

function setVisible(id, isVisible){
  const el = document.getElementById(id);
  if(el) el.style.display = isVisible ? "" : "none";
}

function resolveStatusUI(data){
  const ui = String((data && data.status_ui) || "").trim().toUpperCase();
  if(ui === "PRODUZINDO" || ui === "PARADA") return ui;
  const raw = String((data && data.status) || "").trim().toUpperCase();
  if(raw === "AUTO") return "PRODUZINDO";
  if(raw) return "PARADA";
  return "PARADA";
}

function resolveParadoMin(data){
  const v = Number(data && data.parado_min);
  if(Number.isFinite(v) && v >= 0) return Math.floor(v);
  return null;
}

const WIFI_OFFLINE_THRESHOLD_SEC = 45;

function resolveLastSeenMs(data){
  const candidates = [
    data && data.last_seen_ms,
    data && data.last_seen_ts,
    data && data.last_seen,
    data && data.device_last_seen,
    data && data.device_last_seen_iso
  ];

  for(const c of candidates){
    if(c === null || c === undefined) continue;
    if(typeof c === "number" && Number.isFinite(c)){
      return c > 0 && c < 1e12 ? Math.floor(c * 1000) : Math.floor(c);
    }
    if(typeof c === "string"){
      const t = Date.parse(c);
      if(Number.isFinite(t)) return t;
      const n = Number(c);
      if(Number.isFinite(n) && n > 0) return n < 1e12 ? Math.floor(n * 1000) : Math.floor(n);
    }
  }
  return null;
}

function resolveWifiState(data){
  const lastMs = resolveLastSeenMs(data);
  if(lastMs === null) return "SEM_DADOS";
  const diffSec = (Date.now() - lastMs) / 1000;
  if(!Number.isFinite(diffSec) || diffSec < 0) return "SEM_DADOS";
  return diffSec <= WIFI_OFFLINE_THRESHOLD_SEC ? "ONLINE" : "OFFLINE";
}

function applyWifiToCard(machineId, data){
  const sid = safeSid(machineId);
  const svg = document.getElementById(`wifi-svg-${sid}`);
  const xsvg = document.getElementById(`wifi-xsvg-${sid}`);
  if(!svg || !xsvg) return;
  const st = resolveWifiState(data);
  if(st === "ONLINE"){
    svg.style.color = "#2563eb";
    xsvg.style.display = "none";
  }else if(st === "OFFLINE"){
    svg.style.color = "#64748b";
    xsvg.style.display = "";
  }else{
    svg.style.color = "#94a3b8";
    xsvg.style.display = "none";
  }
}

function applyStatusToCard(machineId, data){
  const sid = safeSid(machineId);
  const badge = document.getElementById(`status-badge-${sid}`);
  const stopEl = document.getElementById(`stopline-${sid}`);
  const statusUI = resolveStatusUI(data);
  const produzindo = statusUI === "PRODUZINDO";

  if(badge){
    badge.textContent = statusUI;
    badge.className = `machine-status ${produzindo ? "status-auto" : "status-manual"}`;
  }

  if(stopEl){
    const mins = resolveParadoMin(data);
    if(!produzindo && mins !== null){
      stopEl.textContent = `${mins} min parados`;
      stopEl.style.display = "";
    }else{
      stopEl.textContent = "";
      stopEl.style.display = "none";
    }
  }

  applyWifiToCard(machineId, data);
}

function refugoTotal(data){
  if(Array.isArray(data && data.refugo_por_hora)){
    return data.refugo_por_hora.reduce((acc, item) => acc + (Number(item) || 0), 0);
  }
  return Number(data && (data.refugo_turno ?? data.refugo_total)) || 0;
}

function updateIndustrialOverview(rows){
  const valid = rows.filter(item => item && item.data);
  let running = 0;
  let stopped = 0;
  let offline = 0;
  let production = 0;
  let meta = 0;
  let scrap = 0;

  valid.forEach(({data}) => {
    if(resolveStatusUI(data) === "PRODUZINDO") running += 1;
    else stopped += 1;
    if(resolveWifiState(data) === "OFFLINE") offline += 1;
    production += Number(data.producao_turno) || 0;
    meta += Number(data.meta_turno) || 0;
    scrap += refugoTotal(data);
  });

  const monitored = getMachines().length;
  const attainment = meta > 0 ? Math.round((production / meta) * 100) : 0;
  setText("kpi-monitored", monitored);
  setText("kpi-running", running);
  setText("kpi-stopped", stopped);
  setText("kpi-offline", offline);
  setText("kpi-production", fmt(production));
  setText("kpi-production-detail", `meta ${fmt(meta)}`);
  setText("kpi-attainment", `${attainment}%`);
  setText("kpi-scrap-detail", `refugo ${fmt(scrap)}`);
}

function refreshStatuses(){
  const machines = getMachines();
  const jobs = machines.map(machineId =>
    fetch(`/machine/status?machine_id=${encodeURIComponent(machineId)}`)
      .then(r => r.ok ? r.json() : Promise.reject(new Error("status")))
      .then(data => {
        applyStatusToCard(machineId, data);
        return { machineId, data };
      })
      .catch(() => ({ machineId, data: null }))
  );

  Promise.all(jobs).then(updateIndustrialOverview).catch(() => {});
}

function ensurePager(){
  if(document.getElementById("pager")) return;
  const grid = document.getElementById("machineGrid");
  if(!grid || !grid.parentNode) return;

  const pager = document.createElement("div");
  pager.className = "pager";
  pager.id = "pager";

  const prev = document.createElement("button");
  prev.id = "btnPrev";
  prev.type = "button";
  prev.textContent = "←";
  prev.title = "Anterior";

  const next = document.createElement("button");
  next.id = "btnNext";
  next.type = "button";
  next.textContent = "→";
  next.title = "Próxima";

  pager.appendChild(prev);
  pager.appendChild(next);
  grid.parentNode.insertBefore(pager, grid.nextSibling);

  prev.addEventListener("click", () => {
    if(currentPage > 0){ currentPage--; renderMachines(); updateAll(); }
  });
  next.addEventListener("click", () => {
    if(currentPage < totalPages() - 1){ currentPage++; renderMachines(); updateAll(); }
  });
}

function renderPager(){
  ensurePager();
  const pager = document.getElementById("pager");
  const prev = document.getElementById("btnPrev");
  const next = document.getElementById("btnNext");
  if(!pager || !prev || !next) return;

  const tp = totalPages();
  clampCurrentPage();
  pager.style.display = tp <= 1 ? "none" : "flex";
  prev.disabled = currentPage === 0;
  next.disabled = currentPage >= tp - 1;
}

function cardHTML(machineId){
  const sid = safeSid(machineId);
  const upper = String(machineId).toUpperCase();

  return `
    <article class="machine-card" onclick="window.location.href='/producao/config/${encodeURIComponent(machineId)}'">
      <div class="machine-header">
        <div style="min-width:0;">
          <div class="machine-name">${upper}</div>
          <div class="machine-caption">Detalhe operacional</div>
        </div>
        <div id="status-badge-${sid}" class="machine-status status-manual">AGUARDANDO</div>
      </div>

      <div id="stopline-${sid}" class="machine-stopline" style="display:none"></div>

      <div class="percent-container">
        <div class="percent-block">
          <div class="percent-value" id="percent-turno-${sid}">0%</div>
          <div class="percent-label">Turno</div>
          <div class="stats-sub"><span id="lbl-meta-turno-u1-${sid}">Meta</span><b id="meta-turno-u1-${sid}">0</b></div>
          <div class="stats-sub"><span id="lbl-prod-turno-u1-${sid}">Produzido</span><b id="prod-turno-u1-${sid}">0</b></div>
          <div class="stats-sub" id="row-meta-turno-u2-${sid}"><span id="lbl-meta-turno-u2-${sid}">Meta</span><b id="meta-turno-u2-${sid}">0</b></div>
          <div class="stats-sub" id="row-prod-turno-u2-${sid}"><span id="lbl-prod-turno-u2-${sid}">Produzido</span><b id="prod-turno-u2-${sid}">0</b></div>
        </div>
        <div class="divider"></div>
        <div class="percent-block">
          <div class="percent-value" id="percent-hora-${sid}">0%</div>
          <div class="percent-label">Hora atual</div>
          <div class="stats-sub"><span id="lbl-meta-hora-u1-${sid}">Meta</span><b id="meta-hora-u1-${sid}">0</b></div>
          <div class="stats-sub"><span id="lbl-prod-hora-u1-${sid}">Produzido</span><b id="prod-hora-u1-${sid}">0</b></div>
          <div class="stats-sub" id="row-meta-hora-u2-${sid}"><span id="lbl-meta-hora-u2-${sid}">Meta</span><b id="meta-hora-u2-${sid}">0</b></div>
          <div class="stats-sub" id="row-prod-hora-u2-${sid}"><span id="lbl-prod-hora-u2-${sid}">Produzido</span><b id="prod-hora-u2-${sid}">0</b></div>
        </div>
      </div>

      <div id="wifi-wrap-${sid}" style="position:absolute;left:15px;bottom:14px;width:24px;height:20px;pointer-events:none;">
        <svg id="wifi-svg-${sid}" viewBox="0 0 64 48" style="width:24px;height:20px;color:#94a3b8;">
          <path d="M8 16 C24 2, 40 2, 56 16" fill="none" stroke="currentColor" stroke-width="6" stroke-linecap="round"/>
          <path d="M16 24 C28 14, 36 14, 48 24" fill="none" stroke="currentColor" stroke-width="6" stroke-linecap="round"/>
          <path d="M24 32 C30 27, 34 27, 40 32" fill="none" stroke="currentColor" stroke-width="6" stroke-linecap="round"/>
          <circle cx="32" cy="40" r="4.5" fill="currentColor"/>
        </svg>
        <svg id="wifi-xsvg-${sid}" viewBox="0 0 20 20" style="position:absolute;right:-2px;top:-2px;width:12px;height:12px;display:none;">
          <circle cx="10" cy="10" r="9" fill="#dc2626"/>
          <path d="M6 6 L14 14 M14 6 L6 14" stroke="#fff" stroke-width="2.4" stroke-linecap="round"/>
        </svg>
      </div>
      <div class="ritmo-medio" id="ritmo-medio-${sid}">Ritmo médio: —</div>
    </article>
  `;
}

function renderMachines(){
  const grid = document.getElementById("machineGrid");
  if(!grid) return;
  clampCurrentPage();
  const pageItems = getMachinesPage();
  grid.innerHTML = pageItems.length ? pageItems.map(cardHTML).join("") : `<div class="empty-state"><strong>Nenhuma máquina monitorada.</strong>A vinculação de equipamentos será controlada pelo GestFlow.</div>`;
  renderPager();
  refreshStatuses();
}

renderMachines();
setInterval(refreshStatuses, 2500);
