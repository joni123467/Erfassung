const TAB_SELECTOR = '.mobile-tab';
const PANEL_SELECTOR = '[data-tab-panel]';
const MODAL_ID = 'mobile-order-modal';
const FORM_SELECTOR = 'form[data-offline]';
const FEEDBACK_ID = 'mobile-feedback';
const MOBILE_STATE_SELECTOR = '[data-mobile-state]';
const VACATION_LIST_SELECTOR = '[data-vacation-list]';
const VACATION_EMPTY_SELECTOR = '[data-vacation-empty]';

const DB_NAME = 'erfassung-mobile';
const DB_VERSION = 4;
const ACTION_STORE = 'pendingActions';
const DATA_STORE = 'mobileData';
const META_STORE = 'meta';
const MOBILE_STATE_STORAGE_KEY = 'erfassungMobileState';
const SERVER_REACHABILITY_KEY = 'serverReachability';
const SYNC_LOCK_KEY = 'syncLock';
const SETTINGS_DEFAULT = { cacheDurationHours: 24 };

const supportsIndexedDb = typeof indexedDB !== 'undefined';
let localStorageUnavailable = false;
let mobileState = null;
let workDurationTimerId = null;
let modalController = null;
let syncInFlight = false;
let initialServerState = null;

function setElementHidden(element, hidden) {
  if (!element) return;
  element.hidden = !!hidden;
  if (hidden) element.setAttribute('hidden', 'hidden');
  else element.removeAttribute('hidden');
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

function setStatusBadge(state) {
  const badge = document.getElementById('mobile-server-badge');
  if (!badge) return;
  const labels = {
    online: 'Server erreichbar',
    offline: 'Offline',
    unreachable: 'Server nicht erreichbar',
    syncing: 'Synchronisiert …',
  };
  badge.textContent = labels[state] || labels.offline;
  badge.dataset.state = state;
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

function getCsrfToken() {
  const meta = document.querySelector('meta[name="csrf-token"]');
  const token = meta ? meta.getAttribute('content') || '' : '';
  if (token) {
    // Cache in localStorage so the static offline shell can use it too
    try { window.localStorage.setItem('erfassung_csrf_token', token); } catch {}
    return token;
  }
  // Fallback: use the token cached from the last online page load
  try { return window.localStorage.getItem('erfassung_csrf_token') || ''; } catch {}
  return '';
}

function fetchWithTimeout(url, options = {}, timeoutMs = 3500) {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);
  return fetch(url, { ...options, signal: controller.signal }).finally(() => window.clearTimeout(timeoutId));
}

function normalizeBreakLabel(minutes) {
  const value = Number(minutes || 0);
  const safe = Number.isFinite(value) ? value : 0;
  const hours = Math.floor(safe / 60);
  const remainder = Math.abs(Math.round(safe % 60));
  return `${hours}:${String(remainder).padStart(2, '0')}`;
}

function buildStateFromEntry(entry) {
  if (!entry) {
    return {
      isWorking: false,
      onBreak: false,
      hasCompany: false,
      startedAtMs: null,
      breakStartedAtMs: null,
      totalBreakMs: 0,
      startLabel: '',
      breakLabel: '',
      breakTotalLabel: '0:00',
      companyName: '',
      workedLabel: '0:00',
      pendingPunchSync: false,
    };
  }
  const startIso = `${entry.work_date}T${entry.start_time}`;
  const breakIso = entry.break_started_at ? `${entry.work_date}T${entry.break_started_at}` : null;
  const startedAtMs = Date.parse(startIso);
  const breakStartedAtMs = breakIso ? Date.parse(breakIso) : null;
  const breakMinutes = Number(entry.total_break_minutes || entry.break_minutes || 0);

  return {
    isWorking: !!entry.is_open,
    onBreak: !!entry.break_started_at,
    hasCompany: !!entry.company_id,
    startedAtMs: Number.isNaN(startedAtMs) ? null : startedAtMs,
    breakStartedAtMs: Number.isNaN(breakStartedAtMs) ? null : breakStartedAtMs,
    totalBreakMs: Math.max(0, breakMinutes * 60000),
    startLabel: entry.start_time ? entry.start_time.slice(0, 5) : '',
    breakLabel: entry.break_started_at ? entry.break_started_at.slice(0, 5) : '',
    breakTotalLabel: normalizeBreakLabel(breakMinutes),
    companyName: entry.company_name || '',
    workedLabel: normalizeBreakLabel(entry.worked_minutes || 0),
    pendingPunchSync: false,
  };
}

function cloneState(state) {
  return {
    isWorking: !!state.isWorking,
    onBreak: !!state.onBreak,
    hasCompany: !!state.hasCompany,
    startedAtMs: state.startedAtMs || null,
    breakStartedAtMs: state.breakStartedAtMs || null,
    totalBreakMs: Number(state.totalBreakMs || 0),
    startLabel: state.startLabel || '',
    breakLabel: state.breakLabel || '',
    breakTotalLabel: state.breakTotalLabel || '0:00',
    companyName: state.companyName || '',
    workedLabel: state.workedLabel || '0:00',
    pendingPunchSync: !!state.pendingPunchSync,
  };
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

function validatePunchActionAgainstState(state, action, payload = {}) {
  const isWorking = !!state?.isWorking;
  const onBreak = !!state?.onBreak;
  const hasCompany = !!state?.hasCompany;

  if (action === 'start_work') {
    if (isWorking) return { allowed: false, duplicate: true, reason: 'Arbeitszeit läuft bereits' };
    return { allowed: true };
  }
  if (action === 'start_company') {
    const requestedName = ((payload.new_company_name || payload.company_name || '') + '').trim();
    const currentName = ((state?.companyName || '') + '').trim();
    if (isWorking && hasCompany && requestedName && currentName && requestedName === currentName) {
      return { allowed: false, duplicate: true, reason: 'Auftrag läuft bereits' };
    }
    return { allowed: true };
  }
  if (action === 'end_work') {
    if (!isWorking) return { allowed: false, duplicate: true, reason: 'Keine laufende Arbeitszeit' };
    return { allowed: true };
  }
  if (action === 'start_break') {
    if (!isWorking || onBreak) return { allowed: false, duplicate: true, reason: 'Pause kann nicht gestartet werden' };
    return { allowed: true };
  }
  if (action === 'end_break') {
    if (!isWorking || !onBreak) return { allowed: false, duplicate: true, reason: 'Keine laufende Pause' };
    return { allowed: true };
  }
  if (action === 'end_company') {
    if (!isWorking || !hasCompany) return { allowed: false, duplicate: true, reason: 'Kein laufender Auftrag' };
    return { allowed: true };
  }
  return { allowed: true };
}

function applyPunchActionToState(state, action, payload = {}) {
  const next = cloneState(state);
  const now = Date.now();
  if (action === 'start_work') {
    next.isWorking = true;
    next.onBreak = false;
    next.hasCompany = false;
    next.startedAtMs = now;
    next.breakStartedAtMs = null;
    next.totalBreakMs = 0;
    next.startLabel = formatTime(now);
    next.breakLabel = '';
    next.breakTotalLabel = '0:00';
    next.companyName = '';
  } else if (action === 'end_work') {
    return buildStateFromEntry(null);
  } else if (action === 'start_break' && next.isWorking && !next.onBreak) {
    next.onBreak = true;
    next.breakStartedAtMs = now;
    next.breakLabel = formatTime(now);
  } else if (action === 'end_break' && next.isWorking && next.onBreak) {
    if (next.breakStartedAtMs) {
      next.totalBreakMs += Math.max(0, now - next.breakStartedAtMs);
    }
    next.onBreak = false;
    next.breakStartedAtMs = null;
    next.breakLabel = '';
    next.breakTotalLabel = formatDuration(next.totalBreakMs);
  } else if (action === 'start_company') {
    next.isWorking = true;
    next.onBreak = false;
    next.hasCompany = true;
    next.startedAtMs = now;
    next.startLabel = formatTime(now);
    next.breakStartedAtMs = null;
    next.totalBreakMs = 0;
    next.breakLabel = '';
    next.breakTotalLabel = '0:00';
    next.companyName = (payload.new_company_name || '').trim() || payload.company_name || '';
  } else if (action === 'end_company') {
    next.isWorking = true;
    next.onBreak = false;
    next.hasCompany = false;
    next.startedAtMs = now;
    next.startLabel = formatTime(now);
    next.breakStartedAtMs = null;
    next.totalBreakMs = 0;
    next.breakLabel = '';
    next.breakTotalLabel = '0:00';
    next.companyName = '';
  }
  return next;
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
    storage.setItem(MOBILE_STATE_STORAGE_KEY, JSON.stringify({ ...mobileState, version: 3, updatedAt: Date.now() }));
    return null;
  });
}

