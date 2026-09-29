# ir_system

`ir_system` 是一个本地优先、跨资产的桌面投研工作台。第一版提供独立桌面外壳、统一业务导航、数据能力诊断，以及与 `ir_search` 隔离的可插拔 Provider 接口。

项目还包含独立的 `zsxq_web` 网页归档适配器。它只处理“会员当前有效、Skill API 未开通、且星主允许下载”的知识星球，不修改 `ir_search`，也不尝试绕过到期或下载限制。

## 当前界面

- Overview
- Macro，包括 `Macro → Asset` 与 `Macro → Industry`
- EQ：Futures（IH/IF/IC/IM 股指期货基差监控，真实行情，盘中每 5 分钟自动刷新并可手动刷新）与 Options（权益标的 model-free VIX：左表各标的 VIX值/dVIX/分位数，右图 VIX×标的双轴走势与可拖动时间窗口，Wind 日终链本地计算）
- FI，包括 Rates、Credit、Bonds、Funds & ETFs、Derivatives
- FX，包括 Spot、Forwards & Swaps、Options、Funds & ETFs
- COMDTY，包括 Energy、Metals、Agriculture、Funds & ETFs、Derivatives
- Companies，分 A股 / 港股 / 美股 三个 tab，按市场显示公司检索、财务、披露、事件与相关研究的已注册能力
- Research
- Calendar
- Watchlists
- Data Center

第一版默认使用明确标记的 Demo Provider。选择 `ir_search` 后，Data Center 会读取其能力目录并诚实显示 ready、partial、planned 或 unavailable；尚未完成数据映射的页面保持空状态。

本地资料库已接通：Research 可搜索、筛选与阅读真实归档，Data Center 可查看采集/解析状态并有界更新索引。原件只读，摘要不冒充全文，默认不联网或上传 OCR。配置、迁移、验收口径及低成本 Agent 操作合同见 [本地资料库说明](docs/LOCAL_ARCHIVE.md)。BrowserSkill 当前只在隔离试验阶段，见 [试验状态](docs/BROWSERSKILL_TRIAL.md)。

音频使用独立队列与存储副本；经明确授权后，可复用 ir_search 的火山语音接口分段转写、断点续传并记录逐段耗时。普通解析、搜索和阅读不会触发转写费用。操作合同见 [音频归档与转写](docs/LOCAL_AUDIO.md)。
后续 Agent 的固定执行顺序是：先完成文字及非音频附件的下载、解析与入库，再下载音频，最后转写音频并入库；不是先把音频预下载。阶段验收和下载器过滤限制见本地资料库操作合同。

## 与 ir_search 的隔离

Electron 应用不会导入 `ir_search`，也不会读取它的内部模块。两者通过 `ir-system-provider/v1` JSON 协议通信：

```text
Renderer → Preload API → Provider Registry → Subprocess Provider
                                             ↓
                                  adapters/ir_search_bridge.py
                                             ↓
                                          ir_search
```

只有 `adapters/ir_search_bridge.py` 了解 `ir_search` 的公共 Python API。未来 `ir_search` 发生变化时，优先只修改或替换该适配器；导航、桌面端、本地配置和其他 Provider 不需要跟随重写。

## EQ 衍生品模块

`adapters/ir_derivatives/` 是纯计算包（不导入 ir_search，数据由桥接层注入），向桌面提供三个方法：

