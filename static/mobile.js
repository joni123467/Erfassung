const TAB_SELECTOR = '.mobile-tab';
const PANEL_SELECTOR = '[data-tab-panel]';
const MODAL_ID = 'mobile-order-modal';
const FORM_SELECTOR = 'form[data-offline]';
const QUEUE_INFO_ID = 'mobile-queue-info';
const QUEUE_COUNT_ID = 'mobile-pending-count';
const FEEDBACK_ID = 'mobile-feedback';
const SYNC_TEXT_ID = 'mobile-sync-text';
const MOBILE_STATE_SELECTOR = '[data-mobile-state]';
const VACATION_LIST_SELECTOR = '[data-vacation-list]';
const VACATION_EMPTY_SELECTOR = '[data-vacation-empty]';
const DB_NAME = 'erfassung-mobile';
const DB_VERSION = 2;
const PUNCH_STORE = 'pendingPunches';
const VACATION_STORE = 'pendingVacations';

const supportsIndexedDb = typeof indexedDB !== 'undefined';

function setElementHidden(element, hidden) {
  if (!element) {
    return;
  }
  if (hidden) {
    element.hidden = true;
    element.setAttribute('hidden', 'hidden');
  } else {
    element.hidden = false;
    element.removeAttribute('hidden');
  }
}

function setButtonDisabled(element, disabled) {
  if (!element) {
    return;
  }
  if (disabled) {
    element.setAttribute('disabled', 'disabled');
  } else {
    element.removeAttribute('disabled');
  }
}

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
  setElementHidden(element, !message);
  if (message) {
    const existingTimeout = Number(element.dataset.timeoutId || 0);
    if (existingTimeout) {
      window.clearTimeout(existingTimeout);
    }
    const timeoutId = window.setTimeout(() => {
      element.textContent = '';
      element.dataset.state = '';
      setElementHidden(element, true);
    }, 3500);
    element.dataset.timeoutId = String(timeoutId);
  }
}

function openDatabase() {
  return new Promise((resolve, reject) => {
    if (!supportsIndexedDb) {
      resolve(null);
      return;
    }
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onerror = () => reject(request.error);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(PUNCH_STORE)) {
        db.createObjectStore(PUNCH_STORE, { keyPath: 'id', autoIncrement: true });
      }
      if (!db.objectStoreNames.contains(VACATION_STORE)) {
        db.createObjectStore(VACATION_STORE, { keyPath: 'id', autoIncrement: true });
      }
    };
    request.onsuccess = () => resolve(request.result);
  });
}

