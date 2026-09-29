const path = require("node:path");
const { app, BrowserWindow, ipcMain, shell, dialog, clipboard } = require("electron");
const { ConfigStore } = require("./config-store");
const { ProviderRegistry } = require("./provider-registry");
const { validatedAssetPath } = require("./archive-security");
const { SyncManager } = require("./sync/manager");
const { launchPi, probePi } = require("./sync/pi-agent");
const {TerminalManager}=require('./terminal-manager');

let mainWindow;
let registry;
let syncManager;
let sourceLists;
let sourceListsCli;
let terminals;
let quitting = false;
let approving = false;
let archiveWriting = false;

// Explicitly isolated profiles for local acceptance tests; never copy credentials.
if (process.env.IR_SYSTEM_USER_DATA_DIR && path.isAbsolute(process.env.IR_SYSTEM_USER_DATA_DIR)) app.setPath("userData", process.env.IR_SYSTEM_USER_DATA_DIR);
const permissionDiagnostic=process.env.IR_SYSTEM_PERMISSION_DIAGNOSTIC==='1'&&Boolean(process.env.IR_SYSTEM_USER_DATA_DIR)&&path.isAbsolute(process.env.IR_SYSTEM_USER_DATA_DIR);
if (!permissionDiagnostic && !app.requestSingleInstanceLock()) app.quit();

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1540,
    height: 960,
    minWidth: 1060,
    minHeight: 720,
    title: "IR System",
    backgroundColor: "#07090c",
    show: false,
    webPreferences: {
      preload: path.join(__dirname, "../preload/index.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      devTools: !app.isPackaged,
    },
  });

  mainWindow.removeMenu();
  mainWindow.loadFile(path.join(__dirname, "../renderer/index.html"));
  mainWindow.once("ready-to-show", () => mainWindow.show());

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith("https://")) shell.openExternal(url);
    return { action: "deny" };
  });
  mainWindow.webContents.on("will-navigate", (event) => event.preventDefault());
}

