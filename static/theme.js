// Light/dark theme switching. The persisted choice (localStorage key
// "erfassung-theme") is applied BEFORE first paint by a small inline snippet
// in the <head> of base.html and mobile-offline-shell.html — this file only
// wires up the toggle buttons and keeps the browser UI color in sync.
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

  // Sync meta/aria with the state the inline head snippet already applied.
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
      /* storage unavailable (private mode) – theme still switches for the session */
    }
    applyTheme(next);
  });
}());
