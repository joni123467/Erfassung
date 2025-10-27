const TAB_SELECTOR = '.mobile-tab';
const PANEL_SELECTOR = '[data-tab-panel]';
const MODAL_ID = 'mobile-order-modal';
const FORM_SELECTOR = 'form[data-offline="punch"]';
const QUEUE_INFO_ID = 'mobile-queue-info';
const QUEUE_COUNT_ID = 'mobile-pending-count';
const FEEDBACK_ID = 'mobile-feedback';
const SYNC_TEXT_ID = 'mobile-sync-text';
const DB_NAME = 'erfassung-mobile';
const STORE_NAME = 'pendingPunches';

const supportsIndexedDb = typeof indexedDB !== 'undefined';

function dispatchSyncStatus(message, state = 'default') {
  document.dispatchEvent(
    new CustomEvent('offline-sync-status', {
      detail: { message, state },
    })
  );
}

function showFeedback(message, type = 'info') {
  const element = document.getElementById(FEEDBACK_ID);
  if (!element) {
    return;
  }
  element.textContent = message;
  element.dataset.state = type;
  element.toggleAttribute('hidden', !message);
  if (message) {
    const existingTimeout = Number(element.dataset.timeoutId || 0);
    if (existingTimeout) {
      window.clearTimeout(existingTimeout);
    }
    const timeoutId = window.setTimeout(() => {
      element.textContent = '';
      element.dataset.state = '';
      element.setAttribute('hidden', 'hidden');
    }, 3500);
    element.dataset.timeoutId = String(timeoutId);
  }
}

const queueStorage = (() => {
  if (!supportsIndexedDb) {
    const KEY = 'erfassungPendingPunches';
    function read() {
      try {
        return JSON.parse(localStorage.getItem(KEY) || '[]');
      } catch (error) {
        console.warn('Konnte Offline-Daten nicht laden', error);
        return [];
      }
    }
    function write(data) {
      try {
        localStorage.setItem(KEY, JSON.stringify(data));
      } catch (error) {
        console.warn('Konnte Offline-Daten nicht speichern', error);
      }
    }
    return {
      async add(record) {
        const data = read();
        data.push({ id: Date.now() + Math.random(), createdAt: Date.now(), data: record });
        write(data);
      },
      async all() {
        return read();
      },
      async remove(id) {
        write(read().filter((item) => item.id !== id));
      },
      async count() {
        return read().length;
      },
    };
  }

  function openDatabase() {
    return new Promise((resolve, reject) => {
      const request = indexedDB.open(DB_NAME, 1);
      request.onerror = () => reject(request.error);
      request.onupgradeneeded = () => {
        request.result.createObjectStore(STORE_NAME, { keyPath: 'id', autoIncrement: true });
      };
      request.onsuccess = () => resolve(request.result);
    });
  }

  async function withStore(mode, callback) {
    const db = await openDatabase();
    return new Promise((resolve, reject) => {
      const transaction = db.transaction(STORE_NAME, mode);
      const store = transaction.objectStore(STORE_NAME);
      const request = callback(store);
      transaction.oncomplete = () => resolve(request?.result);
      transaction.onerror = () => reject(transaction.error);
    });
  }

  return {
    async add(record) {
      await withStore('readwrite', (store) => store.add({ createdAt: Date.now(), data: record }));
    },
    async all() {
      return (await withStore('readonly', (store) => store.getAll())) || [];
    },
    async remove(id) {
      await withStore('readwrite', (store) => store.delete(id));
    },
    async count() {
      const items = await withStore('readonly', (store) => store.getAllKeys());
      return items ? items.length : 0;
    },
  };
})();

function updateQueueIndicator(count) {
  const info = document.getElementById(QUEUE_INFO_ID);
  const countElement = document.getElementById(QUEUE_COUNT_ID);
  const syncText = document.getElementById(SYNC_TEXT_ID);
  if (countElement) {
    countElement.textContent = String(count);
  }
  if (syncText) {
    syncText.textContent = count === 1
      ? 'Eine Buchung wartet auf Synchronisation.'
      : `${count} Buchungen warten auf Synchronisation.`;
  }
  if (info) {
    info.toggleAttribute('hidden', count === 0);
  }
}

async function flushQueue() {
  const records = await queueStorage.all();
  if (!records.length) {
    updateQueueIndicator(0);
    return;
  }
  let processed = 0;
  let errorOccurred = false;
  for (const record of records) {
    const body = new URLSearchParams(record.data);
    try {
      const response = await fetch('/punch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8' },
        body: body.toString(),
        credentials: 'same-origin',
      });
      if (!response.ok) {
        throw new Error(`Serverfehler ${response.status}`);
      }
      await queueStorage.remove(record.id);
      processed += 1;
    } catch (error) {
      console.warn('Synchronisation fehlgeschlagen', error);
      errorOccurred = true;
      break;
    }
  }
  const remaining = await queueStorage.count();
  updateQueueIndicator(remaining);
  if (processed > 0 && remaining === 0) {
    dispatchSyncStatus('Alle zwischengespeicherten Buchungen wurden übertragen.', 'synced');
    showFeedback('Offline-Buchungen erfolgreich übertragen.', 'success');
    return;
  }
  if (errorOccurred) {
    const errorMessage = remaining === 1
      ? 'Synchronisation nicht möglich – 1 Buchung bleibt offen.'
      : `Synchronisation nicht möglich – ${remaining} Buchungen bleiben offen.`;
    dispatchSyncStatus(errorMessage, 'error');
    showFeedback('Synchronisation fehlgeschlagen. Bitte später erneut versuchen.', 'error');
    return;
  }
  if (remaining > 0) {
    const queueMessage = remaining === 1
      ? 'Synchronisation läuft – 1 Buchung verbleibend.'
      : `Synchronisation läuft – ${remaining} Buchungen verbleiben.`;
    dispatchSyncStatus(queueMessage, 'queue');
  }
}

