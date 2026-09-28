const state = {
  bootstrap: null,
  activeModule: "overview",
  activeChild: null,
  busy: false,
};
const archiveState = { query: "", source: "", kind: "", start: "", end: "", offset: 0, status: null, mutating: false, stop: false };
let readerRequest = 0;

const workspace = document.querySelector("#workspace");
const navigation = document.querySelector("#main-navigation");
const commandDialog = document.querySelector("#command-palette");
const commandInput = document.querySelector("#command-input");
const commandResults = document.querySelector("#command-results");

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function statusClass(status) {
  return `status-${String(status || "unavailable").replace(/[^a-z-]/gi, "")}`;
}

function statusBadge(status) {
  return `<span class="status-badge ${statusClass(status)}">${escapeHtml(status || "unknown")}</span>`;
}

function activeProviderStatus() {
  return state.bootstrap?.providers?.find((item) => item.provider === state.bootstrap.activeProvider);
}

function moduleStatus(moduleId) {
  return activeProviderStatus()?.modules?.find((item) => item.id === moduleId)?.status || "planned";
}

function startClock() {
  const target = document.querySelector("#world-clocks");
  const update = () => {
    const now = new Date();
    target.innerHTML = [['北京','Asia/Shanghai'],['东京','Asia/Tokyo'],['伦敦','Europe/London'],['纽约','America/New_York'],['洛杉矶','America/Los_Angeles']].map(([name,timeZone])=>{
      const time = new Intl.DateTimeFormat('en-GB',{timeZone,hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}).format(now);
      const date = new Intl.DateTimeFormat('en-CA',{timeZone,year:'numeric',month:'2-digit',day:'2-digit'}).format(now);
      return `<div class="session-clock" title="${date} · ${timeZone}"><span>${name}</span><time>${time}</time><small>${date.slice(5)}</small></div>`;
    }).join('');
  };
  update();
  window.setInterval(update, 1000);
}

async function initialize() {
  try {
    state.bootstrap = await window.irSystem.getBootstrap();
    renderChrome();
    await showModule("overview");
  } catch (error) {
    workspace.innerHTML = errorPanel("IR System 启动失败", error.message);
    setConnection("error", "STARTUP ERROR");
  }
}

function renderChrome() {
  renderNavigation();
  updateFooter();
  const active = activeProviderStatus();
  setConnection(active?.status === "ready" ? "ready" : "error", `${state.bootstrap.activeProvider} / ${active?.status || "unknown"}`);
}

function renderNavigation() {
  const labels = {
    workspace: "Workspace",
    research: "Research",
    markets: "Markets",
    entities: "Entities",
    intelligence: "Intelligence",
    personal: "Personal",
    system: "System",
  };
  let previousGroup = "";
  navigation.innerHTML = state.bootstrap.navigation.map((item) => {
    const group = item.group !== previousGroup
      ? `<div class="nav-group-label">${escapeHtml(labels[item.group] || item.group)}</div>`
      : "";
    previousGroup = item.group;
    const status = moduleStatus(item.id);
    return `${group}<button class="nav-item ${item.id === state.activeModule ? "active" : ""}" type="button" data-module="${escapeHtml(item.id)}">
      <span class="nav-code">${escapeHtml(item.code)}</span>
      <span>${escapeHtml(item.label)}</span>
      <span class="nav-readiness ${escapeHtml(status)}" title="${escapeHtml(status)}"></span>
    </button>`;
  }).join("");
}

function updateFooter() {
  const dashboard = state.bootstrap.dashboard;
  document.querySelector("#footer-provider").textContent = `PROVIDER: ${state.bootstrap.activeProvider.toUpperCase()}`;
  document.querySelector("#footer-mode").textContent = `MODE: ${(dashboard.dataMode || "unknown").toUpperCase()}`;
}

function setConnection(kind, text) {
  const element = document.querySelector("#connection-status");
  if (!element) return;
  element.className = `connection-status ${kind}`;
  element.innerHTML = `<span class="status-dot"></span>${escapeHtml(String(text).toUpperCase())}`;
}

