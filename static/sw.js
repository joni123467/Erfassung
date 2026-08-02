// Die Version steht im **Inhalt** dieser Datei: Die Route /sw.js stanzt sie als
// self.__ERFASSUNG_VERSION ein, gespeist aus der serverseitigen VERSION-Datei.
// Eine neue Fassung ändert dadurch die Skriptbytes, und genau darauf achtet die
// Aktualisierungsprüfung des Browsers – selbst dann, wenn eine installierte PWA
// noch eine alte Seite aus dem Zwischenspeicher anzeigt, deren
// Registrierungsadresse ein veraltetes `?v=` trägt. Das `?v=` bleibt nur als
// Rückfallebene für die Auslieferung der reinen statischen Datei.
const APP_VERSION = self.__ERFASSUNG_VERSION
  || new URLSearchParams(self.location.search).get('v')
  || 'dev';
const CACHE_VERSION = `erfassung-mobile-v${APP_VERSION}`;
const MOBILE_SHELL = '/mobile';
const OFFLINE_SHELL = '/static/mobile-offline-shell.html';

const CORE_ASSETS = [
  OFFLINE_SHELL,
  '/static/styles.css',
  '/static/mobile.js',
  '/static/app.js',
  '/static/theme.js',
  '/static/manifest.webmanifest',
  '/static/icons/icon.svg',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_VERSION).then(async (cache) => {
      // 'no-cache' erzwingt eine Revalidierung am Server: Der neue Worker darf
      // seine Assets nicht aus einem stalen HTTP-Cache übernehmen, sonst wäre
      // die neue Cache-Version mit alten Dateien gefüllt.
      await cache.addAll(CORE_ASSETS.map((url) => new Request(url, { cache: 'no-cache' })));
      // /mobile vorab mit der Offline-Hülle belegen, damit die Anwendung auch
      // ohne Netz startet – schon vor dem ersten angemeldeten Besuch. Der
      // Eintrag wird stillschweigend durch die echte Seite ersetzt, sobald
      // /mobile das erste Mal online geladen wird.
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
// Immer sofort aus dem Zwischenspeicher ausliefern – möglich, weil /mobile schon
// bei der Installation vorbelegt wird. Die echte, angemeldete Seite wird bei
// jedem Besuch mit Netz im Hintergrund nachgeschrieben und löst die Offline-Hülle
// ab. Weiterleitungen zur Anmeldung landen nie im Zwischenspeicher.
async function offlineFirstNavigation(request) {
  const cache = await caches.open(CACHE_VERSION);

  // Sofort die gespeicherte Seite ausliefern: entweder die bei der Installation
  // hinterlegte Offline-Hülle oder die echte Seite aus einem früheren Besuch.
  const cached = await cache.match(MOBILE_SHELL, { ignoreSearch: true });
  if (cached) {
    // Im Hintergrund still auffrischen – eine Weiterleitung zur Anmeldung wird
    // dabei nie gespeichert.
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
    // Kein Netz
  }

  // Letzte Rückfallebene: die Offline-Hülle; sie steht immer in CORE_ASSETS.
  return (await cache.match(OFFLINE_SHELL)) || Response.error();
}

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (request.mode === 'navigate' || request.destination === 'document') {
    // Nur die Mobilroute wird zuerst aus dem Zwischenspeicher bedient. Jede
    // andere Seite (/, /dashboard, /admin, /login, /records/*) muss ins Netz,
    // damit gewöhnliche Navigation und serverseitige Weiterleitungen (303)
    // schon beim **ersten** Klick greifen.
    //
    // Ohne diese Bremse lieferte der Worker die gespeicherte Mobilhülle für
    // **alle** Navigationen aus – er beherrscht inzwischen den Bereich "/" –,
    // wodurch Nicht-Mobilseiten einen Klick hinterherhinkten und die
    // 303-Weiterleitung von /admin nicht mehr funktionierte.
    if (url.pathname === '/mobile' || url.pathname === '/mobile/') {
      event.respondWith(offlineFirstNavigation(request));
    }
    return;
  }

  if (url.pathname.startsWith('/static/')) {
    event.respondWith(cacheFirstStatic(request));
    return;
  }

  // Schnittstellenaufrufe – auch /mobile/sync-data – gehen direkt ins Netz.
  // Die Abgleichsdaten legt mobile.js ohnehin in der IndexedDB ab; der Worker
  // muss dafür nichts zwischenspeichern.
  if (url.pathname.startsWith('/api/') || url.pathname === '/mobile/sync-data') {
    event.respondWith(
      fetch(request).catch(() => Response.error())
    );
    return;
  }
});
