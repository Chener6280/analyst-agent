const test=require('node:test'),assert=require('node:assert/strict');
const {runBatches}=require('../src/main/sync/batch-runner');
test('transient network errors retry at most three times without changing scope',async()=>{
 let calls=0;const request={plan:{collections:[]}};
 const runner=r=>{assert.equal(r,request);calls++;return {stop(){},promise:Promise.resolve({status:'interrupted',code:'network'})};};
 const result=await runBatches(runner,request,{},{},()=>{},{digest:()=>null,delayMs:0}).promise;
 assert.equal(calls,4);assert.equal(result.code,'network');
});
test('internal budget boundaries automatically continue the same checkpoint and accumulate counts',async()=>{
 const request={jobDirectory:'/synthetic',plan:{collections:[{provider:'zsxq',collectionId:'1'}]}},calls=[],events=[];
 const runner=(r,_p,_rt,event)=>{calls.push(r);event({stage:'downloading',counts:{downloaded:1}});return {stop(){},promise:Promise.resolve(calls.length<3?{status:'budget_paused',code:'operation_budget_exhausted',counts:{operations:60,downloaded:2}}:{status:'completed',counts:{operations:5,downloaded:1}})};};
 const result=await runBatches(runner,request,{}, {},e=>events.push(e),{digest:()=>null,delayMs:0}).promise;
 assert.equal(result.status,'completed');assert.equal(calls.length,3);assert.ok(calls.every(r=>r===request));
 assert.deepEqual(result.counts,{operations:125,downloaded:5});assert.equal(result.batchCount,3);
 assert.equal(events.filter(e=>e.stage==='continuing').length,2);assert.equal(events.at(-1).counts.downloaded,5);
});
for(const code of ['ima_daily_quota_exhausted','rate_limited','human_login_required','membership_expired','unexpected_error'])test('does not automatically retry '+code,async()=>{
 let calls=0;const result=await runBatches(()=>{calls++;return {stop(){},promise:Promise.resolve({status:'needs_attention',code,counts:{downloaded:1}})};},{},{},{},()=>{},{digest:()=>null,delayMs:0}).promise;
 assert.equal(calls,1);assert.equal(result.code,code);
});
test('closed background browser resumes original checkpoint once without a visible popup',async()=>{
 const request={browserMode:'headless',jobDirectory:'/synthetic'},calls=[],events=[];
 const runner=r=>{calls.push(r);return {stop(){},promise:Promise.resolve(calls.length===1?{status:'interrupted',code:'browser_interrupted',counts:{downloaded:2}}:{status:'completed',counts:{downloaded:1}})};};
 const result=await runBatches(runner,request,{},{},e=>events.push(e),{digest:()=>null,delayMs:0}).promise;
 assert.equal(result.status,'completed');assert.equal(result.counts.downloaded,3);assert.equal(calls.length,2);
 assert.ok(calls.every(r=>r===request));assert.equal(events[0].stage,'restarting_browser');
});
test('persistent browser failure stops after one recovery; explicit visible mode is not restarted',async()=>{
 for(const [browserMode,expected] of [['headless',2],['visible',1]]){
  let calls=0;
  const result=await runBatches(()=>{calls++;return {stop(){},promise:Promise.resolve({status:'interrupted',code:'browser_interrupted'})};},{browserMode},{},{},()=>{},{digest:()=>null,delayMs:0}).promise;
  assert.equal(calls,expected);assert.equal(result.code,'browser_interrupted');
 }
});
test('unchanged checkpoint and no committed work stops instead of looping forever',async()=>{
 let calls=0;const result=await runBatches(()=>{calls++;return {stop(){},promise:Promise.resolve({status:'budget_paused',code:'time_budget_exhausted',counts:{operations:60,recordsAttempted:1,reused:1}})};},{},{},{},()=>{},{digest:()=> 'unchanged',delayMs:0}).promise;
 assert.equal(calls,1);assert.equal(result.code,'batch_no_progress');assert.equal(result.status,'needs_attention');
});
test('stop while a child is running waits for it and never launches another batch',async()=>{
 let resolve,stops=0,calls=0;const child=new Promise(r=>{resolve=r;});
 const run=runBatches(()=>{calls++;return {promise:child,stop(){stops++;}};},{},{},{},()=>{},{digest:()=>null,delayMs:0});
 run.stop();assert.equal(stops,1);resolve({status:'budget_paused',code:'file_budget_exhausted',counts:{downloaded:3}});
 const result=await run.promise;assert.equal(calls,1);assert.equal(result.status,'stopped');assert.equal(result.counts.downloaded,3);
});
test('checkpoint progress alone permits another batch even when there are no new files',async()=>{
 let cursor=0,calls=0;const run=runBatches(()=>{cursor++;calls++;return {stop(){},promise:Promise.resolve(calls===1?{status:'budget_paused',code:'record_budget_exhausted',counts:{}}:{status:'partial',code:'coverage_gaps',counts:{}})};},{},{},{},()=>{},{digest:()=>String(cursor),delayMs:0});
 assert.equal((await run.promise).status,'partial');assert.equal(calls,2);
});
test('stop at the batch boundary cancels the scheduled next child',async()=>{
 let calls=0,run;const events=[];
 run=runBatches(()=>{calls++;return {stop(){},promise:Promise.resolve({status:'budget_paused',code:'operation_budget_exhausted',counts:{newRecords:1}})};},{},{},{},event=>{events.push(event);},{digest:()=>null,delayMs:10000});
 await new Promise(setImmediate);assert.equal(events.at(-1).stage,'continuing');
 run.stop();assert.equal((await run.promise).status,'stopped');assert.equal(calls,1);
});
