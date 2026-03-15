const TAB_SELECTOR = '.mobile-tab';
const PANEL_SELECTOR = '[data-tab-panel]';
const MODAL_ID = 'mobile-order-modal';
const FORM_SELECTOR = 'form[data-offline]';
const FEEDBACK_ID = 'mobile-feedback';
const MOBILE_STATE_SELECTOR = '[data-mobile-state]';
const VACATION_LIST_SELECTOR = '[data-vacation-list]';
const VACATION_EMPTY_SELECTOR = '[data-vacation-empty]';

const DB_NAME = 'erfassung-mobile';
const DB_VERSION = 3;
const ACTION_STORE = 'pendingActions';
const DATA_STORE = 'mobileData';
const META_STORE = 'meta';
const MOBILE_STATE_STORAGE_KEY = 'erfassungMobileState';
const MONTH_WINDOW_DAYS = 183;

const supportsIndexedDb = typeof indexedDB !== 'undefined';
let localStorageUnavailable = false;
let mobileState = null;
let workDurationTimerId = null;
let modalController = null;

function setElementHidden(element, hidden) {
  if (!element) return;
  element.hidden = !!hidden;
  if (hidden) {
    element.setAttribute('hidden', 'hidden');
  } else {
    element.removeAttribute('hidden');
  }
}

function withLocalStorage(callback) {
  if (localStorageUnavailable) return null;
  try {
    const storage = window.localStorage;
    if (!storage) {
      localStorageUnavailable = true;
      return null;
    }
    return callback(storage);
  } catch (error) {
    localStorageUnavailable = true;
    return null;
  }
}

function dispatchSyncStatus(message, state = 'default') {
  document.dispatchEvent(new CustomEvent('offline-sync-status', { detail: { message, state } }));
}

function showFeedback(message, type = 'info') {
  const element = document.getElementById(FEEDBACK_ID);
  if (!element) return;
  element.textContent = message;
  element.dataset.state = type;
  setElementHidden(element, !message);
  if (!message) return;
  const oldTimeout = Number(element.dataset.timeoutId || 0);
  if (oldTimeout) window.clearTimeout(oldTimeout);
  const timeoutId = window.setTimeout(() => {
    element.textContent = '';
    element.dataset.state = '';
    setElementHidden(element, true);
  }, 4200);
  element.dataset.timeoutId = String(timeoutId);
}

function setStatusBadge(online) {
  const badge = document.getElementById('mobile-server-badge');
  if (!badge) return;
  badge.textContent = online ? 'Online' : 'Offline';
  badge.dataset.state = online ? 'online' : 'offline';
}

function updateLastSyncLabel(value) {
  const element = document.getElementById('mobile-last-sync');
  if (!element) return;
  if (!value) {
    element.textContent = 'Noch keine Synchronisation';
    return;
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    element.textContent = value;
    return;
  }
  element.textContent = `${date.toLocaleDateString('de-DE')} ${date.toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' })}`;
}

function updateLocalDataBadge(hasData) {
  const element = document.getElementById('mobile-local-data');
  if (!element) return;
  element.textContent = hasData ? 'Lokale Daten verfügbar' : 'Noch keine lokalen Daten';
  element.dataset.state = hasData ? 'ready' : 'empty';
}

function updatePendingIndicator(total, detail) {
  const element = document.getElementById('mobile-pending-actions');
  if (!element) return;
  if (total <= 0) {
    element.textContent = 'Keine ausstehenden Offline-Aktionen';
  } else if (total === 1) {
    element.textContent = detail ? `1 Offline-Aktion wartet (${detail})` : '1 Offline-Aktion wartet';
  } else {
    element.textContent = detail ? `${total} Offline-Aktionen warten (${detail})` : `${total} Offline-Aktionen warten`;
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
      if (!db.objectStoreNames.contains(ACTION_STORE)) {
        const store = db.createObjectStore(ACTION_STORE, { keyPath: 'clientActionId' });
        store.createIndex('createdAt', 'createdAt');
      }
      if (!db.objectStoreNames.contains(DATA_STORE)) {
        db.createObjectStore(DATA_STORE, { keyPath: 'key' });
      }
      if (!db.objectStoreNames.contains(META_STORE)) {
        db.createObjectStore(META_STORE, { keyPath: 'key' });
      }
    };
    request.onsuccess = () => resolve(request.result);
  });
}

