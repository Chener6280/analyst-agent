"use strict";
// Fixed desktop bridge. No model, shell command, URL or selector is accepted.
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const {buildPlan,ZsxqWebError,defaultChromePath,defaultProfileDir,resolveCli,runZsxqCli}=require('./core');
const {runPlan}=require('./archive');
const {makeControl,isPause}=require('./control');
function cliRuntimeCheck(){
  try{
    const status=runZsxqCli(resolveCli(),['auth','status'],{timeoutMs:5000});
    if(/not logged in|未登录/i.test(status)||!/logged in|已登录/i.test(status))return {status:'needs_attention',code:'zsxq_auth_required'};
    return {status:'ready',code:null};
  }catch(e){return {status:'needs_attention',code:/^[a-z_]+$/.test(e.code)?e.code:'zsxq_cli_failed'};}
}
function runtimeCheck(root){
  const issues=[];
  const add=(code,title,action)=>issues.push({code,title,detail:'知识星球网页下载通道的本机检查。',action,level:'attention'});
  if(!fs.existsSync(defaultChromePath()))add('chrome_not_found','未找到网页下载浏览器','安装或配置 Chrome 后重新检查；不会自动安装。');
  if(!fs.existsSync(defaultProfileDir()))add('human_login_required','专用浏览器尚未登录','点击“网页登录”，在专用浏览器中扫码；不读取 Safari 的登录凭据。');
  if(root&&fs.existsSync(path.join(root,'zsxq_web/.archive.lock')))add('web_archive_locked','网页归档锁需要核验','等待原网页任务结束；异常退出时由维护者核验，不自动删除锁。');
  return {status:issues.length?'needs_attention':'ready',issues,loginVerified:false};
}
function prepareDesktop(request,now=Date.now()){
  const {catalog,row,archiveRoot,scopeKey,limits}=request;
  if(!path.isAbsolute(archiveRoot||'')||!fs.statSync(archiveRoot).isDirectory()||!/^[0-9a-f]{64}$/.test(scopeKey||''))throw new ZsxqWebError('web_request_invalid','Invalid desktop scope',2);
  const source=catalog?.sources?.find(s=>s.provider==='zsxq'),stamp=Date.parse(catalog?.scannedAt);
  if(!source?.complete||catalog.complete!==true||!Number.isFinite(stamp)||stamp>now||now-stamp>15*60000)throw new ZsxqWebError('fresh_scan_required','A complete current all-group scan is required',12);
  if(row?.provider!=='zsxq'||!/^\d{1,30}$/.test(row.collectionId||'')||row.start>row.end)throw new ZsxqWebError('web_request_invalid','Invalid collection',2);
  for(const k of ['maxOperations','maxRecords','maxFiles','maxBytes','maxFileBytes','maxSeconds'])if(!Number.isSafeInteger(limits?.[k])||limits[k]<0)throw new ZsxqWebError('web_request_invalid','Invalid budget',2);
  const scan={scanned_at:catalog.scannedAt,groups:source.collections.map(g=>({...g,group_id:g.collectionId}))};
  const plan=buildPlan(scan,{start:row.start,end:row.end,archiveRoot,groupIds:[row.collectionId]});
  const job=plan.jobs[0];
  if(job?.route!=='zsxq_web'||job.state!=='pending')throw new ZsxqWebError(job?.reason||'route_changed','Selected group is not eligible for the web route',12);
  if(job.permissions?.allow_download!==true||job.membership?.active!==true)throw new ZsxqWebError('download_disabled_by_group','No download authorization',21);
  job.job_id='desktop-'+crypto.createHash('sha256').update(JSON.stringify({scopeKey,group:row.collectionId,start:row.start,end:row.end,include:job.include,media:'text_non_audio'})).digest('hex').slice(0,24);
  return plan;
}
async function executeDesktop(request,{runtime={},onControl=()=>{}}={}){
  const plan=prepareDesktop(request),control=makeControl(request.limits);onControl(control);
  let result,manifest=null,code=null,status;
  try{
    if(request.limits.maxRecords===0)throw new ZsxqWebError('record_budget_exhausted','Topic budget reached before browser startup',12);
    if(request.limits.maxOperations===0)throw new ZsxqWebError('operation_budget_exhausted','Operation budget reached before browser startup',12);
    result=await runPlan(plan,{headless:true,headed:process.env.IR_SYSTEM_WEB_BROWSER_MODE==='visible',mediaPolicy:'text_non_audio',control,isolateItemFailures:true,maxJobsPerRun:1,
      maxScrolls:Math.max(1,request.limits.maxOperations),maxTopicsPerRun:Math.max(1,request.limits.maxRecords),
      maxAssetsPerRun:Math.max(1,request.limits.maxFiles),maxAssetsPerTopic:1000,
      assetMaxBytes:request.limits.maxFileBytes,sizeGuardBytes:Number.MAX_SAFE_INTEGER,downloadTimeoutMs:30000},runtime);
    manifest=result.jobs[0];
    status=result.status==='completed'?'completed':manifest.run_budget_exhausted?'budget_paused':'needs_attention';
    code=status==='completed'?null:status==='budget_paused'?'record_budget_exhausted':'web_discovery_incomplete';
    if(manifest.all_discovered_attempted&&!manifest.all_discovered_processed&&(manifest.reached_date_floor||manifest.discovery_exhausted)){
      status='partial';code='web_items_pending';
    }
  }catch(e){
    code=/^[a-z][a-z0-9_]{0,90}$/.test(e.code||'')?e.code:'web_worker_failed';
    status=code==='user_stopped'?'stopped':isPause(code)?'budget_paused':['browser_interrupted','headless_browser_failed','headless_browser_missing','human_login_required'].includes(code)?'interrupted':'needs_attention';
    const expected=path.join(plan.archive_root,'zsxq_web/jobs',plan.jobs[0].job_id,'manifest.json');
    // Read only our exact job's manifest, never an upstream-supplied path.
    if(fs.existsSync(expected))try{manifest=JSON.parse(fs.readFileSync(expected,'utf8'));}catch{}
  }
  return {status,code,counts:control.counts,manifest:manifest?{
    job_id:plan.jobs[0].job_id,record_refs:manifest.record_refs||[],
    reached_date_floor:manifest.reached_date_floor,discovery_exhausted:manifest.discovery_exhausted,
    all_discovered_processed:manifest.all_discovered_processed,coverage_complete:false,
    failures:manifest.failures||{},
    manifest_path:path.join('zsxq_web/jobs',plan.jobs[0].job_id,'manifest.json')}:null};
}
async function main(){
  let raw='';for await(const chunk of process.stdin){raw+=chunk;if(raw.length>2*1024*1024)throw new Error('request_limit');}
  const request=JSON.parse(raw);
  let result;
  if(request.command==='check')result={status:'completed',web:runtimeCheck(request.archiveRoot),zsxqCli:cliRuntimeCheck()};
  else if(request.command==='login'){
    if(!/^\d{1,30}$/.test(request.groupId||''))throw new ZsxqWebError('invalid_group_id','Invalid group',2);
    const controller=new AbortController();
    const stop=()=>controller.abort();process.on('SIGTERM',stop);process.on('SIGINT',stop);
    const browser=require('./browser');
    try{await (process.env.IR_SYSTEM_WEB_BROWSER_MODE==='visible'?browser.login:browser.ensureLogin)({groupId:request.groupId,waitSeconds:120,signal:controller.signal});result={status:'completed'};}
    finally{process.off('SIGTERM',stop);process.off('SIGINT',stop);}
  }else if(request.command==='run')result=await executeDesktop(request,{onControl:control=>{process.on('SIGTERM',()=>{control.stopped=true;});process.on('SIGINT',()=>{control.stopped=true;});}});
  else throw new ZsxqWebError('web_request_invalid','Unknown command',2);
  process.stdout.write(JSON.stringify({protocol:'ir-system-sync/v1',type:'result',result})+'\n');
}
if(require.main===module)main().catch(e=>process.stdout.write(JSON.stringify({protocol:'ir-system-sync/v1',type:'result',result:{status:'needs_attention',code:/^[a-z][a-z0-9_]{0,90}$/.test(e.code||'')?e.code:'web_worker_failed'}})+'\n'));
module.exports={runtimeCheck,cliRuntimeCheck,prepareDesktop,executeDesktop};
