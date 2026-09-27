# 韭菜空间站年度网页归档：修复与续传交接

验证完成时间：2026-09-26 04:50 UTC（北京时间 12:50）。

## 故障与修复

这次不是会员到期或附件不可下载。macOS 原生崩溃日志和复现确认：Chrome 153 的无头浏览器进程发生崩溃；附件处理随后对已关闭页面继续等待，异常又被顶层统一错误遮蔽。

- 默认优先使用已安装的配套浏览器，macOS 使用可见窗口；保留原专用登录配置。
- 增加脱敏异常堆栈、阶段、主题 ID；执行中断仍保存 manifest 和检查点。
- 每个附件单独持久化；续传先校验已下载对象的 SHA-256 和大小再复用。
- 修正历史列表滚动；仅被动读取正常浏览产生的主题列表响应，提取 ID、日期、标题等元数据，不重放私有请求、不落盘正文响应或签名地址。
- 按字符串处理超出 JavaScript 安全整数范围的主题 ID，避免错误跳转。
- 保留禁止复制正文、禁止截图等星球权限，不修改 `ir_search`。

## 实际验证结果

使用原年度任务 `9ce3eb8cb5f2e34792e0546c`，没有重置检查点。验证前重新扫描全部 52 个星球，扫描错误 0。

本轮有意限定 `--max-scrolls 1`，不是全年下载：

- 发现 40 个主题；本轮尝试 32 个，新增写入 25 条记录，其他通过既有记录去重；检查点累计处理 40 个。
- 新下载 8 个附件，共 82,539,701 字节；复用 4 个；失败 0、跳过 0。
- 原失败主题 `14425425554821112` 已成功；两个 PDF 分别为 8,206,268 和 19,549,442 字节，已核对 SHA-256、大小及 PDF 文件头。
- 最早发现日期为 2026-08-30，`reached_date_floor=false`，`coverage_complete=false`；仍远未完成一年。
- 本星球正文保存字符数为 0，符合只允许元数据及附件的权限范围。未验证图片全量下载。

年度清单：`/Users/chen/Documents/ir_archive/zsxq_web/jobs/9ce3eb8cb5f2e34792e0546c/manifest.json`

年度断点：同目录的 `checkpoint.json`。本轮清单会被下一轮更新，不能把本文件中的验证数字当作实时进度。

## 给下载 Agent 的续传指令

使用已安装的 `zsxq-web-archive` Skill，完整读取其 SKILL.md 和 CLI contract。只继续韭菜空间站（51122185284184），日期为 2025-09-25 至 2026-09-24，Asia/Shanghai，含首尾。归档根目录仍为 `/Users/chen/Documents/ir_archive`。保留已有检查点、文件和登录配置，不清空、不修改代码、不复制浏览器凭据。

先执行 Skill 规定的 doctor。通过后使用下面的原年度范围续传命令；不要沿用维护者小测试的 `--max-scrolls 1`：

```sh
python3 /Users/chen/Documents/macro-strategy-analyst/skills/zsxq-web-archive/scripts/zsxq_web.py backfill \
  --zsxq-cli /Users/chen/.hermes/node/bin/zsxq-cli \
  --archive-root /Users/chen/Documents/ir_archive \
  --group-id 51122185284184 \
  --start 2025-09-25 --end 2026-09-24 \
  --max-scrolls 500 \
  --max-topics-per-run 50 --max-assets-per-run 100 \
  --topic-interval-ms 1500 --scroll-delay-ms 1200 \
  --download-timeout-ms 30000
```

每次 backfill 会重新扫描所有星球。只运行一个进程，保持专用浏览器窗口打开，不指定无头模式，不另行登录 Safari 或导出其会话。

只有 `partial`、`run_budget_exhausted=true` 且失败为空时，才按相同命令逐批续传。`completed` 后停止，但仍须声明网页枚举不能证明平台级全量覆盖。无预算耗尽却未到日期下限，或有附件失败、浏览器中断、限流、认证/权限错误时，停止并报告 JSON 错误、具体阶段和清单路径，不反复重试、不调整权限边界。若网页路由变为 `ir_search`，报告路由变化，不自行更换接口。

报告必须区分本轮新增下载、校验复用、失败/跳过，以及历史存量；列出最早发现日期、是否到达日期下限、是否处理完本轮发现主题。正文只存元数据，图片不得宣称完整归档。
