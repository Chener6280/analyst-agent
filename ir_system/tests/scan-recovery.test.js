const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os');
const {recoverScanFailures,isRecoveredScanFailure}=require('../src/main/sync/scan-recovery');
const {SyncManager}=require('../src/main/sync/manager');
const now=Date.parse('2026-09-27T10:00:00Z');
function fixture(){
 const job={id:'old',kind:'sync',status:'needs_attention',code:'zsxq_cli_failed',stage:'scanning',attempt:1,root:'/archive',counts:{},finishedAt:new Date(now-60000).toISOString(),plan:{collections:[{provider:'zsxq',collectionId:'1',mode:'incremental'}]}};
 const state={jobs:[job],catalog:{sources:[{provider:'zsxq',complete:true,scannedAt:new Date(now-1000).toISOString()}]},watermarks:{}};
 const options={root:'/archive',configuration:'c',now,localCheck:{configuration:'c',status:'ready',checkedAt:new Date(now).toISOString(),zsxqCli:{status:'ready'}},hasCheckpoint:()=>false};
 return {job,state,options};
}
test('verified scan-only recovery preserves the failure and never advances coverage',()=>{
 const {job,state,options}=fixture();assert.equal(recoverScanFailures(state,options),true);
 assert.equal(isRecoveredScanFailure(job),true);assert.equal(job.status,'needs_attention');assert.equal(job.code,'zsxq_cli_failed');assert.deepEqual(state.watermarks,{});
 assert.equal(recoverScanFailures(state,options),false);
});
test('never clears downloads, checkpoints, retries, permissions, rate limits or unknown failures',()=>{
 for(const mutate of [f=>f.job.stage='downloading',f=>f.job.counts={downloaded:1},f=>f.job.counts={recordsAttempted:1},f=>delete f.job.counts,
   f=>f.job.attempt=2,f=>f.job.webManifests=['manifest'],f=>f.job.code='zsxq_auth_required',f=>f.job.code='rate_limit',f=>f.job.code='entitlement_denied',
   f=>f.job.code='worker_host_failed',f=>f.job.root='/other',f=>f.job.plan.collections[0].provider='ima',f=>f.options.hasCheckpoint=()=>true,
   f=>f.options.localCheck.zsxqCli.status='unknown',f=>f.options.localCheck.configuration='changed',f=>f.options.localCheck.checkedAt=new Date(now-11*60000).toISOString(),
   f=>f.state.catalog.sources[0].complete=false,f=>f.state.catalog.sources[0].scannedAt=new Date(now-120000).toISOString()]){
   const f=fixture();mutate(f);assert.equal(recoverScanFailures(f.state,f.options),false,mutate.toString());assert.equal(isRecoveredScanFailure(f.job),false);
 }
});
test('manager unlocks a new update only after scan and local check; original plan remains immutable',async t=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'ir-scan-recovery-'));t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));
 const m=new SyncManager(dir,()=>({archiveRoot:dir}),{},()=>({stop(){},promise:Promise.resolve({status:'completed',localCheck:{status:'ready',zsxqCli:{status:'ready'},issues:[]}})}));
 const f=fixture(),j=f.job;j.id='9ff696e1-e822-4adc-ba72-a15824bf690a';j.root=fs.realpathSync(dir);j.finishedAt=new Date(Date.now()-60000).toISOString();j.plan.kind='backfill';
 m.store.state.settings.policies=[{provider:'zsxq',collectionId:'1',name:'Fixture',mode:'incremental',firstDate:'2026-01-01'}];
 m.store.state.catalog={sources:[{provider:'zsxq',complete:true,scannedAt:new Date(Date.now()-1000).toISOString(),collections:[{collectionId:'1',skill_api:'accessible'}]}]};
 m.store.state.jobs=[j];const plan=JSON.stringify(j.plan);
 assert.equal(m.preview('incremental').replacements[0].jobId,j.id);
 await m.checkLocal();assert.equal(m.preview('incremental').plan.collections.length,1);assert.equal(JSON.stringify(j.plan),plan);
 assert.equal(m.view().readiness.zsxq.tone,'ready');assert.equal(m.view().jobs[0].recoveredBeforeDownload,true);assert.deepEqual(m.store.state.watermarks,{});
 delete j.recovery;fs.mkdirSync(m.store.jobDirectory(j.id),{recursive:true});
 await m.checkLocal(true);assert.equal(j.recovery,undefined);assert.equal(m.preview('incremental').replacements[0].jobId,j.id);
});
