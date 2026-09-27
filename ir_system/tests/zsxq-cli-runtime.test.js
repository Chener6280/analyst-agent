const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os');
const {spawnSync}=require('node:child_process');
const {cliInvocation,runZsxqCli,probeSkillApi}=require('../adapters/zsxq_web/core');
const {workerEnvironment}=require('../src/main/sync/runner');
function fixture(t,body){
 const root=fs.mkdtempSync(path.join(os.tmpdir(),"ir-cli-fixture-' "));
 t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
 const entry=path.join(root,'launcher.js'),link=path.join(root,'zsxq-cli');
 fs.writeFileSync(entry,'#!/usr/bin/env node\n'+body,{mode:0o700});fs.symlinkSync(entry,link);return link;
}
test('npm launcher uses the current runtime with a Finder-only PATH and preserves argv',t=>{
 const cli=fixture(t,'process.stdout.write(JSON.stringify(process.argv.slice(2)))');
 const before=process.env.PATH;process.env.PATH='/usr/bin:/bin:/usr/sbin:/sbin';t.after(()=>{process.env.PATH=before;});
 const args=['auth','status','a b',"x'y"];
 assert.deepEqual(JSON.parse(runZsxqCli(cli,args)),args);
 const launch=cliInvocation(cli,args);assert.equal(launch.command,process.execPath);assert.equal(launch.env.ELECTRON_RUN_AS_NODE,'1');
});
test('native CLI binaries run directly, not through Node',()=>{
 assert.equal(cliInvocation('/usr/bin/true',['--version']).command,'/usr/bin/true');
});
test('Skill probes share the fixed launcher and never need shell initialization',t=>{
 const cli=fixture(t,'process.stdout.write(JSON.stringify({succeeded:true}))');
 assert.equal(probeSkillApi(cli,'123').state,'accessible');
});
test('runtime error codes stay actionable without leaking raw stderr',t=>{
 const cli=fixture(t,'process.stderr.write("env: node: No such file or directory\\nsecret=private");process.exit(127);');
 assert.throws(()=>runZsxqCli(cli,[]),e=>e.code==='zsxq_node_runtime_missing'&&!JSON.stringify(e).includes('private'));
 assert.throws(()=>runZsxqCli('/missing/zsxq-cli',[]),e=>e.code==='zsxq_cli_not_found');
});
test('Python SDK gets the same safe argv override, including spaces and apostrophes',t=>{
 const cli=fixture(t,'process.stdout.write("fixture ready")'),prior=process.env.ZSXQ_CLI_COMMAND;
 process.env.ZSXQ_CLI_COMMAND=cli;t.after(()=>{if(prior===undefined)delete process.env.ZSXQ_CLI_COMMAND;else process.env.ZSXQ_CLI_COMMAND=prior;});
 const env=workerEnvironment({}, {appRoot:path.resolve(__dirname,'..')}, 'python','check');
 const result=spawnSync('/usr/bin/python3',['-c','import os,shlex,subprocess; subprocess.run(shlex.split(os.environ["ZSXQ_CLI_COMMAND"]),check=True)'],{env:{...env,PATH:'/usr/bin:/bin:/usr/sbin:/sbin'},encoding:'utf8'});
 assert.equal(result.status,0,result.stderr);assert.equal(result.stdout,'fixture ready');
 assert.equal(process.env.ZSXQ_CLI_COMMAND,cli);assert.equal(env.PYTHONDONTWRITEBYTECODE,'1');
});
