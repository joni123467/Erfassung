const CACHE_VERSION = 'erfassung-cache-v4';
const APP_SHELL_CACHE = `${CACHE_VERSION}-shell`;
const ASSET_CACHE = `${CACHE_VERSION}-assets`;

const PRECACHE_URLS = [
  '/static/offline.html',
  '/static/styles.css',
  '/static/mobile.js',
  '/static/app.js',
  '/static/manifest.webmanifest',
  '/static/icons/icon.svg'
];

self.addEventListener('install', (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(APP_SHELL_CACHE);
    const results = await Promise.allSettled(PRECACHE_URLS.map((url) => cache.add(url)));
    const failed = results.filter((item) => item.status === 'rejected');
    if (failed.length) {
      // do not block activation on partial precache failures
      console.warn('Precache had failures', failed.length);
    }
    await self.skipWaiting();
  })());
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((key) => !key.startsWith(CACHE_VERSION)).map((key) => caches.delete(key)))).then(() => self.clients.claim())
  );
});

async function staleWhileRevalidate(request, cacheName = ASSET_CACHE) {
  const cached = await caches.match(request, { ignoreSearch: true });
  const networkPromise = fetch(request)
    .then((response) => {
      if (response && response.ok) {
        caches.open(cacheName).then((cache) => cache.put(request, response.clone()));
      }
      return response;
    })
    .catch(() => null);
  return cached || networkPromise;
}

async function networkFirstDocument(request) {
  try {
    const response = await fetch(request);
    if (response && response.ok) {
      const cache = await caches.open(APP_SHELL_CACHE);
      cache.put(request, response.clone());
    }
    return response;
  } catch (_error) {
    const cachedExact = await caches.match(request, { ignoreSearch: true });
    if (cachedExact) return cachedExact;
    const fallback = await caches.match('/static/offline.html');
    return fallback || new Response('Offline', { status: 503, headers: { 'Content-Type': 'text/plain' } });
  }
}

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (url.pathname === '/api/ping' || url.pathname === '/health') {
    event.respondWith(fetch(request, { cache: 'no-store' }));
    return;
  }

  if (request.mode === 'navigate') {
    event.respondWith(networkFirstDocument(request));
    return;
  }

  if (url.pathname.startsWith('/api/')) {
    event.respondWith(fetch(request).catch(() => caches.match(request, { ignoreSearch: true })));
    return;
  }

  event.respondWith(staleWhileRevalidate(request));
});
