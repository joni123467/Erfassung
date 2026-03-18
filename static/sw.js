const CACHE_VERSION = 'erfassung-mobile-v0.3.2b';
const MOBILE_SHELL = '/mobile';
const OFFLINE_SHELL = '/static/mobile-offline-shell.html';

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
    caches.open(CACHE_VERSION).then(async (cache) => {
      await cache.addAll(CORE_ASSETS);
      // Pre-seed /mobile with the offline shell so the app always opens offline,
      // even before the first authenticated online visit. This entry is silently
      // replaced with the real page the first time the user loads /mobile online.
      const shell = await cache.match(OFFLINE_SHELL);
      if (shell) await cache.put(MOBILE_SHELL, shell.clone());
    }).then(() => self.skipWaiting())
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
async function cacheFirstStatic(request) {
  const cache = await caches.open(CACHE_VERSION);
  const cached = await cache.match(request, { ignoreSearch: true });
  const networkPromise = fetch(request)
    .then((response) => {
      if (response && response.ok) cache.put(request, response.clone());
      return response;
    })
    .catch(() => null);
  return cached || networkPromise || Response.error();
}

// ── Offline-first navigation ──────────────────────────────────────────────────
// Always serve instantly from cache (guaranteed since we pre-seed /mobile on install).
// The real authenticated page is written in the background on every online visit,
// replacing the offline shell. Auth redirects are never cached.
async function offlineFirstNavigation(request) {
  const cache = await caches.open(CACHE_VERSION);

  // Serve the cached page immediately (offline shell pre-seeded on install,
  // or the real page from a previous online visit).
  const cached = await cache.match(MOBILE_SHELL, { ignoreSearch: true });
  if (cached) {
    // Silently update in the background – but never cache an auth redirect.
    fetch(request)
      .then((response) => {
        if (response && response.ok && !response.redirected) {
          cache.put(MOBILE_SHELL, response.clone());
        }
      })
      .catch(() => {});
    return cached;
  }

  // Fallback: try network (shouldn't normally reach here after first install)
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 8000);
    const response = await fetch(request, { signal: controller.signal });
    clearTimeout(timeoutId);
    if (response && response.ok && !response.redirected) {
      cache.put(MOBILE_SHELL, response.clone());
      return response;
    }
    if (response) return response; // e.g. login redirect – pass through as-is
  } catch {
    // Network unavailable
  }

  // Last resort: offline shell (always in CORE_ASSETS)
  return (await cache.match(OFFLINE_SHELL)) || Response.error();
}

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (request.mode === 'navigate' || request.destination === 'document') {
    event.respondWith(offlineFirstNavigation(request));
    return;
  }

  if (url.pathname.startsWith('/static/')) {
    event.respondWith(cacheFirstStatic(request));
    return;
  }

  // API routes (including /mobile/sync-data) go directly to the network.
  // Sync data is persisted in IndexedDB by mobile.js; no SW caching needed.
  if (url.pathname.startsWith('/api/') || url.pathname === '/mobile/sync-data') {
    event.respondWith(
      fetch(request).catch(() => Response.error())
    );
    return;
  }
});
