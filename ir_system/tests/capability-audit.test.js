const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {applyAudit}=require('../src/main/sync/capability-audit'),{signature}=require('../src/main/sync/subscriptions');
const {downloadStatus}=require('../src/main/sync/download-status');
function fixture(){
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'ir-capability-audit-')),stamp=new Date().toISOString();
 const old={collectionId:'old',name:'Old',present:true,directoryAccess:'accessible'},fresh={collectionId:'new',name:'New',present:true};
 const state={revision:0,grants:{one:{used:false}},settings:{policies:[{provider:'ima',collectionId:'old',name:'Old',mode:'off'}]},subscriptionReview:{'ima:old':{fingerprint:signature(old),pending:false}},catalog:{sources:[{provider:'ima',complete:true,scannedAt:stamp,collections:[old]}]}};
 const audit={schemaVersion:1,id:'fixture-v1',configuration:'config',catalog:{complete:true,scannedAt:stamp,sources:[{provider:'ima',complete:true,inventoryOnly:true,collections:[{collectionId:'old',name:'Old'},fresh]}]},observations:[{provider:'ima',collectionId:'new',status:'client_downloaded',sampleTitle:'sample.pdf',checkedAt:stamp,bytes:10,sha256:'a'.repeat(64),fingerprint:signature(fresh)}]};
 const write=()=>fs.writeFileSync(path.join(dir,'capability-audit.json'),JSON.stringify(audit));write();return {dir,state,audit,write};
}
test('evidence handoff adds new pending row, preserves choices, and never grants API rights',()=>{
 const f=fixture();assert.equal(applyAudit(f.state,f.dir,'config'),true);assert.equal(f.state.settings.policies[0].mode,'off');assert.equal(f.state.settings.policies[1].mode,'pending_selection');
 const r=downloadStatus(f.state,'ima','new',{configuration:'config'});assert.equal(r.status,'available');assert.equal(r.desktop,false);assert.match(r.method,/Computer Use/);
 assert.equal(f.state.imaAccess,undefined);assert.equal(f.state.grants.one.revoked,true);const revision=f.state.revision;assert.equal(applyAudit(f.state,f.dir,'config'),false);assert.equal(f.state.revision,revision);
});
test('wrong machine configuration or invalid proof rejects atomically',()=>{
 const f=fixture(),before=JSON.stringify(f.state);assert.throws(()=>applyAudit(f.state,f.dir,'other'),/invalid/);assert.equal(JSON.stringify(f.state),before);
 f.audit.observations[0].sha256='not a checksum';f.write();assert.throws(()=>applyAudit(f.state,f.dir,'config'),/invalid/);assert.equal(JSON.stringify(f.state),before);
});
test('newer live catalogs cannot be replaced or bound to stale permission observations',()=>{
 const f=fixture();f.state.catalog.sources[0].scannedAt=new Date(Date.now()+1000).toISOString();
 f.state.catalog.sources[0].collections.push({collectionId:'new',name:'New',present:true,directoryAccess:'unavailable'});
 applyAudit(f.state,f.dir,'config');assert.equal(f.state.catalog.sources[0].collections[1].directoryAccess,'unavailable');assert.equal(f.state.downloadEvidence['ima:new'],undefined);
});
