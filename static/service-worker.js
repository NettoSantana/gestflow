// Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\static\service-worker.js
// Último recode: 2026-07-10 12:25 (America/Bahia)
// Motivo: Forçar atualização do ponto_offline.js com envio seguro da acao online.

const GESTFLOW_CACHE = 'gestflow-ponto-offline-v10';
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

function deveUsarCacheOffline(request) {
    if (request.method !== 'GET') {
        return false;
    }

    const url = new URL(request.url);

    if (!mesmaOrigem(url)) {
        return false;
    }

    return ehArquivoFixoPermitido(url.pathname) || ehTelaPontoPublico(url.pathname);
}

async function buscarSemCache(request) {
    return fetch(request, { cache: 'no-store' });
}

async function buscarComFallbackOffline(request) {
    const url = new URL(request.url);
    const cache = await caches.open(GESTFLOW_CACHE);

    try {
        const respostaRede = await fetch(request, { cache: 'no-store' });

        if (respostaRede && respostaRede.ok) {
            await cache.put(request, respostaRede.clone());
        }

        return respostaRede;
    } catch (erro) {
        const respostaCache = await cache.match(request);
        if (respostaCache) {
            return respostaCache;
        }

        if (ehTelaPontoPublico(url.pathname)) {
            const paginas = await cache.keys();
            const ultimaTelaPonto = paginas.reverse().find(item => new URL(item.url).pathname.startsWith('/ponto/'));
            if (ultimaTelaPonto) {
                const fallback = await cache.match(ultimaTelaPonto);
                if (fallback) {
                    return fallback;
                }
            }
        }

        throw erro;
    }
}

self.addEventListener('install', event => {
    event.waitUntil(
        caches.open(GESTFLOW_CACHE)
            .then(cache => Promise.all(ARQUIVOS_FIXOS.map(arquivo => cache.add(arquivo).catch(() => null))))
            .then(() => self.skipWaiting())
    );
});

self.addEventListener('activate', event => {
    event.waitUntil(
        caches.keys()
            .then(keys => Promise.all(keys.filter(key => key !== GESTFLOW_CACHE).map(key => caches.delete(key))))
            .then(() => self.clients.claim())
    );
});

self.addEventListener('fetch', event => {
    const request = event.request;

    if (!deveUsarCacheOffline(request)) {
        event.respondWith(buscarSemCache(request));
        return;
    }

    event.respondWith(buscarComFallbackOffline(request));
});