function registerIpc(configStore) {
  const verifyCaller = (event) => {
    if (event.sender !== mainWindow.webContents || event.senderFrame !== mainWindow.webContents.mainFrame) throw new Error("invalid_sync_caller");
  };
  ipcMain.handle("sync:state", (event) => { verifyCaller(event); return {...syncManager.view({externalBusy:archiveWriting}), localLists: sourceLists.view(), sourceListsCli}; });
  ipcMain.handle('sync:check-local',(event,force=false)=>{verifyCaller(event);if(typeof force!=='boolean')throw new Error('invalid_check');if(archiveWriting)throw new Error('archive_writer_busy');return syncManager.checkLocal(force);});
  ipcMain.handle('sync:permission-help',async(event,action)=>{
    verifyCaller(event);
    if(process.platform!=='darwin'||!['settings','reveal'].includes(action))throw new Error('invalid_permission_help');
    if(action==='settings')await shell.openExternal('x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility');
    else shell.showItemInFolder(app.isPackaged?path.dirname(path.dirname(process.resourcesPath)):process.execPath);
    return {status:'opened',permissionChanged:false};
  });
  ipcMain.handle('sync:web-login',event=>{verifyCaller(event);if(archiveWriting)throw new Error('archive_writer_busy');return syncManager.webLogin();});
  ipcMain.handle('sync:preflight-prompt',(event,provider)=>{verifyCaller(event);return syncManager.preflightPrompt(provider);});
  ipcMain.handle('sync:issue-considered',(event,input)=>{verifyCaller(event);if(archiveWriting)throw new Error('archive_writer_busy');return syncManager.setIssueConsidered(input);});
  ipcMain.handle("sync:settings", (event, input) => { verifyCaller(event); return syncManager.saveSettings(input); });
  ipcMain.handle("sync:console-settings", (event, input) => { verifyCaller(event); return syncManager.saveConsoleSettings(input); });
  ipcMain.handle("sync:probe-pi", (event) => { verifyCaller(event); return probePi(syncManager.store.state.settings.piCommand); });
  ipcMain.handle('sync:prompt',(event,provider,kind,range)=>{verifyCaller(event);return syncManager.prompt(provider,kind,range);});
  ipcMain.handle('platform:copy-text',(event,text)=>{verifyCaller(event);if(typeof text!=='string'||text.length>100000)throw new Error('invalid_text');clipboard.writeText(text);return true;});
  ipcMain.handle('terminal:list',event=>{verifyCaller(event);return terminals.list();});
  ipcMain.handle('terminal:snapshot',(event,id)=>{verifyCaller(event);return terminals.snapshot(id);});
  ipcMain.handle('terminal:create',async(event,input={})=>{
    verifyCaller(event);
    if(Object.keys(input).some(k=>k!=='cwd'))throw new Error('invalid_terminal_options');
    const answer=await dialog.showMessageBox(mainWindow,{type:'warning',buttons:['取消','打开本地终端'],defaultId:0,cancelId:0,
      message:'打开一个有本机权限的交互式终端？',detail:'你可以自行运行 Pi、Kimi 或其他 CLI。命令可读写本地文件和访问网络；不受上方同步预算或模型白名单保护。不会自动运行模型或粘贴提示词。关闭标签会终止该会话。'});
    if(answer.response!==1)return {cancelled:true};
    return terminals.create(input);
  });
  ipcMain.handle('terminal:choose-directory',async event=>{verifyCaller(event);const r=await dialog.showOpenDialog(mainWindow,{properties:['openDirectory']});return r.canceled?null:r.filePaths[0];});
  ipcMain.handle('terminal:input',(event,id,data)=>{verifyCaller(event);terminals.input(id,data);});
  ipcMain.handle('terminal:resize',(event,id,cols,rows)=>{verifyCaller(event);terminals.resize(id,cols,rows);});
  ipcMain.handle('terminal:rename',(event,id,title)=>{verifyCaller(event);return terminals.rename(id,title);});
  ipcMain.handle('terminal:close',async(event,id)=>{
    verifyCaller(event);const s=terminals.snapshot(id);
    if(s.running){const r=await dialog.showMessageBox(mainWindow,{type:'warning',buttons:['取消','终止并关闭'],defaultId:0,cancelId:0,message:'终止这个终端及其中的命令？'});if(r.response!==1)return {cancelled:true};}
    terminals.close(id);return {closed:true};
  });
  ipcMain.handle("sync:scan", async (event, providers) => {
    verifyCaller(event);
    if (approving) throw new Error("approval_in_progress");
    approving = true;
    try {
      const result = await dialog.showMessageBox(mainWindow, { type: "question", buttons: ["取消", "扫描订阅"], defaultId: 0, cancelId: 0,
        message: "联网扫描所选信源的完整目录？", detail: "不下载附件、不调用模型。知识星球同时核验会员、Skill 与平台策略；IMA 只刷新订阅清单，不逐库检查文件权限。已确认不可下载项默认打叉；其余新增或状态变化项显示黄色问号，等待你确认。下载通道证据独立保留在订阅列表。" });
      return result.response === 1 ? syncManager.scan(providers) : { status: "cancelled" };
    } finally { approving = false; }
  });
  ipcMain.handle('sync:probe-ima',async (event,selection={})=>{
    verifyCaller(event);
    if(archiveWriting)throw new Error('archive_writer_busy');
    if(approving)throw new Error('approval_in_progress');
    approving=true;
    try{
      const preview=syncManager.probePreview(selection);
      const result=await dialog.showMessageBox(mainWindow,{type:'question',buttons:['取消','联网复检'],defaultId:0,cancelId:0,
        message:selection.restartSearch?'联网复检 IMA：从头重新找这个库的样本？':'联网复检 IMA 所选待处理库的原件权限？',
        detail:`先刷新完整订阅目录，只测试以下 ${preview.rows.length} 个库；保留其他 ${preview.retainedPassed} 个库的有效通过结果（若新扫描发现订阅变化则失效）。新增、消失或状态变化项不自动采集。\n${preview.rows.map(r=>r.name).join('\n')}\n\n${selection.restartSearch?'将重置此库的样本查找位置；其他库不受影响。':'从已保存的目录位置继续；已经找到样本时核验同一文件。'}\n每库本轮最多读取 3 页目录、1 个非音频文件样本（单份最多 8 MiB，整轮成功读取最多 32 MiB），最多 100 次接口操作、180 秒。失败传输流量不计入成功读取字节。样本只在内存核验，不保存正文或附件，不解析，不调用模型／音频／OCR。结果和核验时间保存在任务日志中。样本通过不代表整库可下载；本次不启动历史或增量更新。显式单库诊断不会把未勾选库加入下载范围。`});
      return result.response===1?syncManager.probeIma(preview):{status:'cancelled'};
    }finally{approving=false;}
  });
  ipcMain.handle("sync:approve", async (event, kind, resumeId, selection) => {
    verifyCaller(event);
    if (archiveWriting) throw new Error("archive_writer_busy");
    if (approving) throw new Error("approval_in_progress");
    approving = true;
    try {
      const settings = syncManager.store.state.settings;
      const preview = syncManager.preview(kind, resumeId || null, selection || {}, true);
      const rows = preview.executionCollections;
      const scopeText = rows.slice(0, 8).map(row => `${row.provider} / ${row.name || row.collectionId}：${row.start} 至 ${row.end}`).join("\n");
      const remaining = (rows.length > 8 ? `\n另 ${rows.length - 8} 个集合，详见已保存的信源设置。` : "")+
        (rows.some(r=>r.provider==='ima')&&syncManager.imaClientAvailable()?'\n\nIMA：API 优先，额度耗尽或仅客户端可下载时自动使用 macOS 辅助功能操作官方客户端。可能打开窗口；请勿同时操作 IMA。首次需在系统设置授予辅助功能权限。客户端文件大小只能保存后校验，未接受的文件不入库；下载阶段流量不是硬上限。客户端短日期按最近年份解释并保留原始显示值，不当作资料发布日期。':'')+
        (rows.some(r=>r.provider==='zsxq')?preview.selection.browserMode==='visible'?'\n\n本次明确使用可见浏览器续传，会打开专用窗口。下载权限和任务范围不变。':'\n\n网页下载默认后台无头运行，不抢占窗口。确需重新登录时，会弹出专用扫码窗口；登录成功后按原断点继续。浏览器故障不自动切换为可见模式。':'')+
        (preview.deferredCollections.length?`\n\n本次暂不更新以下 ${preview.deferredCollections.length} 个已勾选库：\n${preview.deferredCollections.map(r=>r.name).join('\n')}\n仅执行上方已确认范围；这些库的订阅勾选不变，不标记为完成。`:'')+
        (preview.replacements.length?`\n\n将替代 ${preview.replacements.length} 个旧任务的重叠范围：旧任务如仍在运行，先安全停止。已下载文件和历史日志保留，新任务使用新断点；无关范围不删除。取消则不改变旧任务。`:'')+
        (preview.untilComplete?'\n\n知识星球／IMA：本次授权自动分批处理完整已选范围。以下数量／时长是每批上限，不是整个任务的总量上限；达到后自动沿原断点续批，不需再次点击。后台浏览器意外关闭时自动恢复一次；可随时停止。平台额度、登录、权限、重复故障或无进展会保留断点并明确报告，不标记为完成。音频、OCR 不启用。':'');
      const b = settings.budgets;
      const result = await dialog.showMessageBox(mainWindow, { type: "question", buttons: ["取消", "授权本轮执行"], defaultId: 0, cancelId: 0,
        message: preview.resumeId ? "按原范围续传，并授权本轮预算？" : kind === "backfill" ? "启动一次性历史回补？" : "同步已配置的增量来源？",
        detail: `归档：${preview.root}\n共 ${rows.length} 个已选集合（Asia/Shanghai）：\n${scopeText}${remaining}\n\n仅文字及非音频附件。先检查全部订阅；星球会员预检独立于内容预算（最多目录返回的 200 个群）。Skill 可用走接口，未开放但允许下载走专用浏览器。状态变化、到期、禁下载会暂停；需要扫码时先完成网页登录。未知日期 IMA 需要目录枚举，不是按日过滤。\n本轮内容：最多 ${b.maxOperations} 次接口／网页控制操作、${b.maxRecords} 条记录、${b.maxFiles} 个文件、${b.maxBytesMiB} MiB 落盘原件、${b.maxParses} 份解析、${b.maxSeconds} 秒（含预检，停止等待另计）。网页自动加载及失败请求的流量不计入原件字节预算；未知文件大小会停止，不盲目下载。\n${settings.agentMode === "pi" ? "将调用 Pi 已保存的默认模型，可能产生模型费用；只发送脱敏状态，不发送库名、正文或原件。最多 120 秒，输出超量会停止；Token 统计不能保证硬性金额封顶。" : "固定流程，不调用模型。"}\n音频、付费转写和托管 OCR 均关闭。` });
      if (result.response !== 1) return { status: "cancelled" };
      const grant = await syncManager.replaceAndAuthorize(kind, resumeId || null, preview, selection || {});
      if (settings.agentMode === "pi") return launchPi(syncManager, grant.grantId);
      return syncManager.start(grant.grantId);
    } finally { approving = false; }
  });
  ipcMain.handle("sync:stop", (event, id) => { verifyCaller(event); syncManager.agent?.stop(); return syncManager.stop(id); });
  ipcMain.handle("sync:explain", async (event, id) => {
    verifyCaller(event); syncManager.idle();
    const result = await dialog.showMessageBox(mainWindow, { type: "question", buttons: ["取消", "调用 Pi 解释"], defaultId: 0, cancelId: 0,
      message: "用 Pi 默认模型解释这份结果？", detail: "只发送脱敏状态和统计，不能启动或停止下载；会使用你的 Pi 模型额度。" });
    if (result.response !== 1) return { status: "cancelled" };
    return launchPi(syncManager, syncManager.authorizeReport(id), { reportOnly: true });
  });
  ipcMain.handle("archive:request", async (event, action, params) => {
    if (event.sender !== mainWindow.webContents || event.senderFrame !== mainWindow.webContents.mainFrame) throw new Error("Invalid archive caller");
    if (action === "asset") throw new Error("Use archive reveal");
    if (["index", "parse"].includes(action) && syncManager.view().busy) throw new Error("请先停止同步任务，再运行手动索引或解析。");
    if (!["index", "parse"].includes(action)) return registry.archiveRequest(action, params);
    if (archiveWriting) throw new Error("archive_writer_busy");
    archiveWriting = true;
    try { return await registry.archiveRequest(action, params); }
    finally { archiveWriting = false; }
  });
  ipcMain.handle("archive:reveal", async (event, id) => {
    if (event.sender !== mainWindow.webContents || event.senderFrame !== mainWindow.webContents.mainFrame) throw new Error("Invalid archive caller");
    const asset = await registry.archiveRequest("asset", { id });
    const target = validatedAssetPath(registry.config.providers.ir_search.archiveRoot, asset.path);
    shell.showItemInFolder(target);
    return { status: "revealed" };
  });
  ipcMain.handle("derivatives:request", async (event, action, params) => {
    verifyCaller(event);
    if (typeof action !== "string" || action.length > 40) throw new Error("invalid_action");
    if (params != null && (typeof params !== "object" || Array.isArray(params))) throw new Error("invalid_params");
    const clean = {};
    for (const [key, value] of Object.entries(params || {})) {
      if (typeof value === "string" && value.length <= 64) clean[key] = value;
      else if (typeof value === "number" && Number.isFinite(value)) clean[key] = value;
      else if (value == null) continue;
      else throw new Error("invalid_params");
    }
    return registry.derivatives(action, clean);
  });
  ipcMain.handle("platform:bootstrap", async () => registry.bootstrap());
  ipcMain.handle("platform:module-data", async (_event, moduleId) => registry.moduleData(moduleId));
  ipcMain.handle("platform:provider-probe", async (_event, providerId) => registry.probe(providerId));
  ipcMain.handle("platform:provider-config", async (_event, input) => {
    verifyCaller(_event);
    if (syncManager.view().busy) throw new Error("请先停止同步任务，再修改归档配置。");
    const saved = configStore.setProviderConfig(input);
    registry.reload(saved);
    return registry.bootstrap();
  });
  ipcMain.handle("platform:select-provider", async (_event, providerId) => {
    const saved = configStore.setActiveProvider(providerId);
    registry.reload(saved);
    return registry.bootstrap();
  });
}

