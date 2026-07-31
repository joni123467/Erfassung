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


// ── Einsatzort folgt der Firma ────────────────────────────────────────────
//
// Ein Standort gehört zu genau einer Firma. Wird im Formular eine andere
// Firma gewählt, muss die Standortliste mitwandern – sonst stünden dort
// firmenfremde Einträge. Die Daten liegen als JSON in der Seite, es wird
// also nichts nachgeladen (und es funktioniert offline).
//
// Der Server prüft dieselbe Zuordnung noch einmal nach; dieses Skript ist
// Bedienkomfort, keine Absicherung.
(function () {
  function readCatalogue() {
    const node = document.getElementById('location-catalogue');
    if (!node) return null;
    try {
      return JSON.parse(node.textContent || '{}');
    } catch (error) {
      return null;
    }
  }

  function fillPicker(picker, locations, keepValue) {
    const previous = keepValue ? picker.value : '';
    // „Remote" gibt es nur, wenn der Server es gerendert hat – das Kennzeichen
    // hängt am Benutzer. Der Standort selbst hängt nicht daran.
    const allowRemote = picker.hasAttribute('data-allow-remote');
    picker.innerHTML = '';
    const fixed = allowRemote
      ? [['onsite', 'Vor Ort'], ['remote', 'Remote']]
      : [['onsite', 'Vor Ort']];
    fixed.forEach(([value, label]) => {
      const option = document.createElement('option');
      option.value = value;
      option.textContent = label;
      picker.appendChild(option);
    });
    (locations || []).forEach((location) => {
      const option = document.createElement('option');
      option.value = String(location.id);
      option.textContent = location.city
        ? `${location.name} · ${location.city}`
        : location.name;
      picker.appendChild(option);
    });

    // Vorauswahl: der Hauptstandort der Firma. „Vor Ort" wäre hier die
    // falsche Antwort – wer eine Firma mit Standort wählt, meint fast immer
    // deren Standort.
    const primary = (locations || []).find((location) => location.is_primary)
      || (locations || [])[0];
    const wanted = previous && [...picker.options].some((o) => o.value === previous)
      ? previous
      : (primary ? String(primary.id) : 'onsite');
    picker.value = wanted;
  }

  function wire(form, catalogue) {
    const picker = form.querySelector('[data-location-picker]');
    const companySelect = form.querySelector('select[name="company_id"]');
    if (!picker || !companySelect) return;

    const update = (keepValue) => {
      const key = String(companySelect.value || '');
      fillPicker(picker, key ? catalogue[key] : [], keepValue);
    };

    companySelect.addEventListener('change', () => update(false));
    // Beim Laden nur auffrischen, wenn die Firma bereits feststeht – eine
    // servergerenderte Auswahl (z. B. beim Bearbeiten) bleibt sonst erhalten.
    if (companySelect.value) update(true);
  }

  window.addEventListener('DOMContentLoaded', () => {
    const catalogue = readCatalogue();
    if (!catalogue) return;
    document.querySelectorAll('form').forEach((form) => wire(form, catalogue));
  });
})();

// ── Ablehnen braucht eine Begründung ──────────────────────────────────────
//
// Der Server verlangt sie ohnehin und weist die Ablehnung sonst ab. Hier wird
// nur früher darauf hingewiesen, damit die Seite nicht mit einer Fehlermeldung
// neu lädt. Ohne JavaScript bleibt es bei der Prüfung auf dem Server.
(function () {
  window.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('[data-requires-reason]').forEach((button) => {
      button.addEventListener('click', (event) => {
        const form = button.closest('form');
        const reason = form && form.querySelector('input[name="reason"]');
        if (!reason || reason.value.trim()) return;
        event.preventDefault();
        reason.setCustomValidity(button.getAttribute('data-requires-reason') || '');
        reason.reportValidity();
        reason.addEventListener('input', () => reason.setCustomValidity(''), { once: true });
      });
    });
  });
})();
