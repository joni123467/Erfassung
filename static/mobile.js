import './mobile-sync.js';
const { MobileStore, SyncEngine } = globalThis.ErfassungSync;
const outbox = new MobileStore();
let localWriteInFlight = 0;
let updateQuiesced = false;
const dirtyForms = new Set();

const TAB_SELECTOR = '.mobile-tab';
const PANEL_SELECTOR = '[data-tab-panel]';
const MODAL_ID = 'mobile-order-modal';
const FORM_SELECTOR = 'form[data-offline]';
const FEEDBACK_ID = 'mobile-feedback';
const MOBILE_STATE_SELECTOR = '[data-mobile-state]';
const VACATION_LIST_SELECTOR = '[data-vacation-list]';
const VACATION_EMPTY_SELECTOR = '[data-vacation-empty]';

const ACTION_STORE = 'pendingActions';
const DATA_STORE = 'mobileData';
const META_STORE = 'meta';
const MOBILE_STATE_STORAGE_KEY = 'erfassungMobileState';
const SETTINGS_DEFAULT = { syncDays: 30 };

let localStorageUnavailable = false;
let mobileState = null;
let workDurationTimerId = null;
let modalController = null;
let initialServerState = null;
// Gruppenberechtigungen aus dem Server-Snapshot (null = unbekannt → erlauben).
let mobilePermissions = null;

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
  const panel = document.getElementById('sync-status');
  if (panel) {
    panel.dataset.state = state;
    panel.querySelector('[data-sync-label]').textContent = ({ synced: 'Synchronisiert', syncing: 'Synchronisation läuft',
      offline: 'Offline', queue: 'Ausstehende Buchungen', error: 'Synchronisation fehlgeschlagen',
      auth: 'Anmeldung erforderlich', account: 'Anderes Konto angemeldet', identity: 'Kontozuordnung prüfen',
      storage: 'Speicher prüfen', conflict: 'Freigabe erforderlich' })[state] || 'Synchronisation';
    panel.querySelector('[data-sync-message]').textContent = message;
    panel.querySelector('[data-sync-login]').hidden = !['auth', 'account'].includes(state);
    panel.querySelector('[data-sync-identity]').hidden = state !== 'identity';
  }
  setStatusBadge(state === 'synced' ? 'online' : state);
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
    auth: 'Bitte anmelden', account: 'Konto prüfen', conflict: 'Freigabe erforderlich',
    queue: 'Buchungen ausstehend', error: 'Abgleich fehlgeschlagen', storage: 'Speicherfehler', identity: 'Konto prüfen',
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
    // Im localStorage ablegen, damit auch die statische Offline-Hülle es benutzen kann
    try { window.localStorage.setItem('erfassung_csrf_token', token); } catch {}
    return token;
  }
  // Rückfallebene: das Token vom letzten Seitenaufruf mit Netz
  try { return window.localStorage.getItem('erfassung_csrf_token') || ''; } catch {}
  return '';
}

