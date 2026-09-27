// A股行业面板：纯本地静态展示，不读取 provider 能力。分组与行业为 IR System 自有
// 申万一级映射；股票与矩阵单元格为示意占位，不代表实时数据或已接入能力。
(() => {
  const { groups, MATRIX_COLUMNS } = IRCompanyIndustries;
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[c]));

  function matrix(industry) {
    const head = MATRIX_COLUMNS.map(c => `<th>${esc(c)}</th>`).join('');
    const rows = industry.stocks.map(stock => `<tr><th scope="row">${esc(stock)}</th>${MATRIX_COLUMNS.map(() => '<td>—</td>').join('')}</tr>`).join('');
    return `<table class="industry-matrix"><thead><tr><th scope="col">股票</th>${head}</tr></thead><tbody>${rows}</tbody></table>`;
  }

  function subBox(industry) {
    return `<details class="industry-sub"><summary>${esc(industry.name)}<span class="industry-sub-hint">${industry.stocks.length} 只示意</span></summary>${matrix(industry)}</details>`;
  }

  function groupBox(item) {
    return `<details class="industry-group"><summary><span class="industry-group-name">${esc(item.label)}</span><span class="industry-group-count">${item.industries.length} 个行业</span></summary><div class="industry-group-body">${item.industries.map(subBox).join('')}</div></details>`;
  }

  window.renderCompanyIndustries = () =>
    `<section class="industry-panel">${groups.map(groupBox).join('')}</section>`;
})();
