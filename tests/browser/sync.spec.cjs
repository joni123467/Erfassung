const {test:base,expect}=require('@playwright/test');
const {execFileSync}=require('node:child_process');
const {randomUUID}=require('node:crypto');
const fs=require('node:fs'),path=require('node:path');
const {RECOVERY_TIMEOUT,RECOVERY_TEST_TIMEOUT,waitForRecoveredSync}=require('./sync-recovery.cjs');
const test=base.extend({
  account:async({},use)=>{
    const username=`pwa-${randomUUID().slice(0,10)}`;
    execFileSync(process.env.ERFASSUNG_PYTHON,['tests/browser/create_user.py',username],{env:process.env});
    await use(username);
  },
});
async function login(page,account,{recovery=false}={}){
  const options=recovery?{timeout:RECOVERY_TIMEOUT}:{};
  await page.goto('/login');
  await page.locator('[name=username]').fill(account);
  await page.locator('[name=password]').fill('Browser!12345');
  await Promise.all([page.waitForURL('**/dashboard'),page.locator('button[type=submit]').click()]);
  await page.goto('/mobile');
  await expect(page.locator('[data-sync-label]')).toHaveText('Synchronisiert',options);
  // Wait for control without aborting a startup/resume sync with an artificial
  // reload. Reload/restart behavior is exercised explicitly by the relevant tests.
  await page.evaluate(async()=>{
    await navigator.serviceWorker.ready;
    if(!navigator.serviceWorker.controller)await new Promise(resolve=>navigator.serviceWorker.addEventListener('controllerchange',resolve,{once:true}));
  });
  await expect(page.locator('[data-sync-label]')).toHaveText('Synchronisiert',options);
}
async function pending(page){return page.evaluate(async()=>{const s=new ErfassungSync.MobileStore();try{return await s.pending();}finally{s.close();}});}
async function queue(page,action='start_work',eventTime){return page.evaluate(async({action,eventTime})=>{const s=new ErfassungSync.MobileStore();try{return await s.enqueue('punch',{action,event_time:eventTime||new Date().toISOString()});}finally{s.close();}},{action,eventTime});}
async function count(page,n){await expect.poll(async()=>(await pending(page)).length).toBe(n);}
async function sync(page){await page.locator('[data-sync-retry]').click();}
function networkFault(mode){
  const marker=path.join(process.env.ERFASSUNG_E2E_ROOT,'network-fault');
  fs.writeFileSync(marker,mode);
  return ()=>fs.rmSync(marker,{force:true});
}

// A real form/IndexedDB/server round trip, with the service worker controlling navigation.
test('online stamp is saved and acknowledged',async({page,account})=>{
  await login(page,account);
  await page.locator('form[data-offline="punch"]').filter({has:page.locator('input[name=action][value=start_work]')}).locator('button[type=submit]').click();
  // Enqueue is asynchronous: the previous empty queue and sync label can
  // still be visible immediately after click. Wait for the saved booking.
  await expect.poll(async()=>{
    const response=await page.request.get('/mobile/sync-data');
    return(await response.json()).active_entry;
  }).toBeTruthy();
  await expect(page.locator('[data-sync-label]')).toHaveText('Synchronisiert');
  await count(page,0);
  const data=await page.request.get('/mobile/sync-data');
  expect((await data.json()).active_entry).toBeTruthy();
});

