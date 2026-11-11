const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {webcrypto} = require('node:crypto');
const {IDBFactory} = require('fake-indexeddb');

async function fixture(t) {
  const context = vm.createContext({
    indexedDB: new IDBFactory(), crypto: webcrypto, setTimeout, clearTimeout,
    URLSearchParams, location: {search: ''}, navigator: {onLine: false},
    fetch: async () => { throw new Error('These local preference tests must not use the network'); },
    document: {querySelector: () => null, querySelectorAll: () => [], getElementById: () => null},
    window: {addEventListener() {}},
  });
  vm.runInContext(fs.readFileSync('static/mobile-sync.js', 'utf8'), context);
  vm.runInContext(fs.readFileSync('static/mobile.js', 'utf8').replace("import './mobile-sync.js';", '') + `
    globalThis.testInterface = {
      store: outbox, cacheOverviewPreference, hydrateMobileInterface, loadSettings, saveSettings,
      applyPunchActionToState, buildStateFromEntry, isLongRunning,
      mode: () => overviewMode,
      chooseMode: value => { overviewMode = value; overviewInteracted = true; },
    };
  `, context);
  const api = context.testInterface;
  t.after(() => api.store.close());
  await api.store.put('meta', {key: 'owner', id: 7, name: 'Original'});
  return api;
}

test('the saved PWA overview belongs only to its outbox owner', async t => {
  const api = await fixture(t);
  assert.equal(await api.cacheOverviewPreference(8, 'week'), false);
  assert.equal(await api.cacheOverviewPreference(7, 'month'), false);
  assert.equal(await api.store.get('meta', 'overview-preference:8'), undefined);
  assert.equal(await api.cacheOverviewPreference(7, 'week'), true);
  const record = await api.store.get('meta', 'overview-preference:7');
  assert.equal(record.userId, 7);
  assert.equal(record.value, 'week');
});

test('offline replay retains original start times and warns after twelve hours', async t => {
  const api = await fixture(t);
  const start = Date.now() - 13 * 3600000;
  const state = api.applyPunchActionToState(api.buildStateFromEntry(null), 'start_work', {event_time: new Date(start).toISOString()});
  assert.equal(state.startedAtMs, start);
  assert.equal(api.isLongRunning(state), true);
  assert.equal(api.isLongRunning({...state, startedAtMs: Date.now() - 11 * 3600000}), false);
  const stopped = api.applyPunchActionToState(state, 'correct_end_work', {event_time: new Date(start + 8 * 3600000).toISOString()});
  assert.equal(stopped.isWorking, false);
  assert.equal(api.isLongRunning(stopped), false);
});

test('confirmed start uses its UTC offset instead of the device timezone', async t => {
  const api = await fixture(t);
  const state = api.buildStateFromEntry({is_open: true, started_at: '2026-10-25T02:30:00+01:00', work_date: '2026-10-25', start_time: '02:30:00'});
  assert.equal(state.startedAtMs, Date.parse('2026-10-25T01:30:00Z'));
});

test('reconnecting respects a temporary view and never borrows a foreign snapshot preference', async t => {
  const api = await fixture(t);
  await api.store.put('mobileData', {key: 'snapshot', data: {user: {id: 7, overview_preference: 'week'}}});
  await api.hydrateMobileInterface();
  assert.equal(api.mode(), 'week');
  api.chooseMode('day');
  await api.hydrateMobileInterface();
  assert.equal(api.mode(), 'day');
  assert.equal((await api.store.get('meta', 'overview-preference:7')).value, 'week');
  await api.store.put('mobileData', {key: 'snapshot', data: {user: {id: 8, overview_preference: 'day'}}});
  await api.hydrateMobileInterface();
  assert.equal((await api.store.get('meta', 'overview-preference:7')).value, 'week');
  assert.equal(await api.store.get('meta', 'overview-preference:8'), undefined);
});

test('legacy cache duration migrates once, retains at least a week, and stays account scoped', async t => {
  const api = await fixture(t);
  await api.store.put('meta', {key: 'settings', value: {cacheDurationHours: 24}});
  await api.store.put('mobileData', {key: 'snapshot', data: {user: {id: 7}}});
  assert.equal((await api.loadSettings()).syncDays, 7);
  await api.saveSettings({syncDays: 90});
  assert.equal((await api.loadSettings()).syncDays, 90);
  await api.store.put('meta', {key: 'owner', id: 8, name: 'Other'});
  await api.store.put('mobileData', {key: 'snapshot', data: {user: {id: 8}}});
  assert.equal((await api.loadSettings()).syncDays, 30);
  await api.saveSettings({syncDays: 14});
  assert.equal((await api.store.get('meta', 'settings:7')).value.syncDays, 90);
  assert.equal((await api.store.get('meta', 'settings:8')).value.syncDays, 14);
});

test('appearance and cache changes preserve pending bookings, receipts and ownership', async t => {
  const api = await fixture(t);
  await api.store.enqueue('punch', {action: 'start_work', event_time: '2026-11-04T08:00:00'});
  await api.store.put('mobileData', {key: 'receipt:existing', value: {receipt_id: 12, status: 'applied'}});
  const before = JSON.stringify(await api.store.pending());
  await api.cacheOverviewPreference(7, 'week');
  await api.saveSettings({syncDays: 60});
  assert.equal(JSON.stringify(await api.store.pending()), before);
  assert.equal((await api.store.identity()).id, 7);
  assert.equal((await api.store.get('mobileData', 'receipt:existing')).value.receipt_id, 12);
});
