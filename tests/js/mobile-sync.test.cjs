const { test } = require('node:test');
const assert = require('node:assert/strict');
const { IDBFactory } = require('fake-indexeddb');
const { MobileStore, SyncEngine, StorageError } = require('../../static/mobile-sync.js');

const session = {protocol:1, user:{id:7,name:'Test'}, csrf_token:'test-token'};
const json = data => new Response(JSON.stringify(data), {headers:{'content-type':'application/json'}});
async function fixture() {
  const store = new MobileStore(new IDBFactory());
  await store.put('meta',{key:'owner',id:7,name:'Test'});
  return store;
}
function transport(handler = body => ({protocol:1,received:true,owner_id:body.owner_id,
  client_action_id:body.client_action_id,receipt_id:1,status:'applied'})) {
  return async (url, options) => url.endsWith('/session') ? json(session) : handler(JSON.parse(options.body));
}
function goodTransport(handler) { const send=transport(handler); return async (...args)=> { const result=await send(...args); return result instanceof Response ? result : json(result); }; }

test('missing storage cannot report a saved stamp', async () => {
  const store=new MobileStore(null);
  await assert.rejects(store.enqueue('punch',{action:'start_work'}),StorageError);
});

test('version 4 migration preserves IDs and binds only to the cached owner', async () => {
  const factory=new IDBFactory();
  await new Promise((resolve,reject)=> {
    const req=factory.open('erfassung-mobile',4);
    req.onupgradeneeded=()=> {
      req.result.createObjectStore('pendingActions',{keyPath:'clientActionId'}).put({clientActionId:'legacy',type:'punch',payload:{action:'end_work'},createdAt:1});
      req.result.createObjectStore('mobileData',{keyPath:'key'}).put({key:'snapshot',data:{user:{id:7,full_name:'Original'}}});
      req.result.createObjectStore('meta',{keyPath:'key'});
    };
    req.onsuccess=()=> {req.result.close();resolve();}; req.onerror=()=>reject(req.error);
  });
  const store=new MobileStore(factory);
  assert.equal((await store.identity()).id,7);
  const [entry]=await store.pending();
  assert.equal(entry.clientActionId,'legacy'); assert.equal(entry.ownerId,7);
  store.close();
});

test('multiple stamps remain in creation order through restart', async () => {
  const store=await fixture();
  for (const action of ['start_work','start_break','end_break','end_work']) await store.enqueue('punch',{action});
  store.close();
  const resumed=new MobileStore(store.factory);
  assert.deepEqual((await resumed.pending()).map(e=>e.payload.action),['start_work','start_break','end_break','end_work']);
  const engine=new SyncEngine(resumed,{fetch:goodTransport()});
  assert.equal(await engine.run(),true); assert.equal((await resumed.pending()).length,0);
  assert.equal((await resumed.all('mobileData')).length,4);
  resumed.close();
});

for (const scenario of ['html','wrong-id','network','server','auth','conflict']) {
  test(`${scenario} never deletes the unconfirmed original`,async () => {
    const store=await fixture();
    const id=await store.enqueue('punch',{action:'end_work'});
    const states=[];
    const fetch=goodTransport(body=> {
      if(scenario==='html')return new Response('<html>Login</html>',{headers:{'content-type':'text/html'}});
      if(scenario==='network')throw new TypeError('connection reset');
      if(scenario==='server')return new Response('',{status:500});
      if(scenario==='auth')return new Response('',{status:401});
      return {protocol:1,received:true,owner_id:7,client_action_id:scenario==='wrong-id'?'wrong':body.client_action_id,
        receipt_id:3,status:scenario==='conflict'?'conflict':'applied',message:'Bitte prüfen'};
    });
    const engine=new SyncEngine(store,{fetch,notify:(state)=>states.push(state)});
    assert.equal(await engine.run(),false);
    assert.equal((await store.pending())[0].clientActionId,id);
    assert.equal(states.includes('synced'),false);
    assert.equal(engine.running,null);
    store.close();
  });
}

