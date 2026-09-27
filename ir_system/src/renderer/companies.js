(() => {
  const { markets, marketFor, view } = IRCompanyMarkets;
  const STORAGE_KEY = 'ir-company-market';
  const NOTES = {
    mapped: ['版块状态取自 Provider 能力注册：partial = 已注册、未实测；unavailable = 未注册。注册不代表凭证、网络或真实取数已验证。', '当前 Provider 未注册此能力。保持空状态，不生成替代数据。'],
    unavailable: ['Provider 当前不可用，各版块不显示覆盖。', 'Provider 当前不可用。'],
    demo: ['演示模式：只有页面结构，没有真实能力映射。', '演示模式，没有真实能力映射。'],
    planned: ['当前 Provider 未提供分市场能力映射，各版块不显示覆盖。', '当前 Provider 未提供分市场能力映射。'],
  };
  let current = null;
  let active = null;

  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[c]));
  const token = status => String(status || 'unavailable').replace(/[^a-z-]/gi, '');
  const badge = status => `<span class="status-badge status-${token(status)}">${esc(status || 'unknown')}</span>`;
  const capability = item => [item.capability, ...(item.frequencies || [])].filter(Boolean).join(' · ');

  function remembered() { try { return localStorage.getItem(STORAGE_KEY); } catch { return null; } }
  function remember(id) { try { localStorage.setItem(STORAGE_KEY, id); } catch {} }

  function tab(market, selected) {
    const status = view(current, market.id).status;
    return `<button class="company-tab" type="button" role="tab" id="company-tab-${market.id}" data-company-market="${market.id}" aria-controls="company-panel" aria-selected="${selected}" tabindex="${selected ? 0 : -1}"><span class="company-dot ${token(status)}"></span><span>${esc(market.label)}</span><small>${esc(status)}</small></button>`;
  }

  function source(item) {
    const issuer = item.scope === 'issuer_catalog';
    const detail = capability(item);
    return `<li class="${issuer ? 'issuer' : ''}">${esc(item.provider)}${detail ? ` · ${esc(detail)}` : ''}${issuer ? ' · 按发行人目录' : ''}</li>`;
  }

  function section(item, index, empty) {
    const body = item.sources.length
      ? `<ul class="company-sources">${item.sources.map(source).join('')}</ul>`
      : `<p class="company-empty">${esc(empty)}</p>`;
    const action = item.id === 'research' ? '<button class="secondary-button company-action" type="button" data-module="research">打开本地资料库</button>' : '';
    return `<article class="company-section" data-company-section="${esc(item.id)}"><header><span class="section-number">${String(index + 1).padStart(2, '0')}</span>${badge(item.status)}</header><strong>${esc(item.label)}</strong><p>${esc(item.copy)}</p>${body}${action}</article>`;
  }

  function coverage(model) {
    const rows = model.sections.flatMap(s => s.sources.map(src => ({ section: s.label, ...src })));
    if (!rows.length) return '';
    return `<details class="company-coverage"><summary>覆盖说明：${rows.length} 项已注册能力（ir_search 能力注册，未实测）</summary><table class="capability-table"><thead><tr><th>版块</th><th>来源</th><th>能力</th><th>覆盖说明</th></tr></thead><tbody>${rows.map(r => `<tr><td>${esc(r.section)}</td><td>${esc(r.provider)}${r.scope === 'issuer_catalog' ? '<br><small>按发行人目录</small>' : ''}</td><td>${esc(capability(r))}</td><td>${(r.notes || []).length ? `<ul>${r.notes.map(n => `<li>${esc(n)}</li>`).join('')}</ul>` : '—'}</td></tr>`).join('')}</tbody></table></details>`;
  }

  function capabilityPanel(marketId) {
    const model = view(current, marketId);
    const [, empty] = NOTES[model.mapped ? 'mapped' : model.status] || NOTES.planned;
    return `<section class="section-grid company-sections">${model.sections.map((s, i) => section(s, i, empty)).join('')}</section>
      ${coverage(model)}`;
  }

  function panel(marketId) {
    if (marketId === 'A_SHARE' && window.renderCompanyIndustries) return window.renderCompanyIndustries();
    return capabilityPanel(marketId);
  }

  function render(data, childId, heading) {
    current = data;
    active = marketFor(childId, active || remembered());
    remember(active);
    document.querySelector('#workspace').innerHTML = `${heading(data.moduleId, 'Companies', data.dataMode, data.asOf)}
      <div class="company-tabs" role="tablist" aria-label="上市地">${markets.map(m => tab(m, m.id === active)).join('')}</div>
      <div id="company-panel" class="company-panel" role="tabpanel" aria-labelledby="company-tab-${active}">${panel(active)}</div>`;
  }

  // Tabs re-render from the module data already loaded; switching markets
  // does not spawn another provider probe.
  function select(marketId, focus) {
    const target = document.querySelector('#company-panel');
    if (!current || !target || !markets.some(m => m.id === marketId)) return;
    active = marketId;
    remember(marketId);
    for (const element of document.querySelectorAll('[data-company-market]')) {
      const selected = element.dataset.companyMarket === marketId;
      element.setAttribute('aria-selected', String(selected));
      element.tabIndex = selected ? 0 : -1;
      if (selected && focus) element.focus();
    }
    target.setAttribute('aria-labelledby', `company-tab-${marketId}`);
    target.innerHTML = panel(marketId);
  }

  document.addEventListener('click', event => {
    const element = event.target.closest?.('[data-company-market]');
    if (element) select(element.dataset.companyMarket, false);
  });
  document.addEventListener('keydown', event => {
    const element = event.target.closest?.('[data-company-market]');
    if (!element) return;
    const index = markets.findIndex(m => m.id === element.dataset.companyMarket);
    const next = { ArrowRight: index + 1, ArrowLeft: index - 1, Home: 0, End: markets.length - 1 }[event.key];
    if (next === undefined) return;
    event.preventDefault();
    select(markets[(next + markets.length) % markets.length].id, true);
  });

  window.renderCompanies = render;
})();
