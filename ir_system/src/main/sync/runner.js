const path = require("node:path");
const { spawn } = require("node:child_process");

function workerEnvironment(provider, runtime, mode, command) {
  const env = { ...process.env, PYTHONUNBUFFERED: '1', PYTHONDONTWRITEBYTECODE: '1' };
  env.IR_SYSTEM_NODE_EXECUTABLE=process.execPath;env.NODE_PATH=path.join(runtime.appRoot,'node_modules');
  if(command==='check')env.PYTHONDONTWRITEBYTECODE='1';
  if(mode!=='python')env.ELECTRON_RUN_AS_NODE='1';
  if(provider.irSearchPath)env.IR_SEARCH_PATH=provider.irSearchPath;
  if(mode==='python'){
    const {cliInvocation,resolveCli}=require(path.join(runtime.packaged?runtime.resourcesPath:runtime.appRoot,'adapters/zsxq_web/core'));
    const cli=cliInvocation(resolveCli(),[]);
    if(cli.command===process.execPath){
      // ir_search's documented override is an argv command parsed with shlex.
      // This is per-child configuration, never a global PATH or SDK source edit.
      env.ZSXQ_CLI_COMMAND=[cli.command,...cli.args].map(s=>"'"+s.replace(/'/g,"'\"'\"'")+"'").join(' ');
      env.ELECTRON_RUN_AS_NODE='1';
    }
  }
  return env;
}

