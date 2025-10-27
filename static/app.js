const OFFLINE_BANNER_ID = 'offline-banner';
const OFFLINE_STATUS_ID = 'offline-sync-status';
const HIDE_DELAY_MS = 4000;
let hideTimeoutId = null;

function setBannerVisibility(visible, autoHide = false) {
  const banner = document.getElementById(OFFLINE_BANNER_ID);
  if (!banner) {
    return;
  }
  banner.toggleAttribute('hidden', !visible);
  if (hideTimeoutId) {
    window.clearTimeout(hideTimeoutId);
    hideTimeoutId = null;
  }
  if (visible && autoHide) {
    hideTimeoutId = window.setTimeout(() => {
      banner.setAttribute('hidden', 'hidden');
      hideTimeoutId = null;
    }, HIDE_DELAY_MS);
  }
}

function updateBannerText(message, state = 'default') {
  const element = document.getElementById(OFFLINE_STATUS_ID);
  if (!element) {
    return;
  }
  element.textContent = message;
  element.dataset.state = state;
}

function handleOnlineStatusChange() {
  if (navigator.onLine) {
    updateBannerText('Verbindung wiederhergestellt.');
    setBannerVisibility(true, true);
  } else {
    updateBannerText('Offline – Buchungen werden zwischengespeichert.');
    setBannerVisibility(true);
  }
}

window.addEventListener('online', handleOnlineStatusChange);
window.addEventListener('offline', handleOnlineStatusChange);

document.addEventListener('offline-sync-status', (event) => {
  if (!event?.detail) {
    return;
  }
  const { message, state } = event.detail;
  if (typeof message === 'string') {
    updateBannerText(message, state);
    const autoHide = state === 'synced' && navigator.onLine;
    setBannerVisibility(true, autoHide);
  }
});

window.addEventListener('DOMContentLoaded', () => {
  handleOnlineStatusChange();
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker
      .register('/static/sw.js', { scope: '/' })
      .catch((error) => console.warn('Service Worker Registrierung fehlgeschlagen', error));
  }
});
