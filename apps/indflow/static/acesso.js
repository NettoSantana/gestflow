// Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\apps\indflow\static\acesso.js
// Último recode: 2026-10-26 10:37:41 (America/Bahia)
// Motivo: Recuperar e acompanhar solicitações pendentes e permitir cancelamento pelo painel.
(() => {
  'use strict';
  const root = document.getElementById('accessModule'); if (!root) return;
  const csrf = root.dataset.csrf;
  const feedback = document.getElementById('accessFeedback');
  const dialog = document.getElementById('accessDialog');
  const info = document.getElementById('accessDialogInfo');
  const readerSelect = document.getElementById('accessSelectedReader');
  const startBtn = document.getElementById('accessDialogStart');
  let trackingExisting = false;
  let selectedPerson = null, selectedMode = 'capture', activeCmd = null, polling = null;
  function show(message, kind='') { feedback.hidden = false; feedback.className = 'access-feedback ' + kind; feedback.textContent = message; }
  function explain(message, kind='') { info.className='access-dialog-info ' + kind; info.textContent=message; }
  async function api(url, data, method='POST') {
    const options = {method,credentials:'same-origin',headers:{'Accept':'application/json'}};
    if (method !== 'GET') {options.headers['Content-Type']='application/json';options.headers['X-CSRF-Token']=csrf;options.body=JSON.stringify(data||{});}
    let response=await fetch(url,options), result=await response.json();
    if (!response.ok || !result.ok) throw new Error(result.error || 'Não foi possível concluir a solicitação.');
    return result;
  }
  async function submitForm(id, endpoint) {
    const form=document.getElementById(id); if (!form) return;
    form.addEventListener('submit',async e=>{
      e.preventDefault(); const btn=form.querySelector('button[type=submit]');btn.disabled=true;
      try {
        const result=await api(endpoint,Object.fromEntries(new FormData(form)));
        if (result.token) {document.getElementById('accessDeviceToken').value=result.token;document.getElementById('accessTokenBox').hidden=false;}
        else {form.reset();setTimeout(()=>location.reload(),800);}
        show(result.mensagem||'Cadastro realizado.','success');
      } catch(err) {show(err.message,'error');} finally{btn.disabled=false;}
    });
  }
  submitForm('accessPersonForm','/acesso/api/funcionarios');
  submitForm('accessReaderForm','/acesso/api/leitores');
  document.getElementById('accessCopyToken')?.addEventListener('click',()=>{
    const field=document.getElementById('accessDeviceToken');field.select();navigator.clipboard?.writeText(field.value).catch(()=>{});
  });
  function stopPolling(){if(polling){clearInterval(polling);polling=null;}}
  async function cancel(){
    if(trackingExisting){stopPolling();activeCmd=null;trackingExisting=false;if(dialog.open)dialog.close();return;}
    const cmd=activeCmd;
    if(cmd){
      try{await api(`/acesso/api/comandos/${encodeURIComponent(cmd)}/cancelar`,{});}
      catch(err){explain('Não foi possível cancelar: '+err.message,'error');return;}
    }
    stopPolling();activeCmd=null;if(dialog.open)dialog.close();
  }
  document.querySelectorAll('[data-pending]').forEach(button=>button.addEventListener('click',()=>{
    stopPolling();trackingExisting=true;activeCmd=button.dataset.pending;selectedMode=button.dataset.mode;
    document.getElementById('accessDialogTitle').textContent='Acompanhar solicitação';
    document.getElementById('accessDialogName').textContent=button.dataset.name;
    readerSelect.value=button.dataset.reader;readerSelect.disabled=true;
    document.getElementById('accessPermissionRow').hidden=true;
    startBtn.hidden=true;document.getElementById('accessDialogCancel').textContent='Fechar';
    explain('Consultando solicitação pendente...');dialog.showModal();polling=setInterval(check,1200);check();
  }));
  document.querySelectorAll('[data-cancel-pending]').forEach(button=>button.addEventListener('click',async()=>{
    if(!window.confirm('Cancelar esta solicitação no servidor? Isso não desfaz alterações já executadas no ESP32.'))return;
    button.disabled=true;
    try{await api(`/acesso/api/comandos/${encodeURIComponent(button.dataset.cancelPending)}/cancelar`,{});location.reload();}
    catch(err){button.disabled=false;show(err.message,'error');}
  }));
  root.querySelectorAll('time[datetime]').forEach(el=>{const date=new Date(el.dateTime);if(!Number.isNaN(date.getTime()))el.textContent=date.toLocaleString('pt-BR',{timeZone:'America/Bahia'})+' (Bahia)';});
  async function check(){
    if(!activeCmd)return;
    const current=activeCmd;
    try{
      const state=await api(`/acesso/api/comandos/${encodeURIComponent(current)}`,null,'GET');
      if(current!==activeCmd)return;
      if(state.estado==='confirmado'){
        stopPolling();activeCmd=null;startBtn.disabled=true;
        explain(selectedMode==='capture'?`Funcionário cadastrado com sucesso! Crachá: ${state.cracha_uid||'confirmado pelo ESP32'}`:'Permissão confirmada pelo ESP32.','success');
        show('Confirmação recebida do dispositivo.','success');setTimeout(()=>location.reload(),1600);
      } else if(['expirado','falhou','cancelado'].includes(state.estado)){
        stopPolling();activeCmd=null;startBtn.disabled=false;explain(state.erro||'Solicitação não concluída. Tente novamente.','error');
      } else if(state.estado==='aguardando_confirmacao'){
        explain('Crachá lido. Aguardando o ESP32 confirmar a gravação na memória local.');
      } else if(state.estado==='pendente_dispositivo'){
        explain('Solicitação enviada. Aguardando o ESP32 executar e confirmar a permissão.');
      }
    }catch(e){explain(e.message,'error');}
  }
  document.querySelectorAll('[data-action="capture"],[data-action="permission"]').forEach(button=>button.addEventListener('click',()=>{
    stopPolling();activeCmd=null;trackingExisting=false;readerSelect.disabled=false;startBtn.hidden=false;document.getElementById('accessDialogCancel').textContent='Cancelar';selectedPerson=button.dataset.person;
    selectedMode=button.dataset.action;
    document.getElementById('accessDialogTitle').textContent=selectedMode==='capture'?'Vincular crachá':'Permissão por máquina';
    document.getElementById('accessDialogName').textContent=button.dataset.name;
    document.getElementById('accessPermissionRow').hidden=(selectedMode==='capture');
    startBtn.textContent=selectedMode==='capture'?'Iniciar leitura':'Enviar solicitação';
    startBtn.disabled=false;explain(selectedMode==='capture'?'Selecione o leitor. A próxima leitura válida será destinada a este funcionário.':'Escolha o leitor da máquina e confirme a autorização.');
    dialog.showModal();
  }));
  startBtn?.addEventListener('click',async()=>{
    const reader=readerSelect.value;if(!reader){explain('Selecione o leitor da máquina.','error');return;}
    startBtn.disabled=true;
    try {
      let result;
      if(selectedMode==='capture') result=await api('/acesso/api/capturas',{funcionario_id:selectedPerson,leitor_id:reader});
      else result=await api('/acesso/api/permissoes',{funcionario_id:selectedPerson,leitor_id:reader,acao:document.getElementById('accessPermissionAction').value});
      activeCmd=result.comando_id;explain(result.mensagem||'Aguardando dispositivo...');
      polling=setInterval(check,1200);check();
    }catch(err){startBtn.disabled=false;explain(err.message,'error');}
  });
  document.getElementById('accessDialogCancel')?.addEventListener('click',cancel);
  document.getElementById('accessDialogClose')?.addEventListener('click',cancel);
  dialog?.addEventListener('cancel',e=>{e.preventDefault();cancel();});
})();