async function showModule(moduleId, childId = null) {
  if (state.busy) return;
  state.busy = true;
  state.activeModule = moduleId;
  state.activeChild = childId;
  renderNavigation();
  workspace.innerHTML = `<section class="loading-state"><span class="loading-mark">IR</span><p>正在读取 ${escapeHtml(moduleId)}…</p></section>`;

  try {
    if (moduleId === "overview") renderOverview(state.bootstrap.dashboard);
    else if (moduleId === "data") await renderDataCenter();
    else if (moduleId === "research" && (!childId || childId === "research-library")) await renderLibrary();
    else if (moduleId === "companies" && window.renderCompanies) window.renderCompanies(await window.irSystem.getModuleData(moduleId), childId, workspaceHeading);
    else if (moduleId === "eq" && window.renderEquities) window.renderEquities(await window.irSystem.getModuleData(moduleId), childId, workspaceHeading, state.bootstrap.navigation.find((item) => item.id === "eq")?.children);
    else renderModule(await window.irSystem.getModuleData(moduleId));
    workspace.focus();
  } catch (error) {
    workspace.innerHTML = errorPanel("页面加载失败", error.message);
  } finally {
    state.busy = false;
  }
}

function workspaceHeading(section, title, mode, asOf) {
  const connected = mode === "connected";
  return `<section class="workspace-heading">
    <div><div class="eyebrow">WORKSPACE / ${escapeHtml(section)}</div><h1>${escapeHtml(title)}</h1></div>
    <div class="heading-actions"><span class="mode-chip ${connected ? "connected" : ""}">${escapeHtml(mode || "unknown")}</span><span>${escapeHtml(asOf || "NO DATA")}</span></div>
  </section>`;
}

function renderOverview(dashboard) {
  const markets = dashboard.markets || [];
  const marketMarkup = markets.length
    ? `<section class="ticker-grid">${markets.map(renderTicker).join("")}</section>`
    : `<section class="panel empty-panel"><strong>尚未映射实时市场快照</strong><p>数据提供方已经连接，但当前能力目录还不能生成统一的跨资产首页。请在 Data Center 查看各模块覆盖。</p><button class="secondary-button" data-module="data">OPEN DATA CENTER</button></section>`;
  const pulse = dashboard.pulse || [];
  const research = dashboard.research || [];

  workspace.innerHTML = `${workspaceHeading("OVERVIEW", "Global Research Monitor", dashboard.dataMode, dashboard.asOf)}
    ${marketMarkup}
    <section class="main-grid">
      <article class="panel">
        <div class="panel-heading"><div><div class="panel-kicker">ARCHITECTURE</div><h2>Local Research Flow</h2></div><span class="panel-time">PROTOCOL V1</span></div>
        <div class="system-map">
          <div class="system-map-step"><small>01</small><strong>Local Sources</strong><span>数据库、文档、研究平台与公开来源</span></div>
          <div class="system-map-step"><small>02</small><strong>Provider Adapter</strong><span>把外部能力映射到稳定协议</span></div>
          <div class="system-map-step"><small>03</small><strong>IR System</strong><span>实体、工作区、自选与本地状态</span></div>
          <div class="system-map-step"><small>04</small><strong>Evidence</strong><span>带时间、来源、覆盖和诊断的结论</span></div>
        </div>
      </article>
      <article class="panel">
        <div class="panel-heading"><div><div class="panel-kicker">SIGNALS</div><h2>Market Pulse</h2></div><span class="panel-time">${escapeHtml(dashboard.dataMode)}</span></div>
        ${pulse.length ? `<div class="signal-list">${pulse.map(renderSignal).join("")}</div>` : emptyBody("尚无可比较的跨资产信号", "连接的数据源需要提供经过映射的市场状态指标。")}
      </article>
      <article class="panel">
        <div class="panel-heading"><div><div class="panel-kicker">MODULES</div><h2>Research Surfaces</h2></div></div>
        <div class="panel-body section-grid">${state.bootstrap.navigation.filter((item) => ["macro","eq","fi","fx","comdty","companies"].includes(item.id)).map((item, index) => renderSection(item, index)).join("")}</div>
      </article>
      <article class="panel">
        <div class="panel-heading"><div><div class="panel-kicker">RESEARCH QUEUE</div><h2>Latest Evidence</h2></div></div>
        ${research.length ? `<div class="research-list">${research.map(renderResearch).join("")}</div>` : emptyBody("研究队列为空", "后续由 Research Provider 提供资料搜索、阅读与证据状态。")}
      </article>
    </section>`;
}

