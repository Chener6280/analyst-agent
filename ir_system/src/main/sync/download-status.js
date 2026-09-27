// Capability is separate from runtime readiness and from the user's selection.
// A successful sample proves a route, never all files or historical coverage.
const {signature}=require('./subscriptions');
function downloadStatus(state,provider,id,{configuration,now=Date.now()}={}){
  const source=state.catalog?.sources.find(s=>s.provider===provider);
  const row=source?.collections.find(c=>c.collectionId===id);
  const result=(status,route,detail,checkedAt,desktop=false)=>({status,route,detail,checkedAt:checkedAt||null,desktop,
    method:route==='官方客户端'?'Computer Use 操作官方客户端下载按钮':route==='网页程序'?'固定浏览器自动化（不调用模型）':route?.startsWith('API')?'API 直接下载（不调用模型）':null,
    label:status==='available'?'可下载':status==='unavailable'?'不可下载':'待核验',coverageComplete:false});
  if(!row||row.present===false)return result('unknown',null,'当前订阅未发现；不据此断言平台无法下载。',source?.scannedAt);
  if(provider==='zsxq'){
    const m=row.membership,p=row.permissions;
    if(m?.active===false||m?.state==='expired'||(m?.end_time&&Date.parse(m.end_time)<now))return result('unavailable',null,'会员已到期；需恢复会员后重新扫描，不能绕过。',source.scannedAt);
    if(p?.allow_download===false)return result('unavailable',null,'平台禁止附件下载；不通过截图、缓存或其他通道绕过。正文权限另行判断。',source.scannedAt);
    if(m?.active===true&&p?.allow_download===true&&['accessible','not_enabled'].includes(row.skill_api))return result('available',row.skill_api==='accessible'?'API':'网页程序',
      '会员有效且平台允许下载，通道已接入；执行仍逐文件核验。'+(p.allow_copy===false?'正文禁止复制，仅保存允许的元数据和附件。':''),source.scannedAt,true);
    return result('unknown',null,'尚未确认会员、下载策略和可用通道。',source.scannedAt);
  }
  if(provider!=='ima')return result('unknown',null,'尚无子库下载证据。',null);
  const saved=state.downloadEvidence?.['ima:'+id];
  const current=state.imaAccess?.[id];
  const match=e=>e&&e.fingerprint===signature(row)&&(configuration===undefined||e.configuration===configuration);
  if(match(saved)&&saved.status==='library_deleted')return {...result('unavailable',null,'官方客户端显示“该知识库已被删除”；订阅列表残留不代表内容仍可访问。未代替用户取消订阅。',saved.checkedAt),label:'不可下载（库已删除）',attemptedMethod:'Computer Use 核验官方客户端'};
  // Official export prohibition is not an invitation to replay URLs or caches.
  if(match(saved)&&saved.status==='client_blocked'&&!(match(current)&&current.status==='api_sample_ok'&&Date.parse(current.checkedAt)>Date.parse(saved.checkedAt)))return {...result('unavailable',null,'官方客户端明确提示“可查看、不可导出”。'+(saved.sampleTitle?'核验样本：'+saved.sampleTitle+'。':'')+'此结论针对当前验证样本，不代表穷尽全库；若权限调整需复核。',saved.checkedAt),label:'不可下载（已测样本）',attemptedMethod:'Computer Use 操作官方客户端下载按钮'};
  if(match(current)&&current.status==='api_sample_ok')return result('available','API','非音频原件样本已实际读取成功；不代表整库所有附件均可下载。',current.checkedAt,true);
  if(match(saved)&&saved.status==='client_downloaded')return result('available','官方客户端','原件已实际下载并核对文件；Computer Use 可操作官方入口，桌面批量按钮尚未接入这条通道。',saved.checkedAt,false);
  if(match(saved)&&saved.status==='client_unverified')return {...result('unknown',null,saved.reason||'已检查客户端，仍未找到可验证的导出方法。',saved.checkedAt),attemptedMethod:'Computer Use 检查官方客户端'};
  const legacy=state.subscriptionReview?.['ima:'+id];
  if(legacy?.fingerprint===signature(row)&&legacy.capability?.client==='已实测下载成功')return result('available','官方客户端','已有原件下载实证；桌面客户端批量通道尚未接入。',legacy.capability.checkedAt,false);
  if(legacy?.fingerprint===signature(row)&&legacy.capability?.api==='已实测下载成功'&&(!match(current)||current.code==='not_tested'))return result('available','API（历史实测）','已有 API 下载实证；首次使用当前配置仍需单库复核，不能把历史证据当新测试。',legacy.capability.checkedAt,false);
  return result('unknown',null,current?.status==='sample_denied'?'API 拒绝样本，但官方客户端尚未核验；不能判断整库不可下载。':'尚无已验证的下载通道；空目录、未找到样本或技术错误都不等于无权限。',current?.checkedAt||null);
}
module.exports={downloadStatus};