async function withStore(storeName, mode, callback) {
  const db = await openDatabase();
  if (!db) return null;
  return new Promise((resolve, reject) => {
    const transaction = db.transaction(storeName, mode);
    const store = transaction.objectStore(storeName);
    const request = callback(store);
    transaction.oncomplete = () => resolve(request?.result ?? null);
    transaction.onerror = () => reject(transaction.error);
  });
}

async function putRecord(storeName, record) {
  return withStore(storeName, 'readwrite', (store) => store.put(record));
}

async function getRecord(storeName, key) {
  return withStore(storeName, 'readonly', (store) => store.get(key));
}

async function deleteRecord(storeName, key) {
  return withStore(storeName, 'readwrite', (store) => store.delete(key));
}

async function getAllRecords(storeName) {
  return (await withStore(storeName, 'readonly', (store) => store.getAll())) || [];
}

function generateClientActionId(prefix) {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

function serializeFormData(form) {
  const payload = {};
  for (const [key, value] of new FormData(form).entries()) {
    payload[key] = typeof value === 'string' ? value : '';
  }
  return payload;
}

function formatTime(ms) {
  if (!ms) return '';
  const date = new Date(ms);
  return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;
}

function formatDuration(ms) {
  const totalMinutes = Math.max(0, Math.round(ms / 60000));
  return `${Math.floor(totalMinutes / 60)}:${String(totalMinutes % 60).padStart(2, '0')}`;
}

function loadStoredMobileState() {
  return withLocalStorage((storage) => {
    try {
      return JSON.parse(storage.getItem(MOBILE_STATE_STORAGE_KEY) || 'null');
    } catch {
      return null;
    }
  });
}

function persistMobileState() {
  if (!mobileState) return;
  withLocalStorage((storage) => {
    storage.setItem(MOBILE_STATE_STORAGE_KEY, JSON.stringify({ ...mobileState, version: 2, updatedAt: Date.now() }));
    return null;
  });
}

function clearStoredMobileState() {
  withLocalStorage((storage) => {
    storage.removeItem(MOBILE_STATE_STORAGE_KEY);
    return null;
  });
}

function applyStateVisibility(name, active) {
  document.querySelectorAll(`[data-state="${name}"]`).forEach((element) => setElementHidden(element, !active));
}

function refreshControlStates() {
  document.querySelectorAll('[data-toggle-disabled]').forEach((element) => {
    element.toggleAttribute('disabled', !!element.closest('[hidden]'));
  });
}

function updateWorkDuration() {
  if (!mobileState) return;
  if (!mobileState.isWorking || !mobileState.startedAtMs) {
    mobileState.workedLabel = '0:00';
  } else {
    let total = Date.now() - mobileState.startedAtMs - (mobileState.totalBreakMs || 0);
    if (mobileState.onBreak && mobileState.breakStartedAtMs) total -= Date.now() - mobileState.breakStartedAtMs;
    mobileState.workedLabel = formatDuration(total);
  }
  const el = document.querySelector('[data-field="worked-duration"]');
  if (el) el.textContent = mobileState.workedLabel;
}

function startWorkTimer() {
  if (workDurationTimerId) window.clearInterval(workDurationTimerId);
  workDurationTimerId = null;
  updateWorkDuration();
  if (!mobileState?.isWorking) return;
  workDurationTimerId = window.setInterval(updateWorkDuration, 30000);
}

function updateUiState() {
  if (!mobileState) return;
  applyStateVisibility('active', mobileState.isWorking);
  applyStateVisibility('idle', !mobileState.isWorking);
  applyStateVisibility('break-active', mobileState.isWorking && mobileState.onBreak);
  applyStateVisibility('break-idle', mobileState.isWorking && !mobileState.onBreak);
  applyStateVisibility('company-active', mobileState.isWorking && mobileState.hasCompany);

  const map = {
    'header-start': mobileState.isWorking ? mobileState.startLabel || '--:--' : '',
    'work-start': mobileState.isWorking ? mobileState.startLabel || '--:--' : '',
    'company-name': mobileState.companyName || '',
    'break-start': mobileState.onBreak ? mobileState.breakLabel || '--:--' : '',
    'break-total': mobileState.breakTotalLabel || '0:00',
  };
  Object.entries(map).forEach(([key, value]) => {
    const el = document.querySelector(`[data-field="${key}"]`);
    if (el) el.textContent = value;
  });

  refreshControlStates();
  startWorkTimer();
  persistMobileState();
}

function initializeMobileState() {
  const root = document.querySelector(MOBILE_STATE_SELECTOR);
  if (!root) return;
  mobileState = {
    isWorking: root.dataset.stateRunning === 'true',
    onBreak: root.dataset.stateBreak === 'true',
    hasCompany: root.dataset.stateCompany === 'true',
    startedAtMs: root.dataset.startTimestamp ? Date.parse(root.dataset.startTimestamp) : null,
    breakStartedAtMs: root.dataset.breakTimestamp ? Date.parse(root.dataset.breakTimestamp) : null,
    totalBreakMs: Number(root.dataset.totalBreakMinutes || '0') * 60000,
    startLabel: root.dataset.startLabel || '',
    breakLabel: root.dataset.breakLabel || '',
    breakTotalLabel: root.dataset.breakTotalLabel || '0:00',
    companyName: root.dataset.companyName || '',
    workedLabel: root.dataset.workedLabel || '0:00',
    pendingPunchSync: false,
  };
  const stored = loadStoredMobileState();
  if (stored && stored.version >= 1 && (!navigator.onLine || stored.pendingPunchSync)) {
    mobileState = { ...mobileState, ...stored };
  }
  if (!mobileState.isWorking && !mobileState.onBreak && !mobileState.hasCompany) {
    clearStoredMobileState();
  }
  updateUiState();
}

function determineCompanyName(form, payload) {
  const typed = (payload.new_company_name || '').trim();
  if (typed) return typed;
  const select = form.querySelector('select[name="company_id"]');
  if (!select || !(select instanceof HTMLSelectElement)) return '';
  return select.options[select.selectedIndex]?.textContent?.trim() || '';
}

function setWorkingState(startMs, { hasCompany = false, companyName = '', resetBreak = true } = {}) {
  if (!mobileState) return;
  if (startMs) {
    mobileState.isWorking = true;
    mobileState.startedAtMs = startMs;
    mobileState.startLabel = formatTime(startMs);
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

function applyOfflinePunchAction(action, payload, form) {
  if (!mobileState) return;
  mobileState.pendingPunchSync = true;
  const now = Date.now();
  if (action === 'start_work') {
    setWorkingState(now, { hasCompany: false, companyName: '', resetBreak: true });
  } else if (action === 'end_work') {
    setWorkingState(null);
  } else if (action === 'start_break' && mobileState.isWorking && !mobileState.onBreak) {
    mobileState.onBreak = true;
    mobileState.breakStartedAtMs = now;
    mobileState.breakLabel = formatTime(now);
    updateUiState();
  } else if (action === 'end_break' && mobileState.isWorking && mobileState.onBreak) {
    const diff = mobileState.breakStartedAtMs ? Math.max(0, now - mobileState.breakStartedAtMs) : 0;
    mobileState.totalBreakMs += diff;
    mobileState.breakTotalLabel = formatDuration(mobileState.totalBreakMs);
    mobileState.onBreak = false;
    mobileState.breakStartedAtMs = null;
    mobileState.breakLabel = '';
    updateUiState();
  } else if (action === 'start_company') {
    setWorkingState(now, { hasCompany: true, companyName: determineCompanyName(form, payload), resetBreak: true });
    modalController?.close?.();
  } else if (action === 'end_company') {
    setWorkingState(now, { hasCompany: false, companyName: '', resetBreak: true });
  }
}

function appendVacationPreview(payload, offline = false) {
  const list = document.querySelector(VACATION_LIST_SELECTOR);
  const empty = document.querySelector(VACATION_EMPTY_SELECTOR);
  if (!list) return;
  setElementHidden(list, false);
  if (empty) setElementHidden(empty, true);
  const item = document.createElement('li');
  item.className = 'mobile-vacation';
  const head = document.createElement('header');
  head.className = 'mobile-vacation__header';
  const title = document.createElement('strong');
  title.textContent = `${payload.start_date} – ${payload.end_date}`;
  const status = document.createElement('span');
  status.className = `mobile-vacation__status mobile-vacation__status--${offline ? 'offline' : 'pending'}`;
  status.textContent = offline ? 'Offline gespeichert' : 'Wartet auf Freigabe';
  head.append(title, status);
  item.appendChild(head);
  if (offline) {
    const badge = document.createElement('span');
    badge.className = 'mobile-vacation__badge';
    badge.textContent = 'Synchronisation ausstehend';
    item.appendChild(badge);
  }
  list.prepend(item);
}

async function queueAction(type, payload) {
  const clientActionId = payload.client_action_id || generateClientActionId(type);
  payload.client_action_id = clientActionId;
  await putRecord(ACTION_STORE, {
    clientActionId,
    type,
    endpoint: type === 'vacation' ? '/vacations' : '/punch',
    payload,
    createdAt: Date.now(),
  });
  return clientActionId;
}

async function readPendingActions() {
  const all = await getAllRecords(ACTION_STORE);
  return all.sort((a, b) => (a.createdAt || 0) - (b.createdAt || 0));
}

async function refreshQueueIndicator() {
  const actions = await readPendingActions();
  const punchCount = actions.filter((item) => item.type === 'punch').length;
  const vacationCount = actions.filter((item) => item.type === 'vacation').length;
  const total = actions.length;
  const detail = [punchCount ? `${punchCount} Stempel` : '', vacationCount ? `${vacationCount} Urlaub` : ''].filter(Boolean).join(' · ');
  updatePendingIndicator(total, detail);
  return { total, punchCount, vacationCount };
}

async function postAction(action) {
  const body = new URLSearchParams(action.payload);
  const response = await fetch(action.endpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8' },
    body: body.toString(),
    credentials: 'same-origin',
    redirect: 'follow',
  });
  if (!response.ok) throw new Error(`Serverfehler ${response.status}`);
  return response;
}

async function flushOfflineQueue(trigger = 'auto') {
  const pending = await readPendingActions();
  if (!pending.length) {
    dispatchSyncStatus('Keine ausstehenden Offline-Aktionen.', 'synced');
    await refreshQueueIndicator();
    return;
  }
  dispatchSyncStatus('Synchronisation läuft …', 'syncing');
  let processed = 0;
  for (const action of pending) {
    try {
      await postAction(action);
      await deleteRecord(ACTION_STORE, action.clientActionId);
      processed += 1;
    } catch (error) {
      console.warn('Synchronisation gestoppt', error);
      break;
    }
  }
  const counts = await refreshQueueIndicator();
  if (counts.total === 0) {
    if (mobileState) {
      mobileState.pendingPunchSync = false;
      persistMobileState();
    }
    dispatchSyncStatus('Synchronisation erfolgreich. Alle Offline-Aktionen übertragen.', 'synced');
    showFeedback('Synchronisation erfolgreich abgeschlossen.', 'success');
  } else if (processed > 0) {
    dispatchSyncStatus('Synchronisation teilweise abgeschlossen. Verbleibende Aktionen werden erneut versucht.', 'queue');
    showFeedback('Teilweise synchronisiert – Rest folgt automatisch.', 'info');
  } else {
    dispatchSyncStatus('Server aktuell nicht erreichbar. Offline-Aktionen bleiben sicher gespeichert.', 'offline');
    if (trigger !== 'auto') showFeedback('Der Server ist nicht erreichbar. Wir versuchen es automatisch erneut.', 'error');
  }
}

async function syncServerData() {
  if (!navigator.onLine) return false;
  try {
    const response = await fetch('/mobile/sync-data', { credentials: 'same-origin' });
    if (!response.ok) throw new Error(`Sync-HTTP ${response.status}`);
    const payload = await response.json();
    await putRecord(DATA_STORE, { key: 'snapshot', data: payload, savedAt: Date.now() });
    await putRecord(META_STORE, { key: 'lastSyncAt', value: new Date().toISOString() });
    await putRecord(META_STORE, { key: 'localDataReady', value: true });
    updateLastSyncLabel(new Date().toISOString());
    updateLocalDataBadge(true);
    dispatchSyncStatus('Server erreichbar. Daten wurden aktualisiert.', 'synced');
    await hydrateCompaniesFromCache();
    return true;
  } catch (error) {
    console.warn('Datenabgleich fehlgeschlagen', error);
    return false;
  }
}

async function hydrateCompaniesFromCache() {
  const snapshotRecord = await getRecord(DATA_STORE, 'snapshot');
  const companies = snapshotRecord?.data?.companies;
  if (!Array.isArray(companies)) return;
  const selects = Array.from(document.querySelectorAll('select[name="company_id"]'));
  selects.forEach((select) => {
    if (!(select instanceof HTMLSelectElement)) return;
    const currentValue = select.value;
    const defaultOption = select.querySelector('option[value=""]');
    select.innerHTML = '';
    if (defaultOption) {
      select.appendChild(defaultOption);
    } else {
      const option = document.createElement('option');
      option.value = '';
      option.textContent = 'Firma auswählen';
      select.appendChild(option);
    }
    companies.forEach((company) => {
      const option = document.createElement('option');
      option.value = String(company.id);
      option.textContent = company.name;
      if (String(company.id) === String(currentValue)) option.selected = true;
      select.appendChild(option);
    });
  });
}

async function initializeSyncMeta() {
  const syncMeta = await getRecord(META_STORE, 'lastSyncAt');
  const dataMeta = await getRecord(META_STORE, 'localDataReady');
  updateLastSyncLabel(syncMeta?.value || null);
  updateLocalDataBadge(!!dataMeta?.value);
  await refreshQueueIndicator();
}

async function processPunchSubmission(form, payload) {
  payload.client_action_id = payload.client_action_id || generateClientActionId('punch');
  const body = new URLSearchParams(payload);
  if (navigator.onLine) {
    try {
      const response = await fetch(form.getAttribute('action') || '/punch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8' },
        body: body.toString(),
        credentials: 'same-origin',
        redirect: 'follow',
      });
      if (!response.ok) throw new Error(`Serverfehler ${response.status}`);
      if (response.redirected) {
        window.location.href = response.url;
        return;
      }
      showFeedback('Buchung erfolgreich übertragen.', 'success');
      dispatchSyncStatus('Buchung wurde an den Server übertragen.', 'synced');
      return;
    } catch {
      // fallback queue
    }
  }

  await queueAction('punch', payload);
  applyOfflinePunchAction(payload.action, payload, form);
  await refreshQueueIndicator();
  showFeedback('Offline-Aktion lokal gespeichert. Synchronisation folgt automatisch.', 'info');
  dispatchSyncStatus('Offline – Stempelaktion sicher gespeichert.', 'queue');
}

