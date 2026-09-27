// Equities 模块：Futures / Options 两个整行可折叠栏目，复用 companies 行业分组盒样式。
// 内容暂为占位，待接入真实数据结构。
(() => {
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[c]));

  function panel(item) {
    return `<details class="industry-group equities-panel" data-eq-panel="${esc(item.id)}"><summary><span class="industry-group-name">${esc(item.label)}</span><span class="industry-group-count">待接入</span></summary><div class="industry-group-body"><p class="company-empty">该栏目结构待接入；当前不生成替代数据。</p></div></details>`;
  }

  window.renderEquities = (data, childId, heading, children) => {
    // children 由 app.js 从导航定义传入；connected 模式下 provider 不返回 sections。
    const items = Array.isArray(children) && children.length ? children : (Array.isArray(data.sections) ? data.sections : []);
    document.querySelector('#workspace').innerHTML = `${heading(data.moduleId, 'Equities', data.dataMode, data.asOf)}
      <section class="industry-panel equities-panels">${items.map(panel).join('')}</section>`;
  };
})();
