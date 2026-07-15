// Die Service-Worker-Version steckt seit 0.9.13 im SKRIPTINHALT von /sw.js
// (vom Server eingebrannt) – nicht mehr in der Registrierungs-URL. Eine
// konstante URL ist wichtig: Wird app.js vom Service Worker aus dem Cache
// bedient, verliert import.meta.url seinen ?v-Parameter; eine daraus gebaute
// Registrierungs-URL flatterte dann zwischen ?v=<version> und ?v=dev und
// erzeugte ständige Neuinstallationen mit falschem Cache-Namen.

// Info tooltips: hover/focus is pure CSS; this click handler covers touch
// devices (tap to open, tap elsewhere or Escape to close).
document.addEventListener('click', (event) => {
  const trigger = event.target.closest('.info-tip__trigger');
  const openTips = document.querySelectorAll('.info-tip.is-open');
  openTips.forEach((tip) => {
    if (!trigger || tip !== trigger.parentElement) {
      tip.classList.remove('is-open');
      const button = tip.querySelector('.info-tip__trigger');
      if (button) button.setAttribute('aria-expanded', 'false');
    }
  });
  if (trigger) {
    const tip = trigger.parentElement;
    const open = tip.classList.toggle('is-open');
    trigger.setAttribute('aria-expanded', open ? 'true' : 'false');
  }
});

document.addEventListener('keydown', (event) => {
  if (event.key !== 'Escape') return;
  document.querySelectorAll('.info-tip.is-open').forEach((tip) => {
    tip.classList.remove('is-open');
    const button = tip.querySelector('.info-tip__trigger');
    if (button) button.setAttribute('aria-expanded', 'false');
  });
});

window.addEventListener('DOMContentLoaded', () => {
  if ('serviceWorker' in navigator) {
    // The service worker is served from the application root (/sw.js) with a
    // `Service-Worker-Allowed: /` header so its scope can be the whole origin.
    // Registering a /static/sw.js with {scope:'/'} would be REJECTED by the
    // browser (a worker's max scope is its own path), which is why the offline
    // start previously failed: install never ran, nothing was precached.
    //
    // updateViaCache 'none' + explicit update() checks make releases reach
    // installed PWAs reliably (esp. iOS): the /sw.js route stamps the version
    // into the script bytes, so every check after a release finds a new worker.
    navigator.serviceWorker
      .register('/sw.js', { scope: '/', updateViaCache: 'none' })
      .then((registration) => {
        registration.update().catch(() => {});
        document.addEventListener('visibilitychange', () => {
          if (document.visibilityState === 'visible') {
            registration.update().catch(() => {});
          }
        });
      })
      .catch((error) => console.warn('Service Worker Registrierung fehlgeschlagen', error));
  }
});

