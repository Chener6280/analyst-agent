const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");
const { SyncManager } = require("../src/main/sync/manager");
const { makePlan, validateSettings } = require("../src/main/sync/policy");
const { createAgentBroker } = require("../src/main/sync/agent-broker");
const { piArguments, TOOLS } = require("../src/main/sync/pi-agent");

function fixture() {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "ir-sync-test-"));
  const archive = path.join(directory, "archive"); fs.mkdirSync(archive);
  const root = fs.realpathSync(archive);
  let resolve; const requests = [];
  const runner = (request, _provider, _runtime, progress) => {
    requests.push(request); progress({ stage: "scanning", counts: { operations: 1 } });
    return { promise: new Promise(r => { resolve = r; }), stop: () => resolve({ status: "stopped" }) };
  };
  const manager = new SyncManager(directory, () => ({ archiveRoot: root }), {}, runner);
  const settings = structuredClone(manager.view().settings);
  settings.policies = [{ provider: "ima", collectionId: "kb1", name: "private library", mode: "incremental", firstDate: "2026-01-01" }];
  manager.saveSettings(settings);
  const row={collectionId:'kb1',name:'private library',directoryAccess:'accessible',accessCode:null};
  manager.store.state.catalog={sources:[{provider:'ima',complete:true,scannedAt:new Date().toISOString(),collections:[row]}]};
  manager.store.state.imaAccess={kb1:{status:'api_sample_ok',code:'sample_read_ok',checkedAt:new Date().toISOString(),
    fingerprint:require('../src/main/sync/subscriptions').signature(row),configuration:manager.environmentKey()}};
  manager.store.save();
  return { manager, settings, root, directory, requests, finish: async r => { resolve(r); await new Promise(setImmediate); } };
}

test('new history action supersedes the old scope only after confirmation',()=>{
 const f=fixture(),s=f.manager.store.state;
 s.settings.policies=[{provider:'zsxq',collectionId:'123',name:'Fixture',mode:'incremental',firstDate:'2026-01-01'}];
 const selection={provider:'zsxq',start:'2026-08-27',end:'2026-09-26'};
 const plan=makePlan(s.settings,{},'backfill',f.root,undefined,selection);
 s.jobs=[{id:'legacy',kind:'sync',root:f.root,status:'needs_attention',attempt:1,plan,selection,membershipRepair:{code:'membership_classifier_updated'}}];
 const preview=f.manager.preview('backfill',null,selection);
 assert.equal(preview.resumeId,null);assert.equal(preview.replacements[0].jobId,'legacy');
 assert.equal(s.jobs[0].status,'needs_attention');
 const grant=f.manager.authorize('backfill',null,preview,selection);
 assert.notEqual(grant.jobId,'legacy');assert.equal(s.jobs.length,2);assert.equal(s.jobs[0].status,'superseded');
 const changed=f.manager.preview('backfill',null,{...selection,start:'2026-09-20'});
 assert.equal(changed.plan.collections[0].start,'2026-09-20');assert.equal(changed.replacements.length,1);
 assert.throws(()=>f.manager.preview('backfill','legacy',selection),/job_requires_maintainer/);
});

test('replacement stops a live writer and waits for its completion before authorizing a new one',async()=>{
 const f=fixture(),old=f.manager.authorize('incremental');f.manager.start(old.grantId);
 let closeWriter,stopRequested=false;
 const settled=new Promise(r=>{closeWriter=r;});
 f.manager.active.stop=()=>{stopRequested=true;};
 const original=f.manager.active.promise;
 f.manager.active.promise=Promise.all([original,settled]);
 const selection={provider:'ima',start:'2026-09-20',end:'2026-09-26'};
 const preview=f.manager.preview('backfill',null,selection,true);
 const pending=f.manager.replaceAndAuthorize('backfill',null,preview,selection);
 await new Promise(setImmediate);
 assert.equal(stopRequested,true);assert.equal(f.manager.view().replacing,true);
 assert.equal(f.manager.store.state.jobs.length,1);assert.equal(f.requests.length,1);
 assert.throws(()=>f.manager.start(old.grantId),/sync_busy/);
 await f.finish({status:'stopped'});closeWriter();
 const next=await pending;
 assert.equal(f.manager.store.state.jobs[0].status,'superseded');assert.equal(f.requests.length,1);
 f.manager.start(next.grantId);assert.equal(f.requests.length,2);await f.finish({status:'completed'});
});

