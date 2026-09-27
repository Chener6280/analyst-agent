const test=require('node:test'),assert=require('node:assert/strict');
const {forButton}=require('../src/shared/update-activity');
const job={id:'one',kind:'backfill',status:'running',stage:'downloading',collections:[{provider:'ima'}],counts:{downloaded:12}};
test('only the running source and correct update button are marked',()=>{
 assert.equal(forButton([job],'ima','backfill').phase,'下载中');assert.equal(forButton([job],'ima','backfill').detail,'下载中 · 已下载 12 份');
 assert.equal(forButton([job],'ima','incremental'),null);assert.equal(forButton([job],'zsxq','backfill'),null);
 assert.equal(forButton([{...job,kind:'scan'}],'ima','backfill'),null);
 assert.equal(forButton([{...job,kind:'ima_probe'}],'ima','backfill'),null);
});
test('real stage distinguishes scanning, deterministic browser, parsing and waiting',()=>{
 for(const [stage,phase]of Object.entries({scanning:'扫描中',enumerating:'扫描中',web_downloading:'下载中',parsing:'解析中',indexing:'入库中',finished:'收尾中'}))assert.equal(forButton([{...job,stage}],'ima','backfill').phase,phase);
 const waiting=forButton([{...job,code:'rate_limit'}],'ima','backfill');assert.equal(waiting.animate,false);assert.equal(waiting.phase,'等待处理');
 assert.equal(forButton([{...job,stage:'new_stage'}],'ima','backfill').phase,'运行中');
});
test('all stopped, pending and terminal states clear activity regardless of old phase',()=>{
 for(const status of ['authorized','completed','budget_paused','partial','needs_attention','failed','interrupted','stopped'])assert.equal(forButton([{...job,status}],'ima','backfill'),null,status);
});
