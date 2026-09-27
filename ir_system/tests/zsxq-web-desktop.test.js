const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {prepareDesktop,executeDesktop}=require('../adapters/zsxq_web/desktop');
const {makeControl,mediaKind}=require('../adapters/zsxq_web/control');
const {downloadVisibleFiles}=require('../adapters/zsxq_web/archive');
const {login}=require('../adapters/zsxq_web/browser');
function fixture(t){const root=fs.mkdtempSync(path.join(os.tmpdir(),'ir-web-desktop-'));t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
 const g={collectionId:'123',group_id:'123',scan_status:'ok',name:'Fixture',membership:{active:true},permissions:{allow_download:true,allow_copy:false},skill_api:'not_enabled'};
 return {command:'run',archiveRoot:root,scopeKey:'1'.repeat(64),row:{provider:'zsxq',collectionId:'123',start:'2026-09-01',end:'2026-09-26'},catalog:{scannedAt:new Date().toISOString(),complete:true,sources:[{provider:'zsxq',complete:true,collections:[g]}]},limits:{maxOperations:30,maxRecords:1,maxFiles:1,maxBytes:10000,maxFileBytes:1000,maxSeconds:30}};
}
function fakeBrowser(){const pages=[];return {pages:()=>pages.filter(p=>!p.isClosed()),newPage:async()=>{let closed=false;const p={isClosed:()=>closed,close:async()=>{closed=true;}};pages.push(p);return p;},close:async()=>{}};}
function runtime(){return {browserOptions:()=>({profileDir:'synthetic',launch:{}}),launch:async()=>fakeBrowser(),
 discoverTopics:async()=>({topics:[{topic_id:'111',published_on:'2026-09-20'},{topic_id:'222',published_on:'2026-09-21'}],reached_date_floor:true,oldest_visible_date:'2026-08-31'}),
 topicMetadata:async(_page,topic,job)=>({topic_id:topic.topic_id,source_item_id:'zsxq://topic/'+topic.topic_id,source_collection:job.group_id,published_on:topic.published_on,title:'Fixture',content_text:'',detected_attachments:[]}),downloadVisibleFiles:async()=>[]};}