function serializeFormData(form) {
  const formData = new FormData(form);
  const entries = {};
  for (const [key, value] of formData.entries()) {
    entries[key] = typeof value === 'string' ? value : '';
  }
  return entries;
}

async function handleOfflineSubmission(event) {
  if (navigator.onLine) {
    return;
  }
  event.preventDefault();
  const form = event.target;
  const payload = serializeFormData(form);
  try {
    await queueStorage.add(payload);
    const count = await queueStorage.count();
    updateQueueIndicator(count);
    const queueMessage = count === 1
      ? 'Offline – 1 Buchung wird nachgereicht.'
      : `Offline – ${count} Buchungen werden nachgereicht.`;
    dispatchSyncStatus(queueMessage, 'queue');
    showFeedback('Buchung offline gespeichert. Wird synchronisiert, sobald eine Verbindung besteht.', 'info');
  } catch (error) {
    console.error('Konnte Buchung nicht offline speichern', error);
    showFeedback('Fehler beim Zwischenspeichern. Bitte erneut versuchen.', 'error');
    return;
  }
  if (form instanceof HTMLFormElement) {
    form.reset();
  }
}

function registerTabHandling() {
  const tabs = Array.from(document.querySelectorAll(TAB_SELECTOR));
  const panels = Array.from(document.querySelectorAll(PANEL_SELECTOR));
  const validTabs = new Set(tabs.map((tab) => tab.dataset.tab));
  const defaultTab = tabs.find((tab) => tab.classList.contains('is-active'))?.dataset.tab || 'buchung';

  function activateTab(tabName, updateHash = true) {
    if (!validTabs.has(tabName)) {
      tabName = defaultTab;
    }
    tabs.forEach((tab) => {
      const isActive = tab.dataset.tab === tabName;
      tab.classList.toggle('is-active', isActive);
      tab.setAttribute('aria-selected', isActive ? 'true' : 'false');
    });
    panels.forEach((panel) => {
      const isActive = panel.dataset.tabPanel === tabName;
      panel.classList.toggle('is-active', isActive);
      panel.toggleAttribute('hidden', !isActive);
    });
    if (updateHash) {
      const newHash = `#${tabName}`;
      if (history.replaceState) {
        const { pathname, search } = window.location;
        history.replaceState(null, '', `${pathname}${search}${newHash}`);
      } else {
        window.location.hash = newHash;
      }
    }
  }

  tabs.forEach((tab) =>
    tab.addEventListener('click', (event) => {
      event.preventDefault();
      activateTab(tab.dataset.tab);
    })
  );
  window.addEventListener('hashchange', () => activateTab(window.location.hash.replace('#', ''), false));
  const initialHash = window.location.hash.replace('#', '');
  activateTab(initialHash || defaultTab, false);
}

function registerModalHandling() {
  const modal = document.getElementById(MODAL_ID);
  if (!modal) {
    return;
  }
  const openers = document.querySelectorAll(`[data-open="${MODAL_ID}"]`);
  const closers = modal.querySelectorAll('[data-close]');

  const setVisibility = (visible) => {
    if (visible) {
      modal.classList.add('is-visible');
      modal.setAttribute('aria-hidden', 'false');
      document.body.classList.add('modal-open');
      const firstInput = modal.querySelector('select, input, button');
      if (firstInput instanceof HTMLElement) {
        firstInput.focus();
      }
    } else {
      modal.classList.remove('is-visible');
      modal.setAttribute('aria-hidden', 'true');
      document.body.classList.remove('modal-open');
    }
  };

  openers.forEach((button) => button.addEventListener('click', () => setVisibility(true)));
  closers.forEach((element) => element.addEventListener('click', () => setVisibility(false)));
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && modal.classList.contains('is-visible')) {
      setVisibility(false);
    }
  });
}

function registerOfflineForms() {
  const forms = document.querySelectorAll(FORM_SELECTOR);
  forms.forEach((form) => form.addEventListener('submit', handleOfflineSubmission));
}

function setupConnectionHandlers() {
  window.addEventListener('online', () => {
    flushQueue();
  });
}

window.addEventListener('DOMContentLoaded', async () => {
  registerTabHandling();
  registerModalHandling();
  registerOfflineForms();
  setupConnectionHandlers();
  const count = await queueStorage.count();
  updateQueueIndicator(count);
  if (navigator.onLine) {
    flushQueue();
  }
});
