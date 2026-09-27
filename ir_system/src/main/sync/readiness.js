const sources=require('../../shared/sources');
const {key,SOURCES}=require('./policy');
const {decorateIssues,exclusions}=require('./issue-selection');
const {isRecoveredScanFailure,isScanOnlyFailure}=require('./scan-recovery');
const SCAN_MAX_AGE=24*60*60*1000, LOCAL_MAX_AGE=10*60*1000;
const fresh=(at,age,now)=>{const time=Date.parse(at);return Number.isFinite(time)&&time<=now+60000&&now-time<=age;};
// Shared by every source. Unknown/new sources cannot inherit a green default.
function readiness(state,provider,{root='',localCheck=null,busy=false,now=Date.now(),configuration}={}){
  const source=sources.find(s=>s.id===provider),connected=Boolean(source?.ready&&SOURCES.includes(provider)),catalog=state.catalog?.sources.find(s=>s.provider===provider);
  const policies=state.settings.policies.filter(p=>p.provider===provider),selected=policies.filter(p=>p.mode==='incremental');
  const webGroups=provider==='zsxq'?selected.map(p=>catalog?.collections.find(c=>c.collectionId===p.collectionId)).filter(c=>c?.skill_api==='not_enabled'&&c.membership?.active===true&&c.permissions?.allow_download===true):[];
  const issues=[];
  const add=(code,title,detail,action,level='attention',extra={})=>issues.push({code,title,detail,action,level,...extra});
  if(!connected)add('route_not_connected','下载按钮尚未接入','该信源尚未接入桌面历史／增量下载流程。','需维护者接入并验收；配置密钥或让 Agent 执行一次，不会自动接通按钮。','unknown');
  // Per-library availability belongs to the subscription dropdown. Green here
  // means runtime readiness, not permission to download every selected library.
  if(connected){
    if(!catalog?.complete)add('scan_incomplete','订阅扫描尚未完成','缺少一次完整的订阅／栏目扫描。','点击“重新扫描订阅”并确认联网；失败或部分扫描不能变绿。','unknown');
    else if(!fresh(catalog.scannedAt,SCAN_MAX_AGE,now))add('scan_stale','扫描记录需要更新','扫描时间未知或已超过 24 小时。','重新扫描订阅；不把旧快照当作当前权限。','unknown');
  }
  const scan=(state.jobs||[]).filter(j=>j.kind==='scan'&&j.providers?.includes(provider)).at(-1);
  const newerCatalog=catalog?.complete&&Date.parse(catalog.scannedAt)>Date.parse(scan?.finishedAt||scan?.createdAt);
  if(scan&&['running','queued','agent_starting'].includes(scan.status))add('scan_in_progress','正在扫描订阅','扫描尚在进行，这不是扫描失败。','等待本轮完成，界面会自动刷新；不必重复点击。','unknown');
  else if(scan&&scan.status!=='completed'&&!newerCatalog)add('latest_scan_unsuccessful','最近扫描未成功',`状态：${scan.status}；${scan.code||'尚未完成'}。`,'处理扫描错误后重新扫描；保留旧目录不能代表本次检查通过。','attention');
  const selectedKeys=new Set(selected.map(key));
  const taskWarnings=(state.jobs||[]).filter(job=>job.kind==='sync'&&job.root===root&&!['completed','superseded','authorized','running'].includes(job.status)&&!isRecoveredScanFailure(job)&&job.plan?.collections.some(c=>selectedKeys.has(key(c))&&!(job.supersededKeys||[]).includes(key(c))))
    .map(job=>({jobId:job.id,status:job.status,code:job.code,issues:job.issues||[],repairAvailable:Boolean(job.membershipRepair),
      detail:'下载任务尚有未完成项；确认新的更新任务后将替代重叠旧范围，保留已下载文件。不代表本地环境失效。'}));
  if(busy)add('system_busy','已有任务运行','当前同步、检查或归档写入尚未结束。','等待当前任务完成，或通过原任务停止入口处理。','unknown');
  if(!localCheck||!fresh(localCheck.checkedAt,LOCAL_MAX_AGE,now))add('local_check_required','本地环境待核验','尚无最近 10 分钟内的本地检查结果。','点击下载状态按钮或“检查本地环境”；不下载、不调用模型。','unknown');
  else if(localCheck.status!=='ready'){
    for(const issue of localCheck.issues||[])if(!issue.collectionIds?.length||issue.collectionIds.some(id=>selected.some(p=>p.collectionId===id)))issues.push(issue);
    if(!localCheck.issues?.length)add('local_check_failed','本地检查未通过',localCheck.code||'无法确认当前工具链状态。','检查 Python、ir_search 路径和归档目录后重新核验。');
  }
  if(provider==='zsxq'&&localCheck?.zsxqCli?.status!=='ready'){
    const code=localCheck?.zsxqCli?.code||'zsxq_cli_check_required';
    const auth=code==='zsxq_auth_required';
    add(code,auth?'知识星球接口需要登录':'知识星球运行工具待检查',code,
      auth?'完成知识星球 CLI 授权登录，再检查本地环境；网页扫码是另一条通道，不代替接口登录。':code==='zsxq_node_runtime_missing'?'桌面端未找到运行程序，请更新修复版应用后检查本地环境。':code==='zsxq_cli_not_found'?'未找到知识星球 CLI，请安装或配置工具路径后检查。':'点击“检查本地环境”；若仍失败，请保留错误码交给维护者。',localCheck?.zsxqCli?.status==='needs_attention'?'attention':'unknown');
  }
  if(provider==='ima'&&selected.length&&localCheck?.ima?.status==='needs_attention'){
    const code=localCheck.ima.code||'ima_client_unavailable';
    add(code,code==='ima_accessibility_required'?'客户端辅助功能需要授权':'客户端工具需要处理',
      code==='ima_accessibility_required'?'官方客户端备用通道尚未获得本机辅助功能授权；这不是知识库下载权限被拒绝。':code,
      '授权必须对应当前版本。若开关已打开仍提示未授权，请先退出旧 IR System，在辅助功能列表移除旧条目，再用下方“定位当前应用”找到的应用重新添加并启用，随后重新核验。程序不会自行更改系统权限。');
  }
  if(webGroups.length){
    const webScope={collectionIds:webGroups.map(c=>c.collectionId)};
    if(!localCheck?.web)add('web_environment_unverified','网页运行环境待核验','已接入固定网页下载程序，但本机浏览器尚未检查。','点击检查本地环境。','unknown',webScope);
    else if(localCheck.web.status!=='ready'){
      issues.push(...(localCheck.web.issues||[]).map(i=>({...i,...webScope})));
      if(!localCheck.web.issues?.length)add('web_environment_unverified','网页运行环境待核验','尚无可靠的浏览器环境结果。','检查浏览器、专用登录配置及网页归档锁。','unknown',webScope);
    }
    if(localCheck?.web?.status==='ready'&&!localCheck.web.loginVerified)add('web_login_unverified','网页登录待核验','固定网页通道不调用大模型；登录状态需在专用浏览器确认。','预分析会核验账号登录，需要扫码时直接弹出二维码，等待你本人完成；不使用单个星球的续期状态判断整个账号。','unknown',webScope);
  }
  const tone=issues.some(i=>i.level==='attention')?'attention':issues.length?'unknown':'ready';
  return {provider,tone,label:tone==='ready'?'环境就绪':tone==='attention'?'需处理':!connected?'待接入':'待核验',issues:decorateIssues(state,provider,issues),excluded:exclusions(state,provider),taskWarnings,
    checkedAt:localCheck?.checkedAt||null,scannedAt:catalog?.scannedAt||null,selected:selected.length,
    canScan:connected,canSelect:Boolean(source?.children),canConfigure:connected,
    loginGroupId:catalog?.complete&&fresh(catalog.scannedAt,SCAN_MAX_AGE,now)?webGroups[0]?.collectionId||null:null,
    scope:'text_non_audio',coverageComplete:false};
}
module.exports={readiness,SCAN_MAX_AGE,LOCAL_MAX_AGE};