function renderTicker(item, index) {
  const isRates = item.market === "RATES";
  const change = Number(isRates ? item.changeBp : item.changePct) || 0;
  const direction = change > 0 ? "positive" : change < 0 ? "negative" : "neutral";
  const sign = change > 0 ? "+" : "";
  const changeLabel = isRates
    ? `${sign}${change.toFixed(1)} bp`
    : `${sign}${change.toFixed(2)}%`;
  const bars = [34, 47, 39, 58, 52, 71, 64, 78, 69, 86, 75, 92]
    .map((height, barIndex) => `<span style="height:${direction === "negative" ? 110 - height : height - (index * 2 + barIndex % 3)}%"></span>`).join("");
  return `<article class="ticker-card">
    <div class="ticker-meta"><span>${escapeHtml(item.market)}</span><span>${escapeHtml(item.name)}</span></div>
    <div class="ticker-value">${escapeHtml(item.value)}</div>
    <div class="ticker-change ${direction}">${escapeHtml(changeLabel)}</div>
    <div class="sparkline" aria-label="示例趋势">${bars}</div>
  </article>`;
}

function renderSignal(item) {
  const score = Math.max(0, Math.min(100, Number(item.score || 0)));
  return `<div class="signal-row"><div><span class="signal-name">${escapeHtml(item.label)}</span><span class="signal-note">${escapeHtml(item.detail)}</span></div><div class="meter"><span style="width:${score}%"></span></div><span class="signal-score">${score}</span></div>`;
}

function renderResearch(item) {
  return `<div class="research-item"><span class="research-type">${escapeHtml(item.type)}</span><span class="research-copy"><strong>${escapeHtml(item.title)}</strong><small>${escapeHtml(item.subtitle)}</small></span><span class="research-time">${escapeHtml(item.time)}</span></div>`;
}

function renderSection(item, index) {
  return `<button class="section-card" type="button" data-module="${escapeHtml(item.id)}"><span class="section-number">${String(index + 1).padStart(2,"0")}</span><strong>${escapeHtml(item.label)}</strong><span>${escapeHtml(moduleStatus(item.id))} coverage</span></button>`;
}

function renderModule(data) {
  const definition = state.bootstrap.navigation.find((item) => item.id === data.moduleId);
  const sections = definition?.children || data.sections || [];
  const activeChild = sections.find((item) => item.id === state.activeChild);
  const title = activeChild ? `${definition.label} / ${activeChild.label}` : data.title;
  workspace.innerHTML = `${workspaceHeading(data.moduleId, title, data.dataMode, data.asOf)}
    <section class="module-intro"><div><div class="panel-kicker">${escapeHtml(definition?.group || "MODULE")}</div><h2>${escapeHtml(title)}</h2><p>${escapeHtml(data.summary)}</p></div>${statusBadge(data.status)}</section>
    ${sections.length ? `<section class="section-grid">${sections.map((item, index) => `<button class="section-card" type="button" data-child="${escapeHtml(item.id)}" data-parent="${escapeHtml(data.moduleId)}"><span class="section-number">${String(index + 1).padStart(2,"0")}</span><strong>${escapeHtml(item.label)}</strong><span>${item.id === state.activeChild ? "Current view" : "Open workspace"}</span></button>`).join("")}</section>` : `<section class="panel empty-panel"><strong>等待兼容的数据能力</strong><p>该模块已进入平台结构，但当前提供方尚未返回可展示的数据集。应用会保持空状态，不生成替代数字。</p></section>`}
    ${renderDiagnostics(data.diagnostics)}`;
}

