const CACHE_VERSION = 'erfassung-mobile-v0.1.5-r2';
const MOBILE_SHELL = '/mobile';
const OFFLINE_SHELL = '/static/mobile-offline-shell.html';
const CORE_ASSETS = [
  MOBILE_SHELL,
  OFFLINE_SHELL,
  '/static/styles.css',
  '/static/mobile.js',
  '/static/app.js',
  '/static/manifest.webmanifest',
  '/static/icons/icon.svg',
];

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE_VERSION).then((cache) => cache.addAll(CORE_ASSETS)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE_VERSION).map((key) => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

async function cacheFirst(request) {
  const cached = await caches.match(request, { ignoreSearch: true });
  if (cached) {
    return cached;
  }
  const response = await fetch(request);
  if (response && response.ok) {
    const cache = await caches.open(CACHE_VERSION);
    cache.put(request, response.clone());
  }
  return response;
}

async function staleWhileRevalidate(request) {
  const cache = await caches.open(CACHE_VERSION);
  const cached = await cache.match(request, { ignoreSearch: true });
  const networkPromise = fetch(request)
    .then((response) => {
      if (response && response.ok) {
        cache.put(request, response.clone());
      }
      return response;
    })
    .catch(() => null);
  return cached || networkPromise || Response.error();
}

async function networkFirstForNavigation(request) {
  try {
    const response = await fetch(request);
    if (response && response.ok) {
      const cache = await caches.open(CACHE_VERSION);
      cache.put(MOBILE_SHELL, response.clone());
      return response;
    }
  } catch (error) {
    // ignore and fallback to cache
  }
  const cached = await caches.match(request, { ignoreSearch: true });
  if (cached) {
    return cached;
  }
  const mobileShell = await caches.match(MOBILE_SHELL, { ignoreSearch: true });
  if (mobileShell) {
    return mobileShell;
  }
  return (await caches.match(OFFLINE_SHELL, { ignoreSearch: true })) || Response.error();
}

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') {
    return;
  }

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) {
    return;
  }

  if (request.mode === 'navigate' || request.destination === 'document') {
    event.respondWith(networkFirstForNavigation(request));
    return;
  }

  if (url.pathname.startsWith('/static/')) {
    event.respondWith(staleWhileRevalidate(request));
    return;
  }

  if (url.pathname.startsWith('/api/') || url.pathname === '/mobile/sync-data') {
    event.respondWith(
      fetch(request).catch(() => caches.match(request, { ignoreSearch: true }) || Response.error())
    );
    return;
  }

  event.respondWith(cacheFirst(request));
});
