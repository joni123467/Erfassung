const {expect}=require('@playwright/test');

// A terminated page may leave its real 30-second lease behind. The visible
// client's existing retry interval is 15 seconds. Only lifecycle recovery gets
// this budget; ordinary online actions retain Playwright's strict 12 seconds.
const RECOVERY_TIMEOUT=50000;
const RECOVERY_TEST_TIMEOUT=75000;

async function waitForRecoveredSync(page){
  await expect.poll(async()=>{
    const pending=await page.evaluate(async()=>{
      const store=new ErfassungSync.MobileStore();
      try{
        const rows=await store.pending(),lease=await store.get('meta','outboxLease');
        return rows.map(row=>({id:row.clientActionId,action:row.payload.action,
          status:row.status,retryAt:row.retryAt,leaseOwner:lease?.owner,leaseUntil:lease?.until}));
      }finally{store.close();}
    });
    return {pending,state:await page.locator('[data-sync-label]').textContent()};
  },{timeout:RECOVERY_TIMEOUT,message:'Automatische Synchronisation nach Neustart: Lease und Wiederholungsintervall abwarten'}).toEqual({pending:[],state:'Synchronisiert'});
}

module.exports={RECOVERY_TIMEOUT,RECOVERY_TEST_TIMEOUT,waitForRecoveredSync};
