const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {browserOptions,ensureLogin}=require('../adapters/zsxq_web/browser');
const {runBatches}=require('../src/main/sync/batch-runner');
const {SyncManager}=require('../src/main/sync/manager');
const {validateSelection}=require('../src/main/sync/policy');
function loginRuntime(states){
 const modes=[],closed=[],visits=[];
 return {modes,closed,visits,browserOptions:(options,headed)=>({profileDir:'synthetic',launch:{headless:!headed}}),
  launch:async(_profile,o)=>{modes.push(o.headless);const n=modes.length;const locator={count:async()=>1,check:async()=>{},click:async()=>{}};locator.first=()=>locator;
   return {pages:()=>[{goto:async u=>visits.push(u),locator:()=>locator,getByText:()=>locator}],close:async()=>closed.push(n)};},
  inspectPage:async()=>states.shift()};
}
test('desktop headless override is explicit and human login is always visible',t=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'ir-browser-options-'));t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));
 const o={profileDir:dir,chromePath:process.execPath,headless:true};
 assert.equal(browserOptions(o).launch.headless,true);
 assert.equal(browserOptions(o,true).launch.headless,false);
});
test('valid account check never opens a visible window',async()=>{
 const rt=loginRuntime([{authenticated:true,renewal_required:true}]);
 assert.equal((await ensureLogin({groupId:'123'},rt)).authenticated,true);
 assert.deepEqual(rt.modes,[true]);assert.deepEqual(rt.closed,[1]);
});
test('known login page closes headless before opening QR, then closes QR on success',async()=>{
 const rt=loginRuntime([{authenticated:false,login_required:true},{authenticated:false,login_required:true},{authenticated:true}]);
 await ensureLogin({groupId:'123'},rt);
 assert.deepEqual(rt.modes,[true,false]);assert.deepEqual(rt.closed,[1,2]);assert.ok(rt.visits.at(-1).endsWith('/login'));
});
test('unrecognized page and startup crash do not trigger visible fallback',async()=>{
 const rt=loginRuntime([{authenticated:false,login_required:false}]);
 await assert.rejects(ensureLogin({groupId:'123'},rt),e=>e.code==='web_login_state_unknown');assert.deepEqual(rt.modes,[true]);
 let calls=0;rt.launch=async()=>{calls++;throw new Error('Browser closed');};
 await assert.rejects(ensureLogin({groupId:'123'},rt),e=>e.code==='headless_browser_failed');assert.equal(calls,1);
 rt.launch=async()=>{throw new Error('ProcessSingleton profile in use');};
 await assert.rejects(ensureLogin({groupId:'123'},rt),e=>e.code==='browser_profile_busy');
});
test('stop during login check closes browser and never opens QR',async()=>{
 const c=new AbortController(),rt=loginRuntime([]);rt.inspectPage=async()=>{c.abort();return {authenticated:false,login_required:true};};
 await assert.rejects(ensureLogin({groupId:'123',signal:c.signal},rt),e=>e.code==='user_stopped');assert.deepEqual(rt.modes,[true]);
});
test('login success resumes original scope once; subsequent expiry is reported without another popup',async()=>{
 const request={plan:{collections:[{provider:'zsxq',collectionId:'123'}]},jobDirectory:'/synthetic'},requests=[],events=[];
 const runner=r=>{requests.push(r);return {stop(){},promise:Promise.resolve(r.command==='web-login'?{status:'completed'}:{status:'interrupted',code:'human_login_required',counts:{newRecords:1}})};};
 const result=await runBatches(runner,request,{},{},e=>events.push(e),{digest:()=>null}).promise;
 assert.deepEqual(requests.map(r=>r.command||'run'),['run','web-login','run']);assert.equal(requests[0],requests[2]);
 assert.equal(result.code,'human_login_required');assert.equal(result.counts.newRecords,2);assert.equal(events[0].stage,'waiting_browser_login');
});
test('failed or cancelled human login cannot restart a download',async()=>{
 const request={plan:{collections:[{provider:'zsxq',collectionId:'123'}]}},calls=[];
 const runner=r=>{calls.push(r);return {stop(){},promise:Promise.resolve({status:'interrupted',code:r.command==='web-login'?'headless_browser_failed':'human_login_required'})};};
 const result=await runBatches(runner,request,{},{},()=>{},{digest:()=>null}).promise;
 assert.equal(result.code,'headless_browser_failed');assert.equal(calls.length,2);
});
test('visible fallback needs a new confirmation and preserves old job dates, scope and checkpoint',()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'ir-visible-resume-')),requests=[];
 const m=new SyncManager(dir,()=>({archiveRoot:dir}),{},r=>{requests.push(r);return {promise:new Promise(()=>{}),stop(){}};});
 const s=m.store.state;s.settings.policies=[{provider:'zsxq',collectionId:'123',name:'Fixture',mode:'incremental',firstDate:'2026-01-01'}];
 const selection={provider:'zsxq',start:'2026-09-20',end:'2026-09-26'},p=m.preview('backfill',null,selection),g=m.authorize('backfill',null,p,selection);
 const job=s.jobs.find(j=>j.id===g.jobId);job.status='interrupted';job.code='headless_browser_failed';
 const visible=m.preview('incremental',job.id,{browserMode:'visible'});assert.equal(visible.selection.start,selection.start);
 assert.equal(visible.selection.browserMode,'visible');assert.equal(job.selection.browserMode,undefined);
 assert.deepEqual(visible.plan.collections,job.plan.collections);
 const grant=m.authorize('incremental',job.id,visible,{browserMode:'visible'});m.start(grant.grantId);
 assert.equal(requests[0].browserMode,'visible');assert.equal(requests[0].jobDirectory,m.store.jobDirectory(job.id));
 assert.throws(()=>validateSelection({browserMode:'arbitrary'},'incremental'),/invalid_browser_mode/);
});