function clearStoredMobileState() {
  withLocalStorage((storage) => {
    storage.removeItem(MOBILE_STATE_STORAGE_KEY);
    return null;
  });
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

function serializeFormData(form) {
  const payload = {};
  for (const [key, value] of new FormData(form).entries()) {
    payload[key] = typeof value === 'string' ? value : '';
  }
  return payload;
}

function generateClientActionId(prefix) {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
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
  const detail = [punchCount ? `${punchCount} Stempel` : '', vacationCount ? `${vacationCount} Urlaub` : '']
    .filter(Boolean)
    .join(' · ');
  updatePendingIndicator(total, detail);
  return { total, punchCount, vacationCount };
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
    if (mobileState.onBreak && mobileState.breakStartedAtMs) {
      total -= Date.now() - mobileState.breakStartedAtMs;
    }
    mobileState.workedLabel = formatDuration(total);
  }
  const worked = document.querySelector('[data-field="worked-duration"]');
  if (worked) worked.textContent = mobileState.workedLabel;
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

  const values = {
    'header-start': mobileState.isWorking ? mobileState.startLabel || '--:--' : '',
    'work-start': mobileState.isWorking ? mobileState.startLabel || '--:--' : '',
    'company-name': mobileState.companyName || '',
    'break-start': mobileState.onBreak ? mobileState.breakLabel || '--:--' : '',
    'break-total': mobileState.breakTotalLabel || '0:00',
    'booking-mode': mobileState.hasCompany ? 'Auftrag läuft' : 'Nur Arbeitszeit',
  };
  Object.entries(values).forEach(([key, value]) => {
    const element = document.querySelector(`[data-field="${key}"]`);
    if (element) element.textContent = value;
  });

  refreshControlStates();
  startWorkTimer();
  persistMobileState();
}