function escHtml(str) {
  return String(str || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function fmtMins(minutes) {
  const m = Math.max(0, Math.round(Number(minutes || 0)));
  return `${Math.floor(m / 60)}:${String(m % 60).padStart(2, '0')}`;
}

function isoDateStr(date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}

// Örtliche Uhrzeit als "JJJJ-MM-TTTHH:MM:SS", ohne Zonenumrechnung. Nur so
// behält eine offline erfasste Stempelung die **tatsächliche** Zeit des Tippens
// statt der späteren Übertragungszeit. Der Server hält eine Stempelung mit Netz
// genauso fest.
function localIsoTimestamp(date = new Date()) {
  const p = (n) => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${p(date.getMonth() + 1)}-${p(date.getDate())}T${p(date.getHours())}:${p(date.getMinutes())}:${p(date.getSeconds())}`;
}

function getMondayOf(date) {
  const d = new Date(date);
  const day = d.getDay() || 7;
  d.setDate(d.getDate() - (day - 1));
  d.setHours(0, 0, 0, 0);
  return d;
}

function getISOWeekNumber(date) {
  const d = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()));
  const day = d.getUTCDay() || 7;
  d.setUTCDate(d.getUTCDate() + 4 - day);
  const yearStart = new Date(Date.UTC(d.getUTCFullYear(), 0, 1));
  return Math.ceil((((d - yearStart) / 86400000) + 1) / 7);
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
      entryId: null,
      notes: '',
      isRemote: false,
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
    entryId: entry.id || null,
    notes: entry.notes || '',
    isRemote: !!entry.is_remote,
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
    entryId: state.entryId || null,
    notes: state.notes || '',
    isRemote: !!state.isRemote,
  };
}

// Checkbox-Werte aus dem serialisierten Formular ('1'/'on') robust auswerten.
function isTruthyFlag(value) {
  if (value === true) return true;
  const text = String(value ?? '').trim().toLowerCase();
  return text === '1' || text === 'on' || text === 'true' || text === 'yes';
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
    next.entryId = null;
    next.notes = (payload.notes || '').trim();
    next.isRemote = isTruthyFlag(payload.is_remote);
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
    next.entryId = null;
    next.notes = (payload.notes || '').trim();
    next.isRemote = isTruthyFlag(payload.is_remote);
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
    next.entryId = null;
    next.notes = '';
    next.isRemote = false;
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

function withStore(name, mode, callback) { return outbox.withStore(name, mode, callback); }
function putRecord(name, record) { return outbox.put(name, record); }
function getRecord(name, key) { return outbox.get(name, key); }
function deleteRecord(name, key) { return outbox.remove(name, key); }
function getAllRecords(name) { return outbox.all(name); }

function serializeFormData(form) {
  const payload = {};
  for (const [key, value] of new FormData(form).entries()) {
    payload[key] = typeof value === 'string' ? value : '';
  }
  return payload;
}

function generateClientActionId(prefix) {
  return `${prefix}-${crypto.randomUUID()}`;
}

async function queueAction(type, payload) {
  const id = await outbox.enqueue(type, payload);
  navigator.storage?.persist?.().catch(() => {});
  navigator.serviceWorker?.ready.then(registration => registration.sync?.register('erfassung-outbox')).catch(() => {});
  return id;
}

function readPendingActions() { return outbox.pending(); }

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
  const dashboard = document.querySelector(MOBILE_STATE_SELECTOR);
  if (dashboard) dashboard.dataset.workState = mobileState.onBreak ? 'pause' : mobileState.isWorking ? 'working' : 'idle';
  applyStateVisibility('active', mobileState.isWorking);
  applyStateVisibility('idle', !mobileState.isWorking);
  applyStateVisibility('break-active', mobileState.isWorking && mobileState.onBreak);
  applyStateVisibility('break-idle', mobileState.isWorking && !mobileState.onBreak);
  applyStateVisibility('company-active', mobileState.isWorking && mobileState.hasCompany);
  applyStateVisibility('remote-active', mobileState.isWorking && mobileState.isRemote);

  const values = {
    'header-start': mobileState.isWorking ? mobileState.startLabel || '--:--' : '',
    'work-start': mobileState.isWorking ? mobileState.startLabel || '--:--' : '',
    'company-name': mobileState.companyName || '',
    'break-start': mobileState.onBreak ? mobileState.breakLabel || '--:--' : '',
    'break-total': mobileState.breakTotalLabel || '0:00',
    'booking-mode': mobileState.hasCompany ? 'Auftrag läuft' : 'Nur Arbeitszeit',
    'work-status': mobileState.onBreak ? 'Pause läuft' : 'Arbeitszeit läuft',
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
  if (select instanceof HTMLSelectElement && select.value) {
    return select.options[select.selectedIndex]?.textContent?.trim() || '';
  }
  // Kein Dropdown-Wert (Platzhalter): Suchtext verwenden, damit der Server die
  // Firma über den Namen auflösen kann.
  const search = form.querySelector('[data-company-search-target]');
  if (search instanceof HTMLInputElement) {
    return (search.value || '').trim();
  }
  return '';
}

// Löst den Firmennamen aus der Suche client-seitig gegen die Dropdown-Optionen
// auf (exakte Übereinstimmung, Groß-/Kleinschreibung egal) und liefert die id.
function resolveCompanyIdByName(form, name) {
  const cleaned = (name || '').trim().toLocaleLowerCase('de-DE');
  if (!cleaned) return '';
  const select = form.querySelector('select[name="company_id"]');
  if (!(select instanceof HTMLSelectElement)) return '';
  for (const option of Array.from(select.options)) {
    if (!option.value) continue;
    if ((option.textContent || '').trim().toLocaleLowerCase('de-DE') === cleaned) {
      return option.value;
    }
  }
  return '';
}

async function recomputeEffectiveState() {
  const snapshot = await getRecord(DATA_STORE, 'snapshot');
  const pending = await readPendingActions();

  let base = initialServerState ? cloneState(initialServerState) : buildStateFromEntry(snapshot?.data?.active_entry || null);
  if (!snapshot && !initialServerState) {
    const stored = loadStoredMobileState();
    if (stored && stored.version >= 1) {
      base = cloneState(stored);
    }
  }

  const acknowledgedSinceSnapshot = (await getAllRecords(DATA_STORE))
    .filter(row => row.key.startsWith('receipt:') && row.savedAt > (snapshot?.savedAt || 0) && row.receipt.status === 'applied')
    .map(row => row.entry);
  for (const action of [...acknowledgedSinceSnapshot, ...pending].sort((a, b) => a.createdAt - b.createdAt)) {
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

// Blendet Aktionen aus, die die Gruppe des Benutzers nicht erlaubt. Wird aus
// dem Sync-Snapshot gespeist, damit auch die statische Offline-Shell die
// Rechte kennt. Ohne Snapshot (perms = null) bleibt alles sichtbar; der Server
// lehnt nicht erlaubte Aktionen ohnehin ab.
function applyMobilePermissions(perms) {
  if (!perms || typeof perms !== 'object') return;
  mobilePermissions = perms;
  document.querySelectorAll('[data-mobile-admin]').forEach(link => setElementHidden(link, perms.admin_access !== true));
  document.querySelectorAll('[data-mobile-manual]').forEach(link => setElementHidden(link, perms.manual_time_entries !== true));

  if (perms.edit_own_notes === false) {
    const launch = document.getElementById('mobile-notes-launch');
    if (launch) setElementHidden(launch, true);
  }

  document.querySelectorAll('input[name="new_company_name"]').forEach((input) => {
    const label = input.closest('label');
    setElementHidden(label || input, perms.create_companies === false);
  });

  document.querySelectorAll('form[data-offline="vacation"]').forEach((form) => setElementHidden(form, perms.request_vacations === false));
  const denied = document.querySelector('[data-permission="request-vacations-denied"]');
  if (denied) setElementHidden(denied, perms.request_vacations !== false);
}

async function hydratePermissionsFromCache() {
  const snapshot = await getRecord(DATA_STORE, 'snapshot');
  applyMobilePermissions(snapshot?.data?.permissions || null);
}

// Appearance settings are bound to the outbox owner. They never change who
// owns a booking and an account mismatch must not apply another user's default.
let overviewPreferenceOwner = null;
let overviewInteracted = ['day', 'week'].includes(new URLSearchParams(location.search).get('overview'));

async function cacheOverviewPreference(userId, value) {
  const owner = await outbox.identity();
  if (!owner || owner.id !== userId || !['day', 'week'].includes(value)) return false;
  await putRecord(META_STORE, { key: `overview-preference:${userId}`, userId, value, updatedAt: Date.now() });
  return true;
}

async function hydrateMobileInterface() {
  const owner = await outbox.identity();
  if (!owner) {
    document.querySelectorAll('[data-mobile-account-name]').forEach(node => { node.textContent = 'Noch kein Konto eingerichtet'; });
    document.querySelectorAll('[data-mobile-account-group]').forEach(node => { node.textContent = 'Zum ersten Start bitte online anmelden.'; });
    return;
  }
  const snapshot = await getRecord(DATA_STORE, 'snapshot');
  const user = snapshot?.data?.user?.id === owner.id ? snapshot.data.user : null;
  document.querySelectorAll('[data-mobile-account-name]').forEach(node => { node.textContent = user?.full_name || owner.name || 'Mein Konto'; });
  document.querySelectorAll('[data-mobile-account-group]').forEach(node => { node.textContent = user?.group || ''; });
  document.querySelectorAll('[data-mobile-overtime]').forEach(node => setElementHidden(node, !user?.overtime_vacation_enabled));
  if (user && ['day', 'week'].includes(user.overview_preference)) {
    await cacheOverviewPreference(owner.id, user.overview_preference);
  }
  const cached = await getRecord(META_STORE, `overview-preference:${owner.id}`);
  const value = cached?.userId === owner.id && ['day', 'week'].includes(cached.value) ? cached.value : 'day';
  if (overviewPreferenceOwner !== null && overviewPreferenceOwner !== owner.id) overviewInteracted = false;
  if (overviewPreferenceOwner !== owner.id || !overviewInteracted) {
    // Respect an explicit URL choice on first load; it is not a new default.
    const requested = new URLSearchParams(location.search).get('overview');
    overviewMode = overviewPreferenceOwner === null && ['day', 'week'].includes(requested) ? requested : value;
  }
  overviewPreferenceOwner = owner.id;
  const select = document.getElementById('mobile-setting-default-view');
  if (select && !dirtyForms.has(select.form)) select.value = value;
}

function registerMobileInterface() {
  document.querySelectorAll('[data-mobile-online]').forEach(link => link.addEventListener('click', event => {
    if (navigator.onLine !== false) return;
    event.preventDefault();
    showFeedback('Dieser Bereich benötigt eine Verbindung. Deine lokalen Buchungen bleiben auf diesem Gerät.', 'info');
  }));
  const form = document.getElementById('mobile-preference-form');
  form?.addEventListener('submit', async event => {
    event.preventDefault();
    const feedback = document.getElementById('mobile-preference-feedback');
    const button = form.querySelector('button[type="submit"]');
    if (navigator.onLine === false) {
      feedback.textContent = 'Zum Speichern bitte verbinden. Deine bisherige Startansicht bleibt erhalten.';
      return;
    }
    const value = new FormData(form).get('overview_preference');
    if (!['day', 'week'].includes(value)) return;
    button.disabled = true;
    try {
      const session = await syncEngine.connect();
      const answer = await syncEngine.request('/api/account/preferences', {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': session.csrf_token },
        body: JSON.stringify({ overview_preference: value, user_id: session.user.id }),
      });
      if (answer.user_id !== session.user.id || answer.overview_preference !== value) throw new Error('Die Antwort gehört nicht zu deiner Einstellung. Bitte erneut prüfen.');
      if (!await cacheOverviewPreference(answer.user_id, value)) throw new Error('Das Konto hat sich geändert. Bitte erneut anmelden.');
      const snapshot = await getRecord(DATA_STORE, 'snapshot');
      if (snapshot?.data?.user?.id === answer.user_id) {
        snapshot.data.user.overview_preference = value;
        await putRecord(DATA_STORE, snapshot);
      }
      dirtyForms.delete(form);
      overviewMode = value;
      overviewInteracted = false;
      feedback.textContent = 'Startansicht gespeichert. Sie gilt für Web und PWA.';
      await renderOverview();
    } catch (error) {
      feedback.textContent = `Nicht gespeichert: ${error.message || 'Bitte Verbindung prüfen.'}`;
    } finally { button.disabled = false; }
  });
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

  // Suchvorschläge (datalist) ebenfalls befüllen – die Offline-Shell startet
  // mit einer leeren Liste.
  document.querySelectorAll('[data-company-search-target]').forEach((input) => {
    if (!(input instanceof HTMLInputElement)) return;
    const listId = input.getAttribute('list');
    const datalist = listId ? document.getElementById(listId) : null;
    if (!(datalist instanceof HTMLDataListElement)) return;
    datalist.innerHTML = '';
    companies.forEach((company) => {
      const option = document.createElement('option');
      option.value = company.name;
      datalist.appendChild(option);
    });
  });
}

// Einsatzorte aus dem Snapshot in die Auswahlliste des Auftragsdialogs
// schreiben, gefiltert auf die gewählte Firma. Ohne das stünde man offline vor
// einer Liste mit nur „Vor Ort“ und „Remote“ – die Standorte kommen aus der
// Synchronisation, nicht aus der zwischengespeicherten Seite. Ein Standort
// gehört zu genau einer Firma; firmenfremde Einträge dürfen nie auftauchen.
//
// „Vor Ort“ und „Remote“ stehen dabei immer voran, unabhängig von der Firma.
//
// Beim Wechsel der Firma wird der Hauptstandort vorausgewählt: Wer eine Firma
// mit Standort wählt, meint fast immer deren Standort und nicht „Vor Ort“.
async function hydrateLocationsFromCache() {
  const snapshot = await getRecord(DATA_STORE, 'snapshot');
  const locations = snapshot?.data?.locations;
  if (!Array.isArray(locations)) return;

  const byCompany = new Map();
  locations.forEach((location) => {
    const key = String(location.company_id || '');
    if (!byCompany.has(key)) byCompany.set(key, []);
    byCompany.get(key).push(location);
  });

  const fill = (select, items, keepValue) => {
    const previous = keepValue ? select.value : '';
    select.innerHTML = '';
    [['onsite', 'Vor Ort'], ['remote', 'Remote']].forEach(([value, label]) => {
      const option = document.createElement('option');
      option.value = value;
      option.textContent = label;
      select.appendChild(option);
    });
    (items || []).forEach((location) => {
      const option = document.createElement('option');
      option.value = String(location.id);
      option.textContent = location.city
        ? `${location.name} · ${location.city}`
        : location.name;
      select.appendChild(option);
    });
    const primary = (items || []).find((item) => item.is_primary) || (items || [])[0];
    const wanted = previous && [...select.options].some((o) => o.value === previous)
      ? previous
      : (primary ? String(primary.id) : 'onsite');
    select.value = wanted;
  };

  document.querySelectorAll('[data-location-picker]').forEach((select) => {
    if (!(select instanceof HTMLSelectElement)) return;
    const form = select.closest('form');
    const companySelect = form ? form.querySelector('select[name="company_id"]') : null;
    if (!companySelect) {
      fill(select, [], true);
      return;
    }
    const update = (keepValue) => {
      const key = String(companySelect.value || '');
      fill(select, key ? byCompany.get(key) : [], keepValue);
    };
    if (!select.dataset.locationWired) {
      companySelect.addEventListener('change', () => update(false));
      select.dataset.locationWired = '1';
    }
    update(true);
  });
}

async function syncServerData() {
  try {
    const settings = await loadSettings();
    const days = Math.max(7, settings.syncDays || 30);
    const payload = await syncEngine.request(`/mobile/sync-data?days=${days}`, {
      method: 'GET', headers: { Accept: 'application/json' },
    }, 12000);
    const owner = await outbox.identity();
    if (!owner || payload.user?.id !== owner.id) throw new Error('Kontozuordnung stimmt nicht überein.');
    await putRecord(DATA_STORE, { key: 'snapshot', data: payload, savedAt: Date.now() });
    // Den Ausgangszustand am frischen Serverstand ausrichten. Sonst bliebe er
    // an dem Wert vom Seitenaufruf hängen – und die Anzeige sprang direkt nach
    // einer übertragenen Einstempelung zurück auf „arbeitet nicht".
    initialServerState = buildStateFromEntry(payload.active_entry || null);
    await putRecord(META_STORE, { key: 'localDataReady', value: true, updatedAt: Date.now() });
    updateLocalDataBadge(true);
    await hydrateCompaniesFromCache();
    await hydrateLocationsFromCache();
    applyMobilePermissions(payload.permissions || null);
    await hydrateMobileInterface();
    await handleServerVersion(payload.version || '');
    return true;
  } catch (error) {
    const msg = `Sync fehlgeschlagen: ${error?.message || 'Netzwerkfehler'}. Bitte erneut versuchen.`;
    dispatchSyncStatus(msg, 'error');
    showFeedback(msg, 'error');
    return false;
  }
}

const syncEngine = new SyncEngine(outbox, {
  notify: (state, message) => dispatchSyncStatus(message, state),
  snapshot: session => {
    const meta = document.querySelector('meta[name="csrf-token"]');
    if (meta) meta.content = session.csrf_token;
    return syncServerData();
  },
});

async function performReconnectSync(trigger = 'auto') {
  if (updateQuiesced) return;
  try {
    await syncEngine.run(['manual', 'online-event', 'resume', 'punch', 'vacation'].includes(trigger));
    await recomputeEffectiveState();
    await refreshQueueIndicator();
    await updateSettingsTab();
    renderOverview().catch(() => {});
    renderSalden().catch(() => {});
    renderVacations().catch(() => {});
    await renderSyncDetails();
  } catch (error) {
    dispatchSyncStatus(error.message, 'storage');
  }
}

async function processPunchSubmission(form, payload) {
  payload.client_action_id = payload.client_action_id || generateClientActionId('punch');
  // Die tatsächliche Zeit **jetzt** festhalten – den Moment des Tippens. So
  // übersteht sie die Warteschlange und erreicht den Server auch dann richtig,
  // wenn erst Stunden später übertragen wird.
  if (!payload.event_time) payload.event_time = new Date().toISOString();
  if (payload.action === 'start_company') {
    payload.company_name = determineCompanyName(form, payload);
    // Suchvorschlag gewählt, aber Dropdown unberührt: company_id client-seitig
    // aus dem Namen auflösen, damit die Buchung nicht am leeren Dropdown scheitert.
    if (!payload.company_id && !(payload.new_company_name || '').trim()) {
      const resolved = resolveCompanyIdByName(form, payload.company_name);
      if (resolved) payload.company_id = resolved;
    }
  }

  // Nach dem Beenden optional den Kommentar der beendeten Buchung anbieten –
  // Zustand VOR dem Anwenden der Aktion festhalten.
  let notesFollowUp = null;
  if (
    (payload.action === 'end_work' || payload.action === 'end_company')
    && mobileState?.isWorking
    && mobilePermissions?.edit_own_notes !== false
  ) {
    notesFollowUp = {
      entryId: mobileState.entryId || '',
      notes: mobileState.notes || '',
      isRemote: !!mobileState.isRemote,
    };
  }

  // ── Immer zuerst in die Warteschlange: Jede Stempelung landet in der
  // IndexedDB, bevor überhaupt ein Übertragungsversuch startet. Kein Ereignis
  // wird aufgrund einer Vermutung des Geräts verworfen – genau daran gingen
  // früher Ausstempelungen verloren. Was eine Dublette ist, entscheidet allein
  // der Server anhand der `client_action_id`.
  form.dataset.savedActionId = await queueAction('punch', payload);
  dispatchSyncStatus('Buchung sicher auf diesem Gerät gespeichert. Übertragung steht aus.', navigator.onLine ? 'queue' : 'offline');
  await recomputeEffectiveState();
  await refreshQueueIndicator();
  showFeedback('Buchung lokal erfasst. Synchronisiere …', 'info');

  if (notesFollowUp) {
    updateNotesLaunchButton(notesFollowUp.entryId, notesFollowUp.notes, notesFollowUp.isRemote);
    openNotesModal(notesFollowUp.entryId, notesFollowUp.notes, notesFollowUp.isRemote);
  } else if (payload.action === 'update_notes') {
    updateNotesLaunchButton(
      payload.entry_id || '',
      (payload.notes || '').trim(),
      payload.is_remote,
    );
  }

  // Sofortige Übertragung im Hintergrund anstoßen – die Bedienung wartet nicht darauf
  try {
    void performReconnectSync('punch');
  } catch { /* sync failure is non-fatal – action stays in queue */ }
}

async function processVacationSubmission(form, payload) {
  payload.client_action_id = payload.client_action_id || generateClientActionId('vacation');

  // ── Queue-first: always save locally, then attempt sync ──
  form.dataset.savedActionId = await queueAction('vacation', payload);
  dispatchSyncStatus('Antrag auf diesem Gerät gespeichert. Übertragung steht aus.', navigator.onLine ? 'queue' : 'offline');
  await renderVacations();
  await refreshQueueIndicator();
  showFeedback('Urlaubsantrag lokal erfasst. Synchronisiere …', 'info');

  // Attempt immediate sync in background
  try {
    void performReconnectSync('vacation');
  } catch { /* sync failure is non-fatal – action stays in queue */ }
}

async function handleOfflineSubmission(event) {
  event.preventDefault();
  if (updateQuiesced) return;
  const form = event.target;
  if (form.dataset.saving === '1') return;
  form.dataset.saving = '1';
  localWriteInFlight++;
  const buttons = [...form.querySelectorAll('button[type="submit"], button:not([type])')];
  buttons.forEach(button => { button.disabled = true; });
  try {
    const payload = serializeFormData(form);
    if (form.dataset.offline === 'vacation') await processVacationSubmission(form, payload);
    else await processPunchSubmission(form, payload);
    form.reset();
    dirtyForms.delete(form);
    const modal = form.closest('.modal');
    if (modal) {
      modal.classList.remove('is-visible');
      modal.setAttribute('aria-hidden', 'true');
      document.body.classList.remove('modal-open');
    }
  } catch (error) {
    if (form.dataset.savedActionId) {
      // A later display/read failure must not turn a durable write into a
      // misleading "not saved" message and invite the user to book it again.
      const message = `Buchung lokal gespeichert. Anzeige konnte nicht aktualisiert werden: ${error.message}. Bitte abgleichen.`;
      showFeedback(message, 'error');
      dispatchSyncStatus(message, 'storage');
      form.reset();
      dirtyForms.delete(form);
    } else {
      showFeedback(`Nicht gespeichert: ${error.message}`, 'error');
      dispatchSyncStatus(`Buchung nicht bestätigt: ${error.message}`, 'storage');
    }
  } finally {
    localWriteInFlight--;
    form.dataset.saving = '';
    delete form.dataset.savedActionId;
    buttons.forEach(button => { button.disabled = false; });
  }
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
      const moreActive = current === 'salden' && tab.dataset.tab === 'einstellungen';
      tab.classList.toggle('is-active', active || moreActive);
      tab.setAttribute('aria-selected', active || moreActive ? 'true' : 'false');
      if (tab.closest('.mobile-bottom-nav')) tab.tabIndex = active || moreActive ? 0 : -1;
    });
    const dashboard = document.querySelector(MOBILE_STATE_SELECTOR);
    if (dashboard) dashboard.dataset.activeTab = current;
    const title = document.querySelector('.mobile-dashboard__title');
    if (title) title.textContent = ({ buchung: 'Mein Tag', uebersicht: 'Meine Zeiten', salden: 'Mein Zeitkonto', urlaub: 'Urlaub', einstellungen: 'Mehr' })[current];
    panels.forEach((panel) => {
      const active = panel.dataset.tabPanel === current;
      panel.classList.toggle('is-active', active);
      setElementHidden(panel, !active);
      panel.setAttribute('aria-hidden', active ? 'false' : 'true');
    });
    // A restart may hydrate the clock while another panel is open. Re-enable
    // its visible controls when returning, without enabling hidden state actions.
    refreshControlStates();
    if (updateHistory && history.replaceState) {
      const url = new URL(window.location.href);
      url.searchParams.set('tab', current);
      url.hash = `#${current}`;
      history.replaceState(null, '', `${url.pathname}${url.search}${url.hash}`);
    }
  };

  tabs.forEach((tab) => tab.addEventListener('click', (event) => {
    event.preventDefault();
    const tabName = tab.dataset.tab || defaultTab;
    activate(tabName);
    if (tabName === 'uebersicht') renderOverview().catch(() => {});
    if (tabName === 'salden') renderSalden().catch(() => {});
    if (tabName === 'urlaub') renderVacations().catch(() => {});
  }));
  document.querySelectorAll('[data-mobile-open]').forEach(link => link.addEventListener('click', event => {
    event.preventDefault(); activate(link.dataset.mobileOpen);
  }));
  const primaryTabs = tabs.filter(tab => tab.closest('.mobile-bottom-nav'));
  primaryTabs.forEach((tab, index) => tab.addEventListener('keydown', event => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? primaryTabs.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + primaryTabs.length) % primaryTabs.length;
    primaryTabs[next].focus(); primaryTabs[next].click();
  }));
  window.addEventListener('hashchange', () => activate(window.location.hash.replace('#', ''), false));
  activate(window.location.hash.replace('#', '') || new URLSearchParams(location.search).get('tab'), false);
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