test('old files/checkpoints persist, unused grants are revoked, and new job has a distinct checkpoint',()=>{
 const f=fixture(),old=f.manager.authorize('incremental');
 const directory=f.manager.store.jobDirectory(old.jobId);fs.mkdirSync(directory,{recursive:true});
 const file=path.join(directory,'checkpoint.json');fs.writeFileSync(file,'{"old":"retained"}');
 const asset=path.join(f.root,'original.pdf');fs.writeFileSync(asset,'retained original');
 const preview=f.manager.preview('backfill',null,{provider:'ima',start:'2026-09-20',end:'2026-09-26'});
 assert.equal(f.manager.store.state.jobs[0].status,'authorized');
 const next=f.manager.authorize('backfill',null,preview,preview.selection);
 assert.notEqual(f.manager.store.jobDirectory(next.jobId),directory);
 assert.equal(fs.readFileSync(file,'utf8'),'{"old":"retained"}');assert.equal(fs.readFileSync(asset,'utf8'),'retained original');
 assert.throws(()=>f.manager.start(old.grantId),/invalid_grant/);assert.deepEqual(f.manager.view().watermarks,{});
});

test('partial replacement retains the other source checkpoint and resumes only its remaining scope',async()=>{
 const f=fixture();f.settings.policies.push({provider:'zsxq',collectionId:'123',name:'star',mode:'incremental',firstDate:'2026-01-01'});f.manager.saveSettings(f.settings);
 const old=f.manager.authorize('incremental');f.manager.start(old.grantId);await f.finish({status:'budget_paused'});
 const next=f.manager.authorize('incremental',null,null,{provider:'zsxq'});
 const original=f.manager.store.state.jobs.find(j=>j.id===old.jobId);
 assert.equal(original.status,'budget_paused');assert.deepEqual(original.supersededKeys,['zsxq:123']);assert.equal(original.plan.collections.length,2);
 f.manager.start(next.grantId);await f.finish({status:'completed'});
 const preview=f.manager.preview('incremental',old.jobId);assert.deepEqual(preview.executionCollections.map(r=>r.provider),['ima']);
 const resumed=f.manager.authorize('incremental',old.jobId,preview);f.manager.start(resumed.grantId);
 assert.deepEqual(f.requests.at(-1).excludedCollections,['zsxq:123']);await f.finish({status:'completed'});
 assert.equal(f.manager.view().watermarks['zsxq:123'].jobId,next.jobId);
});

test('unrelated live tasks and invalid confirmations cannot be replaced',async()=>{
 const f=fixture();f.settings.policies.push({provider:'zsxq',collectionId:'123',name:'star',mode:'incremental',firstDate:'2026-01-01'});f.manager.saveSettings(f.settings);
 const old=f.manager.authorize('incremental',null,null,{provider:'ima'});f.manager.start(old.grantId);
 assert.throws(()=>f.manager.preview('incremental',null,{provider:'zsxq'},true),/sync_busy/);
 const preview=f.manager.preview('incremental',null,{provider:'ima'},true);
 await assert.rejects(f.manager.replaceAndAuthorize('incremental',null,{...preview,revision:-1},{provider:'ima'}),/sync_scope_changed/);
 assert.equal(f.manager.store.state.jobs[0].status,'running');await f.finish({status:'stopped'});
});

test("strict policy validation never defaults to all sources or all dates", () => {
  const f = fixture();
  assert.throws(() => validateSettings({ ...f.settings, shell: "bad" }));
  assert.throws(() => validateSettings({ ...f.settings, policies: [{ ...f.settings.policies[0], firstDate: "" }] }));
  assert.throws(() => validateSettings({ ...f.settings, budgets: { ...f.settings.budgets, maxFiles: -1 } }));
  assert.throws(() => validateSettings({ ...f.settings, policies: [f.settings.policies[0], f.settings.policies[0]] }));
  assert.throws(() => makePlan({ ...f.settings, policies: [] }, {}, "incremental", f.root));
  const plan = makePlan(f.settings, {}, "incremental", f.root, "2026-09-26");
  assert.equal(plan.collections.length, 1); assert.equal(plan.media, "text_non_audio");
});

