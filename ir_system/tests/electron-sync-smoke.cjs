const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { _electron: electron } = require("playwright-core");

(async () => {
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), "ir-sync-ui-"));
  const packagedExecutable = process.env.IR_SYSTEM_TEST_APP_EXECUTABLE;
  const app = await electron.launch({ ...(packagedExecutable ? { executablePath: packagedExecutable } : {}),
    args: packagedExecutable ? [] : [path.resolve(__dirname, "..")],
    env: { ...process.env, IR_SYSTEM_USER_DATA_DIR: profile, IR_SYSTEM_PROVIDER: "demo", IR_SYSTEM_ARCHIVE_ROOT: "", IR_SYSTEM_IR_SEARCH_PATH: "" } });
  try {
    const page = await app.firstWindow();
    const errors = []; page.on("pageerror", e => errors.push(e.message));
    await page.locator('[data-module="data"]').first().click();
    await page.getByRole("heading", { name: "增量采集", exact: true }).waitFor();
    assert.equal(await page.locator('[data-sync-start="incremental"]').innerText(), "同步新增资料");
    await page.getByText("发现／添加订阅", { exact: true }).click();
    await page.locator('#sync-manual [name="provider"]').selectOption("ima");
    await page.locator('#sync-manual [name="collectionId"]').fill("synthetic_kb");
    await page.locator('#sync-manual [name="name"]').fill("离线验收库（非真实信源）");
    await page.getByRole("button", { name: "加入待选择", exact: true }).click();
    if (!await page.locator('[data-policy-mode]').count()) throw new Error(`Policy row missing: ${await page.locator('#sync-message').innerText()} / ${errors.join(',')}`);
    await page.locator('[data-policy-mode]').selectOption("incremental");
    await page.locator('[data-policy-date]').fill("2026-09-01");
    await page.getByRole("button", { name: "保存信源设置（不启动任务）" }).click();
    await page.getByText("已保存，尚未启动下载。", { exact: true }).waitFor();
    const state = await page.evaluate(() => window.irSystem.syncGetState());
    assert.equal(state.settings.policies[0].collectionId, "synthetic_kb");
    assert.equal(state.jobs.length, 0); assert.equal(state.busy, false);
    await page.evaluate(() => document.querySelectorAll('#sync-center details').forEach(d => { d.open = false; }));
    // Snapshot uses only a synthetic local profile; no network buttons are clicked.
    const output = path.resolve(__dirname, "../.local/sync-acceptance");
    fs.mkdirSync(output, { recursive: true });
    const screenshot = path.join(output, packagedExecutable ? "sync-center-packaged.png" : "sync-center.png");
    await page.locator("#sync-center").screenshot({ path: screenshot });
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ status: "passed", packaged: Boolean(packagedExecutable), modelCalls: 0, sourceCalls: 0, profile, screenshot }));
  } finally { await app.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
