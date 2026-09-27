const test=require('node:test'),assert=require('node:assert/strict');
const {readiness}=require('../src/main/sync/readiness');
const {signature}=require('../src/main/sync/subscriptions');
const now=Date.parse('2026-09-27T04:00:00Z'),stamp=new Date(now).toISOString();
function fixture(provider='ima'){
  const row={collectionId:'one',name:'Fixture',present:true,directoryAccess:'accessible',membership:{active:true},permissions:{allow_download:true},skill_api:'accessible'};
  return {state:{settings:{policies:[{provider,collectionId:'one',name:'Fixture',mode:'incremental'}]},catalog:{sources:[{provider,complete:true,scannedAt:stamp,collections:[row]}]},imaAccess:{one:{status:'api_sample_ok',code:'sample_read_ok',checkedAt:stamp,fingerprint:signature(row)}},subscriptionReview:{},jobs:[]},options:{root:'/archive',now,localCheck:{status:'ready',checkedAt:stamp,issues:[],zsxqCli:{status:'ready'}}},row};
}
for(const provider of ['ima','zsxq','wisburg'])test(provider+' can become green only with explicit completed checks',()=>{
  const f=fixture(provider);assert.equal(readiness(f.state,provider,f.options).tone,'ready');
  assert.notEqual(readiness(f.state,provider,{...f.options,localCheck:null}).tone,'ready');
  f.state.catalog.sources[0].complete=false;assert.notEqual(readiness(f.state,provider,f.options).tone,'ready');
});
test('new and unconnected sources never inherit green',()=>{
  for(const p of ['alphapai','gangtise','future_source']){const f=fixture(p);assert.equal(readiness(f.state,p,f.options).tone,'unknown');}
});
test('permissions are separate; stale discovery and scan failures affect runtime',()=>{
  const f=fixture('zsxq');delete f.row.permissions;
  assert.equal(readiness(f.state,'zsxq',f.options).tone,'ready');
  f.row.permissions={allow_download:null};assert.equal(readiness(f.state,'zsxq',f.options).tone,'ready');
  f.row.permissions={allow_download:true};f.row.membership.active=null;assert.equal(readiness(f.state,'zsxq',f.options).tone,'ready');f.row.membership.active=true;
  f.state.catalog.sources[0].scannedAt='2026-09-25T00:00:00Z';assert.equal(readiness(f.state,'zsxq',f.options).tone,'unknown');
  f.state.catalog.sources[0].scannedAt=stamp;
  f.state.jobs=[{kind:'scan',providers:['zsxq'],status:'failed',code:'rate_limit'}];assert.equal(readiness(f.state,'zsxq',f.options).tone,'attention');
  f.state.jobs.push({kind:'scan',providers:['zsxq'],status:'completed'});assert.equal(readiness(f.state,'zsxq',f.options).tone,'ready');
  assert.equal(readiness(f.state,'zsxq',{...f.options,now:now+11*60000}).tone,'unknown');
});
test('permissions and choices do not color runtime; web route still needs login',()=>{
  const f=fixture('zsxq');f.row.membership.active=false;assert.equal(readiness(f.state,'zsxq',f.options).tone,'ready');
  f.row.membership.active=true;f.state.settings.policies[0].mode='pending_selection';assert.equal(readiness(f.state,'zsxq',f.options).tone,'ready');
  f.state.settings.policies[0].mode='incremental';f.row.skill_api='not_enabled';assert.equal(readiness(f.state,'zsxq',f.options).tone,'unknown');
  f.options.localCheck.web={status:'ready',loginVerified:true,issues:[]};assert.equal(readiness(f.state,'zsxq',f.options).tone,'ready');
  f.row.skill_api='accessible';assert.equal(readiness(f.state,'zsxq',f.options).tone,'ready');
});
test('unfinished tasks remain visible without changing environment readiness',()=>{
  const f=fixture();f.state.jobs=[{id:'old',kind:'sync',status:'needs_attention',root:'/archive',plan:{collections:f.state.settings.policies},agentResult:{text:'问题已解决'}},
    {kind:'scan',providers:['ima'],status:'completed'}];
  const result=readiness(f.state,'ima',f.options);
  assert.equal(result.tone,'ready');assert.equal(result.taskWarnings.length,1);
  assert.equal(result.taskWarnings[0].jobId,'old');assert.equal(result.issues.length,0);
  assert.equal(f.state.jobs[0].status,'needs_attention');
  f.state.jobs[0].root='/another';assert.equal(readiness(f.state,'ima',f.options).tone,'ready');
});
test('audio backlog is separate from non-audio readiness, but local failures are not',()=>{
  const f=fixture();f.state.jobs=[{kind:'sync',status:'completed',root:'/archive',plan:{collections:f.state.settings.policies},counts:{audioDeferred:5}}];
  assert.equal(readiness(f.state,'ima',f.options).tone,'ready');
  assert.equal(readiness(f.state,'ima',{...f.options,localCheck:{status:'needs_attention',checkedAt:stamp,issues:[{level:'attention',code:'archive_writer_busy'}]}}).tone,'attention');
  assert.equal(readiness(f.state,'ima',{...f.options,busy:true}).tone,'unknown');
});
test('unchecked expired subscriptions do not block the selected source scope',()=>{
  const f=fixture('zsxq');f.state.settings.policies.push({provider:'zsxq',collectionId:'expired',name:'Not selected',mode:'off'});
  f.state.catalog.sources[0].collections.push({collectionId:'expired',membership:{active:false}});
  assert.equal(readiness(f.state,'zsxq',f.options).tone,'ready');
});
test('a newer complete catalog from permission reprobe supersedes an older failed scan',()=>{
 const f=fixture();f.state.jobs=[{kind:'scan',providers:['ima'],status:'failed',finishedAt:new Date(now-60000).toISOString()}];
 assert.equal(readiness(f.state,'ima',f.options).tone,'ready');
 f.state.catalog.sources[0].scannedAt=new Date(now-120000).toISOString();
 assert.equal(readiness(f.state,'ima',f.options).tone,'attention');
});
test('a missing CLI runtime cannot inherit green from browser or Python checks',()=>{
 const f=fixture('zsxq');delete f.options.localCheck.zsxqCli;
 assert.equal(readiness(f.state,'zsxq',f.options).tone,'unknown');
 f.options.localCheck.zsxqCli={status:'needs_attention',code:'zsxq_node_runtime_missing'};
 const r=readiness(f.state,'zsxq',f.options);assert.equal(r.tone,'attention');
 assert.match(r.issues.find(i=>i.code==='zsxq_node_runtime_missing').action,/更新修复版/);
 assert.equal(readiness(f.state,'ima',f.options).issues.some(i=>i.code==='zsxq_node_runtime_missing'),false);
});
test('an active scan is progress, not a failed scan',()=>{
 const f=fixture('zsxq');f.state.jobs=[{kind:'scan',providers:['zsxq'],status:'running'}];
 const r=readiness(f.state,'zsxq',f.options);assert.equal(r.tone,'unknown');
 assert.ok(r.issues.some(i=>i.code==='scan_in_progress'));assert.ok(!r.issues.some(i=>i.code==='latest_scan_unsuccessful'));
});
test('a concrete browser/login failure appears once, not alongside another generic login issue',()=>{
 const f=fixture('zsxq');f.row.skill_api='not_enabled';
 f.options.localCheck.web={status:'needs_attention',loginVerified:false,issues:[{code:'human_login_required',level:'attention'}]};
 const r=readiness(f.state,'zsxq',f.options);assert.equal(r.issues.length,1);assert.equal(r.issues[0].code,'human_login_required');
});
