/*
Caminho: C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\GESTFLOW\static\service-worker.js
Último recode: 2026-07-04 16:30 (America/Bahia)
Motivo: Criar service worker básico do PWA GestFlow.
*/

const GESTFLOW_CACHE = "gestflow-pwa-v1";
const GESTFLOW_ASSETS = [
    "/static/manifest.json",
    "/static/css/dashboard.css",
    "/static/img/gestflow-icon-180.png",
    "/static/img/gestflow-icon-192.png",
    "/static/img/gestflow-icon-512.png",
    "/static/img/gestflow-logo.png"
];

self.addEventListener("install", function (event) {
    event.waitUntil(
        caches.open(GESTFLOW_CACHE).then(function (cache) {
            return cache.addAll(GESTFLOW_ASSETS);
        }).catch(function () {
            return Promise.resolve();
        })
    );
    self.skipWaiting();
});

self.addEventListener("activate", function (event) {
    event.waitUntil(
        caches.keys().then(function (keys) {
            return Promise.all(
                keys
                    .filter(function (key) {
                        return key !== GESTFLOW_CACHE;
                    })
                    .map(function (key) {
                        return caches.delete(key);
                    })
            );
        })
    );
    self.clients.claim();
});

self.addEventListener("fetch", function (event) {
    const request = event.request;

    if (request.method !== "GET") {
        return;
    }

    const url = new URL(request.url);

    if (url.origin !== self.location.origin) {
        return;
    }

    if (request.mode === "navigate") {
        event.respondWith(
            fetch(request)
                .then(function (response) {
                    const responseClone = response.clone();
                    caches.open(GESTFLOW_CACHE).then(function (cache) {
                        cache.put(request, responseClone);
                    });
                    return response;
                })
                .catch(function () {
                    return caches.match(request).then(function (cached) {
                        return cached || caches.match("/login");
                    });
                })
        );
        return;
    }

    if (url.pathname.startsWith("/static/")) {
        event.respondWith(
            caches.match(request).then(function (cached) {
                return cached || fetch(request).then(function (response) {
                    const responseClone = response.clone();
                    caches.open(GESTFLOW_CACHE).then(function (cache) {
                        cache.put(request, responseClone);
                    });
                    return response;
                });
            })
        );
    }
});
