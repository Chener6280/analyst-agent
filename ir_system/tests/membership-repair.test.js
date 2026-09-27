const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {membershipEvidence,assertMembership}=require('../adapters/zsxq_web/browser');
const {identifyRepair,blockingCollections}=require('../src/main/sync/membership-repair');
test('reminder alone is not expiration; explicit expiry conflicting with scan stops',()=>{
 for(const text of ['续期提醒','续期提醒 会员将于2026年12月26日到期','即将到期'])assert.equal(membershipEvidence(text).expired,false);
 for(const text of ['成员体验已到期','你的会员已到期','你已于2026年09月01日到期'])assert.equal(membershipEvidence(text).expired,true);
 assert.doesNotThrow(()=>assertMembership({renewal_required:false},{membership:{active:true}}));
 assert.throws(()=>assertMembership({renewal_required:true},{membership:{active:true}}),e=>e.code==='membership_evidence_conflict');
 assert.throws(()=>assertMembership({renewal_required:false},{membership:{active:false}}),e=>e.code==='membership_expired');
});
test('only evidence-backed zero-record legacy failures get a repair retry',t=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'membership-repair-'));t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
 const relative='zsxq_web/jobs/desktop-abc123/manifest.json',file=path.join(root,relative);fs.mkdirSync(path.dirname(file),{recursive:true});
 const manifest={stage:'discover_topics',error:{code:'membership_expired',diagnostic:{message:'The group membership is expired in the browser session'}},topics_processed_total:0,record_refs:[],job:{group_id:'123',group_name:'Fixture',membership:{active:true}}};
 fs.writeFileSync(file,JSON.stringify(manifest));
 const job={kind:'sync',status:'needs_attention',code:'membership_expired',attempt:1,stage:'web_downloading',root,counts:{operations:1,downloaded:0},webManifests:[relative],plan:{collections:[{provider:'zsxq',collectionId:'123'}]}};
 assert.equal(identifyRepair(job).collectionId,'123');
 assert.equal(identifyRepair({...job,attempt:2}),null);assert.equal(identifyRepair({...job,counts:{downloaded:1}}),null);
 manifest.job.membership.active=false;fs.writeFileSync(file,JSON.stringify(manifest));assert.equal(identifyRepair(job),null);
});
test('finished group-local failures block that group only; interrupted batches keep their full scope',()=>{
 const rows=['123','456'].map(collectionId=>({provider:'zsxq',collectionId}));
 const job={status:'partial',stage:'finished',issues:[{provider:'zsxq',collectionId:'123'}],plan:{collections:rows}};
 assert.deepEqual(blockingCollections(job),[rows[0]]);
 assert.deepEqual(blockingCollections({...job,status:'budget_paused'}),rows);
});
