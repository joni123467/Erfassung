// Light/dark theme switching. The persisted choice (localStorage key
// "erfassung-theme") wird **vor** dem ersten Bildaufbau von einem kurzen
// Schnipsel im <head> von base.html und mobile-offline-shell.html gesetzt.
// Diese Datei verdrahtet nur die Umschalter und hält die Browserfarbe passend.
(function () {
  var KEY = 'erfassung-theme';
  var root = document.documentElement;

  function currentTheme() {
    return root.getAttribute('data-theme') === 'dark' ? 'dark' : 'light';
  }

  function applyTheme(theme) {
    if (theme === 'dark') {
      root.setAttribute('data-theme', 'dark');
    } else {
      root.removeAttribute('data-theme');
    }
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) {
      meta.setAttribute('content', theme === 'dark' ? '#0f172a' : '#2563eb');
    }
    var toggles = document.querySelectorAll('[data-theme-toggle]');
    for (var i = 0; i < toggles.length; i++) {
      toggles[i].setAttribute('aria-pressed', theme === 'dark' ? 'true' : 'false');
    }
  }

  // Meta- und ARIA-Angaben mit dem Zustand abgleichen, den der Schnipsel im
  // Kopfbereich bereits gesetzt hat.
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      applyTheme(currentTheme());
    });
  } else {
    applyTheme(currentTheme());
  }

  // Event delegation so toggles in late-rendered content also work.
  document.addEventListener('click', function (event) {
    var target = event.target;
    var button = target && target.closest ? target.closest('[data-theme-toggle]') : null;
    if (!button) return;
    event.preventDefault();
    var next = currentTheme() === 'dark' ? 'light' : 'dark';
    try {
      localStorage.setItem(KEY, next);
    } catch (e) {
      /* Kein Speicher verfügbar (privates Fenster) – das Aussehen wechselt
         trotzdem, nur eben nicht über die Sitzung hinaus. */
    }
    applyTheme(next);
  });
}());