async function processVacationSubmission(form, payload) {
  payload.client_action_id = payload.client_action_id || generateClientActionId('vacation');
  const body = new URLSearchParams(payload);
  if (navigator.onLine) {
    try {
      const response = await fetch(form.getAttribute('action') || '/vacations', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8' },
        body: body.toString(),
        credentials: 'same-origin',
        redirect: 'follow',
      });
      if (!response.ok) throw new Error(`Serverfehler ${response.status}`);
      showFeedback('Urlaubsantrag erfolgreich übertragen.', 'success');
      return;
    } catch {
      // fallback queue
    }
  }
  await queueAction('vacation', payload);
  appendVacationPreview(payload, true);
  await refreshQueueIndicator();
  showFeedback('Urlaubsantrag offline gespeichert. Wird bei Verbindung übertragen.', 'info');
  dispatchSyncStatus('Offline – Urlaubsantrag sicher gespeichert.', 'queue');
}

async function handleOfflineSubmission(event) {
  event.preventDefault();
  const form = event.target;
  const payload = serializeFormData(form);
  if (form.dataset.offline === 'vacation') {
    await processVacationSubmission(form, payload);
  } else {
    await processPunchSubmission(form, payload);
  }
  form.reset();
}

function registerTabHandling() {
  const tabs = Array.from(document.querySelectorAll(TAB_SELECTOR));
  const panels = Array.from(document.querySelectorAll(PANEL_SELECTOR));
  const defaultTab = tabs.find((item) => item.classList.contains('is-active'))?.dataset.tab || 'buchung';
  const valid = new Set(tabs.map((item) => item.dataset.tab));

  const activate = (tabName, updateHistory = true) => {
    const current = valid.has(tabName) ? tabName : defaultTab;
    tabs.forEach((tab) => {
      const active = tab.dataset.tab === current;
      tab.classList.toggle('is-active', active);
      tab.setAttribute('aria-selected', active ? 'true' : 'false');
    });
    panels.forEach((panel) => {
      const active = panel.dataset.tabPanel === current;
      panel.classList.toggle('is-active', active);
      setElementHidden(panel, !active);
      panel.setAttribute('aria-hidden', active ? 'false' : 'true');
    });
    if (updateHistory && history.replaceState) {
      const url = new URL(window.location.href);
      url.searchParams.set('tab', current);
      url.hash = `#${current}`;
      history.replaceState(null, '', `${url.pathname}${url.search}${url.hash}`);
    }
  };

  tabs.forEach((tab) => tab.addEventListener('click', (event) => {
    event.preventDefault();
    activate(tab.dataset.tab || defaultTab);
  }));
  window.addEventListener('hashchange', () => activate(window.location.hash.replace('#', ''), false));
  activate(window.location.hash.replace('#', ''), false);
}