async function renderDataCenter() {
  const active = activeProviderStatus();
  const config = state.bootstrap.providerConfig || {};
  workspace.innerHTML = `
    <details class="dc-engine" id="engine-settings"><summary><span class="dc-engine-state"><i class="dc-mini-dot ${active?.status === "ready" ? "online" : ""}"></i>数据引擎 · ${active?.status === "ready" ? "已连接" : "待配置"}</span><span>ir_search ／ 连接设置 ⌄</span></summary><p class="dc-note">这里只配置本机连接。连接成功不代表各信源的登录和下载权限已通过验证。</p>
    <form id="provider-config-form" class="config-form">
      <div class="field"><label for="python-command">Python 程序</label><input id="python-command" name="pythonCommand" value="${escapeHtml(config.pythonCommand || "python3")}" /></div>
      <div class="field"><label for="ir-search-path">ir_search 源码目录（安装 SDK 后可留空）</label><input id="ir-search-path" name="irSearchPath" value="${escapeHtml(config.irSearchPath || "")}" placeholder="使用已安装的 SDK，或填写源码路径" /></div>
      <div class="field"><label for="archive-root">本地归档目录（原件保留，同步另存新增）</label><input id="archive-root" name="archiveRoot" value="${escapeHtml(config.archiveRoot || "")}" placeholder="/absolute/path/to/ir_archive" /></div>
      <button class="primary-button" type="submit">保存并检查连接</button>
    </form><button class="dc-text-button" data-probe-provider="ir_search">重新检查连接</button>
    <details class="dc-diagnostics"><summary>能力目录与诊断</summary><table class="capability-table"><thead><tr><th>模块</th><th>状态</th><th>能力范围</th></tr></thead><tbody>${(active?.modules || []).map(item => `<tr><td>${escapeHtml(item.label || item.id)}</td><td>${statusBadge(item.status)}</td><td>${escapeHtml(item.summary || "")}</td></tr>`).join("")}</tbody></table>${renderDiagnostics(active?.diagnostics)}</details></details>
    <section id="sync-center"></section>
    <details class="dc-archive"><summary><span>本地资料与处理队列</span><span class="dc-faint">索引 · 解析 · 音频待办</span></summary><section id="archive-center"></section></details>`;
  const target = document.querySelector("#archive-center");
  if (window.renderSyncCenter) await window.renderSyncCenter();
  if (!config.archiveRoot) {
    target.innerHTML = emptyBody("尚未选择本地归档", "保存上面的归档目录后，可查看下载、解析和索引状态。不会自动扫描在线订阅或下载文件。");
    return;
  }
  try {
    const data = await window.irSystem.archiveRequest("status");
    archiveState.status = data;
    window.updateSourceArchiveStatus?.(data);
    target.innerHTML = renderArchiveStatus(data, true);
    const audio = await window.irSystem.archiveRequest("audio_list");
    target.insertAdjacentHTML("beforeend", `<article class="panel archive-status"><div class="panel-heading"><h2>独立音频队列</h2><button class="secondary-button" data-audio-library>查看音频</button></div><div class="panel-body"><p>音频引用 ${escapeHtml(audio.total)} · 已下载 ${escapeHtml(audio.counts.downloaded)} · 待下载 ${escapeHtml(audio.counts.needs_download)} · 已完整转写 ${escapeHtml(audio.counts.transcribed)}</p><p class="archive-warning">普通文档解析自动跳过音频。火山转写需要显式授权和时长预算，不会因浏览或搜索自动收费。新下载仍由原归档器在扫描订阅和权限后处理。</p></div></article>`);
  } catch (error) { target.innerHTML = errorPanel("归档暂不可用", error.message); }
}

const PARSE_LABELS = { pending: "已落盘·待解析", parsed: "已解析", needs_ocr: "需要 OCR·未上传", not_downloaded: "未下载", metadata_only: "仅元数据", source_text: "已有来源文本", invalid_document: "文档无效", unsupported_format: "暂不支持", parser_missing: "缺解析器", parse_failed: "解析失败", timeout: "解析超时" };

Object.assign(PARSE_LABELS, { audio_pending: "音频·待单独转写", audio_partial: "音频·部分转写", audio_transcribed: "音频·完整机器转写", audio_failed: "音频·转写失败" });