test('account switch cannot transmit the previous user’s queue',async () => {
  const store=await fixture(); await store.enqueue('punch',{action:'start_work'});
  let requests=0;
  const engine=new SyncEngine(store,{fetch:async()=>{requests++;return json({...session,user:{id:9,name:'Other'}});}});
  assert.equal(await engine.run(),false);assert.equal(requests,1);assert.equal((await store.pending())[0].ownerId,7);
  store.close();
});

test('two page/worker coordinators share an atomic lease',async () => {
  const store=await fixture();await store.enqueue('punch',{action:'start_work'});
  let release,entered;
  const gate=new Promise(resolve=>release=resolve), started=new Promise(resolve=>entered=resolve);
  let sent=0;
  const fetch=goodTransport(async body=>{ sent++;entered();await gate;return {protocol:1,received:true,owner_id:7,client_action_id:body.client_action_id,receipt_id:1,status:'applied'};});
  const a=new SyncEngine(store,{fetch});const b=new SyncEngine(new MobileStore(store.factory),{fetch});
  const first=a.run();await started;assert.equal(await b.run(),false);release();assert.equal(await first,true);assert.equal(sent,1);
  store.close();b.store.close();
});

test('storage failure releases in-memory lock and next attempt works',async () => {
  const store=await fixture();await store.enqueue('punch',{action:'start_work'});
  const acquire=store.lease.bind(store);store.lease=async()=>{throw new StorageError('full');};
  const engine=new SyncEngine(store,{fetch:goodTransport()});
  assert.equal(await engine.run(),false);assert.equal(engine.running,null);
  store.lease=acquire;assert.equal(await engine.run(),true);store.close();
});

test('server 500 has persisted backoff; force retry preserves the same action ID',async () => {
  const store=await fixture();const id=await store.enqueue('punch',{action:'start_work'});
  let attempts=0;
  const engine=new SyncEngine(store,{fetch:goodTransport(body=> {
    attempts++; if(attempts===1)return new Response('',{status:503});
    assert.equal(body.client_action_id,id);
    return {protocol:1,received:true,owner_id:7,client_action_id:id,receipt_id:1,status:'applied'};
  })});
  assert.equal(await engine.run(),false);
  assert.ok((await store.pending())[0].retryAt>Date.now());
  assert.equal(await engine.run(),false);assert.equal(attempts,1);
  assert.equal(await engine.run(true),true);assert.equal(attempts,2);store.close();
});

test('manual retry during an existing session request bypasses pending backoff',async () => {
  const store=await fixture(),id=await store.enqueue('punch',{action:'end_work'});
  await store.put('pendingActions',{...(await store.pending())[0],status:'retry',retryAt:Date.now()+60000});
  let entered,release,sent=0;
  const started=new Promise(resolve=>entered=resolve),gate=new Promise(resolve=>release=resolve);
  const engine=new SyncEngine(store,{fetch:async(url,options)=>{
    if(url.endsWith('/session')){entered();await gate;return json(session);}
    sent++;
    const body=JSON.parse(options.body);
    assert.equal(body.client_action_id,id);
    return json({protocol:1,received:true,owner_id:7,client_action_id:id,receipt_id:1,status:'applied'});
  }});
  try{
    const automatic=engine.run();await started;
    const manual=engine.run(true);release();
    assert.equal(await automatic,true);
    assert.equal(await manual,true);
    assert.equal(sent,1);assert.equal((await store.pending()).length,0);
  }finally{release();store.close();}
});

test('manual retry during a snapshot is retained by the follow-up run',{timeout:5000},async () => {
  const store=await fixture();
  let entered,release,acknowledged,sent=0;
  const started=new Promise(resolve=>entered=resolve),gate=new Promise(resolve=>release=resolve);
  const saved=new Promise(resolve=>acknowledged=resolve);
  const engine=new SyncEngine(store,{
    snapshot:async()=>{entered();await gate;},
    fetch:goodTransport(body=>{
      sent++;acknowledged();
      return {protocol:1,received:true,owner_id:7,client_action_id:body.client_action_id,receipt_id:1,status:'applied'};
    }),
  });
  try{
    const automatic=engine.run();await started;
    const id=await store.enqueue('punch',{action:'end_work'});
    await store.put('pendingActions',{...(await store.pending())[0],status:'retry',retryAt:Date.now()+60000});
    engine.run(true);release();await automatic;
    await saved;await engine.running;
    assert.equal(sent,1);assert.equal((await store.pending()).length,0);
    assert.equal((await store.get('mobileData',`receipt:${id}`)).receipt.client_action_id,id);
  }finally{release();store.close();}
});