const NOTES_MODAL_ID = 'mobile-notes-modal';

function setNotesModalVisible(visible) {
  const modal = document.getElementById(NOTES_MODAL_ID);
  if (!modal) return;
  modal.classList.toggle('is-visible', visible);
  modal.setAttribute('aria-hidden', visible ? 'false' : 'true');
  document.body.classList.toggle('modal-open', visible);
}

function openNotesModal(entryId, notes, isRemote) {
  const modal = document.getElementById(NOTES_MODAL_ID);
  if (!modal) return;
  const idInput = modal.querySelector('input[name="entry_id"]');
  const textarea = modal.querySelector('textarea[name="notes"]');
  const remoteInput = modal.querySelector('input[name="is_remote"]');
  if (idInput instanceof HTMLInputElement) idInput.value = entryId ? String(entryId) : '';
  if (textarea instanceof HTMLTextAreaElement) textarea.value = notes || '';
  if (remoteInput instanceof HTMLInputElement) remoteInput.checked = isTruthyFlag(isRemote);
  setNotesModalVisible(true);
  if (textarea instanceof HTMLTextAreaElement) textarea.focus();
}

// Hält den "Kommentar bearbeiten"-Button unter den Stempel-Aktionen aktuell,
// damit der Kommentar auch nach dem Schließen des Dialogs erreichbar bleibt.
function updateNotesLaunchButton(entryId, notes, isRemote) {
  if (mobilePermissions?.edit_own_notes === false) return;
  const button = document.getElementById('mobile-notes-launch');
  if (!button) return;
  button.dataset.entryId = entryId ? String(entryId) : '';
  button.dataset.entryNotes = notes || '';
  button.dataset.entryRemote = isTruthyFlag(isRemote) ? '1' : '';
  setElementHidden(button, false);
}

