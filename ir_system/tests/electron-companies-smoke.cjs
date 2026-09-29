const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { _electron: electron } = require('playwright-core');

// Offline by default. With IR_COMPANIES_SMOKE_PYTHON and IR_COMPANIES_SMOKE_IR_SEARCH the
// page renders the real ir_search capability registration; no data or network request is made.
const python = process.env.IR_COMPANIES_SMOKE_PYTHON || '';
const irSearch = process.env.IR_COMPANIES_SMOKE_IR_SEARCH || '';
const connected = Boolean(python && irSearch);
const MARKETS = ['A_SHARE', 'HK', 'US'];
const SECTIONS = ['search', 'financials', 'filings', 'events', 'research'];

(async () => {
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'ir-companies-ui-'));
  const output = path.resolve(__dirname, '../.local/companies-tabs-acceptance'); fs.mkdirSync(output, { recursive: true });
  const mode = connected ? 'connected' : 'offline';
  const launch = () => electron.launch({ args: [path.resolve(__dirname, '..')],
    env: { ...process.env, IR_SYSTEM_USER_DATA_DIR: profile, IR_SYSTEM_PROVIDER: 'ir_search', IR_SYSTEM_DEVELOPMENT_DEMO: '0', IR_SYSTEM_ARCHIVE_ROOT: '',
      IR_SYSTEM_IR_SEARCH_PATH: irSearch, IR_SYSTEM_PYTHON: connected ? python : '__missing_python_for_isolated_ui_test__' } });
  const errors = [];
  const screenshots = [];
  const open = async app => {
    const page = await app.firstWindow();
    page.on('pageerror', e => errors.push(e.message));
    await page.locator('[data-module="companies"]').first().click();
    await page.getByRole('tablist', { name: '上市地' }).waitFor();
    await page.addStyleTag({ content: '*, *::before, *::after { transition: none !important; animation: none !important; }' });
    return page;
  };
  const selected = page => page.locator('[role="tab"][aria-selected="true"]').getAttribute('data-company-market');

  let app = await launch();
  try {
    let page = await open(app);
    assert.equal(await page.getByRole('heading', { level: 1 }).innerText(), 'Companies');
    assert.deepEqual(await page.getByRole('tab').evaluateAll(els => els.map(e => e.children[1].textContent)), ['A股', '港股', '美股']);
    assert.equal(await selected(page), 'A_SHARE');
    assert.equal(await page.locator('.company-intro').count(), 0, 'entities intro box should be removed');
    assert.equal(await page.locator('#company-panel .diagnostics').count(), 0, 'DATA DIAGNOSTICS box should be removed');
    const data = await page.evaluate(() => window.irSystem.getModuleData('companies'));
    const mapping = data.providerDetails?.markets;
    assert.equal(Array.isArray(mapping), connected);

    for (const market of MARKETS) {
      await page.locator(`#company-tab-${market}`).click();
      assert.equal(await selected(page), market);
      assert.equal(await page.locator('.loading-state').count(), 0);
      assert.equal(await page.locator('#company-panel').getAttribute('aria-labelledby'), `company-tab-${market}`);
      if (market === 'A_SHARE') {
        assert.equal(await page.locator('#company-panel [data-company-section]').count(), 0, 'A股 不再渲染 5 个能力 box');
        assert.equal(await page.locator('#company-panel .industry-group').count(), 8, 'A股 应有 8 个行业分组');
        assert.equal(await page.locator('#company-panel .industry-sub').count(), 31, 'A股 应有 31 个申万一级行业');
        const panelWidth = await page.locator('.industry-panel').evaluate(el => el.clientWidth);
        for (const width of await page.locator('.industry-group').evaluateAll(els => els.map(el => el.clientWidth))) {
          assert.ok(Math.abs(width - panelWidth) <= 4, `行业分组应占满整行 (group=${width} panel=${panelWidth})`);
        }
        assert.deepEqual(await page.locator('#company-panel .industry-group-name').allInnerTexts(), ['TMT', '资源', '制造', '周期', '消费', '医药', '金融', '综合']);
        await page.locator('#company-panel .industry-group', { has: page.locator('.industry-group-name', { hasText: 'TMT' }) }).locator('summary').first().click();
        await page.locator('#company-panel .industry-sub', { hasText: '电子' }).locator('summary').first().click();
        const matrix = page.locator('#company-panel .industry-sub', { hasText: '电子' }).locator('.industry-matrix');
        assert.deepEqual((await matrix.locator('thead th').allInnerTexts()).map(s => s.trim()), ['股票', '公告', '新闻', '研报', '电话会', '作文']);
        assert.equal(await matrix.locator('tbody tr').count(), 3, '电子应列 3 只示意股');
      } else {
        const expected = mapping?.find(m => m.id === market);
        for (const id of SECTIONS) {
          const card = page.locator(`#company-panel [data-company-section="${id}"]`);
          const want = expected ? expected.sections.find(s => s.id === id) : { status: 'unavailable', sources: [] };
          assert.equal((await card.locator('.status-badge').innerText()).toLowerCase(), want.status);
          const text = await card.innerText();
          for (const src of want.sources) assert.ok(text.includes(src.provider), `${market}/${id} missing ${src.provider}`);
          assert.equal(await card.locator('.company-sources li').count(), want.sources.length);
        }
      }
      const file = path.join(output, `${mode}-${market}.png`);
      await page.screenshot({ path: file, scale: 'css' });
      screenshots.push(file);
    }

    await page.locator('#company-tab-US').focus();
    for (const [key, market] of [['ArrowRight', 'A_SHARE'], ['ArrowLeft', 'US'], ['Home', 'A_SHARE'], ['End', 'US'], ['ArrowLeft', 'HK']]) {
      await page.keyboard.press(key);
      assert.equal(await selected(page), market);
      assert.equal(await page.evaluate(() => document.activeElement.dataset.companyMarket), market);
    }

    await page.locator('[data-module="overview"]').first().click();
    await page.getByRole('heading', { name: 'Global Research Monitor' }).waitFor();
    await page.locator('[data-module="companies"]').first().click();
    await page.getByRole('tablist', { name: '上市地' }).waitFor();
    assert.equal(await selected(page), 'HK');

    await page.keyboard.press('Meta+k');
    await page.locator('#command-input').fill('美股');
    await page.locator('[data-command-parent="companies"][data-command-child="companies-us"]').click();
    await page.getByRole('tablist', { name: '上市地' }).waitFor();
    assert.equal(await selected(page), 'US');

    await page.locator('[data-company-section="research"] [data-module="research"]').click();
    await page.getByRole('heading', { name: '本地资料库', level: 1 }).waitFor();

    await app.close();
    app = await launch();
    page = await open(app);
    assert.equal(await selected(page), 'US');

    await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].setSize(1060, 720));
    await page.waitForFunction(() => window.innerWidth <= 1060);
    assert.ok(await page.evaluate(() => {
      const w = document.querySelector('#workspace');
      return document.documentElement.scrollWidth <= window.innerWidth && w.scrollWidth <= w.clientWidth;
    }), 'horizontal overflow at minimum window size');
    const small = path.join(output, `${mode}-US-min-window.png`);
    await page.screenshot({ path: small, scale: 'css' });
    screenshots.push(small);

    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ status: 'passed', mode, profile, screenshots }));
  } finally { await app.close().catch(() => {}); }
})().catch(e => { console.error(e); process.exitCode = 1; });
