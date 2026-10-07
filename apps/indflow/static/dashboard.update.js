/*
Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\apps\indflow\static\dashboard.update.js
Último recode: 2026-10-07 06:30:28 (America/Bahia)
Motivo: Repassar a programação atual para o status do card, preservando balizador, produção e tempos.
*/

// static/dashboard.update.js

/* ===========================
   UNIDADES / REGRAS
   =========================== */

function normUnidade(u){
  const v = (u || "").toString().trim().toLowerCase();
  return v ? v : null;
}

function labelUnidade(u){
  const v = normUnidade(u);
  if(!v) return "PCS";
  if(v === "pcs") return "PCS";
  if(v === "m") return "M";
  if(v === "m2") return "M²";
  return v.toUpperCase();
}

function pickValuesByUnit(u, data, scope){
  const unit = normUnidade(u) || "pcs";

  if(scope === "turno"){
    if(unit === "m"){
      return {
        meta: data.meta_turno_ml,
        prod: data.producao_turno_ml
      };
    }
    return {
      meta: data.meta_turno,
      prod: data.producao_turno
    };
  }

  if(unit === "m"){
    return {
      meta: data.meta_hora_ml,
      prod: data.producao_hora_ml
    };
  }

  return {
    meta: data.meta_hora_pcs,
    prod: data.producao_hora
  };
}

function formatTempoMedio(v){
  const n = Number(v);
  if (!Number.isFinite(n) || n <= 0) return "—";
  const fixed = n >= 10 ? n.toFixed(1) : n.toFixed(2);
  return fixed.replace(".", ",");
}

/* ===========================
   STATUS UI (PRODUZINDO / PARADA)
   =========================== */

function resolveStatusUI(data){
  const ui = (data?.status_ui || "").toString().trim().toUpperCase();
  if(ui === "PRODUZINDO" || ui === "PARADA") return ui;

  // fallback: backend antigo
  const raw = (data?.status || "").toString().trim().toUpperCase();
  if(raw === "AUTO") return "PRODUZINDO";
  if(raw) return "PARADA";
  return "PARADA";
}

function resolveParadoMin(data){
  const v = Number(data?.parado_min);
  if(Number.isFinite(v) && v >= 0) return Math.floor(v);
  return null;
}

/* ===========================
   INDICADOR VISUAL
   =========================== */

function renderGoalIndicator(sid, scope, metrics){
  const el = document.getElementById(`balizador-${scope}-${sid}`);
  if(!el) return;
  const goal = Number(metrics?.meta);
  const production = Number(metrics?.producao);
  const expected = Number(metrics?.meta_esperada);
  el.replaceChildren();
  el.style.color = "";
  el.title = "";
  if(!metrics || metrics.producao === null || metrics.producao === undefined ||
     metrics.meta_esperada === null || metrics.meta_esperada === undefined ||
     !Number.isFinite(goal) || goal <= 0 || !Number.isFinite(production) ||
     !Number.isFinite(expected) || production < 0 || expected < 0){
    el.textContent = "—";
    return;
  }
  let symbol = "=";
  let color = "#475569";
  let label = "Dentro da meta";
  if(production >= goal){
    symbol = "↑"; color = "#2563eb"; label = "Meta atingida";
  }else if(production < expected - 0.000001){
    symbol = "↓"; color = "#dc2626"; label = "Abaixo do esperado";
  }else if(production > expected + 0.000001){
    symbol = "↑"; color = "#16a34a"; label = "Acima do esperado";
  }
  const sign = document.createElement("span");
  sign.className = "card-balizador-sinal";
  sign.textContent = symbol;
  sign.setAttribute("aria-label", label);
  const percent = document.createElement("span");
  percent.textContent = `${fmt(production / goal * 100)}%`;
  el.style.color = color;
  el.title = `${label}. Produção: ${fmt(production)}. Esperado até este minuto: ${fmt(expected)}. Meta total: ${fmt(goal)}.`;
  el.append(sign, percent);
}

/* ===========================
   UPDATE
   =========================== */

const dashboardCardCache = new Map();

function fetchCardMetrics(machineId){
  const key = Math.floor(Date.now() / 60000);
  const cached = dashboardCardCache.get(machineId);
  if(cached && cached.key === key && Date.now() - cached.at < 5000) return Promise.resolve(cached.data);
  if(cached && cached.pending) return cached.pending;
  const entry = { key, at: 0, data: null };
  entry.pending = fetch(`/indicadores/api/card/${encodeURIComponent(machineId)}`, { cache: "no-store" })
    .then(r => r.ok ? r.json() : Promise.reject(new Error("card")))
    .then(payload => {
      if(!payload.ok) throw new Error("card");
      entry.data = payload.data;
      return entry.data;
    })
    .catch(() => null)
    .finally(() => { entry.at = Date.now(); entry.pending = null; });
  dashboardCardCache.set(machineId, entry);
  return entry.pending;
}