function createQueue(storeName, fallbackKey) {
  if (!supportsIndexedDb) {
    function read() {
      try {
        return JSON.parse(localStorage.getItem(fallbackKey) || '[]');
      } catch (error) {
        console.warn('Konnte Offline-Daten nicht laden', error);
        return [];
      }
    }
    function write(data) {
      try {
        localStorage.setItem(fallbackKey, JSON.stringify(data));
      } catch (error) {
        console.warn('Konnte Offline-Daten nicht speichern', error);
      }
    }
    return {
      async add(record) {
        const data = read();
        const entry = { id: Date.now() + Math.random(), createdAt: Date.now(), data: record };
        data.push(entry);
        write(data);
        return entry.id;
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

  async function withStore(mode, callback) {
    const db = await openDatabase();
    if (!db) {
      return null;
    }
    return new Promise((resolve, reject) => {
      const transaction = db.transaction(storeName, mode);
      const store = transaction.objectStore(storeName);
      const request = callback(store);
      transaction.oncomplete = () => resolve(request?.result ?? null);
      transaction.onerror = () => reject(transaction.error);
    });
  }

  return {
    async add(record) {
      return withStore('readwrite', (store) => store.add({ createdAt: Date.now(), data: record }));
    },
    async all() {
      return (await withStore('readonly', (store) => store.getAll())) || [];
    },
    async remove(id) {
      await withStore('readwrite', (store) => store.delete(id));
    },
    async count() {
      const keys = (await withStore('readonly', (store) => store.getAllKeys())) || [];
      return keys.length;
    },
  };
}

const punchQueue = createQueue(PUNCH_STORE, 'erfassungPendingPunches');
const vacationQueue = createQueue(VACATION_STORE, 'erfassungPendingVacations');

function updateQueueIndicator({ punches = 0, vacations = 0, total = punches + vacations } = {}) {
  const info = document.getElementById(QUEUE_INFO_ID);
  const countElement = document.getElementById(QUEUE_COUNT_ID);
  const syncText = document.getElementById(SYNC_TEXT_ID);
  if (countElement) {
    countElement.textContent = String(total);
  }
  if (syncText) {
    const detailParts = [];
    if (punches) {
      detailParts.push(`${punches} Stempel`);
    }
    if (vacations) {
      detailParts.push(`${vacations} Urlaub`);
    }
    const detail = detailParts.join(' · ');
    if (total === 0) {
      syncText.textContent = 'Offline-Aktionen werden synchronisiert.';
    } else if (total === 1) {
      syncText.textContent = detail ? `Eine Aktion wartet auf Synchronisation (${detail}).` : 'Eine Aktion wartet auf Synchronisation.';
    } else {
      syncText.textContent = detail ? `${total} Aktionen warten auf Synchronisation (${detail}).` : `${total} Aktionen warten auf Synchronisation.`;
    }
  }
  setElementHidden(info, total === 0);
}

async function refreshQueueIndicator() {
  const [punches, vacations] = await Promise.all([punchQueue.count(), vacationQueue.count()]);
  const total = punches + vacations;
  updateQueueIndicator({ punches, vacations, total });
  return { punches, vacations, total };
}

async function flushPunchQueue() {
  const records = await punchQueue.all();
  if (!records.length) {
    return { processed: 0, error: false };
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
      await punchQueue.remove(record.id);
      processed += 1;
    } catch (error) {
      console.warn('Synchronisation fehlgeschlagen', error);
      errorOccurred = true;
      break;
    }
  }
  const counts = await refreshQueueIndicator();
  if (processed > 0 && counts.total === 0) {
    dispatchSyncStatus('Alle zwischengespeicherten Aktionen wurden übertragen.', 'synced');
    showFeedback('Offline-Buchungen erfolgreich übertragen.', 'success');
  } else if (errorOccurred) {
    dispatchSyncStatus('Synchronisation nicht möglich – verbleibende Aktionen werden später erneut gesendet.', 'error');
    showFeedback('Synchronisation der Buchungen fehlgeschlagen. Bitte später erneut versuchen.', 'error');
  } else if (counts.total > 0) {
    const message = counts.total === 1
      ? 'Synchronisation läuft – 1 Aktion verbleibend.'
      : `Synchronisation läuft – ${counts.total} Aktionen verbleiben.`;
    dispatchSyncStatus(message, 'queue');
  }
  return { processed, error: errorOccurred };
}

function markVacationRequestSynced(offlineId) {
  const list = document.querySelector(VACATION_LIST_SELECTOR);
  if (!list || !offlineId) {
    return;
  }
  const item = list.querySelector(`[data-offline-id="${offlineId}"]`);
  if (!item) {
    return;
  }
  item.removeAttribute('data-offline-id');
  const status = item.querySelector('.mobile-vacation__status');
  if (status) {
    status.textContent = 'Wartet auf Freigabe';
    status.classList.remove('mobile-vacation__status--offline');
    status.classList.add('mobile-vacation__status--pending');
  }
  const badge = item.querySelector('.mobile-vacation__badge');
  if (badge) {
    badge.remove();
  }
}

async function flushVacationQueue() {
  const records = await vacationQueue.all();
  if (!records.length) {
    return { processed: 0, error: false };
  }
  let processed = 0;
  let errorOccurred = false;
  for (const record of records) {
    const body = new URLSearchParams(record.data);
    try {
      const response = await fetch('/vacations', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8' },
        body: body.toString(),
        credentials: 'same-origin',
        redirect: 'follow',
      });
      if (!response.ok) {
        throw new Error(`Serverfehler ${response.status}`);
      }
      await vacationQueue.remove(record.id);
      markVacationRequestSynced(record.id);
      processed += 1;
    } catch (error) {
      console.warn('Synchronisation der Urlaubsanträge fehlgeschlagen', error);
      errorOccurred = true;
      break;
    }
  }
  const counts = await refreshQueueIndicator();
  if (processed > 0 && counts.total === 0) {
    dispatchSyncStatus('Alle zwischengespeicherten Aktionen wurden übertragen.', 'synced');
    showFeedback('Offline-Urlaubsanträge erfolgreich übertragen.', 'success');
  } else if (errorOccurred) {
    dispatchSyncStatus('Synchronisation nicht möglich – verbleibende Aktionen werden später erneut gesendet.', 'error');
    showFeedback('Synchronisation der Urlaubsanträge fehlgeschlagen. Bitte später erneut versuchen.', 'error');
  }
  return { processed, error: errorOccurred };
}

async function flushOfflineQueues() {
  await flushPunchQueue();
  await flushVacationQueue();
}

function serializeFormData(form) {
  const formData = new FormData(form);
  const entries = {};
  for (const [key, value] of formData.entries()) {
    entries[key] = typeof value === 'string' ? value : '';
  }
  return entries;
}

function formatTime(timestamp) {
  if (!timestamp) {
    return '';
  }
  const date = new Date(timestamp);
  const hours = String(date.getHours()).padStart(2, '0');
  const minutes = String(date.getMinutes()).padStart(2, '0');
  return `${hours}:${minutes}`;
}

function formatDuration(ms) {
  const totalMinutes = Math.max(0, Math.round(ms / 60000));
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  return `${hours}:${String(minutes).padStart(2, '0')}`;
}

function formatDateLabel(value) {
  if (!value) {
    return '–';
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    const parts = value.split('-');
    if (parts.length === 3) {
      return `${parts[2]}.${parts[1]}.${parts[0]}`;
    }
    return value;
  }
  const day = String(date.getDate()).padStart(2, '0');
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const year = date.getFullYear();
  return `${day}.${month}.${year}`;
}

let mobileState = null;
let workDurationTimerId = null;
let modalController = null;

function refreshControlStates() {
  document.querySelectorAll('[data-toggle-disabled]').forEach((element) => {
    const isHidden = !!element.closest('[hidden]');
    setButtonDisabled(element, isHidden);
  });
}

function applyStateVisibility(stateName, active) {
  document.querySelectorAll(`[data-state="${stateName}"]`).forEach((element) => {
    setElementHidden(element, !active);
    element.setAttribute('aria-hidden', active ? 'false' : 'true');
  });
}

function updateWorkDuration() {
  if (!mobileState) {
    return;
  }
  if (!mobileState.isWorking || !mobileState.startedAtMs) {
    mobileState.workedLabel = '0:00';
  } else {
    let total = Date.now() - mobileState.startedAtMs;
    total -= mobileState.totalBreakMs;
    if (mobileState.onBreak && mobileState.breakStartedAtMs) {
      total -= Date.now() - mobileState.breakStartedAtMs;
    }
    mobileState.workedLabel = formatDuration(total);
  }
  const workedElement = document.querySelector('[data-field="worked-duration"]');
  if (workedElement) {
    workedElement.textContent = mobileState.workedLabel || '0:00';
  }
}

function startWorkTimer() {
  if (workDurationTimerId) {
    window.clearInterval(workDurationTimerId);
    workDurationTimerId = null;
  }
  if (!mobileState || !mobileState.isWorking || !mobileState.startedAtMs) {
    updateWorkDuration();
    return;
  }
  updateWorkDuration();
  workDurationTimerId = window.setInterval(updateWorkDuration, 30000);
}

function updateUiState() {
  if (!mobileState) {
    return;
  }
  applyStateVisibility('active', mobileState.isWorking);
  applyStateVisibility('idle', !mobileState.isWorking);
  applyStateVisibility('break-active', mobileState.isWorking && mobileState.onBreak);
  applyStateVisibility('break-idle', mobileState.isWorking && !mobileState.onBreak);
  applyStateVisibility('company-active', mobileState.isWorking && mobileState.hasCompany);

  const headerStart = document.querySelector('[data-field="header-start"]');
  if (headerStart) {
    headerStart.textContent = mobileState.isWorking ? mobileState.startLabel || '--:--' : '';
  }
  const workStart = document.querySelector('[data-field="work-start"]');
  if (workStart) {
    workStart.textContent = mobileState.isWorking ? mobileState.startLabel || '--:--' : '';
  }
  const companyName = document.querySelector('[data-field="company-name"]');
  if (companyName) {
    companyName.textContent = mobileState.companyName || '';
  }
  const breakStart = document.querySelector('[data-field="break-start"]');
  if (breakStart) {
    breakStart.textContent = mobileState.onBreak ? mobileState.breakLabel || '--:--' : '';
  }
  const breakTotal = document.querySelector('[data-field="break-total"]');
  if (breakTotal) {
    breakTotal.textContent = mobileState.breakTotalLabel || '0:00';
  }
  refreshControlStates();
  updateWorkDuration();
  startWorkTimer();
}

function initializeMobileState() {
  const root = document.querySelector(MOBILE_STATE_SELECTOR);
  if (!root) {
    return;
  }
  const data = root.dataset;
  mobileState = {
    isWorking: data.stateRunning === 'true',
    onBreak: data.stateBreak === 'true',
    hasCompany: data.stateCompany === 'true',
    startedAtMs: data.startTimestamp ? Date.parse(data.startTimestamp) : null,
    breakStartedAtMs: data.breakTimestamp ? Date.parse(data.breakTimestamp) : null,
    totalBreakMs: Number(data.totalBreakMinutes || '0') * 60000,
    startLabel: data.startLabel || '',
    breakLabel: data.breakLabel || '',
    breakTotalLabel: data.breakTotalLabel || (data.totalBreakMinutes ? formatDuration(Number(data.totalBreakMinutes) * 60000) : '0:00'),
    companyName: data.companyName || '',
    workedLabel: data.workedLabel || '0:00',
  };
  if (mobileState.isWorking && !mobileState.startedAtMs) {
    mobileState.startedAtMs = Date.now();
    mobileState.startLabel = formatTime(mobileState.startedAtMs);
  }
  updateUiState();
}

function determineCompanyName(form, payload) {
  const newCompany = (payload.new_company_name || '').trim();
  if (newCompany) {
    return newCompany;
  }
  const select = form?.querySelector('select[name="company_id"]');
  if (select && select instanceof HTMLSelectElement) {
    const option = select.options[select.selectedIndex];
    if (option && option.value) {
      return option.textContent.trim();
    }
  }
  return '';
}

function setWorkingState(startTimestamp, { hasCompany = false, companyName = '', resetBreak = true } = {}) {
  if (!mobileState) {
    return;
  }
  if (startTimestamp) {
    mobileState.isWorking = true;
    mobileState.startedAtMs = startTimestamp;
    mobileState.startLabel = formatTime(startTimestamp);
    if (resetBreak) {
      mobileState.totalBreakMs = 0;
      mobileState.breakTotalLabel = '0:00';
    }
    mobileState.onBreak = false;
    mobileState.breakStartedAtMs = null;
    mobileState.breakLabel = '';
    mobileState.hasCompany = hasCompany;
    mobileState.companyName = companyName;
  } else {
    mobileState.isWorking = false;
    mobileState.startedAtMs = null;
    mobileState.startLabel = '';
    mobileState.totalBreakMs = 0;
    mobileState.breakTotalLabel = '0:00';
    mobileState.onBreak = false;
    mobileState.breakStartedAtMs = null;
    mobileState.breakLabel = '';
    mobileState.hasCompany = false;
    mobileState.companyName = '';
  }
  updateUiState();
}

function appendVacationPreview(payload, { offline = false, offlineId = null, status = 'pending' } = {}) {
  const list = document.querySelector(VACATION_LIST_SELECTOR);
  const empty = document.querySelector(VACATION_EMPTY_SELECTOR);
  if (!list) {
    return;
  }
  setElementHidden(list, false);
  if (empty) {
    setElementHidden(empty, true);
  }
  const item = document.createElement('li');
  item.className = 'mobile-vacation';
  if (offlineId) {
    item.dataset.offlineId = String(offlineId);
  }
  const statusClass = offline ? 'offline' : status;
  const statusLabels = {
    approved: 'Genehmigt',
    pending: 'Wartet auf Freigabe',
    withdraw: 'Rücknahme angefragt',
    cancelled: 'Zurückgezogen',
    rejected: 'Abgelehnt',
    offline: 'Offline gespeichert',
  };
  const statusLabel = statusLabels[statusClass] || 'Wartet auf Freigabe';

  const header = document.createElement('header');
  header.className = 'mobile-vacation__header';

  const title = document.createElement('strong');
  title.textContent = `${formatDateLabel(payload.start_date)} – ${formatDateLabel(payload.end_date)}`;
  header.appendChild(title);

  const statusElement = document.createElement('span');
  statusElement.className = `mobile-vacation__status mobile-vacation__status--${statusClass}`;
  statusElement.textContent = statusLabel;
  header.appendChild(statusElement);
  item.appendChild(header);

  const meta = document.createElement('div');
  meta.className = 'mobile-vacation__meta';
  const type = document.createElement('span');
  const useOvertime = payload.use_overtime === 'on' || payload.use_overtime === 'true';
  type.textContent = useOvertime ? 'Überstundenabbau' : 'Urlaub';
  meta.appendChild(type);
  const comment = (payload.comment || '').trim();
  if (comment) {
    const commentElement = document.createElement('span');
    commentElement.className = 'mobile-vacation__comment';
    commentElement.textContent = comment;
    meta.appendChild(commentElement);
  }
  item.appendChild(meta);

  if (offline) {
    const badge = document.createElement('span');
    badge.className = 'mobile-vacation__badge';
    badge.textContent = 'Synchronisation ausstehend';
    item.appendChild(badge);
  }

  list.prepend(item);
  const maxItems = 8;
  while (list.children.length > maxItems) {
    list.removeChild(list.lastElementChild);
  }
}

function applyOfflinePunchAction(action, payload, form) {
  if (!mobileState) {
    return;
  }
  const now = Date.now();
  switch (action) {
    case 'start_work':
      setWorkingState(now, { hasCompany: false, companyName: '', resetBreak: true });
      break;
    case 'end_work':
      setWorkingState(null);
      break;
    case 'start_break':
      if (!mobileState.onBreak && mobileState.isWorking) {
        mobileState.onBreak = true;
        mobileState.breakStartedAtMs = now;
        mobileState.breakLabel = formatTime(now);
        updateUiState();
      }
      break;
    case 'end_break':
      if (mobileState.onBreak && mobileState.isWorking) {
        const diff = mobileState.breakStartedAtMs ? Math.max(0, now - mobileState.breakStartedAtMs) : 0;
        mobileState.totalBreakMs += diff;
        mobileState.breakTotalLabel = formatDuration(mobileState.totalBreakMs);
        mobileState.onBreak = false;
        mobileState.breakStartedAtMs = null;
        mobileState.breakLabel = '';
        updateUiState();
      }
      break;
    case 'start_company': {
      const companyName = determineCompanyName(form, payload);
      setWorkingState(now, { hasCompany: true, companyName, resetBreak: true });
      if (modalController?.close) {
        modalController.close();
      }
      break;
    }
    case 'end_company':
      setWorkingState(now, { hasCompany: false, companyName: '', resetBreak: true });
      break;
    default:
      break;
  }
}

async function processPunchSubmission(form, payload) {
  const action = payload.action;
  const actionUrl = form?.getAttribute('action') || '/punch';
  const body = new URLSearchParams(payload);

  async function storeOffline(reason) {
    try {
      await punchQueue.add(payload);
      await refreshQueueIndicator();
      if (reason === 'server') {
        dispatchSyncStatus('Server nicht erreichbar – Aktionen werden nachgereicht.', 'error');
        showFeedback('Server nicht erreichbar. Buchung wurde zwischengespeichert.', 'error');
      } else {
        dispatchSyncStatus('Offline – Aktionen werden nachgereicht.', 'queue');
        showFeedback('Buchung offline gespeichert. Wird synchronisiert, sobald eine Verbindung besteht.', 'info');
      }
      applyOfflinePunchAction(action, payload, form);
      if (form instanceof HTMLFormElement) {
        form.reset();
      }
    } catch (error) {
      console.error('Konnte Buchung nicht offline speichern', error);
      showFeedback('Fehler beim Zwischenspeichern. Bitte erneut versuchen.', 'error');
    }
  }

  if (navigator.onLine) {
    try {
      const response = await fetch(actionUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8' },
        body: body.toString(),
        credentials: 'same-origin',
        redirect: 'follow',
      });
      if (!response.ok) {
        throw new Error(`Serverfehler ${response.status}`);
      }
      if (response.redirected) {
        window.location.href = response.url;
        return;
      }
      const nextUrl = payload.next_url;
      if (typeof nextUrl === 'string' && nextUrl) {
        window.location.href = nextUrl;
        return;
      }
      dispatchSyncStatus('Buchung erfolgreich übertragen.', 'synced');
      showFeedback('Buchung erfolgreich übertragen.', 'success');
      if (form instanceof HTMLFormElement) {
        form.reset();
      }
      return;
    } catch (error) {
      console.warn('Direkte Übertragung fehlgeschlagen, speichere offline', error);
      await storeOffline('server');
      return;
    }
  }

  await storeOffline('offline');
}