test('offline stamp survives page close and seven-day-old events sync in order',async({page,context,account})=>{
  // A closed page may retain its 30-second ownership lease until expiry.
  // Allow that lease plus the existing 15-second visible-client retry, without
  // weakening ownership or adding global retries to the suite.
  test.setTimeout(RECOVERY_TEST_TIMEOUT);
  await login(page,account);
  await context.setOffline(true);
  const day=new Date(Date.now()-7*86400000);day.setUTCHours(8,0,0,0);
  const start=day.toISOString(),ids=[];
  ids.push(await queue(page,'start_work',start));
  ids.push(await queue(page,'start_break',new Date(Date.parse(start)+3*3600000).toISOString()));
  ids.push(await queue(page,'end_break',new Date(Date.parse(start)+3.5*3600000).toISOString()));
  ids.push(await queue(page,'end_work',new Date(Date.parse(start)+8*3600000).toISOString()));
  await count(page,4);
  await page.close();
  const resumed=await context.newPage();await resumed.goto('/mobile');
  await expect(resumed.locator('#sync-status')).toBeVisible();await count(resumed,4);
  await context.setOffline(false);await sync(resumed);
  await waitForRecoveredSync(resumed);
  const response=await resumed.request.get('/mobile/sync-data');
  const saved=await response.json();
  expect(saved.active_entry).toBeNull();
  expect(saved.entries).toHaveLength(1);
  expect(saved.entries[0]).toMatchObject({worked_minutes:450,total_break_minutes:30,status:'approved'});
  const receipts=await resumed.evaluate(async ids=>{
    const store=new ErfassungSync.MobileStore();
    try{return await Promise.all(ids.map(async id=>(await store.get('mobileData',`receipt:${id}`))?.receipt));}
    finally{store.close();}
  },ids);
  expect(receipts.map(receipt=>receipt.client_action_id)).toEqual(ids);
  expect(new Set(receipts.map(receipt=>receipt.receipt_id)).size).toBe(4);
});

test('expired login preserves events and re-login continues',async({page,account,context})=>{
  test.setTimeout(RECOVERY_TEST_TIMEOUT);
  await login(page,account);await context.setOffline(true);await queue(page);await count(page,1);
  await context.clearCookies();await context.setOffline(false);await sync(page);
  await expect(page.locator('[data-sync-label]')).toHaveText('Anmeldung erforderlich');await count(page,1);
  await login(page,account,{recovery:true});await waitForRecoveredSync(page);
});

test('server rejection stays visible until reviewed',async({page,account})=>{
  test.setTimeout(RECOVERY_TEST_TIMEOUT);
  await login(page,account);await queue(page,'end_work');await sync(page);
  await expect(page.locator('[data-sync-label]')).toHaveText('Freigabe erforderlich');await count(page,1);
  await expect(page.locator('[data-sync-message]')).toContainText('Keine laufende Arbeitszeit');
  await expect(page.locator('[data-sync-message]')).toContainText('Synchronisationskonflikte');
  await page.reload();await expect(page.locator('[data-sync-label]')).toHaveText('Freigabe erforderlich',{timeout:RECOVERY_TIMEOUT});await count(page,1);
  await expect(page.locator('[data-sync-message]')).toContainText('Keine laufende Arbeitszeit');
});

test('forgotten clock-out survives offline restart and records the chosen end',async({page,context,account})=>{
  test.setTimeout(RECOVERY_TEST_TIMEOUT);
  await page.setViewportSize({width:390,height:844});
  await login(page,account);await context.setOffline(true);
  const start=new Date(Date.now()-14*3600000);start.setSeconds(0,0);
  const end=new Date(start.getTime()+8*3600000);
  const startId=await queue(page,'start_work',start.toISOString());
  await page.reload();await count(page,1);
  const warning=page.locator('#mobile-long-running');
  await expect(warning).toBeVisible();
  await warning.locator('button').click();
  const dialog=page.locator('#mobile-end-review');
  await expect(dialog).toBeVisible();
  await dialog.locator('[data-end-cancel]').click();await count(page,1);
  await warning.locator('button').click();
  const localEnd=await page.evaluate(iso=>{
    const d=new Date(iso),pad=n=>String(n).padStart(2,'0');
    return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  },end.toISOString());
  await dialog.locator('[name=actual_end]').fill(localEnd);
  await dialog.locator('[name=correction_reason]').fill('Ausstempeln vergessen');
  expect(await dialog.evaluate(el=>el.getBoundingClientRect().right<=innerWidth)).toBe(true);
  await dialog.locator('button[type=submit]').click();await count(page,2);
  const actions=await pending(page);
  expect(actions[0].clientActionId).toBe(startId);
  expect(actions[1].payload).toMatchObject({action:'correct_end_work',event_time:end.toISOString(),
    expected_started_at:start.toISOString(),expected_state:'working',correction_reason:'Ausstempeln vergessen'});
  await page.reload();await count(page,2);await expect(warning).toBeHidden();
  await context.setOffline(false);await waitForRecoveredSync(page);
  const saved=await(await page.request.get('/mobile/sync-data')).json();
  expect(saved.active_entry).toBeNull();expect(saved.entries).toHaveLength(1);
  expect(saved.entries[0]).toMatchObject({is_open:false,worked_minutes:480});
});

