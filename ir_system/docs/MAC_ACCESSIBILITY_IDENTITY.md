# 辅助功能开关已开启但仍未授权：2026-09-27 修复

## 核实的原因

系统设置界面确认 IR System 开关为 on。旧 bulk-source-update-preview 应用的 `codesign --verify --deep --strict` 校验失败，错误为 `code has no resources but signature indicates they must be present`。可执行文件仍带 Electron 的残留链接器签名，Info.plist 未绑定、没有资源封装。

macOS tccd 日志显示：从桌面启动的旧应用，其 helper 授权被归属到 `identifier=Electron` 的可执行文件路径；设置里的条目使用 `com.irsystem.desktop`。这解释了已勾选仍返回未授权。没有读取或修改受保护的 TCC 数据库。

以前从开发工具启动的检查不构成桌面启动验收：该方式的 responsible process 可能是 Codex。本次新增独立诊断模式，通过 LaunchServices 正常启动，无调试器、不打开资料、不调用模型、不请求或修改权限。

## 修复

- 本地 macOS 构建明确使用 ad-hoc 签名，不再静默跳过签名。
- afterSign 校验整个应用及嵌套组件，检查 Info.plist 绑定和 `com.irsystem.desktop` 代码身份；无效则打包失败。
- Python 适配器运行时不在应用资源目录生成字节码缓存，避免破坏资源签名。
- 辅助功能提示补充旧授权重新关联指引，提供“打开辅助功能设置”和“定位当前应用”按钮。按钮不更改权限。
- 删除 Data Center 顶部宣传区及合并按钮旁的冗余说明。

## 验收边界

新版本签名通过校验，系统日志的 responsible identifier 已是 `com.irsystem.desktop`。正常启动的只读诊断仍返回 `mainTrusted=false`、helper `ima_accessibility_required`，即新签名对应的授权尚未由用户确认；不会把修好签名等同于授权通过或下载完成。

用户须先退出旧应用，打开桌面新版；在系统设置的辅助功能列表移除旧 IR System 条目，重新添加“定位当前应用”显示的新版并启用，再检查本地环境。程序不重置 TCC、不自动替用户勾选。

本地 ad-hoc 签名不是 Apple Developer ID，也没有公证；不能承诺以后任意改版都免重新授权。正式跨机器发行和稳定升级身份应配置合法 Developer ID 签名及公证，不伪造证书或关闭系统安全保护。

参考：[Apple 当前进程辅助功能检查](https://developer.apple.com/documentation/applicationservices/1460720-axisprocesstrusted)、[Electron 代码签名](https://www.electronjs.org/docs/latest/tutorial/code-signing)。
