// No debugger inheritance, no permission prompt, no production profile writes.
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),assert=require('node:assert/strict');
const {execFileSync}=require('node:child_process');
(async()=>{
 if(process.platform!=='darwin')return;
 const executable=process.env.IR_SYSTEM_TEST_APP_EXECUTABLE;
 if(!executable||!path.isAbsolute(executable))throw new Error('Set packaged app executable explicitly');
 const app=path.dirname(path.dirname(path.dirname(executable)));
 const profile=fs.mkdtempSync(path.join(os.tmpdir(),'ir-launchservices-permission-'));
 execFileSync('/usr/bin/open',['-n','-g',app,'--env','IR_SYSTEM_USER_DATA_DIR='+profile,'--env','IR_SYSTEM_PERMISSION_DIAGNOSTIC=1']);
 const file=path.join(profile,'permission-diagnostic.json');
 for(let n=0;n<100&&!fs.existsSync(file);n++)await new Promise(r=>setTimeout(r,300));
 const result=JSON.parse(fs.readFileSync(file,'utf8'));
 assert.equal(result.signatureValid,true);
 assert.equal(result.networkCalls,0);assert.equal(result.permissionChanges,0);
 assert.equal(result.helper.status==='completed',result.mainTrusted);
 execFileSync('/usr/bin/codesign',['--verify','--deep','--strict',app],{stdio:'pipe'});
 console.log(JSON.stringify({status:'passed',permissionGranted:result.mainTrusted,helper:result.helper,report:file,signatureValid:true}));
})().catch(e=>{console.error(e.message);process.exitCode=1;});
