const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {access,saveProbes,MAX_AGE}=require('../src/main/sync/ima-access');
const {applyCatalog,signature}=require('../src/main/sync/subscriptions');
const {assistance}=require('../src/main/sync/assistance');
const {readiness}=require('../src/main/sync/readiness');
const {SyncManager}=require('../src/main/sync/manager');
const now=Date.now(),stamp=new Date(now).toISOString();
test('old 220021 evidence is explained as API quota, never a library permission denial',()=>{
 const f=fixture();saveProbes(f.state,f.job,[{...f.result,status:'unverified',code:'ima_upstream_rejected',diagnostic:{providerCode:220021,httpStatus:200,operation:'get_knowledge_list'}}]);
 const value=access(f.state,'one',{now,configuration:'config'});
 assert.equal(value.code,'ima_daily_quota_exhausted');assert.match(value.label,/额度/);assert.match(value.detail,/官方客户端/);
 const {canResume}=require('../src/main/sync/membership-repair');
 assert.equal(canResume({status:'needs_attention',code:'ima_daily_quota_exhausted'}),true);
 assert.equal(canResume({status:'needs_attention',code:'unexpected_error'}),false);
});
function fixture(){
 const row={collectionId:'one',name:'Library',directoryAccess:'accessible',accessCode:null,present:true};
 const state={revision:0,grants:{},settings:{policies:[{provider:'ima',collectionId:'one',name:'Library',mode:'incremental',firstDate:'2026-01-01'}]},
  catalog:{sources:[{provider:'ima',complete:true,scannedAt:stamp,collections:[row]}]},jobs:[],
  subscriptionReview:{'ima:one':{fingerprint:signature(row),pending:false,capability:{api:'原文样本拒绝'}}}};
 const job={id:'probe',probeSelection:['one'],finishedAt:stamp,probeConfiguration:'config'};
 const result={collectionId:'one',status:'api_sample_ok',code:'sample_read_ok',checkedAt:stamp,bytes:123,sampleRef:'ima://media/sample'};
 return {state,row,job,result};
}
test('client evidence never grants the desktop API route, and restrictions cannot be sent to an LLM as a bypass',()=>{
 const f=fixture(),dir=fs.mkdtempSync(path.join(os.tmpdir(),'ir-client-route-'));
 const manager=new SyncManager(dir,()=>({archiveRoot:dir}),{});Object.assign(manager.store.state,f.state);
 const configuration=manager.environmentKey(),s=manager.store.state;
 s.downloadEvidence={'ima:one':{status:'client_downloaded',checkedAt:stamp,configuration,fingerprint:signature(f.row)}};
 const plan={collections:[{provider:'ima',collectionId:'one'}]};
 assert.throws(()=>manager.checkDownloadRoutes(plan),/ima_client_route_not_connected/);
 assert.equal(assistance(s,'ima',{configuration}).needsAI,true);
 s.downloadEvidence['ima:one'].status='client_blocked';
 assert.throws(()=>manager.checkDownloadRoutes(plan),/ima_export_disabled/);
 assert.equal(assistance(s,'ima',{configuration}).needsAI,false);
});
test('current sample evidence supersedes old denial without erasing it or requiring a model',()=>{
 const f=fixture();assert.equal(access(f.state,'one').status,'unverified');
 assert.equal(assistance(f.state,'ima').needsAI,false);
 saveProbes(f.state,f.job,[f.result]);
 assert.equal(access(f.state,'one',{now,configuration:'config'}).status,'api_sample_ok');
 assert.equal(assistance(f.state,'ima').reasons.length,0);
 assert.equal(f.state.subscriptionReview['ima:one'].capability.api,'原文样本拒绝');
 assert.equal(readiness(f.state,'ima',{now,configuration:'config',localCheck:{checkedAt:stamp,status:'ready'}}).tone,'ready');
});
test('directory-only refresh and a prose report never establish original rights',()=>{
 const f=fixture();applyCatalog(f.state,{scannedAt:stamp,sources:f.state.catalog.sources});
 f.state.agentResult='all permissions fixed';
 assert.equal(access(f.state,'one').status,'unverified');
 assert.equal(readiness(f.state,'ima',{now,localCheck:{checkedAt:stamp,status:'ready'}}).tone,'ready');
});
test('evidence persists over time but rejects future stamps, configuration or subscription changes',()=>{
 const f=fixture();saveProbes(f.state,f.job,[f.result]);
 assert.equal(access(f.state,'one',{now:now+MAX_AGE+1}).status,'api_sample_ok');
 assert.equal(access(f.state,'one',{now:now-61000}).status,'unverified');
 assert.equal(access(f.state,'one',{configuration:'different'}).status,'unverified');
 f.row.name='Renamed';assert.equal(access(f.state,'one').status,'unverified');
});
test('not-tested uses observation time internally but never pretends it was checked',()=>{
 const f=fixture();saveProbes(f.state,f.job,[{collectionId:'one',status:'unverified',code:'not_tested'}]);
 let result=access(f.state,'one',{now});assert.equal(result.code,'not_tested');assert.equal(result.checkedAt,null);assert.match(result.label,/本轮未检查/);
 // Old application versions stored the job finish time as checkedAt: normalize display.
 f.state.imaAccess.one.checkedAt=stamp;result=access(f.state,'one',{now});assert.equal(result.checkedAt,null);
 saveProbes(f.state,f.job,[{...f.result,status:'unverified',code:'sample_not_found_in_budget'}]);
 assert.match(access(f.state,'one',{now}).detail,/3 页目录/);
});
test('new failures and interruption replace old success; IDs never merge by name',()=>{
 const f=fixture();saveProbes(f.state,f.job,[f.result]);
 saveProbes(f.state,f.job,[{...f.result,status:'sample_denied',code:'entitlement_denied'}]);
 assert.equal(access(f.state,'one').status,'sample_denied');
 assert.equal(assistance(f.state,'ima').needsAI,false);
 saveProbes(f.state,f.job,[]);assert.equal(access(f.state,'one').status,'unverified');
 assert.equal(access(f.state,'two').status,'unverified');
});
test('manager probe is scoped, confirmed, restart-safe and never advances watermarks',async()=>{
 const f=fixture(),dir=fs.mkdtempSync(path.join(os.tmpdir(),'ir-ima-probe-'));let resolve,request;
 const manager=new SyncManager(dir,()=>({archiveRoot:dir}),{},r=>{request=r;return {promise:new Promise(x=>resolve=x),stop:()=>resolve({status:'stopped'})};});
 Object.assign(manager.store.state,f.state);
 manager.store.state.settings.policies.push({provider:'ima',collectionId:'off',name:'Off',mode:'off'});
 manager.store.state.settings.policies.push({provider:'zsxq',collectionId:'123',name:'Other',mode:'incremental'});
 const preview=manager.probePreview();assert.equal(preview.rows.length,1);
 assert.throws(()=>manager.probeIma({...preview,revision:-1}),/scope_changed/);
 const job=manager.probeIma(preview);assert.equal(request.command,'ima-probe');assert.deepEqual(request.selected,['one']);
 assert.equal(access(manager.store.state,'one').status,'unverified');assert.equal(manager.view().busy,true);
 assert.throws(()=>manager.probePreview(),/busy/);
 resolve({status:'completed',catalog:structuredClone(f.state.catalog),imaProbes:[f.result]});await new Promise(setImmediate);
 assert.equal(manager.report(job.jobId).status,'completed');assert.equal(manager.view().imaAccess.one.status,'api_sample_ok');
 assert.deepEqual(manager.store.state.watermarks,{});assert.equal(manager.view().jobs[0].kind,'ima_probe');
 assert.throws(()=>manager.probePreview(),/ima_no_pending_probes/);
 const again=manager.probeIma(manager.probePreview({collectionId:'one'}));
 const restarted=new SyncManager(dir,()=>({archiveRoot:dir}),{});
 assert.equal(restarted.report(again.jobId).status,'interrupted');assert.equal(restarted.view().imaAccess.one.status,'unverified');
 resolve({status:'stopped'});await new Promise(setImmediate);
});