function registerModalHandling() {
  const modal = document.getElementById(MODAL_ID);
  if (!modal) return;
  const setVisible = (visible) => {
    modal.classList.toggle('is-visible', visible);
    modal.setAttribute('aria-hidden', visible ? 'false' : 'true');
    document.body.classList.toggle('modal-open', visible);
  };
  modalController = { open: () => setVisible(true), close: () => setVisible(false) };
  document.querySelectorAll(`[data-open="${MODAL_ID}"]`).forEach((el) => el.addEventListener('click', () => setVisible(true)));
  modal.querySelectorAll('[data-close]').forEach((el) => el.addEventListener('click', () => setVisible(false)));
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && modal.classList.contains('is-visible')) setVisible(false);
  });
}

function registerOfflineForms() {
  document.querySelectorAll(FORM_SELECTOR).forEach((form) => form.addEventListener('submit', handleOfflineSubmission));
}

function handleNetworkStatus() {
  const online = navigator.onLine;
  setStatusBadge(online);
  if (online) {
    dispatchSyncStatus('Server erreichbar. Synchronisation wird ausgeführt.', 'online');
    syncServerData();
    flushOfflineQueue('network-online');
  } else {
    dispatchSyncStatus('Keine Verbindung. Du arbeitest offline, Eingaben werden lokal gespeichert.', 'offline');
  }
}

function setupConnectionHandlers() {
  window.addEventListener('online', handleNetworkStatus);
  window.addEventListener('offline', handleNetworkStatus);
}

window.addEventListener('DOMContentLoaded', async () => {
  registerTabHandling();
  registerModalHandling();
  initializeMobileState();
  registerOfflineForms();
  setupConnectionHandlers();
  await initializeSyncMeta();
  await hydrateCompaniesFromCache();
  setStatusBadge(navigator.onLine);
  if (navigator.onLine) {
    const synced = await syncServerData();
    if (synced) {
      showFeedback(`Lokale Daten der letzten ${Math.round(MONTH_WINDOW_DAYS / 30)} Monate aktualisiert.`, 'success');
    }
    await flushOfflineQueue('app-start');
  } else {
    dispatchSyncStatus('Offline-Modus aktiv. Lokale Daten werden verwendet.', 'offline');
  }
});