- `derivatives.basis`：上证50/沪深300/中证500/中证1000（IH/IF/IC/IM）基差监控，四行布局：左表（代码/点位/涨跌幅/基差/d基差/年化基差率/分位数，首行为指数行情行），右图（当月/下月/当季/下季四条年化基差线 + 标的指数细线右轴，checkbox 开关，默认只显示下季与指数），图下方为全历史双滑块（默认窗口 = 左表「过去 N 年」，可拖动查看更长的上市全历史，手动刷新复位）。指数实时水平用新浪分钟线（AKShare，延迟未核实），期货最新价用 Fiona 快照；取不到时回落到 Wind 日终收盘。历史为全历史（自各品种上市日：IF 2010-04-16、IH/IC 2015-04-16、IM 2022-07-22），EOD 收盘一次性全量回建后长期缓存在 userData/derivatives-cache（basis-eod-v1.json，缓存记录覆盖的品种/指数集合，请求超出即整窗重拉），每次调用只补最近约 10 天尾部；分位数窗口默认过去 3 年（750 个交易日，每个品种 0.5–10 年可调）。每行参数：use 勾选按持有成本调整基差（基差 + 指数×(无风险利率−分红率)×剩余天数/365，即 F*−期货，勾选/取消为前端即时口径切换）；无风险利率默认取 Wind SHIBOR_3M(10) 最新值（3 个月 Shibor 过去 10 个数据平均），分红率默认取 Wind 指数滚动股息率最近可得值，两者可按品种手动覆盖。盘中 09:30–15:10（Asia/Shanghai）每 5 分钟自动刷新并显示时钟与倒计时，其余时间显示已收盘、不自动刷新；手动刷新随时可用；页面折叠或离开后停止计时器。
- `derivatives.options_vix`：全部 12 个权益类期权标的的 model-free VIX，按标的物分组展示——上证50（510050 沪ETF、000016 中金所HO）、沪深300（510300 沪ETF、159919 深ETF、000300 中金所IO）、中证500（510500、159922）、中证1000（000852 中金所MO）、科创板50（588000 华夏、588080 易方达）、创业板（159915）、深证100（159901）。算法为 CBOE 白皮书方差互换公式：取剩余 ≥8 个自然日的最近两个到期，远期用平价关系（|C−P| 最小行权价），OTM 取价用有成交合约收盘价（Wind 链无买卖盘，替代零买价截断），T₁σ₁²/T₂σ₂² 插值到 30 天 ×100；利率用当日 SHIBOR_3M(10)。有效行权价 <6 的日期留空不编造。历史按标的按日缓存在 userData/derivatives-cache（vix-v1-*.json），**自各品种期权上市日起全量构建**（510050 自 2015-02-09，IO/159919 自 2019-12-23，MO 自 2022-07-22 等）；链按交易所分块拉取（同一交易所的标的共享分块，不重复取数），每次调用最多补 2 个 ≤31 天分块（按交易所轮转），前端自动续建并显示进度；早于各所期权业务开办日（SSE 2015-02-09、SZSE/CFFEX 2019-12-23）的空分块按空值落盘，之后的空分块视为可疑故障不落缓存、下轮重试。环境变量 IR_SYSTEM_VIX_UNDERLYINGS（逗号分隔标的代码）与 IR_SYSTEM_VIX_SINCE（YYYY-MM-DD，构建起点上移）仅供测试/诊断。界面：左侧分组标的列表（组头条加粗合并；数据行 = 代码/名称/VIX值/dVIX/分位数，「过去 N 年」只作用于分位数与 dVIX 统计窗口），右侧主图（左轴 VIX、右轴标的）为全历史 + 下方双滑块窗口刷选（默认窗口 = 过去 N 年贴右缘，拖动后固定，手动刷新复位）。
- `derivatives.options_catalog` / `derivatives.options_surface`：波动率曲面标定引擎（eSSVI/SVI/去美式化）保留为版本化 API，当前未挂载界面。

时间轴用方差时间 τ：交易日权重 1，非交易日权重 ω_n（由历史收盘对数收益方差回归估计，每日缓存到 userData 下的 derivatives-cache；估计失败时回落 0.1 并标注）。历史链按日缓存；当日数据不缓存。口径与诊断在页面底部逐项列出。

参考：`tests/test_ir_derivatives.py`（纯合成数据单元测试）、`tests/derivatives-plumbing.test.js`（桌面管道）、`tests/electron-derivatives-smoke.cjs`（真实数据桌面冒烟，需本机配置好 ir_search 后运行）。

## 本机开发

需要 Node.js 22 或兼容版本：

```bash
npm install
npm start
```

检查代码与 Provider 契约：

```bash
npm run check
```

## 连接 ir_search

应用启动后进入 `Data Center`：

1. 填写本机 Python 命令，通常为 `python3`。
2. 填写本机 `ir_search` 仓库或安装目录的绝对路径；如果已安装为 Python 包，可以留空。
3. 点击 `SAVE & PROBE`。
4. 当状态为 `ready` 后选择 `USE PROVIDER`。

也可以在开发时使用环境变量：

```bash
IR_SYSTEM_PROVIDER=ir_search \
IR_SYSTEM_IR_SEARCH_PATH=/path/to/ir_search \
npm start
```

凭证仍由 `ir_search` 自己的私有配置管理。`ir_system` 不保存、复制或打包供应商密钥。

