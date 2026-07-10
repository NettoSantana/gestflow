// Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\static\service-worker.js
// Último recode: 2026-07-10 10:20 (America/Bahia)
// Motivo: Reforçar cache da tela pública de ponto e atualizar arquivos offline do navegador.

const GESTFLOW_CACHE = 'gestflow-ponto-offline-v5';
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

async function salvarResposta(cache, request, resposta) {
    if (!resposta || !resposta.ok) {
        return resposta;
    }

    const url = new URL(request.url);
    await cache.put(request, resposta.clone());

    if (ehTelaPontoPublico(url.pathname)) {
        await cache.put(new Request(url.origin + url.pathname), resposta.clone());
    }

    return resposta;
}

async function buscarArquivoFixo(request) {
    const cache = await caches.open(GESTFLOW_CACHE);
    const respostaCache = await cache.match(request);
    if (respostaCache) {
        return respostaCache;
    }

    const respostaRede = await fetch(request, { cache: 'reload' });
    return salvarResposta(cache, request, respostaRede);
}

async function buscarTelaPonto(request) {
    const cache = await caches.open(GESTFLOW_CACHE);
    const url = new URL(request.url);

    try {
        const respostaRede = await fetch(request, { cache: 'no-store' });
        return await salvarResposta(cache, request, respostaRede);
    } catch (erro) {
        const respostaExata = await cache.match(request);
        if (respostaExata) {
            return respostaExata;
        }

        const respostaSemQuery = await cache.match(new Request(url.origin + url.pathname));
        if (respostaSemQuery) {
            return respostaSemQuery;
        }

        const keys = await cache.keys();
        for (const key of keys) {
            const keyUrl = new URL(key.url);
            if (ehTelaPontoPublico(keyUrl.pathname)) {
                const respostaQualquerPonto = await cache.match(key);
                if (respostaQualquerPonto) {
                    return respostaQualquerPonto;
                }
            }
        }

        throw erro;
    }
}

self.addEventListener('install', event => {
    event.waitUntil(
        caches.open(GESTFLOW_CACHE)
            .then(cache => Promise.all(
                ARQUIVOS_FIXOS.map(async arquivo => {
                    try {
                        const resposta = await fetch(arquivo, { cache: 'reload' });
                        if (resposta && resposta.ok) {
                            await cache.put(arquivo, resposta);
                        }
                    } catch (erro) {}
                })
            ))
            .then(() => self.skipWaiting())
    );
});

self.addEventListener('activate', event => {
    event.waitUntil(
        caches.keys()
            .then(keys => Promise.all(
                keys
                    .filter(key => key !== GESTFLOW_CACHE)
                    .map(key => caches.delete(key))
            ))
            .then(() => self.clients.claim())
    );
});

self.addEventListener('fetch', event => {
    const request = event.request;

    if (!deveUsarCacheOffline(request)) {
        return;
    }

    const url = new URL(request.url);

    if (ehArquivoFixoPermitido(url.pathname)) {
        event.respondWith(buscarArquivoFixo(request));
        return;
    }

    if (ehTelaPontoPublico(url.pathname)) {
        event.respondWith(buscarTelaPonto(request));
    }
});