function registerNotesModal() {
  const modal = document.getElementById(NOTES_MODAL_ID);
  if (!modal) return;

  modal.querySelectorAll('[data-close]').forEach((closer) => {
    closer.addEventListener('click', (event) => {
      event.preventDefault();
      setNotesModalVisible(false);
    });
  });

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && modal.classList.contains('is-visible')) setNotesModalVisible(false);
  });

  const launch = document.getElementById('mobile-notes-launch');
  if (launch) {
    launch.addEventListener('click', (event) => {
      event.preventDefault();
      openNotesModal(
        launch.dataset.entryId || '',
        launch.dataset.entryNotes || '',
        launch.dataset.entryRemote || '',
      );
    });
  }
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
      let exactMatchValue = '';
      Array.from(select.options).forEach((option, index) => {
        if (index === 0) {
          option.hidden = false;
          return;
        }
        const label = (option.textContent || '').toLocaleLowerCase('de-DE');
        const visible = !query || label.includes(query);
        option.hidden = !visible;
        if (visible) visibleCount += 1;
        if (query && label === query) {
          exactMatchValue = option.value;
        }
      });

      // Ein gewählter Suchvorschlag (datalist) erreicht das Dropdown sonst nie:
      // bei exakter Übereinstimmung die Firma direkt auswählen, damit das
      // Stempeln ohne zusätzlichen Dropdown-Tipp funktioniert.
      if (exactMatchValue) {
        select.value = exactMatchValue;
      }

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
    // Manche Browser feuern bei der Übernahme eines datalist-Vorschlags nur
    // 'change' statt 'input'.
    input.addEventListener('change', update);
    update();
  });
}

function registerOfflineForms() {
  document.querySelectorAll(FORM_SELECTOR).forEach((form) => form.addEventListener('submit', handleOfflineSubmission));
}

function initializeServerStateFromDataset() {
  const root = document.querySelector(MOBILE_STATE_SELECTOR);
  if (root?.hasAttribute('data-offline-shell')) {
    initialServerState = null;
    mobileState = buildStateFromEntry(null);
    return;
  }
  if (!root) {
    initialServerState = buildStateFromEntry(null);
    mobileState = buildStateFromEntry(null);
    return;
  }

  const data = root.dataset;
  const entry = data.stateRunning === 'true' ? {
    id: data.entryId ? Number(data.entryId) : null,
    work_date: data.startTimestamp ? data.startTimestamp.slice(0, 10) : new Date().toISOString().slice(0, 10),
    start_time: data.startLabel ? `${data.startLabel}:00` : '00:00:00',
    break_started_at: data.stateBreak === 'true' && data.breakLabel ? `${data.breakLabel}:00` : null,
    company_id: data.stateCompany === 'true' ? 1 : null,
    company_name: data.companyName || '',
    is_open: true,
    total_break_minutes: Number(data.totalBreakMinutes || 0),
    worked_minutes: 0,
    break_minutes: Number(data.totalBreakMinutes || 0),
    notes: data.entryNotes || '',
  } : null;

  initialServerState = buildStateFromEntry(entry);
  mobileState = cloneState(initialServerState);
}

