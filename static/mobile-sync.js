/* Shared by the page and the classic service worker. No DOM dependencies. */
(function (root) {
  'use strict';
  const DB_NAME = 'erfassung-mobile';
  const DB_VERSION = 5;
  const ACTIONS = 'pendingActions', DATA = 'mobileData', META = 'meta';

  class StorageError extends Error {}
  class SyncError extends Error {
    constructor(message, state = 'error') { super(message); this.state = state; }
  }

  class MobileStore {
    constructor(factory = root.indexedDB) { this.factory = factory; this.connection = null; this.opening = null; }
    async open() {
      if (!this.factory) throw new StorageError('Lokaler Speicher fehlt. Die Buchung wurde nicht gespeichert.');
      if (this.connection) return this.connection;
      if (this.opening) return this.opening;
      this.opening = new Promise((resolve, reject) => {
        let settled = false;
        const request = this.factory.open(DB_NAME, DB_VERSION);
        const timer = setTimeout(() => {
          settled = true;
          reject(new StorageError('Lokaler Speicher blockiert. Andere Erfassung-Fenster schließen und erneut versuchen.'));
        }, 5000);
        request.onupgradeneeded = () => {
          const db = request.result;
          if (!db.objectStoreNames.contains(ACTIONS)) {
            const store = db.createObjectStore(ACTIONS, { keyPath: 'clientActionId' });
            store.createIndex('createdAt', 'createdAt');
          }
          if (!db.objectStoreNames.contains(DATA)) db.createObjectStore(DATA, { keyPath: 'key' });
          if (!db.objectStoreNames.contains(META)) db.createObjectStore(META, { keyPath: 'key' });
          // Existing records/IDs are retained; ownership is migrated from the
          // last authenticated snapshot by identity(), never guessed at login.
        };
        request.onerror = () => { clearTimeout(timer); reject(new StorageError(request.error?.message || 'Speicher nicht verfügbar')); };
        request.onsuccess = () => {
          clearTimeout(timer);
          const db = request.result;
          if (settled) { db.close(); return; }
          db.onversionchange = () => { db.close(); this.connection = null; };
          db.onclose = () => { this.connection = null; };
          this.connection = db;
          resolve(db);
        };
      }).finally(() => { this.opening = null; });
      return this.opening;
    }
    async transact(names, mode, callback) {
      const db = await this.open();
      return new Promise((resolve, reject) => {
        let tx, result;
        try { tx = db.transaction(names, mode); result = callback(tx); }
        catch (error) { if (tx) tx.abort(); reject(new StorageError(error.message)); return; }
        tx.oncomplete = () => resolve(typeof result === 'function' ? result() : result?.result);
        tx.onabort = tx.onerror = () => reject(new StorageError(tx.error?.message || 'Buchung konnte nicht dauerhaft gespeichert werden.'));
      });
    }
    withStore(name, mode, callback) { return this.transact([name], mode, tx => callback(tx.objectStore(name))); }
    get(name, key) { return this.withStore(name, 'readonly', s => s.get(key)); }
    put(name, value) { return this.withStore(name, 'readwrite', s => s.put(value)); }
    remove(name, key) { return this.withStore(name, 'readwrite', s => s.delete(key)); }
    async all(name) { return (await this.withStore(name, 'readonly', s => s.getAll())) || []; }
    async identity() {
      let owner = await this.get(META, 'owner');
      if (!owner) {
        const snapshot = await this.get(DATA, 'snapshot');
        if (snapshot?.data?.user?.id) {
          owner = { key: 'owner', id: snapshot.data.user.id, name: snapshot.data.user.full_name || '' };
          await this.put(META, owner);
        }
      }
      if (owner) {
        await this.withStore(ACTIONS, 'readwrite', s => {
          const cursor = s.openCursor();
          cursor.onsuccess = () => {
            const item = cursor.result;
            if (!item) return;
            if (!item.value.ownerId) item.update({ ...item.value, ownerId: owner.id, status: 'queued' });
            item.continue();
          };
          return cursor;
        });
      }
      return owner;
    }
    async enqueue(type, payload) {
      const owner = await this.identity();
      if (!owner) throw new StorageError('Zuerst online anmelden, damit Buchungen eindeutig deinem Konto zugeordnet sind.');
      const clientActionId = payload.client_action_id || root.crypto.randomUUID();
      payload = { ...payload };
      delete payload.csrf_token;
      // add(), not put(): an accidental ID reuse must never overwrite an event.
      await this.transact([ACTIONS, META], 'readwrite', tx => {
        const meta = tx.objectStore(META);
        const read = meta.get('lastEnqueuedAt');
        read.onsuccess = () => {
          const createdAt = Math.max(Date.now(), (read.result?.value || 0) + 1);
          meta.put({ key: 'lastEnqueuedAt', value: createdAt });
          tx.objectStore(ACTIONS).add({ clientActionId, type, payload: { ...payload, client_action_id: clientActionId },
            ownerId: owner.id, createdAt, status: 'queued', attempts: 0, retryAt: 0 });
        };
        return read;
      });
      return clientActionId;
    }
    async pending() {
      return (await this.all(ACTIONS)).sort((a, b) => (a.createdAt || 0) - (b.createdAt || 0)
        || String(a.clientActionId).localeCompare(String(b.clientActionId)));
    }
    async acknowledge(entry, receipt) {
      // Archive acknowledgement and remove outbox item in one durable commit.
      await this.transact([ACTIONS, DATA], 'readwrite', tx => {
        tx.objectStore(DATA).put({ key: `receipt:${entry.clientActionId}`, entry, receipt, savedAt: Date.now() });
        tx.objectStore(ACTIONS).delete(entry.clientActionId);
      });
    }
    async restore(backup) {
      const owner = await this.identity();
      if (!owner || backup?.format !== 'erfassung-outbox-1' || backup.owner?.id !== owner.id
          || !Array.isArray(backup.actions) || backup.actions.length > 10000) {
        throw new StorageError('Die Sicherung gehört nicht zu diesem Konto oder hat ein ungültiges Format.');
      }
      const entries = backup.actions;
      for (const entry of entries) {
        if (entry.ownerId !== owner.id || !/^[\w.-]{1,191}$/.test(entry.clientActionId)
            || !['punch', 'vacation'].includes(entry.type) || !Number.isFinite(entry.createdAt)
            || !entry.payload || Object.values(entry.payload).some(value => typeof value !== 'string' || value.length > 8000)) {
          throw new StorageError('Ungültige Buchung in der Sicherung. Es wurde nichts importiert.');
        }
      }
      const canonical = value => JSON.stringify(Object.fromEntries(Object.entries(value).filter(([key]) => key !== 'csrf_token').sort()));
      await this.transact([ACTIONS, META], 'readwrite', tx => {
        const actions = tx.objectStore(ACTIONS);
        for (const entry of entries) {
          const read = actions.get(entry.clientActionId);
          read.onsuccess = () => {
            if (read.result) {
              if (read.result.type !== entry.type || canonical(read.result.payload) !== canonical(entry.payload)) tx.abort();
              return;
            }
            const payload = { ...entry.payload }; delete payload.csrf_token;
            actions.add({ ...entry, payload, status: 'queued', retryAt: 0 });
          };
        }
        const meta = tx.objectStore(META), read = meta.get('lastEnqueuedAt');
        read.onsuccess = () => meta.put({ key: 'lastEnqueuedAt', value: Math.max(read.result?.value || 0, ...entries.map(e => e.createdAt)) });
        return read;
      });
    }
    async lease(owner, release = false) {
      return this.transact([META], 'readwrite', tx => {
        const store = tx.objectStore(META);
        const read = store.get('outboxLease');
        let acquired = false;
        read.onsuccess = () => {
          const current = read.result;
          if (current && current.owner !== owner && current.until > Date.now()) return;
          if (release) {
            if (current?.owner === owner) store.delete('outboxLease');
          } else {
            store.put({ key: 'outboxLease', owner, until: Date.now() + 30000 });
            acquired = true;
          }
        };
        return () => acquired;
      });
    }
    close() { this.connection?.close(); this.connection = null; }
  }

  class SyncEngine {
    constructor(store, { fetch: fetcher = root.fetch.bind(root), notify = () => {}, snapshot = async () => {} } = {}) {
      this.store = store; this.fetcher = fetcher; this.notify = notify; this.snapshot = snapshot;
      this.running = null; this.requested = false; this.leaseId = root.crypto.randomUUID();
    }
    async request(url, options = {}, timeout = 10000) {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), timeout);
      try {
        const response = await this.fetcher(url, { credentials: 'same-origin', cache: 'no-store',
          redirect: 'error', ...options, signal: controller.signal });
        if (response.status === 401) throw new SyncError('Bitte erneut anmelden. Alle Buchungen bleiben lokal gespeichert.', 'auth');
        if (response.status === 403) throw new SyncError('Sitzung oder Berechtigung prüfen. Buchungen bleiben erhalten.', 'auth');
        if (!response.ok) throw new SyncError(`Serverfehler (${response.status}). Erneuter Versuch folgt.`);
        if (!(response.headers.get('content-type') || '').includes('application/json')) throw new SyncError('Unklare Serverantwort. Keine Buchung wird gelöscht.');
        return await response.json();
      } finally { clearTimeout(timer); }
    }
    async connect() {
      const session = await this.request('/api/mobile/session');
      if (session.protocol !== 1 || !Number.isInteger(session.user?.id) || !session.csrf_token) throw new SyncError('Serverversion unterstützt den sicheren Abgleich nicht.');
      const owner = await this.store.identity();
      const pending = await this.store.pending();
      if ((owner && owner.id !== session.user.id) || pending.some(item => item.ownerId && item.ownerId !== session.user.id)) {
        throw new SyncError(`Bitte als ${owner?.name || 'ursprünglicher Benutzer'} anmelden. Die vorhandenen Buchungen bleiben erhalten.`, 'account');
      }
      if (!owner && pending.length) throw new SyncError('Alte Buchungen ohne Kontozuordnung gefunden. Bitte in den Sync-Details prüfen und zuordnen.', 'identity');
      if (!owner) await this.store.put(META, { key: 'owner', ...session.user });
      return session;
    }
    run(force = false) {
      if (this.running) { this.requested = true; return this.running; }
      this.running = this.drain(force).finally(() => {
        this.running = null;
        if (this.requested) { this.requested = false; setTimeout(() => this.run(), 0); }
      });
      return this.running;
    }
    async drain(force) {
      let held = false;
      let finalStatus;
      const report = (...status) => { finalStatus = status; };
      try {
        if (root.navigator?.onLine === false) {
          report('offline', 'Offline. Buchungen bleiben auf diesem Gerät gespeichert.');
          return false;
        }
        held = await this.store.lease(this.leaseId);
        if (!held) { report('queue', 'Ein anderes Erfassung-Fenster synchronisiert.'); return false; }
        this.notify('syncing', 'Buchungen werden abgeglichen …');
        const session = await this.connect();
        do {
          this.requested = false;
          const pending = await this.store.pending();
          for (const entry of pending) {
            if (entry.retryAt > Date.now() && !force) {
              report(entry.status === 'conflict' ? 'conflict' : entry.status === 'auth' ? 'auth' : 'queue',
                entry.status === 'conflict' ? 'Buchung wartet auf Freigabe; Original bleibt erhalten.' : entry.message || 'Erneuter Versuch folgt automatisch.');
              return false;
            }
            if (!await this.store.lease(this.leaseId)) throw new SyncError('Abgleich wurde von einem anderen Fenster übernommen.');
            try {
              const receipt = await this.request('/api/mobile/actions', {
                method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': session.csrf_token },
                body: JSON.stringify({ protocol: 1, owner_id: entry.ownerId, client_action_id: entry.clientActionId,
                  kind: entry.type, payload: entry.payload }),
              });
              if (receipt.protocol !== 1 || receipt.received !== true || receipt.owner_id !== entry.ownerId
                  || receipt.client_action_id !== entry.clientActionId || !Number.isInteger(receipt.receipt_id)
                  || !['applied', 'conflict', 'rejected'].includes(receipt.status)) {
                throw new SyncError('Die Serverbestätigung passt nicht zur Buchung. Buchung bleibt erhalten.');
              }
              if (receipt.status === 'conflict') {
                await this.store.put(ACTIONS, { ...entry, status: 'conflict', message: receipt.message, receipt,
                  retryAt: Date.now() + 30000 });
                report('conflict', 'Eine Buchung wartet auf Freigabe. Nachfolgende Buchungen bleiben gespeichert.');
                return false;
              }
              await this.store.acknowledge(entry, receipt);
              if (receipt.status === 'rejected') await this.store.put(META, { key: 'lastDecision', message: receipt.resolution_note, at: Date.now() });
            } catch (error) {
              const attempts = (entry.attempts || 0) + 1;
              const delay = Math.min(60000, 2000 * 2 ** Math.min(attempts - 1, 5)) * (0.8 + Math.random() * 0.4);
              await this.store.put(ACTIONS, { ...entry, status: error.state === 'auth' ? 'auth' : 'retry', attempts,
                retryAt: Date.now() + delay, message: error.message });
              throw error;
            }
          }
        } while (this.requested);
        // Snapshot is independent of upload: a slow report must not hold the outbox.
        const fresh = await this.snapshot(session);
        if (fresh === false) throw new SyncError('Buchungen übertragen; die Übersicht konnte noch nicht aktualisiert werden.');
        if ((await this.store.pending()).length) {
          this.requested = true;
          report('queue', 'Weitere Buchungen werden anschließend übertragen.');
          return false;
        }
        const now = new Date().toISOString();
        await this.store.put(META, { key: 'lastSyncAt', value: now, updatedAt: Date.now() });
        report('synced', 'Alle Buchungen sind auf dem Server angekommen.');
        return true;
      } catch (error) {
        report(error instanceof StorageError ? 'storage' : error.state || (root.navigator?.onLine === false ? 'offline' : 'error'), error.message);
        return false;
      } finally {
        if (held) {
          try { await this.store.lease(this.leaseId, true); }
          catch (error) { report('storage', error.message); }
        }
        if (finalStatus) this.notify(...finalStatus);
      }
    }
  }
  const exported = { MobileStore, SyncEngine, StorageError, SyncError, DB_NAME, DB_VERSION, ACTIONS, DATA, META };
  root.ErfassungSync = exported;
  if (typeof module !== 'undefined' && module.exports) module.exports = exported;
})(globalThis);