test('manual retry while the previous run releases its lease is retained',{timeout:5000},async () => {
  const store=await fixture(),id=await store.enqueue('punch',{action:'end_work'});
  await store.put('pendingActions',{...(await store.pending())[0],status:'retry',retryAt:Date.now()+60000});
  let entered,release,acknowledged,sent=0,hold=true;
  const started=new Promise(resolve=>entered=resolve),gate=new Promise(resolve=>release=resolve);
  const saved=new Promise(resolve=>acknowledged=resolve),lease=store.lease.bind(store);
  store.lease=async(owner,releasing=false)=>{
    if(releasing&&hold){hold=false;entered();await gate;}
    return lease(owner,releasing);
  };
  const engine=new SyncEngine(store,{fetch:goodTransport(body=>{
    sent++;acknowledged();
    return {protocol:1,received:true,owner_id:7,client_action_id:body.client_action_id,receipt_id:1,status:'applied'};
  })});
  try{
    const automatic=engine.run();await started;
    engine.run(true);assert.equal(sent,0);release();
    assert.equal(await automatic,false);
    await saved;await engine.running;
    assert.equal(sent,1);assert.equal((await store.pending()).length,0);
    assert.equal((await store.get('mobileData',`receipt:${id}`)).receipt.client_action_id,id);
  }finally{release();store.close();}
});

test('HTML, retryable conflicts and blocked dependency chain never appear synced',async () => {
  const store=await fixture();await store.enqueue('punch',{action:'start_work'});await store.enqueue('punch',{action:'end_work'});
  let sent=0;
  const engine=new SyncEngine(store,{fetch:goodTransport(body=>{sent++;return {protocol:1,received:true,owner_id:7,client_action_id:body.client_action_id,receipt_id:1,status:'conflict'};})});
  assert.equal(await engine.run(),false);assert.equal(sent,1);assert.equal((await store.pending()).length,2);store.close();
});

test('rejection requires a matching durable receipt and is archived with its reason',async () => {
  const store=await fixture();await store.enqueue('punch',{action:'end_work'});
  const engine=new SyncEngine(store,{fetch:goodTransport(body=>({protocol:1,received:true,owner_id:7,client_action_id:body.client_action_id,receipt_id:12,status:'rejected',resolution_note:'Bereits erfasst'}))});
  assert.equal(await engine.run(),true);assert.equal((await store.pending()).length,0);
  assert.equal((await store.get('meta','lastDecision')).message,'Bereits erfasst');
  assert.equal((await store.all('mobileData'))[0].entry.payload.action,'end_work');store.close();
});

test('backup restore is additive, owner-bound and rejects changed originals atomically',async()=>{
  const store=await fixture();const id=await store.enqueue('punch',{action:'start_work',csrf_token:'must-not-be-persisted'});
  assert.equal((await store.pending())[0].payload.csrf_token,undefined);
  const backup={format:'erfassung-outbox-1',owner:{id:7},actions:await store.pending()};
  await store.restore(backup);assert.equal((await store.pending()).length,1);
  backup.owner.id=8;await assert.rejects(store.restore(backup),StorageError);backup.owner.id=7;
  backup.actions[0].payload.action='end_work';await assert.rejects(store.restore(backup),StorageError);
  assert.equal((await store.pending())[0].payload.action,'start_work');
  backup.actions[0].payload.action='start_work';await store.remove('pendingActions',id);
  await store.restore(backup);assert.equal((await store.pending())[0].clientActionId,id);store.close();
});

test('IndexedDB versionchange closes old connections instead of blocking an upgrade',async()=>{
  const store=await fixture();await store.enqueue('punch',{action:'start_work'});
  await new Promise((resolve,reject)=>{
    const next=store.factory.open('erfassung-mobile',6);next.onblocked=()=>reject(new Error('upgrade blocked'));
    next.onsuccess=()=>{next.result.close();resolve();};next.onerror=()=>reject(next.error);
  });
  assert.equal(store.connection,null);
});
