const fs=require('node:fs'),path=require('node:path');
// One-time, evidence-backed recovery for the former whole-page reminder bug.
// Keep the original failure and checkpoint; the next authorized run re-scans.
function identifyRepair(job){
  if(job.kind!=='sync'||job.status!=='needs_attention'||job.code!=='membership_expired'||job.attempt!==1||job.stage!=='web_downloading'||job.webManifests?.length!==1)return null;
  if(!job.counts||Object.entries(job.counts).some(([k,v])=>k!=='operations'&&v!==0))return null;
  const relative=job.webManifests[0];
  if(!/^zsxq_web\/jobs\/desktop-[a-f0-9]+\/manifest\.json$/.test(relative))return null;
  try{
    const root=fs.realpathSync(job.root),file=fs.realpathSync(path.join(root,relative));
    if(!file.startsWith(root+path.sep))return null;
    const m=JSON.parse(fs.readFileSync(file,'utf8'));
    if(m.stage!=='discover_topics'||m.error?.code!=='membership_expired'||m.error?.diagnostic?.message!=='The group membership is expired in the browser session'||m.topics_processed_total!==0||m.record_refs?.length||m.job?.membership?.active!==true)return null;
    if(!job.plan.collections.some(c=>c.provider==='zsxq'&&c.collectionId===m.job.group_id))return null;
    return {code:'membership_classifier_updated',collectionId:m.job.group_id,name:m.job.group_name,originalCode:job.code};
  }catch{return null;}
}
function canResume(job){return ['budget_paused','stopped','interrupted'].includes(job.status)||Boolean(job.status==='needs_attention'&&(job.code==='ima_daily_quota_exhausted'||/^ima_(client_|accessibility_)/.test(job.code||'')||job.diagnostic?.providerCode===220021||job.attempt===1&&job.membershipRepair));}
function blockingCollections(job){
  // Only a finished, explicitly scoped partial result releases healthy siblings.
  if(job.status==='partial'&&job.stage==='finished'&&job.issues?.length&&job.issues.every(i=>i.provider&&i.collectionId)){
    return job.plan.collections.filter(c=>job.issues.some(i=>i.provider===c.provider&&i.collectionId===c.collectionId));
  }
  return job.plan?.collections||[];
}
module.exports={identifyRepair,canResume,blockingCollections};