// ── Client-side Übersicht (offline-capable day/week view) ────────────────────

let overviewMode = ['day', 'week'].includes(new URLSearchParams(location.search).get('overview'))
  ? new URLSearchParams(location.search).get('overview')
  : document.querySelector(MOBILE_STATE_SELECTOR)?.dataset.overviewPreference === 'week' ? 'week' : 'day';
let overviewDate = (() => { const d = new Date(); d.setHours(0, 0, 0, 0); return d; })();

function _overviewAttachNav(container, onPrev, onNext, onMode) {
  container.querySelector('[data-ov-prev]')?.addEventListener('click', () => { onPrev(); renderOverview().catch(() => {}); });
  container.querySelector('[data-ov-next]')?.addEventListener('click', () => { onNext(); renderOverview().catch(() => {}); });
  container.querySelectorAll('[data-ov-mode]').forEach((btn) => {
    btn.addEventListener('click', () => { overviewInteracted = true; onMode(btn.dataset.ovMode); renderOverview().catch(() => {}); });
  });
}

function _modeToggleHtml() {
  return `
    <div class="mobile-segmented" role="group" aria-label="Darstellung wählen">
      <button type="button" class="mobile-segmented__button${overviewMode === 'day' ? ' is-active' : ''}" data-ov-mode="day" aria-pressed="${overviewMode === 'day'}">Tag</button>
      <button type="button" class="mobile-segmented__button${overviewMode === 'week' ? ' is-active' : ''}" data-ov-mode="week" aria-pressed="${overviewMode === 'week'}">Woche</button>
    </div>`;
}

async function renderOverview() {
  const container = document.getElementById('overview-card');
  if (!container) return;

  const snapshot = await getRecord(DATA_STORE, 'snapshot');
  if (!snapshot?.data) {
    container.innerHTML = '<p class="mobile-empty-state">Keine lokalen Daten vorhanden. Bitte online verbinden.</p>';
    return;
  }

  const allEntries = snapshot.data.entries || [];
  const fallbackDaily = snapshot.data.user?.daily_target_minutes || 480;
  // `daily_targets` gibt es seit 0.20.7: die Sollzeit je Kalendertag aus dem
  // am jeweiligen Tag gültigen Arbeitszeitplan. Ohne diese Angabe – etwa in
  // einer Momentaufnahme, die vor dem Update entstanden ist – gilt weiter die
  // pauschale Rechnung „Tagessoll an Werktagen".
  const dailyTargets = snapshot.data.daily_targets || null;
  const targetFor = (dateStr, dateObj) => {
    if (dailyTargets && Object.prototype.hasOwnProperty.call(dailyTargets, dateStr)) {
      return dailyTargets[dateStr];
    }
    const weekday = dateObj.getDay();
    return weekday >= 1 && weekday <= 5 ? fallbackDaily : 0;
  };
  const today = new Date(); today.setHours(0, 0, 0, 0);

  if (overviewMode === 'week') {
    _renderWeekView(container, allEntries, targetFor, today);
  } else {
    _renderDayView(container, allEntries, targetFor, today);
  }
}

function _renderDayView(container, allEntries, targetFor, today) {
  const dateStr = isoDateStr(overviewDate);
  const isToday = dateStr === isoDateStr(today);
  const dayEntries = allEntries.filter((e) => e.work_date === dateStr);
  const totalWorked = dayEntries.reduce((s, e) => s + (e.worked_minutes || 0), 0);
  const dailyTarget = targetFor(dateStr, overviewDate);
  const balance = totalWorked - dailyTarget;

  const prevDate = new Date(overviewDate); prevDate.setDate(prevDate.getDate() - 1);
  const nextDate = new Date(overviewDate); nextDate.setDate(nextDate.getDate() + 1);
  const canNext = nextDate <= today;

  const dateLabel = overviewDate.toLocaleDateString('de-DE', { weekday: 'long', day: '2-digit', month: '2-digit', year: 'numeric' });

  let html = `
    <div class="mobile-card__header">
      <h2 class="mobile-card__title">Übersicht</h2>
      ${_modeToggleHtml()}
    </div>
    <div class="mobile-overview-nav" aria-label="Tag wechseln">
      <button class="mobile-nav-button" data-ov-prev aria-label="Vorheriger Tag">&lsaquo;</button>
      <span class="mobile-overview-nav__label">
        <strong>${escHtml(dateLabel)}</strong>
        ${isToday ? '<small>(Heute)</small>' : ''}
      </span>
      ${canNext
        ? '<button class="mobile-nav-button" data-ov-next aria-label="Nächster Tag">&rsaquo;</button>'
        : '<span class="mobile-nav-button is-disabled" aria-hidden="true">&rsaquo;</span>'}
    </div>
    <dl class="mobile-overview-summary">
      <div><dt>Arbeitszeit</dt><dd>${fmtMins(totalWorked)} Std</dd></div>
      <div><dt>Soll</dt><dd>${fmtMins(dailyTarget)} Std</dd></div>
      <div><dt>Saldo</dt><dd class="${balance < 0 ? 'is-negative' : ''}">${balance < 0 ? '-' : ''}${fmtMins(Math.abs(balance))} Std</dd></div>
    </dl>`;

  if (dayEntries.length > 0) {
    html += '<ul class="mobile-entry-list mobile-entry-list--compact">';
    for (const entry of dayEntries) {
      const endTime = entry.is_open ? 'läuft' : (entry.end_time ? entry.end_time.slice(0, 5) : '–');
      html += `
        <li class="mobile-entry${entry.is_open ? ' is-active' : ''}">
          <div class="mobile-entry__times">
            <strong>${escHtml(entry.start_time.slice(0, 5))}</strong>
            <span>–</span>
            <strong>${escHtml(endTime)}</strong>
          </div>
          <div class="mobile-entry__meta">
            <span>Arbeitszeit ${fmtMins(entry.worked_minutes)} Std</span>
            ${entry.total_break_minutes ? `<span>Pausen ${fmtMins(entry.total_break_minutes)} Std</span>` : ''}
            ${entry.company_name ? `<span>${escHtml(entry.company_name)}</span>` : ''}
            ${entry.is_remote ? '<span class="mobile-badge mobile-badge--remote">Remote</span>' : ''}
            ${entry.notes ? `<span class="mobile-entry__notes">${escHtml(entry.notes)}</span>` : ''}
          </div>
        </li>`;
    }
    html += '</ul>';
  } else {
    html += '<p class="mobile-empty-state">Für diesen Tag wurden keine Buchungen erfasst.</p>';
  }

  container.innerHTML = html;
  _overviewAttachNav(
    container,
    () => { overviewDate = prevDate; },
    () => { if (canNext) overviewDate = nextDate; },
    (mode) => { overviewMode = mode; if (mode === 'day') { overviewDate = new Date(today); } }
  );
}