test("once/off/pending policies are separate from increments and completed once is excluded", () => {
  const f = fixture(); f.settings.policies[0].mode = "once";
  assert.throws(() => makePlan(f.settings, {}, "incremental", f.root));
  assert.equal(makePlan(f.settings, {}, "backfill", f.root).collections.length, 1);
  assert.throws(() => makePlan(f.settings, { "ima:kb1": { onceComplete: true } }, "backfill", f.root));
});

test("approval preview is read-only and changed scope requires a new confirmation", () => {
  const f = fixture(), before = JSON.stringify(f.manager.store.state);
  const preview = f.manager.preview("incremental");
  assert.equal(JSON.stringify(f.manager.store.state), before);
  assert.equal(preview.plan.collections[0].collectionId, "kb1");
  f.settings.budgets.maxFiles = 21; f.manager.saveSettings(f.settings);
  assert.throws(() => f.manager.authorize("incremental", null, preview), /sync_scope_changed/);
  assert.equal(f.manager.view().jobs.length, 0);
  assert.throws(() => validateSettings({ ...f.settings, policies: [{ ...f.settings.policies[0], firstDate: "2026-99-99" }] }), /invalid_first_date/);
});
test('local checks use a read-only command, never add jobs, and do not replace subscription evidence',async()=>{
  const f=fixture();delete f.manager.store.state.imaAccess;const check=f.manager.checkLocal();
  assert.equal(f.requests[0].command,'check');assert.equal(f.manager.view().busy,true);
  assert.equal(f.manager.view().jobs.length,0);
  await f.finish({status:'completed',localCheck:{status:'ready',issues:[]}});await check;
  assert.equal(f.manager.view().busy,false);assert.equal(f.manager.view().jobs.length,0);
  assert.equal(f.manager.view().readiness.ima.tone,'ready');
  assert.equal(f.manager.view().imaAccess.kb1?.status||'unverified','unverified');
});
test('local archive maintenance is included in the same pre-analysis busy state',()=>{
  const f=fixture();const view=f.manager.view({externalBusy:true});
  assert.equal(view.busy,true);
  assert.ok(view.readiness.ima.issues.some(i=>i.code==='system_busy'));
  assert.equal(f.manager.view().busy,false);
});
test('preprocessing login validates selected web scope, runs login only, and adds no download job',async()=>{
  const f=fixture();await assert.rejects(f.manager.webLogin(),/scope_required/);
  const stamp=new Date().toISOString();
  f.manager.store.state.settings.policies=[{provider:'zsxq',collectionId:'123',name:'Fixture',mode:'incremental'}];
  f.manager.store.state.catalog={sources:[{provider:'zsxq',complete:true,scannedAt:stamp,collections:[{collectionId:'123',membership:{active:true},permissions:{allow_download:true},skill_api:'not_enabled'}]}]};
  f.manager.localCheck={status:'ready',checkedAt:stamp,configuration:f.manager.environmentKey(),zsxqCli:{status:'ready'},web:{status:'needs_attention',issues:[{code:'human_login_required'}],loginVerified:false}};
  const login=f.manager.webLogin();assert.equal(f.requests[0].command,'web-login');assert.equal(f.requests[0].groupId,'123');
  assert.equal(f.manager.view().jobs.length,0);assert.equal(f.manager.view().busy,true);
  await f.finish({status:'completed'});await login;
  assert.equal(f.manager.view().readiness.zsxq.tone,'ready');assert.equal(f.manager.view().jobs.length,0);
  const verifiedAt=f.manager.localCheck.web.verifiedAt;
  const recheck=f.manager.checkLocal(true);
  await f.finish({status:'completed',localCheck:{status:'ready',zsxqCli:{status:'ready'},web:{status:'ready',loginVerified:false,issues:[]}}});await recheck;
  assert.equal(f.manager.localCheck.web.loginVerified,true);assert.equal(f.manager.localCheck.web.verifiedAt,verifiedAt);
  assert.equal(f.manager.store.state.webLoginCheck.status,'completed');
});

