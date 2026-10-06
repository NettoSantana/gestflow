/*
Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\apps\indflow\static\dashboard.state.js
Último recode: 2026-10-06 09:43 (America/Bahia)
Motivo: Ajustar até dez máquinas ao espaço da tela, adicionar tela inteira e troca automática de páginas por intervalo.
*/

// static/dashboard.state.js
// ===========================
// ESTADO + PAGINAÇÃO
// (CÓPIA DO dashboard.js — PASSO 1)
// ===========================

let tenantMachines = [];
let linkedMachines = new Set();
let machineDisplay = {};

function machineDisplayConfig(machineId){
  return machineDisplay[normalizeId(machineId)] || {};
}

function machineHasDevice(machineId){
  return linkedMachines.has(normalizeId(machineId));
}

/* PAGINAÇÃO */
let PAGE_SIZE = 10;
let currentPage = 0;

/* ===========================
   ESTADO / MÁQUINAS
   =========================== */

function getMachines(){
  return tenantMachines.slice();
}

function setMachines(arr){
  const next = [];
  const seen = new Set();

  (Array.isArray(arr) ? arr : []).forEach(item => {
    const id = normalizeId(item);
    if(!id || seen.has(id)) return;
    seen.add(id);
    next.push(id);
  });

  tenantMachines = next;
}

function loadTenantMachines(){
  return fetch("/devices/machines", {
    method: "GET",
    credentials: "same-origin",
    headers: { "Accept": "application/json" }
  })
    .then(response => {
      if(!response.ok) throw new Error("Falha ao carregar máquinas do tenant");
      return response.json();
    })
    .then(data => {
      setMachines(Array.isArray(data && data.machines) ? data.machines : []);
      linkedMachines = new Set((Array.isArray(data.linked_machines) ? data.linked_machines : data.machines || []).map(normalizeId));
      machineDisplay = data.machine_display && typeof data.machine_display === "object" ? data.machine_display : {};
      currentPage = 0;

      if(typeof renderMachines === "function") renderMachines();
      if(typeof updateAll === "function") updateAll();

      return getMachines();
    })
    .catch(() => {
      setMachines([]);
      linkedMachines.clear();
      machineDisplay = {};
      currentPage = 0;

      if(typeof renderMachines === "function") renderMachines();
      if(typeof updateAll === "function") updateAll();

      return [];
    });
}

function normalizeId(s){
  let v = (s || "").trim().toLowerCase();
  v = v.replace(/\s+/g, "_");
  v = v.replace(/[^a-z0-9_\-]/g, "");
  return v;
}

function nextMachineId(machines){
  let maxN = 1;
  machines.forEach(id => {
    const m = String(id).match(/^maquina(\d+)$/);
    if(m){
      const n = parseInt(m[1], 10);
      if(Number.isFinite(n) && n > maxN) maxN = n;
    }
  });
  const next = maxN + 1;
  return "maquina" + String(next).padStart(2, "0");
}

function safeSid(machineId){
  return String(machineId).replace(/[^a-z0-9_\-]/g, "");
}

/* ===========================
   PAGINAÇÃO
   =========================== */

function totalPages(){
  const total = getMachines().length;
  return Math.max(1, Math.ceil(total / PAGE_SIZE));
}

function clampCurrentPage(){
  const tp = totalPages();
  if(currentPage < 0) currentPage = 0;
  if(currentPage > tp - 1) currentPage = tp - 1;
}

function getMachinesPage(){
  const machines = getMachines();
  const start = currentPage * PAGE_SIZE;
  return machines.slice(start, start + PAGE_SIZE);
}

function ensurePager(){
  if(document.getElementById("pager")) return;

  const wrapper = document.querySelector(".dashboard-wrapper") || document.body;
  const grid = document.getElementById("machineGrid");

  const pager = document.createElement("div");
  pager.className = "pager";
  pager.id = "pager";
  pager.style.display = "none";

  const btnPrev = document.createElement("button");
  btnPrev.id = "btnPrev";
  btnPrev.type = "button";
  btnPrev.textContent = "←";
  btnPrev.title = "Anterior";

  const btnNext = document.createElement("button");
  btnNext.id = "btnNext";
  btnNext.type = "button";
  btnNext.textContent = "→";
  btnNext.title = "Próxima";

  pager.appendChild(btnPrev);
  pager.appendChild(btnNext);

  if(grid && grid.parentNode){
    grid.parentNode.insertBefore(pager, grid.nextSibling);
  }else{
    wrapper.appendChild(pager);
  }

  btnPrev.addEventListener("click", () => {
    if(currentPage > 0){
      changeDashboardPage(-1);
    }
  });

  btnNext.addEventListener("click", () => {
    const tp = totalPages();
    if(currentPage < tp - 1){
      changeDashboardPage(1);
    }
  });
}

function renderPager(){
  ensurePager();

  const pager = document.getElementById("pager");
  const btnPrev = document.getElementById("btnPrev");
  const btnNext = document.getElementById("btnNext");

  if(!pager || !btnPrev || !btnNext) return;

  const tp = totalPages();
  clampCurrentPage();

  if(tp <= 1){
    pager.style.display = "none";
    return;
  }

  pager.style.display = "flex";

  btnPrev.disabled = currentPage === 0;
  btnNext.disabled = currentPage >= tp - 1;
}

/* ===========================
   EXCLUSÃO DE MÁQUINA
   =========================== */

function removeMachine(machineId){
  const id = String(machineId || "").trim().toUpperCase();
  window.alert(
    `Gerencie a máquina ${id || "selecionada"} em Máquinas e dispositivos.`
  );
}

loadTenantMachines();
