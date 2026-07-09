// Caminho: static/service-worker.js
// Último recode: 2026-07-09 10:00 (America/Bahia)
// Motivo: Permitir carregamento offline básico da tela pública de ponto.
const GESTFLOW_CACHE = 'gestflow-ponto-offline-v1';
const ARQUIVOS_FIXOS = [
    '/manifest.json',
    '/static/css/dashboard.css',
    '/static/js/ponto_offline.js'
];

self.addEventListener('install', event => {
    event.waitUntil(
        caches.open(GESTFLOW_CACHE).then(cache => cache.addAll(ARQUIVOS_FIXOS)).then(() => self.skipWaiting())
    );
});

self.addEventListener('activate', event => {
    event.waitUntil(
        caches.keys().then(keys => Promise.all(keys.filter(key => key !== GESTFLOW_CACHE).map(key => caches.delete(key)))).then(() => self.clients.claim())
    );
});

self.addEventListener('fetch', event => {
    const request = event.request;
    if(request.method !== 'GET'){return;}

    event.respondWith(
        fetch(request).then(response => {
            const copia = response.clone();
            caches.open(GESTFLOW_CACHE).then(cache => cache.put(request, copia));
            return response;
        }).catch(() => caches.match(request).then(response => response || caches.match('/static/js/ponto_offline.js')))
    );
});
