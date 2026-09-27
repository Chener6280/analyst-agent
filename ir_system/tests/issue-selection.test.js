const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),os=require('node:os');
const {SyncManager}=require('../src/main/sync/manager');
const {signature,applyCatalog}=require('../src/main/sync/subscriptions');

function fixture(){
 const dir=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'ir-issue-selection-')));
 const manager=new SyncManager(dir,()=>({archiveRoot:dir}),{appRoot:'/application'},()=>{throw new Error('Network forbidden in this test');});
 const s=manager.store.state,stamp=new Date().toISOString();
 const rows=Array.from({length:4},(_,i)=>({collectionId:'kb'+i,name:'Library '+i,directoryAccess:'accessible',accessCode:null,present:true}));
 s.settings.policies=rows.map(r=>({provider:'ima',collectionId:r.collectionId,name:r.name,mode:'incremental',firstDate:'2026-01-01'}));
 s.catalog={sources:[{provider:'ima',complete:true,scannedAt:stamp,collections:rows}]};
 for(const r of rows)s.subscriptionReview['ima:'+r.collectionId]={fingerprint:signature(r),pending:false};
 s.imaAccess=Object.fromEntries(rows.map((r,i)=>[r.collectionId,{status:i?'sample_denied':'api_sample_ok',code:i?'entitlement_denied':'sample_read_ok',checkedAt:stamp,fingerprint:signature(r),configuration:manager.environmentKey()}]));
 manager.localCheck={status:'ready',checkedAt:stamp,configuration:manager.environmentKey(),issues:[]};
 s.grants.unused={used:false};s.grants.used={used:true};manager.store.save();
 return {manager,dir,rows};
}
function choose(m,issue,considered){return m.setIssueConsidered({provider:'ima',issueId:issue.issueId,considered,revision:m.view().revision});}


