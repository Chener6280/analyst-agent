const {downloadStatus}=require('./download-status');
const {access}=require('./ima-access');

// One decision for both the update dialog and the execution gate.
function updateRoute(state,provider,id,options={}){
  if(provider!=='ima')return {ready:true,code:null,label:'执行时核验',action:''};
  const capability=downloadStatus(state,provider,id,options);
  if(capability.status==='unavailable')return {ready:false,code:'ima_export_disabled',label:'原件导出受限',action:capability.detail};
  if(options.imaClientAvailable){
    const evidence=access(state,id,options);
    return {ready:true,code:null,client:evidence.status!=='api_sample_ok'||capability.route==='官方客户端',
      label:evidence.status==='api_sample_ok'?'API 优先 · 客户端备用':'官方客户端 · 执行时逐文件核验',
      action:'API 额度用尽时自动转官方客户端。可能需要辅助功能授权或登录；窗口自动操作期间请勿同时操作 IMA。仅使用正常下载按钮，不绕过导出限制。'};
  }
  if(capability.route==='官方客户端')return {ready:false,code:'ima_client_route_not_connected',label:'客户端可下载 · 自动更新待接入',action:'已验证官方下载入口，但尚无桌面批量下载器。不是登录错误，复检 API 或重启不会自动接通客户端。'};
  const evidence=access(state,id,options);
  if(evidence.status!=='api_sample_ok')return {ready:false,code:'ima_permission_probe_required',label:'API 待核验',action:evidence.detail};
  return {ready:true,code:null,label:'API 已接入 · 可更新',action:'原件样本通过，执行仍逐文件核验。'};
}
module.exports={updateRoute};
