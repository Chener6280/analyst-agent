// Equities 模块：Futures（股指期货基差监控）与 Options（期权波动率曲面）。
// 数据全部来自 ir_search（经 derivatives:* 桥接方法）；页面不生成替代数据。
(() => {
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[c]));
  const fmt = (x, d = 2) => (x === null || x === undefined || Number.isNaN(Number(x))) ? '—' : Number(x).toFixed(d);
  const pct = (x, d = 2) => (x === null || x === undefined) ? '—' : `${(x * 100).toFixed(d)}%`;
  const cls = x => x === null || x === undefined ? '' : x > 0 ? 'd-pos' : x < 0 ? 'd-neg' : '';
  const AUTO_SECONDS = 300;

  const PRODUCT_ORDER = ['IH', 'IF', 'IC', 'IM'];
  const SLOTS = ['当月', '下月', '当季', '下季'];
  const SLOT_CLASS = { '当月': 'd-c0', '下月': 'd-c1', '当季': 'd-c2', '下季': 'd-c3' };
  const AUTO_STOP_MINUTES = 15 * 60 + 10; // 15:10（Asia/Shanghai）后停止自动刷新

  const futures = { data: null, loading: false, timer: null, countdown: AUTO_SECONDS, use: {}, overrides: {}, hidden: {}, hiddenIdx: {}, window: {} };
  const vixState = { data: null, loading: false, years: 3, selected: '000300.SH', win: {}, error: null };

  // ---------------------------------------------------------------- shared bits

  // [date, 调整, code, 原始] —— use 切换调整/原始口径。
  const valOf = (pt, useCarry) => (useCarry ? pt[1] : (pt[3] !== undefined ? pt[3] : pt[1]));

  // 四个期限的年化基差同图，标的指数走势以更细的线叠加在右轴。
  // sharedDomain：四个品种共用同一组交易日（并集），起始日期对齐；win = [i0, i1] 为可见窗口（滑块选择）。
  function svgBasisChart(p, hidden, hideIdx, useCarry, sharedDomain, win) {
    const width = 560, height = 190, L = 46, R = 52, T = 12, B = 24;
    const hist = p.history || {};
    const idxPts = (p.index_history || []).filter(pt => pt[1] !== null && pt[1] !== undefined);
    const fullDomain = (sharedDomain || []).length ? sharedDomain
      : idxPts.length ? idxPts.map(pt => pt[0])
      : [...new Set(SLOTS.flatMap(s => (hist[s] || []).map(pt => pt[0])))].sort();
    if (fullDomain.length < 2) return '<p class="d-empty">样本不足</p>';
    const domain = win ? fullDomain.slice(win[0], win[1] + 1) : fullDomain;
    if (domain.length < 2) return '<p class="d-empty">窗口内样本不足</p>';
    const pos = new Map(domain.map((d, i) => [d, i]));
    const X = d => L + (pos.get(d) / (domain.length - 1)) * (width - L - R);
    const series = SLOTS.filter(s => !hidden.has(s))
      .map(s => ({ slot: s, pts: (hist[s] || []).filter(pt => {
        const v = valOf(pt, useCarry);
        return v !== null && v !== undefined && pos.has(pt[0]);
      }) }));
    const vals = series.flatMap(s => s.pts.map(pt => valOf(pt, useCarry)));
    if (!vals.length) return '<p class="d-empty">已隐藏全部期限（勾选下方期限恢复）</p>';
    // 临近到期年化被天数放大成毛刺：纵轴取可见样本的 2%–98% 分位，极值出界由 viewBox 裁剪
    const sorted = [...vals].sort((a, b) => a - b);
    const q = t => sorted[Math.min(sorted.length - 1, Math.max(0, Math.floor(t * (sorted.length - 1))))];
    let lo = q(0.02), hi = q(0.98);
    const pad = (hi - lo) * 0.15 || 0.005;
    lo -= pad; hi += pad;
    const Y = v => T + (1 - (v - lo) / (hi - lo)) * (height - T - B);
    const grid = [0, 0.25, 0.5, 0.75, 1].map(t => {
      const v = lo + (hi - lo) * t;
      return `<line x1="${L}" x2="${width - R}" y1="${Y(v)}" y2="${Y(v)}" class="d-grid"/><text x="${L - 4}" y="${Y(v) + 3}" text-anchor="end" class="d-axistext">${(v * 100).toFixed(1)}%</text>`;
    }).join('');
    const zero = lo < 0 && hi > 0 ? `<line x1="${L}" x2="${width - R}" y1="${Y(0)}" y2="${Y(0)}" class="d-zero"/>` : '';
    const lines = series.map(s => {
      const dAttr = s.pts.map((pt, i) => `${i ? 'L' : 'M'}${X(pt[0]).toFixed(1)},${Y(valOf(pt, useCarry)).toFixed(1)}`).join('');
      return dAttr ? `<path d="${dAttr}" class="d-line ${SLOT_CLASS[s.slot]}"/>` : '';
    }).join('');
    let idxLine = '', idxAxis = '';
    const idxWin = idxPts.filter(pt => pos.has(pt[0]));
    if (idxWin.length && !hideIdx) {
      const iv = idxWin.map(pt => pt[1]);
      let ilo = Math.min(...iv), ihi = Math.max(...iv);
      const ipad = (ihi - ilo) * 0.1 || 1;
      ilo -= ipad; ihi += ipad;
      const YI = v => T + (1 - (v - ilo) / (ihi - ilo)) * (height - T - B);
      idxLine = `<path d="${idxWin.map((pt, i) => `${i ? 'L' : 'M'}${X(pt[0]).toFixed(1)},${YI(pt[1]).toFixed(1)}`).join('')}" class="d-line-idx"/>`;
      idxAxis = [0, 0.5, 1].map(t => {
        const v = ilo + (ihi - ilo) * t;
        return `<text x="${width - R + 4}" y="${YI(v) + 3}" class="d-axistext d-axistext-idx">${fmt(v, 0)}</text>`;
      }).join('');
    }
    const ticks = [0, 0.25, 0.5, 0.75, 1].map(t => {
      const i = Math.round(t * (domain.length - 1));
      return `<text x="${X(domain[i])}" y="${height - 6}" text-anchor="middle" class="d-axistext">${esc(domain[i].slice(2))}</text>`;
    }).join('');
    return `<svg viewBox="0 0 ${width} ${height}" class="d-chart" preserveAspectRatio="none">${grid}${zero}${idxLine}${lines}${idxAxis}${ticks}</svg>`;
  }

  // ---------------------------------------------------------------- Futures

  const hiddenFor = product => futures.hidden[product] || (futures.hidden[product] = new Set(['当月', '下月', '当季']));
  const useCarryFor = product => futures.use[product] !== false;

  // 每个品种的时间窗口（双滑块）：futures.window[product] = {i0, i1, follow}。
  // follow = 默认「过去 N 年」窗口：数据变长时贴住右缘；用户拖动后 follow=false 固定不动；手动刷新整体复位。
  const FBRUSH = { width: 560, height: 44, L: 46, R: 52 };
  const fbrushX = (n, i) => FBRUSH.L + (i / (n - 1)) * (FBRUSH.width - FBRUSH.L - FBRUSH.R);

  function futWindow(p, n) {
    const w = futures.window[p.product];
    const span = Math.max(20, Math.round(((p.carry || {}).years || 3) * 250));
    let i0, i1;
    if (!w || w.follow) { i1 = n - 1; i0 = Math.max(0, n - 1 - span); }
    else { i0 = Math.max(0, Math.min(w.i0, n - 2)); i1 = Math.min(n - 1, Math.max(w.i1, i0 + 1)); }
    futures.window[p.product] = { i0, i1, follow: !w || !!w.follow };
    return [i0, i1];
  }

  // 缩略图固定画「下季」年化基差（默认可见的那条），帮助定位基差 regime；坐标轴与主图一致的全历史。
  function svgFutBrush(p, use, domain, i0, i1) {
    const n = domain.length;
    if (n < 2) return '';
    const pos = new Map(domain.map((d, i) => [d, i]));
    const pts = ((p.history || {})['下季'] || [])
      .map(pt => [pos.get(pt[0]), valOf(pt, use)])
      .filter(x => x[0] !== undefined && x[1] !== null && x[1] !== undefined);
    const { width, height, L, R } = FBRUSH;
    let path = '';
    if (pts.length > 1) {
      const vals = pts.map(x => x[1]);
      let lo = Math.min(...vals), hi = Math.max(...vals);
      const pad = (hi - lo) * 0.08 || 0.005;
      lo -= pad; hi += pad;
      const Y = v => 3 + (1 - (v - lo) / (hi - lo)) * (height - 8);
      path = pts.map((x, j) => `${j ? 'L' : 'M'}${fbrushX(n, x[0]).toFixed(1)},${Y(x[1]).toFixed(1)}`).join('');
    }
    return `<svg viewBox="0 0 ${width} ${height}" class="d-brush-svg" preserveAspectRatio="none">
      ${path ? `<path d="${path}" class="d-line d-c3 d-brush-line"/>` : ''}
      <rect data-b="dimL" x="${L}" y="0" width="${fbrushX(n, i0) - L}" height="${height}" class="d-brush-dim"/>
      <rect data-b="dimR" x="${fbrushX(n, i1)}" y="0" width="${width - R - fbrushX(n, i1)}" height="${height}" class="d-brush-dim"/>
      <rect data-b="win" x="${fbrushX(n, i0)}" y="0" width="${fbrushX(n, i1) - fbrushX(n, i0)}" height="${height}" class="d-brush-win"/>
      <rect data-b="hl" x="${fbrushX(n, i0) - 2}" y="0" width="4" height="${height}" class="d-brush-handle"/>
      <rect data-b="hr" x="${fbrushX(n, i1) - 2}" y="0" width="4" height="${height}" class="d-brush-handle"/>
    </svg>`;
  }

  function updateFutBrush(panel, product, n, i0, i1) {
    const box = panel.querySelector(`[data-fut-brush="${product}"]`);
    if (!box) return;
    const set = (name, attrs) => {
      const el = box.querySelector(`[data-b="${name}"]`);
      if (el) Object.entries(attrs).forEach(([k, v]) => el.setAttribute(k, v));
    };
    const { width, height, L, R } = FBRUSH;
    set('dimL', { x: L, width: fbrushX(n, i0) - L });
    set('dimR', { x: fbrushX(n, i1), width: width - R - fbrushX(n, i1) });
    set('win', { x: fbrushX(n, i0), width: fbrushX(n, i1) - fbrushX(n, i0) });
    set('hl', { x: fbrushX(n, i0) - 2 });
    set('hr', { x: fbrushX(n, i1) - 2 });
  }

  function drawFutRow(panel, product, domain) {
    const d = futures.data;
    if (!d || domain.length < 2) return;
    const p = (d.products || []).find(x => x.product === product);
    if (!p) return;
    const [i0, i1] = futWindow(p, domain.length);
    const chart = panel.querySelector(`[data-fut-chart="${product}"]`);
    if (chart) chart.innerHTML = svgBasisChart(p, hiddenFor(product), !!futures.hiddenIdx[product], useCarryFor(product), domain, [i0, i1]);
    updateFutBrush(panel, product, domain.length, i0, i1);
  }

  function attachFutBrush(panel, product, domain) {
    const container = panel.querySelector(`[data-fut-brush="${product}"]`);
    if (!container) return;
    let drag = null;
    container.addEventListener('pointerdown', e => {
      const n = domain.length;
      if (n < 2) return;
      const svg = container.querySelector('svg');
      const rect = svg.getBoundingClientRect();
      const toX = ev => (ev.clientX - rect.left) / rect.width * FBRUSH.width;
      const toI = x => Math.round((x - FBRUSH.L) / (FBRUSH.width - FBRUSH.L - FBRUSH.R) * (n - 1));
      const x = toX(e);
      let { i0, i1 } = futures.window[product] || { i0: 0, i1: n - 1 };
      const w = i1 - i0;
      let mode, grab = 0;
      if (Math.abs(x - fbrushX(n, i0)) <= 8) mode = 'l';
      else if (Math.abs(x - fbrushX(n, i1)) <= 8) mode = 'r';
      else if (x > fbrushX(n, i0) && x < fbrushX(n, i1)) { mode = 'move'; grab = x - fbrushX(n, i0); }
      else {  // 点击空白：窗口中心跳到该处并进入拖动
        mode = 'move';
        i0 = Math.max(0, Math.min(n - 1 - w, toI(x) - Math.round(w / 2)));
        i1 = i0 + w;
        grab = (fbrushX(n, i1) - fbrushX(n, i0)) / 2;
      }
      futures.window[product] = { i0, i1, follow: false };
      drag = { mode, grab };
      container.setPointerCapture(e.pointerId);
      e.preventDefault();
      drawFutRow(panel, product, domain);
    });
    container.addEventListener('pointermove', e => {
      if (!drag) return;
      const n = domain.length;
      const svg = container.querySelector('svg');
      const rect = svg.getBoundingClientRect();
      const x = (e.clientX - rect.left) / rect.width * FBRUSH.width;
      const toI = v => Math.round((v - FBRUSH.L) / (FBRUSH.width - FBRUSH.L - FBRUSH.R) * (n - 1));
      let { i0, i1 } = futures.window[product];
      const w = i1 - i0;
      if (drag.mode === 'move') {
        const ni0 = Math.max(0, Math.min(n - 1 - w, toI(x - drag.grab)));
        i1 = ni0 + w; i0 = ni0;
      } else if (drag.mode === 'l') {
        i0 = Math.max(0, Math.min(i1 - 10, toI(x)));
      } else {
        i1 = Math.min(n - 1, Math.max(i0 + 10, toI(x)));
      }
      futures.window[product] = { i0, i1, follow: false };
      drawFutRow(panel, product, domain);
    });
    container.addEventListener('pointerup', () => { drag = null; });
    container.addEventListener('pointercancel', () => { drag = null; });
  }

  function slotBar(product, hidden, hideIdx) {
    return `<div class="d-slotbar">${SLOTS.map(s =>
      `<label class="d-slotcb"><input type="checkbox" data-slot-cb="${esc(product)}|${esc(s)}" ${hidden.has(s) ? '' : 'checked'}><span class="d-sw ${SLOT_CLASS[s]}"></span>${s}</label>`).join('')}
      <label class="d-slotcb"><input type="checkbox" data-idx-cb="${esc(product)}" ${hideIdx ? '' : 'checked'}><span class="d-sw d-sw-idx"></span>指数</label></div>`;
  }

  function futTable(p, use) {
    const ix = p.index || {};
    const ixPct = ix.last && ix.previous_close ? (ix.last - ix.previous_close) / ix.previous_close : null;
    const blocks = use ? (p.percentiles || {}) : (p.percentiles_raw || {});
    const rows = [`<tr class="d-index-row"><td>${esc(ix.code || '')}</td><td>${fmt(ix.last)}</td>
      <td class="${cls(ixPct)}">${ixPct === null ? '—' : `${(ixPct * 100).toFixed(2)}%`}</td><td>—</td><td>—</td><td>—</td><td>—</td></tr>`];
    (p.contracts || []).forEach(c => {
      const chgPct = c.price && c.previous_close ? (c.price - c.previous_close) / c.previous_close : null;
      const basis = use ? c.basis : c.basis_raw;
      const dBasis = use ? c.basis_change
        : (ix.change !== null && ix.change !== undefined && c.change !== null && c.change !== undefined ? ix.change - c.change : null);
      const ann = use ? c.annualized : c.annualized_raw;
      const block = blocks[c.slot];
      rows.push(`<tr><td>${esc(c.code)}</td><td>${fmt(c.price)}</td>
        <td class="${cls(chgPct)}">${chgPct === null ? '—' : `${(chgPct * 100).toFixed(2)}%`}</td>
        <td class="${cls(basis)}">${fmt(basis)}</td><td class="${cls(dBasis)}">${fmt(dBasis)}</td>
        <td class="${cls(ann)}">${pct(ann)}</td><td>${block ? pct(block.percentile, 0) : '—'}</td></tr>`);
    });
    return `<table class="d-table d-table-fut"><thead><tr><th>代码</th><th>点位</th><th>涨跌幅</th><th>基差</th><th>d基差</th><th>年化基差率</th><th>分位数</th></tr></thead><tbody>${rows.join('')}</tbody></table>`;
  }

  function futRow(p, sharedDomain) {
    const product = p.product;
    const hidden = hiddenFor(product);
    const hideIdx = !!futures.hiddenIdx[product];
    const use = useCarryFor(product);
    const carry = p.carry || {};
    const ov = futures.overrides[product] || {};
    const rfPct = ov.rf !== undefined ? ov.rf : (carry.rf !== null && carry.rf !== undefined ? carry.rf * 100 : '');
    const divPct = ov.div !== undefined ? ov.div : (carry.div !== null && carry.div !== undefined ? carry.div * 100 : '');
    const yrs = ov.years !== undefined ? ov.years : (carry.years || 3);
    const num = v => (typeof v === 'number' && Number.isFinite(v)) ? String(Math.round(v * 100) / 100) : '';
    const [i0, i1] = futWindow(p, sharedDomain.length);
    const head = `<div class="d-futrow-head"><b>${esc((p.index || {}).name || product)}</b>
      <label class="d-param"><input type="checkbox" data-use-carry="${esc(product)}" ${use ? 'checked' : ''}> use</label>
      <label class="d-param">无风险利率 <input data-carry-input="rf|${esc(product)}" type="number" step="0.01" min="-5" max="20" value="${num(rfPct)}" style="width:52px">%</label>
      <label class="d-param">分红率 <input data-carry-input="div|${esc(product)}" type="number" step="0.01" min="-5" max="20" value="${num(divPct)}" style="width:52px">%</label>
      <label class="d-param">过去 <input data-carry-input="years|${esc(product)}" type="number" step="0.5" min="0.5" max="10" value="${num(yrs)}" style="width:44px"> 年</label></div>`;
    return `<section class="d-futrow" data-futrow="${esc(product)}">${head}
      <div class="d-futleft">${futTable(p, use)}</div>
      <div class="d-futright"><div data-fut-chart="${esc(product)}">${svgBasisChart(p, hidden, hideIdx, use, sharedDomain, [i0, i1])}</div>
      <div data-fut-brush="${esc(product)}">${svgFutBrush(p, use, sharedDomain, i0, i1)}</div>
      <div class="d-muted d-brush-hint">全历史 ${esc(sharedDomain[0] || '')} ~ ${esc(sharedDomain[sharedDomain.length - 1] || '')} · 拖动滑块选择区间</div>
      ${slotBar(product, hidden, hideIdx)}</div></section>`;
  }

  function renderFuturesBody(panel) {
    const body = panel.querySelector('.d-body');
    if (futures.loading && !futures.data) {
      body.innerHTML = '<p class="d-empty">正在读取期货、指数行情并构建全历史（首次约 1–2 分钟，之后走本地缓存只补增量）…</p>';
      return;
    }
    if (!futures.data) return;
    const d = futures.data;
    const status = d.status || {};
    const head = `<div class="d-statusline" data-asof="${esc(d.asOf || '')}">
        <span class="d-status d-status-${esc(status.code || 'closed')}">${esc(status.label || '')}</span>
        <span class="d-muted" data-countdown></span>
        <button class="secondary-button" data-refresh>手动刷新</button>
      </div>`;
    const products = [...(d.products || [])].sort((a, b) => PRODUCT_ORDER.indexOf(a.product) - PRODUCT_ORDER.indexOf(b.product));
    const sharedDomain = [...new Set(products.flatMap(p => (p.index_history || []).map(pt => pt[0])))].sort();
    body.innerHTML = head + products.map(p => futRow(p, sharedDomain)).join('');
    products.forEach(p => attachFutBrush(panel, p.product, sharedDomain));
    body.querySelector('[data-refresh]').addEventListener('click', () => {
      futures.window = {};  // 手动刷新：滑块复位到「过去 N 年」默认窗口
      loadBasis(panel, true);
    });
    body.querySelectorAll('[data-slot-cb]').forEach(cb => cb.addEventListener('change', () => {
      const [product, slot] = cb.dataset.slotCb.split('|');
      const hidden = hiddenFor(product);
      if (cb.checked) hidden.delete(slot); else hidden.add(slot);
      renderFuturesBody(panel);
    }));
    body.querySelectorAll('[data-idx-cb]').forEach(cb => cb.addEventListener('change', () => {
      futures.hiddenIdx[cb.dataset.idxCb] = !cb.checked;
      renderFuturesBody(panel);
    }));
    body.querySelectorAll('[data-use-carry]').forEach(cb => cb.addEventListener('change', () => {
      futures.use[cb.dataset.useCarry] = cb.checked;
      renderFuturesBody(panel);
    }));
    body.querySelectorAll('[data-carry-input]').forEach(el => el.addEventListener('change', () => {
      const [key, product] = el.dataset.carryInput.split('|');
      const v = Number(el.value);
      if (!Number.isFinite(v)) return;
      const ov = futures.overrides[product] || (futures.overrides[product] = {});
      if (key === 'years') {
        ov.years = Math.max(0.5, Math.min(10, v));
        delete futures.window[product];  // 默认窗口跟随新的「过去 N 年」
      } else ov[key] = Math.max(-5, Math.min(20, v));
      loadBasis(panel, true);
    }));
  }

  async function loadBasis(panel, manual) {
    if (futures.loading) return;
    futures.loading = true;
    if (!futures.data) renderFuturesBody(panel);
    const stamp = panel.querySelector('[data-refresh]');
    if (stamp) { stamp.disabled = true; stamp.textContent = '刷新中…'; }
    const params = { years: 3 };
    for (const p of PRODUCT_ORDER) {
      const ov = futures.overrides[p] || {};
      if (ov.rf !== undefined) params[`rf_${p}`] = ov.rf / 100;
      if (ov.div !== undefined) params[`div_${p}`] = ov.div / 100;
      if (ov.years !== undefined) params[`years_${p}`] = ov.years;
    }
    try {
      futures.data = await window.irSystem.derivativesRequest('basis', params);
      futures.error = null;
    } catch (error) {
      futures.error = error.message;
      if (!futures.data) {
        panel.querySelector('.d-body').innerHTML = `<p class="d-empty">基差数据读取失败：${esc(error.message)}</p>`;
      }
    } finally {
      futures.loading = false;
      futures.countdown = AUTO_SECONDS;
      if (panel.isConnected) renderFuturesBody(panel);
    }
  }

  function shanghaiNowParts() {
    const parts = new Intl.DateTimeFormat('en-US', { timeZone: 'Asia/Shanghai', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }).formatToParts(new Date());
    const pick = t => Number((parts.find(p => p.type === t) || {}).value || 0);
    return { h: pick('hour') % 24, m: pick('minute'), s: pick('second') };
  }

  function autoRefreshActive() {
    const status = futures.data && futures.data.status && futures.data.status.code;
    if (status === 'holiday') return false;
    const { h, m } = shanghaiNowParts();
    const minutes = h * 60 + m;
    return minutes >= 9 * 60 + 30 && minutes < AUTO_STOP_MINUTES;  // 09:30–15:10（上海）
  }

  function scheduleFuturesTimer(panel) {
    clearInterval(futures.timer);
    futures.timer = setInterval(() => {
      if (!panel.isConnected || !panel.open) { clearInterval(futures.timer); futures.timer = null; return; }
      const el = panel.querySelector('[data-countdown]');
      if (!autoRefreshActive()) { if (el) el.textContent = '已收盘'; return; }
      futures.countdown -= 5;
      if (futures.countdown <= 0) { loadBasis(panel, false); return; }
      const { h, m, s } = shanghaiNowParts();
      const t = `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
      if (el) el.textContent = `${t} · 于 ${Math.round(futures.countdown)}s 后自动刷新`;
    }, 5000);
  }

  // ---------------------------------------------------------------- Options（VIX）

  // 每个标的时间窗口（双滑块，语义同 Futures）：win[code] = {i0, i1, follow}；
  // follow = 默认「过去 N 年」贴右缘，用户拖动后固定，手动刷新/改年份整体复位。
  function vixWindow(u, n) {
    const w = vixState.win[u.underlying];
    const span = Math.max(20, Math.round((vixState.years || 3) * 250));
    let i0, i1;
    if (!w || w.follow) { i1 = n - 1; i0 = Math.max(0, n - 1 - span); }
    else { i0 = Math.max(0, Math.min(w.i0, n - 2)); i1 = Math.min(n - 1, Math.max(w.i1, i0 + 1)); }
    vixState.win[u.underlying] = { i0, i1, follow: !w || !!w.follow };
    return [i0, i1];
  }

  // 左表按标的物分组：组间插入整行合并的加粗组头条，数据行 = 代码 | 名称 | VIX值 | dVIX | 分位数
  function vixTable(uds) {
    const rows = [];
    let lastGroup = null;
    for (const u of uds) {
      if (u.group !== lastGroup) {
        lastGroup = u.group;
        rows.push(`<tr class="d-vixgroup"><td colspan="5"><b>${esc(u.group || '')}</b></td></tr>`);
      }
      const s = u.stats || {};
      rows.push(`<tr data-vix-row="${esc(u.underlying)}" class="${u.underlying === vixState.selected ? 'd-row-active' : ''}"><td>${esc(u.underlying)}</td>
        <td class="d-muted">${esc(u.kind || '')}</td>
        <td>${fmt(s.current)}</td><td class="${cls(s.d_vix)}">${s.d_vix === null || s.d_vix === undefined ? '—' : `${s.d_vix >= 0 ? '+' : ''}${fmt(s.d_vix)}`}</td>
        <td>${s.percentile === null || s.percentile === undefined ? '—' : pct(s.percentile, 0)}</td></tr>`);
    }
    return `<table class="d-table"><thead><tr><th>代码</th><th>名称</th><th>VIX值</th><th>dVIX</th><th>分位数</th></tr></thead><tbody>${rows.join('')}</tbody></table>`;
  }

  function vixMainChart(u, i0, i1) {
    const pts = u.vix || [];
    const win = pts.slice(i0, i1 + 1);
    if (win.length < 2) return '<p class="d-empty">窗口内样本不足</p>';
    const width = 640, height = 240, L = 44, R = 56, T = 10, B = 22;
    const X = i => L + (i / (win.length - 1)) * (width - L - R);
    const vals = win.map(p => p[1]);
    let lo = Math.min(...vals), hi = Math.max(...vals);
    const pad = (hi - lo) * 0.12 || 1;
    lo -= pad; hi += pad;
    const Y = v => T + (1 - (v - lo) / (hi - lo)) * (height - T - B);
    const grid = [0, 0.25, 0.5, 0.75, 1].map(t => {
      const v = lo + (hi - lo) * t;
      return `<line x1="${L}" x2="${width - R}" y1="${Y(v)}" y2="${Y(v)}" class="d-grid"/><text x="${L - 4}" y="${Y(v) + 3}" text-anchor="end" class="d-axistext">${v.toFixed(1)}</text>`;
    }).join('');
    const vixPath = win.map((p, i) => `${i ? 'L' : 'M'}${X(i).toFixed(1)},${Y(p[1]).toFixed(1)}`).join('');
    let spotPath = '', spotAxis = '';
    const spotMap = new Map(u.spot || []);
    const spotPts = win.map((p, i) => [i, spotMap.get(p[0])]).filter(x => x[1] !== undefined && x[1] !== null);
    if (spotPts.length > 1) {
      const sv = spotPts.map(x => x[1]);
      let slo = Math.min(...sv), shi = Math.max(...sv);
      const spad = (shi - slo) * 0.1 || 1;
      slo -= spad; shi += spad;
      const YS = v => T + (1 - (v - slo) / (shi - slo)) * (height - T - B);
      spotPath = `<path d="${spotPts.map((x, j) => `${j ? 'L' : 'M'}${X(x[0]).toFixed(1)},${YS(x[1]).toFixed(1)}`).join('')}" class="d-line-idx"/>`;
      spotAxis = [0, 0.5, 1].map(t => {
        const v = slo + (shi - slo) * t;
        return `<text x="${width - R + 4}" y="${YS(v) + 3}" class="d-axistext d-axistext-idx">${fmt(v, v > 100 ? 0 : 2)}</text>`;
      }).join('');
    }
    const ticks = [0, 0.25, 0.5, 0.75, 1].map(t => {
      const i = Math.round(t * (win.length - 1));
      return `<text x="${X(i)}" y="${height - 5}" text-anchor="middle" class="d-axistext">${esc(win[i][0].slice(2))}</text>`;
    }).join('');
    return `<svg viewBox="0 0 ${width} ${height}" class="d-chart" preserveAspectRatio="none">${grid}<path d="${vixPath}" class="d-line"/>${spotPath}${spotAxis}${ticks}</svg>`;
  }

  const BRUSH = { width: 640, height: 56, L: 44, R: 56 };
  const brushX = (n, i) => BRUSH.L + (i / (n - 1)) * (BRUSH.width - BRUSH.L - BRUSH.R);

  function vixBrushSvg(u, i0, i1) {
    const pts = u.vix || [];
    if (pts.length < 2) return '';
    const { width, height, L, R } = BRUSH;
    const vals = pts.map(p => p[1]);
    const lo = Math.min(...vals), hi = Math.max(...vals);
    const pad = (hi - lo) * 0.08 || 1;
    const Y = v => 4 + (1 - (v - lo + pad) / (hi - lo + 2 * pad)) * (height - 12);
    const path = pts.map((p, i) => `${i ? 'L' : 'M'}${brushX(pts.length, i).toFixed(1)},${Y(p[1]).toFixed(1)}`).join('');
    return `<svg viewBox="0 0 ${width} ${height}" class="d-brush-svg" preserveAspectRatio="none">
      <path d="${path}" class="d-line d-brush-line"/>
      <rect data-b="dimL" x="${L}" y="0" width="${brushX(pts.length, i0) - L}" height="${height}" class="d-brush-dim"/>
      <rect data-b="dimR" x="${brushX(pts.length, i1)}" y="0" width="${width - R - brushX(pts.length, i1)}" height="${height}" class="d-brush-dim"/>
      <rect data-b="win" x="${brushX(pts.length, i0)}" y="0" width="${brushX(pts.length, i1) - brushX(pts.length, i0)}" height="${height}" class="d-brush-win"/>
      <rect data-b="hl" x="${brushX(pts.length, i0) - 2}" y="0" width="4" height="${height}" class="d-brush-handle"/>
      <rect data-b="hr" x="${brushX(pts.length, i1) - 2}" y="0" width="4" height="${height}" class="d-brush-handle"/>
    </svg>`;
  }

  function updateBrush(panel, u, i0, i1) {
    const n = (u.vix || []).length;
    const set = (name, attrs) => {
      const el = panel.querySelector(`[data-b="${name}"]`);
      if (el) Object.entries(attrs).forEach(([k, v]) => el.setAttribute(k, v));
    };
    const { width, height, L, R } = BRUSH;
    set('dimL', { x: L, width: brushX(n, i0) - L });
    set('dimR', { x: brushX(n, i1), width: width - R - brushX(n, i1) });
    set('win', { x: brushX(n, i0), width: brushX(n, i1) - brushX(n, i0) });
    set('hl', { x: brushX(n, i0) - 2 });
    set('hr', { x: brushX(n, i1) - 2 });
  }

  function selectedUnderlying() {
    const uds = (vixState.data && vixState.data.underlyings) || [];
    return uds.find(u => u.underlying === vixState.selected) || uds[0];
  }

  function drawVixCharts(panel) {
    const u = selectedUnderlying();
    if (!u) return;
    const n = (u.vix || []).length;
    if (n < 2) return;
    const [i0, i1] = vixWindow(u, n);
    const main = panel.querySelector('[data-vix-main]');
    if (main) main.innerHTML = vixMainChart(u, i0, i1);
    updateBrush(panel, u, i0, i1);
  }

  function attachVixBrush(panel) {
    const container = panel.querySelector('[data-vix-brush]');
    if (!container) return;
    let drag = null;
    container.addEventListener('pointerdown', e => {
      const u = selectedUnderlying();
      const n = (u.vix || []).length;
      if (!u || n < 2) return;
      const svg = container.querySelector('svg');
      const rect = svg.getBoundingClientRect();
      const toX = ev => (ev.clientX - rect.left) / rect.width * BRUSH.width;
      const toI = x => Math.round((x - BRUSH.L) / (BRUSH.width - BRUSH.L - BRUSH.R) * (n - 1));
      const x = toX(e);
      let { i0, i1 } = vixState.win[u.underlying] || { i0: 0, i1: n - 1 };
      const w = i1 - i0;
      let mode, grab = 0;
      if (Math.abs(x - brushX(n, i0)) <= 8) mode = 'l';
      else if (Math.abs(x - brushX(n, i1)) <= 8) mode = 'r';
      else if (x > brushX(n, i0) && x < brushX(n, i1)) { mode = 'move'; grab = x - brushX(n, i0); }
      else {  // 点击空白：窗口中心跳到该处并进入拖动
        mode = 'move';
        i0 = Math.max(0, Math.min(n - 1 - w, toI(x) - Math.round(w / 2)));
        i1 = i0 + w;
        grab = (brushX(n, i1) - brushX(n, i0)) / 2;
      }
      vixState.win[u.underlying] = { i0, i1, follow: false };
      drag = { mode, grab };
      container.setPointerCapture(e.pointerId);
      e.preventDefault();
      drawVixCharts(panel);
    });
    container.addEventListener('pointermove', e => {
      if (!drag) return;
      const u = selectedUnderlying();
      const n = (u.vix || []).length;
      const svg = container.querySelector('svg');
      const rect = svg.getBoundingClientRect();
      const x = (e.clientX - rect.left) / rect.width * BRUSH.width;
      const toI = v => Math.round((v - BRUSH.L) / (BRUSH.width - BRUSH.L - BRUSH.R) * (n - 1));
      let { i0, i1 } = vixState.win[u.underlying];
      const w = i1 - i0;
      if (drag.mode === 'move') {
        const ni0 = Math.max(0, Math.min(n - 1 - w, toI(x - drag.grab)));
        i1 = ni0 + w; i0 = ni0;
      } else if (drag.mode === 'l') {
        i0 = Math.max(0, Math.min(i1 - 10, toI(x)));
      } else {
        i1 = Math.min(n - 1, Math.max(i0 + 10, toI(x)));
      }
      vixState.win[u.underlying] = { i0, i1, follow: false };
      drawVixCharts(panel);
    });
    container.addEventListener('pointerup', () => { drag = null; });
    container.addEventListener('pointercancel', () => { drag = null; });
  }

  function renderOptionsBody(panel) {
    const body = panel.querySelector('.d-body');
    if (vixState.loading && !vixState.data) {
      body.innerHTML = '<p class="d-empty">正在构建 VIX 历史（12 个权益类标的、逐日计算，首次约 25–40 分钟，自动续建并显示进度；之后走本地缓存）…</p>';
      return;
    }
    if (!vixState.data) {
      body.innerHTML = `<p class="d-empty">${vixState.error ? `VIX 读取失败：${esc(vixState.error)}` : ''}</p>`;
      return;
    }
    const d = vixState.data;
    const uds = d.underlyings || [];
    if (!uds.length) { body.innerHTML = '<p class="d-empty">无 VIX 数据</p>'; return; }
    if (!uds.some(u => u.underlying === vixState.selected)) vixState.selected = uds[0].underlying;
    const prog = d.building && d.progress
      ? `<span class="d-muted">历史构建 ${Math.round((d.progress.done / Math.max(1, d.progress.total)) * 100)}%，自动续建…</span>` : '';
    // 下拉按标的物分组（optgroup）
    const optgroups = [];
    let lastGroup = null;
    for (const u of uds) {
      if (u.group !== lastGroup) {
        if (lastGroup !== null) optgroups.push('</optgroup>');
        optgroups.push(`<optgroup label="${esc(u.group || '')}">`);
        lastGroup = u.group;
      }
      optgroups.push(`<option value="${esc(u.underlying)}" ${u.underlying === vixState.selected ? 'selected' : ''}>${esc(u.underlying)} · ${esc(u.kind || u.name)}</option>`);
    }
    if (lastGroup !== null) optgroups.push('</optgroup>');
    body.innerHTML = `<div class="d-vixwrap">
      <div class="d-vixleft">
        <div class="d-vixhead"><b class="d-vix-title">VIX</b>
          <label class="d-param">过去 <input data-vix-years type="number" step="0.5" min="0.5" max="10" value="${vixState.years}" style="width:44px"> 年</label>
          <button class="secondary-button" data-vix-refresh>手动刷新</button>${prog}</div>
        ${vixTable(uds)}
      </div>
      <div class="d-vixright">
        <div class="d-vixhead"><select data-vix-underlying>${optgroups.join('')}</select>
          <span class="d-muted">左轴 VIX · 右轴标的 · 全历史自上市日起 · 拖动下方窗口选择区间</span></div>
        <div data-vix-main></div>
        <div data-vix-brush></div>
      </div></div>`;
    const u = selectedUnderlying();
    const n = (u.vix || []).length;
    const [i0, i1] = vixWindow(u, n);
    panel.querySelector('[data-vix-brush]') && (body.querySelector('[data-vix-brush]').innerHTML = vixBrushSvg(u, i0, i1));
    attachVixBrush(panel);
    drawVixCharts(panel);
    body.querySelector('[data-vix-refresh]').addEventListener('click', () => {
      vixState.win = {};  // 手动刷新：滑块复位到「过去 N 年」默认窗口
      loadVix(panel, true);
    });
    body.querySelector('[data-vix-years]').addEventListener('change', ev => {
      vixState.years = Math.max(0.5, Math.min(10, Number(ev.target.value) || 3));
      vixState.win = {};
      loadVix(panel, true);
    });
    body.querySelector('[data-vix-underlying]').addEventListener('change', ev => {
      vixState.selected = ev.target.value;
      renderOptionsBody(panel);
    });
    body.querySelectorAll('[data-vix-row]').forEach(tr => tr.addEventListener('click', () => {
      vixState.selected = tr.dataset.vixRow;
      renderOptionsBody(panel);
    }));
  }

  async function loadVix(panel, manual) {
    if (vixState.loading) return;
    vixState.loading = true;
    if (!vixState.data) renderOptionsBody(panel);
    try {
      const d = await window.irSystem.derivativesRequest('options_vix', { years: vixState.years });
      vixState.data = d;
      vixState.error = null;
      vixState.loading = false;
      if (panel.isConnected) renderOptionsBody(panel);
      if (d.building && panel.isConnected && panel.open) setTimeout(() => loadVix(panel, false), 300);
    } catch (error) {
      vixState.error = error.message;
      vixState.loading = false;
      if (panel.isConnected) renderOptionsBody(panel);
    }
  }

  function openOptions(panel) {
    if (!vixState.data && !vixState.loading) loadVix(panel, false);
    else renderOptionsBody(panel);
  }

  // ---------------------------------------------------------------- entry

  window.renderEquities = (data, childId, heading, children) => {
    const items = Array.isArray(children) && children.length ? children : (Array.isArray(data.sections) ? data.sections : []);
    const openId = childId || 'eq-futures';
    document.querySelector('#workspace').innerHTML = `${heading(data.moduleId, 'Equities', data.dataMode, data.asOf)}
      <section class="industry-panel equities-panels">${items.map(item =>
        `<details class="industry-group equities-panel" data-eq-panel="${esc(item.id)}" ${item.id === openId ? 'open' : ''}>
          <summary><span class="industry-group-name">${esc(item.label)}</span><span class="industry-group-count"></span></summary>
          <div class="industry-group-body equities-body"><div class="d-body"></div></div></details>`).join('')}</section>`;
    items.forEach(item => {
      const panel = document.querySelector(`[data-eq-panel="${item.id}"]`);
      if (!panel) return;
      panel.addEventListener('toggle', () => {
        if (!panel.open) return;
        if (item.id === 'eq-futures') { loadBasis(panel, false); scheduleFuturesTimer(panel); }
        if (item.id === 'eq-options') openOptions(panel);
      });
      if (panel.open) {
        if (item.id === 'eq-futures') { loadBasis(panel, false); scheduleFuturesTimer(panel); }
        if (item.id === 'eq-options') openOptions(panel);
      }
    });
  };
})();