function renderArchiveStatus(data, controls = false) {
  const rows = data.states || [];
  const jobs = data.web_jobs || [];
  const snapshot = data.subscription_snapshot || {};
  return `<article class="panel archive-status"><div class="panel-heading"><div><div class="panel-kicker">LOCAL DATA / 来源快照，不是在线体检</div><h2>资料与采集中心</h2></div>${statusBadge(data.status)}</div>
    <div class="panel-body"><div class="archive-metrics"><div><strong>${escapeHtml(data.documents ?? "—")}</strong><span>索引条目（主题＋附件）</span></div><div><strong>${escapeHtml(data.unknown_dates ?? "—")}</strong><span>发布日期未知</span></div><div><strong>${escapeHtml(snapshot.summary?.total ?? "—")}</strong><span>订阅快照中的星球</span></div></div>
    <p>索引更新：${escapeHtml(data.indexed_at || "尚未建立")} · 订阅扫描：${escapeHtml(snapshot.scanned_at || "无快照")}</p>
    <p class="archive-warning">下载成功 ≠ 解析完整 ≠ 全年覆盖。图片和扫描页未自动 OCR；摘要保持摘要标记。原文件不会被 Markdown 替换。</p>
    <div class="archive-state-list">${rows.map(r => `<span class="archive-state">${r.kind === "record" ? "主题" : "附件"} / ${escapeHtml(PARSE_LABELS[r.state] || r.state)} <b>${escapeHtml(r.count)}</b></span>`).join("")}</div>
    ${controls ? `<div class="provider-actions"><button class="primary-button" data-archive-action="index">更新本地索引</button><button class="secondary-button" data-archive-action="parse">解析下一批（最多20份）</button><button class="secondary-button" data-archive-action="stop">完成当前文件后停止</button><button class="secondary-button" data-module="research">打开资料库</button></div><p id="archive-progress" role="status" aria-live="polite"></p>` : ""}
    ${jobs.length ? `<details><summary>网页归档任务快照（${jobs.length}）</summary><table class="capability-table"><thead><tr><th>星球 / 日期</th><th>已处理 / 发现</th><th>最早发现</th><th>日期下限</th></tr></thead><tbody>${jobs.map(j => `<tr><td>${escapeHtml(j.job?.group_name)}<br>${escapeHtml(j.job?.start)} ～ ${escapeHtml(j.job?.end)}</td><td>${escapeHtml(j.topics_processed_total ?? "—")} / ${escapeHtml(j.topics_discovered ?? "—")}</td><td>${escapeHtml(j.oldest_visible_date || "未知")}</td><td>${j.reached_date_floor ? "已到达，非完整性证明" : "未到达"}</td></tr>`).join("")}</tbody></table></details>` : ""}
    </div></article>`;
}

