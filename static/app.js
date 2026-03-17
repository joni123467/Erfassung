window.addEventListener('DOMContentLoaded', () => {
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker
      .register('/static/sw.js?v=0.3.0', { scope: '/' })
      .catch((error) => console.warn('Service Worker Registrierung fehlgeschlagen', error));
  }
});
