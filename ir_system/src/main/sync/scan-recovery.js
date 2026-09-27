// Only a first-attempt CLI failure before downloads can be superseded by a
// fresh successful scan. Never discard checkpoints or manufacture completion.
const CODES=new Set(['zsxq_cli_failed','zsxq_cli_not_found','zsxq_node_runtime_missing']);
const RECOVERED='scan_recovered_before_download';
function isScanOnlyFailure(job){
  return Boolean(job.kind==='sync'&&['failed','needs_attention'].includes(job.status)&&CODES.has(job.code)&&
    job.stage==='scanning'&&job.attempt===1&&job.plan?.collections?.length>0&&
    job.plan.collections.every(c=>c.provider==='zsxq')&&
    job.counts&&Object.values(job.counts).every(n=>n===0)&&!job.webManifests?.length);
}
function isRecoveredScanFailure(job){return isScanOnlyFailure(job)&&job.recovery?.code===RECOVERED;}
function recoverScanFailures(state,{root,configuration,localCheck,hasCheckpoint,now=Date.now()}){
  const checkAt=Date.parse(localCheck?.checkedAt),catalog=state.catalog?.sources.find(s=>s.provider==='zsxq'),scanAt=Date.parse(catalog?.scannedAt);
  if(localCheck?.configuration!==configuration||localCheck.status!=='ready'||localCheck.zsxqCli?.status!=='ready'||
    !Number.isFinite(checkAt)||checkAt>now||now-checkAt>10*60000||!catalog?.complete||
    !Number.isFinite(scanAt)||scanAt>now||now-scanAt>24*60*60000)return false;
  let changed=false;
  for(const job of state.jobs||[]){
    if(job.root!==root||!isScanOnlyFailure(job)||job.recovery||!(scanAt>Date.parse(job.finishedAt))||hasCheckpoint(job))continue;
    job.recovery={code:RECOVERED,verifiedAt:new Date(now).toISOString(),scannedAt:catalog.scannedAt};
    changed=true;
  }
  return changed;
}
module.exports={isScanOnlyFailure,isRecoveredScanFailure,recoverScanFailures};