async function renderLibrary() {
  workspace.innerHTML = `${workspaceHeading("RESEARCH", "本地资料库", "local", "OFFLINE SNAPSHOT")}
    <section class="module-intro"><div><h2>从原件到证据</h2><p>按关键词、公司或行业名称做字面搜索；未进行自动实体识别。日期是来源记录日期，附件继承帖子日期，不推断研报日期。</p></div><button class="secondary-button" data-module="data">资料与采集状态</button></section>
    <div id="library-main">正在读取本地索引…</div>`;
  const target = document.querySelector("#library-main");
  if (!state.bootstrap.providerConfig.archiveRoot) {
    target.innerHTML = emptyBody("先选择本地归档目录", "进入 Data Center 配置归档目录与 ir_search。资料库不会展示 Demo 资料，也不会自动调用网络信源。");
    return;
  }
  const status = await window.irSystem.archiveRequest("status");
  archiveState.status = status;
  if (status.status !== "ready") { target.innerHTML = emptyBody("尚未建立索引", "在 Data Center 点击“更新本地索引”。此操作只创建派生数据，不改写下载原件。"); return; }
  const filters = { query: archiveState.query, source: archiveState.source, kind: archiveState.kind, offset: archiveState.offset, limit: 30 };
  if (archiveState.start || archiveState.end) Object.assign(filters, { start: archiveState.start || null, end: archiveState.end || null });
  const result = await window.irSystem.archiveRequest("search", filters);
  target.innerHTML = `<form id="archive-search-form" class="archive-search">
    <div class="field"><label for="archive-query">关键词 / 公司 / 行业</label><input id="archive-query" name="query" value="${escapeHtml(archiveState.query)}" placeholder="如 宏观 / 半导体 / 英伟达" /></div>
    <div class="field"><label for="archive-source">来源</label><select id="archive-source" name="source"><option value="">全部本地来源</option>${(status.sources || []).map(s => `<option value="${escapeHtml(s.source)}" ${archiveState.source === s.source ? "selected" : ""}>${escapeHtml(s.source)}</option>`).join("")}</select></div>
    <div class="field"><label for="archive-kind">类型</label><select id="archive-kind" name="kind"><option value="">全部</option><option value="record" ${archiveState.kind === "record" ? "selected" : ""}>主题 / 文章</option><option value="attachment" ${archiveState.kind === "attachment" ? "selected" : ""}>附件</option><option value="audio" ${archiveState.kind === "audio" ? "selected" : ""}>音频</option></select></div>
    <div class="field"><label for="archive-start">开始日期</label><input id="archive-start" name="start" type="date" value="${escapeHtml(archiveState.start)}" /></div><div class="field"><label for="archive-end">结束日期</label><input id="archive-end" name="end" type="date" value="${escapeHtml(archiveState.end)}" /></div><button class="primary-button">搜索</button>
    </form><p class="archive-warning">日期筛选须成对填写；筛选时排除未知日期。不筛日期可看到 IMA 等未知日期资料。</p>
    <div class="archive-toolbar"><span>匹配 ${escapeHtml(result.total)} 条 · 第 ${Math.floor(archiveState.offset/30)+1} 页</span><button class="secondary-button" data-archive-page="prev" ${archiveState.offset ? "" : "disabled"}>上一页</button><button class="secondary-button" data-archive-page="next" ${result.has_more ? "" : "disabled"}>下一页</button></div>
    <section class="library-grid"><div class="panel archive-results">${result.items.map(r => `<button class="archive-result" data-archive-read="${escapeHtml(r.id)}"><span class="archive-result-meta">${escapeHtml(r.source)} · ${escapeHtml(r.published_on || "日期未知")} · ${r.kind === "attachment" ? "附件" : "主题"}</span><strong>${escapeHtml(r.title)}</strong><span>${escapeHtml(r.snippet || "暂无可索引正文")}</span><small>${escapeHtml(r.text_scope)} / ${escapeHtml(PARSE_LABELS[r.parse_status] || r.parse_status)}</small></button>`).join("") || emptyBody("没有匹配结果", "尝试缩短关键词或取消日期筛选。")}</div><article class="panel archive-reader" id="archive-reader"><div class="empty-panel">选择一条资料阅读。附件原件仅定位，不自动执行文件。</div></article></section>`;
}

async function readArchiveDocument(id, offset = 0) {
  const request = ++readerRequest;
  const target = document.querySelector("#archive-reader");
  if (!target) return;
  target.textContent = "正在读取…";
  try {
    const r = await window.irSystem.archiveRequest("read", { id, offset });
    if (request !== readerRequest || !target.isConnected) return;
    target.innerHTML = `<div class="panel-heading"><h2>${escapeHtml(r.title)}</h2></div><div class="panel-body"><p>${escapeHtml(r.source)} · ${escapeHtml(r.published_on || "日期未知")} · ${escapeHtml(r.text_scope)}</p>
      <p class="archive-warning">${escapeHtml(PARSE_LABELS[r.parse_status] || r.parse_status)} · ${escapeHtml(r.date_basis)}${r.text_scope === "abstract" ? " · 供应商摘要，不是原文" : ""}</p>
      ${r.machine_transcribed ? `<p class="archive-warning">火山机器转写，需听原音核对。已转 ${escapeHtml(Number(r.completed_seconds).toFixed(2))} / ${escapeHtml(Number(r.duration_seconds).toFixed(2))} 秒 · ${r.whole_audio_transcribed ? "整份已转写" : "仅部分转写"}；没有生成研究摘要。</p>` : ""}
      <p class="archive-ref">来源引用：${escapeHtml(r.source_ref)}<br>文本版本：${escapeHtml(r.text_hash)}${r.original_url ? `<br>来源页面：${escapeHtml(r.original_url)}` : ""}</p>
      ${r.kind === "attachment" && r.download_status === "ok" ? `<button class="secondary-button" data-archive-reveal="${escapeHtml(r.id)}">在文件夹中定位原件（校验哈希）</button>` : ""}
      ${r.children.length ? `<div class="archive-attachments"><h3>附件（${r.children.length}）</h3>${r.children.map(a => `<button class="secondary-button" data-archive-read="${escapeHtml(a.id)}">${escapeHtml(a.title)} · ${escapeHtml(PARSE_LABELS[a.parse_status] || a.parse_status)}</button>`).join("")}</div>` : ""}
      <p>字符位置 ${r.offset}–${r.offset+r.text.length} / ${r.total_chars}${r.pages.length ? ` · PDF 页码 ${r.pages.map(p=>p.page).join(", ")}` : ""}</p>
      <pre class="archive-text">${escapeHtml(r.text || "正文不可用：可能仅元数据、尚未解析，或需要 OCR。")}</pre>
      <div class="provider-actions">${offset ? `<button class="secondary-button" data-archive-read="${r.id}" data-read-offset="${Math.max(0,offset-20000)}">上一段</button>` : ""}${r.has_more ? `<button class="secondary-button" data-archive-read="${r.id}" data-read-offset="${offset+20000}">下一段</button>` : ""}</div>
      <p class="archive-warning">${r.warnings.map(escapeHtml).join(" · ")}</p></div>`;
  } catch (error) { if (request === readerRequest && target.isConnected) target.innerHTML = errorPanel("读取失败", error.message); }
}