test('default pending-only selection preserves other valid success; scope excludes off and unknown IDs',async()=>{
 const f=fixture(),dir=fs.mkdtempSync(path.join(os.tmpdir(),'ir-ima-select-'));let resolve,request;
 const manager=new SyncManager(dir,()=>({archiveRoot:dir}),{},r=>{request=r;return {promise:new Promise(x=>resolve=x),stop:()=>{}};});
 Object.assign(manager.store.state,f.state);
 const good={...f.row,collectionId:'good',name:'Passed'};
 f.state.catalog.sources[0].collections.push(good);
 manager.store.state.settings.policies.push({provider:'ima',collectionId:'good',name:'Passed',mode:'incremental',firstDate:'2026-01-01'});
 saveProbes(manager.store.state,{...f.job,probeSelection:['good'],probeConfiguration:manager.environmentKey()},[{...f.result,collectionId:'good'}]);
 const before=structuredClone(manager.store.state.imaAccess.good);
 assert.deepEqual(manager.probePreview().rows.map(r=>r.collectionId),['one']);
 assert.equal(manager.probePreview().retainedPassed,1);
 assert.throws(()=>manager.probePreview({collectionId:'off'}),/invalid_probe_selection/);
 assert.throws(()=>manager.probePreview({restartSearch:true}),/invalid_probe_selection/);
 manager.probeIma(manager.probePreview());
 assert.deepEqual(request.selected,['one']);assert.deepEqual(manager.store.state.imaAccess.good,before);
 resolve({status:'needs_attention',imaProbes:[{collectionId:'one',status:'unverified',code:'not_tested'}]});await new Promise(setImmediate);
 assert.deepEqual(manager.store.state.imaAccess.good,before);
 assert.equal(manager.view().imaAccess.good.status,'api_sample_ok');
});