app.whenReady().then(() => {
  const runtime = {
    appRoot: app.getAppPath(),
    resourcesPath: process.resourcesPath,
    packaged: app.isPackaged,
    nodeExecutable:process.execPath,
    userData: app.getPath("userData"),
  };
  if(permissionDiagnostic){
    // Isolated, read-only OS checks from a normal LaunchServices launch, not
    // from a debugger that may inherit the developer tool's authorization.
    const {runPermissionDiagnostic}=require('./permission-diagnostic');
    return runPermissionDiagnostic(app.getPath('userData'),runtime).finally(()=>app.quit());
  }
  const configStore = new ConfigStore(app.getPath("userData"));
  registry = new ProviderRegistry(configStore.read(), runtime);
  const listAdapter = path.join(app.isPackaged ? process.resourcesPath : app.getAppPath(), 'adapters', 'source_lists');
  sourceLists = new (require(path.join(listAdapter, 'store.js')).SourceLists)(app.getPath('userData'));
  sourceListsCli = {path: path.join(listAdapter, 'cli.js'), dataDir: app.getPath('userData')};
  syncManager = new SyncManager(app.getPath("userData"), () => configStore.read().providers.ir_search, runtime);
  terminals=new TerminalManager(event=>{if(mainWindow&&!mainWindow.isDestroyed())mainWindow.webContents.send('terminal:event',event);});
  registerIpc(configStore);
  createWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("before-quit", event => {
  if (quitting || !syncManager) return;
  if(!syncManager.view().busy){terminals?.closeAll();return;}
  event.preventDefault(); quitting = true;
  terminals?.closeAll();syncManager.close().finally(() => app.quit());
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