function _renderWeekView(container, allEntries, targetFor, today) {
  const monday = getMondayOf(overviewDate);
  const sunday = new Date(monday); sunday.setDate(sunday.getDate() + 6);
  const weekNum = getISOWeekNumber(monday);
  const prevMonday = new Date(monday); prevMonday.setDate(prevMonday.getDate() - 7);
  const nextMonday = new Date(monday); nextMonday.setDate(nextMonday.getDate() + 7);
  const canNext = nextMonday <= today;

  const dayMap = {};
  let weeklyTarget = 0;
  for (let i = 0; i < 7; i++) {
    const d = new Date(monday); d.setDate(d.getDate() + i);
    const ds = isoDateStr(d);
    const target = targetFor(ds, d);
    weeklyTarget += target;
    dayMap[ds] = { date: d, minutes: 0, target };
  }
  let totalWorked = 0;
  for (const entry of allEntries) {
    if (dayMap[entry.work_date]) {
      dayMap[entry.work_date].minutes += entry.worked_minutes || 0;
      totalWorked += entry.worked_minutes || 0;
    }
  }
  const balance = totalWorked - weeklyTarget;
  const sundayStr = sunday.toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric' });
  const mondayStr = monday.toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit' });

  let html = `
    <div class="mobile-card__header">
      <h2 class="mobile-card__title">Übersicht</h2>
      ${_modeToggleHtml()}
    </div>
    <div class="mobile-overview-nav" aria-label="Woche wechseln">
      <button class="mobile-nav-button" data-ov-prev aria-label="Vorherige Woche">&lsaquo;</button>
      <span class="mobile-overview-nav__label">
        <strong>KW ${weekNum}</strong>
        <small>${mondayStr} – ${sundayStr}</small>
      </span>
      ${canNext
        ? '<button class="mobile-nav-button" data-ov-next aria-label="Nächste Woche">&rsaquo;</button>'
        : '<span class="mobile-nav-button is-disabled" aria-hidden="true">&rsaquo;</span>'}
    </div>
    <dl class="mobile-overview-summary">
      <div><dt>Arbeitszeit</dt><dd>${fmtMins(totalWorked)} Std</dd></div>
      <div><dt>Soll</dt><dd>${fmtMins(weeklyTarget)} Std</dd></div>
      <div><dt>Saldo</dt><dd class="${balance < 0 ? 'is-negative' : ''}">${balance < 0 ? '-' : ''}${fmtMins(Math.abs(balance))} Std</dd></div>
    </dl>
    <ul class="mobile-week-list mobile-week-list--grid">`;

  for (const ds of Object.keys(dayMap).sort()) {
    const { date, minutes, target } = dayMap[ds];
    const isToday = ds === isoDateStr(today);
    const label = date.toLocaleDateString('de-DE', { weekday: 'short', day: '2-digit', month: '2-digit' });
    html += `
      <li class="mobile-week-day${isToday ? ' is-today' : ''}">
        <span class="mobile-week-day__label">${escHtml(label)}</span>
        <span class="mobile-week-day__minutes">${fmtMins(minutes)} Std</span>
        ${target > 0 ? `<span class="mobile-week-day__target">Soll ${fmtMins(target)} Std</span>` : '<span class="mobile-week-day__target">frei</span>'}
      </li>`;
  }
  html += '</ul>';

  container.innerHTML = html;
  _overviewAttachNav(
    container,
    () => { overviewDate = new Date(prevMonday); },
    () => { if (canNext) overviewDate = new Date(nextMonday); },
    (mode) => { overviewMode = mode; if (mode === 'day') { overviewDate = new Date(today); } }
  );
}

// ── Client-side Salden (from cached metrics) ──────────────────────────────────

async function renderSalden() {
  const container = document.getElementById('salden-card');
  if (!container) return;

  const snapshot = await getRecord(DATA_STORE, 'snapshot');
  const m = snapshot?.data?.metrics;
  const vs = m?.vacation_summary;
  if (!m) {
    container.innerHTML = '<p class="mobile-empty-state">Keine lokalen Daten. Bitte online verbinden.</p>';
    return;
  }

  container.innerHTML = `
    <h2 class="mobile-card__title">Monatswerte</h2>
    <dl class="mobile-stats-grid">
      <div><dt>Ist</dt><dd>${fmtMins(m.worked_minutes)} Std</dd></div>
      <div><dt>Soll</dt><dd>${fmtMins(m.target_minutes)} Std</dd></div>
      <div><dt>Saldo</dt><dd class="${m.balance_minutes < 0 ? 'is-negative' : ''}">${fmtMins(m.balance_minutes)} Std</dd></div>
    </dl>
    ${vs ? `
    <h2 class="mobile-card__title" style="margin-top:0.75rem">Urlaubskonto</h2>
    <dl class="mobile-stats-grid">
      <div><dt>Jahresurlaub</dt><dd>${Number(vs.total_days || 0).toFixed(1)} Tage</dd></div>
      ${vs.carryover_days > 0 ? `<div><dt>Übertrag</dt><dd>${Number(vs.carryover_days).toFixed(1)} Tage</dd></div>` : ''}
      <div><dt>Genommen</dt><dd>${Number(vs.used_days || 0).toFixed(1)} Tage</dd></div>
      <div><dt>Geplant</dt><dd>${Number(vs.planned_days || 0).toFixed(1)} Tage</dd></div>
      <div><dt>Rest</dt><dd>${Number(vs.remaining_days || 0).toFixed(1)} Tage</dd></div>
    </dl>` : ''}`;
}

// ── Client-side Urlaubsliste (offline-fähig, aus Snapshot + Queue) ───────────

const VACATION_STATUS_LABELS = {
  approved: { label: 'Genehmigt', cls: 'approved' },
  pending: { label: 'Wartet auf Freigabe', cls: 'pending' },
  withdraw_requested: { label: 'Rücknahme angefragt', cls: 'withdraw' },
  cancelled: { label: 'Zurückgezogen', cls: 'cancelled' },
  rejected: { label: 'Abgelehnt', cls: 'rejected' },
};

function fmtDateDE(iso) {
  const date = new Date(`${String(iso || '').slice(0, 10)}T00:00:00`);
  if (Number.isNaN(date.getTime())) return iso || '';
  return date.toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric' });
}

// Zeichnet alle Urlaubsanträge des laufenden Jahres aus dem gespeicherten
// Serverstand und mischt die noch nicht übertragenen Anträge aus der
// Warteschlange dazu.
//
// Genau das hält übertragene Anträge sichtbar – früher verschwanden sie, weil
// sie nach der Übertragung niemand mehr aus dem Serverstand zeichnete.
async function renderVacations() {
  const list = document.querySelector(VACATION_LIST_SELECTOR);
  if (!list) return;
  const empty = document.querySelector(VACATION_EMPTY_SELECTOR);

  const snapshot = await getRecord(DATA_STORE, 'snapshot');
  const hasSnapshot = Array.isArray(snapshot?.data?.vacations);
  const serverVacations = hasSnapshot ? snapshot.data.vacations : [];

  const pending = await readPendingActions();
  const pendingVacations = pending
    .filter((action) => action.type === 'vacation')
    .map((action) => ({
      start_date: action.payload?.start_date,
      end_date: action.payload?.end_date,
      comment: action.payload?.comment || '',
      status: 'offline',
      _offline: true,
    }))
    .filter((v) => v.start_date && v.end_date);

  // Vor der ersten Übertragung gibt es noch keine gespeicherte Liste. Dann
  // bleibt stehen, was der Server bereits in die Seite geschrieben hat – besser
  // als eine leere Fläche.
  if (!hasSnapshot && pendingVacations.length === 0) return;

  const year = String(new Date().getFullYear());
  const inCurrentYear = (v) =>
    String(v.start_date).slice(0, 4) === year || String(v.end_date).slice(0, 4) === year;

  const all = [...pendingVacations, ...serverVacations].filter(inCurrentYear);
  all.sort((a, b) => String(b.start_date).localeCompare(String(a.start_date)));

  if (all.length === 0) {
    list.innerHTML = '';
    setElementHidden(list, true);
    if (empty) setElementHidden(empty, false);
    return;
  }
  setElementHidden(list, false);
  if (empty) setElementHidden(empty, true);

  list.innerHTML = all
    .map((v) => {
      const meta = v._offline
        ? { label: 'Synchronisation ausstehend', cls: 'offline' }
        : VACATION_STATUS_LABELS[v.status] || { label: 'Abgelehnt', cls: 'rejected' };
      const typ = v.use_overtime ? 'Überstundenabbau' : 'Urlaub';
      const comment = v.comment
        ? `<span class="mobile-vacation__comment">${escHtml(v.comment)}</span>`
        : '';
      let action = '';
      if (!v._offline && v.id != null && (v.status === 'pending' || v.status === 'approved')) {
        action = `<form method="post" action="/vacations/${v.id}/withdraw" class="mobile-vacation__action">
            <input type="hidden" name="csrf_token" value="${escHtml(getCsrfToken())}">
            <button type="submit" class="mobile-link-button">Zurückziehen</button>
          </form>`;
      } else if (v.status === 'withdraw_requested') {
        action = '<span class="mobile-vacation__badge">In Prüfung</span>';
      }
      return `
        <li class="mobile-vacation" data-status="${meta.cls}">
          <header class="mobile-vacation__header">
            <strong>${fmtDateDE(v.start_date)} – ${fmtDateDE(v.end_date)}</strong>
            <span class="mobile-vacation__status mobile-vacation__status--${meta.cls}">${escHtml(meta.label)}</span>
          </header>
          <div class="mobile-vacation__meta">
            <span>${typ}</span>
            ${comment}
          </div>
          ${action}
        </li>`;
    })
    .join('');
}