test('page progress survives process interruption and restart, reset is explicit and per-library',async()=>{
 const f=fixture(),dir=fs.mkdtempSync(path.join(os.tmpdir(),'ir-ima-resume-'));let resolve,event,request;
 const runner=(r,p,t,onEvent)=>{request=r;event=onEvent;return {promise:new Promise(x=>resolve=x),stop:()=>{}};};
 const manager=new SyncManager(dir,()=>({archiveRoot:dir}),{},runner);Object.assign(manager.store.state,f.state);
 manager.probeIma(manager.probePreview());
 const c={version:1,queue:[[null,'page4']],visited:['a'.repeat(64)],sample:null,pagesTotal:3,skippedTotal:20};
 event({stage:'probing_permissions',imaProbeSearch:{one:c},imaProbes:[],counts:{}});
 const restarted=new SyncManager(dir,()=>({archiveRoot:dir}),{},runner);
 assert.equal(restarted.view().imaAccess.one.search.pagesTotal,3);
 resolve({status:'interrupted'});await new Promise(setImmediate);
 restarted.probeIma(restarted.probePreview());assert.deepEqual(request.probeCheckpoints,{one:c});
 resolve({status:'stopped'});await new Promise(setImmediate);
 restarted.probeIma(restarted.probePreview({collectionId:'one',restartSearch:true}));
 assert.deepEqual(request.probeCheckpoints,{});assert.equal(restarted.view().imaAccess.one.search,null);
 resolve({status:'stopped'});await new Promise(setImmediate);
});

test('completed sample progress survives missing final worker output; untested scopes never become successes',async()=>{
 const f=fixture(),dir=fs.mkdtempSync(path.join(os.tmpdir(),'ir-ima-events-'));let resolve,event;
 const manager=new SyncManager(dir,()=>({archiveRoot:dir}),{},(r,p,t,emit)=>{event=emit;return {promise:new Promise(x=>resolve=x),stop:()=>{}};});
 Object.assign(manager.store.state,f.state);manager.probeIma(manager.probePreview());
 event({stage:'probing_permissions',imaProbes:[f.result],counts:{samplesPassed:1}});
 resolve({status:'interrupted'});await new Promise(setImmediate);
 assert.equal(manager.view().imaAccess.one.status,'api_sample_ok');
 assert.equal(manager.view().jobs[0].status,'interrupted');assert.deepEqual(manager.store.state.watermarks,{});
});

test('cursor state is bound to configuration and membership, diagnostics do not echo arbitrary data',()=>{
 const {saveSearch,searchCheckpoint}=require('../src/main/sync/ima-access'),f=fixture();
 const c={version:1,queue:[[null,'page4']],visited:[],sample:null,pagesTotal:3,skippedTotal:0};
 const job={...f.job,probeFingerprints:{one:signature(f.row)}};saveSearch(f.state,job,{one:c});
 assert.deepEqual(searchCheckpoint(f.state,'one','config'),c);
 assert.equal(searchCheckpoint(f.state,'one','another'),null);
 saveProbes(f.state,f.job,[{...f.result,diagnostic:{phase:'sample_read',providerCode:210011,httpStatus:200,message:'secret',headers:{token:'secret'}}}]);
 assert.doesNotMatch(JSON.stringify(access(f.state,'one')),/secret/);
 f.row.name='Changed';assert.equal(searchCheckpoint(f.state,'one','config'),null);
});
