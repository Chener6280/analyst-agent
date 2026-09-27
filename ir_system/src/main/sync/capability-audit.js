// Maintainer-only, local, idempotent evidence handoff. Not a renderer upload or
// a permission grant. Files contain no cookies, URLs, source text or credentials.
const fs=require('node:fs'),path=require('node:path');
const {applyCatalog,signature}=require('./subscriptions');
function applyAudit(state,directory,configuration){
 const file=path.join(directory,'capability-audit.json');
 if(!fs.existsSync(file))return false;
 if(fs.statSync(file).size>1024*1024)throw new Error('capability_audit_invalid');
 const a=JSON.parse(fs.readFileSync(file,'utf8'));
 if(a.id===state.capabilityAuditId)return false;
 if(a.schemaVersion!==1||typeof a.id!=='string'||a.id.length>100||a.configuration!==configuration||!Array.isArray(a.observations)||a.observations.length>500||!Array.isArray(a.catalog?.sources))throw new Error('capability_audit_invalid');
 const validStamp=t=>Number.isFinite(Date.parse(t))&&Date.parse(t)<=Date.now()+60000;
 if(!validStamp(a.catalog.scannedAt)||new Set(a.catalog.sources.map(s=>s.provider)).size!==a.catalog.sources.length)throw new Error('capability_audit_invalid');
 for(const s of a.catalog.sources){
  if(!['ima','zsxq'].includes(s.provider)||s.complete!==true||!Array.isArray(s.collections)||s.collections.length>500)throw new Error('capability_audit_invalid');
  if(s.scannedAt!==undefined&&!validStamp(s.scannedAt)||new Set(s.collections.map(r=>r.collectionId)).size!==s.collections.length)throw new Error('capability_audit_invalid');
  for(const r of s.collections)if(!/^[A-Za-z0-9_+=.-]{1,512}$/.test(r.collectionId)||typeof r.name!=='string'||r.name.length>500)throw new Error('capability_audit_invalid');
 }
 for(const e of a.observations){
  if(e.provider!=='ima'||!['client_downloaded','client_blocked','client_unverified','library_deleted'].includes(e.status)||!a.catalog.sources.some(s=>s.provider==='ima'&&s.collections.some(r=>r.collectionId===e.collectionId))||!Number.isFinite(Date.parse(e.checkedAt))||Date.parse(e.checkedAt)>Date.now()+60000||typeof e.sampleTitle!=='string'||e.sampleTitle.length>500||e.reason!==undefined&&(typeof e.reason!=='string'||e.reason.length>600))throw new Error('capability_audit_invalid');
  if(e.status==='client_downloaded'&&(!Number.isSafeInteger(e.bytes)||e.bytes<=0||!/^[a-f0-9]{64}$/.test(e.sha256)))throw new Error('capability_audit_invalid');
  if(typeof e.fingerprint!=='string'||e.fingerprint.length>4096)throw new Error('capability_audit_invalid');
 }
 // Never replace a newer live subscription snapshot with an older audit.
 const sources=a.catalog.sources.filter(s=>!state.catalog?.sources.some(old=>old.provider===s.provider&&Date.parse(old.scannedAt)>Date.parse(s.scannedAt||a.catalog.scannedAt)));
 if(sources.length)applyCatalog(state,{...a.catalog,sources});
 state.downloadEvidence||={};
 for(const e of a.observations){
  const row=state.catalog?.sources.find(s=>s.provider==='ima')?.collections.find(c=>c.collectionId===e.collectionId);
  const audited=a.catalog.sources.find(s=>s.provider==='ima')?.collections.find(c=>c.collectionId===e.collectionId);
  if(!row||row.present===false||row.name!==audited?.name||e.fingerprint!==signature(row))continue;
  const k='ima:'+e.collectionId,old=state.downloadEvidence[k];
  if(old&&Date.parse(old.checkedAt)>Date.parse(e.checkedAt))continue;
  state.downloadEvidence[k]={status:e.status,checkedAt:e.checkedAt,sampleTitle:e.sampleTitle,reason:e.reason||null,bytes:e.bytes||0,sha256:e.sha256||null,
   fingerprint:signature(row),configuration};
 }
 state.capabilityAuditId=a.id;state.revision++;
 for(const g of Object.values(state.grants))if(!g.used)g.revoked=true;
 return true;
}
module.exports={applyAudit};