function determineCompanyName(form, payload) {
  const typed = (payload.new_company_name || '').trim();
  if (typed) return typed;
  const select = form.querySelector('select[name="company_id"]');
  if (!(select instanceof HTMLSelectElement)) return '';
  return select.options[select.selectedIndex]?.textContent?.trim() || '';
}

async function recomputeEffectiveState() {
  const snapshot = await getRecord(DATA_STORE, 'snapshot');
  const pending = await readPendingActions();

  let base = initialServerState ? cloneState(initialServerState) : buildStateFromEntry(snapshot?.data?.active_entry || null);
  if (!snapshot?.data?.active_entry && !initialServerState) {
    const stored = loadStoredMobileState();
    if (stored && stored.version >= 1) {
      base = cloneState(stored);
    }
  }

  for (const action of pending) {
    if (action.type !== 'punch') continue;
    const payload = action.payload || {};
    if (payload.action === 'start_company' && !payload.company_name) {
      payload.company_name = determineCompanyName(document, payload);
    }
    base = applyPunchActionToState(base, payload.action, payload);
    base.pendingPunchSync = true;
  }

  if (!pending.some((entry) => entry.type === 'punch')) {
    base.pendingPunchSync = false;
  }

  mobileState = base;
  updateUiState();
}

async function appendVacationPreview(payload, offline = false) {
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

async function checkServerReachability(force = false) {
  if (!navigator.onLine) {
    await putRecord(META_STORE, { key: SERVER_REACHABILITY_KEY, value: 'offline', updatedAt: Date.now() });
    setStatusBadge('offline');
    return 'offline';
  }

  const last = await getRecord(META_STORE, SERVER_REACHABILITY_KEY);
  if (!force && last?.value === 'online' && Date.now() - (last.updatedAt || 0) < 15000) {
    setStatusBadge('online');
    return 'online';
  }

  try {
    const response = await fetchWithTimeout('/api/ping', {
      method: 'GET',
      credentials: 'same-origin',
      cache: 'no-store',
      headers: { Accept: 'application/json' },
    }, 2500);
    if (!response.ok) {
      throw new Error(`Ping ${response.status}`);
    }
    await putRecord(META_STORE, { key: SERVER_REACHABILITY_KEY, value: 'online', updatedAt: Date.now() });
    setStatusBadge('online');
    return 'online';
  } catch (error) {
    await putRecord(META_STORE, { key: SERVER_REACHABILITY_KEY, value: 'unreachable', updatedAt: Date.now() });
    setStatusBadge('unreachable');
    return 'unreachable';
  }
}

async function hydrateCompaniesFromCache() {
  const snapshot = await getRecord(DATA_STORE, 'snapshot');
  const companies = snapshot?.data?.companies;
  if (!Array.isArray(companies) || companies.length === 0) return;

  const selects = document.querySelectorAll('select[name="company_id"]');
  selects.forEach((select) => {
    if (!(select instanceof HTMLSelectElement)) return;
    const selected = select.value;
    const empty = document.createElement('option');
    empty.value = '';
    empty.textContent = 'Firma auswählen';
    select.innerHTML = '';
    select.appendChild(empty);
    companies.forEach((company) => {
      const option = document.createElement('option');
      option.value = String(company.id);
      option.textContent = company.name;
      if (String(company.id) === String(selected)) option.selected = true;
      select.appendChild(option);
    });
  });
}

async function syncServerData() {
  const status = await checkServerReachability(true);
  if (status !== 'online') {
    return false;
  }
  try {
    const response = await fetchWithTimeout('/mobile/sync-data', {
      method: 'GET',
      credentials: 'same-origin',
      cache: 'no-store',
    }, 5000);
    if (!response.ok) throw new Error(`Sync HTTP ${response.status}`);
    const payload = await response.json();
    await putRecord(DATA_STORE, { key: 'snapshot', data: payload, savedAt: Date.now() });
    await putRecord(META_STORE, { key: 'lastSyncAt', value: new Date().toISOString(), updatedAt: Date.now() });
    await putRecord(META_STORE, { key: 'localDataReady', value: true, updatedAt: Date.now() });
    updateLocalDataBadge(true);
    updateLastSyncLabel(new Date().toISOString());
    await hydrateCompaniesFromCache();
    return true;
  } catch (error) {
    return false;
  }
}

async function postQueuedAction(entry) {
  const body = new URLSearchParams(entry.payload);
  body.set('csrf_token', getCsrfToken());
  const response = await fetchWithTimeout(entry.endpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8' },
    body: body.toString(),
    credentials: 'same-origin',
    redirect: 'follow',
    cache: 'no-store',
  }, 8000);
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  return response;
}

