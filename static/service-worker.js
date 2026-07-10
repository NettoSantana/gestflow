// Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\static\service-worker.js
// Último recode: 2026-07-10 09:35 (America/Bahia)
// Motivo: Reforçar offline do ponto público no navegador sem exigir instalação como app.

const GESTFLOW_CACHE = 'gestflow-ponto-offline-v3';
const GESTFLOW_CACHE_ANTERIORES = [
    'gestflow-ponto-offline-v1',
    'gestflow-ponto-offline-v2'
];

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

async function salvarResposta(request, resposta) {
    if (!resposta || !resposta.ok) {
        return resposta;
    }

    const url = new URL(request.url);
    const cache = await abrirCache();

    await cache.put(request, resposta.clone());

    if (ehTelaPontoPublico(url.pathname)) {
        await cache.put('/__gestflow_ultimo_ponto_publico__', resposta.clone());
    }

    return resposta;
}

async function buscarArquivoFixo(request) {
    const cache = await abrirCache();
    const respostaCache = await cache.match(request, { ignoreSearch: true });

    if (respostaCache) {
        return respostaCache;
    }

    const respostaRede = await fetch(request, { cache: 'reload' });
    return salvarResposta(request, respostaRede);
}

async function buscarTelaPonto(request) {
    const cache = await abrirCache();

    try {
        const respostaRede = await fetch(request, { cache: 'no-store' });
        return salvarResposta(request, respostaRede);
    } catch (erro) {
        const respostaExata = await cache.match(request);
        if (respostaExata) {
            return respostaExata;
        }

        const respostaSemQuery = await cache.match(request, { ignoreSearch: true });
        if (respostaSemQuery) {
            return respostaSemQuery;
        }

        const ultimaTelaPonto = await cache.match('/__gestflow_ultimo_ponto_publico__');
        if (ultimaTelaPonto) {
            return ultimaTelaPonto;
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
                    h1{font-size:22px;margin:0 0 10px}p{font-size:14px;line-height:1.45;color:#475569}
                </style>
            </head>
            <body>
                <div class="card">
                    <h1>Ponto offline ainda não preparado</h1>
                    <p>Abra este link uma vez com internet no Chrome. Depois disso, ele ficará disponível offline neste navegador.</p>
                </div>
            </body>
            </html>`,
            {
                status: 200,
                headers: { 'Content-Type': 'text/html; charset=utf-8' }
            }
        );
    }
}

self.addEventListener('install', event => {
    event.waitUntil(
        abrirCache()
            .then(cache => cache.addAll(ARQUIVOS_FIXOS))
            .then(() => self.skipWaiting())
    );
});

self.addEventListener('activate', event => {
    event.waitUntil(
        Promise.all([
            caches.keys().then(keys => Promise.all(
                keys
                    .filter(key => key !== GESTFLOW_CACHE && (key.startsWith('gestflow-ponto-offline-') || GESTFLOW_CACHE_ANTERIORES.includes(key)))
                    .map(key => caches.delete(key))
            )),
            self.registration.navigationPreload ? self.registration.navigationPreload.enable() : Promise.resolve(),
            self.clients.claim()
        ])
    );
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
