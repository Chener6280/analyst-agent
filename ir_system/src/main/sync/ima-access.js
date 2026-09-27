const {signature}=require('./subscriptions');
const MAX_AGE=24*60*60*1000;
const statuses={
  api_sample_ok:['程序样本通过','本次一个非音频原件读取成功；正式更新仍逐文件检查，不代表整库权限或历史齐全。'],
  sample_denied:['原件样本被拒绝','本次样本被接口拒绝。请在官方客户端确认该文件能否下载；不能推断整个库不可下载，也未证明客户端通道可用。'],
  directory_denied:['目录访问被拒绝','本次目录访问未通过，请核验账号或分享权限。'],
  not_visible:['当前订阅未发现','完整扫描未发现这个 ID。请在客户端核对，不自动替换成同名或其他库。'],
  review_required:['订阅变化待确认','新扫描发现状态变化，请先在订阅列表确认问号，再复检。'],
  unverified:['原件权限待核验','尚未取得有效的原件样本证据；未找到样本、超限或技术错误不等于无权限。'],
};
const explanations={
  sample_not_found_in_budget:['尚未找到合适样本','本轮最多检查 3 页目录，未找到符合条件的非音频文件；已保存位置，下次继续找样本。原件权限尚未测试，不等于无法下载。'],
  sample_search_exhausted:['当前目录未找到样本','已走完本次发现的目录，未找到可测试的非音频文件；没有测试原件权限，不等于整库不可下载。可在客户端核验文件类型，或明确从头重新找样本。'],
  pagination_cycle:['目录翻页出现循环','已停止，不自动重试。请查看诊断；确认后可单独从头重新找样本。'],
  pagination_stalled:['目录翻页停滞','已停止，不自动重试。请查看诊断；确认后可单独从头重新找样本。'],
  invalid_cursor:['目录位置失效','平台不再接受保存的翻页位置。可单独从头重新找样本，不会清除其他库结果。'],
  ima_probe_checkpoint_invalid:['查找断点不可用','断点校验失败，未继续查找。请明确从头重新找样本；不会自动改写或猜测断点。'],
  probe_checkpoint_budget_exhausted:['目录断点达到保护上限','已停止并保留位置，需要维护者检查目录结构；不无限增长或自动丢弃进度。'],
  ima_upstream_rejected:['上游错误待诊断','IMA 返回未分类业务错误，本轮按保护规则停止。现有证据不足以判断是限流、权限还是其他原因。'],
  ima_daily_quota_exhausted:['API 当日额度用尽','IMA 官方返回：资料获取次数已达上限，请明天再尝试。不是该库无权限或日期错误。支持辅助功能的 macOS 版更新任务可转官方客户端下载；仍逐文件核验正常导出权限。'],
  not_tested:['本轮未检查','本轮尚未检查到这个库；前项异常、停止或预算耗尽可能使后项未执行。不算本库下载失败。'],
  probe_in_progress:['等待本轮核验','复检正在进行，尚无本轮结果。'],
  evidence_stale_or_changed:['证据需要更新','订阅／本机连接配置变化，或原证据时间无效。请重新复检，不沿用旧成功。'],
  asset_exceeds_max_bytes:['样本超过核验预算','该样本超过本次读取大小上限，未证明有或没有下载权限。'],
};
function access(state,id,{now=Date.now(),configuration}={}){
  const source=state.catalog?.sources.find(s=>s.provider==='ima'),row=source?.collections.find(c=>c.collectionId===id);
  const saved=state.imaAccess?.[id],at=Date.parse(saved?.status==='api_sample_ok'?saved.checkedAt:saved?.observedAt||saved?.checkedAt);
  const valid=saved&&Number.isFinite(at)&&at<=now+60000&&saved.fingerprint===signature(row||{present:false})&&
    (configuration===undefined||saved.configuration===configuration);
  const status=valid&&statuses[saved.status]?saved.status:'unverified';
  const code=valid?(saved.diagnostic?.providerCode===220021?'ima_daily_quota_exhausted':saved.code):saved?'evidence_stale_or_changed':'probe_required';
  const [label,detail]=status==='unverified'&&explanations[code]?explanations[code]:statuses[status];
  return {collectionId:id,status,label,detail,code,
    checkedAt:['not_tested','probe_in_progress'].includes(saved?.code)?null:saved?.checkedAt||null,sampleRef:valid?saved.sampleRef||null:null,bytes:valid?saved.bytes||0:0,
    sampleTitle:valid?saved.sampleTitle||null:null,sampleFolderId:valid?saved.sampleFolderId||null:null,
    diagnostic:valid?saved.diagnostic||null:null,pagesChecked:valid?saved.pagesChecked||0:0,
    search:searchSummary(state,id,configuration),
    historicalDenied:state.subscriptionReview?.['ima:'+id]?.capability?.api==='原文样本拒绝'};
}
function searchCheckpoint(state,id,configuration){
  const row=state.catalog?.sources.find(s=>s.provider==='ima')?.collections.find(c=>c.collectionId===id),saved=state.imaProbeSearch?.[id];
  // Positions are account/configuration and subscription-bound, but not date-bound.
  return saved&&saved.configuration===configuration&&saved.fingerprint===signature(row||{present:false})?saved.checkpoint:null;
}
function searchSummary(state,id,configuration){
  const c=searchCheckpoint(state,id,configuration);
  return c?{pagesTotal:c.pagesTotal||0,pendingPages:c.queue?.length||0,hasSample:!!c.sample,
    exhausted:!c.sample&&!c.queue?.length}:null;
}
function saveSearch(state,job,checkpoints){
  state.imaProbeSearch||={};
  for(const id of job.probeSelection){
    const c=checkpoints?.[id];if(!c)continue;
    const row=state.catalog?.sources.find(s=>s.provider==='ima')?.collections.find(c=>c.collectionId===id);
    const fingerprint=job.probeFingerprints?.[id];
    if(fingerprint!==signature(row||{present:false}))continue;
    state.imaProbeSearch[id]={checkpoint:structuredClone(c),fingerprint,configuration:job.probeConfiguration};
  }
}
function safeDiagnostic(d){
  if(!d||typeof d!=='object')return null;
  const result={};
  for(const key of ['phase','code','operation'])if(typeof d[key]==='string'&&/^[a-z][a-z0-9_]{0,90}$/.test(d[key]))result[key]=d[key];
  for(const [key,lo,hi] of [['httpStatus',100,599],['providerCode',-2147483648,2147483647]])if(Number.isSafeInteger(d[key])&&d[key]>=lo&&d[key]<=hi)result[key]=d[key];
  if(typeof d.observedAt==='string'&&Number.isFinite(Date.parse(d.observedAt)))result.observedAt=d.observedAt;
  return result;
}
function saveProbes(state,job,rows){
  state.imaAccess||={};
  const source=state.catalog?.sources.find(s=>s.provider==='ima');
  for(const id of job.probeSelection){
    const row=rows.find(r=>r.collectionId===id),collection=source?.collections.find(c=>c.collectionId===id);
    // Every new attempt invalidates older success, including interruption/unprobed rows.
    const status=row&&statuses[row.status]?row.status:'unverified';
    const checkedAt=row?.checkedAt||null;
    state.imaAccess[id]={status,checkedAt,observedAt:job.finishedAt,code:row?.code||job.code||'not_tested',
      sampleRef:/^ima:\/\/media\/[A-Za-z0-9_+=.-]{1,512}$/.test(row?.sampleRef||'')?row.sampleRef:null,
      bytes:Number.isSafeInteger(row?.bytes)?row.bytes:0,
      sampleTitle:typeof row?.sampleTitle==='string'?row.sampleTitle.replace(/[\x00-\x1f\x7f]/g,' ').slice(0,300):null,
      sampleFolderId:/^[A-Za-z0-9_+=.-]{1,512}$/.test(row?.sampleFolderId||'')?row.sampleFolderId:null,
      pagesChecked:Number.isSafeInteger(row?.pagesChecked)?row.pagesChecked:0,
      diagnostic:safeDiagnostic(row?.diagnostic),
      fingerprint:signature(collection||{present:false}),configuration:job.probeConfiguration,jobId:job.id};
  }
}
module.exports={access,saveProbes,searchCheckpoint,saveSearch,safeDiagnostic,MAX_AGE};