async function flushOfflineQueue() {
  const pending = await readPendingActions();
  if (!pending.length) {
    return { processed: 0, failed: 0, skipped: 0 };
  }

  dispatchSyncStatus('Synchronisation läuft …', 'syncing');
  setStatusBadge('syncing');

  const snapshot = await getRecord(DATA_STORE, 'snapshot');
  let projectedState = buildStateFromEntry(snapshot?.data?.active_entry || null);
  let processed = 0;
  let skipped = 0;

  for (const entry of pending) {
    if (entry.type === 'punch') {
      const action = entry.payload?.action;
      const validation = validatePunchActionAgainstState(projectedState, action, entry.payload || {});
      if (!validation.allowed) {
        await deleteRecord(ACTION_STORE, entry.clientActionId);
        skipped += 1;
        continue;
      }
    }

    try {
      await postQueuedAction(entry);
      await deleteRecord(ACTION_STORE, entry.clientActionId);
      if (entry.type === 'punch') {
        projectedState = applyPunchActionToState(projectedState, entry.payload?.action, entry.payload || {});
      }
      processed += 1;
    } catch (error) {
      break;
    }
  }

  const remaining = await refreshQueueIndicator();
  if (remaining.total === 0) {
    dispatchSyncStatus('Synchronisation erfolgreich. Alle Aktionen wurden übertragen.', 'synced');
    showFeedback('Synchronisation erfolgreich.', 'success');
    return { processed, failed: 0, skipped };
  }
  if (processed > 0 || skipped > 0) {
    dispatchSyncStatus('Synchronisation teilweise erfolgreich. Verbleibende Aktionen folgen automatisch.', 'queue');
    showFeedback('Teilweise synchronisiert. Rest wird erneut versucht.', 'info');
    return { processed, failed: remaining.total, skipped };
  }
  dispatchSyncStatus('Server aktuell nicht erreichbar. Aktionen bleiben sicher lokal gespeichert.', 'unreachable');
  return { processed: 0, failed: remaining.total, skipped };
}

