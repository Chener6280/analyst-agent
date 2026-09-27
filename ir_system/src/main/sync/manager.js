const fs = require("node:fs");
const path = require("node:path");
const { randomUUID } = require("node:crypto");
const { SyncStore } = require("./store");
const { validateSettings, validateSelection, makePlan, key, SOURCES, exact } = require("./policy");
const { runWorker } = require("./runner");
const { applyCatalog, acknowledge, signature } = require('./subscriptions');
const {assistance,buildPrompt,buildPreflightPrompt}=require('./assistance');
const sources=require('../../shared/sources');
const {readiness}=require('./readiness');
const {access:imaAccess,saveProbes,searchCheckpoint,saveSearch,safeDiagnostic}=require('./ima-access');
const {setConsidered,clearRestoredExclusions}=require('./issue-selection');
const {downloadStatus}=require('./download-status');
const {applyAudit}=require('./capability-audit');
const {applyDownloadDefaults}=require('./download-selection');
const {isRecoveredScanFailure,recoverScanFailures}=require('./scan-recovery');
const {identifyRepair,canResume}=require('./membership-repair');
const {remaining,replacements,supersede}=require('./replacement');
const {runBatches}=require('./batch-runner');
const {updateRoute}=require('./update-route');

class SyncManager {
  constructor(directory, getProvider, runtime, runner = runWorker) {
    this.store = new SyncStore(directory); this.getProvider = getProvider;
    this.runtime = runtime; this.runner = runner; this.active = null; this.agent = null;
    this.localCheck=null;this.localChecking=null;
    try{if(applyAudit(this.store.state,directory,this.environmentKey()))this.store.save();}
    catch{this.store.state.capabilityAuditError='capability_audit_invalid';this.store.save();}
    if(applyDownloadDefaults(this.store.state,{configuration:this.environmentKey()}))this.store.save();
    let repaired=false;
    for(const job of this.store.state.jobs){
      const evidence=identifyRepair(job);
      if(evidence&&!job.membershipRepair){job.membershipRepair=evidence;repaired=true;}
    }
    if(repaired)this.store.save();
  }
  view({externalBusy=false}={}) {
    const s = this.store.state;
    let root = this.getProvider().archiveRoot || "";
    try { root = fs.realpathSync(root); } catch { /* Unconfigured archive: no invented watermarks. */ }
    return structuredClone({ schemaVersion: 1, revision: s.revision, settings: s.settings, catalog: s.catalog,
      consoleSettings: s.consoleSettings, subscriptionReview:s.subscriptionReview, watermarks: s.watermarks[root] || {},
      jobs: s.jobs.filter(j => ['scan','ima_probe'].includes(j.kind) || j.root === root).slice(-30).reverse().map(({ plan, ...j }) => ({ ...j, recoveredBeforeDownload:isRecoveredScanFailure({...j,plan}), kind: plan?.kind || j.kind, collections: j.status==='superseded'?plan?.collections||[]:remaining({...j,plan}), collectionCount: remaining({...j,plan}).length })),
      busy: Boolean(this.active || this.agent || this.localChecking || this.replacing || externalBusy), agentConnected: Boolean(this.agent),
      replaceableProviders:!this.replacing&&!this.localChecking&&!externalBusy?[...new Set(remaining(s.jobs.find(j=>j.id===(this.active?.id||this.agent?.jobId))||{}).map(c=>c.provider))]:[],
      replacing:Boolean(this.replacing),
      imaAccess:Object.fromEntries(s.settings.policies.filter(p=>p.provider==='ima').map(p=>[p.collectionId,imaAccess(s,p.collectionId,{configuration:this.environmentKey()})])),
      downloadStatus:Object.fromEntries(s.settings.policies.map(p=>[key(p),downloadStatus(s,p.provider,p.collectionId,{configuration:this.environmentKey()})])),
      updateRoutes:Object.fromEntries(s.settings.policies.map(p=>[key(p),updateRoute(s,p.provider,p.collectionId,{configuration:this.environmentKey(),imaClientAvailable:this.imaClientAvailable()})])),
      assistance:Object.fromEntries(sources.map(p=>[p.id,assistance(s,p.id,{configuration:this.environmentKey()})])),
      readiness:Object.fromEntries(sources.map(p=>[p.id,readiness(s,p.id,{root,configuration:this.environmentKey(),localCheck:this.localCheck?.configuration===this.environmentKey()?this.localCheck:null,busy:Boolean(this.active||this.agent||this.localChecking||externalBusy)})])),
      implementation: "API first; deterministic ZSXQ web and macOS IMA accessibility fallback; no automatic audio/OCR" });
  }
  saveSettings(input) {
    this.idle(); this.store.state.settings = validateSettings(input); this.store.state.revision++;
    acknowledge(this.store.state,this.store.state.settings.policies);
    clearRestoredExclusions(this.store.state);
    // Configuration changes revoke unused grants, including grants issued by another view.
    for (const g of Object.values(this.store.state.grants)) if (!g.used) g.revoked = true;
    this.store.save(); return this.view();
  }
  setIssueConsidered(input){
    this.idle();exact(input,['provider','issueId','considered','revision']);
    if(!SOURCES.includes(input.provider)||typeof input.issueId!=='string'||typeof input.considered!=='boolean')throw new Error('invalid_issue_choice');
    if(input.revision!==this.store.state.revision)throw new Error('issue_state_changed');
    setConsidered(this.store.state,input.provider,this.view().readiness[input.provider],input.issueId,input.considered);
    this.store.save();return this.view();
  }
  probePreview(selection={}){
    this.idle();
    exact(selection,['collectionId','restartSearch']);
    if(selection.collectionId!==undefined&&(typeof selection.collectionId!=='string'||!/^[A-Za-z0-9_+=.-]{1,512}$/.test(selection.collectionId)))throw new Error('invalid_probe_selection');
    if(selection.restartSearch!==undefined&&(typeof selection.restartSearch!=='boolean'||!selection.collectionId))throw new Error('invalid_probe_selection');
    const s=this.store.state,configuration=this.environmentKey();
    // Explicit one-library diagnosis may inspect an unselected library without
    // subscribing it to updates. Batch checks still use only selected scope.
    const selected=s.settings.policies.filter(p=>p.provider==='ima'&&(selection.collectionId?
      p.collectionId===selection.collectionId&&p.mode!=='pending_selection'&&s.catalog?.sources.find(s=>s.provider==='ima')?.collections.some(c=>c.collectionId===p.collectionId&&c.present!==false):p.mode==='incremental'));
    if(selection.collectionId&&!selected.length)throw new Error('invalid_probe_selection');
    if(!selected.length)throw new Error('no_selected_collections');
    const rows=selected.filter(p=>selection.collectionId?p.collectionId===selection.collectionId:imaAccess(s,p.collectionId,{configuration}).status!=='api_sample_ok');
    if(!rows.length)throw new Error(selection.collectionId?'invalid_probe_selection':'ima_no_pending_probes');
    if(rows.length>25)throw new Error('ima_probe_scope_limit');
    return {revision:s.revision,configuration,selection,retainedPassed:s.settings.policies.filter(p=>p.provider==='ima'&&p.mode==='incremental'&&!rows.includes(p)&&imaAccess(s,p.collectionId,{configuration}).status==='api_sample_ok').length,
      rows:rows.map(p=>({collectionId:p.collectionId,name:p.name}))};
  }
  probeIma(confirmed){
    const preview=this.probePreview(confirmed?.selection);
    if(JSON.stringify(preview)!==JSON.stringify(confirmed))throw new Error('sync_scope_changed');
    const job={id:randomUUID(),kind:'ima_probe',providers:['ima'],probeSelection:preview.rows.map(r=>r.collectionId),
      probeConfiguration:preview.configuration,probeFingerprints:Object.fromEntries(preview.rows.map(r=>[r.collectionId,signature(this.store.state.catalog?.sources.find(s=>s.provider==='ima')?.collections.find(c=>c.collectionId===r.collectionId)||{present:false})])),
      status:'running',createdAt:new Date().toISOString(),counts:{}};
    const probeCheckpoints={};
    for(const id of job.probeSelection){
      if(preview.selection.restartSearch)delete this.store.state.imaProbeSearch?.[id];
      else {const c=searchCheckpoint(this.store.state,id,preview.configuration);if(c)probeCheckpoints[id]=structuredClone(c);}
    }
    this.store.state.jobs.push(job);
    saveProbes(this.store.state,{...job,finishedAt:job.createdAt,code:'probe_in_progress'},[]);
    this.store.save();
    this.launch(job,{command:'ima-probe',providers:['ima'],selected:job.probeSelection,probeCheckpoints});
    return this.report(job.id);
  }
  prompt(provider,kind,range){return buildPrompt(this.store.state,provider,kind,range,this.getProvider().archiveRoot,this.runtime);}
  preflightPrompt(provider){return buildPreflightPrompt(this.store.state,provider,this.view().readiness[provider],this.getProvider().archiveRoot,this.runtime);}
  async webLogin(){
    this.idle();const groupId=this.view().readiness.zsxq.loginGroupId;
    if(!groupId)throw new Error('web_login_scope_required');
    if(!this.localCheck?.web||(this.localCheck.web.issues||[]).some(i=>i.code!=='human_login_required'))throw new Error('web_environment_not_ready');
    const configuration=this.environmentKey(),running=this.runner({command:'web-login',groupId},this.getProvider(),this.runtime,()=>{});
    const promise=running.promise.then(result=>{
      if(this.localCheck?.configuration===configuration){
        const code=result.code||'web_login_check_failed',verifiedAt=new Date().toISOString();
        if(result.status==='completed')this.localCheck.web={status:'ready',issues:[],loginVerified:true,verifiedAt};
        else this.localCheck.web={status:'needs_attention',loginVerified:false,issues:[{code,
          title:code==='human_login_required'?'等待本人扫码登录':code==='membership_expired'?'星球续期提示被返回，账号登录尚未确认':'网页登录核验遇到程序错误',
          detail:`网页登录核验结果：${code}。不代表全部网页星球不可下载。`,
          action:code==='human_login_required'?'点击检查本地环境重新打开登录页，完成本人扫码；不启动下载。':'保留此错误码交给维护者；不要反复扫码或取消全部星球。',level:'attention'}]};
        this.store.state.webLoginCheck={status:result.status,code:result.code||null,checkedAt:verifiedAt};this.store.save();
      }
      return result;
    }).finally(()=>{this.localChecking=null;});
    this.localChecking={...running,promise};return promise;
  }
  environmentKey(){const p=this.getProvider();return JSON.stringify([p.archiveRoot||'',p.pythonCommand||'python3',p.irSearchPath||'']);}
  recoverScanFailures(){
    let root=this.getProvider().archiveRoot||'';try{root=fs.realpathSync(root);}catch{return;}
    if(recoverScanFailures(this.store.state,{root,configuration:this.environmentKey(),localCheck:this.localCheck,
      hasCheckpoint:job=>{try{fs.lstatSync(this.store.jobDirectory(job.id));return true;}catch(e){return e.code!=='ENOENT';}}}))this.store.save();
  }
  async checkLocal(force=false){
    if(this.localChecking)return this.localChecking.promise;
    this.idle();
    const configuration=this.environmentKey();
    if(!force&&this.localCheck?.configuration===configuration&&Date.now()-Date.parse(this.localCheck.checkedAt)<30000)return this.localCheck;
    const running=this.runner({command:'check',archiveRoot:this.getProvider().archiveRoot||''},this.getProvider(),this.runtime,()=>{});
    const promise=running.promise.then(result=>{
      const check=result.localCheck||{status:'unknown',code:result.code||'local_check_unavailable',issues:[]};
      const previous=this.localCheck;
      if(previous?.configuration===configuration&&previous.web?.loginVerified&&check.web?.status==='ready'&&
        Date.now()-Date.parse(previous.web.verifiedAt)<10*60000){
        check.web={...check.web,loginVerified:true,verifiedAt:previous.web.verifiedAt};
      }
      this.localCheck={...check,checkedAt:new Date().toISOString(),configuration};this.recoverScanFailures();return this.localCheck;
    }).finally(()=>{this.localChecking=null;});
    this.localChecking={...running,promise};return promise;
  }
  saveConsoleSettings(input) {
    this.idle(); exact(input, ["runtime", "commands"]); exact(input.commands, ["pi", "kimi", "custom"]);
    if (!["pi", "kimi", "custom"].includes(input.runtime)) throw new Error("unsupported_console_runtime");
    for (const runtime of ["pi", "kimi", "custom"]) {
      const command = input.commands[runtime];
      if (typeof command !== "string" || command.length > 1024 || /[\0\r\n]/.test(command) || (runtime !== "custom" && !command.trim())) throw new Error("invalid_cli_command");
    }
    this.store.state.consoleSettings = { runtime: input.runtime, commands: Object.fromEntries(Object.entries(input.commands).map(([k, v]) => [k, v.trim()])) };
    this.store.state.settings.piCommand = input.commands.pi.trim();
    this.store.state.revision++;
    for (const grant of Object.values(this.store.state.grants)) if (!grant.used) grant.revoked = true;
    this.store.save(); return this.view();
  }
  idle() { if (this.active || this.agent || this.localChecking || this.replacing) throw new Error("sync_busy"); }
  provider() {
    const p = this.getProvider();
    if (!p.archiveRoot || !path.isAbsolute(p.archiveRoot) || !fs.statSync(p.archiveRoot).isDirectory()) throw new Error("archive_root_required");
    return { ...p, archiveRoot: fs.realpathSync(p.archiveRoot) };
  }
  checkDownloadRoutes(plan){
    const state=this.store.state,configuration=this.environmentKey();
    for(const row of plan.collections)if(row.provider==='ima'){
      const route=updateRoute(state,'ima',row.collectionId,{configuration,imaClientAvailable:this.imaClientAvailable()});
      if(!route.ready)throw new Error(route.code);
    }
  }
  imaClientAvailable(){
    const root=this.runtime.packaged?this.runtime.resourcesPath:this.runtime.appRoot;
    return process.platform==='darwin'&&Boolean(root)&&fs.existsSync(path.join(root,'adapters/ima_client/ima-accessibility'));
  }
  preview(kind, resumeId = null, selection = {}, allowRunningReplacement=false) {
    if(!allowRunningReplacement)this.idle();
    if(this.localChecking||this.replacing)throw new Error('sync_busy');
    const p = this.provider(); const state = this.store.state;
    let plan;
    let scope = validateSelection(selection, kind);
    if (resumeId) {
      const job = state.jobs.find(j => j.id === resumeId);
      if (!job || !canResume(job)) throw new Error("job_requires_maintainer_or_new_scope");
      if (job.root !== p.archiveRoot || remaining(job).some(row => !state.settings.policies.some(policy =>
        key(policy) === key(row) && policy.mode === row.mode && policy.firstDate === row.firstDate))) throw new Error("resume_scope_changed");
      plan = structuredClone(job.plan); plan.budgets = structuredClone(state.settings.budgets);
      scope = {...job.selection,...(scope.browserMode?{browserMode:scope.browserMode}:{})};
    } else {
      plan = makePlan(state.settings, state.watermarks[p.archiveRoot] || {}, kind, p.archiveRoot, undefined, scope);
    }
    const replace=resumeId?[]:replacements(state,p.archiveRoot,plan);
    for(const id of [this.active?.id,this.agent?.jobId].filter(Boolean))if(resumeId||!replace.some(r=>r.jobId===id))throw new Error('sync_busy');
    if(this.agent&&!this.agent.jobId)throw new Error('sync_busy');
    const executionCollections=resumeId?remaining(state.jobs.find(j=>j.id===resumeId)):plan.collections;
    if(!executionCollections.length)throw new Error('no_selected_collections');
    this.checkDownloadRoutes({...plan,collections:executionCollections});
    const deferredCollections=scope.collectionIds?state.settings.policies.filter(row=>row.provider===scope.provider&&row.mode==='incremental'&&!scope.collectionIds.includes(row.collectionId)).map(row=>({collectionId:row.collectionId,name:row.name})):[];
    return { revision: state.revision, root: p.archiveRoot, plan, executionCollections, deferredCollections, selection: scope, resumeId, replacements:replace,
      untilComplete:executionCollections.every(c=>SOURCES.includes(c.provider)) };
  }
  async replaceAndAuthorize(kind,resumeId,confirmed,selection={}){
    const preview=this.preview(kind,resumeId,selection,true);
    if(JSON.stringify(preview)!==JSON.stringify(confirmed))throw new Error('sync_scope_changed');
    this.replacing=true;
    try{
      const targets=new Set(preview.replacements.map(r=>r.jobId));
      // Revoke unused model grants before waiting: an old agent cannot restart.
      for(const g of Object.values(this.store.state.grants))if(targets.has(g.jobId)&&!g.used)g.revoked=true;
      this.store.save();
      const waitStopped=async process=>{
        let timer;
        try{process.stop();await Promise.race([process.promise,new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error('previous_job_stop_timeout')),85000);})]);}
        finally{clearTimeout(timer);}
      };
      const agent=this.agent;if(agent)await waitStopped(agent);
      const running=this.active;if(running)await waitStopped(running);
    }finally{this.replacing=false;}
    // Scan completion may legitimately change subscription choices. Require a
    // new confirmation if settings/root/scope changed while stopping.
    const fresh=this.preview(kind,resumeId,selection);
    if(fresh.revision!==preview.revision||fresh.root!==preview.root||JSON.stringify(fresh.plan)!==JSON.stringify(preview.plan))throw new Error('sync_scope_changed');
    return this.authorize(kind,resumeId,fresh,selection);
  }
  authorize(kind, resumeId = null, confirmed = null, selection = {}) {
    const preview = this.preview(kind, resumeId, selection);
    if (confirmed && JSON.stringify(confirmed) !== JSON.stringify(preview)) throw new Error("sync_scope_changed");
    const state = this.store.state;
    let job = preview.resumeId ? state.jobs.find(j => j.id === preview.resumeId) : null;
    if (job) { job.plan = preview.plan; job.revision = preview.revision; job.selection=preview.selection; }
    else {
      job = { id: randomUUID(), kind: "sync", plan: preview.plan, selection: preview.selection, root: preview.root, revision: preview.revision, status: "authorized", createdAt: new Date().toISOString(), attempt: 0, counts: {} };
      supersede(state,preview.replacements,job.id);
      state.jobs.push(job);
    }
    const id = randomUUID();
    job.untilComplete=preview.untilComplete;
    job.deferredCollections=preview.deferredCollections;
    state.grants[id] = { jobId: job.id, revision: state.revision, root: preview.root, expires: Date.now() + 15 * 60000, used: false };
    this.store.save(); return { grantId: id, jobId: job.id, scope: { kind: job.plan.kind, collections: job.plan.collections.length, budgets: job.plan.budgets, media: job.plan.media } };
  }
  start(grantId) {
    if(this.replacing)throw new Error('sync_busy');
    const state = this.store.state, g = state.grants[grantId];
    if (!g || g.revoked) throw new Error("invalid_grant");
    if (g.readOnly) throw new Error("read_only_grant");
    const job = state.jobs.find(j => j.id === g.jobId);
    if (g.used) return this.report(job.id); // idempotent, never restarts a terminal job
    if (g.expires < Date.now() || g.revision !== state.revision || g.root !== this.provider().archiveRoot) throw new Error("grant_expired_or_changed");
    if (this.active) throw new Error("sync_busy");
    if(job.status==='superseded'||!remaining(job).length)throw new Error('job_superseded');
    this.checkDownloadRoutes({...job.plan,collections:remaining(job)});
    g.used = true; job.attempt++; job.status = "running"; job.code = null; job.startedAt = new Date().toISOString(); this.store.save();
    this.launch(job, { command: "run", plan: job.plan, browserMode:job.selection?.browserMode||'headless', excludedCollections:job.supersededKeys||[], jobDirectory: this.store.jobDirectory(job.id) });
    return this.report(job.id);
  }
  scan(providers) {
    this.idle();
    if (!Array.isArray(providers) || !providers.length || providers.some(p => !SOURCES.includes(p))) throw new Error("explicit_scan_sources_required");
    const job = { id: randomUUID(), kind: "scan", providers: [...new Set(providers)], status: "running", createdAt: new Date().toISOString(), counts: {} };
    this.store.state.jobs.push(job); this.store.save();
    this.launch(job, { command: "scan", providers: [...new Set(providers)] });
    return this.report(job.id);
  }
  launch(job, request) {
    request.subscriptionBaseline = this.store.state.catalog;
    if(job.kind==='sync'&&this.imaClientAvailable()){
      request.imaClientEnabled=true;
      request.imaClientCollections=remaining(job).filter(r=>r.provider==='ima'&&updateRoute(this.store.state,'ima',r.collectionId,{configuration:this.environmentKey(),imaClientAvailable:true}).client).map(r=>r.collectionId);
    }
    const runner=job.kind==='sync'&&job.untilComplete?(...args)=>runBatches(this.runner,...args):this.runner;
    const running = runner(request, this.getProvider(), this.runtime, event => {
      if(job.kind==='ima_probe'){
        saveSearch(this.store.state,job,event.imaProbeSearch);
        // Completed rows and page positions survive even a hard process interruption.
        const checked=(event.imaProbes||[]).filter(r=>r.checkedAt&&job.probeSelection.includes(r.collectionId));
        if(checked.length){
          job.probeRows={...job.probeRows,...Object.fromEntries(checked.map(r=>[r.collectionId,r]))};
          saveProbes(this.store.state,{...job,probeSelection:checked.map(r=>r.collectionId),finishedAt:new Date().toISOString()},checked);
        }
      }
      job.stage = event.stage; job.counts = event.counts || job.counts;
      if(event.batchNumber)job.batchNumber=event.batchNumber;
      this.store.save();
    });
    this.active = { id: job.id, ...running };
    this.active.promise=running.promise.then(result => {
      const allowed = ["completed", "partial", "needs_attention", "failed", "budget_paused", "interrupted", "stopped"];
      job.status = allowed.includes(result.status) ? result.status : "failed";
      job.code = result.code || null; job.counts = result.counts || job.counts;
      job.diagnostic = safeDiagnostic(result.diagnostic);
      if(result.batchCount)job.batchNumber=result.batchCount;
      if(['human_login_required','browser_interrupted'].includes(job.code)&&this.localCheck?.web)this.localCheck.web.loginVerified=false;
      job.coverageComplete = false; job.issues = result.issues || []; job.stage = result.stage || job.stage;
      job.webManifests=result.webManifests||job.webManifests||[];
      job.finishedAt = new Date().toISOString();
      if (result.catalog) {
        applyCatalog(this.store.state,result.catalog);
      }
      if(job.kind==='ima_probe'){
        saveSearch(this.store.state,job,result.imaProbeSearch);
        saveProbes(this.store.state,job,result.imaProbes?.length?result.imaProbes:Object.values(job.probeRows||{}));
        job.imaProbeDiagnostic=safeDiagnostic(result.imaProbeDiagnostic);
        job.imaProbes=job.probeSelection.map(id=>imaAccess(this.store.state,id,{configuration:job.probeConfiguration}));
        this.store.state.revision++;
        for(const grant of Object.values(this.store.state.grants))if(!grant.used)grant.revoked=true;
      }
      if (job.kind === "sync" && job.status === "completed") {
        const marks = this.store.state.watermarks[job.root] ||= {};
        for (const row of remaining(job)) {
          const previous = marks[key(row)] || {};
          if (job.plan.kind === "incremental") marks[key(row)] = { ...previous,
            ...(!job.selection?.start ? {through:row.end} : {}),
            latestWindow:{start:row.start,end:row.end}, checkedAt: job.finishedAt, jobId: job.id };
          else marks[key(row)] = { ...previous, history: [...(previous.history || []), { start: row.start, end: row.end, checkedAt: job.finishedAt, jobId: job.id }].slice(-50),
            onceComplete: previous.onceComplete || (!job.selection?.start && row.mode === "once") };
        }
      }
      applyDownloadDefaults(this.store.state,{configuration:this.environmentKey()});
      this.recoverScanFailures();
      this.active = null; this.store.save();
    }).catch(() => { job.status = "failed"; job.code = "worker_host_failed"; this.active = null; this.store.save(); });
  }
  report(id) {
    const job = this.store.state.jobs.find(j => j.id === id);
    if (!job) throw new Error("unknown_job");
    // Model-visible report: no library names/IDs, titles, filesystem paths or upstream payloads.
    return { schemaVersion: 1, jobId: job.id, status: job.status, stage: job.stage || null, code: job.code || null,
      counts: job.counts, issueCount: (job.issues || []).length, coverageComplete: false, attempt: job.attempt || 0 };
  }
  authorizeReport(id) {
    this.idle(); this.report(id);
    const grantId = randomUUID();
    this.store.state.grants[grantId] = { jobId: id, readOnly: true, expires: Date.now() + 180000 };
    this.store.save(); return grantId;
  }
  stop(id) {
    if (this.active?.id === id) this.active.stop();
    return this.report(id);
  }
  async close() {
    this.agent?.stop();
    const checking=this.localChecking;
    if(checking){checking.stop();await checking.promise;}
    const running = this.active;
    if (running) { running.stop(); await running.promise; }
  }
}
module.exports = { SyncManager };