test('long work can be explicitly confirmed when clocking out now',async({page,account})=>{
  await login(page,account);
  await queue(page,'start_work',new Date(Date.now()-13*3600000).toISOString());
  await sync(page);await count(page,0);
  await expect(page.locator('#mobile-long-running')).toBeVisible();
  await page.locator('.mobile-action-grid form').filter({has:page.locator('input[name=action][value=end_work]')}).locator('button[type=submit]').click();
  await expect(page.locator('#mobile-end-review')).toBeVisible();
  await page.locator('[data-end-continue]').click();
  await expect.poll(async()=>(await(await page.request.get('/mobile/sync-data')).json()).active_entry).toBeNull();
  await count(page,0);
});

test('independent phone and PC stores refresh before stamping against stale state',async({page,browser,account})=>{
  const pcContext=await browser.newContext({baseURL:`http://127.0.0.1:${process.env.ERFASSUNG_E2E_PORT||8765}`});
  try{
    const pc=await pcContext.newPage();
    await login(page,account);await login(pc,account);
    // Keep the phone's known state offline while the PC starts work.
    await page.context().setOffline(true);
    await pc.locator('form[data-offline=punch]').filter({has:pc.locator('input[name=action][value=start_work]')}).locator('button[type=submit]').click();
    await expect.poll(async()=>(await(await pc.request.get('/mobile/sync-data')).json()).active_entry).toBeTruthy();
    await count(pc,0);
    // Restore network without the online-event recovery so the click itself
    // exercises the mandatory refresh of a stale, otherwise empty phone store.
    await page.evaluate(()=>window.addEventListener('online',event=>event.stopImmediatePropagation(),{capture:true,once:true}));
    await page.context().setOffline(false);
    await page.locator('form[data-offline=punch]').filter({has:page.locator('input[name=action][value=start_work]')}).locator('button[type=submit]').click();
    await expect(page.locator('#mobile-feedback')).toContainText('Buchungsstand wurde inzwischen geändert');
    await count(page,0);
    const phoneReceipts=await page.evaluate(async()=>{const s=new ErfassungSync.MobileStore();try{return(await s.all('mobileData')).filter(r=>r.key.startsWith('receipt:')).length;}finally{s.close();}});
    expect(phoneReceipts).toBe(0);
    const saved=await(await pc.request.get('/mobile/sync-data')).json();
    expect(saved.entries).toHaveLength(1);
    expect(saved.active_entry).toBeTruthy();
  }finally{await pcContext.close();}
});

test('offline phone clock-out never closes the newer PC booking',async({page,context,browser,account})=>{
  const pcContext=await browser.newContext({baseURL:`http://127.0.0.1:${process.env.ERFASSUNG_E2E_PORT||8765}`});
  try{
    const pc=await pcContext.newPage();await login(pc,account);
    await queue(pc,'start_work',new Date(Date.now()-3600000).toISOString());await sync(pc);await count(pc,0);
    await login(page,account);await context.setOffline(true);
    await page.locator('.mobile-action-grid form').filter({has:page.locator('input[name=action][value=end_work]')}).locator('button[type=submit]').click();
    await count(page,1);const [original]=await pending(page);
    await page.locator('#mobile-notes-modal button[data-close]').first().click();
    await queue(pc,'end_work',new Date(Date.now()-60000).toISOString());
    await queue(pc,'start_work',new Date(Date.now()-30000).toISOString());
    await sync(pc);await count(pc,0);
    const before=await(await pc.request.get('/mobile/sync-data')).json();
    await context.setOffline(false);await sync(page);
    await expect(page.locator('[data-sync-label]')).toHaveText('Freigabe erforderlich');
    await expect(page.locator('[data-sync-message]')).toContainText('anderen Gerät');
    await count(page,1);expect((await pending(page))[0].payload).toEqual(original.payload);
    const after=await(await pc.request.get('/mobile/sync-data')).json();
    expect(after.entries).toHaveLength(2);
    expect(after.active_entry.id).toBe(before.active_entry.id);
    expect(after.active_entry.is_open).toBe(true);
  }finally{await pcContext.close();}
});