async function performReconnectSync(trigger = 'auto') {
  if (syncInFlight) return;
  syncInFlight = true;
  await putRecord(META_STORE, { key: SYNC_LOCK_KEY, value: true, updatedAt: Date.now() });
  try {
    const status = await checkServerReachability(true);
    if (status !== 'online') {
      if (status === 'unreachable') {
        dispatchSyncStatus('Internet vorhanden, aber Server nicht erreichbar.', 'unreachable');
      } else {
        dispatchSyncStatus('Keine Verbindung. Du arbeitest offline.', 'offline');
      }
      await recomputeEffectiveState();
      return;
    }

    await syncServerData();
    await recomputeEffectiveState();
    await flushOfflineQueue();
    await syncServerData();
    await recomputeEffectiveState();
    await refreshQueueIndicator();

    if (trigger !== 'background') {
      dispatchSyncStatus('Server wieder erreichbar. Daten sind synchronisiert.', 'synced');
    }
  } finally {
    await putRecord(META_STORE, { key: SYNC_LOCK_KEY, value: false, updatedAt: Date.now() });
    syncInFlight = false;
    await checkServerReachability();
  }
}

async function processPunchSubmission(form, payload) {
  payload.client_action_id = payload.client_action_id || generateClientActionId('punch');
  if (payload.action === 'start_company') {
    payload.company_name = determineCompanyName(form, payload);
  }

  await recomputeEffectiveState();
  const validation = validatePunchActionAgainstState(mobileState || buildStateFromEntry(null), payload.action, payload);
  if (!validation.allowed) {
    showFeedback(`Aktion übersprungen: ${validation.reason}.`, 'info');
    dispatchSyncStatus('Aktion war bereits berücksichtigt und wurde nicht erneut gespeichert.', 'queue');
    return;
  }

  const reachability = await checkServerReachability();
  if (reachability !== 'online') {
    await queueAction('punch', payload);
    await recomputeEffectiveState();
    await refreshQueueIndicator();
    showFeedback('Offline-Aktion lokal gespeichert. Wird automatisch synchronisiert.', 'info');
    dispatchSyncStatus('Offline gespeichert – Stempelung wurde lokal erfasst.', 'queue');
    return;
  }

  try {
    const punchParams = new URLSearchParams(payload);
    punchParams.set('csrf_token', getCsrfToken());
    const response = await fetchWithTimeout(form.getAttribute('action') || '/punch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8' },
      body: punchParams.toString(),
      credentials: 'same-origin',
      redirect: 'follow',
      cache: 'no-store',
    }, 5000);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    if (response.redirected) {
      window.location.href = response.url;
      return;
    }
    showFeedback('Buchung erfolgreich übertragen.', 'success');
    dispatchSyncStatus('Buchung wurde an den Server übertragen.', 'synced');
    await syncServerData();
    await recomputeEffectiveState();
  } catch (error) {
    await putRecord(META_STORE, { key: SERVER_REACHABILITY_KEY, value: 'unreachable', updatedAt: Date.now() });
    setStatusBadge('unreachable');
    await queueAction('punch', payload);
    await recomputeEffectiveState();
    await refreshQueueIndicator();
    showFeedback('Server nicht erreichbar. Aktion wurde lokal gespeichert.', 'info');
    dispatchSyncStatus('Server nicht erreichbar – Aktion lokal gespeichert.', 'unreachable');
  }
}

