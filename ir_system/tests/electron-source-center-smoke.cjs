const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { _electron: electron } = require('playwright-core');

(async () => {
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'ir-source-ui-'));
  const archive = path.join(profile, 'synthetic-archive'); fs.mkdirSync(archive);
  const output = path.resolve(__dirname, '../.local/source-center-acceptance'); fs.mkdirSync(output, { recursive: true });
  const executablePath = process.env.IR_SYSTEM_TEST_APP_EXECUTABLE;
  const app = await electron.launch({ ...(executablePath ? { executablePath } : {}), args: executablePath ? [] : [path.resolve(__dirname, '..')],
    env: { ...process.env, IR_SYSTEM_USER_DATA_DIR: profile, IR_SYSTEM_PROVIDER: 'ir_search', IR_SYSTEM_DEVELOPMENT_DEMO: '0', IR_SYSTEM_ARCHIVE_ROOT: '', IR_SYSTEM_IR_SEARCH_PATH: '', IR_SYSTEM_PYTHON: '__missing_python_for_isolated_ui_test__' } });
  try {
    const page = await app.firstWindow(), errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.locator('[data-module="data"]').first().click();
    await page.getByRole('heading', { name: '信源管理', exact: true }).waitFor();
    assert.equal(await page.locator('[data-source-row]').count(), 13);
    assert.equal(await page.locator('.provider-card').count(), 0);
    assert.equal(await page.locator('text=Demo Provider').count(), 0);
    for (const source of ['alphapai', 'gangtise']) assert.equal(await page.locator(`[data-source-row="${source}"] [data-kind="incremental"]`).isDisabled(), true);
    await page.evaluate(async archiveRoot => {
      const b = await window.irSystem.getBootstrap();
      if (b.activeProvider !== 'ir_search') throw new Error('production default must be real engine');
      await window.irSystem.saveProviderConfig({ pythonCommand: '__missing_python_for_isolated_ui_test__', irSearchPath: '', archiveRoot });
    }, archive);
    await page.locator('[data-source-select="ima"]').click();
    await page.getByText('手动填写已确认的真实 ID', { exact: true }).click();
    await page.locator('#source-manual [name="collectionId"]').fill('synthetic_kb');
    await page.locator('#source-manual [name="name"]').fill('离线验收库（非真实信源）');
    await page.getByRole('button', { name: '加入草稿', exact: true }).click();
    await page.locator('[data-draft-check="0"]').check();
    await page.locator('[data-draft-date="0"]').fill('2026-09-01');
    await page.getByRole('button', { name: '保存选择', exact: true }).click();
    await page.locator('#source-dialog').waitFor({ state: 'hidden' });
    const state = await page.evaluate(() => window.irSystem.syncGetState());
    assert.equal(state.settings.policies[0].collectionId, 'synthetic_kb');
    assert.equal(state.jobs.length, 0); assert.equal(state.busy, false);
    await app.evaluate(({ dialog }) => {
      globalThis.__irTestDialogs = [];
      dialog.showMessageBox = async (_window, options) => { globalThis.__irTestDialogs.push(options); return { response: 0 }; };
    });
    await page.locator('[data-source-update="ima"][data-kind="backfill"]').click();
    await page.locator('#source-update [name="start"]').fill('2026-08-01');
    await page.locator('#source-update [name="end"]').fill('2026-08-15');
    assert.ok((await page.locator('#source-dialog').innerText()).includes('不能严格按上述日期过滤'));
    await page.locator('#source-dialog').screenshot({ path: path.join(output, 'history-dialog.png'), scale: 'css' });
    await page.getByRole('button', { name: '确认范围并继续', exact: true }).click();
    await page.locator('#source-dialog').waitFor({ state: 'hidden' });
    const approvals = await app.evaluate(() => globalThis.__irTestDialogs);
    assert.equal(approvals.length, 1);
    assert.ok(approvals[0].detail.includes('2026-08-01 至 2026-08-15'));
    assert.ok(approvals[0].detail.includes('共 1 个已选集合'));
    assert.equal((await page.evaluate(() => window.irSystem.syncGetState())).jobs.length, 0);
    await page.locator('[data-console-tab="settings"]').first().click();
    await page.locator('#console-settings [name="runtime"]').selectOption('custom');
    await page.locator('#console-settings [name="custom"]').fill('/not/executed/cli');
    await page.getByRole('button', { name: '保存 CLI 设置', exact: true }).click();
    assert.equal((await page.evaluate(() => window.irSystem.syncGetState())).consoleSettings.commands.custom, '/not/executed/cli');
    await page.locator('#console-settings [name="runtime"]').selectOption('pi');
    await page.getByRole('button', { name: '保存 CLI 设置', exact: true }).click();
    await page.locator('[data-console-tab="assistant"]').first().click();
    assert.ok((await page.locator('#console-body').innerText()).includes('正文分类、摘要与交互式 CLI 会话待接入'));
    await page.locator('#console-input').fill('/status'); await page.locator('#console-input').press('Enter');
    await page.waitForFunction(() => document.querySelector('#sync-message').textContent.includes('个近期任务'));
    await page.locator('#console-input').fill('echo NEVER_EXECUTE'); await page.locator('#console-input').press('Enter');
    await page.waitForFunction(() => document.querySelector('#sync-message').textContent.includes('输入未执行'));
    await page.locator('[data-source-coverage="ima"]').click();
    assert.ok((await page.locator('#source-dialog').innerText()).includes('日期覆盖无法可靠确认'));
    await page.getByRole('button', { name: '关闭弹窗', exact: true }).click();
    assert.equal((await page.evaluate(() => window.irSystem.syncGetState())).jobs.length, 0);
    // The only download confirmation was cancelled; SDK and CLI execution are unavailable in this profile.
    await page.locator('[data-module="data"]').first().click();
    await page.getByRole('heading', { name: '信源管理', exact: true }).waitFor();
    await page.evaluate(() => { document.querySelector('#workspace').scrollTop = 0; });
    const screenshot = path.join(output, executablePath ? 'source-center-packaged.png' : 'source-center.png');
    await page.screenshot({ path: screenshot, scale: 'css' });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ status: 'passed', packaged: Boolean(executablePath), modelCalls: 0, sourceCalls: 0, profile, screenshot }));
  } finally { await app.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
