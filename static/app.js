window.addEventListener('DOMContentLoaded', () => {
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker
      .register('/sw.js?v=0.1.6-r2', { scope: '/' })
      .catch((error) => console.warn('Service Worker Registrierung fehlgeschlagen', error));
  }
});