function formatStopDuration(value){
  if(value === null || value === undefined || value === "") return "—";
  const seconds = Number(value);
  if(!Number.isFinite(seconds) || seconds < 0) return "—";
  const total = Math.floor(seconds);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const rest = total % 60;
  return [hours, minutes, rest].map(v => String(v).padStart(2, "0")).join(":");
}

function renderCardPeriod(sid, scope, metrics, status){
  const u1 = normUnidade(status.unidade_1) || "pcs";
  const u2 = normUnidade(status.unidade_2);
  const conversion = Number(status.conv_m_por_pcs);
  const showU2 = !!u2 && u2 !== u1;
  [u1, u2].forEach((unit, index) => {
    const slot = index + 1;
    if(index === 1){
      setVisible(`row-meta-${scope}-u2-${sid}`, showU2);
      setVisible(`row-prod-${scope}-u2-${sid}`, showU2);
    }
    if(!unit) return;
    const convert = value => {
      if(value === null || value === undefined) return "—";
      if(unit === "m") return conversion > 0 ? fmt(Number(value) * conversion) : "—";
      return fmt(value);
    };
    setText(`lbl-meta-${scope}-u${slot}-${sid}`, `Meta (${labelUnidade(unit)})`);
    setText(`lbl-prod-${scope}-u${slot}-${sid}`, `Produção (${labelUnidade(unit)})`);
    setText(`meta-${scope}-u${slot}-${sid}`, convert(metrics?.meta));
    setText(`prod-${scope}-u${slot}-${sid}`, convert(metrics?.producao));
  });
  renderGoalIndicator(sid, scope, metrics);
  if(scope === "turno") setText(`period-turno-${sid}`, metrics?.label || "Turno");
  const oee = metrics?.oee;
  setText(`oee-${scope}-${sid}`, oee !== null && oee !== undefined && Number.isFinite(Number(oee)) ? `${fmt(Number(oee) * 100)}%` : "—");
  setText(`stops-${scope}-${sid}`, formatStopDuration(metrics?.tempo_parado_sec));
  const quality = document.getElementById(`quality-${scope}-${sid}`);
  if(quality){
    quality.replaceChildren();
    (metrics?.ocorrencias || []).forEach(item => {
      const row = document.createElement("div");
      row.className = "stats-sub";
      const label = document.createElement("span");
      const value = document.createElement("b");
      label.textContent = item.nome;
      value.textContent = fmt(item.quantidade);
      row.append(label, value);
      quality.appendChild(row);
    });
  }
}

function updateMachine(machineId){
  const sid = safeSid(machineId);
  if(!machineHasDevice(machineId)){
    const display = machineDisplayConfig(machineId);
    applyStatusToCard(machineId, display);
    renderCardPeriod(sid, "turno", null, display);
    renderCardPeriod(sid, "hora", null, display);
    setText(`gramatura-${sid}`, "");
    setVisible(`gramatura-${sid}`, false);
    setText(`ritmo-medio-${sid}`, "Ritmo médio: —");
    return Promise.resolve();
  }
  return Promise.all([
    fetch(`/machine/status?machine_id=${encodeURIComponent(machineId)}`).then(r => r.ok ? r.json() : Promise.reject(new Error("status"))),
    fetchCardMetrics(machineId)
  ]).then(([status, metrics]) => {
    if(!document.getElementById(`status-badge-${sid}`)) return;
    status.communication = metrics?.communication;
    status.schedule_status = metrics?.schedule_status;
    applyStatusToCard(machineId, status);
    const gram = String(metrics?.gramatura || "").trim();
    const gramLabel = gram && /^\d+(?:[.,]\d+)?$/.test(gram) ? `${gram} GR` : gram;
    setText(`gramatura-${sid}`, gramLabel);
    setVisible(`gramatura-${sid}`, !!gramLabel);
    renderCardPeriod(sid, "turno", metrics?.turno, status);
    renderCardPeriod(sid, "hora", metrics?.hora, status);
    const tempo = formatTempoMedio(status.tempo_medio_min_por_peca);
    setText(`ritmo-medio-${sid}`, tempo === "—" ? "Ritmo médio: —" : `Ritmo médio: ${tempo} min/peça`);
  }).catch(() => {
    const display = {...machineDisplayConfig(machineId), status_fetch_failed:true};
    applyStatusToCard(machineId, display);
    renderCardPeriod(sid, "turno", null, display);
    renderCardPeriod(sid, "hora", null, display);
    setText(`gramatura-${sid}`, "");
  });
}

function updateAll(){
  const pageItems = getMachinesPage();
  pageItems.forEach(updateMachine);
}

/* INIT */
updateAll();
setInterval(updateAll, 1000);
