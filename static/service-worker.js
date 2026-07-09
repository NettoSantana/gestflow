// Caminho: static/service-worker.js
// Último recode: 2026-07-09 11:30 (America/Bahia)
// Motivo: Atualizar cache offline da tela pública de ponto após validação do celular.
const GESTFLOW_CACHE = 'gestflow-ponto-offline-v2';
const ARQUIVOS_FIXOS = [
    '/manifest.json',
    '/static/css/dashboard.css',
    '/static/js/ponto_offline.js'
];

self.addEventListener('install', event => {
    event.waitUntil(
        caches.open(GESTFLOW_CACHE)
            .then(cache => cache.addAll(ARQUIVOS_FIXOS))
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
    if(request.method !== 'GET'){return;}

    const url = new URL(request.url);
    const ehTelaPonto = url.pathname.startsWith('/ponto/');

    if(ehTelaPonto){
        event.respondWith(
            fetch(request).then(response => {
                const copia = response.clone();
                caches.open(GESTFLOW_CACHE).then(cache => cache.put(request, copia));
                return response;
            }).catch(() => caches.match(request).then(response => response || caches.match('/static/js/ponto_offline.js')))
        );
        return;
    }

    event.respondWith(
        caches.match(request).then(cached => {
            if(cached){return cached;}
            return fetch(request).then(response => {
                const copia = response.clone();
                caches.open(GESTFLOW_CACHE).then(cache => cache.put(request, copia));
                return response;
            });
        }).catch(() => caches.match('/static/js/ponto_offline.js'))
    );
});
