(() => {
  const names = { zsxq: "知识星球", wisburg: "智堡", ima: "IMA" };
  const modes = { pending_selection: "待选择", off: "不下载", once: "一次性回补", incremental: "持续增量" };
  const statuses = { authorized: "等待启动", running: "运行中", completed: "本轮完成", partial: "有覆盖缺口", needs_attention: "需要处理", budget_paused: "预算暂停", stopped: "已停止", interrupted: "中断可续传", failed: "失败" };
  let view, timer, importPreview;
  const esc = v => String(v ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");
  const stable = value => JSON.stringify(value, (_k, v) => v && typeof v === "object" && !Array.isArray(v) ? Object.fromEntries(Object.entries(v).sort(([a], [b]) => a.localeCompare(b))) : v);
  const message = text => { const box = document.querySelector("#sync-message"); if (box) box.textContent = text; };
  const budgetLabels = { maxOperations: "接口操作上限", maxRecords: "记录上限", maxFiles: "文件上限", maxBytesMiB: "总下载 MiB", maxFileMiB: "单文件 MiB", maxParses: "解析份数", maxSeconds: "运行秒数" };

  function rows(policies) {
    return policies.map((p, index) => `<tr data-sync-row="${index}"><td>${esc(names[p.provider])}</td><td>${esc(p.name || p.collectionId)}<small class="sync-id">${esc(p.collectionId)}</small></td>
      <td><select data-policy-mode>${Object.entries(modes).map(([k, v]) => `<option value="${k}" ${p.mode === k ? "selected" : ""}>${v}</option>`).join("")}</select></td>
      <td><input type="date" data-policy-date value="${esc(p.firstDate)}" aria-label="首次起点" /></td></tr>`).join("");
  }
  function catalog() {
    if (!view.catalog) return "尚未扫描；先扫描目录，再选择需要同步的集合。";
    return `<p>${esc(view.catalog.scannedAt)} · ${view.catalog.complete ? "本次目录扫描完整" : "扫描不完整，不可据此启动下载"}</p>` + view.catalog.sources.map(s => `<details><summary>${esc(names[s.provider])} · ${s.collections.length} 个${s.provider === "wisburg" ? "固定栏目" : "目录条目"} ${s.provider === "zsxq" ? "（API 目录不证明会员有效期）" : ""}</summary><div class="sync-catalog">${s.collections.map(c => `<button class="secondary-button" data-sync-add="${esc(s.provider)}" data-id="${esc(c.collectionId)}" data-name="${esc(c.name)}">＋ ${esc(c.name)}</button>`).join("")}</div></details>`).join("");
  }
  function renderJobs() {
    const target = document.querySelector("#sync-jobs"); if (!target) return;
    target.innerHTML = view.jobs.map(j => `<article class="sync-job"><div><strong>${esc(j.kind === "scan" ? "订阅扫描" : j.kind === "backfill" ? "历史回补" : "增量同步")}</strong> · ${esc(statuses[j.status] || j.status)} · ${esc(j.stage || "")}<small class="sync-id">${esc(j.id)}</small></div>
      <p>本次尝试：新增 ${j.counts.newRecords || 0} · 更新 ${j.counts.updatedRecords || 0} · 下载 ${j.counts.downloaded || 0} · 复用 ${j.counts.reused || 0} · 解析 ${j.counts.parsed || 0} · 音频待办 ${j.counts.audioDeferred || 0}</p>
      ${j.code ? `<p class="archive-warning">${esc(j.code)}。保留断点，不自动重复尝试。</p>` : ""}
      ${j.issues?.length ? `<p class="archive-warning">缺口：${esc([...new Set(j.issues.map(i => i.code))].join("、"))}</p>` : ""}
      ${j.agentResult ? `<p>Pi 说明（非权威统计）：${esc(j.agentResult.text || j.agentResult.status)} · 输入 ${j.agentResult.usage.input} / 输出 ${j.agentResult.usage.output} token（供应商返回值）</p>` : ""}
      ${["running", "queued", "agent_starting"].includes(j.status) || (view.agentConnected && j.status === "authorized") ? `<button class="secondary-button" data-sync-stop="${esc(j.id)}">停止本轮</button>` : ""}
      ${["budget_paused", "interrupted", "stopped"].includes(j.status) && j.kind !== "scan" ? `<button class="secondary-button" data-sync-resume="${esc(j.id)}">授权续传</button>` : ""}
      ${!view.busy && !["authorized", "running"].includes(j.status) ? `<button class="secondary-button" data-sync-explain="${esc(j.id)}">用 Pi 解释报告（需额度）</button>` : ""}
      <small>本轮结果不代表平台全量、全文或全年覆盖。</small></article>`).join("") || "还没有运行任务。";
    document.querySelectorAll("[data-sync-start]").forEach(b => { b.disabled = view.busy; });
  }
  window.renderSyncCenter = async () => {
    clearTimeout(timer);
    const target = document.querySelector("#sync-center"); if (!target) return;
    try {
      view = await window.irSystem.syncGetState();
      target.innerHTML = `<article class="panel"><div class="panel-heading"><div><div class="panel-kicker">INCREMENTAL SYNC · EXPLICIT AUTHORIZATION</div><h2>增量采集</h2></div></div><div class="panel-body">
        <p>先文字及非音频附件；不会启动音频下载、火山转写或托管 OCR。当前接 API 路径；网页与 IMA 客户端自动下载尚未接入。资料来源保持真实范围，不把摘要当全文。</p>
        <div class="provider-actions"><button class="primary-button" data-sync-start="incremental">同步新增资料</button><button class="secondary-button" data-sync-start="backfill">一次性历史回补</button></div>
        <details id="sync-config-details" ${view.settings.policies.length ? "" : "open"}><summary>信源与执行设置</summary><form id="sync-settings"><div class="sync-fields"><label>执行方式<select name="agentMode"><option value="fixed" ${view.settings.agentMode === "fixed" ? "selected" : ""}>固定流程（不调用模型）</option><option value="pi" ${view.settings.agentMode === "pi" ? "selected" : ""}>Pi（使用 Pi 保存的默认模型）</option></select></label>
        <label>Pi 程序<input name="piCommand" value="${esc(view.settings.piCommand)}" /></label><button type="button" class="secondary-button" data-sync-probe>检查 Pi（不调用模型）</button></div>
        <p class="archive-warning">Pi 仅获得四个同步工具，不开放终端、文件读写或自由浏览器操作；此为模型工具限制，不是对 CLI 进程的操作系统沙箱。模型在 Pi 中配置；Kimi Code CLI 独立直连尚未验收。</p>
        <button type="button" class="secondary-button" data-sync-import>读取 IMA Excel 标记（只读预览）</button><div id="sync-import-preview"></div>
        <table class="capability-table"><thead><tr><th>来源</th><th>集合</th><th>采集方式</th><th>首次回补起点</th></tr></thead><tbody id="sync-policy-rows">${rows(view.settings.policies)}</tbody></table>
        <p>IMA 缺少可靠日期：起点只记录你的目标范围，实际枚举可访问目录并按文件 ID 去重，不宣称已按日期筛出资料。新增订阅默认待选择。</p>
        <details><summary>本轮预算与增量重叠回扫</summary><div class="sync-fields">${Object.entries(budgetLabels).map(([k, label]) => `<label>${label}<input type="number" name="${k}" value="${view.settings.budgets[k]}" min="0" /></label>`).join("")}<label>重叠回扫天数<input type="number" name="overlapDays" value="${view.settings.overlapDays}" min="1" max="30" /></label></div></details>
        <button type="submit" class="primary-button">保存信源设置（不启动任务）</button></form></details>
        <details><summary>发现／添加订阅</summary><div class="sync-fields">${Object.entries(names).map(([k,v]) => `<label><input type="checkbox" data-scan-provider value="${k}" checked /> ${v}</label>`).join("")}<button class="secondary-button" data-sync-scan>扫描所选信源目录</button></div><div id="sync-catalog">${catalog()}</div>
        <form id="sync-manual"><div class="sync-fields"><label>来源<select name="provider">${Object.entries(names).map(([k,v]) => `<option value="${k}">${v}</option>`).join("")}</select></label><label>真实集合 ID<input name="collectionId" required /></label><label>显示名称<input name="name" /></label><button class="secondary-button">加入待选择</button></div></form></details>
        <p id="sync-message" role="status" aria-live="polite">设置和按钮范围会再次确认；点击同步前仍会重新扫描本轮信源完整目录。</p><details open><summary>运行记录</summary><div id="sync-jobs"></div></details>
      </div></article>`;
      renderJobs(); poll();
    } catch (e) { target.textContent = e.message; }
  };
  async function poll() {
    clearTimeout(timer);
    if (!document.querySelector("#sync-jobs")) return;
    try {
      const latest = await window.irSystem.syncGetState();
      view.jobs = latest.jobs; view.busy = latest.busy; view.agentConnected = latest.agentConnected;
      if (JSON.stringify(view.catalog) !== JSON.stringify(latest.catalog)) { view.catalog = latest.catalog; document.querySelector("#sync-catalog").innerHTML = catalog(); renderImport(); }
      renderJobs();
    } catch (e) { message(e.message); }
    timer = setTimeout(poll, 2000);
  }
  function collect() {
    const form = document.querySelector("#sync-settings"), fields = new FormData(form);
    return { agentMode: fields.get("agentMode"), piCommand: fields.get("piCommand"), overlapDays: Number(fields.get("overlapDays")),
      budgets: Object.fromEntries(Object.keys(budgetLabels).map(k => [k, Number(fields.get(k))])),
      policies: view.settings.policies.map((p, i) => { const row = form.querySelector(`[data-sync-row="${i}"]`); return { ...p, mode: row.querySelector("[data-policy-mode]").value, firstDate: row.querySelector("[data-policy-date]").value }; }) };
  }
  function add(p) {
    if (view.settings.policies.some(r => r.provider === p.provider && r.collectionId === p.collectionId)) { message("这个集合已经在设置中。"); return; }
    view.settings = collect(); view.settings.policies.push({ ...p, mode: "pending_selection", firstDate: "" });
    document.querySelector("#sync-policy-rows").innerHTML = rows(view.settings.policies); message("已加入待选择；请选择采集方式和起点，再保存设置。");
  }
  function renderImport() {
    const target = document.querySelector("#sync-import-preview");
    if (!target || !importPreview) return;
    const directory = view.catalog?.sources?.find(s => s.provider === "ima")?.collections || [];
    target.innerHTML = `<p>共 ${importPreview.rows.length} 行：一次性 ${importPreview.counts.once || 0}、增量 ${importPreview.counts.incremental || 0}、不下载 ${importPreview.counts.off || 0}。原 Excel 未修改。请选择真实 ID 后加入草稿，再填写起点并保存。</p>
      ${importPreview.issues.length ? `<p class="archive-warning">${esc(importPreview.issues.map(x => `${x.sheet} 第 ${x.row} 行：${x.code}`).join("；"))}</p>` : ""}
      <table class="capability-table"><thead><tr><th>表中名称</th><th>标记</th><th>实际知识库绑定</th><th>确认</th></tr></thead><tbody>${importPreview.rows.map((r, i) => {
        const exact = directory.filter(c => c.name === r.name);
        const candidate = r.collectionId || (!r.ambiguous && exact.length === 1 ? exact[0].collectionId : "");
        return `<tr><td>${esc(r.name)}${r.ambiguous ? "（名称重复，须核对）" : ""}</td><td>${esc(modes[r.mode])}</td><td><select data-import-binding="${i}"><option value="">先扫描 IMA，再选择</option>${directory.map(c => `<option value="${esc(c.collectionId)}" ${candidate === c.collectionId ? "selected" : ""}>${esc(c.name)} · ${esc(c.collectionId)}</option>`).join("")}</select></td><td><button type="button" class="secondary-button" data-import-confirm="${i}">加入草稿</button></td></tr>`;
      }).join("")}</tbody></table>`;
  }
  document.addEventListener("submit", async event => {
    if (!["sync-settings", "sync-manual"].includes(event.target.id)) return;
    event.preventDefault();
    try {
      if (event.target.id === "sync-manual") { const f = new FormData(event.target); add({ provider: f.get("provider"), collectionId: f.get("collectionId").trim(), name: f.get("name").trim() }); return; }
      view = await window.irSystem.syncSaveSettings(collect()); message("已保存，尚未启动下载。");
    } catch (e) { message(e.message); }
  });
  document.addEventListener("click", async event => {
    const b = event.target.closest("button"); if (!b || !b.closest("#sync-center")) return;
    try {
      if (b.hasAttribute("data-sync-import")) { const preview = await window.irSystem.syncImportExcel(); if (!preview.cancelled) { importPreview = preview; renderImport(); } return; }
      if (b.hasAttribute("data-import-confirm")) {
        const r = importPreview.rows[Number(b.dataset.importConfirm)];
        const id = document.querySelector(`[data-import-binding="${b.dataset.importConfirm}"]`).value;
        if (!id) return message("请先扫描 IMA 并选择一个真实知识库 ID。");
        if (view.settings.policies.some(p => p.provider === "ima" && p.collectionId === id)) return message("该 ID 已在设置中，请直接调整原行，避免重复绑定。");
        view.settings = collect(); view.settings.policies.push({ provider: "ima", collectionId: id, name: r.name, mode: r.mode, firstDate: "" });
        document.querySelector("#sync-policy-rows").innerHTML = rows(view.settings.policies); return message("已加入草稿；启用下载的行须填写首次起点，再保存。");
      }
      if (b.hasAttribute("data-sync-add")) return add({ provider: b.dataset.syncAdd, collectionId: b.dataset.id, name: b.dataset.name });
      if (b.hasAttribute("data-sync-probe")) { const result = await window.irSystem.syncProbePi(); return message(result.ready ? "Pi 支持受限工具模式；没有调用模型。模型使用 Pi 保存的默认选择。" : result.code); }
      let result;
      if (b.hasAttribute("data-sync-scan")) result = await window.irSystem.syncScan([...document.querySelectorAll("[data-scan-provider]:checked")].map(x => x.value));
      if (b.hasAttribute("data-sync-start")) {
        if (stable(collect()) !== stable((await window.irSystem.syncGetState()).settings)) return message("请先保存信源设置，再开始同步。");
        result = await window.irSystem.syncApprove(b.dataset.syncStart);
      }
      if (b.hasAttribute("data-sync-resume")) result = await window.irSystem.syncApprove("incremental", b.dataset.syncResume);
      if (b.hasAttribute("data-sync-stop")) result = await window.irSystem.syncStop(b.dataset.syncStop);
      if (b.hasAttribute("data-sync-explain")) result = await window.irSystem.syncExplain(b.dataset.syncExplain);
      if (result) { message(result.status === "cancelled" ? "已取消，未启动。" : "请求已提交；以下程序状态为准，Pi 文字说明不替代执行结果。"); await poll(); }
    } catch (e) { message(e.message); }
  });
})();