function runProcess(request, provider, runtime, onEvent, mode = 'python') {
  const node=mode!=='python';
  const script = path.join(runtime.packaged ? runtime.resourcesPath : runtime.appRoot, "adapters", mode==='scan'?'subscription_scan.js':mode==='web'?'zsxq_web/desktop.js':"sync_worker.py");
  const env = workerEnvironment(provider,runtime,mode,request.command);
  if(request.imaClientEnabled)env.IR_SYSTEM_IMA_CLIENT_ENABLED='1';
  env.IR_SYSTEM_WEB_BROWSER_MODE=request.browserMode==='visible'?'visible':'headless';
  const child = spawn(node ? process.execPath : provider.pythonCommand || "python3", [script], { env, stdio: ["pipe", "pipe", "pipe"], detached: process.platform !== "win32" });
  let pending = "", last = null, bytes = 0, finished = false, killTimer, failure=null;
  let resolve;
  const promise = new Promise(r => { resolve = r; });
  function finish(value) { if (!finished) { finished = true; clearTimeout(timer); clearTimeout(killTimer); resolve(value); } }
  function signal(name) {
    try { if (process.platform === "win32") child.kill(name); else process.kill(-child.pid, name); } catch {}
  }
  // Let the parent finish its bounded parser/download operation; do not kill a
  // parser child and cache a spurious worker_failed result on a normal stop.
  function stop() { try { child.kill("SIGTERM"); } catch {} killTimer ||= setTimeout(() => signal("SIGKILL"), request.command==='check'?5000:70000); killTimer.unref?.(); }
  const timer = setTimeout(stop, request.command==='check'?15000:((request.plan?.budgets.maxSeconds || 300) + 75) * 1000);
  child.stdout.on("data", chunk => {
    bytes += chunk.length; pending += chunk.toString("utf8");
    if (bytes > 16 * 1024 * 1024 || pending.length > 4 * 1024 * 1024) { failure={ status: "failed", code: "worker_output_limit" }; signal("SIGKILL"); return; }
    let end;
    while ((end = pending.indexOf("\n")) !== -1) {
      const line = pending.slice(0, end); pending = pending.slice(end + 1);
      try {
        const event = JSON.parse(line);
        if (event.protocol !== "ir-system-sync/v1") throw new Error();
        if (event.type === "result") last = event.result;
        else if (event.type === "progress") onEvent(event.progress);
      } catch { failure={ status: "failed", code: "invalid_worker_response" }; signal("SIGKILL"); return; }
    }
  });
  // Never forward raw stderr to a model or UI; upstream messages may contain secrets.
  child.stderr.on("data", () => {});
  child.on("error", () => {failure={ status: "failed", code: "worker_unavailable" };});
  child.on("close", () => finish(failure || last || { status: "interrupted", code: "worker_interrupted" }));
  child.stdin.on("error", () => {});
  child.stdin.end(JSON.stringify(request) + "\n");
  return { promise, stop };
}
function runWorker(request,provider,runtime,onEvent) {
  if(request.command==='ima-permission'){
    // Same responsible app/process chain as the downloader. Check only; do not
    // re-prompt or operate IMA while the user is changing System Settings.
    const binary=path.join(runtime.packaged?runtime.resourcesPath:runtime.appRoot,'adapters/ima_client/ima-accessibility');
    const child=spawn(binary,[],{stdio:['pipe','pipe','ignore']});let raw='',resolve,finished=false;
    const promise=new Promise(r=>resolve=r);
    const finish=result=>{if(finished)return;finished=true;clearTimeout(timer);resolve(result);};
    const timer=setTimeout(()=>{child.kill();finish({status:'needs_attention',code:'ima_client_timeout'});},5000);
    child.stdout.on('data',b=>{raw+=b;if(raw.length>65536){child.kill();finish({status:'needs_attention',code:'ima_client_output_limit'});}});
    child.on('error',()=>finish({status:'needs_attention',code:'ima_client_unavailable'}));
    child.on('close',()=>{try{const r=JSON.parse(raw);finish({status:r.status==='ready'||r.status==='ok'||r.code==='ima_client_not_running'?'completed':'needs_attention',code:r.code});}catch{finish({status:'needs_attention',code:'ima_client_invalid_response'});}});
    child.stdin.on('error',()=>{});child.stdin.end(JSON.stringify({command:'check'})+'\n');
    return {promise,stop:()=>{child.kill();finish({status:'stopped',code:'user_stopped'});}};
  }
  if(request.command==='web-login')return runProcess({command:'login',groupId:request.groupId,browserMode:request.browserMode},provider,runtime,onEvent,'web');
  if(request.command==='check'){
    let running=runProcess(request,provider,runtime,onEvent),stopped=false;
    const promise=(async()=>{const result=await running.promise;if(stopped)return result;
      running=runProcess(request,provider,runtime,onEvent,'web');const web=await running.promise;
      if(result.localCheck){
        result.localCheck.web=web.web||{status:'unknown',issues:[]};result.localCheck.zsxqCli=web.zsxqCli||{status:'unknown',code:'zsxq_cli_check_unavailable'};
        const base=runtime.packaged?runtime.resourcesPath:runtime.appRoot;
        if(!stopped&&process.platform==='darwin'&&base&&require('node:fs').existsSync(path.join(base,'adapters/ima_client/ima-accessibility'))){
          running=runWorker({command:'ima-permission'},provider,runtime,()=>{});
          const permission=await running.promise;
          result.localCheck.ima={status:permission.status==='completed'?'ready':'needs_attention',code:permission.code};
        }
      }return result;
    })();return {promise,stop:()=>{stopped=true;running.stop();}};
  }
  let running,stopped=false;const started=Date.now();
  const promise=(async()=>{
    const providers=request.providers || [...new Set(request.plan.collections.filter(c=>!(request.excludedCollections||[]).includes(c.provider+':'+c.collectionId)).map(c=>c.provider))];
    if(providers.includes('zsxq')) {
      onEvent({stage:'scanning',counts:{}});
      running=runProcess(request,provider,runtime,onEvent,'scan');
      const result=await running.promise;
      if(stopped || result.status!=='completed') return stopped?{status:'stopped',catalog:result.catalog}:result;
      request={...request,zsxqCatalog:result.catalog};
      if(request.command==='scan' && providers.length===1) return result;
      if(request.plan){
        const remaining=request.plan.budgets.maxSeconds-Math.ceil((Date.now()-started)/1000);
        if(remaining<30)return {status:'budget_paused',code:'time_budget_exhausted',catalog:result.catalog};
        request={...request,plan:{...request.plan,budgets:{...request.plan.budgets,maxSeconds:remaining}}};
      }
    }
    if(stopped) return {status:'stopped'};
    running=runProcess(request,provider,runtime,onEvent);
    return running.promise;
  })();
  return {promise,stop:()=>{stopped=true;running?.stop();}};
}
module.exports = { runWorker, workerEnvironment };