test('desktop routes only explicit, fresh, active, download-enabled web selections',t=>{
 const r=fixture(t),job=prepareDesktop(r).jobs[0];assert.match(job.job_id,/^desktop-/);assert.equal(job.include.topics,'metadata_only');
 const g=r.catalog.sources[0].collections[0];g.membership.active=false;assert.throws(()=>prepareDesktop(r),/not eligible/);g.membership.active=true;
 g.permissions.allow_download=false;assert.throws(()=>prepareDesktop(r));g.permissions.allow_download=true;
 g.skill_api='accessible';assert.throws(()=>prepareDesktop(r));g.skill_api='not_enabled';
 r.catalog.complete=false;assert.throws(()=>prepareDesktop(r),/all-group/);r.catalog.complete=true;
 r.catalog.scannedAt='2020-01-01T00:00:00Z';assert.throws(()=>prepareDesktop(r),/all-group/);
});
test('desktop budget pause resumes exact checkpoint and new task does not reuse completion',async t=>{
 const r=fixture(t),rt=runtime();const first=await executeDesktop(r,{runtime:rt});assert.equal(first.status,'budget_paused');assert.equal(first.counts.newRecords,1);
 const second=await executeDesktop(r,{runtime:rt});assert.equal(second.status,'completed');assert.equal(second.counts.newRecords,1);assert.equal(second.manifest.record_refs.length,2);
 assert.equal(second.manifest.coverage_complete,false);assert.equal(fs.existsSync(path.join(r.archiveRoot,'zsxq_web/.archive.lock')),false);
 const old=prepareDesktop(r).jobs[0].job_id;r.scopeKey='2'.repeat(64);assert.notEqual(prepareDesktop(r).jobs[0].job_id,old);
});
test('stop saves a resumable manifest and does not mark discovery complete',async t=>{
 const r=fixture(t),rt=runtime();const out=await executeDesktop(r,{runtime:rt,onControl:c=>{c.stopped=true;}});
 assert.equal(out.status,'stopped');assert.equal(out.counts.downloaded,0);assert.equal(out.manifest,null);
});
test('text-only download excludes audio before any UI click and preserves old audio',async t=>{
 const r=fixture(t),storage=path.join(r.archiveRoot,'zsxq_web'),job=prepareDesktop(r).jobs[0],control=makeControl(r.limits);
 const record={topic_id:'111',detected_attachments:['voice.mp3','movie.mp4']};
 const recordPath=path.join(storage,'groups/123/topics/111/record.json');fs.mkdirSync(path.dirname(recordPath),{recursive:true});
 fs.writeFileSync(recordPath,JSON.stringify({attachments:[{original_filename:'voice.mp3',status:'ok',sha256:'2'.repeat(64),object_path:'objects/22/'+ '2'.repeat(64)}]}));
 const entries=await downloadVisibleFiles({},record,job,storage,{mediaPolicy:'text_non_audio',control});
 assert.equal(entries[0].status,'ok');assert.equal(entries[0].preserved,true);assert.equal(entries[1].status,'deferred');assert.equal(control.counts.audioDeferred,1);assert.equal(control.counts.videoDeferred,1);assert.equal(control.counts.downloaded,0);
 assert.equal(mediaKind('ARCHIVE.ZIP'),'unknown');
 await assert.rejects(downloadVisibleFiles({}, {...record,detected_attachments:['unknown.zip']},job,storage,{mediaPolicy:'text_non_audio',control}),e=>e.code==='media_type_requires_confirmation');
 await assert.rejects(downloadVisibleFiles({}, {...record,detected_attachments:['size-unknown.pdf']},job,storage,{mediaPolicy:'text_non_audio',control}),e=>e.code==='asset_size_unverified');
});
test('zero file and operation budgets never silently fall back to defaults',()=>{
 const c=makeControl({maxSeconds:30,maxFiles:0,maxBytes:100,maxFileBytes:100,maxOperations:0,maxRecords:0});
 assert.throws(()=>c.file(10),e=>e.code==='file_budget_exhausted');assert.throws(()=>c.step(),e=>e.code==='operation_budget_exhausted');assert.throws(()=>c.topic(),e=>e.code==='record_budget_exhausted');
});
test('desktop isolated attachment failures do not stop healthy topics or retry forever',async t=>{
 const r=fixture(t),rt=runtime();r.limits.maxRecords=10;
 rt.downloadVisibleFiles=async(_p,record)=>record.topic_id==='111'?[{original_filename:'unknown.zip',status:'failed',reason:'media_type_requires_confirmation'}]:[];
 const first=await executeDesktop(r,{runtime:rt});
 assert.equal(first.status,'budget_paused');assert.equal(first.counts.newRecords,2);
 const second=await executeDesktop(r,{runtime:rt});
 assert.equal(second.status,'partial');assert.equal(second.code,'web_items_pending');
 assert.equal(second.manifest.failures['111'].attempts,2);
 const third=await executeDesktop(r,{runtime:rt});
 assert.equal(third.status,'partial');assert.equal(third.counts.recordsAttempted,0);
});
test('unknown files and unverified sizes are recorded while other attachments continue',async t=>{
 const r=fixture(t),storage=path.join(r.archiveRoot,'zsxq_web'),job=prepareDesktop(r).jobs[0];
 const record={topic_id:'111',detected_attachments:['unknown.zip','size-unknown.pdf','voice.mp3']};
 const out=await downloadVisibleFiles({},record,job,storage,{mediaPolicy:'text_non_audio',control:makeControl(r.limits),isolateItemFailures:true});
 assert.deepEqual(out.map(a=>a.status),['failed','failed','deferred']);
});
test('controlled PDF download enforces shared file budget, checkpoints success and reuses it',async t=>{
 const r=fixture(t),job=prepareDesktop(r).jobs[0],storage=path.join(r.archiveRoot,'zsxq_web'),raw=Buffer.from('%PDF-synthetic');
 const record={topic_id:'111',source_url:'https://wx.zsxq.com/group/123/topic/111',detected_attachments:['voice.mp3','one.pdf','two.pdf'],file_metadata:[{name:'one.pdf',size:raw.length},{name:'two.pdf',size:raw.length}]};
 const recordPath=path.join(storage,'groups/123/topics/111/record.json');fs.mkdirSync(path.dirname(recordPath),{recursive:true});
 const control=makeControl(r.limits);let downloads=0;
 const element={count:async()=>1,click:async()=>{},waitFor:async()=>{}};element.first=element.last=element.filter=()=>element;
 const page={locator:()=>element,getByText:()=>element,goto:async()=>{},waitForEvent:async()=>({saveAs:async p=>{downloads++;fs.writeFileSync(p,raw);},suggestedFilename:()=> 'file.pdf',cancel:async()=>{}})};
 const options={mediaPolicy:'text_non_audio',control,onAttachmentProgress:entries=>fs.writeFileSync(recordPath,JSON.stringify({...record,attachments:entries}))};
 await assert.rejects(downloadVisibleFiles(page,record,job,storage,options),e=>e.code==='file_budget_exhausted');
 assert.equal(downloads,1);assert.equal(control.counts.bytes,raw.length);
 assert.equal(JSON.parse(fs.readFileSync(recordPath)).attachments[1].status,'ok');
 const next=makeControl(r.limits);const entries=await downloadVisibleFiles(page,record,job,storage,{...options,control:next});
 assert.equal(downloads,2);assert.equal(next.counts.reused,1);assert.equal(next.counts.downloaded,1);assert.equal(entries[0].status,'deferred');
});
test('login opens QR page for the operator, never invokes download, and closes its context',async()=>{
 const visited=[],clicked=[];let inspected=0,closed=false;
 const control={count:async()=>1,check:async()=>{},click:async()=>clicked.push('qr')};control.first=()=>control;
 const page={goto:async url=>visited.push(url),locator:()=>control,getByText:()=>control};
 const result=await login({groupId:'123'},{browserOptions:()=>({profileDir:'synthetic',launch:{}}),launch:async()=>({pages:()=>[page],close:async()=>{closed=true;}}),inspectPage:async()=>({authenticated:++inspected===2,renewal_required:false})});
 assert.equal(result.status,'ready');assert.equal(closed,true);assert.deepEqual(visited,['https://wx.zsxq.com/group/123','https://wx.zsxq.com/login']);assert.deepEqual(clicked,['qr']);
});
test('account login does not mistake a group renewal banner for account logout',async()=>{
 const visited=[];let closed=false;
 const page={goto:async u=>visited.push(u)};
 const result=await login({groupId:'123'},{browserOptions:()=>({profileDir:'synthetic',launch:{}}),launch:async()=>({pages:()=>[page],close:async()=>{closed=true;}}),inspectPage:async()=>({authenticated:true,renewal_required:true})});
 assert.equal(result.authenticated,true);assert.equal(closed,true);assert.deepEqual(visited,['https://wx.zsxq.com/group/123']);
 // This tests account readiness only; archive.js still rejects renewal-required groups.
});
test('corrupt object is repaired only after a verified complete download, with old bytes retained',async t=>{
 const r=fixture(t),job=prepareDesktop(r).jobs[0],storage=path.join(r.archiveRoot,'zsxq_web'),raw=Buffer.from('%PDF-repaired');
 const sha=require('node:crypto').createHash('sha256').update(raw).digest('hex'),object=path.join(storage,'objects',sha.slice(0,2),sha);
 fs.mkdirSync(path.dirname(object),{recursive:true});fs.writeFileSync(object,'damaged');
 const record={topic_id:'111',detected_attachments:['one.pdf'],file_metadata:[{name:'one.pdf',size:raw.length}]};
 const recordPath=path.join(storage,'groups/123/topics/111/record.json');fs.mkdirSync(path.dirname(recordPath),{recursive:true});
 fs.writeFileSync(recordPath,JSON.stringify({...record,attachments:[{original_filename:'one.pdf',status:'ok',sha256:sha,size_bytes:raw.length}]}));
 const element={count:async()=>1,click:async()=>{},waitFor:async()=>{}};element.first=element.last=element.filter=()=>element;
 let fail=true;
 const page={locator:()=>element,getByText:()=>element,waitForEvent:async()=>({saveAs:async p=>{fs.writeFileSync(p,fail?'partial':raw);if(fail)throw new Error('connection interrupted');},suggestedFilename:()=> 'one.pdf',cancel:async()=>{}})};
 const options=()=>({mediaPolicy:'text_non_audio',control:makeControl(r.limits)});
 await assert.rejects(downloadVisibleFiles(page,record,job,storage,options()),/connection interrupted/);
 assert.equal(fs.readFileSync(object,'utf8'),'damaged');
 fail=false;const entries=await downloadVisibleFiles(page,record,job,storage,options());
 assert.equal(entries[0].status,'ok');assert.deepEqual(fs.readFileSync(object),raw);
 const quarantine=fs.readdirSync(path.join(storage,'.quarantine'));assert.equal(quarantine.length,1);
 assert.equal(fs.readFileSync(path.join(storage,'.quarantine',quarantine[0]),'utf8'),'damaged');
 const reused=await downloadVisibleFiles({},record,job,storage,options());assert.equal(reused[0].reused,true);
});
