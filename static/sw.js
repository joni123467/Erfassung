const CACHE_VERSION = 'erfassung-mobile-v0.3.0';
const MOBILE_SHELL = '/mobile';
const OFFLINE_SHELL = '/static/mobile-offline-shell.html';

// All assets that must be available immediately after install – including the
// offline shell so the app is usable without any prior online visit.
const CORE_ASSETS = [
  OFFLINE_SHELL,
  '/static/styles.css',
  '/static/mobile.js',
  '/static/app.js',
  '/static/manifest.webmanifest',
  '/static/icons/icon.svg',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches
      .open(CACHE_VERSION)
      .then((cache) => cache.addAll(CORE_ASSETS))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(keys.filter((key) => key !== CACHE_VERSION).map((key) => caches.delete(key)))
      )
      .then(() => self.clients.claim())
  );
});

// ── Cache-first for static assets ────────────────────────────────────────────
// Serve from cache immediately; revalidate in the background.
async function cacheFirstStatic(request) {
  const cache = await caches.open(CACHE_VERSION);
  const cached = await cache.match(request, { ignoreSearch: true });
  // Background revalidation (fire-and-forget)
  const networkPromise = fetch(request)
    .then((response) => {
      if (response && response.ok) cache.put(request, response.clone());
      return response;
    })
    .catch(() => null);
  return cached || networkPromise || Response.error();
}

// ── Offline-first navigation ──────────────────────────────────────────────────
// Serve cached page immediately so the app opens instantly, even without
// network. The authenticated /mobile page is cached on first successful load
// and updated silently in the background on every subsequent online visit.
async function offlineFirstNavigation(request) {
  const cache = await caches.open(CACHE_VERSION);

  // 1. Try the exact cached page first (covers /mobile with any query params)
  const exactCached = await cache.match(request, { ignoreSearch: true });
  if (exactCached) {
    // Silently update the cache in the background
    fetch(request)
      .then((response) => {
        if (response && response.ok) cache.put(MOBILE_SHELL, response.clone());
      })
      .catch(() => {});
    return exactCached;
  }

  // 2. Try the generic /mobile shell cached from a previous visit
  const shellCached = await cache.match(MOBILE_SHELL, { ignoreSearch: true });
  if (shellCached) {
    fetch(request)
      .then((response) => {
        if (response && response.ok) cache.put(MOBILE_SHELL, response.clone());
      })
      .catch(() => {});
    return shellCached;
  }

  // 3. No cached page yet – try the network (first-ever visit)
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 6000);
    const response = await fetch(request, { signal: controller.signal });
    clearTimeout(timeoutId);
    if (response && response.ok) {
      cache.put(MOBILE_SHELL, response.clone());
      return response;
    }
  } catch {
    // Network unavailable on very first visit
  }

  // 4. Ultimate fallback: static offline shell
  return (await cache.match(OFFLINE_SHELL)) || Response.error();
}

// ── Sync-data: cache last successful response ─────────────────────────────────
async function syncDataHandler(request) {
  const cache = await caches.open(CACHE_VERSION);
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 6000);
    const response = await fetch(request, { signal: controller.signal });
    clearTimeout(timeoutId);
    if (response && response.ok) {
      cache.put(request, response.clone());
      return response;
    }
    throw new Error(`HTTP ${response.status}`);
  } catch {
    const cached = await cache.match(request, { ignoreSearch: true });
    return cached || Response.error();
  }
}

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // Navigation requests (HTML pages)
  if (request.mode === 'navigate' || request.destination === 'document') {
    event.respondWith(offlineFirstNavigation(request));
    return;
  }

  // Static assets – serve from cache immediately
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(cacheFirstStatic(request));
    return;
  }

  // Sync-data endpoint – cache last successful payload for offline use
  if (url.pathname === '/mobile/sync-data') {
    event.respondWith(syncDataHandler(request));
    return;
  }

  // API ping – always network, no cache (used for reachability checks)
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(
      fetch(request).catch(() => Response.error())
    );
    return;
  }
});
