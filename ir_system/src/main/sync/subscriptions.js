const fs = require('node:fs');
const path = require('node:path');
const {key} = require('./policy');
const {defaults} = require('../../shared/dates');

// Only permission/availability changes trigger review, never ordinary content counts.
function signature(row) {
  return JSON.stringify({name:row.name || '',present:row.present !== false,
    membership:row.membership?.state || null, expires:row.membership?.end_time || null,
    skill:row.skill_api || null,permissions:row.permissions || null,
    directoryAccess:row.directoryAccess || null,accessCode:row.accessCode || null});
}
function applyCatalog(state, catalog) {
  state.subscriptionReview ||= {};
  const prior = state.catalog?.sources || [];
  const incoming = [];
  let changed = false;
  for (const source of catalog.sources || []) {
    const before = prior.find(p=>p.provider===source.provider);
    const rows = source.collections.map(c=>({...(source.inventoryOnly?before?.collections.find(r=>r.collectionId===c.collectionId):{}),...c,present:true}));
    // A partial scan cannot establish disappearance or reset an old permission.
    if (!source.complete) { incoming.push({...before,...source,collections:before?.collections || rows,scannedAt:before?.scannedAt || null,lastAttemptAt:catalog.scannedAt}); continue; }
    for (const old of before?.collections || []) if (!rows.some(c=>c.collectionId===old.collectionId)) rows.push({...old,present:false});
    for (const c of rows) {
      const k = key({...c,provider:source.provider});
      const fingerprint = signature(c), previous = state.subscriptionReview[k];
      let policy = state.settings.policies.find(p=>key(p)===k);
      if (!policy) {
        policy = {provider:source.provider,collectionId:c.collectionId,name:c.name,mode:'pending_selection',firstDate:''};
        state.settings.policies.push(policy);
      }
      if (!previous || previous.fingerprint !== fingerprint) {
        const oldRow=before?.collections.find(r=>r.collectionId===c.collectionId);
        // Wisburg has fixed public categories, not user-managed subscriptions.
        const firstKnownPolicy = !previous && policy.mode !== 'pending_selection' &&
          (source.provider === 'wisburg' || (oldRow && signature(oldRow)===fingerprint));
        state.subscriptionReview[k] = { ...previous, fingerprint, pending:!firstKnownPolicy,
          reason: !previous ? 'new' : c.present === false ? 'missing' : 'changed',
          observedAt:catalog.scannedAt, priorMode:policy.mode };
        if (!firstKnownPolicy) policy.mode = 'pending_selection';
        policy.name = c.name;
        changed = true;
      }
    }
    incoming.push({...source,collections:rows,scannedAt:source.scannedAt||catalog.scannedAt});
  }
  const merged = [...prior.filter(s=>!incoming.some(r=>r.provider===s.provider)),...incoming];
  state.catalog = {...catalog,sources:merged,complete:merged.every(s=>s.complete)};
  if (changed) { state.revision++; for (const g of Object.values(state.grants)) if (!g.used) g.revoked=true; }
}
function applySeed(state, directory) {
  const file=path.join(directory,'subscription-preferences.json');
  if (!fs.existsSync(file)) return;
  const seed=JSON.parse(fs.readFileSync(file,'utf8'));
  if (state.preferenceMigration === seed.id) return;
  if (seed.schemaVersion!==1 || !Array.isArray(seed.rows) || seed.rows.length>500) throw new Error('invalid_preference_seed');
  state.subscriptionReview ||= {};
  const firstDate=defaults('backfill').start;
  for (const r of seed.rows) {
    if (!['zsxq','ima'].includes(r.provider) || !/^[A-Za-z0-9_+=.-]{1,512}$/.test(r.collectionId)) throw new Error('invalid_preference_seed');
    const k=key(r), old=state.settings.policies.find(p=>key(p)===k);
    const policy={provider:r.provider,collectionId:r.collectionId,name:r.name,mode:r.mark==='优先下载'?'incremental':'off',firstDate};
    if (old) Object.assign(old,policy); else state.settings.policies.push(policy);
    let source=state.catalog?.sources.find(s=>s.provider===r.provider);
    if (!state.catalog) state.catalog={sources:[],complete:false};
    if (!source) {source={provider:r.provider,complete:false,collections:[],scannedAt:seed.observedAt};state.catalog.sources.push(source);}
    const c={...(source.collections.find(c=>c.collectionId===r.collectionId)||{}),...r.observation,collectionId:r.collectionId,name:r.name,present:true};
    source.collections=source.collections.filter(c=>c.collectionId!==r.collectionId).concat(c);
    state.subscriptionReview[k]={fingerprint:signature(c),pending:false,reason:null,observedAt:seed.observedAt,originalMark:r.mark,capability:r.capability || null};
  }
  state.preferenceMigration=seed.id; state.revision++;
  for(const g of Object.values(state.grants)) if(!g.used)g.revoked=true;
}
function acknowledge(state, policies) {
  for(const p of policies) {
    const review=state.subscriptionReview?.[key(p)];
    if(review && p.mode!=='pending_selection') {review.pending=false;review.reason=null;}
  }
}
module.exports={signature,applyCatalog,applySeed,acknowledge};
