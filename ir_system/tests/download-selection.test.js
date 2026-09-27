const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),os=require('node:os');
const {applyDownloadDefaults}=require('../src/main/sync/download-selection');
const {signature,applyCatalog}=require('../src/main/sync/subscriptions');
const {SyncStore}=require('../src/main/sync/store'),{SyncManager}=require('../src/main/sync/manager');
function fixture(){
 const rows=[{collectionId:'blocked',name:'Blocked',present:true},{collectionId:'client',name:'Client',present:true},{collectionId:'unknown',name:'Unknown',present:true},{collectionId:'deleted',name:'Deleted',present:true}];
 const stars=[{collectionId:'1',name:'Expired',membership:{active:false,state:'expired'},permissions:{allow_download:true}},{collectionId:'2',name:'Disabled',membership:{active:true},permissions:{allow_download:false}}];
 const s={revision:0,grants:{unused:{used:false},used:{used:true}},jobs:[],watermarks:{},settings:{policies:[...rows.map(r=>({provider:'ima',collectionId:r.collectionId,name:r.name,mode:r.collectionId==='deleted'?'pending_selection':'incremental',firstDate:'2026-01-01'})),...stars.map(r=>({provider:'zsxq',collectionId:r.collectionId,name:r.name,mode:'incremental',firstDate:'2026-01-01'}))]},catalog:{sources:[{provider:'ima',complete:true,collections:rows},{provider:'zsxq',complete:true,collections:stars}]},subscriptionReview:{},downloadEvidence:{}};
 rows.forEach(r=>{s.subscriptionReview['ima:'+r.collectionId]={fingerprint:signature(r),pending:r.collectionId==='deleted'};});
 for(const [i,status] of [[0,'client_blocked'],[1,'client_downloaded'],[3,'library_deleted']])s.downloadEvidence['ima:'+rows[i].collectionId]={status,fingerprint:signature(rows[i]),configuration:'config',checkedAt:new Date().toISOString()};
 s.imaAccess={unknown:{status:'sample_denied',code:'entitlement_denied',fingerprint:signature(rows[2]),configuration:'config'}};
 return {s,rows,stars};
}
test('only confirmed unavailable subscriptions default off, never API refusal or a client route',()=>{
 const {s}=fixture();assert.equal(applyDownloadDefaults(s,{configuration:'config'}),true);
 assert.deepEqual(s.settings.policies.map(p=>p.mode),['off','incremental','incremental','off','off','off']);
 assert.equal(s.subscriptionReview['ima:deleted'].pending,false);assert.equal(s.grants.unused.revoked,true);assert.equal(s.grants.used.revoked,undefined);
 assert.deepEqual(s.jobs,[]);assert.deepEqual(s.watermarks,{});
});
test('same evidence is idempotent and does not silently overwrite later manual choices',()=>{
 const {s}=fixture();applyDownloadDefaults(s,{configuration:'config'});s.settings.policies[0].mode='incremental';const revision=s.revision;
 assert.equal(applyDownloadDefaults(s,{configuration:'config'}),false);assert.equal(s.revision,revision);assert.equal(s.settings.policies[0].mode,'incremental');
});
test('restored download capability asks for selection instead of automatically enabling',()=>{
 const {s,stars}=fixture();applyDownloadDefaults(s,{configuration:'config'});
 const current={...stars[0],membership:{active:true,state:'active_paid'},skill_api:'accessible'};
 applyCatalog(s,{scannedAt:new Date().toISOString(),sources:[{provider:'zsxq',complete:true,collections:[current,stars[1]]}]});
 applyDownloadDefaults(s,{configuration:'config'});
 assert.equal(s.settings.policies.find(p=>p.collectionId==='1').mode,'pending_selection');assert.equal(s.subscriptionReview['zsxq:1'].pending,true);
});
test('wrong-machine evidence and unknown new subscriptions do not get default exclusions',()=>{
 const {s,rows}=fixture();s.settings.policies[2].mode='pending_selection';applyDownloadDefaults(s,{configuration:'different'});
 assert.equal(s.settings.policies[0].mode,'incremental');assert.equal(s.settings.policies[2].mode,'pending_selection');
});
test('startup persists defaults and explicit single-library diagnostics do not re-enable it',async()=>{
 const {s,rows}=fixture(),dir=fs.mkdtempSync(path.join(os.tmpdir(),'ir-default-off-')),store=new SyncStore(dir);
 Object.assign(store.state,s);const configuration=JSON.stringify([dir,'python3','']);for(const e of Object.values(store.state.downloadEvidence))e.configuration=configuration;store.save();
 let resolve,request;const manager=new SyncManager(dir,()=>({archiveRoot:dir}),{},r=>{request=r;return {promise:new Promise(x=>resolve=x),stop(){}};});
 assert.equal(manager.view().settings.policies[0].mode,'off');
 assert.equal(manager.probePreview().rows.some(r=>r.collectionId==='blocked'),false);
 const preview=manager.probePreview({collectionId:'blocked'});assert.deepEqual(preview.rows.map(r=>r.collectionId),['blocked']);
 manager.probeIma(preview);assert.deepEqual(request.selected,['blocked']);assert.equal(manager.view().settings.policies[0].mode,'off');
 resolve({status:'needs_attention',imaProbes:[{collectionId:'blocked',status:'sample_denied',code:'entitlement_denied',checkedAt:new Date().toISOString()}]});await new Promise(setImmediate);
 assert.equal(manager.view().settings.policies[0].mode,'off');assert.deepEqual(manager.store.state.watermarks,{});
 const restarted=new SyncManager(dir,()=>({archiveRoot:dir}),{});assert.equal(restarted.view().settings.policies[0].mode,'off');
});