async function processVacationSubmission(form, payload) {
  payload.client_action_id = payload.client_action_id || generateClientActionId('vacation');
  const reachability = await checkServerReachability();
  if (reachability !== 'online') {
    await queueAction('vacation', payload);
    await appendVacationPreview(payload, true);
    await refreshQueueIndicator();
    showFeedback('Urlaubsantrag offline gespeichert.', 'info');
    dispatchSyncStatus('Offline gespeichert – Urlaubsantrag wartet auf Synchronisation.', 'queue');
    return;
  }

  try {
    const vacationParams = new URLSearchParams(payload);
    vacationParams.set('csrf_token', getCsrfToken());
    const response = await fetchWithTimeout(form.getAttribute('action') || '/vacations', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8' },
      body: vacationParams.toString(),
      credentials: 'same-origin',
      redirect: 'follow',
      cache: 'no-store',
    }, 5000);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    showFeedback('Urlaubsantrag erfolgreich übertragen.', 'success');
    await syncServerData();
  } catch (error) {
    await putRecord(META_STORE, { key: SERVER_REACHABILITY_KEY, value: 'unreachable', updatedAt: Date.now() });
    setStatusBadge('unreachable');
    await queueAction('vacation', payload);
    await appendVacationPreview(payload, true);
    await refreshQueueIndicator();
    showFeedback('Server nicht erreichbar. Antrag lokal gespeichert.', 'info');
    dispatchSyncStatus('Server nicht erreichbar – Antrag lokal gespeichert.', 'unreachable');
  }
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
  if (!tabs.length || !panels.length) return;
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
  const openers = Array.from(document.querySelectorAll(`[data-open="${MODAL_ID}"]`));
  const closers = Array.from(modal.querySelectorAll('[data-close]'));

  const setVisible = (visible) => {
    modal.classList.toggle('is-visible', visible);
    modal.setAttribute('aria-hidden', visible ? 'false' : 'true');
    document.body.classList.toggle('modal-open', visible);
    if (visible) {
      const firstInput = modal.querySelector('select, input, button');
      if (firstInput instanceof HTMLElement) {
        firstInput.focus();
      }
    }
  };

  modalController = { open: () => setVisible(true), close: () => setVisible(false) };

  openers.forEach((opener) => {
    opener.addEventListener('click', (event) => {
      event.preventDefault();
      setVisible(true);
    });
  });

  closers.forEach((closer) => {
    closer.addEventListener('click', (event) => {
      event.preventDefault();
      setVisible(false);
    });
  });

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && modal.classList.contains('is-visible')) setVisible(false);
  });
}