test("start is idempotent, expires and only completed jobs advance watermarks", async () => {
  const f = fixture(), grant = f.manager.authorize("incremental");
  assert.equal(f.manager.start(grant.grantId).status, "running");
  f.manager.start(grant.grantId); assert.equal(f.requests.length, 1);
  assert.throws(() => f.manager.saveSettings(f.settings), /busy/);
  // A per-file safety cap still needs new authorization; ordinary per-batch
  // file counts now continue automatically for IMA as well as ZSXQ.
  await f.finish({ status: "budget_paused", code: "asset_exceeds_authorized_budget" });
  assert.deepEqual(f.manager.store.state.watermarks, {});
  f.manager.start(grant.grantId); assert.equal(f.requests.length, 1);
  assert.equal(f.manager.preview("incremental").replacements[0].jobId,grant.jobId);
  f.settings.budgets.maxFiles = 30; f.manager.saveSettings(f.settings);
  const resumed = f.manager.authorize("incremental", grant.jobId);
  assert.equal(f.manager.store.state.jobs[0].plan.budgets.maxFiles, 30);
  f.manager.start(resumed.grantId);
  await f.finish({ status: "completed", counts: { downloaded: 2 } });
  assert.equal(f.manager.store.state.watermarks[f.root]["ima:kb1"].jobId, grant.jobId);
  const next = f.manager.authorize("incremental");
  f.manager.store.state.grants[next.grantId].expires = 0;
  assert.throws(() => f.manager.start(next.grantId), /expired/);
});

test("restart preserves a resumable job without silently rerunning it", async () => {
  const f = fixture(), grant = f.manager.authorize("incremental");
  f.manager.start(grant.grantId);
  const restarted = new SyncManager(f.directory, () => ({ archiveRoot: f.root }), {});
  assert.equal(restarted.report(grant.jobId).status, "interrupted");
  assert.equal(restarted.active, null);
  await f.finish({ status: "stopped" });
});

test("source config changes revoke grants and reports never expose private scope", () => {
  const f = fixture(), grant = f.manager.authorize("incremental");
  f.manager.saveSettings(f.settings);
  assert.throws(() => f.manager.start(grant.grantId), /invalid_grant/);
  const report = JSON.stringify(f.manager.report(grant.jobId));
  assert.ok(!report.includes(f.root)); assert.ok(!report.includes("private library")); assert.ok(!report.includes("kb1"));
});

test("loopback broker authenticates, rejects scope mutations, origin, foreign job and arbitrary tools", async () => {
  const f = fixture(), grant = f.manager.authorize("incremental");
  const broker = await createAgentBroker(f.manager, grant.grantId, { maxCalls: 8 });
  async function request(tool, args = {}, token = broker.token, extra = {}) {
    return fetch(broker.url, { method: "POST", headers: { Authorization: `Bearer ${token}`, ...extra }, body: JSON.stringify({ tool, arguments: args }) });
  }
  try {
    assert.equal((await request("sync_start", {}, "bad")).status, 403);
    assert.equal((await request("sync_start", {}, broker.token, { Origin: "https://evil.invalid" })).status, 403);
    assert.equal((await request("bash")).status, 400);
    assert.equal((await request("sync_start", { provider: "other" })).status, 400);
    assert.equal((await request("sync_start", { jobId: "foreign" })).status, 400);
    assert.equal((await request("sync_start", [])).status, 400);
    const r = await (await request("sync_start")).json(); assert.equal(r.status, "running");
    assert.equal((await (await request("sync_report")).json()).jobId, grant.jobId);
    await request("sync_start"); assert.equal(f.requests.length, 1);
    await f.finish({ status: "completed" });
  } finally { broker.close(); }
});

test("Pi has only explicit sync tools, no model override or session reuse", () => {
  const args = piArguments("/test/pi-sync.ts", "start");
  assert.equal(args[args.indexOf("--tools") + 1], TOOLS.join(","));
  for (const flag of ["--no-context-files", "--no-skills", "--no-extensions", "--no-session", "--no-approve", "--offline"]) assert.ok(args.includes(flag));
  for (const flag of ["--model", "--continue", "--resume", "--api-key"]) assert.ok(!args.includes(flag));
});

test("explanation grants cannot start, stop or expand an existing job", async () => {
  const f = fixture(), grant = f.manager.authorize("incremental");
  const readOnly = f.manager.authorizeReport(grant.jobId);
  assert.throws(() => f.manager.start(readOnly), /read_only/);
  const broker = await createAgentBroker(f.manager, readOnly);
  try {
    for (const tool of ["sync_start", "sync_stop"]) {
      const result = await fetch(broker.url, { method: "POST", headers: { Authorization: `Bearer ${broker.token}` }, body: JSON.stringify({ tool, arguments: {} }) });
      assert.equal(result.status, 400);
    }
    assert.equal(f.requests.length, 0);
  } finally { broker.close(); }
});

