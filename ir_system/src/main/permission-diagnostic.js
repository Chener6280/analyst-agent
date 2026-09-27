const fs=require('node:fs'),path=require('node:path');
const {execFile}=require('node:child_process');
const {systemPreferences}=require('electron');
const {runWorker}=require('./sync/runner');
async function runPermissionDiagnostic(directory,runtime){
 const appPath=path.dirname(path.dirname(runtime.resourcesPath));
 const signatureValid=await new Promise(resolve=>execFile('/usr/bin/codesign',['--verify','--deep','--strict',appPath],{timeout:15000},err=>resolve(!err)));
 const mainTrusted=systemPreferences.isTrustedAccessibilityClient(false);
 const helper=await runWorker({command:'ima-permission'},{},runtime,()=>{}).promise;
 fs.mkdirSync(directory,{recursive:true,mode:0o700});
 fs.writeFileSync(path.join(directory,'permission-diagnostic.json'),JSON.stringify({schemaVersion:1,checkedAt:new Date().toISOString(),appPath,signatureValid,mainTrusted,helper,networkCalls:0,downloads:0,permissionChanges:0},null,2),{mode:0o600});
}
module.exports={runPermissionDiagnostic};
