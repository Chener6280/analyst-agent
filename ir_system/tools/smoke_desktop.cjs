// Opt-in desktop acceptance against a configured LOCAL archive. No downloads.
const { _electron } = require("playwright-core");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

(async () => {
  if (!process.env.IR_SYSTEM_ARCHIVE_ROOT || !process.env.IR_SYSTEM_PYTHON) throw new Error("Set archive root and isolated Python first");
  const appRoot = path.resolve(__dirname, "..");
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), "ir-system-ui-"));
  const output = path.join(appRoot, ".local");
  fs.mkdirSync(output, { recursive: true });
  let desktop;
  try {
    const executablePath = process.env.IR_SYSTEM_APP_EXECUTABLE;
    desktop = await _electron.launch({ executablePath, args: [...(executablePath ? [] : [appRoot]), `--user-data-dir=${profile}`], env: { ...process.env, IR_SYSTEM_PROVIDER: "ir_search" } });
    const page = await desktop.firstWindow();
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.locator('[data-module="data"]').first().click();
    await page.locator(".archive-metrics").waitFor();
    assert.match(await page.locator(".archive-status").first().innerText(), /下载成功 ≠ 解析完整 ≠ 全年覆盖/);
    await page.locator("[data-audio-library]").waitFor();
    await page.locator(".archive-status").first().scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.join(output, "data-center.png") });
    await page.locator('[data-module="research"]').first().click();
    await page.locator("#archive-query").fill("宏观");
    await page.locator("#archive-source").selectOption("wisburg");
    await page.locator('#archive-search-form button').click();
    await page.waitForFunction(() => document.querySelector("#archive-source")?.value === "wisburg" && [...document.querySelectorAll(".archive-result-meta")].every(e => e.textContent.includes("wisburg")));
    await page.locator(".archive-result").first().click();
    await page.locator(".archive-text").waitFor();
    assert.match(await page.locator("#archive-reader").innerText(), /供应商摘要，不是原文/);
    await page.screenshot({ path: path.join(output, "research-library.png") });
    await page.locator("#archive-start").fill("2026-09-01");
    await page.locator('#archive-search-form button').click();
    assert.equal(await page.locator("#archive-end").evaluate(e => e.validity.valid), false);
    await page.locator("#archive-end").fill("2026-09-30");
    await page.locator('#archive-search-form button').click();
    await page.locator(".archive-result").first().waitFor();
    await page.locator("#archive-query").fill('<img src=x onerror="window.pwned=1">');
    await page.locator('#archive-search-form button').click();
    await page.getByText("没有匹配结果", { exact: true }).waitFor();
    assert.equal(await page.evaluate(() => window.pwned), undefined);
    const response = await page.evaluate(() => window.irSystem.archiveRequest("search", { kind: "attachment", limit: 1 }));
    assert.equal(response.items[0].kind, "attachment");
    assert.equal(response.items[0].raw_path, undefined);
    await page.locator('[data-module="data"]').first().click();
    await page.locator("[data-audio-library]").click();
    assert.equal(await page.locator("#archive-kind").inputValue(), "audio");
    await page.locator("#archive-query").fill("盘前早报 20260908.mp3");
    await page.locator('#archive-search-form button').click();
    await page.getByText("盘前早报 20260908.mp3", { exact: true }).first().click();
    await page.locator("#archive-reader").getByText("盘前早报 20260908.mp3", { exact: true }).waitFor();
    const audioRow = await page.evaluate(() => window.irSystem.archiveRequest("search", { kind: "audio", query: "盘前早报 20260908.mp3", limit: 1 }));
    if (audioRow.items[0].machine_transcribed) {
      await page.locator("#archive-reader").getByText(/火山机器转写，需听原音核对/).waitFor();
    }
    await page.screenshot({ path: path.join(output, "audio-library.png") });
    await desktop.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].setSize(1060, 720));
    await page.locator('[data-module="data"]').first().click();
    await page.locator(".archive-metrics").waitFor();
    await page.locator(".archive-status").first().scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.join(output, "data-center-small.png") });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ status: "passed", checks: ["status", "literal_search", "provider_filter", "abstract_label", "date_validation", "escaped_text", "attachment_search", "audio_queue", "audio_filter", "audio_reader", "small_window"], screenshots: 4 }));
  } finally {
    if (desktop) await desktop.close();
    fs.rmSync(profile, { recursive: true, force: true });
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
