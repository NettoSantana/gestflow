// Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\static\service-worker.js
// Último recode: 2026-07-10 10:05 (America/Bahia)
// Motivo: Reforçar offline do ponto público no navegador Android/iPhone sem exigir instalação do app.

const GESTFLOW_CACHE = 'gestflow-ponto-offline-v4';
const CACHE_ANTIGOS_PREFIXO = 'gestflow-ponto-offline-';
const ULTIMO_PONTO_KEY = '/__gestflow_ultimo_ponto_publico__';
const OFFLINE_HTML_KEY = '/__gestflow_ponto_offline_base__';

const ARQUIVOS_FIXOS = [
    '/manifest.json',
    '/static/css/dashboard.css',
    '/static/js/ponto_offline.js'
];

function mesmaOrigem(url) {
    return url.origin === self.location.origin;
}

function ehArquivoFixoPermitido(pathname) {
    return ARQUIVOS_FIXOS.includes(pathname);
}

function ehTelaPontoPublico(pathname) {
    return pathname.startsWith('/ponto/');
}

function ehNavegacaoHtml(request) {
    return request.mode === 'navigate' || (request.headers.get('accept') || '').includes('text/html');
}

function deveTratarOffline(request) {
    if (request.method !== 'GET') {
        return false;
    }

    const url = new URL(request.url);
    if (!mesmaOrigem(url)) {
        return false;
    }

    return ehArquivoFixoPermitido(url.pathname) || ehTelaPontoPublico(url.pathname);
}

async function abrirCache() {
    return caches.open(GESTFLOW_CACHE);
}

async function fetchComTimeout(request, opcoes = {}, timeoutMs = 4500) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
        return await fetch(request, {...opcoes, signal: controller.signal});
    } finally {
        clearTimeout(timer);
    }
}

async function salvarRespostaPonto(request, resposta) {
    if (!resposta || !resposta.ok) {
        return resposta;
    }

    const url = new URL(request.url);
    const cache = await abrirCache();

    await cache.put(request, resposta.clone());
    await cache.put(url.pathname, resposta.clone());
    await cache.put(ULTIMO_PONTO_KEY, resposta.clone());

    return resposta;
}

async function salvarRespostaFixa(request, resposta) {
    if (!resposta || !resposta.ok) {
        return resposta;
    }

    const cache = await abrirCache();
    await cache.put(request, resposta.clone());
    return resposta;
}

async function buscarArquivoFixo(request) {
    const cache = await abrirCache();
    const respostaCache = await cache.match(request, {ignoreSearch: true});

    const atualizar = fetchComTimeout(request, {cache: 'reload'}, 3500)
        .then(resposta => salvarRespostaFixa(request, resposta))
        .catch(() => null);

    if (respostaCache) {
        atualizar.catch(() => null);
        return respostaCache;
    }

    const respostaRede = await atualizar;
    if (respostaRede) {
        return respostaRede;
    }

    return new Response('', {status: 504, statusText: 'Offline'});
}

async function fallbackPontoOffline(request) {
    const cache = await abrirCache();
    const url = new URL(request.url);

    const tentativas = [
        request,
        url.pathname,
        ULTIMO_PONTO_KEY,
        OFFLINE_HTML_KEY
    ];

    for (const chave of tentativas) {
        const resposta = await cache.match(chave, {ignoreSearch: true});
        if (resposta) {
            return resposta;
        }
    }

    return new Response(
        `<!doctype html>
        <html lang="pt-BR">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>GestFlow - Ponto Offline</title>
            <style>
                body{font-family:Arial,sans-serif;background:#f8fafc;color:#0f172a;padding:24px;margin:0}
                .card{max-width:520px;margin:40px auto;background:#fff;border:1px solid #e5eaf2;border-radius:18px;padding:22px;box-shadow:0 12px 28px rgba(15,23,42,.12)}
                h1{font-size:22px;margin:0 0 10px}p{font-size:14px;line-height:1.45;color:#475569}.ok{font-weight:900;color:#166534}
            </style>
        </head>
        <body>
            <div class="card">
                <h1>Ponto offline ainda não preparado neste navegador</h1>
                <p>Abra este mesmo link uma vez com internet no Chrome/Safari e aguarde alguns segundos. Depois disso, o link abre offline neste navegador.</p>
                <p class="ok">Não precisa instalar app.</p>
            </div>
        </body>
        </html>`,
        {
            status: 200,
            headers: {
                'Content-Type': 'text/html; charset=utf-8',
                'Cache-Control': 'no-store'
            }
        }
    );
}

async function buscarTelaPonto(request) {
    try {
        const respostaRede = await fetchComTimeout(request, {
            cache: 'no-store',
            credentials: 'include'
        }, 4500);

        return await salvarRespostaPonto(request, respostaRede);
    } catch (erro) {
        return fallbackPontoOffline(request);
    }
}

async function preCacheSeguro() {
    const cache = await abrirCache();
    await Promise.allSettled(
        ARQUIVOS_FIXOS.map(async arquivo => {
            try {
                const resposta = await fetch(arquivo, {cache: 'reload'});
                if (resposta && resposta.ok) {
                    await cache.put(arquivo, resposta.clone());
                }
            } catch (erro) {
                // Se algum arquivo fixo falhar, o service worker não deve quebrar a instalação.
            }
        })
    );
}

self.addEventListener('install', event => {
    event.waitUntil(
        preCacheSeguro()
            .then(() => self.skipWaiting())
    );
});

self.addEventListener('activate', event => {
    event.waitUntil(
        Promise.all([
            caches.keys().then(keys => Promise.all(
                keys
                    .filter(key => key !== GESTFLOW_CACHE && key.startsWith(CACHE_ANTIGOS_PREFIXO))
                    .map(key => caches.delete(key))
            )),
            self.registration.navigationPreload ? self.registration.navigationPreload.enable() : Promise.resolve(),
            self.clients.claim()
        ])
    );
});

self.addEventListener('message', event => {
    const dados = event.data || {};

    if (dados.tipo === 'SKIP_WAITING') {
        self.skipWaiting();
        return;
    }

    if (dados.tipo === 'CACHE_PONTO_HTML') {
        event.waitUntil((async () => {
            const html = String(dados.html || '');
            const urlTexto = String(dados.url || '');

            if (!html || !urlTexto) {
                return;
            }

            const url = new URL(urlTexto, self.location.origin);
            if (!mesmaOrigem(url) || !ehTelaPontoPublico(url.pathname)) {
                return;
            }

            const resposta = new Response(html, {
                status: 200,
                headers: {
                    'Content-Type': 'text/html; charset=utf-8',
                    'Cache-Control': 'no-store'
                }
            });

            const cache = await abrirCache();
            await cache.put(url.href, resposta.clone());
            await cache.put(url.pathname, resposta.clone());
            await cache.put(ULTIMO_PONTO_KEY, resposta.clone());
            await cache.put(OFFLINE_HTML_KEY, resposta.clone());
        })());
    }
});

self.addEventListener('fetch', event => {
    const request = event.request;

    if (!deveTratarOffline(request)) {
        return;
    }

    const url = new URL(request.url);

    if (ehArquivoFixoPermitido(url.pathname)) {
        event.respondWith(buscarArquivoFixo(request));
        return;
    }

    if (ehTelaPontoPublico(url.pathname) && ehNavegacaoHtml(request)) {
        event.respondWith(buscarTelaPonto(request));
        return;
    }

    event.respondWith(fetch(request));
});
