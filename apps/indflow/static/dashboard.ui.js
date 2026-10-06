/*
Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\apps\indflow\static\dashboard.ui.js
Último recode: 2026-10-06 10:18 (America/Bahia)
Motivo: Exibir tempo de paradas abaixo da produção e status colorido de comunicação sem ícone de Wi-Fi.
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

const WIFI_OFFLINE_THRESHOLD_SEC = 60;

function resolveLastSeenMs(data){
  const candidates = [
    data && data.last_seen_ms,
    data && data._last_esp_ts_ms_seen,
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
  if(data?.status_fetch_failed) return "OFFLINE";
  const expires = Number(data?.communication?.expires_at_ms);
  if(data?.communication?.monitored && Number.isFinite(expires)){
    return Date.now() < expires ? "ONLINE" : "OFFLINE";
  }
  const lastMs = resolveLastSeenMs(data);
  if(lastMs === null) return "SEM_DADOS";
  const diffSec = (Date.now() - lastMs) / 1000;
  if(!Number.isFinite(diffSec) || diffSec < 0) return "SEM_DADOS";
  return diffSec <= WIFI_OFFLINE_THRESHOLD_SEC ? "ONLINE" : "OFFLINE";
}

function resolveCardStatusUI(machineId, data){
  if(!machineHasDevice(machineId)) return "SEM DISPOSITIVO";
  if(resolveWifiState(data) !== "ONLINE") return "OFFLINE";
  return resolveStatusUI(data);
}

function applyStatusToCard(machineId, data){
  const sid = safeSid(machineId);
  const showHour = data?.config_v2?.show_hour_tracking !== false;
  const card = document.getElementById(`machine-card-${sid}`);
  if(card) card.classList.toggle("machine-card-compact", !showHour);
  setVisible(`hour-block-${sid}`, showHour);
  setVisible(`hour-divider-${sid}`, showHour);
  const percentContainer = document.getElementById(`percent-container-${sid}`);
  if(percentContainer) percentContainer.style.gridTemplateColumns = showHour ? "" : "minmax(0,1fr)";
  const badge = document.getElementById(`status-badge-${sid}`);
  const stopEl = document.getElementById(`stopline-${sid}`);
  const statusUI = resolveCardStatusUI(machineId, data);
  const produzindo = statusUI === "PRODUZINDO";

  if(badge){
    badge.textContent = statusUI;
    const classes = {"PRODUZINDO":"status-auto", "PARADA":"status-manual", "OFFLINE":"status-offline", "SEM DISPOSITIVO":"status-unlinked"};
    badge.className = `machine-status ${classes[statusUI]}`;
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

  queueDashboardLayout();
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

  valid.forEach(({machineId, data}) => {
    const status = resolveCardStatusUI(machineId, data);
    if(status === "PRODUZINDO") running += 1;
    else if(status === "PARADA") stopped += 1;
    else if(status === "OFFLINE") offline += 1;
    production += Number(data.producao_turno) || 0;
    meta += Number(data.meta_turno) || 0;
    scrap += refugoTotal(data);
  });

  const monitored = getMachines().filter(machineHasDevice).length;
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
  machines.filter(id => !machineHasDevice(id)).forEach(id => applyStatusToCard(id, machineDisplayConfig(id)));
  const jobs = machines.filter(machineHasDevice).map(machineId =>
    fetch(`/machine/status?machine_id=${encodeURIComponent(machineId)}`)
      .then(r => r.ok ? r.json() : Promise.reject(new Error("status")))
      .then(async data => {
        const metrics = await fetchCardMetrics(machineId);
        data.communication = metrics?.communication;
        applyStatusToCard(machineId, data);
        return { machineId, data };
      })
      .catch(() => {
        const data = {...machineDisplayConfig(machineId), status_fetch_failed:true};
        applyStatusToCard(machineId, data);
        return {machineId, data};
      })
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
    if(currentPage > 0) changeDashboardPage(-1);
  });
  next.addEventListener("click", () => {
    if(currentPage < totalPages() - 1) changeDashboardPage(1);
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
  setText("dashboardPage", `Página ${currentPage + 1} de ${tp}`);
  restartDashboardRotation();
}

function cardHTML(machineId){
  const sid = safeSid(machineId);
  const upper = String(machineId).toUpperCase();

  return `
    <article id="machine-card-${sid}" class="machine-card${machineDisplayConfig(machineId)?.config_v2?.show_hour_tracking === false ? ' machine-card-compact' : ''}" onclick="window.location.href='/producao/config/${encodeURIComponent(machineId)}'">
      <div class="machine-card-body">
      <div class="machine-header">
        <div style="min-width:0;">
          <div class="machine-caption">Máquina</div>
          <div class="machine-name">${upper}</div>
          <div class="machine-gramatura" id="gramatura-${sid}"></div>
        </div>
        <div id="status-badge-${sid}" class="machine-status status-manual">AGUARDANDO</div>
      </div>

      <div class="percent-container" id="percent-container-${sid}">
        <div class="percent-block">
          <div class="percent-label" id="period-turno-${sid}">Turno</div>
          <div class="stats-sub"><span id="lbl-meta-turno-u1-${sid}">Meta</span><b id="meta-turno-u1-${sid}">0</b></div>
          <div class="stats-sub"><span id="lbl-prod-turno-u1-${sid}">Produzido</span><b id="prod-turno-u1-${sid}">0</b></div>
          <div class="stats-sub" id="row-meta-turno-u2-${sid}"><span id="lbl-meta-turno-u2-${sid}">Meta</span><b id="meta-turno-u2-${sid}">0</b></div>
          <div class="stats-sub" id="row-prod-turno-u2-${sid}"><span id="lbl-prod-turno-u2-${sid}">Produzido</span><b id="prod-turno-u2-${sid}">0</b></div>
          <div class="stats-sub"><span>Paradas</span><b id="stops-turno-${sid}">—</b></div>
          <div class="stats-sub card-oee"><span>OEE</span><b id="oee-turno-${sid}">—</b></div>
          <div id="quality-turno-${sid}"></div>
        </div>
        <div class="divider" id="hour-divider-${sid}"></div>
        <div class="percent-block" id="hour-block-${sid}">
          <div class="percent-label">Hora atual</div>
          <div class="stats-sub"><span id="lbl-meta-hora-u1-${sid}">Meta</span><b id="meta-hora-u1-${sid}">0</b></div>
          <div class="stats-sub"><span id="lbl-prod-hora-u1-${sid}">Produzido</span><b id="prod-hora-u1-${sid}">0</b></div>
          <div class="stats-sub" id="row-meta-hora-u2-${sid}"><span id="lbl-meta-hora-u2-${sid}">Meta</span><b id="meta-hora-u2-${sid}">0</b></div>
          <div class="stats-sub" id="row-prod-hora-u2-${sid}"><span id="lbl-prod-hora-u2-${sid}">Produzido</span><b id="prod-hora-u2-${sid}">0</b></div>
          <div class="stats-sub"><span>Paradas</span><b id="stops-hora-${sid}">—</b></div>
          <div class="stats-sub card-oee"><span>OEE</span><b id="oee-hora-${sid}">—</b></div>
          <div id="quality-hora-${sid}"></div>
        </div>
      </div>

      <div class="ritmo-medio" id="ritmo-medio-${sid}">Ritmo médio: —</div>
      </div>
    </article>
  `;
}

function renderMachines(){
  const grid = document.getElementById("machineGrid");
  if(!grid) return;
  clampCurrentPage();
  const pageItems = getMachinesPage();
  grid.innerHTML = pageItems.length ? pageItems.map(cardHTML).join("") : `<div class="empty-state"><strong>Nenhuma máquina cadastrada.</strong></div>`;
  renderPager();
  refreshStatuses();
  queueDashboardLayout();
}

let dashboardLayoutPending = false;
let dashboardRotationTimer = null;
let dashboardMeasuredHeight = 0;
let dashboardMeasuredWidth = 0;

function queueDashboardLayout(){
  if(dashboardLayoutPending) return;
  dashboardLayoutPending = true;
  requestAnimationFrame(() => {
    dashboardLayoutPending = false;
    fitDashboardCards();
  });
}

function fitDashboardCards(){
  const grid = document.getElementById("machineGrid");
  if(!grid) return;
  const cards = Array.from(grid.querySelectorAll(".machine-card"));
  if(!cards.length) return;
  const gap = 8;
  const width = grid.clientWidth;
  const hasHour = getMachines().some(id => machineDisplayConfig(id)?.config_v2?.show_hour_tracking !== false);
  const columns = Math.max(1, Math.min(5, Math.floor((width + gap) / ((hasHour ? 300 : 205) + gap))));
  const cellWidth = (width - gap * (columns - 1)) / columns;
  grid.style.gridTemplateColumns = `repeat(${columns}, minmax(0, 1fr))`;
  const measurements = cards.map(card => {
    const body = card.querySelector(".machine-card-body");
    const baseWidth = card.classList.contains("machine-card-compact") ? 225 : 380;
    const widthScale = Math.min(1, (cellWidth - 2) / baseWidth);
    body.style.width = `${(cellWidth - 2) / widthScale}px`;
    return {card, body, widthScale, height: body.offsetHeight};
  });
  if(Math.abs(width - dashboardMeasuredWidth) > 1){
    dashboardMeasuredWidth = width;
    dashboardMeasuredHeight = 0;
  }
  dashboardMeasuredHeight = Math.max(dashboardMeasuredHeight, ...measurements.map(item => item.height * item.widthScale));
  const naturalHeight = dashboardMeasuredHeight;
  const gridTop = grid.getBoundingClientRect().top;
  const maxCapacity = Math.min(10, columns * 2);
  let available = Math.max(100, window.innerHeight - gridTop - (getMachines().length > maxCapacity ? 48 : 24));
  const wantedRows = Math.min(2, Math.ceil(Math.min(10, getMachines().length) / columns));
  const rows = wantedRows > 1 && available >= naturalHeight * 0.74 * 2 + gap ? 2 : 1;
  const capacity = Math.min(10, columns * rows);
  if(capacity !== PAGE_SIZE){
    const firstIndex = currentPage * PAGE_SIZE;
    PAGE_SIZE = capacity;
    currentPage = Math.floor(firstIndex / PAGE_SIZE);
    renderMachines();
    updateAll();
    return;
  }
  available = Math.max(100, window.innerHeight - gridTop - (getMachines().length > capacity ? 48 : 24));
  const rowHeight = Math.min(naturalHeight, (available - gap * (rows - 1)) / rows);
  grid.style.gridTemplateRows = `repeat(${rows}, ${rowHeight}px)`;
  measurements.forEach(({card, body, widthScale, height}) => {
    const scale = Math.min(widthScale, (rowHeight - 2) / height);
    body.style.width = `${(cellWidth - 2) / scale}px`;
    body.style.transform = `scale(${scale})`;
    card.style.height = `${rowHeight}px`;
  });
}

function changeDashboardPage(delta){
  const pages = totalPages();
  currentPage = (currentPage + delta + pages) % pages;
  renderMachines();
  updateAll();
}

function restartDashboardRotation(){
  if(dashboardRotationTimer !== null) clearInterval(dashboardRotationTimer);
  dashboardRotationTimer = null;
  const enabled = document.getElementById("dashboardAutoRotate");
  const interval = document.getElementById("dashboardRotationSeconds");
  const seconds = Number(interval?.value);
  if(!enabled?.checked || !Number.isInteger(seconds) || seconds < 5 || seconds > 3600 || totalPages() <= 1) return;
  dashboardRotationTimer = setInterval(() => {
    if(!document.hidden) changeDashboardPage(1);
  }, seconds * 1000);
}

function initDashboardDisplay(){
  const root = document.getElementById("dashboardDisplay");
  const button = document.getElementById("dashboardFullscreen");
  const interval = document.getElementById("dashboardRotationSeconds");
  const enabled = document.getElementById("dashboardAutoRotate");
  if(!root || !button) return;
  button.addEventListener("click", async () => {
    try{
      if(document.fullscreenElement === root) await document.exitFullscreen();
      else await root.requestFullscreen();
    }catch(error){
      window.alert("Não foi possível abrir a tela inteira neste navegador.");
    }
  });
  document.addEventListener("fullscreenchange", () => {
    button.textContent = document.fullscreenElement === root ? "Sair da tela inteira" : "Tela inteira";
    queueDashboardLayout();
  });
  window.addEventListener("resize", queueDashboardLayout);
  interval?.addEventListener("change", () => {
    if(!interval.checkValidity()){ interval.reportValidity(); return; }
    restartDashboardRotation();
  });
  enabled?.addEventListener("change", restartDashboardRotation);
  if(typeof ResizeObserver !== "undefined"){
    new ResizeObserver(queueDashboardLayout).observe(root);
  }
  queueDashboardLayout();
}

initDashboardDisplay();
renderMachines();
setInterval(refreshStatuses, 2500);