test('download capability is independent of runtime readiness and the backend still blocks unknown API rights',()=>{
 const {manager:m}=fixture();
 assert.equal(m.view().readiness.ima.tone,'ready');
 assert.equal(m.view().downloadStatus['ima:kb1'].status,'unknown');
 assert.throws(()=>m.preview('incremental'),/ima_permission_probe_required/);
 const settings=structuredClone(m.view().settings);settings.policies.forEach((p,i)=>{if(i)p.mode='off';});m.saveSettings(settings);
 for(const kind of ['backfill','incremental'])assert.deepEqual(m.preview(kind,null,{provider:'ima',start:'2026-01-01',end:'2026-01-02'}).plan.collections.map(r=>r.collectionId),['kb0']);
 assert.equal(m.store.state.imaAccess.kb1.status,'sample_denied');assert.deepEqual(m.store.state.watermarks,{});
});
test('selection persists across restart without turning an API refusal into success',()=>{
 const {manager:m,dir}=fixture(),settings=structuredClone(m.view().settings);
 settings.policies[1].mode='off';m.saveSettings(settings);
 const restarted=new SyncManager(dir,()=>({archiveRoot:dir}),{appRoot:'/app'});
 assert.equal(restarted.view().settings.policies[1].mode,'off');
 assert.equal(restarted.view().imaAccess.kb1.status,'sample_denied');
 assert.equal(restarted.view().jobs.length,0);
});
test('global lock is mandatory even with no selected library',()=>{
 const {manager:m}=fixture();m.localCheck.status='needs_attention';m.localCheck.issues=[{code:'archive_writer_busy',title:'Lock',level:'attention'}];
 const issue=m.view().readiness.ima.issues[0];assert.equal(issue.canExclude,false);
 assert.throws(()=>choose(m,issue,false),/required_check_cannot_be_ignored/);
 m.store.state.settings.policies.forEach(p=>p.mode='off');
 assert.equal(m.view().readiness.ima.tone,'attention');assert.throws(()=>m.preview('incremental'),/no_selected_collections/);
});
function addUnfinished(m,dir){
 m.store.state.jobs=[{id:'old',kind:'sync',root:dir,status:'needs_attention',plan:{collections:[m.store.state.settings.policies[1]]}}];
 // Checkboxes still apply to scoped runtime failures, not historical jobs.
 m.localCheck.status='needs_attention';
 m.localCheck.issues=[{code:'client_environment_unverified',title:'Client runtime',level:'attention',collectionIds:['kb1']}];
 return m.view().readiness.ima.issues.find(i=>i.code==='client_environment_unverified');
}
test('runtime issue checkbox excludes a scope; stale and busy actions remain rejected',()=>{
 const {manager:m,dir}=fixture(),issue=addUnfinished(m,dir),revision=m.view().revision;
 choose(m,issue,false);assert.equal(m.view().settings.policies[1].mode,'off');assert.equal(m.view().readiness.ima.tone,'ready');
 assert.throws(()=>m.setIssueConsidered({provider:'ima',issueId:issue.issueId,considered:false,revision}),/issue_state_changed/);
 assert.throws(()=>choose(m,{issueId:'invented'},false),/issue_state_changed/);
 m.active={id:'test'};assert.throws(()=>choose(m,m.view().readiness.ima.excluded[0],true),/sync_busy/);m.active=null;
 choose(m,m.view().readiness.ima.excluded[0],true);assert.equal(m.view().readiness.ima.tone,'attention');
 assert.equal(m.store.state.jobs[0].status,'needs_attention');
});
test('changed subscription invalidates saved exclusion and asks for a fresh choice',()=>{
 const {manager:m,dir,rows}=fixture();choose(m,addUnfinished(m,dir),false);
 const excluded=m.view().readiness.ima.excluded[0];
 applyCatalog(m.store.state,{scannedAt:new Date().toISOString(),sources:[{provider:'ima',complete:true,collections:rows.map(r=>r.collectionId===excluded.collectionId?{...r,name:'Changed library'}:r)}]});
 assert.equal(m.view().readiness.ima.excluded.length,0);assert.equal(m.view().settings.policies[1].mode,'pending_selection');
 assert.throws(()=>choose(m,excluded,true),/issue_state_changed/);assert.equal(m.store.state.grants.unused.revoked,true);
});
test('excluded unfinished jobs are not deleted and cannot be bypassed by a new task',()=>{
 const {manager:m,dir}=fixture(),settings=structuredClone(m.view().settings);
 settings.policies[2].mode='off';settings.policies[3].mode='off';m.saveSettings(settings);
 choose(m,addUnfinished(m,dir),false);
 assert.equal(m.store.state.jobs[0].status,'needs_attention');assert.deepEqual(m.preview('incremental').plan.collections.map(c=>c.collectionId),['kb0']);
 const restored=structuredClone(m.view().settings);restored.policies[1].mode='incremental';m.saveSettings(restored);
 assert.equal(m.view().readiness.ima.excluded.length,0);
 assert.throws(()=>m.preview('incremental'),/ima_permission_probe_required/); // replacement never bypasses permission checks
});
test('ZSXQ can exclude a web-only scope without suppressing API or global permission checks',()=>{
 const {manager:m}=fixture(),stamp=new Date().toISOString(),s=m.store.state;
 s.settings.policies=['123','456'].map(id=>({provider:'zsxq',collectionId:id,name:id,mode:'incremental',firstDate:'2026-01-01'}));
 s.catalog={sources:[{provider:'zsxq',complete:true,scannedAt:stamp,collections:s.settings.policies.map(p=>({collectionId:p.collectionId,name:p.name,membership:{active:true},permissions:{allow_download:true},skill_api:p.collectionId==='123'?'accessible':'not_enabled'}))}]};
 m.localCheck.web={status:'ready',loginVerified:false,issues:[]};m.localCheck.zsxqCli={status:'ready'};
 const issue=m.view().readiness.zsxq.issues.find(i=>i.code==='web_login_unverified');assert.deepEqual(issue.affectedCollectionIds,['456']);
 m.setIssueConsidered({provider:'zsxq',issueId:issue.issueId,considered:false,revision:m.view().revision});
 assert.equal(m.view().readiness.zsxq.tone,'ready');assert.deepEqual(m.preview('incremental').plan.collections.map(c=>c.collectionId),['123']);
});
