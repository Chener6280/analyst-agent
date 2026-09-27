const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const BOUNDARIES=new Set(['operation_budget_exhausted','record_budget_exhausted','file_budget_exhausted','byte_budget_exhausted','parse_budget_exhausted','time_budget_exhausted']);
const add=(a={},b={})=>{const sum={...a};for(const [k,v] of Object.entries(b))if(Number.isFinite(v)&&v>=0)sum[k]=(sum[k]||0)+v;return sum;};
function checkpointDigest(request){
 try{return crypto.createHash('sha256').update(fs.readFileSync(path.join(request.jobDirectory,'checkpoint.json'))).digest('hex');}catch{return null;}
}
// One explicit whole-scope authorization; bounded child batches retain the same
// checkpoint. No model, new scope, automatic error retry, or concurrent writer.
function runBatches(runner,request,provider,runtime,onEvent,{digest=checkpointDigest,delayMs=1000,permissionPolls=90,permissionDelayMs=2000}={}){
 let stopped=false,current=null,wake=null,counts={},batches=0,loginAttempted=false,browserRestarts=0,networkRetries=0;
 let permissionWaited=false;
 const promise=(async()=>{
  while(!stopped){
   const before=digest(request),base={...counts};batches++;
   current=runner(request,provider,runtime,event=>onEvent({...event,batchNumber:batches,counts:add(base,event.counts)}));
   const result=await current.promise;current=null;
   counts=add(base,result.counts);
   const final={...result,counts,batchCount:batches,lastBatchCounts:result.counts||{}};
   if(stopped)return {...final,status:'stopped',code:'user_stopped'};
   if(result.code==='ima_accessibility_required'&&request.imaClientEnabled&&!permissionWaited){
    permissionWaited=true;
    onEvent({stage:'waiting_accessibility',batchNumber:batches,counts});
    let allowed=false;
    for(let i=0;i<permissionPolls&&!stopped;i++){
     await new Promise(resolve=>{const timer=setTimeout(()=>{wake=null;resolve();},permissionDelayMs);wake=()=>{clearTimeout(timer);wake=null;resolve();};});
     if(stopped)break;
     current=runner({command:'ima-permission'},provider,runtime,()=>{});
     const check=await current.promise;current=null;
     if(check.status==='completed'){allowed=true;break;}
     if(check.code!=='ima_accessibility_required')return {...final,code:check.code};
    }
    if(stopped)return {...final,status:'stopped',code:'user_stopped'};
    if(!allowed)return final;
    onEvent({stage:'continuing',batchNumber:batches+1,counts});
    continue;
   }
   if(['network','timeout','network_error','request_timeout'].includes(result.code)&&networkRetries<3){
    networkRetries++;
    onEvent({stage:'retrying_network',batchNumber:batches+1,counts});
    await new Promise(resolve=>{const timer=setTimeout(()=>{wake=null;resolve();},delayMs*2**networkRetries);wake=()=>{clearTimeout(timer);wake=null;resolve();};});
    continue;
   }
   // Recover one closed/crashed background browser under the same authorization.
   // No permission/quota retries, no visible fallback and no infinite restart loop.
   if(result.code==='browser_interrupted'&&request.browserMode!=='visible'&&browserRestarts<1){
    browserRestarts++;
    onEvent({stage:'restarting_browser',batchNumber:batches+1,counts});
    await new Promise(resolve=>{const timer=setTimeout(()=>{wake=null;resolve();},delayMs);wake=()=>{clearTimeout(timer);wake=null;resolve();};});
    continue;
   }
   const loginGroup=request.plan?.collections.find(c=>c.provider==='zsxq'&&!(request.excludedCollections||[]).includes('zsxq:'+c.collectionId));
   if(result.code==='human_login_required'&&!loginAttempted&&loginGroup){
    loginAttempted=true;
    onEvent({stage:'waiting_browser_login',batchNumber:batches,counts});
    current=runner({command:'web-login',groupId:loginGroup.collectionId,browserMode:request.browserMode},provider,runtime,()=>{});
    const login=await current.promise;current=null;
    if(stopped)return {...final,status:'stopped',code:'user_stopped'};
    if(login.status!=='completed')return {...final,status:'interrupted',code:login.code||'human_login_required'};
    // Human action resolved the authentication condition. Resume the exact
    // already-authorized plan/checkpoint, not a fresh or expanded download.
    onEvent({stage:'continuing',batchNumber:batches+1,counts});
    continue;
   }
   if(result.status!=='budget_paused'||!BOUNDARIES.has(result.code))return final;
   const after=digest(request),c=result.counts||{};
   const progress=(after!==null&&after!==before)||['downloaded','newRecords','updatedRecords','parsed'].some(k=>c[k]>0);
   if(!progress)return {...final,status:'needs_attention',code:'batch_no_progress'};
   onEvent({stage:'continuing',batchNumber:batches+1,counts});
   await new Promise(resolve=>{const timer=setTimeout(()=>{wake=null;resolve();},delayMs);wake=()=>{clearTimeout(timer);wake=null;resolve();};});
  }
  return {status:'stopped',code:'user_stopped',counts,batchCount:batches};
 })();
 return {promise,stop:()=>{stopped=true;current?.stop();wake?.();}};
}
module.exports={runBatches,BOUNDARIES};