async function mutateArchive(action) {
  if (action === "stop") { archiveState.stop = true; return; }
  if (archiveState.mutating) return;
  archiveState.mutating = true; archiveState.stop = false;
  const progress = document.querySelector("#archive-progress");
  const buttons = [...document.querySelectorAll('[data-archive-action="parse"], [data-archive-action="index"]')];
  buttons.forEach(b => { b.disabled = true; });
  try {
    if (action === "index") {
      progress.textContent = "正在更新本地派生索引，原件保持不变…";
      await window.irSystem.archiveRequest("index");
      progress.textContent = "索引已更新。";
    } else if (action === "parse") {
      let count = 0;
      for (; count < 20 && !archiveState.stop; count++) {
        progress.textContent = `本地解析中：第 ${count+1} 份 / 最多20份；不会上传 OCR。`;
        const result = await window.irSystem.archiveRequest("parse");
        if (!result.attempted) break;
        if (result.status !== "ok") { progress.textContent = `已停止：${result.results.map(r=>r.status).join(", ")}。成功结果已保存。`; return; }
      }
      progress.textContent = `解析批次已结束；成功 ${count} 份。可刷新状态查看。`;
    }
    if (state.activeModule === "data") await renderDataCenter();
  } catch (error) { if (progress) progress.textContent = `操作停止：${error.message}`; }
  finally { archiveState.mutating = false; buttons.forEach(b => { b.disabled = false; }); }
}

function renderDiagnostics(items = []) {
  if (!items?.length) return "";
  return `<section class="diagnostics"><strong>DATA DIAGNOSTICS</strong><ul>${items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul></section>`;
}

function emptyBody(title, copy) {
  return `<div class="empty-panel"><strong>${escapeHtml(title)}</strong><p>${escapeHtml(copy)}</p></div>`;
}

function errorPanel(title, copy) {
  return `<section class="panel empty-panel"><strong>${escapeHtml(title)}</strong><p>${escapeHtml(copy)}</p></section>`;
}

async function refreshBootstrap() {
  state.bootstrap = await window.irSystem.getBootstrap();
  renderChrome();
  await showModule(state.activeModule);
}

function openCommandPalette() {
  if (!commandDialog.open) commandDialog.showModal();
  commandInput.value = "";
  renderCommandResults();
  commandInput.focus();
}

function renderCommandResults() {
  const query = commandInput.value.trim().toLowerCase();
  const results = [];
  for (const item of state.bootstrap?.navigation || []) {
    results.push({ parent: item.id, child: null, code: item.code, label: item.label, path: item.group });
    for (const child of item.children || []) {
      results.push({ parent: item.id, child: child.id, code: item.code, label: child.label, path: item.label });
    }
  }
  const filtered = results.filter((item) => !query || `${item.label} ${item.path}`.toLowerCase().includes(query)).slice(0, 18);
  commandResults.innerHTML = filtered.map((item) => `<button class="command-result" type="button" data-command-parent="${escapeHtml(item.parent)}" data-command-child="${escapeHtml(item.child || "")}"><span class="code">${escapeHtml(item.code)}</span><strong>${escapeHtml(item.label)}</strong><span class="path">${escapeHtml(item.path)}</span></button>`).join("") || emptyBody("没有匹配页面", "尝试输入 Macro、Industry、EQ、Research 或 Data。 ");
}

