// Loaded as a module via `app.js?v={{ app_version }}` (see templates/base.html),
// so import.meta.url carries the current app version. We forward that same
// version to the service worker registration URL so that the SW cache name
// (derived from `?v=` in sw.js) tracks the deployed VERSION automatically.
const SW_VERSION = new URL(import.meta.url).searchParams.get('v') || 'dev';

window.addEventListener('DOMContentLoaded', () => {
  if ('serviceWorker' in navigator) {
    // The service worker is served from the application root (/sw.js) with a
    // `Service-Worker-Allowed: /` header so its scope can be the whole origin.
    // Registering a /static/sw.js with {scope:'/'} would be REJECTED by the
    // browser (a worker's max scope is its own path), which is why the offline
    // start previously failed: install never ran, nothing was precached.
    navigator.serviceWorker
      .register(`/sw.js?v=${SW_VERSION}`, { scope: '/' })
      .catch((error) => console.warn('Service Worker Registrierung fehlgeschlagen', error));
  }
});