test('manual cache recovery preserves offline outbox',async({page,account,context})=>{
  await login(page,account);await context.setOffline(true);await queue(page);
  await page.locator('[data-tab=einstellungen]').click();
  await page.locator('#mobile-clear-cache-btn').click();await count(page,1);
  await page.reload();await count(page,1);
});

test('parallel tabs send an event once',async({page,account,context})=>{
  await login(page,account);const other=await context.newPage();await other.goto('/mobile');
  await expect(other.locator('[data-sync-label]')).toHaveText('Synchronisiert');
  await queue(page);await Promise.all([sync(page),sync(other)]);await count(page,0);
  const data=await page.request.get('/mobile/sync-data');expect((await data.json()).active_entry).toBeTruthy();
});

test('offline interface remains usable at phone width',async({page,account,context})=>{
  await page.setViewportSize({width:390,height:844});await login(page,account);
  await context.setOffline(true);await page.reload();
  await expect(page.locator('#sync-status')).toBeVisible();
  const overflow=await page.evaluate(()=>[...document.querySelectorAll('body *')].filter(e=>e.getBoundingClientRect().right>innerWidth && e.getBoundingClientRect().width>0).map(e=>({tag:e.tagName,classes:e.className,right:e.getBoundingClientRect().right})));
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),JSON.stringify(overflow)).toBe(true);
  await page.locator('form[data-offline="punch"]').filter({has:page.locator('input[name=action][value=start_work]')}).locator('button[type=submit]').click();
  await count(page,1);
  await expect(page.locator('[data-sync-label]')).toHaveText('Offline');
});

test('connection lost after server commit retries the same event without duplication',async({page,account})=>{
  await login(page,account);
  const recover=networkFault('disconnect-after-commit');
  try{
    const id=await queue(page);
    await sync(page);await expect(page.locator('[data-sync-label]')).toHaveText('Synchronisation fehlgeschlagen');await count(page,1);
    expect((await (await page.request.get('/mobile/sync-data')).json()).active_entry).toBeTruthy();
    expect((await pending(page))[0].clientActionId).toBe(id);
    recover();await sync(page);await count(page,0);
    const receipt=await page.evaluate(async id=>{const s=new ErfassungSync.MobileStore();try{return (await s.get('mobileData',`receipt:${id}`)).receipt;}finally{s.close();}},id);
    expect(receipt.duplicate).toBe(true);
  }finally{recover();}
});

test('HTML response is never interpreted as a booking receipt',async({page,account})=>{
  await login(page,account);
  const recover=networkFault('html');
  try{
    await queue(page);
    await sync(page);await expect(page.locator('[data-sync-label]')).toHaveText('Synchronisation fehlgeschlagen');await count(page,1);
    expect((await (await page.request.get('/mobile/sync-data')).json()).active_entry).toBeNull();
    recover();await sync(page);await count(page,0);
  }finally{recover();}
});

test('version 4 IndexedDB is migrated without losing its pending event',async({page,account})=>{
  await page.goto('/login');await page.locator('[name=username]').fill(account);await page.locator('[name=password]').fill('Browser!12345');
  await Promise.all([page.waitForURL('**/dashboard'),page.locator('button[type=submit]').click()]);
  await page.evaluate(async()=>{
    const session=await (await fetch('/api/mobile/session')).json();
    await new Promise((resolve,reject)=>{
      const req=indexedDB.open('erfassung-mobile',4);
      req.onupgradeneeded=()=>{
        req.result.createObjectStore('pendingActions',{keyPath:'clientActionId'}).put({clientActionId:'legacy-e2e',type:'punch',payload:{action:'start_work',event_time:new Date().toISOString()},createdAt:Date.now()});
        req.result.createObjectStore('mobileData',{keyPath:'key'}).put({key:'snapshot',data:{user:{id:session.user.id,full_name:session.user.name}}});
        req.result.createObjectStore('meta',{keyPath:'key'});
      };req.onsuccess=()=>{req.result.close();resolve();};req.onerror=()=>reject(req.error);
    });
  });
  await page.goto('/mobile');await expect(page.locator('[data-sync-label]')).toHaveText('Synchronisiert');await count(page,0);
  expect(await page.evaluate(async()=>{const s=new ErfassungSync.MobileStore();try{return !!await s.get('mobileData','receipt:legacy-e2e');}finally{s.close();}})).toBe(true);
});

