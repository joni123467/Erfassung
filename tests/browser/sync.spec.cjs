const {test:base,expect}=require('@playwright/test');
const {execFileSync}=require('node:child_process');
const {randomUUID}=require('node:crypto');
const fs=require('node:fs'),path=require('node:path');
const test=base.extend({
  account:async({},use)=>{
    const username=`pwa-${randomUUID().slice(0,10)}`;
    execFileSync(process.env.ERFASSUNG_PYTHON,['tests/browser/create_user.py',username],{env:process.env});
    await use(username);
  },
});
async function login(page,account){
  await page.goto('/login');
  await page.locator('[name=username]').fill(account);
  await page.locator('[name=password]').fill('Browser!12345');
  await Promise.all([page.waitForURL('**/dashboard'),page.locator('button[type=submit]').click()]);
  await page.goto('/mobile');
  await expect(page.locator('[data-sync-label]')).toHaveText('Synchronisiert');
  // Wait for control without aborting a startup/resume sync with an artificial
  // reload. Reload/restart behavior is exercised explicitly by the relevant tests.
  await page.evaluate(async()=>{
    await navigator.serviceWorker.ready;
    if(!navigator.serviceWorker.controller)await new Promise(resolve=>navigator.serviceWorker.addEventListener('controllerchange',resolve,{once:true}));
  });
  await expect(page.locator('[data-sync-label]')).toHaveText('Synchronisiert');
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
  await expect(page.locator('[data-sync-label]')).toHaveText('Synchronisiert');
  await count(page,0);
  const data=await page.request.get('/mobile/sync-data');
  expect((await data.json()).active_entry).toBeTruthy();
});

test('offline stamp survives page close and seven-day-old events sync in order',async({page,context,account})=>{
  await login(page,account);
  await context.setOffline(true);
  const start=new Date(Date.now()-7*86400000).toISOString();
  await queue(page,'start_work',start);
  await queue(page,'start_break',new Date(Date.parse(start)+3*3600000).toISOString());
  await queue(page,'end_break',new Date(Date.parse(start)+3.5*3600000).toISOString());
  await queue(page,'end_work',new Date(Date.parse(start)+8*3600000).toISOString());
  await count(page,4);
  await page.close();
  const resumed=await context.newPage();await resumed.goto('/mobile');
  await expect(resumed.locator('#sync-status')).toBeVisible();await count(resumed,4);
  await context.setOffline(false);await sync(resumed);await count(resumed,0);
  await expect(resumed.locator('[data-sync-label]')).toHaveText('Synchronisiert');
  const response=await resumed.request.get('/mobile/sync-data');
  expect((await response.json()).active_entry).toBeNull();
});

test('expired login preserves events and re-login continues',async({page,account,context})=>{
  await login(page,account);await context.setOffline(true);await queue(page);await count(page,1);
  await context.clearCookies();await context.setOffline(false);await sync(page);
  await expect(page.locator('[data-sync-label]')).toHaveText('Anmeldung erforderlich');await count(page,1);
  await login(page,account);await count(page,0);
});

test('server rejection stays visible until reviewed',async({page,account})=>{
  await login(page,account);await queue(page,'end_work');await sync(page);
  await expect(page.locator('[data-sync-label]')).toHaveText('Freigabe erforderlich');await count(page,1);
  await page.reload();await expect(page.locator('[data-sync-label]')).toHaveText('Freigabe erforderlich');await count(page,1);
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
  await login(page,account);await queue(page);await sync(page);await count(page,0);
  await expect(page.locator('[data-sync-label]')).toHaveText('Synchronisiert');
  await context.setOffline(true);await page.reload();
  const end=page.locator('form[data-offline="punch"]').filter({has:page.locator('input[name=action][value=end_work]')}).locator('button[type=submit]');
  await expect(end).toBeVisible();await end.click();await count(page,1);
  expect((await pending(page))[0].payload.action).toBe('end_work');
  await context.setOffline(false);await count(page,0);
});

test('outbox survives a complete browser process restart',async({playwright,browserName,account})=>{
  const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
  const profile=fs.mkdtempSync(path.join(os.tmpdir(),'erfassung-browser-'));
  const options={headless:true,baseURL:'http://127.0.0.1:8765',viewport:{width:390,height:844}};
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
    await context.setOffline(false);await count(page,0);
  }finally{await context?.close();fs.rmSync(profile,{recursive:true,force:true});}
});

test('a full offline working week uploads all fourteen stamps',async({page,account,context})=>{
  await login(page,account);await context.setOffline(true);
  for(let days=7;days>=1;days--){
    const start=new Date(Date.now()-days*86400000);
    await queue(page,'start_work',start.toISOString());
    await queue(page,'end_work',new Date(start.getTime()+8*3600000).toISOString());
  }
  await count(page,14);await page.reload();await count(page,14);
  await context.setOffline(false);await count(page,0);
  const receipts=await page.evaluate(async()=>{const s=new ErfassungSync.MobileStore();try{return(await s.all('mobileData')).filter(row=>row.key.startsWith('receipt:'));}finally{s.close();}});
  expect(receipts.length).toBe(14);expect(receipts.every(row=>row.receipt.status==='applied')).toBe(true);
});

test('a display failure after saving still reports the durable local booking',async({page,account,context})=>{
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
  await context.setOffline(false);await count(page,0);
});
