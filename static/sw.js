const CACHE_VERSION = 'erfassung-mobile-v0.2.0';
const MOBILE_SHELL = '/mobile';
const OFFLINE_SHELL = '/static/mobile-offline-shell.html';
const NAVIGATION_TIMEOUT_MS = 3000;
const API_TIMEOUT_MS = 4000;

// Only truly static assets are pre-cached on install.
// /mobile is NOT pre-cached here because it requires authentication –
// caching during install would store the /login redirect instead.
// It gets cached the first time the authenticated user loads it
// (see networkFirstForNavigation below).
const CORE_ASSETS = [
  OFFLINE_SHELL,
  '/static/styles.css',
  '/static/mobile.js',
  '/static/app.js',
  '/static/manifest.webmanifest',
  '/static/icons/icon.svg',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_VERSION).then((cache) => cache.addAll(CORE_ASSETS)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE_VERSION).map((key) => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

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

async function fetchWithTimeout(request, timeoutMs) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(request, { signal: controller.signal });
  } finally {
    clearTimeout(timeoutId);
  }
}

// Network-first for authenticated page navigation.
// On success: updates the cache so offline visits get the latest version.
// On failure: serves the cached page (has the user's session state from last visit),
//             or falls back to the static offline shell as last resort.
async function networkFirstForNavigation(request) {
  const cache = await caches.open(CACHE_VERSION);
  try {
    const response = await fetchWithTimeout(request, NAVIGATION_TIMEOUT_MS);
    if (response && response.ok) {
      cache.put(MOBILE_SHELL, response.clone());
      return response;
    }
  } catch {
    // Network unavailable or timeout – fall through to cache
  }
  const cached = await cache.match(request, { ignoreSearch: true });
  if (cached) return cached;
  const mobileShell = await cache.match(MOBILE_SHELL, { ignoreSearch: true });
  if (mobileShell) return mobileShell;
  return (await cache.match(OFFLINE_SHELL)) || Response.error();
}

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (request.mode === 'navigate' || request.destination === 'document') {
    event.respondWith(networkFirstForNavigation(request));
    return;
  }

  if (url.pathname.startsWith('/static/')) {
    event.respondWith(staleWhileRevalidate(request));
    return;
  }

  if (url.pathname === '/mobile/sync-data') {
    // Cache the last successful sync-data response for offline use
    event.respondWith(
      fetchWithTimeout(request, API_TIMEOUT_MS)
        .then(async (response) => {
          if (response && response.ok) {
            const cache = await caches.open(CACHE_VERSION);
            cache.put(request, response.clone());
          }
          return response;
        })
        .catch(async () => {
          const cached = await caches.match(request, { ignoreSearch: true });
          return cached || Response.error();
        })
    );
    return;
  }

  if (url.pathname.startsWith('/api/')) {
    // API calls: always try network, no cache fallback (used for auth checks)
    event.respondWith(
      fetchWithTimeout(request, API_TIMEOUT_MS).catch(() => Response.error())
    );
    return;
  }
});