test('update waits for acceptance and preserves pending events across worker change',async({page,account})=>{
  const marker=path.join(process.env.ERFASSUNG_E2E_ROOT,'worker-version');
  await login(page,account);
  const recover=networkFault('unavailable');
  try {
    const id=await queue(page);
    // A release changes the actual worker bytes, exercising install/waiting/activate.
    fs.writeFileSync(marker,`0.21.0-e2e-${Date.now()}`);
    await page.evaluate(async()=>{const r=await navigator.serviceWorker.getRegistration();await r.update();});
    await expect(page.locator('#sync-update')).toBeVisible();
    await count(page,1);
    await expect.poll(()=>page.evaluate(async()=>!!(await navigator.serviceWorker.getRegistration()).waiting)).toBe(true);
    await expect.poll(()=>page.evaluate(async()=>!(await new ErfassungSync.MobileStore().get('meta','outboxLease')))).toBe(true);
    await page.evaluate(()=>{const form=document.createElement('form');form.id='test-dirty-form';const field=document.createElement('input');field.id='test-dirty-input';form.append(field);document.querySelector('.mobile-dashboard').append(form);});
    await page.locator('#test-dirty-input').fill('ungespeicherte Eingabe');
    await page.locator('#sync-update').click();
    await expect(page.locator('#mobile-feedback')).toContainText('Eingabe abschließen');
    expect(await page.evaluate(async()=>!!(await navigator.serviceWorker.getRegistration()).waiting)).toBe(true);
    await page.locator('#test-dirty-form').evaluate(e=>e.remove());
    await Promise.all([page.waitForEvent('domcontentloaded'),page.locator('#sync-update').click()]);
    await expect.poll(()=>page.evaluate(async()=>!(await navigator.serviceWorker.getRegistration()).waiting)).toBe(true);
    await expect(page.locator('#sync-status')).toBeVisible();await count(page,1);
    expect((await pending(page))[0].clientActionId).toBe(id);
    recover();await sync(page);await count(page,0);
  } finally {recover();fs.rmSync(marker,{force:true});}
});

test('confirmed running work is available for clock-out after offline restart',async({page,context,account})=>{
  test.setTimeout(RECOVERY_TEST_TIMEOUT);
  await login(page,account);const startId=await queue(page);await sync(page);await count(page,0);
  await expect(page.locator('[data-sync-label]')).toHaveText('Synchronisiert');
  await context.setOffline(true);await page.reload();
  const end=page.locator('form[data-offline="punch"]').filter({has:page.locator('input[name=action][value=end_work]')}).locator('button[type=submit]');
  await expect(end).toBeVisible();await end.click();await count(page,1);
  const stop=(await pending(page))[0];
  expect(stop.payload.action).toBe('end_work');
  // Reproduce a terminated tab's still-valid lock, rather than depending on
  // whether a startup/resume request happens to overlap the page reload.
  await page.evaluate(async()=>{
    const store=new ErfassungSync.MobileStore();
    try{await store.put('meta',{key:'outboxLease',owner:'terminated-tab',until:Date.now()+30000});}
    finally{store.close();}
  });
  await context.setOffline(false);
  await expect(page.locator('[data-sync-message]')).toContainText('anderes Erfassung-Fenster');
  expect((await pending(page))[0].clientActionId).toBe(stop.clientActionId);
  await waitForRecoveredSync(page);
  const saved=await(await page.request.get('/mobile/sync-data')).json();
  expect(saved.active_entry).toBeNull();
  expect(saved.entries).toHaveLength(1);
  expect(saved.entries[0]).toMatchObject({is_open:false,status:'approved'});
  const receipts=await page.evaluate(async()=>{
    const store=new ErfassungSync.MobileStore();
    try{return(await store.all('mobileData')).filter(row=>row.key.startsWith('receipt:')).map(row=>row.receipt);}
    finally{store.close();}
  });
  expect(receipts).toHaveLength(2);
  expect(receipts.map(receipt=>receipt.client_action_id).sort()).toEqual([startId,stop.clientActionId].sort());
  expect(new Set(receipts.map(receipt=>receipt.receipt_id)).size).toBe(2);
  for(const receipt of receipts)expect(receipt).toMatchObject({owner_id:saved.user.id,received:true,status:'applied'});
});

