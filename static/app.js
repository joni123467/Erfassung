const OFFLINE_BANNER_ID = 'offline-banner';
const OFFLINE_STATUS_ID = 'offline-sync-status';
const HIDE_DELAY_MS = 4000;
let hideTimeoutId = null;
let previousNetworkOnline = null;

function setBannerVisibility(visible, autoHide = false) {
  const banner = document.getElementById(OFFLINE_BANNER_ID);
  if (!banner) return;
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
  if (!element) return;
  element.textContent = message;
  element.dataset.state = state;
}

function renderConnectivityState(state, fromTransition = false) {
  if (!state) return;
  const { networkOnline, serverReachable, syncInProgress, pendingOperations, failedOperations, conflictOperations } = state;

  if (!networkOnline) {
    updateBannerText('Kein Netz – Offline-Modus aktiv.', 'offline');
    setBannerVisibility(true);
    return;
  }
  if (!serverReachable) {
    updateBannerText('Netz verfügbar, Server nicht erreichbar.', 'error');
    setBannerVisibility(true);
    return;
  }
  if (conflictOperations > 0) {
    updateBannerText(`${conflictOperations} Konflikt(e) erfordern Prüfung.`, 'error');
    setBannerVisibility(true);
    return;
  }
  if (failedOperations > 0) {
    updateBannerText(`${failedOperations} Aktion(en) fehlgeschlagen.`, 'error');
    setBannerVisibility(true);
    return;
  }
  if (syncInProgress) {
    updateBannerText('Synchronisation läuft …', 'queue');
    setBannerVisibility(true);
    return;
  }
  if (pendingOperations > 0) {
    updateBannerText(`${pendingOperations} Aktion(en) warten auf Synchronisation.`, 'queue');
    setBannerVisibility(true);
    return;
  }
  if (fromTransition) {
    updateBannerText('Verbindung wiederhergestellt.', 'synced');
    setBannerVisibility(true, true);
  } else {
    setBannerVisibility(false);
  }
}

window.addEventListener('online', () => {
  if (previousNetworkOnline === false) {
    renderConnectivityState({
      networkOnline: true,
      serverReachable: false,
      syncInProgress: false,
      pendingOperations: 0,
      failedOperations: 0,
      conflictOperations: 0,
    }, true);
  }
  previousNetworkOnline = true;
});
window.addEventListener('offline', () => {
  previousNetworkOnline = false;
  renderConnectivityState({
    networkOnline: false,
    serverReachable: false,
    syncInProgress: false,
    pendingOperations: 0,
    failedOperations: 0,
    conflictOperations: 0,
  });
});

document.addEventListener('mobile-sync-state', (event) => {
  const detail = event?.detail;
  if (!detail) return;
  const transition = previousNetworkOnline === false && detail.networkOnline === true;
  previousNetworkOnline = !!detail.networkOnline;
  renderConnectivityState(detail, transition);
});

document.addEventListener('offline-sync-status', (event) => {
  if (!event?.detail?.message) return;
  updateBannerText(event.detail.message, event.detail.state || 'default');
  setBannerVisibility(true, event.detail.state === 'synced');
});

window.addEventListener('DOMContentLoaded', () => {
  previousNetworkOnline = navigator.onLine;
  if (!navigator.onLine) {
    renderConnectivityState({
      networkOnline: false,
      serverReachable: false,
      syncInProgress: false,
      pendingOperations: 0,
      failedOperations: 0,
      conflictOperations: 0,
    });
  } else {
    setBannerVisibility(false);
  }
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/static/sw.js', { scope: '/' }).catch((error) => {
      console.warn('Service Worker Registrierung fehlgeschlagen', error);
    });
  }
});