// ── Settings ─────────────────────────────────────────────────────────────────

async function loadSettings() {
  const owner = await outbox.identity();
  if (!owner) return { ...SETTINGS_DEFAULT };
  let record = await getRecord(META_STORE, `settings:${owner.id}`);
  if (!record) {
    const snapshot = await getRecord(DATA_STORE, 'snapshot');
    // The legacy record had no owner. Only migrate it with a matching snapshot.
    if (snapshot?.data?.user?.id === owner.id) {
      const legacy = await getRecord(META_STORE, 'settings');
      if (legacy && (!legacy.userId || legacy.userId === owner.id)) {
        record = { ...legacy, key: `settings:${owner.id}`, userId: owner.id };
        await putRecord(META_STORE, record);
        await putRecord(META_STORE, { ...legacy, userId: owner.id });
      }
    }
  }
  const saved = record?.value || {};
  // Backward compat: migrate old cacheDurationHours → syncDays
  if (saved.cacheDurationHours && !saved.syncDays) {
    saved.syncDays = Math.max(7, Math.round(saved.cacheDurationHours / 24)) || 30;
  }
  if (saved.syncDays) saved.syncDays = [7, 14, 30, 60, 90].find(days => days >= saved.syncDays) || 90;
  return { ...SETTINGS_DEFAULT, ...saved };
}

async function saveSettings(settings) {
  const owner = await outbox.identity();
  if (!owner) throw new Error('Zuerst online mit deinem Konto anmelden.');
  await putRecord(META_STORE, {
    key: `settings:${owner.id}`,
    userId: owner.id,
    value: { ...SETTINGS_DEFAULT, ...settings },
    updatedAt: Date.now(),
  });
}

async function isCacheStale() {
  const settings = await loadSettings();
  const lastSync = await getRecord(META_STORE, 'lastSyncAt');
  if (!lastSync?.value) return true;
  const elapsed = Date.now() - new Date(lastSync.value).getTime();
  return elapsed > settings.syncDays * 86400000;
}

async function updateSettingsTab() {
  const settings = await loadSettings();

  const select = document.getElementById('mobile-setting-cache-duration');
  if (select) select.value = String(settings.syncDays);

  const stale = await isCacheStale();
  // Der Hinweis auf veraltete Daten erscheint nur, wenn das Gerät wirklich ohne
  // Netz ist. Mit Netz wird gleich übertragen – der Hinweis wäre irreführend.
  const showStaleWarning = stale && !navigator.onLine;
  const cacheStatus = document.getElementById('mobile-cache-status');
  if (cacheStatus) {
    cacheStatus.textContent = showStaleWarning
      ? 'Offline-Daten möglicherweise veraltet – bitte mit Server verbinden.'
      : 'Offline-Daten sind aktuell.';
    cacheStatus.dataset.state = showStaleWarning ? 'warning' : 'ok';
  }

  const staleWarning = document.getElementById('mobile-stale-warning');
  if (staleWarning) {
    staleWarning.hidden = !showStaleWarning;
  }
}

async function initSettingsTab() {
  await updateSettingsTab();

  const select = document.getElementById('mobile-setting-cache-duration');
  if (select) {
    select.addEventListener('change', async () => {
      const days = Number(select.value);
      if ([7, 14, 30, 60, 90].includes(days)) {
        try {
          await saveSettings({ syncDays: days });
          showFeedback(
            `Datenzeitraum gesetzt: ${select.options[select.selectedIndex].text}.`,
            'info'
          );
        } catch (error) { showFeedback(`Nicht gespeichert: ${error.message}`, 'error'); }
      }
    });
  }

  const syncBtn = document.getElementById('mobile-sync-now-btn');
  if (syncBtn) syncBtn.addEventListener('click', () => performReconnectSync('manual'));
  const clearBtn = document.getElementById('mobile-clear-cache-btn');
  if (clearBtn) {
    clearBtn.textContent = 'Übersicht neu laden';
    clearBtn.addEventListener('click', async () => {
      // Only refresh derived display data. Outbox, account and receipts stay intact.
      await performReconnectSync('manual');
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
  window.addEventListener('offline', () => dispatchSyncStatus('Offline. Neue Buchungen werden auf diesem Gerät gespeichert.', 'offline'));
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') performReconnectSync('resume');
  });
  window.addEventListener('pageshow', () => performReconnectSync('resume'));
  // iOS has no Background Sync. Retry while visible; resume is mandatory.
  window.setInterval(() => {
    if (document.visibilityState === 'visible' && navigator.onLine) performReconnectSync('background');
  }, 15000);
  navigator.serviceWorker?.addEventListener('message', event => {
    if (event.data?.type === 'SYNC_COMPLETE') performReconnectSync('worker');
    if (event.data?.type === 'CAN_ACTIVATE') {
      const safe = canActivateUpdate();
      if (safe) {
        updateQuiesced = true;
        const dashboard = document.querySelector('.mobile-dashboard');
        if (dashboard) dashboard.inert = true;
        // Another tab may veto or disappear. Never leave this page disabled.
        setTimeout(() => { updateQuiesced = false; if (dashboard) dashboard.inert = false; }, 5000);
      }
      event.ports[0]?.postMessage({ safe });
    }
  });
}

function canActivateUpdate() {
  return !localWriteInFlight && !syncEngine.running && ![...dirtyForms].some(form => form.isConnected)
    && !document.querySelector('.modal.is-visible');
}

function setupServiceWorkerUpdateHandling() {
  if (!('serviceWorker' in navigator)) return;
  let reloaded = false;
  const hadController = !!navigator.serviceWorker.controller;
  navigator.serviceWorker.addEventListener('controllerchange', () => {
    // Only an explicitly accepted update reloads this tab. Persisted stamps survive.
    if (hadController && !reloaded && canActivateUpdate()) {
      reloaded = true;
      window.location.reload();
    } else if (!canActivateUpdate()) {
      showUpdateAvailable();
    }
  });
  const check = async () => {
    const registration = await navigator.serviceWorker.getRegistration();
    if (!registration) return;
    if (registration.waiting) showUpdateAvailable();
    registration.addEventListener('updatefound', () => {
      registration.installing?.addEventListener('statechange', () => {
        if (registration.waiting) showUpdateAvailable();
      });
    });
    await registration.update();
  };
  check().catch(() => {});
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') check().catch(() => {});
  });
}

function showUpdateAvailable() {
  const button = document.getElementById('sync-update');
  if (button) button.hidden = false;
}

async function handleServerVersion(serverVersion) {
  if (!serverVersion) return;
  const stored = await getRecord(META_STORE, 'appVersion');
  if (stored?.value === serverVersion) return;
  await putRecord(META_STORE, { key: 'appVersion', value: serverVersion, updatedAt: Date.now() });
  if (stored?.value) {
    // Neue Server-Version erkannt: Service-Worker-Update anstoßen; der
    // controllerchange-Handler lädt die Seite danach einmalig neu.
    navigator.serviceWorker?.getRegistration()
      .then((registration) => registration?.update())
      .catch(() => {});
  }
}

