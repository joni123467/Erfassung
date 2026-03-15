const CACHE_VERSION = 'erfassung-mobile-v0.1.6-r3';
const MOBILE_SHELL = '/mobile';
const OFFLINE_SHELL = '/static/mobile-offline-shell.html';
const NAVIGATION_TIMEOUT_MS = 1500;
const API_TIMEOUT_MS = 4000;
const STATIC_TIMEOUT_MS = 2500;
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
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE_VERSION);
    await Promise.allSettled(CORE_ASSETS.map((asset) => cache.add(asset)));
    await self.skipWaiting();
  })());
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE_VERSION).map((key) => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

async function fetchWithTimeout(request, timeoutMs) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(request, { signal: controller.signal });
  } finally {
    clearTimeout(timeoutId);
  }
}

async function cacheFirst(request, timeoutMs = 0) {
  const cached = await caches.match(request, { ignoreSearch: true });
  if (cached) {
    return cached;
  }
  const response = timeoutMs > 0 ? await fetchWithTimeout(request, timeoutMs) : await fetch(request);
  if (response && response.ok) {
    const cache = await caches.open(CACHE_VERSION);
    cache.put(request, response.clone());
  }
  return response;
}

async function refreshInBackground(request, timeoutMs) {
  try {
    const response = await fetchWithTimeout(request, timeoutMs);
    if (response && response.ok) {
      const cache = await caches.open(CACHE_VERSION);
      await cache.put(request, response.clone());
    }
  } catch (error) {
    // ignore refresh failures
  }
}

async function networkFirstForNavigation(request) {
  try {
    const response = await fetchWithTimeout(request, NAVIGATION_TIMEOUT_MS);
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
    event.respondWith(cacheFirst(request, STATIC_TIMEOUT_MS).catch(() => Response.error()));
    event.waitUntil(refreshInBackground(request, STATIC_TIMEOUT_MS));
    return;
  }

  if (url.pathname.startsWith('/api/') || url.pathname === '/mobile/sync-data') {
    event.respondWith(
      fetchWithTimeout(request, API_TIMEOUT_MS).catch(() => caches.match(request, { ignoreSearch: true }) || Response.error())
    );
    return;
  }

  event.respondWith(cacheFirst(request, NAVIGATION_TIMEOUT_MS));
});