function registerCompanySearch() {
  const searchInputs = document.querySelectorAll('[data-company-search-target]');
  searchInputs.forEach((input) => {
    if (!(input instanceof HTMLInputElement)) return;
    const targetId = input.dataset.companySearchTarget || '';
    if (!targetId) return;
    const select = document.getElementById(targetId);
    if (!(select instanceof HTMLSelectElement)) return;

    const update = () => {
      const query = (input.value || '').trim().toLocaleLowerCase('de-DE');
      let visibleCount = 0;
      Array.from(select.options).forEach((option, index) => {
        if (index === 0) {
          option.hidden = false;
          return;
        }
        const label = (option.textContent || '').toLocaleLowerCase('de-DE');
        const visible = !query || label.includes(query);
        option.hidden = !visible;
        if (visible) visibleCount += 1;
      });

      let hint = input.parentElement?.querySelector('.company-search-empty');
      if (!hint) {
        hint = document.createElement('small');
        hint.className = 'company-search-empty';
        input.parentElement?.appendChild(hint);
      }
      hint.textContent = visibleCount === 0 && query ? 'Keine passende Firma gefunden. Du kannst unten eine neue Firma anlegen.' : '';
      hint.hidden = !hint.textContent;

      const selected = select.options[select.selectedIndex];
      if (selected && selected.hidden) {
        select.value = '';
      }
    };

    input.addEventListener('input', update);
    update();
  });
}

function registerOfflineForms() {
  document.querySelectorAll(FORM_SELECTOR).forEach((form) => form.addEventListener('submit', handleOfflineSubmission));
}

function initializeServerStateFromDataset() {
  const root = document.querySelector(MOBILE_STATE_SELECTOR);
  if (!root) {
    initialServerState = buildStateFromEntry(null);
    mobileState = buildStateFromEntry(null);
    return;
  }

  const data = root.dataset;
  const entry = data.stateRunning === 'true' ? {
    work_date: data.startTimestamp ? data.startTimestamp.slice(0, 10) : new Date().toISOString().slice(0, 10),
    start_time: data.startLabel ? `${data.startLabel}:00` : '00:00:00',
    break_started_at: data.stateBreak === 'true' && data.breakLabel ? `${data.breakLabel}:00` : null,
    company_id: data.stateCompany === 'true' ? 1 : null,
    company_name: data.companyName || '',
    is_open: true,
    total_break_minutes: Number(data.totalBreakMinutes || 0),
    worked_minutes: 0,
    break_minutes: Number(data.totalBreakMinutes || 0),
  } : null;

  initialServerState = buildStateFromEntry(entry);
  mobileState = cloneState(initialServerState);
}

// ── Settings ─────────────────────────────────────────────────────────────────

async function loadSettings() {
  const record = await getRecord(META_STORE, 'settings');
  return { ...SETTINGS_DEFAULT, ...(record?.value || {}) };
}

async function saveSettings(settings) {
  await putRecord(META_STORE, {
    key: 'settings',
    value: { ...SETTINGS_DEFAULT, ...settings },
    updatedAt: Date.now(),
  });
}

async function isCacheStale() {
  const settings = await loadSettings();
  const lastSync = await getRecord(META_STORE, 'lastSyncAt');
  if (!lastSync?.value) return true;
  const elapsed = Date.now() - new Date(lastSync.value).getTime();
  return elapsed > settings.cacheDurationHours * 3600000;
}

async function updateSettingsTab() {
  const settings = await loadSettings();

  const select = document.getElementById('mobile-setting-cache-duration');
  if (select) select.value = String(settings.cacheDurationHours);

  const stale = await isCacheStale();
  const cacheStatus = document.getElementById('mobile-cache-status');
  if (cacheStatus) {
    cacheStatus.textContent = stale
      ? 'Offline-Daten möglicherweise veraltet – bitte mit Server verbinden.'
      : 'Offline-Daten sind aktuell.';
    cacheStatus.dataset.state = stale ? 'warning' : 'ok';
  }

  const staleWarning = document.getElementById('mobile-stale-warning');
  if (staleWarning) {
    staleWarning.hidden = !stale;
  }
}