function installSyncPanel() {
  const container = document.querySelector('.mobile-dashboard');
  if (!container) return;
  for (const name of ['input', 'change']) container.addEventListener(name, event => {
    const form = event.target.closest('form');
    if (form) dirtyForms.add(form);
  });
  container.addEventListener('reset', event => dirtyForms.delete(event.target));
  const panel = document.createElement('section');
  panel.id = 'sync-status';
  panel.className = 'sync-status';
  panel.setAttribute('aria-label', 'Buchungssicherheit und Synchronisation');
  panel.innerHTML = `<div role="status" aria-live="polite" aria-atomic="true">
    <strong data-sync-label>Synchronisation wird vorbereitet</strong>
    <p data-sync-message>Gespeicherte Buchungen werden geprüft.</p></div>
    <div class="sync-status__actions">
      <button type="button" class="button small" data-sync-retry>Jetzt abgleichen</button>
      <a href="/login" class="button small" data-sync-login hidden>Erneut anmelden</a>
      <button type="button" class="button small" id="sync-update" hidden>Update verfügbar · jetzt laden</button>
      <a href="#einstellungen" class="button ghost small" data-mobile-open="einstellungen">Details &amp; Sicherung</a>
    </div>
    <details><summary>Buchungen und Synchronisationsdetails</summary>
      <p data-sync-owner></p><p data-sync-count></p><p data-sync-last></p>
      <ul data-sync-entries></ul><p data-sync-decision></p>
      <button type="button" class="button ghost small" data-sync-export>Buchungen als Sicherung exportieren</button>
      <label class="sync-import">Buchungssicherung wiederherstellen
        <input type="file" data-sync-import accept="application/json,.json">
      </label>
      <button type="button" class="button ghost small" data-sync-identity hidden>Alte Buchungen meinem Konto zuordnen</button>
      <p class="muted">Ausstehende Buchungen bleiben bis zur Bestätigung erhalten. Bei Problemen die App nicht löschen.
      Safari/iOS kann Website-Daten entfernen; die Sicherung enthält deine lokalen Buchungen.</p>
    </details>`;
  container.querySelector('header')?.after(panel);
  panel.querySelector('[data-sync-retry]').addEventListener('click', () => performReconnectSync('manual'));
  panel.querySelector('details').addEventListener('toggle', () => renderSyncDetails().catch(error => dispatchSyncStatus(error.message, 'storage')));
  panel.querySelector('[data-sync-export]').addEventListener('click', async () => {
    try {
      const backup = { format: 'erfassung-outbox-1', exportedAt: new Date().toISOString(), owner: await outbox.identity(),
        actions: await outbox.pending(), receipts: (await outbox.all(DATA_STORE)).filter(row => row.key.startsWith('receipt:')) };
      const url = URL.createObjectURL(new Blob([JSON.stringify(backup, (key, value) => key === 'csrf_token' ? undefined : value, 2)], { type: 'application/json' }));
      const link = document.createElement('a'); link.href = url; link.download = 'erfassung-buchungssicherung.json'; link.click();
      setTimeout(() => URL.revokeObjectURL(url), 30000);
    } catch (error) { dispatchSyncStatus(error.message, 'storage'); }
  });
  panel.querySelector('[data-sync-import]').addEventListener('change', async event => {
    try {
      const file = event.target.files[0];
      if (!file) return;
      if (file.size > 10 * 1024 * 1024) throw new Error('Die Sicherung ist zu groß (maximal 10 MB).');
      const backup = JSON.parse(await file.text());
      if (!confirm('Diese Buchungssicherung für dein Konto wiederherstellen? Vorhandene Buchungen bleiben erhalten.')) return;
      localWriteInFlight++;
      try { await outbox.restore(backup); } finally { localWriteInFlight--; }
      await performReconnectSync('manual');
    } catch (error) { dispatchSyncStatus(error.message, 'storage'); }
    finally { event.target.value = ''; }
  });
  panel.querySelector('[data-sync-identity]').addEventListener('click', async () => {
    try {
      const session = await syncEngine.request('/api/mobile/session');
      if (await outbox.identity()) return;
      const entries = await outbox.pending();
      if (!entries.length) return;
      if (!confirm(`${entries.length} alte Buchungen ohne Kontozuordnung gefunden. Gehören ALLE zu ${session.user.name}? Nur dann bestätigen. Andernfalls zuerst exportieren und prüfen lassen.`)) return;
      await outbox.put(META_STORE, { key: 'owner', ...session.user });
      await outbox.identity();
      await performReconnectSync('manual');
    } catch (error) { dispatchSyncStatus(error.message, error.state || 'error'); }
  });
  panel.querySelector('#sync-update').addEventListener('click', async () => {
    if (!canActivateUpdate()) { showFeedback('Bitte Eingabe abschließen und den laufenden Abgleich abwarten.', 'info'); return; }
    const registration = await navigator.serviceWorker.getRegistration();
    if (!registration?.waiting) { window.location.reload(); return; }
    window.erfassungUpdateAccepted = true;
    const channel = new MessageChannel();
    channel.port1.onmessage = event => {
      if (!event.data?.accepted) {
        window.erfassungUpdateAccepted = false;
        showFeedback('In einem anderen Fenster läuft noch eine Eingabe. Bitte dort abschließen oder das Fenster schließen.', 'info');
      }
      channel.port1.close();
    };
    registration.waiting.postMessage({ type: 'ACTIVATE_UPDATE' }, [channel.port2]);
  });
}

async function renderSyncDetails() {
  const panel = document.getElementById('sync-status');
  if (!panel) return;
  const owner = await outbox.identity();
  const entries = await outbox.pending();
  const last = await getRecord(META_STORE, 'lastSyncAt');
  panel.querySelector('[data-sync-owner]').textContent = owner ? `Konto: ${owner.name || owner.id}` : 'Konto noch nicht zugeordnet';
  panel.querySelector('[data-sync-count]').textContent = `${entries.length} Buchung(en) noch nicht abschließend bestätigt`;
  panel.querySelector('[data-sync-last]').textContent = last?.value ? `Letzter vollständiger Abgleich: ${new Date(last.value).toLocaleString('de-DE')}` : 'Noch kein vollständiger Abgleich';
  updateLastSyncLabel(last?.value);
  const list = panel.querySelector('[data-sync-entries]');
  list.replaceChildren();
  for (const entry of entries) {
    const li = document.createElement('li');
    const label = ({ start_work: 'Arbeitszeit starten', end_work: 'Arbeitszeit beenden', start_break: 'Pause starten',
      end_break: 'Pause beenden', start_company: 'Auftrag starten', end_company: 'Auftrag beenden', update_notes: 'Kommentar' })[entry.payload?.action] || 'Urlaubsantrag';
    li.textContent = `${label} · ${entry.payload?.event_time ? new Date(entry.payload.event_time).toLocaleString('de-DE') : new Date(entry.createdAt).toLocaleString('de-DE')} · ${entry.status === 'conflict' ? 'Wartet auf Freigabe' : 'Lokal gespeichert'}${entry.message ? `: ${entry.message}` : ''}`;
    list.appendChild(li);
  }
  const decision = await getRecord(META_STORE, 'lastDecision');
  panel.querySelector('[data-sync-decision]').textContent = decision ? `Eine Buchung wurde bei der Prüfung abgelehnt: ${decision.message}` : '';
}

window.addEventListener('DOMContentLoaded', async () => {
  installSyncPanel();
  try {
  // Das heutige Datum in der Offline-Hülle setzen; das statische HTML bringt
  // keines vom Server mit.
  const offlineDateEl = document.getElementById('offline-shell-date');
  if (offlineDateEl) {
    offlineDateEl.textContent = new Date().toLocaleDateString('de-DE', {
      weekday: 'long', day: '2-digit', month: '2-digit', year: 'numeric',
    });
  }

  // ── Phase 1: Immediate local rendering (works offline) ─────────────────────
  registerTabHandling();
  registerMobileInterface();
  registerModalHandling();
  registerNotesModal();
  registerOfflineForms();
  registerCompanySearch();
  setupConnectionHandlers();
  setupServiceWorkerUpdateHandling();
  initializeServerStateFromDataset();
  await outbox.identity();
  await hydrateMobileInterface();
  await initializeSyncMeta();
  await initSettingsTab();
  await hydrateCompaniesFromCache();
  await hydrateLocationsFromCache();
  await hydratePermissionsFromCache();
  await recomputeEffectiveState();
  // Mit dem zeichnen, was bereits in der IndexedDB liegt – womöglich aus einer
  // früheren Sitzung.
  renderOverview().catch(() => {});
  renderSalden().catch(() => {});
  renderVacations().catch(() => {});

  // ── Phase 2: Attempt server sync (non-blocking for app startup) ────────────
  try {
    await performReconnectSync('startup');
  } catch { /* sync failure is non-fatal */ }
  await updateSettingsTab();

  } catch (error) {
    dispatchSyncStatus(error.message, 'storage');
  }
});
