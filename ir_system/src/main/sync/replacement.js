const {key}=require('./policy');
function remaining(job){return (job.plan?.collections||[]).filter(c=>!(job.supersededKeys||[]).includes(key(c)));}
function replacements(state,root,plan){
 const keys=new Set(plan.collections.map(key));
 return state.jobs.filter(j=>j.kind==='sync'&&j.root===root&&!['completed','superseded'].includes(j.status))
  .map(j=>({jobId:j.id,keys:remaining(j).map(key).filter(k=>keys.has(k))})).filter(x=>x.keys.length);
}
function supersede(state,items,newId){
 const at=new Date().toISOString();
 for(const item of items){
  const job=state.jobs.find(j=>j.id===item.jobId);
  if(job.status==='running')throw new Error('previous_job_still_running');
  job.replacements||=[];job.replacements.push({jobId:newId,keys:item.keys,at,previousStatus:job.status});
  job.supersededKeys=[...new Set([...(job.supersededKeys||[]),...item.keys])];
  if(!remaining(job).length){job.priorStatus=job.status;job.status='superseded';job.supersededAt=at;}
  for(const g of Object.values(state.grants))if(g.jobId===job.id&&!g.used)g.revoked=true;
 }
}
module.exports={remaining,replacements,supersede};