async function processVacationSubmission(form, payload) {
  const actionUrl = form?.getAttribute('action') || '/vacations';
  const body = new URLSearchParams(payload);

  async function storeOffline(reason) {
    try {
      const id = await vacationQueue.add(payload);
      await refreshQueueIndicator();
      if (reason === 'server') {
        dispatchSyncStatus('Server nicht erreichbar – Aktionen werden nachgereicht.', 'error');
        showFeedback('Server nicht erreichbar. Urlaubsantrag wurde zwischengespeichert.', 'error');
      } else {
        dispatchSyncStatus('Offline – Aktionen werden nachgereicht.', 'queue');
        showFeedback('Urlaubsantrag offline gespeichert. Wird synchronisiert, sobald eine Verbindung besteht.', 'info');
      }
      appendVacationPreview(payload, { offline: true, offlineId: id });
      if (form instanceof HTMLFormElement) {
        form.reset();
      }
    } catch (error) {
      console.error('Konnte Urlaubsantrag nicht offline speichern', error);
      showFeedback('Fehler beim Zwischenspeichern. Bitte erneut versuchen.', 'error');
    }
  }

  if (navigator.onLine) {
    try {
      const response = await fetch(actionUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8' },
        body: body.toString(),
        credentials: 'same-origin',
        redirect: 'follow',
      });
      if (!response.ok) {
        throw new Error(`Serverfehler ${response.status}`);
      }
      const finalUrl = response.url ? new URL(response.url, window.location.origin) : null;
      const errorMessage = finalUrl?.searchParams.get('error');
      if (errorMessage) {
        showFeedback(decodeURIComponent(errorMessage.replace(/\+/g, ' ')), 'error');
        return;
      }
      appendVacationPreview(payload, { status: 'pending' });
      showFeedback('Urlaubsantrag erfolgreich übertragen.', 'success');
      if (form instanceof HTMLFormElement) {
        form.reset();
      }
      return;
    } catch (error) {
      console.warn('Direkte Übertragung des Urlaubsantrags fehlgeschlagen, speichere offline', error);
      await storeOffline('server');
      return;
    }
  }

  await storeOffline('offline');
}

