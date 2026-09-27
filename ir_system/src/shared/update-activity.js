(function(root,factory){
  const api=factory();
  if(typeof module==='object'&&module.exports)module.exports=api;
  else root.IRUpdateActivity=api;
})(typeof globalThis==='object'?globalThis:this,function(){
  const phases={retrying_network:'网络重试中',client_downloading:'官方客户端下载中',restarting_browser:'后台浏览器恢复中',continuing:'自动续批中',preflight:'准备中',scanning:'扫描中',enumerating:'扫描中',downloading:'下载中',web_downloading:'下载中',indexing:'入库中',parsing:'解析中',finished:'收尾中'};
  function forButton(jobs,provider,kind){
    const job=(jobs||[]).find(j=>j.status==='running'&&(j.plan?.kind||j.kind)===kind&&(j.collections||j.plan?.collections||[]).some(c=>c.provider===provider));
    if(!job)return null;
    const waiting=['waiting','cooldown','rate_limited','waiting_browser_login','waiting_accessibility'].includes(job.stage)||job.code==='rate_limit';
    const phase=job.stage==='waiting_accessibility'?'等待辅助功能授权':job.stage==='waiting_browser_login'?'等待扫码登录':waiting?'等待处理':phases[job.stage]||'运行中';
    const downloaded=Number.isSafeInteger(job.counts?.downloaded)&&job.counts.downloaded>=0?job.counts.downloaded:0;
    return {jobId:job.id,phase,waiting,animate:!waiting,detail:`${phase} · 已下载 ${downloaded} 份`};
  }
  return {forButton};
});
