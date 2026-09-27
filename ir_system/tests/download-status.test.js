const test=require('node:test'),assert=require('node:assert/strict');
const {downloadStatus}=require('../src/main/sync/download-status');
const {signature,applyCatalog}=require('../src/main/sync/subscriptions');
function fixture(provider='ima'){
 const row={collectionId:'one',name:'Library',present:true};
 return {row,state:{revision:0,settings:{policies:[{provider,collectionId:'one',name:'Library',mode:'incremental'}]},grants:{},subscriptionReview:{},catalog:{sources:[{provider,complete:true,scannedAt:'2026-09-27T06:00:00Z',collections:[row]}]}}};
}
test('official client success counts as downloadable, not a desktop API grant',()=>{
 const {state,row}=fixture();state.downloadEvidence={'ima:one':{status:'client_downloaded',checkedAt:'2026-09-27T06:00:00Z',fingerprint:signature(row),configuration:'local'}};
 const r=downloadStatus(state,'ima','one',{configuration:'local'});assert.equal(r.status,'available');assert.equal(r.desktop,false);assert.equal(r.route,'官方客户端');
 assert.equal(downloadStatus(state,'ima','one',{configuration:'different'}).status,'unknown');
 row.name='Changed';assert.equal(downloadStatus(state,'ima','one',{configuration:'local'}).status,'unknown');
});
test('API refusal alone stays inconclusive; explicit client export restriction is distinct',()=>{
 const {state,row}=fixture();state.imaAccess={one:{status:'sample_denied',fingerprint:signature(row),code:'entitlement_denied'}};
 assert.equal(downloadStatus(state,'ima','one').status,'unknown');
 state.downloadEvidence={'ima:one':{status:'client_blocked',fingerprint:signature(row),sampleTitle:'Sample.pdf'}};
 assert.equal(downloadStatus(state,'ima','one').status,'unavailable');
 state.downloadEvidence['ima:one'].status='library_deleted';
 assert.equal(downloadStatus(state,'ima','one').label,'不可下载（库已删除）');
});
test('ZSXQ checks expiry and platform policy, routes API or deterministic browser',()=>{
 const {state,row}=fixture('zsxq');Object.assign(row,{membership:{active:true},permissions:{allow_download:true,allow_copy:false},skill_api:'accessible'});
 assert.equal(downloadStatus(state,'zsxq','one').route,'API');row.skill_api='not_enabled';assert.equal(downloadStatus(state,'zsxq','one').route,'网页程序');
 row.permissions.allow_download=false;assert.equal(downloadStatus(state,'zsxq','one').status,'unavailable');
 row.permissions.allow_download=true;row.membership.end_time='2020-01-01';assert.equal(downloadStatus(state,'zsxq','one').status,'unavailable');
});
test('IMA discovery adds new library without changing old permission evidence or choice',()=>{
 const {state,row}=fixture();Object.assign(row,{directoryAccess:'accessible',accessCode:null});state.subscriptionReview['ima:one']={fingerprint:signature(row),pending:false};
 applyCatalog(state,{scannedAt:'2026-09-27T07:00:00Z',sources:[{provider:'ima',complete:true,inventoryOnly:true,collections:[{collectionId:'one',name:'Library'},{collectionId:'new',name:'New library'}]}]});
 assert.equal(state.settings.policies[0].mode,'incremental');assert.equal(state.settings.policies[1].mode,'pending_selection');
 assert.equal(state.catalog.sources[0].collections[0].directoryAccess,'accessible');
 assert.equal(downloadStatus(state,'ima','new').status,'unknown');
});