async function initSettingsTab() {
  await updateSettingsTab();

  const select = document.getElementById('mobile-setting-cache-duration');
  if (select) {
    select.addEventListener('change', async () => {
      const hours = Number(select.value);
      if (Number.isFinite(hours) && hours > 0) {
        await saveSettings({ cacheDurationHours: hours });
        showFeedback(
          `Cache-Dauer gesetzt: ${select.options[select.selectedIndex].text}.`,
          'info'
        );
      }
    });
  }

  const syncBtn = document.getElementById('mobile-sync-now-btn');
  if (syncBtn) {
    syncBtn.addEventListener('click', async () => {
      syncBtn.disabled = true;
      try {
        const reachability = await checkServerReachability(true);
        if (reachability !== 'online') {
          showFeedback('Server nicht erreichbar. Bitte Internetverbindung prüfen.', 'info');
          return;
        }
        await performReconnectSync('manual');
        await updateSettingsTab();
        showFeedback('Synchronisation abgeschlossen.', 'success');
      } finally {
        syncBtn.disabled = false;
      }
    });
  }

  const clearBtn = document.getElementById('mobile-clear-cache-btn');
  if (clearBtn) {
    clearBtn.addEventListener('click', async () => {
      if (
        !confirm(
          'Alle lokal gespeicherten Daten und noch nicht synchronisierten Offline-Aktionen löschen?\n\nDaten auf dem Server bleiben erhalten.'
        )
      )
        return;
      // Keep settings, clear everything else
      const settingsRecord = await getRecord(META_STORE, 'settings');
      await withStore(ACTION_STORE, 'readwrite', (store) => store.clear());
      await withStore(DATA_STORE, 'readwrite', (store) => store.clear());
      await withStore(META_STORE, 'readwrite', (store) => store.clear());
      if (settingsRecord) await putRecord(META_STORE, settingsRecord);
      mobileState = buildStateFromEntry(null);
      updateUiState();
      updateLocalDataBadge(false);
      updateLastSyncLabel(null);
      await refreshQueueIndicator();
      await updateSettingsTab();
      showFeedback('Lokaler Cache wurde geleert.', 'success');
    });
  }
}

// ─────────────────────────────────────────────────────────────────────────────

async function initializeSyncMeta() {
  const lastSync = await getRecord(META_STORE, 'lastSyncAt');
  const localData = await getRecord(META_STORE, 'localDataReady');
  updateLastSyncLabel(lastSync?.value || null);
  updateLocalDataBadge(!!localData?.value);
  await refreshQueueIndicator();
}

function setupConnectionHandlers() {
  window.addEventListener('online', () => performReconnectSync('online-event'));
  window.addEventListener('offline', async () => {
    setStatusBadge('offline');
    dispatchSyncStatus('Keine Verbindung. Eingaben werden lokal gespeichert.', 'offline');
    await checkServerReachability(true);
  });
}

window.addEventListener('DOMContentLoaded', async () => {
  // Set today's date in the offline shell (static HTML has no server-rendered date)
  const offlineDateEl = document.getElementById('offline-shell-date');
  if (offlineDateEl) {
    offlineDateEl.textContent = new Date().toLocaleDateString('de-DE', {
      weekday: 'long', day: '2-digit', month: '2-digit', year: 'numeric',
    });
  }

  registerTabHandling();
  registerModalHandling();
  registerOfflineForms();
  registerCompanySearch();
  setupConnectionHandlers();
  initializeServerStateFromDataset();
  await initializeSyncMeta();
  await initSettingsTab();
  await hydrateCompaniesFromCache();
  await recomputeEffectiveState();

  const status = await checkServerReachability(true);
  if (status === 'online') {
    await performReconnectSync('startup');
    await updateSettingsTab();
  } else {
    await updateSettingsTab();
    if (status === 'unreachable') {
      dispatchSyncStatus('Internet vorhanden, aber Server nicht erreichbar. Lokale Daten werden genutzt.', 'unreachable');
    } else {
      dispatchSyncStatus('Offline-Modus aktiv. Lokale Daten werden verwendet.', 'offline');
    }
  }
});
