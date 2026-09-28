(() => {
  const sources = IRSources;
  const names = Object.fromEntries(sources.map(s => [s.id, s.name]));
  const categories = ["ib", "company", "am", "archive", "ec", "feed", "market_daily", "article", "mikko"];
  const categoryNames={ib:'投行研报',company:'公司研究',am:'资管报告',archive:'央行·政府·智库',ec:'财报电话会',feed:'投研资讯流',market_daily:'市场日报',article:'智堡研究',mikko:'Mikko 市场短评'};
  const collectionName=p=>p.provider==='wisburg'?(categoryNames[p.collectionId]||p.name):p.name;
  const modes = { pending_selection: "待选择", off: "不采集", once: "一次性归档", incremental: "持续更新" };
  const statuses = { superseded:"已被新任务替代", authorized: "待启动", running: "运行中", completed: "本轮完成", partial: "有覆盖缺口", needs_attention: "需要处理", budget_paused: "预算暂停", stopped: "已停止", interrupted: "中断可续传", failed: "失败" };
  const stages = { preflight: "检查环境", scanning: "扫描订阅", enumerating: "枚举资料", downloading: "下载附件", web_downloading:"网页下载（无模型）", indexing: "更新索引", parsing: "解析文档", finished: "处理结束" };
  const budgetLabels = { maxOperations: "接口／网页操作上限", maxRecords: "记录上限", maxFiles: "文件上限", maxBytesMiB: "原件落盘 MiB", maxFileMiB: "单文件 MiB", maxParses: "解析份数", maxSeconds: "运行秒数" };
  const errors = { resolve_previous_job_first: "这个范围有未完成任务，请续传或处理原任务。", no_selected_collections: "没有符合本次操作的子信源，请先选择采集方式。", archive_root_required: "请先在连接设置里填写有效的本地归档目录。", first_date_required: "请为已启用的子信源填写首次更新起点。", sync_busy: "已有任务在运行，请等待或停止后再操作。", invalid_history_range: "起止日期无效，结束日期不能晚于今天（上海时间）。", sync_scope_changed: "设置已发生变化，请重新打开弹窗确认范围。", pi_not_found: "找不到 Pi，请在 CLI 设置中填写完整程序路径。", unsupported_sync_source: "这个信源的采集通道尚未接入。" };
  const esc = v => String(v ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");
  errors.previous_job_stop_timeout='旧任务尚未确认退出，新任务未启动。请等待或查看任务日志；不要删除锁或文件。';
  errors.job_superseded='此任务已被新任务替代，请使用最新任务；旧记录和文件仍保留。';
  stages.probing_permissions='核验原件样本';
  stages.continuing='自动续批中';
  stages.client_downloading='IMA 官方客户端下载（无模型）';
  stages.waiting_accessibility='等待辅助功能授权；授权后自动继续';
  stages.retrying_network='网络短暂异常，按原断点自动重试';
  Object.assign(errors,{
    ima_accessibility_required:'当前应用进程尚未通过系统授权。若 IR System 开关已开，可能仍对应旧版本；请退出旧应用，在辅助功能列表移除旧条目，再添加当前版本并启用，然后续传。程序不会自行修改系统权限。',
    ima_client_not_running:'请启动并登录官方 IMA 客户端，然后续传。',
    ima_client_library_window_required:'请在 IMA 中打开“知识库”页面，然后续传。',
    ima_client_focus_changed:'客户端操作期间焦点被切换，已保留断点；请暂时不要操作 IMA，再点击续传。',
    ima_client_library_ambiguous:'官方客户端未找到唯一匹配的库名；请打开对应知识库，维护者核验目录映射后续传。',
    ima_client_inventory_incomplete:'客户端目录尚未核对完整，不能标记完成；已保存发现位置和缺口。',
    ima_client_ui_timeout:'客户端页面或保存窗口未按预期出现，断点已保存；请检查 IMA 是否有登录或平台提示后续传。'
  });
  stages.waiting_browser_login='等待本人扫码；完成后自动续传';
  errors.headless_browser_missing='缺少与当前版本配套的后台浏览器，请安装 chromium-headless-shell 运行组件后重试；不会自动弹出普通浏览器。';
  Object.assign(errors,{headless_browser_failed:'后台浏览器启动或运行失败。断点保留，未自动弹窗；可在任务日志选择“可见浏览器续传”。',browser_profile_busy:'专用浏览器正在被另一任务使用，请等待原任务退出，不要删除登录配置或锁。',web_login_state_unknown:'网页未能确认登录状态，未自动弹窗；请检查网络或页面提示。'});
  Object.assign(errors,{ima_export_disabled:'当前已选范围有不可导出的项目（样本禁止导出或库已删除）；请在子库列表查看具体依据，取消勾选或先处理平台问题。',ima_client_route_not_connected:'已选库可通过官方客户端下载，但这条通道尚未接入更新按钮；请单独处理或取消勾选后运行程序通道。',ima_permission_probe_required:'请在对应库的“查看原因与方法 → 高级：重新核验／技术详情”中确认 API 通道；客户端可下载不等于 API 可用。',ima_probe_scope_limit:'每轮复检最多 25 个已勾选库，请先缩小范围。'});
  Object.assign(errors,{issue_state_changed:'问题或选择已变化，请重新打开预分析再操作。',required_check_cannot_be_ignored:'这是系统必检项，不能通过取消勾选绕过。'});
  Object.assign(errors,{ima_no_pending_probes:'当前勾选库的样本证据仍有效，无需重复复检。',invalid_probe_selection:'请先确认该库的订阅变化；缺失或待确认的库不能复检。'});
  const today = () => new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
  const dateTime = value => value ? /^\d{4}-\d{2}-\d{2}$/.test(value)?value+'（仅记录日期）':new Date(value).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai", hour12: false }) : "尚未检查";
  const key = p => `${p.provider}:${p.collectionId}`;
  const enabled = p => ["once", "incremental"].includes(p.mode);
  let view, timer, generation = 0, archiveStatus = null, tab = "logs", draft = [], modalSource, modalRevision, selectionDraft=null;
  let rangeKind='backfill', ranges={}, pendingPrompts=null, promptTab='nonAudio', promptGeneration=0,preflightText=null;
  let bulkSources=new Set(), bulkScope=[], verifying=false, audioActivity=[];
  try{const saved=JSON.parse(localStorage.getItem('ir-source-selection')||'[]');if(Array.isArray(saved))bulkSources=new Set(saved.filter(id=>sources.some(s=>s.id===id)));}catch{}
  function selectedSources(){return sources.filter(s=>bulkSources.has(s.id)).map(s=>s.id);}
  function bulkNames(ids){return ids.map(id=>names[id]).join(' / ');}
  function requireBulk(){const ids=selectedSources();if(!ids.length)throw new Error('请先勾选至少一个信源。');return ids;}
  function renderBulk(){
    const el=document.querySelector('#dc-bulk-actions');if(!el)return;
    el.innerHTML=`<span>已选 ${bulkSources.size} 个信源</span><button class="dc-history" data-bulk-action="verify" ${view.busy||verifying?'disabled':''}>${verifying?'核验中…':'核验'}</button><button class="dc-history" data-bulk-action="backfill" ${view.busy||verifying?'disabled':''}>更新历史</button><button class="dc-latest" data-bulk-action="incremental" ${view.busy||verifying?'disabled':''}>更新到最新</button><button class="dc-llm ai" data-bulk-action="llm">LLM</button>`;
    if(audioActivity.some(a=>bulkSources.has(a.source)||a.source==='zsxq_web'&&bulkSources.has('zsxq'))){const llm=el.querySelector('[data-bulk-action="llm"]');llm.innerHTML='<span class="dc-update-spinner"></span> 转写中';llm.setAttribute('aria-busy','true');}
  }
  function renderBulkVerification(ids){
    dialog(bulkNames(ids)+' · 合并核验',`<p class="dc-note">历史与最新共用核验。不会下载文件或调用模型；未接入的信源保留待接入状态。</p>${ids.map(id=>{const r=view.readiness?.[id];return `<section class="dc-readiness-item"><h3>${esc(names[id])} · ${esc(r?.label||'待核验')}</h3>${(r?.issues||[]).map(i=>`<p>${esc(i.title)}：${esc(i.detail||i.text)}<br>${esc(i.action)}</p>`).join('')||'<p>未发现运行环境问题；不代表资料已全部下载。</p>'}</section>`;}).join('')}<button class="dc-history" data-bulk-repair>生成合并修复提示词</button><textarea id="bulk-repair-text" class="dc-prompt-text" readonly hidden></textarea><button class="dc-history" data-copy-preflight hidden id="bulk-repair-copy">复制修复提示词</button>`);
  }
  async function verifyBulk(ids){
    verifying=true;bulkScope=[...ids];renderBulk();
    try{
      const supported=ids.filter(id=>sources.find(s=>s.id===id).ready);
      if(supported.length){
        const scan=await window.irSystem.syncScan(supported);
        if(scan.status==='cancelled')return log('已取消合并核验，未扫描。');
        log('正在扫描已选信源，完成后自动核验本地环境。');
        for(;;){await new Promise(r=>setTimeout(r,1000));await refresh();const j=view.jobs.find(j=>j.id===scan.jobId);if(!j)throw new Error('核验任务记录已不可见，请查看任务日志。');if(j.status!=='running')break;}
        await window.irSystem.syncCheckLocal(true);await refresh();
        const r=view.readiness?.zsxq;
        if(ids.includes('zsxq')&&r?.loginGroupId&&r.issues.some(i=>['web_login_unverified','human_login_required'].includes(i.code))){await window.irSystem.syncWebLogin();await refresh();}
      }
      renderBulkVerification(ids);
    }finally{verifying=false;renderBulk();}
  }
  function openBulkUpdate(ids,kind){
    readGlobalDates();rangeKind=kind;renderDates();bulkScope=[...ids];modalRevision=view.revision;
    const unsupported=ids.filter(id=>!sources.find(s=>s.id===id).ready);
    const missing=ids.filter(id=>!policies(id).some(p=>p.mode==='incremental'));
    if(unsupported.length||missing.length){
      dialog('合并更新 · 请先确认范围',`<p>${esc(bulkNames([...new Set([...unsupported,...missing])]))} 尚未接入或没有已勾选范围。不会静默跳过，也不会启动下载。</p>${missing.includes('wisburg')?`<button class="dc-latest" data-source-select="wisburg">选择智堡栏目</button><p class="dc-note">保存栏目选择后，重新点击合并更新。</p>`:''}`);
      return;
    }
    const rows=ids.flatMap(id=>policies(id).filter(p=>p.mode==='incremental'));
    dialog(bulkNames(ids)+' · 合并'+(kind==='backfill'?'更新历史':'更新到最新'),`<form id="bulk-update" data-kind="${kind}"><div class="dc-date-range">${dateFields(kind)}</div><p class="dc-note">北京时间，含首尾。一个任务、一个归档写入者；依次处理所选范围，自动续批。IMA 客户端可能占用窗口，授权、平台限制或持续故障会明确报告。</p><details open><summary>${rows.length} 个已勾选子信源</summary><ul>${rows.map(p=>`<li>${esc(names[p.provider])} / ${esc(collectionName(p))}</li>`).join('')}</ul></details><p>仅文字及非音频附件。未勾选、问号、一次性库不加入本次合并任务。IMA 保留日期依据，不按文件名猜日期。</p><button type="submit" class="dc-latest">确认范围并继续</button></form>`);
  }
  const rangeFor=kind=>ranges[kind] || IRDates.defaults(kind);
  function dateFields(kind,prefix='') {const r=rangeFor(kind);return `<label>startdate <input ${prefix?`id="${prefix}-start"`: 'name="start"'} inputmode="numeric" maxlength="6" placeholder="yymmdd" value="${IRDates.compact(r.start)}" required pattern="[0-9]{6}" /></label><span>—</span><label>enddate <input ${prefix?`id="${prefix}-end"`:'name="end"'} inputmode="numeric" maxlength="6" placeholder="yymmdd" value="${IRDates.compact(r.end)}" required pattern="[0-9]{6}" /></label>`;}
  function renderDates(){const el=document.querySelector('#dc-global-dates');if(el)el.innerHTML=`<div class="dc-date-mode"><button data-range-kind="backfill" class="${rangeKind==='backfill'?'active':''}">历史范围</button><button data-range-kind="incremental" class="${rangeKind==='incremental'?'active':''}">最新范围</button></div>${dateFields(rangeKind,'global')}<button class="dc-text-button" data-range-reset>恢复默认</button><small>北京时间 · yymmdd · 所有信源共用</small>`;}
  function readGlobalDates(){const a=document.querySelector('#global-start'),b=document.querySelector('#global-end');if(a&&b){const r={start:IRDates.parse(a.value),end:IRDates.parse(b.value)};if(r.start>r.end||r.end>today())throw new Error('invalid_history_range');if(a.dataset.dirty||b.dataset.dirty)ranges[rangeKind]=r;}}
  let lines = [];
  function friendly(error) {
    const raw = String(error?.message || error), known = Object.keys(errors).find(code => raw.includes(code));
    return known ? errors[known] : raw;
  }
  function message(text) { const el = document.querySelector("#sync-message"); if (el) el.textContent = text; }
  function log(text) { lines.push({ time: new Date().toISOString(), text }); lines = lines.slice(-80); message(text); if (tab === "logs") renderConsole(); }
  function policies(id) { return view.settings.policies.filter(p => p.provider === id); }
  function directory(id) { return view.catalog?.sources?.find(s => s.provider === id); }
  const isLocalList = id => sources.some(s => s.id === id && s.localList);
  function listPrompt(id) {
    const tool=view.sourceListsCli;
    if(!tool)throw Error('清单管理工具尚未加载，请刷新页面。');
    return `请只管理 IR System 的「${names[id]}」本地清单，不执行下载、登录、模型调用或修改 ir_search。\n工具：${tool.path}\n数据目录：${tool.dataDir}\n先使用 Node 运行上述 cli.js：list --data-dir <数据目录> --source ${id}，读取当前名单和 revision。\n按我随后明确指定的名字执行 add 或 remove，每次带 --data-dir <数据目录> --source ${id} --name <完整名字> --revision <刚读取的版本号>。公众号有已确认的 ghid 才带 --ghid，不猜 ID。参数必须独立传递或正确引用，名字不能作为命令执行。\n每次写入后重新 list 核验；版本冲突先重读，不覆盖他人修改。错误立即报告，不删除锁、不直接编辑 JSON。删除仅移除清单项，原下载资料不动；没有我指定的具体增删项就等待，不自行扩充。\n页面会自动刷新清单，下载通道仍待接入。`;
  }
  function openLocalList(id) {
    const s=sources.find(s=>s.id===id), data=view.localLists, rows=data?.sources?.[id]||[];
    dialog(s.name+' · 本地清单',`<div data-local-list-view="${id}"><p class="dc-callout">${data?.status==='error'?'清单读取失败：'+esc(data.error):`共 ${rows.length} 个${s.unit}`}。这里只管理清单，自动更新通道尚未接入。</p><div class="dc-dialog-tools"><button class="dc-history" data-list-refresh="${id}">刷新清单</button><button class="dc-history" data-list-prompt="${id}">生成清单管理提示词</button></div><p class="dc-note">可复制提示词到下方终端，让你的 CLI 模型增删名字。移除清单项不会删除已下载资料。</p><div class="dc-draft-scroll"><table class="dc-draft-table"><thead><tr><th>名称</th><th>已知标识</th></tr></thead><tbody>${rows.map(row=>`<tr><td>${esc(row.name)}</td><td>${esc(row.ghid||'—')}</td></tr>`).join('')||'<tr><td colspan="2">清单为空，暂未配置。</td></tr>'}</tbody></table></div><p class="dc-note">独立清单：${esc(data?.file||'尚未加载')}</p></div>`);
  }
  function jobsFor(id) { return view.jobs.filter(j => j.collections?.some(c => c.provider === id) || j.providers?.includes(id)); }
  function checkedSummary(id) {
    const selected = policies(id).filter(p => p.mode === "incremental"), marks = selected.map(p => view.watermarks?.[key(p)]).filter(m => m?.through);
    const windows=selected.map(p=>view.watermarks?.[key(p)]?.latestWindow).filter(Boolean);
    if (id === "ima") return { text: "日期覆盖待核验", note: marks.length ? `${marks.length}/${selected.length} 个增量库已检查` : "按目录去重，不推断发布日期" };
    if(windows.length)return {text:`最近检查 ${windows.map(w=>w.end).sort().at(-1)}`,note:'仅所选日期窗口，不代表此前连续覆盖'};
    if (selected.length && marks.length === selected.length) return { text: `检查至 ${marks.map(m => m.through).sort()[0]}`, note: "已选增量范围 · 不代表历史齐全" };
    return { text: marks.length ? `${marks.length}/${selected.length} 已检查` : "尚无检查记录", note: "展开查看资料日期与缺口" };
  }
  function updateButton(source,kind,activity){
    const label=kind==='backfill'?'更新历史':'更新到最新';
    const canReplace=view.replaceableProviders?.includes(source.id);
    return '<button class="'+(kind==='backfill'?'dc-history':'dc-latest')+(activity?(activity.waiting?' dc-update-waiting':' dc-update-running'):'')+'" data-source-update="'+source.id+'" data-kind="'+kind+'" aria-busy="'+Boolean(activity)+'" '+(activity?'title="'+esc(activity.detail)+'；点击可确认新任务替代"':'')+' '+((view.busy&&!canReplace)||!source.ready?'disabled':'')+'>'+(activity?(activity.animate?'<span class="dc-update-spinner" aria-hidden="true"></span>':'')+label+' · '+esc(activity.phase):label+(kind==='incremental'?' <span>↗</span>':''))+'</button>';
  }
  function renderRows() {
    const el = document.querySelector("#source-rows"); if (!el) return;
    el.innerHTML = sources.map(s => {
      const selected = policies(s.id).filter(p=>p.mode==='incremental'), dirs = directory(s.id), last = jobsFor(s.id)[0], summary = checkedSummary(s.id);
      const pending = policies(s.id).filter(p=>p.mode==='pending_selection').length;
      const help=view.assistance?.[s.id];
      const historyActivity=IRUpdateActivity.forButton(view.jobs,s.id,'backfill'),latestActivity=IRUpdateActivity.forButton(view.jobs,s.id,'incremental'),activity=historyActivity||latestActivity;
      const readiness=view.readiness?.[s.id]||{tone:'unknown',label:'待核验'};
      const count = archiveStatus?.sources?.filter(r => r.source === s.id || s.id === "zsxq" && r.source === "zsxq_web").reduce((n, r) => n + r.count, 0);
      const speaking=audioActivity.some(a=>a.source===s.id||s.id==='zsxq'&&a.source==='zsxq_web');
      return `<tr data-source-row="${s.id}"><td><div class="dc-source-name"><input type="checkbox" class="dc-source-check" data-bulk-source="${s.id}" aria-label="合并操作选择 ${s.name}" ${bulkSources.has(s.id)?'checked':''} ${verifying?'disabled':''}><span class="dc-source-mark mark-${s.id}">${s.mark}</span><div><strong>${s.name}</strong><small>${s.detail}</small></div></div></td>
        <td>${s.localList ? `<button class="dc-selection" data-local-list="${s.id}">${view.localLists?.status==='error'?'清单读取异常':`清单 ${view.localLists?.sources?.[s.id]?.length||0} 个${s.unit}`} <span>⌄</span></button><small class="dc-row-note">本地管理 · 终端修改后自动刷新</small>` : s.children ? `<button class="dc-selection" data-source-select="${s.id}">${selected.length ? `已选 ${selected.length} 个${s.unit}` : `选择${s.unit}`} <span>⌄</span></button><small class="dc-row-note">${pending ? `${pending} 个目录条目待选择` : dirs ? `目录 ${dirs.collections.length} 个 · ${dirs.complete ? "扫描完成" : "扫描不完整"}` : "尚未扫描订阅"}</small>` : `<span class="dc-no-child">—</span><small class="dc-row-note">${s.id === "wisburg" ? "采集范围在更新时确认" : "无子信源选择"}</small>`}</td>
        <td><button class="dc-coverage" data-source-coverage="${s.id}">${s.ready ? summary.text : "采集待接入"}<span>↗</span></button><small class="dc-row-note">${s.ready ? summary.note : s.localList ? "清单管理已接入，自动更新待接入" : "已有搜索能力，尚未接入同步"}</small></td>
        <td><button class="dc-readiness-button ${readiness.tone}" data-source-readiness="${s.id}" title="预分析：历史与最新共用的下载前检查">${esc(readiness.label)}</button><small class="dc-row-note">${last?esc(statuses[last.status]||last.status)+' · ':''}${count === undefined ? "本地条目待核对" : `本地索引 ${count.toLocaleString()} 条`}</small></td>
        <td class="dc-source-actions">${updateButton(s,'backfill',historyActivity)}${updateButton(s,'incremental',latestActivity)}<button class="dc-llm ${help?.needsAI||speaking?'ai':'neutral'}" data-source-llm="${s.id}" aria-busy="${speaking}" title="生成非语音／语音执行提示词，不调用模型">${speaking?'<span class="dc-update-spinner"></span> 转写中':'LLM'+(help?.needsAI?' ●':'')}</button>${activity?`<small class="dc-update-progress ${activity.waiting?'waiting':''}" role="status">${esc(activity.detail)}</small>`:''}</td></tr>`;
    }).join("");
    renderBulk();
    const state = document.querySelector("#dc-run-state"); if (state) state.textContent = view.replacing ? "● 正在安全停止旧任务，请稍候" : view.busy ? "● 有任务运行中" : "● 当前空闲";
  }
  function jobHtml(j) {
    const sourceNames = [...new Set([...(j.collections || []).map(c => names[c.provider]), ...(j.providers || []).map(p => names[p])])].filter(Boolean).join(" / ");
    const quotaWaiting=j.code==='ima_daily_quota_exhausted'||j.diagnostic?.providerCode===220021||j.imaProbes?.some(r=>r.diagnostic?.providerCode===220021);
    const resume = (["budget_paused", "interrupted", "stopped"].includes(j.status)||j.status==='needs_attention'&&(quotaWaiting||/^ima_(client_|accessibility_)/.test(j.code||'')||j.attempt===1&&j.membershipRepair)) && !["scan","ima_probe"].includes(j.kind);
    return `<article class="dc-log-job"><div><time>${esc(dateTime(j.startedAt || j.createdAt))}</time><strong>${esc(sourceNames || "已选信源")} · ${j.kind === "ima_probe" ? "原件权限复检" : j.kind === "scan" ? "扫描目录" : j.kind === "backfill" ? "更新历史" : "更新到最新"}</strong><span class="dc-log-state">${j.recoveredBeforeDownload?'启动故障已恢复':esc(statuses[j.status] || j.status)}</span></div>
      <p>${esc(stages[j.stage] || j.stage || "等待执行")}　新增 ${j.counts.newRecords || 0} · 下载 ${j.counts.downloaded || 0} · 复用 ${j.counts.reused || 0} · 解析 ${j.counts.parsed || 0} · 音频待办 ${j.counts.audioDeferred || 0}</p>
      ${j.untilComplete?`<p>自动处理完整所选范围 · 第 ${j.batchNumber||1} 批 · 累计统计；仅错误、无进展或主动停止时中断。</p>`:''}
      ${j.status==='running'&&j.stage==='waiting_accessibility'?'<p class="dc-log-warning">请在 macOS 系统设置 → 隐私与安全性 → 辅助功能中启用当前 IR System。程序最多等待 3 分钟，确认授权后自动续传；此时尚未下载，不必重复点击。超时后可从这里授权续传。</p>':''}
      ${j.collections?.length?`<p>北京时间范围：${esc(j.collections[0].start)} 至 ${esc(j.collections[0].end)}（含首尾）；当日更新仅包含执行时已发布的资料。</p>`:''}
      ${quotaWaiting?'<p class="dc-log-warning">IMA API 当日额度用尽（220021），不是订阅无权限或日期错误。macOS 版续传时可自动转官方客户端，沿用原范围；客户端仍须有正常下载权限，不会改成次日范围。</p>':''}
      ${j.diagnostic?`<p>接口诊断：${esc(j.diagnostic.operation||j.diagnostic.phase||'未提供')} · HTTP ${esc(j.diagnostic.httpStatus??'未知')} · 业务码 ${esc(j.diagnostic.providerCode??'未知')}</p>`:''}
      ${j.deferredCollections?.length?`<p>本任务仅更新 ${j.collectionCount} 个库；另 ${j.deferredCollections.length} 个已勾选库本次暂不更新，不代表 IMA 全部完成。</p>`:''}
      ${j.code==='batch_no_progress'?'<p>当前批次没有推进断点或产生新文件，已停止空转；需维护者检查，不是已完成。</p>':''}
      ${['headless_browser_failed','browser_interrupted'].includes(j.code)?'<p>浏览器中断，断点和已下载文件保留。不会自动反复弹窗；可明确选择可见浏览器续传。</p>':''}
      ${j.code ? `<p class="dc-log-warning">${esc(errors[j.code]||j.code)}${j.issues?.length ? ` · ${esc([...new Set(j.issues.map(i => i.code))].join("、"))}` : ""}</p>` : ""}
      ${j.recoveredBeforeDownload?'<p>旧任务未进入下载；扫描与环境复检已通过，不再阻塞。可重新点击“更新历史／更新到最新”，原失败记录保留。</p>':''}
      ${j.replacements?.length?`<p>已有 ${j.supersededKeys.length} 个订阅范围被新任务替代，旧断点不再用于这些范围；文件和历史记录保留。</p>`:''}
      ${j.membershipRepair&&j.status!=='superseded'?`<p>会员判断程序已修订：${esc(j.membershipRepair.name)}。可续传，或按新范围开始更新；均重新扫描并核验。</p>`:''}
      ${j.issues?.some(i=>i.collectionId)?`<ul>${j.issues.filter(i=>i.collectionId).map(i=>`<li>${esc(i.name||i.collectionId)}：${esc(i.code)}（仅此订阅暂停，不自动重试）</li>`).join('')}</ul>`:''}
      ${j.imaProbeDiagnostic?`<p class="dc-log-warning">订阅扫描诊断：${esc(j.imaProbeDiagnostic.operation||'未提供接口名')} · ${esc(j.imaProbeDiagnostic.code)} · HTTP ${esc(j.imaProbeDiagnostic.httpStatus??'未提供')} · 业务码 ${esc(j.imaProbeDiagnostic.providerCode??'未提供')} · ${esc(dateTime(j.imaProbeDiagnostic.observedAt))}</p>`:''}
      ${j.kind==='ima_probe'?`<p>样本尝试 ${j.counts.samplesAttempted||0} · 通过 ${j.counts.samplesPassed||0} · 读取 ${j.counts.sampleBytes||0} 字节（未保存原件）</p><details><summary>逐库复检结果</summary><ul>${(j.imaProbes||[]).map(r=>`<li>${esc(policies('ima').find(p=>p.collectionId===r.collectionId)?.name||r.collectionId)}：${esc(r.label)} · ${esc(r.code)} · ${esc(dateTime(r.checkedAt))}</li>`).join('')}</ul></details>`:''}
      ${j.webManifests?.length?`<details class="dc-scope-detail"><summary>网页归档清单／断点位置</summary><p>以下路径相对于当前归档目录；checkpoint.json 与 manifest.json 同目录。</p><ul>${j.webManifests.map(p=>`<li>${esc(p)}</li>`).join('')}</ul></details>`:''}
      <div class="dc-log-actions">${["running", "authorized"].includes(j.status) && view.busy ? `<button data-sync-stop="${j.id}">停止本轮</button>` : ""}${resume && !view.busy ? `<button data-sync-resume="${j.id}">授权续传</button>` : ""}${resume&&!view.busy&&['headless_browser_failed','browser_interrupted'].includes(j.code)?`<button data-sync-resume-visible="${j.id}">可见浏览器续传</button>`:''}<span>${esc(j.id.slice(0, 8))} · 不代表全量覆盖</span></div></article>`;
  }
  function renderConsole() {
    const el = document.querySelector("#console-body"); if (!el || !view) return;
    document.querySelectorAll("[data-console-tab]").forEach(b => { b.classList.toggle("active", b.dataset.consoleTab === tab); b.setAttribute("aria-selected", String(b.dataset.consoleTab === tab)); });
    el.hidden=tab==='terminal';document.querySelector('#terminal-panel').hidden=tab!=='terminal';
    if(tab==='terminal'){window.fitIRTerminal();return;}
    el.innerHTML = `<div class="dc-console-intro"><span>系统输出</span> 以下为实际程序状态，查看日志不调用模型。</div>${view.jobs.length ? view.jobs.slice(0, 10).map(jobHtml).join("") : `<div class="dc-console-empty"><span class="dc-terminal-glyph">›_</span><div><strong>准备就绪，等待第一个任务。</strong><p>从上方选择一个信源。任务进度与暂停原因会显示在这里。</p></div></div>`}${lines.map(line => `<div class="dc-local-line"><time>${esc(dateTime(line.time))}</time><span>${esc(line.text)}</span></div>`).join("")}`;
  }
  function showConsoleTab(next) {
    if(!['logs','terminal'].includes(next))return;
    tab = next; renderConsole();
  }
  window.updateSourceArchiveStatus = value => { archiveStatus = value; if (view) renderRows(); };
  window.renderSyncCenter = async () => {
    clearTimeout(timer); const current = ++generation; tab = "terminal"; archiveStatus = null;
    const el = document.querySelector("#sync-center"); if (!el) return;
    try {
      view = await window.irSystem.syncGetState(); if (generation !== current || !el.isConnected) return;
      el.innerHTML = `<section class="dc-sources"><div class="dc-section-top"><div><span class="dc-section-number">01</span><h2>信源管理</h2><span class="dc-count">${String(sources.length).padStart(2,'0')} SOURCES</span><div id="dc-bulk-actions" class="dc-bulk-actions"></div></div><button class="dc-text-button" data-open-budgets>本轮预算与执行设置 ⚙</button></div>
        <div id="dc-global-dates" class="dc-global-dates"></div><div class="dc-table-wrap"><table class="dc-source-table"><thead><tr><th>信源</th><th>子信源</th><th>信息截止于 / 覆盖</th><th>预分析</th><th>更新操作</th></tr></thead><tbody id="source-rows"></tbody></table></div><div class="dc-table-foot"><span>绿色：环境就绪 · 琥珀色：运行问题 · 下载能力见子信源列表</span><span>历史／最新共用预分析 · 紫色 LLM：AI 待办</span></div></section>
        <div id="sync-message" class="dc-message" role="status" aria-live="polite">选择信源开始。所有下载都需要确认范围；本页没有自动启动任务。</div>
        <section class="dc-console"><div class="dc-console-title"><div><span class="dc-section-number">02</span><h2>Command Window</h2><span class="dc-console-subtitle">采集之后，在这里整理。</span></div><span id="dc-run-state">● 当前空闲</span></div>
        <div class="dc-console-tabs" role="tablist" aria-label="工作窗口"><button data-console-tab="terminal" role="tab" class="active" aria-selected="true">终端</button><button data-console-tab="logs" role="tab" aria-selected="false">任务日志</button><span>下载程序与本地终端相互独立</span></div><div id="console-body" class="dc-console-body" role="tabpanel"></div><div id="terminal-panel" hidden></div></section>
        <dialog id="source-dialog" class="dc-dialog" aria-labelledby="source-dialog-title"></dialog>`;
      document.querySelector('#dc-global-dates').insertAdjacentHTML('beforebegin','<div id="dc-audio-activity" class="dc-audio-active" role="status"></div>');
      renderDates();renderRows(); await window.mountIRTerminals(document.querySelector('#terminal-panel'));renderConsole(); poll(current);pollAudio(current);
    } catch (e) { el.innerHTML = `<p class="dc-message">${esc(friendly(e))}</p>`; }
  };
  async function poll(current) {
    clearTimeout(timer); if (current !== generation || !document.querySelector("#source-rows")) return;
    try { const latest = await window.irSystem.syncGetState(); if (current !== generation) return;
      const catalogChanged = JSON.stringify(view.catalog) !== JSON.stringify(latest.catalog);
      const listsChanged = JSON.stringify(view.localLists) !== JSON.stringify(latest.localLists);
      const readinessChanged=JSON.stringify(view.readiness)!==JSON.stringify(latest.readiness);
      const capabilityChanged=JSON.stringify(view.downloadStatus)!==JSON.stringify(latest.downloadStatus);
      const choicesChanged=JSON.stringify(view.settings.policies)!==JSON.stringify(latest.settings.policies);
      const imaChanged=JSON.stringify(view.imaAccess)!==JSON.stringify(latest.imaAccess)||view.busy!==latest.busy;
      const routesChanged=JSON.stringify(view.updateRoutes)!==JSON.stringify(latest.updateRoutes)||view.busy!==latest.busy;
      view = latest;
      const listDialog=document.querySelector('[data-local-list-view]');
      if(listsChanged&&listDialog&&document.querySelector('#source-dialog')?.open)openLocalList(listDialog.dataset.localListView);
      if(routesChanged&&document.querySelector('#source-update[data-provider="ima"]'))renderImaUpdateRoutes();
      if ((catalogChanged||choicesChanged) && document.querySelector("#source-dialog")?.open && document.querySelector("#source-selection")) {
        // New scan invalidates any unsaved choices against the old status.
        draft=structuredClone(policies(modalSource));modalRevision=view.revision;
        document.querySelector('#source-draft-rows').innerHTML=draftRows();dialogMessage('新结果已载入。已确认不可下载的项默认打叉，其余新增／变化项等待确认；未自动下载。');
      }
      if(capabilityChanged && document.querySelector('#source-selection')) document.querySelector('#source-draft-rows').innerHTML=draftRows();
      const evidence=document.querySelector('[data-ima-evidence-view]');
      if((imaChanged||capabilityChanged)&&evidence&&document.querySelector('#source-dialog')?.open)openImaEvidence(evidence.dataset.imaEvidenceView);
      const readiness=document.querySelector('[data-readiness-provider]');
      if(readinessChanged && document.querySelector('#source-dialog')?.open && readiness)openReadiness(readiness.dataset.readinessProvider);
      renderRows(); renderConsole(); }
    catch (e) { message(friendly(e)); }
    if (current === generation) timer = setTimeout(() => poll(current), 2500);
  }
  async function refresh() { view = await window.irSystem.syncGetState(); renderRows(); renderConsole(); }
  async function pollAudio(current){
    if(current!==generation||!document.querySelector('#dc-audio-activity'))return;
    try{
      const result=await window.irSystem.archiveRequest('audio_list',{});
      if(current!==generation)return;
      const data=result.data||result;audioActivity=data.activity||[];
      const el=document.querySelector('#dc-audio-activity');
      if(el)el.textContent=audioActivity.map(a=>`转写中 · ${names[a.source]||a.source} · ${a.title} · ${Math.round(a.completed_seconds)} / ${Math.round(a.duration_seconds)} 秒`).join('；');
      renderRows();
    }catch{audioActivity=[];const el=document.querySelector('#dc-audio-activity');if(el)el.textContent='转写状态暂不可读；未启动转写。';}
    if(current===generation)setTimeout(()=>pollAudio(current),5000);
  }
  function dialog(title, body) {
    const d = document.querySelector("#source-dialog");
    d.innerHTML = `<div class="dc-dialog-heading"><div><div class="eyebrow">SOURCE CONTROL</div><h2 id="source-dialog-title">${esc(title)}</h2></div><button data-dialog-close aria-label="关闭弹窗">×</button></div><div class="dc-dialog-body">${body}</div><p id="dialog-message" class="dc-dialog-message" role="status"></p>`;
    if (!d.open) d.showModal(); return d;
  }
  function dialogMessage(text) { const el = document.querySelector("#dialog-message"); if (el) el.textContent = text; }
  function closeDialog() { document.querySelector("#source-dialog")?.close(); }
  function draftRows() {
    draft.sort((a,b)=>{const rank=p=>p.mode==='incremental'?0:p.mode==='pending_selection'?1:2;return rank(a)-rank(b)||a.name.localeCompare(b.name,'zh-CN');});
    return draft.map((p,i)=>{
      const c=directory(modalSource)?.collections.find(c=>c.collectionId===p.collectionId),r=view.subscriptionReview?.[key(p)];
      const status=[c?.present===false?'订阅已消失':null,c?.membership?.state==='expired'?'会员已到期':null,c?.membership?.state==='active_paid'?'会员有效':null,c?.membership?.state==='active_free'?'免费有效':null,c?.skill_api==='not_enabled'?'Skill 未开通':null,c?.permissions?.allow_download===false?'禁止附件下载':null,c?.directoryAccess==='unavailable'?'目录访问受限':null].filter(Boolean).join(' · ');
      const pending=p.mode==='pending_selection',checked=p.mode==='incremental',cap=view.downloadStatus?.[key(p)];
      const badge='<span class="dc-download-badge dc-download-'+esc(cap?.status||'unknown')+'">'+esc(cap?.label||'待核验')+(cap?.route?' · '+esc(cap.route):'')+'</span><details><summary>查看原因与方法</summary><p>'+esc(cap?.detail||'尚未核验')+'</p><p>导出／核验方法：'+esc(cap?.method||cap?.attemptedMethod||'尚无已验证方法')+'</p><small>核验时间：'+esc(dateTime(cap?.checkedAt))+'</small>'+(modalSource==='ima'?'<p><button type="button" class="dc-text-button" data-ima-evidence="'+esc(p.collectionId)+'">高级：重新核验／技术详情</button></p>':'')+'</details>';
      const reason=pending?({new:'新订阅，待确认',changed:'状态已变化，待确认',missing:'订阅已消失，待确认'}[r?.reason]||'待确认'):view.readiness?.[modalSource]?.excluded?.some(x=>x.collectionId===p.collectionId)?'预分析已排除，当前不参与更新':(!checked&&r?.autoExcluded?'已确认不可下载，默认打叉':r?.originalMark==='需要下载'&&!checked?'原标记：一次性归档，当前未勾选':'');
      return '<tr data-draft="'+i+'" class="'+(pending?'dc-review-pending':'')+'"><td><div class="dc-tristate"><span class="dc-choice-state" aria-label="'+(pending?'待确认':checked?'已勾选':'未勾选')+'">'+(pending?'?':checked?'✓':'×')+'</span><button type="button" data-choice="'+i+'" data-value="incremental" aria-label="勾选 '+esc(p.name)+'" class="'+(checked?'selected':'')+'">✓</button><button type="button" data-choice="'+i+'" data-value="off" aria-label="不选择 '+esc(p.name)+'" class="'+(!pending&&!checked?'selected':'')+'">×</button></div></td><td><strong>'+esc(p.name)+'</strong><small>'+esc(p.collectionId)+'</small></td><td>'+badge+'<span>'+esc(status||'目录已发现')+'</span><small>'+esc(reason)+'</small></td></tr>';
    }).join('') || '<tr><td colspan="3" class="dc-empty-cell">点击“扫描当前订阅”，订阅清单将自动出现。</td></tr>';
  }
  function openSelection(id,restore=false) {
    if(id==='wisburg')return openWisburgSelection();
    const saved=restore&&selectionDraft?.source===id&&selectionDraft.revision===view.revision?selectionDraft:null;
    modalSource=id;modalRevision=view.revision;draft=structuredClone(saved?saved.rows:policies(id));selectionDraft=null;
    for(const c of directory(id)?.collections||[])if(!draft.some(p=>p.collectionId===c.collectionId))draft.push({provider:id,collectionId:c.collectionId,name:c.name,mode:'pending_selection',firstDate:''});
    const s=sources.find(s=>s.id===id);
    dialog(s.name+' · 选择'+s.unit, '<div class="dc-dialog-tools"><span>已勾选置顶。黄色 ? 需确认成 ✓ 或 ×。</span><button class="dc-history" data-scan-source="'+id+'" '+(view.busy?'disabled':'')+'>扫描当前订阅</button></div><p class="dc-note">已确认不可下载的项默认打叉；待核验不等于不可下载。勾选只代表更新意向，不改变平台权限。恢复可下载后需重新确认，不自动勾选。'+(id==='ima'?'IMA 扫描只发现订阅，不会被某个库的原件权限挡住。可下载包含 API 或官方客户端通道；待核验不等于不可下载。':'星球扫描同时核验会员、Skill 与下载策略。')+'</p><form id="source-selection"><div class="dc-draft-scroll"><table class="dc-draft-table"><thead><tr><th>选择</th><th>'+s.unit+'名称</th><th>原件下载 / 通道</th></tr></thead><tbody id="source-draft-rows">'+draftRows()+'</tbody></table></div><div class="dc-dialog-footer"><span>仅 ✓ 参加更新。保存不启动任务。</span><button class="dc-latest" type="submit">保存选择</button></div></form>');
  }
  function openUpdate(id,kind) {
    readGlobalDates();rangeKind=kind;renderDates();
    modalSource=id;modalRevision=view.revision;
    const rows=policies(id).filter(p=>p.mode==='incremental'),initialize=false;
    if(!rows.length) {
      openSelection(id);dialogMessage('请先勾选需要更新的子信源。');
      return;
    }
    dialog(names[id]+' · '+(kind==='backfill'?'更新历史':'更新到最新'),'<form id="source-update" data-provider="'+id+'" data-kind="'+kind+'" data-initialize="'+(initialize?'yes':'no')+'"><div class="dc-date-range">'+dateFields(kind)+'</div><p class="dc-note">北京时间，含首尾。'+(kind==='backfill'?'默认上个月同日（月底取有效日）至昨天。':'默认今天至今天，仅检查这一天，不自动补齐历史缺口。')+'日期会用于所有信源同类操作。</p><div class="dc-scope-summary"><span>本次范围</span><strong>'+(initialize?'智堡全部 9 个固定栏目':rows.length+' 个已勾选子信源')+'</strong><small>不扩展到问号或未勾选项</small></div>'+(id==='ima'?'<div class="dc-callout">IMA 缺少可靠发布日期，将枚举已选库目录并去重，不能严格按上述日期过滤。</div>':'')+'<details class="dc-scope-detail"><summary>查看已选范围</summary><ul>'+rows.map(collectionName).map(n=>'<li>'+esc(n)+'</li>').join('')+'</ul></details><div class="dc-budget-summary">仅文字与非音频附件。音频、转写和 OCR 不自动启动。程序通道不可用或权限变化会暂停。</div><div class="dc-dialog-footer"><span>下一步确认联网范围和预算。</span><button type="submit" class="dc-latest">'+(initialize?'保存范围并继续':'确认范围并继续')+'</button></div></form>');
    if(id==='ima')renderImaUpdateRoutes();
  }
  function openWisburgSelection(){
    modalSource='wisburg';modalRevision=view.revision;
    const existing=new Map(policies('wisburg').map(p=>[p.collectionId,p]));
    dialog('智堡 · 选择栏目',`<form id="wisburg-selection"><p class="dc-note">保存后，更新历史、更新到最新及合并更新共用这份选择。未勾选栏目不下载；保存不会启动任务。</p><div class="dc-readiness-controls"><button type="button" class="dc-history" data-wisburg-select="all">全选 9 个栏目</button><button type="button" class="dc-history" data-wisburg-select="none">清空选择</button></div><div class="dc-cli-fields">${categories.map(id=>{const p=existing.get(id);return `<label><input type="checkbox" name="category" value="${id}" ${p?.mode==='incremental'||!existing.size?'checked':''}>${esc(categoryNames[id])}<small> ${esc(id)}</small></label>`;}).join('')}</div><p id="wisburg-selection-count" role="status"></p><div class="dc-dialog-footer"><span>仅保存栏目，不下载、不改变日期。</span><button type="submit" class="dc-latest" ${view.busy?'disabled':''}>保存选择</button></div></form>`);
    updateWisburgCount();
  }
  function updateWisburgCount(){
    const form=document.querySelector('#wisburg-selection');if(!form)return;
    const count=form.querySelectorAll('[name="category"]:checked').length;
    form.querySelector('#wisburg-selection-count').textContent=`已选 ${count} / 9 个栏目${count?'':'，请勾选需要更新的栏目'}`;
    form.querySelector('button[type="submit"]').disabled=view.busy||form.dataset.submitting==='yes';
  }
  function renderImaUpdateRoutes(){
    const form=document.querySelector('#source-update[data-provider="ima"]');if(!form)return;
    const rows=policies('ima').filter(p=>p.mode==='incremental'),ready=rows.filter(p=>view.updateRoutes?.[key(p)]?.ready),pending=rows.length-ready.length;
    let panel=form.querySelector('#ima-update-routes');
    if(!panel){panel=document.createElement('section');panel.id='ima-update-routes';form.querySelector('.dc-budget-summary').before(panel);}
    panel.innerHTML=`<h3>本次更新通道 · ${ready.length} / ${rows.length} 个库已就绪</h3><p class="dc-note">平台可下载 ≠ 桌面自动更新已接入。以下逐库列出实际通道；未接入或待核验的库不会被标记为完成。</p><div class="dc-draft-scroll"><table class="dc-draft-table"><thead><tr><th>已勾选知识库</th><th>更新按钮状态／下一步</th></tr></thead><tbody>${rows.map(p=>{const r=view.updateRoutes?.[key(p)]||{ready:false,label:'通道待核验',action:'请刷新状态。'};return `<tr data-update-route="${esc(p.collectionId)}"><td>${esc(p.name)}</td><td><strong>${esc(r.label)}</strong><p>${esc(r.action)}</p>${r.code==='ima_permission_probe_required'?`<button type="button" class="dc-history" data-update-probe="${esc(p.collectionId)}" ${view.busy?'disabled':''}>核验这个库的 API</button>`:''}</td></tr>`;}).join('')}</tbody></table></div>${pending?`<p class="dc-callout">本次可先更新 ${ready.length} 个已就绪库；其余 ${pending} 个暂不更新，原订阅勾选保留。客户端待接入属于开发缺口，不需要你反复扫码或重启。</p>`:''}`;
    form.querySelector('.dc-dialog-footer').innerHTML=`<span>${pending?'仅缩小本次执行范围，不修改订阅选择。':'下一步确认联网范围和预算。'}</span><button type="submit" class="dc-latest" ${pending?'data-ready-only':''} ${!ready.length||view.busy?'disabled':''}>${pending?`本次只更新已就绪的 ${ready.length} 个库`:'确认范围并继续'}</button>`;
  }
  async function openAssistance(id) {
    await refresh();
    return openLLM(id);
  }
  async function checkReadiness(id,force=false){
    await refresh();openReadiness(id);
    if(view.busy)return dialogMessage('当前有任务运行，请先等待任务结束。');
    dialogMessage('正在检查本地工具链、归档目录与锁；不会联网或下载。');
    document.querySelectorAll('#source-dialog [data-probe-ima], #source-dialog [data-probe-ima-library], #source-dialog [data-scan-source], #source-dialog [data-check-readiness], #source-dialog [data-issue-considered]').forEach(b=>b.disabled=true);
    try{await window.irSystem.syncCheckLocal(force);await refresh();
      const r=view.readiness?.[id];
      if(id==='zsxq'&&r?.loginGroupId&&r.issues.some(i=>['web_login_unverified','human_login_required'].includes(i.code))&&!r.issues.some(i=>['chrome_not_found','web_archive_locked','web_environment_unverified'].includes(i.code))){
        dialogMessage('正在后台核验登录；只有确需登录时才弹出二维码，请本人扫码。不会启动下载。');
        await window.irSystem.syncWebLogin();await refresh();
      }
      if(document.querySelector('#source-dialog')?.open&&document.querySelector('[data-readiness-provider]')?.dataset.readinessProvider===id)openReadiness(id);
    }catch(e){if(document.querySelector('#source-dialog')?.open)dialogMessage(friendly(e));}
  }
  function openImaEvidence(id){
    const p=policies('ima').find(p=>p.collectionId===id);if(!p)return;
    if(document.querySelector('#source-selection'))selectionDraft={source:modalSource,revision:modalRevision,rows:structuredClone(draft)};
    const e=view.imaAccess?.[id]||{},d=e.diagnostic,cap=view.downloadStatus?.['ima:'+id],s=e.search,disabled=view.busy||p.mode==='pending_selection',phases={subscription_scan:'刷新订阅目录',directory_page:'查找目录样本',sample_read:'读取原件样本'};
    dialog(p.name+' · 重新核验／技术详情',`<div class="dc-ima-evidence" data-ima-evidence-view="${esc(id)}"><p class="dc-callout">${esc(cap?.label||'待核验')} · ${esc(cap?.method||cap?.attemptedMethod||'暂无已验证方法')}<br>${esc(cap?.detail||'')}</p><p class="dc-note">本页是按需诊断，不是每次更新的必做步骤。重新核验只测试这个库的 API 样本，不启动下载任务、不自动勾选。客户端能力需在官方客户端另行核验。</p><h3>API 技术详情</h3><p>${esc(e.label||'未核验')} · ${esc(e.code||'probe_required')}</p>${s?`<p>累计查 ${s.pagesTotal} 页 · ${s.hasSample?'已找到样本':s.exhausted?'本次目录已查完':`待查 ${s.pendingPages} 处`}</p>`:''}<p class="dc-callout">${esc(e.detail||'尚未检查。')}</p><dl><dt>知识库 ID</dt><dd>${esc(id)}</dd><dt>样本标题</dt><dd>${esc(e.sampleTitle||'旧记录未保留标题；单库复检后可补充，不按名称猜测文件。')}</dd><dt>样本引用</dt><dd>${esc(e.sampleRef||'尚无样本')}</dd>${e.sampleFolderId?`<dt>所在文件夹 ID</dt><dd>${esc(e.sampleFolderId)}</dd>`:''}<dt>核验时间（北京时间）</dt><dd>${esc(dateTime(e.checkedAt))}</dd><dt>诊断</dt><dd>${d?`${esc(phases[d.phase]||d.phase)} · ${esc(d.code)}${d.operation?`<br>接口 ${esc(d.operation)}`:''}<br>HTTP ${esc(d.httpStatus??'未提供')} · 业务码 ${esc(d.providerCode??'旧接口未提供')}<br>${esc(dateTime(d.observedAt))}`:'旧日志无详细诊断；不能据此猜测限流或权限。'}</dd></dl>
      <p class="dc-note">客户端核验：在官方 IMA 中打开这个库，定位同一个样本，检查是否提供官方“下载”入口。可阅读不等于可下载；接口拒绝不等于会员过期。客户端若能实际下载，再由维护者接入并验收自动化；此处没有人工“标记通过”入口，也不会绕过平台限制。</p>
      <div class="dc-readiness-controls"><button class="dc-history" data-probe-ima-library="${esc(id)}" ${disabled?'disabled':''}>${s&&!s.hasSample&&s.pendingPages?'继续找样本':'重新核验 API'}</button><button class="dc-text-button" data-probe-ima-library="${esc(id)}" data-probe-restart ${disabled?'disabled':''}>从头重新找样本…</button><button class="dc-history" data-evidence-back>返回订阅列表</button></div></div>`);
  }
  function openReadiness(id) {
    const result=view.readiness?.[id]||{tone:'unknown',label:'待核验',issues:[],selected:0},reasons=result.issues;
    const title=result.tone==='ready'?'运行环境就绪':result.tone==='attention'?'运行前需处理':'运行环境待核验';
    dialog(names[id]+' · 预分析 · '+title,`<div data-readiness-provider="${id}" data-readiness-tone="${result.tone}">
      <p class="dc-callout ${result.tone==='ready'?'dc-ready-callout':''}">${result.tone==='ready'?`程序运行环境已就绪。各子库是否可下载、走哪条通道，请看订阅列表；绿色不代表每个库都可下载。`:`当前有 ${reasons.length} 项需要处理或核验，不代表整个信源都不能下载。`}${result.excluded?.length?` 已排除 ${result.excluded.length} 个库／栏目，不参加更新，也未标记为已解决。`:''}</p>
      <p class="dc-note dc-issue-help">问题默认勾选。取消某项，会把对应库从历史／最新更新及复检范围排除；同一库的其他问题一起暂不考虑。选择会保存到下次使用，可在“已排除”中重新勾选恢复。系统必检项保持勾选，不能忽略。</p>
      <p class="dc-note">历史与最新共用预分析，无需下载日期。先检查本地环境；已选星球需要网页通道时，会打开专用浏览器核验登录，需要时直接显示二维码。不检查各子库原件权限，不下载资料或调用模型；绿色仅代表运行环境就绪，执行仍逐文件检查；Pi 的文字回复不会直接改变状态。</p>
      <p class="dc-note">订阅／栏目核验：${esc(dateTime(result.scannedAt))} · 本地检查：${esc(dateTime(result.checkedAt))}（北京时间）。扫描超过 24 小时、本地检查超过 10 分钟需重新核验。</p>
      ${result.taskWarnings?.length?`<section class="dc-task-warnings"><h3>下载任务提醒 · 不影响环境颜色</h3>${result.taskWarnings.map(t=>`<p>${esc(t.code||t.status)} · ${esc(t.detail)}${t.repairAvailable?' 会员判断已修订，可在任务日志授权续传，或按原日期再次更新。':''}</p>`).join('')}</section>`:''}
      
      <div class="dc-readiness-list">${reasons.map(r=>`<article class="dc-readiness-item" data-attention-code="${esc(r.code||r.kind)}"><div class="dc-readiness-heading"><label class="dc-issue-choice"><input type="checkbox" data-issue-considered="${esc(r.issueId)}" data-provider="${id}" data-revision="${view.revision}" checked ${!r.canExclude||view.busy?'disabled':''} aria-label="考虑 ${esc(r.name||names[id])}：${esc(r.title)}" /><strong>${esc(r.name||names[id])}</strong></label><span>${esc(r.title||'下载前需处理')}</span></div><small>${r.canExclude?`取消将排除 ${r.affectedCollectionIds.length} 个对应库／栏目，且不下载它们。`:'系统必检项，不能忽略。'}</small>${r.collectionId?`<small>ID ${esc(r.collectionId)}</small>`:''}<p>${esc(r.detail||r.text)}</p><div class="dc-readiness-action"><b>需要你处理</b><p>${esc(r.action||'重新核验，不自动下载或扩大范围。')}</p></div></article>`).join('')}</div>
      ${result.excluded?.length?`<section class="dc-excluded-issues"><h3>已排除 · ${result.excluded.length} 项</h3><p class="dc-note">以下范围不参与更新。重新勾选只恢复范围，不代表权限通过，也不会自动下载。</p>${result.excluded.map(x=>`<article class="dc-excluded-item"><label class="dc-issue-choice"><input type="checkbox" data-issue-considered="${esc(x.issueId)}" data-provider="${id}" data-revision="${view.revision}" ${view.busy?'disabled':''} aria-label="恢复 ${esc(x.name)}" /><strong>${esc(x.name)}</strong><span>已排除，不下载</span></label><small>${esc(x.title)} · ${esc(dateTime(x.excludedAt))}</small><p>${esc(x.detail)}</p></article>`).join('')}</section>`:''}
      <div class="dc-readiness-controls">${result.canSelect?`<button type="button" class="dc-latest" data-source-select="${id}">查看／调整勾选</button>`:result.canConfigure?`<button type="button" class="dc-latest" data-source-update="${id}" data-kind="backfill">设置采集范围</button>`:''}${result.canScan?`<button type="button" class="dc-history" data-scan-source="${id}" ${view.busy?'disabled':''}>重新扫描订阅</button>`:''}<button type="button" class="dc-history" data-check-readiness="${id}" ${view.busy?'disabled':''}>检查本地环境</button></div>
      <div class="dc-dialog-footer"><span>预处理不启动整库下载或转写；样本复检单独确认。</span><button type="button" class="dc-text-button" data-readiness-prompts="${id}">预处理提示词 →</button></div></div>`);
    if(id==='ima'&&reasons.some(r=>r.code==='ima_accessibility_required'))document.querySelector('#source-dialog .dc-readiness-controls').insertAdjacentHTML('afterend','<div class="dc-readiness-controls"><button class="dc-history" data-permission-help="settings">打开辅助功能设置</button><button class="dc-history" data-permission-help="reveal">定位当前应用</button></div>');
  }
  function openPreflight(id){
    preflightText=null;
    dialog(names[id]+' · 预处理提示词',`<div id="preflight-prompt-options" data-provider="${id}"><p class="dc-note">历史／最新共用，不选日期，不分语音／非语音。只处理权限、登录、工具与未完成任务；需要扫码时直接打开登录页面，等你本人操作，不启动下载。</p><button class="dc-latest" data-generate-preflight="${id}">生成预处理提示词</button><div id="preflight-prompt-result" hidden><textarea class="dc-prompt-text" id="preflight-prompt-text" readonly></textarea><button class="dc-history" data-copy-preflight>复制预处理提示词</button></div></div>`);
  }
  async function openLLM(id) {
    readGlobalDates();
    pendingPrompts=null;promptTab='nonAudio';promptGeneration++;
    dialog(names[id]+' · LLM 提示词','<form id="llm-prompt-options" data-provider="'+id+'"><div class="dc-date-range"><label>任务类型<select name="kind"><option value="backfill" '+(rangeKind==='backfill'?'selected':'')+'>更新历史</option><option value="incremental" '+(rangeKind==='incremental'?'selected':'')+'>更新到最新</option></select></label>'+dateFields(rangeKind)+'</div><button type="submit" class="dc-latest">生成提示词</button></form><p class="dc-note">本地生成两份独立提示词，可分别交给不同模型。不调用模型、不自动执行；语音仍须等非语音阶段验收后再处理。</p><div id="llm-prompt-results" hidden><div class="dc-prompt-tabs" role="tablist" aria-label="提示词类型"><button type="button" id="prompt-tab-nonAudio" data-prompt-tab="nonAudio" role="tab" aria-controls="prompt-panel-nonAudio" aria-selected="true">非语音</button><button type="button" id="prompt-tab-audio" data-prompt-tab="audio" role="tab" aria-controls="prompt-panel-audio" aria-selected="false" tabindex="-1">语音</button></div><div id="prompt-panel-nonAudio" role="tabpanel" aria-labelledby="prompt-tab-nonAudio"><textarea id="llm-prompt-nonAudio" class="dc-prompt-text" readonly aria-label="非语音提示词"></textarea></div><div id="prompt-panel-audio" role="tabpanel" aria-labelledby="prompt-tab-audio" hidden><textarea id="llm-prompt-audio" class="dc-prompt-text" readonly aria-label="语音提示词"></textarea></div><button type="button" class="dc-history" data-copy-prompt>复制非语音提示词</button></div>');
  }
  function invalidatePrompts() {
    promptGeneration++;pendingPrompts=null;
    const results=document.querySelector('#llm-prompt-results');if(results)results.hidden=true;
    const submit=document.querySelector('#llm-prompt-options button[type="submit"]');if(submit)submit.disabled=false;
  }
  function showPromptTab(next) {
    if(!pendingPrompts||!['nonAudio','audio'].includes(next))return;
    promptTab=next;
    document.querySelectorAll('[data-prompt-tab]').forEach(b=>{const selected=b.dataset.promptTab===next;b.setAttribute('aria-selected',String(selected));b.tabIndex=selected?0:-1;});
    for(const kind of ['nonAudio','audio'])document.querySelector('#prompt-panel-'+kind).hidden=kind!==next;
    document.querySelector('[data-copy-prompt]').textContent=next==='audio'?'复制语音提示词':'复制非语音提示词';
  }
  async function generatePrompt(id,kind,range) {
    invalidatePrompts();const current=promptGeneration,form=document.querySelector('#llm-prompt-options'),submit=form.querySelector('button[type="submit"]');submit.disabled=true;
    try {
      const reports=await Promise.all((id==='bulk'?bulkScope:[id]).map(provider=>isLocalList(provider)?{prompts:{nonAudio:listPrompt(provider),audio:`${names[provider]}：自动采集和音频处理尚未接入。本轮不下载、不转写、不调用付费模型。`}}:window.irSystem.syncPrompt(provider,kind,range)));
      const result={prompts:Object.fromEntries(['nonAudio','audio'].map(type=>[type,reports.map(r=>r.prompts[type]).join('\n\n──────── 下一个已选信源（同一阶段依次执行，不并发写归档）────────\n\n')]))};
      if(current!==promptGeneration||!form.isConnected||!form.closest('dialog').open)return;
      pendingPrompts=result.prompts;
      for(const type of ['nonAudio','audio'])document.querySelector('#llm-prompt-'+type).value=pendingPrompts[type];
      document.querySelector('#llm-prompt-results').hidden=false;showPromptTab('nonAudio');
      dialogMessage('两份提示词已生成，可分别复制给不同模型。生成语音提示词不代表已获准下载或付费转写。');
    } finally {if(form.isConnected&&current===promptGeneration)submit.disabled=false;}
  }
  async function openCoverage(id) {
    const s = sources.find(s => s.id === id), selected = policies(id).filter(enabled), dir = directory(id);
    const gaps = jobsFor(id).filter(j => !j.recoveredBeforeDownload&&["failed", "partial", "needs_attention", "budget_paused", "stopped", "interrupted"].includes(j.status));
    dialog(`${s.name} · 信息状态`, `<div class="dc-coverage-metrics"><div><span>本地最新资料日期</span><strong id="coverage-latest">正在核对…</strong><small>信源整体索引，不等于已选范围齐全</small></div><div><span>最近目录扫描</span><strong>${esc(dateTime(dir?.scannedAt))}</strong><small>目录扫描不代表下载完成</small></div><div><span>需关注的任务</span><strong>${gaps.length}</strong><small>仅统计桌面任务，历史归档另见下方</small></div></div>
      <p class="dc-callout">${id === "ima" ? "IMA 日期覆盖无法可靠确认。目录检查完成不等于指定日期范围已完整归档。" : "最新条目的日期、检查位置、历史覆盖是三个不同指标。不根据一条新资料推断全量完整。"}</p>
      ${!s.ready ? `<p>已有搜索／读取能力，历史与增量采集待接入。不将搜索结果当成全量下载。</p>` : ""}
      <table class="dc-draft-table"><thead><tr><th>已选范围</th><th>方式</th><th>增量检查至</th><th>最近历史回补</th></tr></thead><tbody>${selected.map(p => { const m = view.watermarks?.[key(p)] || {}, h = m.history?.at(-1); return `<tr><td>${esc(p.name)}</td><td>${modes[p.mode]}</td><td>${p.mode === "once" ? "不参加日常增量" : id === "ima" ? m.through ? `目录检查目标 ${m.through}` : "未检查" : esc(m.through || "未检查")}</td><td>${h ? `${esc(h.start)} ～ ${esc(h.end)}` : "无桌面记录"}</td></tr>`; }).join("") || `<tr><td colspan="4">尚未选择子信源或保存整体采集范围。</td></tr>`}</tbody></table><p class="dc-note">已有 CLI 历史归档不会自动变成桌面完成记录；下方「本地资料与处理队列」仍可查看原索引。</p>`);
    const target = document.querySelector("#coverage-latest");
    try {
      const results = await Promise.all((id === "zsxq" ? ["zsxq", "zsxq_web"] : [id]).map(source => window.irSystem.archiveRequest("search", { source, kind: "record", limit: 1 })));
      const dates = results.flatMap(r => r.items.map(i => i.published_on)).filter(Boolean).sort(), count = results.reduce((n, r) => n + r.total, 0);
      if (target.isConnected) target.textContent = dates.at(-1) || (count ? "发布日期未知" : "暂无已索引主题");
    } catch { if (target.isConnected) target.textContent = "本地索引尚未就绪"; }
  }
  function openBudgets() {
    modalRevision = view.revision;
    dialog("本轮预算与执行设置", `<form id="source-budgets"><div class="dc-cli-fields">${Object.entries(budgetLabels).map(([k, label]) => `<label>${label}<input type="number" name="${k}" value="${view.settings.budgets[k]}" min="0" required /></label>`).join("")}<label>重叠回扫天数<input type="number" name="overlapDays" value="${view.settings.overlapDays}" min="1" max="30" required /></label><label>下载任务启动方式<select name="agentMode"><option value="fixed" ${view.settings.agentMode === "fixed" ? "selected" : ""}>固定流程（不调用模型）</option><option value="pi" ${view.settings.agentMode === "pi" ? "selected" : ""}>Pi 受限启动（需要额度）</option></select></label></div><p class="dc-note">下载由固定程序执行。整理助手在下方单独配置；预算耗尽会暂停，不自动拆批绕过上限。</p><div class="dc-dialog-footer"><span>保存不启动任务。</span><button class="dc-latest">保存预算</button></div></form>`);
  }
  async function checkDraftRevision() { const latest = await window.irSystem.syncGetState(); if (latest.revision !== modalRevision) throw new Error("sync_scope_changed"); return latest; }
  document.addEventListener('input',event=>{if(event.target.closest('#llm-prompt-options')){invalidatePrompts();dialogMessage('范围已变化，请重新生成提示词。');}});
  document.addEventListener('keydown',event=>{
    const b=event.target.closest('[data-prompt-tab]');if(!b||!pendingPrompts||!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
    event.preventDefault();const next=event.key==='Home'?'nonAudio':event.key==='End'?'audio':promptTab==='nonAudio'?'audio':'nonAudio';showPromptTab(next);document.querySelector('[data-prompt-tab="'+next+'"]').focus();
  });
  document.addEventListener("change", async event => {
    const el = event.target;
    if(el.name==='category'&&el.closest('#wisburg-selection'))return updateWisburgCount();
    if(el.matches('[data-bulk-source]')){el.checked?bulkSources.add(el.dataset.bulkSource):bulkSources.delete(el.dataset.bulkSource);localStorage.setItem('ir-source-selection',JSON.stringify([...bulkSources]));renderBulk();return;}
    if(el.matches('[data-issue-considered]')){
      const id=el.dataset.provider,considered=el.checked;
      document.querySelectorAll('#source-dialog [data-issue-considered]').forEach(input=>input.disabled=true);
      try{view=await window.irSystem.syncSetIssueConsidered({provider:id,issueId:el.dataset.issueConsidered,considered,revision:Number(el.dataset.revision)});renderRows();openReadiness(id);dialogMessage(considered?'已恢复对应范围，按实际证据重新判断；未启动下载。':'已排除对应范围，历史／最新更新及复检都会跳过；未启动下载。');}
      catch(e){await refresh();openReadiness(id);dialogMessage(friendly(e));}
      return;
    }
    if(el.id==='global-start'||el.id==='global-end')el.dataset.dirty='true';
    if(el.name==='kind'&&el.closest('#llm-prompt-options')){const r=rangeFor(el.value);el.form.elements.start.value=IRDates.compact(r.start);el.form.elements.end.value=IRDates.compact(r.end);invalidatePrompts();}
  });
  document.addEventListener("click", async event => {
    const b = event.target.closest("button"); if (!b || !b.closest("#sync-center")) return;
    try {
      if(b.hasAttribute('data-local-list')||b.hasAttribute('data-list-refresh')){await refresh();return openLocalList(b.dataset.localList||b.dataset.listRefresh);}
      if(b.hasAttribute('data-list-prompt')){const id=b.dataset.listPrompt;dialog(names[id]+' · 清单管理提示词',`<textarea class="dc-prompt-text" readonly>${esc(listPrompt(id))}</textarea><button class="dc-history" data-list-copy="${id}">复制提示词</button>`);return;}
      if(b.hasAttribute('data-list-copy')){await window.irSystem.copyText(listPrompt(b.dataset.listCopy));return dialogMessage('已复制；未调用模型或修改清单。');}
      const localId=b.dataset.sourceLlm||b.dataset.sourceReadiness||b.dataset.sourceCoverage;
      if(isLocalList(localId)){await refresh();return openLocalList(localId);}
      if(b.hasAttribute('data-wisburg-select')){document.querySelectorAll('#wisburg-selection [name="category"]').forEach(input=>input.checked=b.dataset.wisburgSelect==='all');updateWisburgCount();return;}
      if(b.hasAttribute('data-choice')){const p=draft[Number(b.dataset.choice)];p.mode=b.dataset.value;p.firstDate ||= IRDates.defaults('backfill').start;document.querySelector('#source-draft-rows').innerHTML=draftRows();return;}
      if(b.hasAttribute('data-bulk-action')){
        const ids=requireBulk(),action=b.dataset.bulkAction;
        if(action==='verify')return await verifyBulk(ids);
        if(action==='llm'){bulkScope=[...ids];names.bulk=bulkNames(ids);return openLLM('bulk');}
        return openBulkUpdate(ids,action);
      }
      if(b.hasAttribute('data-bulk-repair')){
        preflightText=(await Promise.all(bulkScope.map(id=>isLocalList(id)?listPrompt(id):window.irSystem.syncPreflightPrompt(id)))).join('\n\n──────── 下一个信源；仅核验修复，不下载 ────────\n\n');
        const area=document.querySelector('#bulk-repair-text');area.value=preflightText;area.hidden=false;document.querySelector('#bulk-repair-copy').hidden=false;return;
      }
      if(b.hasAttribute('data-permission-help')){await window.irSystem.syncPermissionHelp(b.dataset.permissionHelp);return dialogMessage('已打开对应位置；请由你本人确认当前版本的系统授权。未下载资料。');}
      if(b.hasAttribute('data-range-kind')){readGlobalDates();rangeKind=b.dataset.rangeKind;renderDates();return;}
      if(b.hasAttribute('data-range-reset')){delete ranges[rangeKind];renderDates();return;}
      if(b.hasAttribute('data-source-llm'))return await openAssistance(b.dataset.sourceLlm);
      if(b.hasAttribute('data-source-readiness'))return await checkReadiness(b.dataset.sourceReadiness);
      if(b.hasAttribute('data-check-readiness'))return await checkReadiness(b.dataset.checkReadiness,true);
      if(b.hasAttribute('data-readiness-prompts'))return openPreflight(b.dataset.readinessPrompts);
      if(b.hasAttribute('data-generate-preflight')){preflightText=await window.irSystem.syncPreflightPrompt(b.dataset.generatePreflight);const field=document.querySelector('#preflight-prompt-text');if(field){field.value=preflightText;document.querySelector('#preflight-prompt-result').hidden=false;}return;}
      if(b.hasAttribute('data-copy-preflight')){if(preflightText)await window.irSystem.copyText(preflightText);return dialogMessage('预处理提示词已复制，未执行任务。');}
      if(b.hasAttribute('data-prompt-tab'))return showPromptTab(b.dataset.promptTab);
      if(b.hasAttribute('data-copy-prompt')){if(!pendingPrompts)return;await window.irSystem.copyText(pendingPrompts[promptTab]);return dialogMessage((promptTab==='audio'?'语音':'非语音')+'提示词已复制，没有执行或发送给模型。');}
      if (b.hasAttribute("data-dialog-close")) return closeDialog();
      if (b.hasAttribute("data-source-select")) return openSelection(b.dataset.sourceSelect);
      if (b.hasAttribute("data-source-update")) return openUpdate(b.dataset.sourceUpdate, b.dataset.kind);
      if(b.hasAttribute('data-update-probe')){
        const r=await window.irSystem.syncProbeIma({collectionId:b.dataset.updateProbe});await refresh();renderImaUpdateRoutes();
        return dialogMessage(r.status==='cancelled'?'已取消核验，未联网、未启动下载。':'正在核验这一个库；通过后列表会自动刷新，不会自动启动下载。');
      }
      if (b.hasAttribute("data-source-coverage")) return await openCoverage(b.dataset.sourceCoverage);
      if (b.hasAttribute("data-open-budgets")) return openBudgets();
      if (b.hasAttribute("data-console-tab")) return showConsoleTab(b.dataset.consoleTab);
      if (b.hasAttribute("data-scan-source")) { const r = await window.irSystem.syncScan([b.dataset.scanSource]); log(r.status === "cancelled" ? "已取消扫描。" : "正在扫描订阅，未启动下载。"); dialogMessage("扫描后新条目会进入待选择；不会自动下载。"); return; }
      if(b.hasAttribute('data-ima-evidence'))return openImaEvidence(b.dataset.imaEvidence);
      if(b.hasAttribute('data-evidence-back'))return openSelection('ima',true);
      if(b.hasAttribute('data-probe-ima-library')){
        const selection={collectionId:b.dataset.probeImaLibrary,...(b.hasAttribute('data-probe-restart')?{restartSearch:true}:{})};
        const r=await window.irSystem.syncProbeIma(selection);await refresh();openImaEvidence(selection.collectionId);return dialogMessage(r.status==='cancelled'?'已取消复检，未联网。':'正在核验这个库的 API 样本；不改变下载勾选，不启动历史或增量下载。');
      }
      if (b.hasAttribute("data-sync-resume")) { const r = await window.irSystem.syncApprove("incremental", b.dataset.syncResume); log(r.status === "cancelled" ? "已取消续传。" : "已提交原范围续传。"); return await refresh(); }
      if (b.hasAttribute('data-sync-resume-visible')) {const r=await window.irSystem.syncApprove('incremental',b.dataset.syncResumeVisible,{browserMode:'visible'});log(r.status==='cancelled'?'已取消，未打开浏览器。':'已授权本任务使用可见浏览器按原断点续传。');return await refresh();}
      if (b.hasAttribute("data-sync-stop")) { await window.irSystem.syncStop(b.dataset.syncStop); log("已请求停止，将保存当前进度。"); return await refresh(); }
    } catch (e) { if (document.querySelector("#source-dialog")?.open) dialogMessage(friendly(e)); log(friendly(e)); }
  });
  document.addEventListener("submit", async event => {
    const form = event.target; if (!form.closest("#sync-center")) return;
    event.preventDefault(); const fields = new FormData(form);
    if(form.id==='source-update'||form.id==='wisburg-selection'){
      if(form.dataset.submitting==='yes')return;
      form.dataset.submitting='yes';
      form.querySelectorAll('button[type="submit"]').forEach(button=>button.disabled=true);
    }
    try {
      if(form.id==='wisburg-selection'){
        const latest=await checkDraftRevision(),selected=fields.getAll('category');
        if(selected.some(value=>!categories.includes(value)))throw new Error('invalid_category');
        const existing=new Map(latest.settings.policies.filter(p=>p.provider==='wisburg').map(p=>[p.collectionId,p]));
        const rows=categories.map(collectionId=>{const old=existing.get(collectionId);return {provider:'wisburg',collectionId,name:categoryNames[collectionId],mode:selected.includes(collectionId)?'incremental':'off',firstDate:old?.firstDate||IRDates.defaults('backfill').start};});
        await window.irSystem.syncSaveSettings({...latest.settings,policies:[...latest.settings.policies.filter(p=>p.provider!=='wisburg'),...rows]});
        closeDialog();await refresh();return log('智堡栏目选择已保存，历史与最新更新共用；未启动下载。');
      }
      if (form.id === "source-selection") {
        const latest = await checkDraftRevision(); view = await window.irSystem.syncSaveSettings({ ...latest.settings, policies: [...latest.settings.policies.filter(p => p.provider !== modalSource), ...draft] }); closeDialog(); renderRows(); return log(`${names[modalSource]} 的选择已保存，未启动下载。`);
      }
      if (form.id === "wisburg-mode") {
        const latest = await checkDraftRevision(); view = await window.irSystem.syncSaveSettings({ ...latest.settings, policies: latest.settings.policies.map(p => p.provider === "wisburg" && (enabled(p) || fields.has("enableInactive")) ? { ...p, mode: fields.get("mode") } : p) }); closeDialog(); renderRows(); return log("智堡采集方式已保存，未启动下载。");
      }
      if(form.id==='bulk-update'){
        await checkDraftRevision();
        const kind=form.dataset.kind,selection={providers:[...bulkScope],start:IRDates.parse(fields.get('start')),end:IRDates.parse(fields.get('end'))};
        ranges[kind]={start:selection.start,end:selection.end};renderDates();
        const result=await window.irSystem.syncApprove(kind,null,selection);closeDialog();await refresh();return log(result.status==='cancelled'?'已取消，未启动下载。':'合并更新任务已提交；以下方实际进度为准。');
      }
      if(form.id==='llm-prompt-options') {
        const range={start:IRDates.parse(fields.get('start')),end:IRDates.parse(fields.get('end'))};
        return await generatePrompt(form.dataset.provider,fields.get('kind'),range);
      }
      if(form.id==='source-update') {
        const id=form.dataset.provider,kind=form.dataset.kind,selection={provider:id,start:IRDates.parse(fields.get('start')),end:IRDates.parse(fields.get('end'))};
        if(selection.start>selection.end||selection.end>today())throw new Error('invalid_history_range');
        const latest=await checkDraftRevision();
        if(id==='wisburg'){
          selection.collectionIds=latest.settings.policies.filter(p=>p.provider===id&&p.mode==='incremental').map(p=>p.collectionId);
          if(!selection.collectionIds.length)throw new Error('no_selected_collections');
        }
        if(id==='ima'){
          const selected=latest.settings.policies.filter(p=>p.provider==='ima'&&p.mode==='incremental');
          const ready=selected.filter(p=>latest.updateRoutes?.[key(p)]?.ready);
          if(ready.length!==selected.length){
            if(!event.submitter?.hasAttribute('data-ready-only'))throw new Error('sync_scope_changed');
            if(!ready.length)throw new Error('no_selected_collections');
            selection.collectionIds=ready.map(p=>p.collectionId);
          }
        }
        ranges[kind]={start:selection.start,end:selection.end};rangeKind=kind;renderDates();
        if(form.dataset.initialize==='yes'){
          view=await window.irSystem.syncSaveSettings({...latest.settings,policies:[...latest.settings.policies,...categories.map(collectionId=>({provider:id,collectionId,name:collectionId,mode:'incremental',firstDate:selection.start}))]});
        }
        const r=await window.irSystem.syncApprove(kind,null,selection);closeDialog();await refresh();return log(r.status==='cancelled'?'已取消，未启动下载。':names[id]+' 任务已提交，请以下方程序状态为准。');
      }
      if (form.id === "source-budgets") {
        const latest = await checkDraftRevision(); view = await window.irSystem.syncSaveSettings({ ...latest.settings, agentMode: fields.get("agentMode"), overlapDays: Number(fields.get("overlapDays")), budgets: Object.fromEntries(Object.keys(budgetLabels).map(k => [k, Number(fields.get(k))])) }); closeDialog(); return log("本轮预算已保存，未启动任务。");
      }
    } catch (e) { if (document.querySelector("#source-dialog")?.open) dialogMessage(friendly(e)); log(friendly(e)); }
    finally {
      if((form.id==='source-update'||form.id==='wisburg-selection')&&form.isConnected){
        delete form.dataset.submitting;
        form.querySelectorAll('button[type="submit"]').forEach(button=>button.disabled=false);
        if(form.id==='wisburg-selection')updateWisburgCount();
        if(form.dataset.provider==='ima')renderImaUpdateRoutes();
      }
    }
  });
})();