## 知识星球网页归档

`zsxq_web` 是确定性的命令行工具，Codex、Claude 或低成本 Agent 都可以调用。Agent 不需要理解网页或处理 Cookie：每次下载前，工具会重新扫描全部星球、核对会员到期日、真实探测 Skill API、检查下载策略，然后生成固定任务。

```bash
# 环境检查
npm run zsxq-web -- doctor --zsxq-cli /absolute/path/to/zsxq-cli

# 重扫全部星球并准备一个有界任务
npm run zsxq-web -- prepare \
  --zsxq-cli /absolute/path/to/zsxq-cli \
  --archive-root /absolute/path/to/ir_archive \
  --group-id 51122185284184 \
  --start 2026-09-18 --end 2026-09-24

# 推荐给低成本 Agent：一次完成全量扫描、计划和断点归档
npm run zsxq-web -- backfill \
  --zsxq-cli /absolute/path/to/zsxq-cli \
  --archive-root /absolute/path/to/ir_archive \
  --group-id 51122185284184 \
  --start 2026-09-18 --end 2026-09-24

# 首次使用时，由用户本人扫码登录专用 Chrome 配置
npm run zsxq-web -- login --group-id 51122185284184

# 执行任务；要求 prepare 的完整扫描不超过15分钟，并从检查点续传
npm run zsxq-web -- run \
  --zsxq-cli /absolute/path/to/zsxq-cli \
  --plan /absolute/path/to/plan.json
```

网页归档写入 `<archive-root>/zsxq_web/`，与现有 SQLite 归档隔离。订阅快照及任务计划分别写入 `<archive-root>/subscriptions/` 和 `<archive-root>/plans/`。凭据只保留在系统钥匙串和专用浏览器配置中；快照、日志和清单不会保存 Cookie、Token 或签名下载地址。

给 Agent 使用时，优先调用仓库内的 `skills/zsxq-web-archive/scripts/zsxq_web.py`。它提供稳定 JSON 输出、固定退出码、单进程锁、断点和失败停止规则。

浏览器优先使用本机已安装、与 Playwright 配套的 Chromium / Chrome for Testing，找不到时才使用系统 Chrome；`--chrome-path` 可覆盖选择。macOS 默认打开专用浏览器窗口（本机 Chrome 153 无头模式实测发生原生崩溃），任务运行期间请保持窗口打开。原专用配置中的有效登录继续使用，无需从 Safari 导出登录信息。`ZSXQ_WEB_HEADLESS=1` 仅供维护者重新验证无头兼容性。

已进入执行阶段的中断会保存失败环节、脱敏异常、检查点及 manifest。已下载附件续传前校验 SHA-256 后复用。`attachments_this_run` 是本轮统计，`archive_inventory` 是整个星球的历史存量，不可混用。`partial` 不等于故障，也不等于完整：低成本 Agent 只在预算用尽且没有失败时自动继续；其余情况按 Skill 规则停止报告。

年度任务的修复验证和续传交接见 [网页归档修复记录](docs/ZSXQ_WEB_RECOVERY.md)。

## 在其他电脑安装

应用本身可以在没有 `ir_search` 的电脑上运行，此时使用 Demo Provider。需要真实数据时，在目标电脑另外安装或放置 `ir_search`，然后通过 Data Center 配置路径。

在相应操作系统上构建安装包：

```bash
npm run dist:mac
npm run dist:win
npm run dist:linux
```

产物写入 `release/`。桌面程序使用 Electron 的系统级用户目录保存本机配置，不写入应用安装目录，也不依赖开发电脑的绝对路径。

一般应在目标操作系统上构建该系统的安装包。第一版未配置代码签名，因此对外分发前还需要增加 macOS notarization 或 Windows code signing。

## 安全边界

- Electron renderer 开启 `contextIsolation` 和 sandbox，关闭 Node.js 集成。
- Renderer 只能调用 preload 暴露的最小只读接口。
- 外部链接在系统浏览器打开，不在应用中执行。
- Provider 响应有超时、大小和协议版本限制。
- Demo 数值永远标记为 Demo，不得当作实时市场数据。
- `ir_search` 的来源已配置不等于真实取数已通过，界面保留能力和诊断状态。

更详细的模块边界见 [Architecture](docs/ARCHITECTURE.md)。
