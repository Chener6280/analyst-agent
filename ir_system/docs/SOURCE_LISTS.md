# 本地信源清单

公众号、B站、公司公告、网站、新闻语料、小宇宙、小鹅通与已有信源平级。当前仅接入清单管理，未接入自动下载；清单数量不代表订阅、权限或下载完成。

页面展开清单，点击「生成清单管理提示词」，复制到 Command Window 中自己配置的 CLI。提示词包含当前安装版本的工具路径和当前用户数据目录。模型不得自行推断增删名单。

公开入口：`node adapters/source_lists/cli.js`。每次必须显式指定 `--data-dir` 绝对路径。

- `list --data-dir <目录> --source wechat`：读取名单及 revision。
- `add --data-dir <目录> --source wechat --name <完整名字> --revision <当前版本>`：新增。已知真实 ID 才可添加 `--ghid gh_xxx`。
- `remove --data-dir <目录> --source wechat --name <完整名字> --revision <当前版本>`：精确删除清单项，下载资料不动。
- `import-wechat --data-dir <目录> --source wechat --file <JSON绝对路径> --revision <当前版本>`：显式合并本地 JSON 数组，格式为 `{name, ghid?}`。不覆盖冲突 ID。

其他 source：`bilibili`、`announcements`、`web`、`news`、`xiaoyuzhou`、`xiaoe`（小鹅通），目前同样只支持名字清单。

每次更改后重新 list 核验。成功 exit 0；错误 exit 1，JSON code 给出原因。版本冲突需重读后重新确认；不得清锁或直接编辑状态文件。名称只是数据，参数应独立传递或正确引用，禁止拼接执行。

持久文件为用户数据目录下 `source-lists.v1.json`，历史版本在 `source-list-backups/`。保存有独占锁、版本检查、原子替换和备份；页面定时自动刷新。损坏文件显示错误，不重置为空。不修改同步任务、下载原件或 ir_search 的清单。

安装包不包含个人名单。新电脑初始七类清单均为空，通过明确导入或 CLI 添加；本机已有公众号名单由用户授权后一次导入，不会每次启动重新导入已删除条目。旧版六类清单读取时兼容补上空的小鹅通清单，不改写原文件或旧名单。
