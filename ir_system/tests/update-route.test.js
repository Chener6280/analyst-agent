const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {SyncManager}=require('../src/main/sync/manager');
const {signature}=require('../src/main/sync/subscriptions');
const {makePlan,validateSelection}=require('../src/main/sync/policy');
function fixture(){
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'ir-update-route-'));
 const m=new SyncManager(dir,()=>({archiveRoot:dir}),{}),s=m.store.state,stamp=new Date().toISOString();
 const rows=['ready','client','probe','off'].map(id=>({collectionId:id,name:id,present:true,directoryAccess:'accessible'}));
 s.catalog={sources:[{provider:'ima',scannedAt:stamp,complete:true,collections:rows}]};
 s.settings.policies=rows.map(r=>({provider:'ima',collectionId:r.collectionId,name:r.name,mode:r.name==='off'?'off':'incremental',firstDate:'2026-01-01'}));
 const evidence=r=>({checkedAt:stamp,observedAt:stamp,configuration:m.environmentKey(),fingerprint:signature(r)});
 s.imaAccess={ready:{...evidence(rows[0]),status:'api_sample_ok',code:'sample_read_ok'}};
 s.downloadEvidence={'ima:client':{...evidence(rows[1]),status:'client_downloaded'}};
 return {m,s};
}
test('mixed IMA scope exposes all blockers and only explicitly narrowed scope can execute',()=>{
 const {m,s}=fixture(),before=structuredClone(s.settings.policies),v=m.view();
 assert.equal(v.updateRoutes['ima:ready'].ready,true);
 assert.equal(v.updateRoutes['ima:client'].code,'ima_client_route_not_connected');
 assert.equal(v.updateRoutes['ima:probe'].code,'ima_permission_probe_required');
 const selection={provider:'ima',start:'2026-09-20',end:'2026-09-26'};
 assert.throws(()=>m.preview('backfill',null,selection),/ima_client_route_not_connected/);
 const chosen={...selection,collectionIds:['ready']},p=m.preview('backfill',null,chosen);
 assert.deepEqual(p.executionCollections.map(r=>r.collectionId),['ready']);
 assert.deepEqual(p.deferredCollections.map(r=>r.collectionId),['client','probe']);
 const grant=m.authorize('backfill',null,p,chosen),job=s.jobs.find(j=>j.id===grant.jobId);
 assert.deepEqual(job.plan.collections.map(r=>r.collectionId),['ready']);
 assert.deepEqual(s.settings.policies,before);assert.deepEqual(s.watermarks,{});
 assert.throws(()=>m.preview('backfill',null,{...chosen,collectionIds:['client']}),/ima_client_route_not_connected/);
 s.imaAccess.ready.status='unverified';assert.throws(()=>m.start(grant.grantId),/ima_permission_probe_required/);
});
test('temporary scope cannot add unselected, unknown, duplicate or malformed IDs',()=>{
 const {s}=fixture(),selection={provider:'ima',start:'2026-09-20',end:'2026-09-26'};
 for(const ids of [[],['ready','ready'],['/secret'],[1],null])assert.throws(()=>validateSelection({...selection,collectionIds:ids},'backfill'),/invalid_selected_collections/);
 for(const id of ['off','missing'])assert.throws(()=>makePlan(s.settings,{},'backfill','/tmp','2026-09-27',{...selection,collectionIds:[id]}),/invalid_selected_collections/);
 assert.throws(()=>validateSelection({collectionIds:['ready']},'incremental'));
});
test('macOS native route accepts selected client libraries without pretending API works',()=>{
 const {m,s}=fixture();m.imaClientAvailable=()=>true;
 const routes=m.view().updateRoutes;
 assert.equal(routes['ima:ready'].client,false);
 assert.equal(routes['ima:client'].client,true);
 assert.equal(routes['ima:probe'].client,true);
 const selection={provider:'ima',start:'2026-09-27',end:'2026-09-27'};
 const p=m.preview('incremental',null,selection);
 assert.equal(p.executionCollections.length,3);
 assert.equal(s.imaAccess.client,undefined);
});
