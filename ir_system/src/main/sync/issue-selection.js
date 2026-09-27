// Excluding an issue excludes its collection from execution, not its safeguards.
const {createHash}=require('node:crypto');
const {key}=require('./policy');
const {signature}=require('./subscriptions');
const digest=value=>createHash('sha256').update(JSON.stringify(value)).digest('hex').slice(0,24);
function collectionSignature(state,provider,id){
  const row=state.catalog?.sources.find(s=>s.provider===provider)?.collections.find(c=>c.collectionId===id);
  return signature(row||{present:false});
}
function decorateIssues(state,provider,issues){
  const eligible=new Set(state.settings.policies.filter(p=>p.provider===provider&&['incremental','pending_selection'].includes(p.mode)).map(p=>p.collectionId));
  return issues.map(issue=>{
    const ids=[...new Set(issue.collectionIds|| (issue.collectionId?[issue.collectionId]:[]))].filter(id=>eligible.has(id)).sort();
    return {...issue,issueId:digest([provider,issue.code||issue.kind,ids,issue.jobId||null]),
      considered:true,canExclude:ids.length>0,affectedCollectionIds:ids};
  });
}
function exclusions(state,provider){
  return Object.entries(state.issueExclusions||{}).flatMap(([k,x])=>{
    const p=state.settings.policies.find(p=>key(p)===k);
    if(x.provider!==provider||!p||p.mode!=='off'||x.fingerprint!==collectionSignature(state,provider,p.collectionId))return [];
    return [{...x,key:k,name:p.name,issueId:'restore-'+digest(k),considered:false}];
  });
}
function setConsidered(state,provider,report,issueId,considered){
  state.issueExclusions||={};
  if(considered){
    const x=exclusions(state,provider).find(e=>e.issueId===issueId);
    if(!x)throw new Error('issue_state_changed');
    const p=state.settings.policies.find(p=>key(p)===x.key);
    p.mode=x.priorMode;
    if(state.subscriptionReview?.[x.key]&&x.priorReview)Object.assign(state.subscriptionReview[x.key],x.priorReview);
    delete state.issueExclusions[x.key];
  }else{
    const issue=report.issues.find(i=>i.issueId===issueId);
    if(!issue)throw new Error('issue_state_changed');
    if(!issue.canExclude)throw new Error('required_check_cannot_be_ignored');
    for(const id of issue.affectedCollectionIds){
      const p=state.settings.policies.find(p=>p.provider===provider&&p.collectionId===id);
      state.issueExclusions[key(p)]={provider,collectionId:id,priorMode:p.mode,title:issue.title,detail:issue.detail,
        priorReview:state.subscriptionReview?.[key(p)]?{pending:state.subscriptionReview[key(p)].pending,reason:state.subscriptionReview[key(p)].reason}:null,
        code:issue.code,excludedAt:new Date().toISOString(),fingerprint:collectionSignature(state,provider,id)};
      p.mode='off';
      const review=state.subscriptionReview?.[key(p)];
      if(review){review.pending=false;review.reason=null;}
    }
  }
  state.revision++;
  for(const grant of Object.values(state.grants))if(!grant.used)grant.revoked=true;
}
function clearRestoredExclusions(state){
  for(const k of Object.keys(state.issueExclusions||{}))if(state.settings.policies.find(p=>key(p)===k)?.mode!=='off')delete state.issueExclusions[k];
}
module.exports={decorateIssues,exclusions,setConsidered,clearRestoredExclusions};
