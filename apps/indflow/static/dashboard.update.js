/*
Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\apps\indflow\static\dashboard.update.js
Último recode: 2026-10-06 10:18 (America/Bahia)
Motivo: Exibir tempo de paradas abaixo da produção e status colorido de comunicação sem ícone de Wi-Fi.
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

function calcularIndicador(percentual){
  const p = Number(percentual) || 0;

  if(p >= 102){
    return { icon: "▲", color: "#16a34a" }; // verde
  }

  if(p <= 98){
    return { icon: "▼", color: "#dc2626" }; // vermelho
  }

  return { icon: "—", color: "#2563eb" }; // azul
}

function renderPercentWithIndicator(el, percentual, indicadorOverride){
  if(!el) return;

  const p = Number(percentual) || 0;
  const ind = indicadorOverride ? indicadorOverride : calcularIndicador(p);

  el.innerHTML = `
    <span style="display:inline-flex; align-items:baseline; gap:10px; white-space:nowrap;">
      <span style="font-size:26px; font-weight:900; line-height:1; color:${ind.color};">${ind.icon}</span>
      <span>${p}%</span>
    </span>
  `;
}

/* ===========================
   HORA: RITMO DENTRO DA HORA
   =========================== */

function getFracHoraAtual(){
  const now = new Date();
  const m = now.getMinutes();
  const s = now.getSeconds();
  const frac = (m * 60 + s) / 3600;
  return Math.min(1, Math.max(0, frac));
}

function indicadorPorRitmoDaHora(metaHora, produzidoHora){
  const meta = Number(metaHora) || 0;
  const prod = Number(produzidoHora) || 0;

  // Se não tem meta, não julga (normal)
  if(meta <= 0){
    return { icon: "—", color: "#2563eb" };
  }

  const frac = getFracHoraAtual();
  const esperadoAgora = meta * frac;

  // muito no começo da hora (ex: 1% da hora) evita ruído
  if(esperadoAgora <= 0.5){
    return { icon: "—", color: "#2563eb" };
  }

  const pctVsEsperado = (prod / esperadoAgora) * 100;
  return calcularIndicador(pctVsEsperado);
}

/* ===========================
   UPDATE
   =========================== */

const dashboardCardCache = new Map();

function fetchCardMetrics(machineId){
  const key = Math.floor(Date.now() / 3600000);
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