function handleOfflineSubmission(event) {
  event.preventDefault();
  const form = event.target;
  const payload = serializeFormData(form);
  const offlineType = form?.dataset.offline || 'punch';
  if (offlineType === 'vacation') {
    processVacationSubmission(form, payload);
  } else {
    processPunchSubmission(form, payload);
  }
}

function registerTabHandling() {
  const tabs = Array.from(document.querySelectorAll(TAB_SELECTOR));
  const panels = Array.from(document.querySelectorAll(PANEL_SELECTOR));
  const validTabs = new Set(tabs.map((tab) => tab.dataset.tab));
  const defaultTab = tabs.find((tab) => tab.classList.contains('is-active'))?.dataset.tab || 'buchung';

  function activateTab(tabName, updateHistory = true) {
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
      panel.setAttribute('aria-hidden', isActive ? 'false' : 'true');
      setElementHidden(panel, !isActive);
    });
    if (updateHistory) {
      const newHash = `#${tabName}`;
      if (history.replaceState) {
        const url = new URL(window.location.href);
        url.searchParams.set('tab', tabName);
        url.hash = newHash;
        history.replaceState(null, '', `${url.pathname}${url.search}${url.hash}`);
      } else {
        window.location.hash = newHash;
      }
    }
  }

  tabs.forEach((tab) =>
    tab.addEventListener('click', (event) => {
      try {
        activateTab(tab.dataset.tab);
        event.preventDefault();
      } catch (error) {
        console.error('Konnte mobilen Reiter nicht wechseln', error);
      }
    })
  );
  window.addEventListener('hashchange', () => activateTab(window.location.hash.replace('#', ''), false));
  const initialHash = window.location.hash.replace('#', '');
  let initialTab = initialHash;
  if (!initialTab) {
    try {
      const url = new URL(window.location.href);
      initialTab = url.searchParams.get('tab') || '';
    } catch (error) {
      initialTab = '';
    }
  }
  activateTab(initialTab || defaultTab, false);
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

  modalController = {
    open: () => setVisibility(true),
    close: () => setVisibility(false),
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
    flushOfflineQueues();
  });
}

window.addEventListener('DOMContentLoaded', async () => {
  registerTabHandling();
  registerModalHandling();
  initializeMobileState();
  registerOfflineForms();
  setupConnectionHandlers();
  await refreshQueueIndicator();
  if (navigator.onLine) {
    flushOfflineQueues();
  }
});
