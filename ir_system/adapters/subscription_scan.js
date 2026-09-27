// Read-only all-group scan. Never opens pages, stores credentials or downloads assets.
const {scanGroups} = require('./zsxq_web/core');
try {
  const scan=scanGroups({intervalMs:500,timeoutMs:30000});
  const complete=scan.summary.scan_errors===0 && scan.summary.skill_probe_errors===0;
  process.stdout.write(JSON.stringify({protocol:'ir-system-sync/v1',type:'result',result:{status:complete?'completed':'needs_attention',code:complete?null:'subscription_scan_incomplete',
    catalog:{scannedAt:scan.scanned_at,complete,sources:[{provider:'zsxq',complete,membershipVerification:'verified',collections:scan.groups.map(g=>({...g,collectionId:g.group_id,present:true}))}]}}})+'\n');
} catch(e) {process.stdout.write(JSON.stringify({protocol:'ir-system-sync/v1',type:'result',result:{status:'needs_attention',code:/^[a-z_]+$/.test(e.code)?e.code:'subscription_scan_failed'}})+'\n');}
