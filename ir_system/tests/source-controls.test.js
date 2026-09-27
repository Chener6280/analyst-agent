const test=require('node:test');const assert=require('node:assert/strict');
const {defaults,parse,today}=require('../src/shared/dates');
const {applyCatalog,signature,acknowledge}=require('../src/main/sync/subscriptions');
const {assistance,buildPrompt}=require('../src/main/sync/assistance');
const {makePlan}=require('../src/main/sync/policy');
function state(){return {revision:0,settings:{policies:[],budgets:{},overlapDays:3},grants:{a:{used:false}},subscriptionReview:{},jobs:[]};}
function scan(rows,complete=true){return {scannedAt:'2026-09-27T02:00:00Z',sources:[{provider:'zsxq',complete,collections:rows}]};}
const row={collectionId:'123',name:'Alpha',membership:{state:'active_paid',active:true,end_time:'2027-01-01'},skill_api:'accessible',permissions:{allow_download:true},statistics:{topics:1}};
test('Shanghai midnight, leap year, previous month clamp, and yymmdd strict dates',()=>{
  assert.equal(today(new Date('2026-09-26T16:01:00Z')),'2026-09-27');
  assert.deepEqual(defaults('backfill',new Date('2024-03-31T04:00:00Z')),{start:'2024-02-29',end:'2024-03-30'});
  assert.deepEqual(defaults('backfill',new Date('2026-01-31T04:00:00Z')),{start:'2025-12-31',end:'2026-01-30'});
  assert.deepEqual(defaults('incremental',new Date('2026-09-26T16:01:00Z')),{start:'2026-09-27',end:'2026-09-27'});
  assert.deepEqual(defaults('incremental',new Date('2026-09-27T08:59:59-07:00')),{start:'2026-09-27',end:'2026-09-27'});
  assert.deepEqual(defaults('incremental',new Date('2026-09-27T09:00:00-07:00')),{start:'2026-09-28',end:'2026-09-28'});
  assert.equal(parse('260927'),'2026-09-27');assert.throws(()=>parse('260231'));assert.throws(()=>parse('991301'));
});
test('new and changed subscriptions remain pending across scans until explicit decision',()=>{
  const s=state();applyCatalog(s,scan([row]));assert.equal(s.settings.policies[0].mode,'pending_selection');
  s.settings.policies[0].mode='incremental';s.settings.policies[0].firstDate='2026-01-01';acknowledge(s,s.settings.policies);
  applyCatalog(s,scan([{...row,statistics:{topics:200}}]));assert.equal(s.settings.policies[0].mode,'incremental');
  const changed={...row,permissions:{allow_download:false}};applyCatalog(s,scan([changed]));assert.equal(s.settings.policies[0].mode,'pending_selection');assert.equal(s.subscriptionReview['zsxq:123'].reason,'changed');
  applyCatalog(s,scan([changed]));assert.equal(s.settings.policies[0].mode,'pending_selection');
  s.settings.policies[0].mode='off';acknowledge(s,s.settings.policies);applyCatalog(s,scan([changed]));assert.equal(s.settings.policies[0].mode,'off');
  applyCatalog(s,scan([]));assert.equal(s.subscriptionReview['zsxq:123'].reason,'missing');assert.equal(s.catalog.sources[0].collections[0].present,false);
  assert.equal(s.grants.a.revoked,true);
});
test('incomplete scan never invents removals and unreviewed rows are excluded from jobs',()=>{
  const s=state();applyCatalog(s,scan([row]));applyCatalog(s,scan([],false));assert.equal(s.catalog.sources[0].collections.length,1);
  assert.throws(()=>makePlan(s.settings,{},'incremental','/tmp','2026-09-27',{provider:'zsxq',start:'2026-09-27',end:'2026-09-27'}),/no_selected/);
});
test('explicitly selected fixed Wisburg categories stay selected after their first scan',()=>{
  const s=state();s.settings.policies=[{provider:'wisburg',collectionId:'archive',name:'archive',mode:'incremental',firstDate:'2026-08-27'}];
  applyCatalog(s,{scannedAt:'2026-09-27T02:00:00Z',sources:[{provider:'wisburg',complete:true,collections:[{collectionId:'archive',name:'archive'}]}]});
  assert.equal(s.settings.policies[0].mode,'incremental');
  assert.equal(s.subscriptionReview['wisburg:archive'].pending,false);
});
test('web CLI and permission restrictions are not falsely classified as LLM requirements',()=>{
  const s=state();s.settings.policies=[{provider:'zsxq',collectionId:'123',name:'Alpha',mode:'incremental'}];s.catalog=scan([{...row,skill_api:'not_enabled'}]);
  assert.equal(assistance(s,'zsxq').needsAI,false);
  s.jobs=[{plan:{collections:s.settings.policies},counts:{audioDeferred:2}}];assert.equal(assistance(s,'zsxq').needsAI,true);
  const prompts=buildPrompt(s,'zsxq','incremental',{start:'2026-09-27',end:'2026-09-27'},'/archive',{appRoot:'/app'}).prompts;
  assert.match(prompts.audio,/此提示词不是付费授权/);assert.match(prompts.audio,/60 秒/);assert.match(prompts.audio,/123/);
});
test('non-audio and audio prompts are standalone, independently scoped and stage-gated',()=>{
  const s=state();s.settings.policies=[{provider:'ima',collectionId:'chosen',name:'Chosen',mode:'incremental'},
    {provider:'ima',collectionId:'excluded',name:'Excluded',mode:'off'},
    {provider:'ima',collectionId:'unconfirmed',name:'Pending',mode:'pending_selection'}];
  s.jobs=[{plan:{collections:s.settings.policies},counts:{audioDeferred:3},issues:[{code:'needs_ocr'}]}];
  const result=buildPrompt(s,'ima','backfill',{start:'2026-08-01',end:'2026-08-31'},'/archive',{packaged:true,resourcesPath:'/resources'});
  assert.deepEqual(Object.keys(result.prompts),['nonAudio','audio']);
  for(const text of Object.values(result.prompts)){
    assert.match(text,/chosen/);assert.doesNotMatch(text,/excluded|unconfirmed/);
    assert.match(text,/2026-08-01 至 2026-08-31/);assert.match(text,/归档目录：\/archive/);
    assert.match(text,/\/resources\/docs/);assert.match(text,/此提示词不是付费授权/);
  }
  assert.match(result.prompts.nonAudio,/不要下载音频/);assert.match(result.prompts.nonAudio,/不得自行切换到语音阶段/);
  assert.match(result.prompts.nonAudio,/扫描件待 OCR/);assert.doesNotMatch(result.prompts.nonAudio,/60 秒|最近任务发现 3 条音频/);
  assert.match(result.prompts.audio,/不能证明已验收就停止/);assert.match(result.prompts.audio,/火山/);
  assert.match(result.prompts.audio,/60 秒/);assert.match(result.prompts.audio,/成功调用耗时、失败调用耗时和整轮墙钟时间分列/);
  assert.match(result.prompts.audio,/whole_audio_transcribed=true/);assert.doesNotMatch(result.prompts.audio,/最近任务有扫描件待 OCR/);
});
test('both prompts stop when no subscription is selected',()=>{
  const prompts=buildPrompt(state(),'ima','incremental',{start:'2026-09-27',end:'2026-09-27'},'',{appRoot:'/app'}).prompts;
  for(const text of Object.values(prompts)){assert.match(text,/当前没有已勾选范围/);assert.match(text,/尚未配置，请先向用户确认/);}
});
test('amber issues identify each affected subscription, evidence time and corrective action',()=>{
  const s=state();const rows=[
    {...row,collectionId:'expired',name:'Expired',membership:{active:false}},
    {...row,collectionId:'disabled',name:'Disabled',permissions:{allow_download:false}},
    {...row,collectionId:'web',name:'Web',skill_api:'not_enabled'},
    {...row,collectionId:'ignored',name:'Ignored',membership:{active:false}}
  ];
  s.settings.policies=rows.map(r=>({provider:'zsxq',collectionId:r.collectionId,name:r.name,mode:r.collectionId==='ignored'?'off':'incremental'}));
  s.catalog=scan(rows);s.catalog.sources[0].scannedAt='2026-09-26T20:00:00Z';
  const help=assistance(s,'zsxq');
  assert.equal(help.tone,'attention');assert.equal(help.needsAI,false);
  assert.deepEqual(help.reasons.map(r=>r.code),['membership_expired','download_disabled']);
  assert.deepEqual(help.reasons.map(r=>r.collectionId),['expired','disabled']);
  for(const r of help.reasons){assert.equal(r.observedAt,'2026-09-26T20:00:00Z');assert.ok(r.title&&r.detail&&r.action&&r.name);}
  assert.match(help.reasons[0].action,/重新扫描订阅/);assert.match(help.reasons[1].action,/不使用 AI 或网页工具绕过/);
  s.jobs=[{plan:{collections:s.settings.policies},counts:{audioDeferred:1}}];assert.equal(assistance(s,'zsxq').tone,'ai');
});
test('preprocessing prompt has no execution range or audio stage and directly opens QR login when needed',()=>{
  const {buildPreflightPrompt}=require('../src/main/sync/assistance');
  const s=state();s.settings.policies=[{provider:'zsxq',collectionId:'123',name:'Selected',mode:'incremental'}];
  const prompt=buildPreflightPrompt(s,'zsxq',{issues:[{code:'human_login_required'}],loginGroupId:'123'},'/archive',{appRoot:'/app',packaged:true,resourcesPath:'/resources',nodeExecutable:'/app/IR System'});
  assert.match(prompt,/直接通过已有 login 入口打开/);assert.match(prompt,/不要下载资料/);assert.match(prompt,/不调用语音模型/);
  assert.match(prompt,/--group-id/);assert.match(prompt,/NODE_PATH/);assert.doesNotMatch(prompt,/startdate|enddate|2026-\d\d-\d\d|audio-transcribe/);
});
