// EQ 模块（股指期货基差 + 期权波动率曲面）的桌面交互冒烟。
// 真实链路：Renderer → preload → IPC → provider registry → 子进程桥 → ir_search 公开 SDK。
// 需要可用的 Python + ir_search（环境变量 IR_SYSTEM_PYTHON / IR_SYSTEM_IR_SEARCH_PATH 注入，文件不含本机路径）。
// 运行：IR_SYSTEM_PYTHON=/path/to/python IR_SYSTEM_IR_SEARCH_PATH=/path/to/ir_search node tests/electron-derivatives-smoke.cjs
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { _electron: electron } = require("playwright-core");

(async () => {
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), "ir-derivatives-"));
  const archive = path.join(profile, "archive");
  fs.mkdirSync(archive);
  const output = path.resolve(__dirname, "../.local/derivatives-acceptance");
  fs.mkdirSync(output, { recursive: true });
  const executablePath = process.env.IR_SYSTEM_TEST_APP_EXECUTABLE;
  const app = await electron.launch({
    ...(executablePath ? { executablePath } : {}),
    args: executablePath ? [] : [path.resolve(__dirname, "..")],
    env: {
      ...process.env,
      IR_SYSTEM_USER_DATA_DIR: profile,
      IR_SYSTEM_PROVIDER: "ir_search",
      IR_SYSTEM_ARCHIVE_ROOT: archive,
      IR_SYSTEM_PYTHON: process.env.IR_SYSTEM_SMOKE_PYTHON || process.env.IR_SYSTEM_PYTHON || "python3",
      // 冒烟限速：VIX 只构建 2 个标的且起点上移（生产默认 12 个标的、自各品种上市日全历史）
      IR_SYSTEM_VIX_UNDERLYINGS: "510300.SH,000300.SH",
      IR_SYSTEM_VIX_SINCE: "2026-05-01",
      ...(process.env.IR_SYSTEM_IR_SEARCH_PATH ? { IR_SYSTEM_IR_SEARCH_PATH: process.env.IR_SYSTEM_IR_SEARCH_PATH } : {}),
    },
  });
  try {
    const page = await app.firstWindow();
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));

    await page.locator('[data-module="eq"]').first().click();
    await page.locator('[data-eq-panel="eq-futures"]').waitFor();
    await page.locator('[data-eq-panel="eq-options"]').waitFor();

    // ---- Futures：四行布局（上证50/沪深300/中证500/中证1000），左表右图，真实数据首次约 20 秒
    await page.waitForSelector(".d-futrow", { timeout: 240000 });
    assert.equal(await page.locator(".d-futrow").count(), 4);
    const futBody = '[data-eq-panel="eq-futures"] .d-body';
    const latestText = await page.locator(futBody).innerText();
    let at = -1;
    for (const name of ["上证50", "沪深300", "中证500", "中证1000"]) {
      const i = latestText.indexOf(name);
      assert.ok(i > at, `futures row order broken at: ${name}`);
      at = i;
    }
    for (const word of ["代码", "点位", "涨跌幅", "基差", "d基差", "年化基差", "分位数", "use", "无风险利率", "分红率", "过去", "手动刷新"]) {
      assert.ok(latestText.includes(word), `futures panel missing: ${word}`);
    }
    for (const gone of ["采样", "窗口", "口径与诊断", "IF/IH/IC/IM"]) {
      assert.ok(!latestText.includes(gone), `futures panel should not show: ${gone}`);
    }
    // 表内首行是指数行情行
    assert.ok((await page.locator(".d-futrow").first().locator("tr.d-index-row td").first().innerText()).includes("000016.SH"));
    // 右图默认只显示 下季 + 指数 = 2 条线；勾选 当月 后 3 条
    const rowPaths = page.locator(".d-futrow").first().locator("svg.d-chart path");
    assert.equal(await rowPaths.count(), 2);
    await page.locator('[data-slot-cb="IH|当月"]').check();
    assert.equal(await rowPaths.count(), 3);
    await page.locator('[data-slot-cb="IH|当月"]').uncheck();
    assert.equal(await rowPaths.count(), 2);
    // 全历史双滑块：四个品种各一条 brush；拖右柄缩小窗口，手动刷新后复位
    assert.equal(await page.locator("[data-fut-brush] svg").count(), 4);
    const ihWin = page.locator('[data-fut-brush="IH"] [data-b="win"]');
    const ihBrushBox = await page.locator('[data-fut-brush="IH"] svg').boundingBox();
    const fw = Number(await ihWin.getAttribute("width"));
    const fy = ihBrushBox.y + ihBrushBox.height / 2;
    await page.mouse.move(ihBrushBox.x + ihBrushBox.width * 0.92, fy);  // 右柄（默认窗口贴右缘）
    await page.mouse.down();
    await page.mouse.move(ihBrushBox.x + ihBrushBox.width * 0.45, fy, { steps: 5 });
    await page.mouse.up();
    const fwResized = Number(await ihWin.getAttribute("width"));
    assert.ok(fwResized < fw - 5, `futures brush resize: ${fw} -> ${fwResized}`);
    // use 切换为即时前端口径切换（不重新取数）：第一行基差单元格文本变化
    const basisCell = page.locator(".d-futrow").first().locator("tbody tr").nth(1).locator("td").nth(3);
    const beforeUse = await basisCell.innerText();
    await page.locator('[data-use-carry="IH"]').uncheck();
    await page.waitForFunction((args) => {
      const el = document.querySelector(".d-futrow tbody tr:nth-child(2) td:nth-child(4)");
      return el && el.textContent !== args.before && el.textContent !== "—";
    }, { before: beforeUse }, { timeout: 10000 });
    await page.locator('[data-use-carry="IH"]').check();
    await page.locator('[data-eq-panel="eq-futures"]').screenshot({ path: path.join(output, "eq-futures-latest.png") });

    // 倒计时：交易日 09:30–15:10（上海）显示时钟与倒计时，否则显示已收盘
    const statusText = await page.locator('[data-eq-panel="eq-futures"] .d-status').first().innerText();
    const shNow = new Date(new Date().toLocaleString("en-US", { timeZone: "Asia/Shanghai" }));
    const shMinutes = shNow.getHours() * 60 + shNow.getMinutes();
    const inSession = !statusText.includes("休市") && shMinutes >= 9 * 60 + 30 && shMinutes < 15 * 60 + 10;
    if (inSession) {
      await page.waitForFunction(
        () => /于 \d+s 后自动刷新/.test(document.querySelector('[data-eq-panel="eq-futures"] [data-countdown]')?.textContent || ""),
        null, { timeout: 20000 });
    } else {
      await page.waitForFunction(
        () => document.querySelector('[data-eq-panel="eq-futures"] [data-countdown]')?.textContent.includes("已收盘"),
        null, { timeout: 20000 });
    }

    // 手动刷新：采样时间（data-asof）必须更新；滑块复位回「过去 N 年」默认窗口
    const before = await page.locator('[data-eq-panel="eq-futures"] .d-statusline').getAttribute("data-asof");
    await page.locator('[data-refresh]').first().click();
    await page.waitForFunction((old) => {
      const el = document.querySelector('[data-eq-panel="eq-futures"] .d-statusline');
      return el && el.dataset.asof !== old && document.querySelector(".d-futrow");
    }, before, { timeout: 240000 });
    const fwAfterRefresh = Number(await page.locator('[data-fut-brush="IH"] [data-b="win"]').getAttribute("width"));
    assert.ok(Math.abs(fwAfterRefresh - fw) < 2, `refresh should reset brush: ${fw} -> ${fwAfterRefresh}`);

    // ---- Options：VIX 面板（真实数据；隔离 profile 首次构建，把窗口缩到 0.5 年提速，自动续建）
    await page.locator('[data-eq-panel="eq-options"] > summary').click();
    await page.waitForSelector('[data-vix-years]', { timeout: 420000 });
    await page.locator('[data-vix-years]').fill("0.5");
    await page.locator('[data-vix-years]').dispatchEvent("change");
    await page.waitForFunction(() => {
      const el = document.querySelector('[data-eq-panel="eq-options"] .d-body');
      return el && el.textContent.includes("510300.SH") && !el.textContent.includes("自动续建")
        && el.querySelector("[data-vix-main] svg path");
    }, null, { timeout: 900000 });
    const vixText = await page.locator('[data-eq-panel="eq-options"] .d-body').innerText();
    for (const word of ["VIX", "代码", "名称", "VIX值", "dVIX", "分位数", "过去", "手动刷新", "510300.SH", "000300.SH", "沪ETF", "中金所指数"]) {
      assert.ok(vixText.includes(word), `vix panel missing: ${word}`);
    }
    assert.equal(await page.locator("[data-vix-row]").count(), 2);
    // 两个冒烟标的同属「沪深300」组 → 一个加粗组头条
    assert.equal(await page.locator(".d-vixgroup").count(), 1);
    assert.ok((await page.locator(".d-vixgroup").first().innerText()).includes("沪深300"));
    assert.ok((await page.locator("[data-vix-main] svg path").count()) >= 2);  // VIX + 标的
    assert.equal(await page.locator("[data-vix-underlying] option").count(), 2);
    // 标的切换
    await page.locator("[data-vix-underlying]").selectOption("510300.SH");
    await page.waitForFunction(() => document.querySelector('[data-eq-panel="eq-options"] [data-vix-row]')?.classList.contains("d-row-active"), null, { timeout: 10000 });
    // 拖动时间窗口：以选择框的 DOM 属性断言（先拖右柄缩小，再整体右移）
    // 注意：Futures 面板展开时本面板在视口下方，brush 必须先滚入视口才能接收鼠标事件
    await page.waitForSelector('[data-vix-brush] [data-b="win"]', { timeout: 10000 });
    await page.locator("[data-vix-brush] svg").scrollIntoViewIfNeeded();
    const winAttr = a => page.locator('[data-vix-brush] [data-b="win"]').getAttribute(a);
    const widthBefore = Number(await winAttr("width"));
    const brushBox = await page.locator("[data-vix-brush] svg").boundingBox();
    const by = brushBox.y + brushBox.height / 2;
    await page.mouse.move(brushBox.x + brushBox.width * 0.90, by);  // 右柄（X(i1)≈91% 处）
    await page.mouse.down();
    await page.mouse.move(brushBox.x + brushBox.width * 0.55, by, { steps: 5 });
    await page.mouse.up();
    const widthResized = Number(await winAttr("width"));
    assert.ok(widthResized < widthBefore - 5, `brush resize: ${widthBefore} -> ${widthResized}`);
    const xBefore = Number(await winAttr("x"));
    await page.mouse.move(brushBox.x + brushBox.width * 0.30, by);  // 窗口内部整体右移
    await page.mouse.down();
    await page.mouse.move(brushBox.x + brushBox.width * 0.50, by, { steps: 5 });
    await page.mouse.up();
    const xMoved = Number(await winAttr("x"));
    assert.ok(xMoved > xBefore + 5, `brush move: ${xBefore} -> ${xMoved}`);
    await page.locator('[data-eq-panel="eq-options"]').screenshot({ path: path.join(output, "eq-options-vix.png") });

    assert.deepEqual(errors, []);
    console.log("electron-derivatives-smoke: PASS");
  } finally {
    await app.close();
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
