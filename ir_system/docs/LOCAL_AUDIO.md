# 独立音频归档与火山转写

音频与 PDF/Office 分流。普通 `parse` 会自动跳过 MP3、M4A、WAV、FLAC、OGG、AAC；不会因为遇到音频而终止文档批次，也不会悄悄调用付费语音接口。

## 开始条件：先文字与非音频附件，后音频

后续任务统一遵守 `LOCAL_ARCHIVE.md` 的固定顺序：文字及非音频附件下载、解析、入库完成 → 音频下载 → 音频转写、入库。

- 文字阶段未完成时，不新下载音频，不运行 `audio-prepare` 或 `audio-transcribe`；既有音频原件与已完成转写保留不动。`audio-list` 的只读统计不受影响。
- 第一阶段是否完成，要依据本轮范围与交接报告核对；不能以一次文档预算用尽、零次尝试或索引 ready 代替验收。失败与权限缺口须明确报告，未经用户确认跳过，不自行进入音频阶段。
- 本轮音频下载任务处理完后，才开始转写；下载失败或未完成的项目按下载器原有停止规则处理，不假装文件已经可用。
- 用户明确指定某个音频先行测试属于单独例外，不改变后续批次的默认顺序。此前完成的《盘前早报 20260908.mp3》无需重下或重转。
- 顺序调整本身不启动任务，也不授权不限量付费转写；仍需明确文件范围及累计时长预算。

## 下载与存储

- 新音频的下载仍由原先的受授权归档器完成，遵守每轮先扫描全部订阅、会员有效期和下载策略的规则。这里不另开绕过权限的下载通道。
- 已成功下载的音频不重复下载。`audio-prepare` 校验原件后，单独保存一个可播放副本，并离线生成精确分段所需的 PCM。
- 尚未下载的音频只进入 `needs_download` 清单，不把元数据、文件名或链接当成已落盘文件。
- 普通归档的原件与检查点不变；本功能只写派生音频目录。

```text
ir_archive/derived/local_archive_v1/audio/<原音频SHA256>/
  original.mp3        # 后缀随实际音频格式变化；校验后的独立副本
  pcm16k.s16le        # 本地离线生成，按精确采样点分段
  transcript.json    # 逐字稿、句段时间、哈希、完整性、断点及耗时
  transcript.txt     # 已成功段落的纯文本；不是研究摘要
```

支持的准备预算为单原件 <= 200 MiB、容器时长 <= 2 小时、PCM <= 256 MiB；超出就报告，不擅自扩大。
这些是当前执行安全预算，不是平台提供数据的上限。

## 给低成本 Agent 的执行合同

使用 `LOCAL_ARCHIVE.md` 中指定的 Python 和 ir_search 路径。
通过公开 CLI 执行，不直接调用内部音频模块，不改代码或检查点。
除只读 `audio-list` 外，执行前必须确认上述阶段条件已经满足；以下命令不是文字阶段的并行任务。

```bash
# 只读音频队列，无网络
python -m ir_search.local_archive_cli --root /path/to/ir_archive audio-list --limit 30

# 复用已下载原件，单独保存、离线准备；不调用 ASR
python -m ir_search.local_archive_cli --root /path/to/ir_archive audio-prepare DOCUMENT_ID

# 只有用户明确允许火山转写且给出预算后才执行
python -m ir_search.local_archive_cli --root /path/to/ir_archive audio-transcribe DOCUMENT_ID --max-seconds 60 --allow-network
```

每条 `audio-transcribe` 最多转一个 1–180 秒的窗口（默认 60 秒）。续跑同一 ID 时使用已保存的下一采样点，不猜测起点、不从头重转。已整份完成时返回缓存结果，`asr_invoked=false`。
实际执行优先 60 秒短段。180 秒长段可能因累积流式响应触发保护；不得由执行 Agent 自动提高或删除响应预算。

1. 用户必须给出文件范围及累计时长预算。没有明确授权，不添加 `--allow-network`。
2. 单份整段转写时，先读取真实时长并说明预计处理时间。每次检查 `completed_seconds`、`whole_audio_transcribed` 和窗口耗时。
3. `status=ok` 只代表这一窗口成功；只有 `whole_audio_transcribed=true` 才表示这份音频的已解码采样点全部转写完成。
4. 用户预算耗尽或整份完成即停。一次只运行一个归档写入任务，不并发。
5. 任何 error 都停止。失败连接可能已经消耗额度；禁止自动重试，禁止自行添加 `--retry-failed`。需要用户重新确认后才允许重试。
6. 程序在调用火山之前保存 in-flight 标记；若崩溃后遗留该标记，必须报告不确定的调用，不默默重新计费。
7. 不修改套餐配置、不切换普通按量接口、不换其他转写供应商、不生成内容摘要。
8. 报告音频时长、成功窗口覆盖、逐段耗时、成功/失败尝试累计耗时、开始结束时间、文件路径。开发和调试时间不混入 ASR 耗时。

计时口径：`successful_asr_elapsed_seconds` 是成功调用的累计耗时；`failed_asr_elapsed_seconds` 单独累计失败调用。整轮墙钟时间还包含逐段存盘和索引更新，不能混称为纯转写耗时。首次开始到最终完成的跨重试时间可能包含用户确认等待，应另列而不作为转写速度。时间戳使用带时区的 UTC。

## 现有火山能力的复用

本功能复用 ir_search 的 `audio_profile` / `transcribe_pcm` 驱动，固定使用 Agent Plan 的 `doubao-seed-asr-2.0`，不引入第二套供应商凭证。
仅将当前窗口 PCM 发往原驱动固定的火山 TLS 接口；FFmpeg 只读本地文件，不访问网络。
接口按接近实时速度发送。具体扣费取决于账号套餐和超额配置，本功能不查询余额、不承诺免费。

独立 Python 环境需安装 ir_search 的 `audio` 可选依赖（`websockets==15.0.1`），本机 PATH 需有 FFmpeg 和 FFprobe。可选解析/转写依赖不随桌面二进制内嵌。

## 阅读与证据

成功窗口进入原有本地资料库，可用 `search --kind audio` 或桌面的“音频”筛选查询。搜索和阅读只取缓存，永远不触发 ASR。
机器转写标记 `asr_transcript` / `machine_transcribed=true`，并保留每句在原音频中的时间范围。时间是句段级，不伪装成逐词对齐。
数字、人名和专业词仍需听原音核对；“整份转完”不等于“人工校对正确”。部分转写必须保留 partial 标记。

公开 API：`list_local_audio`、`prepare_local_audio`、`transcribe_local_audio`，随 ir_search wheel 部署，不依赖本机工具脚本。
