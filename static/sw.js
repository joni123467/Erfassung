// VERSION is injected into /sw.js by the server. The worker and its assets
// remain one version for their complete lifetime; no background replacement.
const APP_VERSION = self.__ERFASSUNG_VERSION || new URLSearchParams(self.location.search).get('v') || 'dev';
const CACHE_PREFIX = 'erfassung-mobile-v';
const CACHE_VERSION = `${CACHE_PREFIX}${APP_VERSION}`;
const OFFLINE_SHELL = '/static/mobile-offline-shell.html';
const CORE_ASSETS = [OFFLINE_SHELL, '/static/styles.css', '/static/mobile-interface.css', '/static/admin-interface.css',
  '/static/dashboard-interface.css', '/static/interface.js', '/static/mobile.js', '/static/mobile-sync.js',
  '/static/app.js', '/static/theme.js', '/static/vacation-calendar.js', '/static/manifest.webmanifest',
  '/static/icons/icon.svg', '/static/icons/icon-192.png', '/static/icons/icon-512.png'];
importScripts(`/static/mobile-sync.js?v=${APP_VERSION}`);

self.addEventListener('install', event => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE_VERSION);
    try {
      await cache.addAll(CORE_ASSETS.map(url => new Request(`${url}?v=${APP_VERSION}`, { cache: 'no-cache' })));
    } catch (error) {
      await caches.delete(CACHE_VERSION);
      throw error;
    }
    // First installation activates normally. Updates wait for explicit acceptance.
  })());
});

self.addEventListener('activate', event => {
  event.waitUntil((async () => {
    const keys = (await caches.keys()).filter(key => key.startsWith(CACHE_PREFIX));
    // Keep one previous release for clients finishing their navigation. Never
    // delete unrelated applications' caches, IndexedDB, outbox or localStorage.
    const previous = keys.filter(key => key !== CACHE_VERSION).at(-1);
    await Promise.all(keys.filter(key => key !== CACHE_VERSION && key !== previous).map(key => caches.delete(key)));
    await self.clients.claim();
  })());
});

async function clientsAreSafe() {
  const clients = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
  const answers = await Promise.all(clients.filter(client => new URL(client.url).pathname.startsWith('/mobile')).map(client => new Promise(resolve => {
    const channel = new MessageChannel();
    const timer = setTimeout(() => { channel.port1.close(); resolve(false); }, 3000);
    channel.port1.onmessage = event => { clearTimeout(timer); channel.port1.close(); resolve(event.data?.safe === true); };
    client.postMessage({ type: 'CAN_ACTIVATE' }, [channel.port2]);
  })));
  return answers.every(Boolean);
}

self.addEventListener('message', event => {
  if (event.data?.type !== 'ACTIVATE_UPDATE') return;
  event.waitUntil((async () => {
    const accepted = await clientsAreSafe();
    event.ports[0]?.postMessage({ accepted });
    if (accepted) await self.skipWaiting();
  })());
});

self.addEventListener('sync', event => {
  if (event.tag !== 'erfassung-outbox') return;
  event.waitUntil((async () => {
    const store = new self.ErfassungSync.MobileStore();
    const engine = new self.ErfassungSync.SyncEngine(store);
    try {
      const ok = await engine.run();
      const clients = await self.clients.matchAll({ type: 'window' });
      clients.forEach(client => client.postMessage({ type: 'SYNC_COMPLETE' }));
      if (!ok && (await store.pending()).length) throw new Error('Outbox wartet auf Verbindung, Anmeldung oder Prüfung');
    } finally { store.close(); }
  })());
});

self.addEventListener('fetch', event => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== 'GET' || url.origin !== self.location.origin) return;
  if (request.mode === 'navigate') {
    if (url.pathname === '/mobile' || url.pathname === '/mobile/') {
      // Generic shell only: no stale session, CSRF token or another user's HTML.
      event.respondWith((async () => {
        const cache = await caches.open(CACHE_VERSION);
        return (await cache.match(`${OFFLINE_SHELL}?v=${APP_VERSION}`)) || Response.error();
      })());
    }
    return;
  }
  if (CORE_ASSETS.includes(url.pathname)) {
    event.respondWith((async () => {
      const requestedVersion = url.searchParams.get('v') || APP_VERSION;
      const cache = await caches.open(`${CACHE_PREFIX}${requestedVersion}`);
      const cached = await cache.match(`${url.pathname}?v=${requestedVersion}`);
      if (cached) return cached;
      // Old workers cached unversioned files; they stay readable during upgrade.
      const legacy = await cache.match(url.pathname);
      if (legacy) return legacy;
      return fetch(request);
    })());
  }
  // APIs and session endpoints always go to the network. Never cache them.
});
