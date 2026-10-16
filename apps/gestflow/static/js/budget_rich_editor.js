/* Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\apps\gestflow\static\js\budget_rich_editor.js
Último recode: 2026-10-16 14:32 (America/Bahia)
Motivo: Editar e colar escopos com títulos, negrito e listas, mantendo o campo original do formulário. */
(function () {
    'use strict';
    const marker = '<!--GESTFLOW_SCOPE_V1-->';
    const allowed = new Set(['P','DIV','BR','H1','H2','H3','STRONG','B','EM','I','U','UL','OL','LI','BLOCKQUOTE']);
    const blocked = new Set(['SCRIPT','STYLE','IFRAME','OBJECT','EMBED','SVG','MATH','TEMPLATE','NOSCRIPT','HEAD']);
    const escape = s => s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    function plainHtml(text) {
        let list = '', output = '';
        String(text || '').replace(/\r\n?/g,'\n').split('\n').forEach(line => {
            const heading = line.match(/^\s*(#{1,6})\s+(.+)$/);
            const item = line.match(/^\s*([-*+•]|\d+[.)])\s+(.+)$/);
            const type = item ? (/^\d/.test(item[1]) ? 'ol' : 'ul') : '';
            if (list && type !== list) {output += '</'+list+'>'; list = '';}
            const inline = value => escape(value).replace(/\*\*([^*\n]+)\*\*/g,'<strong>$1</strong>');
            if (item) {
                if (!list) {
                    const start = type === 'ol' ? ' start="'+parseInt(item[1],10)+'"' : '';
                    output += '<'+type+start+'>'; list = type;
                }
                output += '<li>'+inline(item[2])+'</li>';
            } else if (heading) {
                const level = Math.min(heading[1].length,3);
                output += '<h'+level+'>'+inline(heading[2])+'</h'+level+'>';
            } else {output += '<p>'+(line.trim() ? inline(line) : '<br>')+'</p>';}
        });
        return output+(list ? '</'+list+'>' : '');
    }
    function cleanHtml(value) {
        const parsed = new DOMParser().parseFromString(value,'text/html');
        const result = document.createElement('div');
        function copy(node, parent) {
            if (node.nodeType === Node.TEXT_NODE) {parent.appendChild(document.createTextNode(node.textContent)); return;}
            if (node.nodeType !== Node.ELEMENT_NODE || blocked.has(node.tagName)) return;
            let tag = node.tagName;
            if (tag === 'SPAN') {
                if (node.style.fontWeight === 'bold' || Number(node.style.fontWeight) >= 600) tag = 'STRONG';
                else if (node.style.fontStyle === 'italic') tag = 'EM';
                else if (node.style.textDecoration.includes('underline')) tag = 'U';
            }
            const target = allowed.has(tag) ? document.createElement(tag.toLowerCase()) : parent;
            if (target !== parent) {
                if (tag === 'OL' && /^\d{1,5}$/.test(node.getAttribute('start') || '')) target.setAttribute('start',node.getAttribute('start'));
                parent.appendChild(target);
            }
            Array.from(node.childNodes).forEach(child => copy(child,target));
        }
        Array.from(parsed.body.childNodes).forEach(node => copy(node,result));
        return result.innerHTML;
    }
    function attach(textarea) {
        if (textarea.dataset.richReady) return;
        textarea.dataset.richReady = '1';
        const shell = document.createElement('div'); shell.className = 'budget-rich-shell';
        const toolbar = document.createElement('div'); toolbar.className = 'budget-rich-toolbar'; toolbar.setAttribute('role','toolbar'); toolbar.setAttribute('aria-label','Formatação do escopo');
        const editor = document.createElement('div'); editor.className = 'budget-rich-area'; editor.contentEditable = 'true'; editor.id = textarea.id+'-editor';
        editor.setAttribute('role','textbox'); editor.setAttribute('aria-multiline','true');
        editor.setAttribute('aria-label',textarea.id === 'gerador_observacoes_cliente' ? 'Observações adicionais para o cliente' : 'Escopo e observações para o cliente');
        editor.dataset.placeholder = textarea.placeholder || 'Digite ou cole o escopo. Use os botões para formatar.';
        textarea.scopeEditor = editor;
        let lastValue = '', savedRange = null;
        function load() {
            const value = textarea.value.replace(/^\s*Escopo:\s*(?=<!--GESTFLOW_SCOPE_V1-->)/i,'');
            editor.innerHTML = value.startsWith(marker) ? cleanHtml(value.slice(marker.length)) : plainHtml(value);
            lastValue = textarea.value;
        }
        function sync() {
            textarea.value = editor.textContent.trim() ? marker+cleanHtml(editor.innerHTML) : '';
            lastValue = textarea.value;
        }
        function remember() {
            const selection = window.getSelection();
            if (selection.rangeCount && editor.contains(selection.anchorNode) && editor.contains(selection.focusNode)) savedRange = selection.getRangeAt(0).cloneRange();
        }
        function restore() {
            editor.focus();
            if (savedRange && editor.contains(savedRange.commonAncestorContainer)) {
                const selection = window.getSelection(); selection.removeAllRanges(); selection.addRange(savedRange);
            }
        }
        function command(name, value) {restore(); document.execCommand(name,false,value || null); sync(); remember();}
        const blocks = document.createElement('select'); blocks.setAttribute('aria-label','Tipo de parágrafo');
        [['p','Parágrafo'],['h1','Título 1'],['h2','Título 2'],['h3','Título 3']].forEach(([value,label]) => {const option = document.createElement('option'); option.value=value; option.textContent=label; blocks.appendChild(option);});
        blocks.addEventListener('pointerdown',remember); blocks.addEventListener('change',() => command('formatBlock',blocks.value)); toolbar.appendChild(blocks);
        [['Negrito','bold'],['Itálico','italic'],['Sublinhado','underline'],['Marcadores','insertUnorderedList'],['Numeração','insertOrderedList'],['Desfazer','undo'],['Refazer','redo']].forEach(([label,name]) => {
            const button = document.createElement('button'); button.type='button'; button.textContent=label; button.title=label;
            button.addEventListener('mousedown',event => {event.preventDefault(); remember();});
            button.addEventListener('click',() => command(name)); toolbar.appendChild(button);
        });
        shell.append(toolbar,editor); textarea.insertAdjacentElement('afterend',shell);
        const label = document.querySelector('label[for="'+textarea.id+'"]'); if (label) label.htmlFor = editor.id;
        load(); textarea.hidden=true;
        editor.addEventListener('input',sync); editor.addEventListener('keyup',remember); editor.addEventListener('mouseup',remember);
        editor.addEventListener('paste',event => {
            event.preventDefault();
            const html = event.clipboardData.getData('text/html');
            const content = html ? cleanHtml(html) : plainHtml(event.clipboardData.getData('text/plain'));
            if (/<(?:p|div|h[1-6]|ul|ol)\b/i.test(content)) document.execCommand('formatBlock',false,'p');
            document.execCommand('insertHTML',false,content); sync(); remember();
        });
        editor.addEventListener('drop',event => event.preventDefault());
        textarea.addEventListener('input',() => {if (textarea.value !== lastValue) load();});
        if (textarea.form) {
            textarea.form.addEventListener('submit',sync,true);
            textarea.form.addEventListener('reset',() => setTimeout(load,0));
        }
    }
    function init() {document.querySelectorAll('[data-budget-rich]').forEach(attach);}
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded',init); else init();
})();