document.addEventListener("click", async (event) => {
  if (event.target.closest("[data-audio-library]")) {
    Object.assign(archiveState, { kind: "audio", query: "", source: "", start: "", end: "", offset: 0 });
    return showModule("research");
  }
  const archiveAction = event.target.closest("[data-archive-action]");
  if (archiveAction) return mutateArchive(archiveAction.dataset.archiveAction);
  const archiveRead = event.target.closest("[data-archive-read]");
  if (archiveRead) return readArchiveDocument(archiveRead.dataset.archiveRead, Number(archiveRead.dataset.readOffset || 0));
  const archiveReveal = event.target.closest("[data-archive-reveal]");
  if (archiveReveal) {
    try { await window.irSystem.revealArchiveAsset(archiveReveal.dataset.archiveReveal); }
    catch (error) { archiveReveal.textContent = error.message; }
    return;
  }
  const archivePage = event.target.closest("[data-archive-page]");
  if (archivePage) { archiveState.offset = Math.max(0, archiveState.offset + (archivePage.dataset.archivePage === "next" ? 30 : -30)); return showModule("research"); }
  const moduleButton = event.target.closest("[data-module]");
  if (moduleButton) return showModule(moduleButton.dataset.module);
  const childButton = event.target.closest("[data-child]");
  if (childButton) return showModule(childButton.dataset.parent, childButton.dataset.child);
  const selectButton = event.target.closest("[data-select-provider]");
  if (selectButton) {
    await window.irSystem.selectProvider(selectButton.dataset.selectProvider);
    return refreshBootstrap();
  }
  const probeButton = event.target.closest("[data-probe-provider]");
  if (probeButton) {
    probeButton.textContent = "PROBING…";
    await window.irSystem.probeProvider(probeButton.dataset.probeProvider);
    return refreshBootstrap();
  }
  const commandButton = event.target.closest("[data-command-parent]");
  if (commandButton) {
    commandDialog.close();
    return showModule(commandButton.dataset.commandParent, commandButton.dataset.commandChild || null);
  }
});

document.addEventListener("submit", async (event) => {
  if (event.target.id === "archive-search-form") {
    event.preventDefault();
    const form = new FormData(event.target);
    const start = String(form.get("start") || "");
    const end = String(form.get("end") || "");
    const dateInput = event.target.elements.end;
    dateInput.setCustomValidity(Boolean(start) !== Boolean(end) ? "请同时填写开始和结束日期。" : start > end ? "结束日期不能早于开始日期。" : "");
    if (!dateInput.reportValidity()) return;
    for (const name of ["query", "source", "kind", "start", "end"]) archiveState[name] = String(form.get(name) || "").trim();
    archiveState.offset = 0;
    return showModule("research");
  }
  if (event.target.id !== "provider-config-form") return;
  event.preventDefault();
  if (archiveState.mutating) {
    const progress = document.querySelector("#archive-progress");
    if (progress) progress.textContent = "请先停止当前解析批次，完成当前文件后再修改归档配置。";
    return;
  }
  const form = new FormData(event.target);
  await window.irSystem.saveProviderConfig({
    pythonCommand: form.get("pythonCommand"),
    irSearchPath: form.get("irSearchPath"),
    archiveRoot: form.get("archiveRoot"),
  });
  await refreshBootstrap();
});

document.addEventListener("input", (event) => {
  if (event.target.closest("#archive-search-form")) document.querySelector("#archive-end")?.setCustomValidity("");
});

document.querySelector("#command-trigger").addEventListener("click", openCommandPalette);
commandInput.addEventListener("input", renderCommandResults);
document.addEventListener("keydown", (event) => {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
    event.preventDefault();
    openCommandPalette();
  }
  if (event.key === "Escape" && commandDialog.open) commandDialog.close();
});

startClock();
initialize();
