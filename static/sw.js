const CACHE_VERSION = 'erfassung-cache-v1';
const CORE_ASSETS = [
  '/',
  '/mobile',
  '/static/styles.css',
  '/static/mobile.js',
  '/static/app.js',
  '/static/manifest.webmanifest',
  '/static/icons/icon.svg'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_VERSION).then((cache) => cache.addAll(CORE_ASSETS)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys.filter((key) => key !== CACHE_VERSION).map((key) => caches.delete(key))
      )
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') {
    return;
  }
  const url = new URL(request.url);
  if (url.origin === self.location.origin) {
    if (request.destination === 'document') {
      event.respondWith(
        fetch(request)
          .then((response) => {
            if (response && response.ok) {
              const copy = response.clone();
              caches.open(CACHE_VERSION).then((cache) => cache.put(request, copy));
              return response;
            }
            return caches.match(request).then((cached) => {
              if (cached) {
                return cached;
              }
              return caches.match('/mobile');
            });
          })
          .catch(() => caches.match(request).then((cached) => cached || caches.match('/mobile')))
      );
      return;
    }
    if (CORE_ASSETS.includes(url.pathname)) {
      event.respondWith(
        caches.match(request).then((cached) => {
          if (cached) {
            return cached;
          }
          return fetch(request)
            .then((response) => {
              if (response && response.ok) {
                const copy = response.clone();
                caches.open(CACHE_VERSION).then((cache) => cache.put(request, copy));
              }
              return response;
            })
            .catch(() => caches.match(request));
        })
      );
      return;
    }
  }
  event.respondWith(
    caches.match(request).then((cached) => cached || fetch(request).catch(() => cached))
  );
});