test('outbox survives a complete browser process restart',async({playwright,browserName,account})=>{
  // A terminated browser cannot release its 30-second ownership lease.
  // Wait for lease expiry plus the existing 15-second retry in this case only.
  test.setTimeout(RECOVERY_TEST_TIMEOUT);
  const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
  const profile=fs.mkdtempSync(path.join(os.tmpdir(),'erfassung-browser-'));
  const options={headless:true,baseURL:`http://127.0.0.1:${process.env.ERFASSUNG_E2E_PORT||8765}`,viewport:{width:390,height:844}};
  if(browserName==='chromium'&&process.env.ERFASSUNG_CHROMIUM_PATH)options.executablePath=process.env.ERFASSUNG_CHROMIUM_PATH;
  let context;
  try{
    context=await playwright[browserName].launchPersistentContext(profile,options);
    let page=context.pages()[0];await login(page,account);await context.setOffline(true);
    const id=await queue(page);await count(page,1);await context.close();
    context=await playwright[browserName].launchPersistentContext(profile,options);
    await context.setOffline(true);page=context.pages()[0];await page.goto('/mobile');
    await expect(page.locator('#sync-status')).toBeVisible();await count(page,1);
    expect((await pending(page))[0].clientActionId).toBe(id);
    await context.setOffline(false);
    await waitForRecoveredSync(page);
    const saved=await (await page.request.get('/mobile/sync-data')).json();
    expect(saved.entries).toHaveLength(1);
    expect(saved.active_entry).toMatchObject({id:saved.entries[0].id,status:'approved',is_open:true});
    const receipts=await page.evaluate(async()=>{
      const store=new ErfassungSync.MobileStore();
      try{return(await store.all('mobileData')).filter(row=>row.key.startsWith('receipt:')).map(row=>row.receipt);}
      finally{store.close();}
    });
    expect(receipts).toHaveLength(1);
    expect(receipts[0]).toMatchObject({client_action_id:id,owner_id:saved.user.id,received:true,status:'applied'});
    expect(Number.isInteger(receipts[0].receipt_id)).toBe(true);
    expect(receipts[0].receipt_id).toBeGreaterThan(0);
  }finally{await context?.close();fs.rmSync(profile,{recursive:true,force:true});}
});

test('a full offline working week uploads all fourteen stamps',async({page,account,context})=>{
  test.setTimeout(RECOVERY_TEST_TIMEOUT);
  await login(page,account);await context.setOffline(true);
  for(let days=7;days>=1;days--){
    const start=new Date(Date.now()-days*86400000);
    await queue(page,'start_work',start.toISOString());
    await queue(page,'end_work',new Date(start.getTime()+8*3600000).toISOString());
  }
  await count(page,14);await page.reload();await count(page,14);
  await context.setOffline(false);await waitForRecoveredSync(page);
  const receipts=await page.evaluate(async()=>{const s=new ErfassungSync.MobileStore();try{return(await s.all('mobileData')).filter(row=>row.key.startsWith('receipt:'));}finally{s.close();}});
  expect(receipts.length).toBe(14);expect(receipts.every(row=>row.receipt.status==='applied')).toBe(true);
});

test('a display failure after saving still reports the durable local booking',async({page,account,context})=>{
  test.setTimeout(RECOVERY_TEST_TIMEOUT);
  await login(page,account);await context.setOffline(true);
  await page.evaluate(()=>{
    const proto=ErfassungSync.MobileStore.prototype,enqueue=proto.enqueue,pending=proto.pending;
    let fail=false;
    proto.enqueue=async function(...args){const id=await enqueue.apply(this,args);fail=true;return id;};
    proto.pending=async function(){if(fail){fail=false;throw new Error('Lesefehler nach Speicherung');}return pending.call(this);};
  });
  await page.locator('form[data-offline="punch"]').filter({has:page.locator('input[name=action][value=start_work]')}).locator('button[type=submit]').click();
  await expect(page.locator('[data-sync-message]')).toContainText('Buchung lokal gespeichert. Anzeige konnte nicht aktualisiert werden');
  await count(page,1);await page.reload();await count(page,1);
  await context.setOffline(false);await waitForRecoveredSync(page);
});
