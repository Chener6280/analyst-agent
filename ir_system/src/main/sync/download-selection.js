// A default choice, not a permission grant or an irreversible user preference.
const {downloadStatus}=require('./download-status');
const {signature}=require('./subscriptions');
const {key}=require('./policy');
function applyDownloadDefaults(state,{configuration,now=Date.now()}={}){
  state.downloadSelectionDefaults||={};state.subscriptionReview||={};
  let changed=false;
  for(const policy of state.settings.policies){
    if(!['ima','zsxq'].includes(policy.provider))continue;
    const k=key(policy),row=state.catalog?.sources.find(s=>s.provider===policy.provider)?.collections.find(c=>c.collectionId===policy.collectionId);
    const result=downloadStatus(state,policy.provider,policy.collectionId,{configuration,now});
    const previous=state.downloadSelectionDefaults[k];
    if(result.status==='unavailable'){
      // Scan timestamps are not permission changes. Do not undo an explicit
      // user choice on every poll/restart while the same evidence remains.
      const evidenceKey=JSON.stringify([signature(row),result.label,result.detail]);
      if(previous?.evidenceKey===evidenceKey)continue;
      const review=state.subscriptionReview[k]||={fingerprint:signature(row)};
      state.downloadSelectionDefaults[k]={evidenceKey,appliedAt:new Date(now).toISOString(),priorMode:policy.mode};
      policy.mode='off';review.pending=false;review.reason=null;
      review.autoExcluded={reason:'已确认不可下载，默认不选',detail:result.detail,checkedAt:result.checkedAt};
      changed=true;
    }else if(result.status==='available'&&previous){
      // A restored subscription is reviewed, never silently re-enabled.
      const review=state.subscriptionReview[k]||={fingerprint:signature(row)};
      delete state.downloadSelectionDefaults[k];delete review.autoExcluded;
      policy.mode='pending_selection';review.pending=true;review.reason='changed';
      changed=true;
    }
    // Unknown, partial scans, API refusals and technical errors do not change
    // the user's choice or become evidence of a platform prohibition.
  }
  if(changed){state.revision++;for(const grant of Object.values(state.grants||{}))if(!grant.used)grant.revoked=true;}
  return changed;
}
module.exports={applyDownloadDefaults};