test("source-scoped history supports explicit dates without including other sources or moving increments", async () => {
  const f = fixture();
  f.settings.policies.push({ provider: "zsxq", collectionId: "12345", name: "other", mode: "incremental", firstDate: "2026-01-01" });
  f.manager.saveSettings(f.settings);
  f.manager.store.state.watermarks[f.root] = { "ima:kb1": { through: "2026-09-24", jobId: "previous" } };
  const scope = { provider: "ima", start: "2025-09-01", end: "2025-09-30" };
  const preview = f.manager.preview("backfill", null, scope);
  assert.equal(preview.plan.collections.length, 1);
  assert.equal(preview.plan.collections[0].start, "2025-09-01");
  assert.equal(preview.plan.collections[0].mode, "incremental");
  const grant = f.manager.authorize("backfill", null, preview, scope);
  f.manager.start(grant.grantId); await f.finish({ status: "completed" });
  const mark = f.manager.view().watermarks["ima:kb1"];
  assert.equal(mark.through, "2026-09-24"); assert.equal(mark.jobId, "previous");
  assert.equal(mark.history[0].end, "2025-09-30"); assert.equal(mark.onceComplete, false);
  assert.equal(f.manager.preview("incremental", null, scope).plan.collections[0].start, scope.start);
  assert.throws(() => f.manager.preview("backfill", null, { ...scope, provider: "alphapai" }), /unsupported_sync_source/);
  assert.throws(() => f.manager.preview("backfill", null, { ...scope, start: "2027-10-01" }), /history_range/);
});

test("unresolved source blocks only overlapping collections and history resume preserves range", async () => {
  const f = fixture();
  f.settings.policies.push({ provider: "zsxq", collectionId: "12345", name: "other", mode: "incremental", firstDate: "2026-01-01" });
  f.manager.saveSettings(f.settings);
  const scope = { provider: "ima", start: "2026-02-01", end: "2026-02-28" };
  const grant = f.manager.authorize("backfill", null, null, scope);
  f.manager.start(grant.grantId); await f.finish({ status: "budget_paused" });
  assert.equal(f.manager.preview("incremental", null, { provider: "ima" }).replacements[0].jobId,grant.jobId);
  assert.equal(f.manager.preview("incremental", null, { provider: "zsxq" }).plan.collections.length, 1);
  const resumed = f.manager.authorize("incremental", grant.jobId);
  const job = f.manager.store.state.jobs.find(j => j.id === resumed.jobId);
  assert.equal(job.plan.kind, "backfill"); assert.equal(job.plan.collections[0].end, "2026-02-28");
});

test("source scans preserve other sources and local CLI profiles never launch a command", async () => {
  const f = fixture();
  f.manager.scan(["ima"]); await f.finish({ status: "completed", catalog: { scannedAt: "2026-09-25T00:00:00Z", sources: [{ provider: "ima", complete: true, collections: [{ collectionId: "kb1" }] }] } });
  f.manager.scan(["zsxq"]); await f.finish({ status: "completed", catalog: { scannedAt: "2026-09-26T00:00:00Z", sources: [{ provider: "zsxq", complete: true, collections: [{ collectionId: "12345" }] }] } });
  assert.equal(f.manager.view().catalog.sources.length, 2);
  assert.equal(f.manager.view().catalog.sources[0].scannedAt, "2026-09-25T00:00:00Z");
  const calls = f.requests.length;
  f.manager.saveConsoleSettings({ runtime: "kimi", commands: { pi: "/example/pi", kimi: "/example/kimi", custom: "" } });
  assert.equal(f.manager.view().consoleSettings.runtime, "kimi"); assert.equal(f.requests.length, calls);
  assert.equal(f.manager.view().settings.piCommand, "/example/pi");
  assert.throws(() => f.manager.saveConsoleSettings({ runtime: "custom", commands: { pi: "pi", kimi: "kimi", custom: "a\nb" } }), /invalid_cli_command/);
});
