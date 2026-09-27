"use strict";

const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const { setTimeout: delay } = require("node:timers/promises");
const { chromium } = require("playwright-core");
const { browserOptions, launchContext, inspectPage, assertMembership } = require("./browser");
const { ZsxqWebError, writeJsonAtomic } = require("./core");
const { errorDiagnostic } = require("./diagnostics");
const {mediaKind,accepted,isPause}=require('./control');

const FILE_NAME = /([^/\\<>:"|?*\n\r]{1,180}\.(?:pdf|docx?|xlsx?|pptx?|zip|rar|7z|csv|txt|md|html|rtf|png|jpe?g|gif|webp|bmp|mp3|m4a|wav|aac|flac|ogg|opus|wma|amr|mp4|mov|mkv|avi|webm))(?:\s|$)/i;

function shanghaiToday(now = new Date()) {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit" }).format(now);
}

function parseTopicDate(text, now = new Date()) {
  const value = String(text || "");
  let match = value.match(/(20\d{2})[年/.\-](\d{1,2})[月/.\-](\d{1,2})日?/);
  if (match) return `${match[1]}-${match[2].padStart(2, "0")}-${match[3].padStart(2, "0")}`;
  match = value.match(/(?:^|\s)(\d{1,2})[月/.\-](\d{1,2})日?(?:\s|$)/);
  if (match) {
    const today = shanghaiToday(now);
    return `${today.slice(0, 4)}-${match[1].padStart(2, "0")}-${match[2].padStart(2, "0")}`;
  }
  const today = shanghaiToday(now);
  if (/前天/.test(value)) return shiftDay(today, -2);
  if (/昨天/.test(value)) return shiftDay(today, -1);
  if (/今天|刚刚|小时前|分钟前/.test(value)) return today;
  return null;
}

function shiftDay(day, amount) {
  const date = new Date(`${day}T12:00:00+08:00`);
  date.setUTCDate(date.getUTCDate() + amount);
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit" }).format(date);
}

function safeName(value, fallback = "file") {
  const cleaned = path.basename(String(value || "")).replace(/[^\p{L}\p{N}._()（）\- ]/gu, "_").trim().slice(0, 180);
  return cleaned || fallback;
}

function sha256File(target) {
  const hash = crypto.createHash("sha256");
  const bytes = fs.readFileSync(target);
  hash.update(bytes);
  return { sha256: hash.digest("hex"), size_bytes: bytes.length };
}

function objectsDiskTotal(root) {
  const objects = path.join(root, "objects");
  if (!fs.existsSync(objects)) return 0;
  let total = 0;
  for (const prefix of fs.readdirSync(objects, { withFileTypes: true })) {
    if (!prefix.isDirectory()) continue;
    const directory = path.join(objects, prefix.name);
    for (const item of fs.readdirSync(directory, { withFileTypes: true })) {
      if (item.isFile() && /^[0-9a-f]{64}$/.test(item.name)) total += fs.statSync(path.join(directory, item.name)).size;
    }
  }
  return total;
}

function acquireLock(root) {
  fs.mkdirSync(root, { recursive: true });
  const lockPath = path.join(root, ".archive.lock");
  try {
    const descriptor = fs.openSync(lockPath, "wx", 0o600);
    fs.writeFileSync(descriptor, `${process.pid}\n`, "utf8");
    return () => {
      try { fs.closeSync(descriptor); } catch {}
      try { fs.unlinkSync(lockPath); } catch {}
    };
  } catch (error) {
    if (error.code === "EEXIST") throw new ZsxqWebError("archive_locked", "Another zsxq_web archive process is already running", 12);
    throw error;
  }
}

function parseBrowserFeed(raw, groupId) {
  // ZSXQ IDs exceed Number.MAX_SAFE_INTEGER. Preserve numeric ID tokens before
  // parsing; response.json() would silently round some topic IDs.
  const payload = JSON.parse(raw.replace(/("(?:topic_id|group_id)"\s*:\s*)(\d+)(?=\s*[,}])/g, '$1"$2"'));
  if (payload.succeeded !== true || !Array.isArray(payload.resp_data?.topics)) {
    throw new ZsxqWebError("browser_feed_unavailable", "The website did not return a usable topic list", 4);
  }
  return payload.resp_data.topics.map((topic) => {
    const id = String(topic.topic_id || "");
    if (!/^\d+$/.test(id)) throw new ZsxqWebError("browser_feed_schema", "The website returned an invalid topic ID", 4);
    if (topic.group?.group_id && String(topic.group.group_id) !== String(groupId)) {
      throw new ZsxqWebError("browser_feed_schema", "Unexpected group in browser topic list", 4);
    }
    const date = new Date(topic.create_time);
    const publishedOn = Number.isFinite(date.getTime()) ? shanghaiToday(date) : null;
    const firstLine = String(topic.title || topic.talk?.text || topic.question?.text || "")
      .replace(/<br\s*\/?\s*>/gi, "\n").replace(/<[^>]*>/g, "").trim().split(/\r?\n/)[0].slice(0, 300);
    return {
      topic_id: id,
      url: `https://wx.zsxq.com/group/${groupId}/topic/${id}`,
      context_text: firstLine,
      published_on: publishedOn,
      sticky: Boolean(topic.sticky),
      stable_id_scope: "browser_feed",
      // Passive browser response metadata only. Never retain signed URLs.
      files: (topic.talk?.files||topic.question?.files||topic.files||[]).map(f=>({name:String(f.name||''),size:Number(f.size)||null})).filter(f=>f.name),
      audio_count: Number(Boolean(topic.talk?.audio||topic.question?.audio||topic.audio)),
      image_count: (topic.talk?.images||topic.question?.images||topic.images||[]).length,
    };
  });
}

async function discoverTopics(page, job, options = {}) {
  const found = new Map();
  const pending = new Set();
  let feedError = null;
  let feedPages = 0;
  let exhausted = false;
  let oldest = null;
  let noGrowth = 0;
  let reachedDateFloor = false;
  const collect = (response) => {
    const url = new URL(response.url());
    if (url.hostname !== "api.zsxq.com" || url.pathname !== `/v2/groups/${job.group_id}/topics`) return;
    const task = (async () => {
      if (response.status() === 429) throw new ZsxqWebError("rate_limited", "Website rate limit; stop and cool down", 14);
      const rows = parseBrowserFeed(await response.text(), job.group_id);
      feedPages += 1;
      exhausted = rows.length === 0;
      for (const topic of rows) {
        found.set(topic.topic_id, topic);
        if (!topic.sticky && topic.published_on && (!oldest || topic.published_on < oldest)) oldest = topic.published_on;
      }
    })().catch((error) => { feedError = error; });
    pending.add(task);
    task.finally(() => pending.delete(task));
  };
  page.on("response", collect);
  try {
    options.control?.step();
    await page.goto(`https://wx.zsxq.com/group/${job.group_id}`, { waitUntil: "domcontentloaded", timeout: 45_000 });
    const access = await inspectPage(page);
    if (access.login_required || !access.authenticated) throw new ZsxqWebError("human_login_required", "The dedicated browser profile is not logged in", 10);
    assertMembership(access, job);
    await page.locator("app-topic").first().waitFor({ state: "attached", timeout: 12_000 });
    for (let scroll = 0; scroll < Number(options.maxScrolls || 120); scroll += 1) {
      options.control?.check();
      await Promise.all([...pending]);
      if (feedError) throw feedError;
      if (oldest && oldest < job.start) { reachedDateFloor = true; break; }
      if (exhausted || noGrowth >= 5) break;
      const before = found.size;
      // Trigger the same wheel-driven loading as normal browsing. Programmatic
      // window scrolling did not reliably request more history on this site.
      await page.mouse.move(700, 700);
      for (let step = 0; step < 40 && found.size === before; step += 1) {
        options.control?.step();
        await page.mouse.wheel(0, 850);
        await delay(75);
      }
      await delay(Number(options.scrollDelayMs || 900));
      await Promise.all([...pending]);
      noGrowth = before === found.size ? noGrowth + 1 : 0;
    }
    await Promise.all([...pending]);
    if (feedError) throw feedError;
    reachedDateFloor = Boolean(oldest && oldest < job.start);
    const topics = [...found.values()].filter((topic) => !topic.published_on || (topic.published_on >= job.start && topic.published_on <= job.end));
    topics.sort((a, b) => String(a.published_on || "9999").localeCompare(String(b.published_on || "9999")) || a.topic_id.localeCompare(b.topic_id));
    return { topics, reached_date_floor: reachedDateFloor, oldest_visible_date: oldest, feed_pages: feedPages, discovery_exhausted: exhausted,
      link_resolution: { attempted: topics.length, succeeded: topics.length, failed_by_stage: {} } };
  } finally {
    page.off("response", collect);
    await Promise.all([...pending]);
  }
}

function largestContentText(payload) {
  const candidates = Array.isArray(payload) ? payload : [];
  return candidates.map((value) => String(value || "").trim()).filter((value) => value.length >= 20).sort((a, b) => b.length - a.length)[0] || "";
}

function inferCardTitle(text) {
  const lines = String(text || "").split(/\n+/).map((line) => line.trim()).filter(Boolean);
  const dateIndex = lines.findIndex((line) => /20\d{2}[年/.\-]\d{1,2}[月/.\-]\d{1,2}/.test(line));
  const candidates = lines.slice(dateIndex >= 0 ? dateIndex + 1 : 0).filter((line) =>
    !/^(为我总结|查看详情|风险提示|觉得很赞)/.test(line) && !line.startsWith("#") && !FILE_NAME.test(line));
  return candidates[0]?.slice(0, 300) || "";
}

function recordSignature(record) {
  const publishedOn = String(record?.published_on || "").trim();
  const title = String(record?.title || "").replace(/\s+/g, " ").trim().toLocaleLowerCase("zh-CN");
  if (!publishedOn || !title) return null;
  return `${publishedOn}\n${title}`;
}

function recordAttachmentsComplete(record,policy='all') {
  const attachments = record?.attachments || [];
  return attachments.every((item) => accepted(item,policy)) &&
    (record?.detected_attachments || []).every((name) => attachments.some((item) => item.original_filename === name && accepted(item,policy)));
}

function verifiedRecord(record,root,policy){
  if(!recordAttachmentsComplete(record,policy))return false;
  for(const a of record.attachments||[]){
    if(policy==='text_non_audio'&&['audio','video'].includes(mediaKind(a.original_filename)))continue;
    if(a.status!=='ok'||!/^[0-9a-f]{64}$/.test(a.sha256||''))return false;
    try{const info=sha256File(path.join(root,'objects',a.sha256.slice(0,2),a.sha256));if(info.sha256!==a.sha256||info.size_bytes!==a.size_bytes)return false;}catch{return false;}
  }
  return true;
}

function existingRecordSignatures(topicsRoot) {
  const result = new Map();
  if (!fs.existsSync(topicsRoot)) return result;
  for (const item of fs.readdirSync(topicsRoot, { withFileTypes: true })) {
    if (!item.isDirectory()) continue;
    const recordPath = path.join(topicsRoot, item.name, "record.json");
    if (!fs.existsSync(recordPath)) continue;
    try {
      const record = JSON.parse(fs.readFileSync(recordPath, "utf8"));
      const signature = recordSignature(record);
      if (signature && !result.has(signature)) {
        result.set(signature, { topic_id: item.name, complete: recordAttachmentsComplete(record) });
      }
    } catch {}
  }
  return result;
}

function archiveInventory(topicsRoot, topicIdAliases = {}) {
  const inventory = {
    records_total: 0,
    active_topic_references: 0,
    stable_topic_records: 0,
    legacy_fingerprint_records: 0,
    attachments_ok: 0,
    attachments_failed: 0,
    attachments_skipped: 0,
    legacy_attachments_ok: 0,
    legacy_attachments_failed: 0,
    legacy_attachments_skipped: 0,
    content_characters_stored: 0,
  };
  if (!fs.existsSync(topicsRoot)) return inventory;
  for (const item of fs.readdirSync(topicsRoot, { withFileTypes: true })) {
    if (!item.isDirectory()) continue;
    const recordPath = path.join(topicsRoot, item.name, "record.json");
    if (!fs.existsSync(recordPath)) continue;
    try {
      const record = JSON.parse(fs.readFileSync(recordPath, "utf8"));
      inventory.records_total += 1;
      const stable = /^\d+$/.test(item.name);
      if (stable) inventory.stable_topic_records += 1;
      else inventory.legacy_fingerprint_records += 1;
      inventory.content_characters_stored += String(record.content_text || "").length;
      for (const attachment of record.attachments || []) {
        const prefix = stable ? "attachments" : "legacy_attachments";
        if (attachment.status === "ok") inventory[`${prefix}_ok`] += 1;
        else if (attachment.status === "skipped") inventory[`${prefix}_skipped`] += 1;
        else inventory[`${prefix}_failed`] += 1;
      }
    } catch {}
  }
  inventory.active_topic_references = inventory.stable_topic_records + Object.keys(topicIdAliases || {}).length;
  return inventory;
}

async function topicMetadata(page, topic, job, now = new Date(), options={}) {
  if (!topic.url) {
    const content = topic.context_text || "";
    const fileNames = [];
    for (const line of content.split(/\n+/)) {
      const match = line.trim().match(FILE_NAME);
      if (match && !fileNames.includes(match[1])) fileNames.push(match[1]);
    }
    return {
      source: "zsxq_web",
      source_item_id: `zsxq_web://card/${topic.topic_id}`,
      source_collection: job.group_id,
      source_url: null,
      topic_id: topic.topic_id,
      title: inferCardTitle(content),
      published_on: topic.published_on || parseTopicDate(content, now),
      fetched_at: new Date().toISOString(),
      content_text: job.include.topics === "full_text" ? content : "",
      text_scope: job.include.topics === "full_text" ? "web_member_view" : "metadata_only_group_copy_disabled",
      detected_attachments: fileNames,
      warnings: ["stable_topic_url_not_resolved"],
    };
  }
  options.control?.step();
  await page.goto(topic.url, { waitUntil: "domcontentloaded", timeout: 45_000 });
  const access = await inspectPage(page);
  if (access.login_required || !access.authenticated) throw new ZsxqWebError("human_login_required", "Browser login expired during archive", 10);
  assertMembership(access, job);
  const title = await page.title().catch(() => "");
  const blocks = await page.locator("article, main, [class*=topic], [class*=content]").evaluateAll((nodes) => nodes.map((node) => (node.innerText || "").slice(0, 200_000))).catch(() => []);
  const bodyText = await page.locator("body").innerText().catch(() => "");
  const content = largestContentText(blocks) || bodyText;
  const publishedOn = topic.published_on || parseTopicDate(content, now);
  const fileNames = (topic.files||[]).map(f=>f.name);
  const visibleNames=await page.locator('.file-name').allTextContents();
  for(const name of visibleNames.map(n=>n.trim()).filter(Boolean))if(!fileNames.includes(name))fileNames.push(name);
  for (const line of content.split(/\n+/)) {
    const match = line.trim().match(FILE_NAME);
    if (match && !fileNames.includes(match[1])) fileNames.push(match[1]);
  }
  return {
    source: "zsxq_web",
    source_item_id: `zsxq://topic/${topic.topic_id}`,
    source_collection: job.group_id,
    source_url: topic.url,
    topic_id: topic.topic_id,
    title: inferCardTitle(topic.context_text) || title.replace(/[-|]\s*知识星球.*$/i, "").trim(),
    published_on: publishedOn,
    fetched_at: new Date().toISOString(),
    content_text: job.include.topics === "full_text" ? content : "",
    text_scope: job.include.topics === "full_text" ? "web_member_view" : "metadata_only_group_copy_disabled",
    detected_attachments: fileNames,
    file_metadata: topic.files||[],
    audio_count: topic.audio_count||0,
    image_count: topic.image_count||0,
  };
}

async function downloadVisibleFiles(page, record, job, storage, options = {}) {
  const entries = [];
  if (!job.include.attachments) return entries;
  const maxAssets = Number(options.maxAssetsPerTopic || 50);
  const maxBytes = Number(options.assetMaxBytes || 200 * 1024 * 1024);
  const runBudget = options.runBudget || { assets: 0, bytes: objectsDiskTotal(storage) };
  const maxAssetsPerRun = Number(options.maxAssetsPerRun || 100);
  const sizeGuardBytes = Number(options.sizeGuardBytes || 20 * 1024 * 1024 * 1024);
  const previousPath = path.join(storage, "groups", job.group_id, "topics", record.topic_id, "record.json");
  let previousAttachments = [];
  try { previousAttachments = JSON.parse(fs.readFileSync(previousPath, "utf8")).attachments || []; } catch {}
  const attachmentNames = record.detected_attachments.slice(0, maxAssets);
  for (let attachmentIndex = 0; attachmentIndex < attachmentNames.length; attachmentIndex += 1) {
    const originalName = attachmentNames[attachmentIndex];
    options.control?.check();
    const kind=mediaKind(originalName);
    if(options.mediaPolicy==='text_non_audio'&&['audio','video'].includes(kind)){
      const prior=previousAttachments.find(a=>a.original_filename===originalName&&a.status==='ok');
      entries.push(prior?{...prior,preserved:true}:{original_filename:originalName,status:'deferred',reason:kind+'_deferred'});
      if(options.control)options.control.counts[kind+'Deferred']++;
      options.onAttachmentProgress?.(entries);continue;
    }
    if(options.mediaPolicy==='text_non_audio'&&kind==='unknown'){
      if(!options.isolateItemFailures)throw new ZsxqWebError('media_type_requires_confirmation','Unknown or compound media; no download was started',12);
      entries.push({original_filename:originalName,status:'failed',reason:'media_type_requires_confirmation'});
      options.onAttachmentProgress?.(entries);continue;
    }
    const previous = previousAttachments.find((item) => item.original_filename === originalName && item.status === "ok" && /^[0-9a-f]{64}$/.test(item.sha256 || ""));
    if (previous) {
      const objectPath = path.join(storage, "objects", previous.sha256.slice(0, 2), previous.sha256);
      try {
        const info = sha256File(objectPath);
        if (info.sha256 === previous.sha256 && info.size_bytes === previous.size_bytes) {
          entries.push({ ...previous, reused: true });
          if(options.control)options.control.counts.reused++;
          options.onAttachmentProgress?.(entries);
          continue;
        }
      } catch {}
    }
    if (runBudget.assets >= maxAssetsPerRun) {
      entries.push({ original_filename: originalName, status: "skipped", reason: "run_asset_budget_exhausted" });
      continue;
    }
    let pending = null;
    let stage = "open_attachment";
    try {
      const declaredSize=record.file_metadata?.find(f=>f.name===originalName)?.size;
      options.control?.file(declaredSize);
      if (attachmentIndex > 0 && record.source_url) {
        options.control?.step();
        await page.goto(record.source_url, { waitUntil: "domcontentloaded", timeout: 45_000 });
        await page.locator(".file-name").first().waitFor({ state: "visible", timeout: 10_000 });
      }
      const candidates=page.locator('.file-name').filter({hasText:options.control?new RegExp('^\\s*'+originalName.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')+'\\s*$'):originalName});
      if(options.control&&await candidates.count()!==1)throw new ZsxqWebError('visible_download_control_ambiguous','Expected exactly one matching file control',12);
      const target = candidates.first();
      if (!(await target.count())) {
        entries.push({ original_filename: originalName, status: "failed", reason: "visible_download_control_not_found" });
        continue;
      }
      await target.click({ timeout: 10_000 });
      const downloadControl = page.getByText("下载文件", { exact: true }).last();
      await downloadControl.waitFor({ state: "visible", timeout: 10_000 });
      stage = "await_download";
      options.control?.step();
      const [download] = await Promise.all([
        page.waitForEvent("download", { timeout: Number(options.downloadTimeoutMs || 15_000) }),
        downloadControl.click({ timeout: 10_000 }),
      ]);
      if(options.mediaPolicy==='text_non_audio'&&mediaKind(download.suggestedFilename()||originalName)!=='document'){
        await download.cancel();throw new ZsxqWebError('download_media_mismatch','Downloaded filename changed media type; cancelled',12);
      }
      const pendingDir = path.join(storage, ".pending");
      fs.mkdirSync(pendingDir, { recursive: true, mode: 0o700 });
      pending = path.join(pendingDir, `${process.pid}-${crypto.randomBytes(8).toString("hex")}`);
      stage = "save_download";
      let downloadTimer;
      try {await Promise.race([download.saveAs(pending),new Promise((_,reject)=>{downloadTimer=setTimeout(()=>{download.cancel().catch(()=>{});reject(new ZsxqWebError('download_timeout','Download timed out',12));},Number(options.downloadTimeoutMs||30000));})]);}
      finally {clearTimeout(downloadTimer);}
      const size=fs.statSync(pending).size;
      if(options.control&&(size!==declaredSize||size>maxBytes))throw new ZsxqWebError('download_size_mismatch','Actual file size differs from the authorized metadata',12);
      const info = sha256File(pending);
      if (info.size_bytes <= 0) throw new Error("empty");
      if(options.control&&path.extname(originalName).toLowerCase()==='.pdf'){
        const fd=fs.openSync(pending,'r'),header=Buffer.alloc(5);try{fs.readSync(fd,header,0,5,0);}finally{fs.closeSync(fd);}
        if(header.toString()!=='%PDF-')throw new ZsxqWebError('pdf_magic_mismatch','File content is not a PDF',12);
      }
      if (info.size_bytes > maxBytes) {
        entries.push({ original_filename: originalName, status: "skipped", reason: "asset_exceeds_max_bytes", size_bytes: info.size_bytes });
        continue;
      }
      const objectRelative = path.join("objects", info.sha256.slice(0, 2), info.sha256);
      const objectPath = path.join(storage, objectRelative);
      let alreadyStored = false;
      if(fs.existsSync(objectPath)){
        const existing=sha256File(objectPath);
        alreadyStored=existing.sha256===info.sha256&&existing.size_bytes===info.size_bytes;
      }
      if (!alreadyStored && runBudget.bytes + info.size_bytes > sizeGuardBytes) {
        entries.push({ original_filename: originalName, status: "skipped", reason: "size_guard_tripped", size_bytes: info.size_bytes });
        continue;
      }
      fs.mkdirSync(path.dirname(objectPath), { recursive: true });
      if (!alreadyStored) {
        // The validated replacement is ready before touching the old object.
        // Keep a recoverable copy of corrupt bytes; never truncate in place.
        if(fs.existsSync(objectPath)){
          const quarantine=path.join(storage,'.quarantine');fs.mkdirSync(quarantine,{recursive:true,mode:0o700});
          fs.copyFileSync(objectPath,path.join(quarantine,`${info.sha256}-${crypto.randomUUID()}`),fs.constants.COPYFILE_EXCL);
        }
        fs.renameSync(pending, objectPath);
      }
      runBudget.assets += 1;
      if(options.control){options.control.counts.downloaded++;options.control.counts.bytes+=info.size_bytes;}
      if (!alreadyStored) runBudget.bytes += info.size_bytes;
      entries.push({
        original_filename: originalName,
        safe_filename: safeName(download.suggestedFilename() || originalName),
        status: "ok",
        size_bytes: info.size_bytes,
        sha256: info.sha256,
        object_path: objectRelative,
      });
    } catch (error) {
      const isolatable=['asset_size_unverified','asset_exceeds_authorized_budget','visible_download_control_ambiguous','download_media_mismatch','download_size_mismatch','pdf_magic_mismatch','download_timeout'].includes(error.code);
      if(options.control&&!(options.isolateItemFailures&&isolatable))throw error;
      entries.push({ original_filename: originalName, status: "failed", reason: isolatable?error.code:"download_save_failed", stage, diagnostic: errorDiagnostic(error) });
      options.onAttachmentProgress?.(entries);
    } finally {
      try { if (pending && fs.existsSync(pending)) fs.unlinkSync(pending); } catch {}
      options.onAttachmentProgress?.(entries);
    }
  }
  for (const originalName of record.detected_attachments.slice(maxAssets)) {
    entries.push({ original_filename: originalName, status: "skipped", reason: "topic_asset_budget_exhausted" });
  }
  // A text-only refresh must not discard previously archived audio originals.
  for(const old of previousAttachments)if(old.status==='ok'&&!entries.some(e=>e.original_filename===old.original_filename))entries.push({...old,preserved:true});
  return entries;
}

async function runJob(context, job, root, options = {}, runtime = {}) {
  const jobRoot = path.join(root, "jobs", job.job_id);
  const topicsRoot = path.join(root, "groups", job.group_id, "topics");
  fs.mkdirSync(jobRoot, { recursive: true });
  const checkpointPath = path.join(jobRoot, "checkpoint.json");
  const manifestPath = path.join(jobRoot, "manifest.json");
  let checkpoint = { schema_version: 1, job_id: job.job_id, processed_topic_ids: [], topic_id_aliases: {}, failures: {} };
  if (fs.existsSync(checkpointPath)) {
    try { checkpoint = JSON.parse(fs.readFileSync(checkpointPath, "utf8")); }
    catch { throw new ZsxqWebError("checkpoint_invalid", "Checkpoint could not be read; preserved without resetting", 12, { checkpoint_path: checkpointPath }); }
  }
  checkpoint.topic_id_aliases = checkpoint.topic_id_aliases || {};
  checkpoint.failures = checkpoint.failures || {};
  const processed = new Set(checkpoint.processed_topic_ids || []);
  const knownSignatures = existingRecordSignatures(topicsRoot);
  let page;
  let discovery = { topics: [], reached_date_floor: false, oldest_visible_date: null, link_resolution: {} };
  const records = [];
  const maxTopicsPerRun = Number(options.maxTopicsPerRun || 50);
  let attemptedThisRun = 0;
  let stage = "open_browser_page";
  let currentTopicId = null;
  let fatalError = null;
  const saveCheckpoint = () => {
    checkpoint.processed_topic_ids = [...processed].sort();
    checkpoint.updated_at = new Date().toISOString();
    writeJsonAtomic(checkpointPath, checkpoint);
  };
  writeJsonAtomic(manifestPath, { schema_version: 1, job, status: "running", stage, started_at: new Date().toISOString(), checkpoint_path: checkpointPath, coverage_complete: false });
  try {
    page = context.pages().find((item) => !item.isClosed()) || await context.newPage();
    stage = "discover_topics";
    discovery = await (runtime.discoverTopics || discoverTopics)(page, job, options);
    const discoveryPage = page;
    page = await context.newPage();
    await discoveryPage.close();
    for (const topic of discovery.topics) {
      if(options.control&&processed.has(topic.topic_id)){
        try{if(!verifiedRecord(JSON.parse(fs.readFileSync(path.join(topicsRoot,topic.topic_id,'record.json'),'utf8')),root,options.mediaPolicy))processed.delete(topic.topic_id);}
        catch{processed.delete(topic.topic_id);}
      }
      if (processed.has(topic.topic_id)) continue;
      if(options.isolateItemFailures&&(checkpoint.failures[topic.topic_id]?.attempts||0)>=2)continue;
      if (attemptedThisRun >= maxTopicsPerRun) break;
      options.control?.topic();
      attemptedThisRun += 1;
      currentTopicId = topic.topic_id;
      try {
        if (page.isClosed()) page = await context.newPage();
        stage = "topic_metadata";
        const record = await (runtime.topicMetadata || topicMetadata)(page, topic, job, options.now || new Date(),options);
        if(options.control){options.control.counts.audioDeferred+=record.audio_count||0;options.control.counts.imagesDeferred+=record.image_count||0;if(!record.content_text)options.control.counts.metadataOnly++;if(!record.published_on)options.control.counts.unknownDates++;}
        if (record.published_on && (record.published_on < job.start || record.published_on > job.end)) {
          processed.add(topic.topic_id);
          continue;
        }
        const signature = recordSignature(record);
        const existing = signature ? knownSignatures.get(signature) : null;
        if (!options.control && existing?.complete && !/^\d+$/.test(existing.topic_id) && existing.topic_id !== topic.topic_id) {
          checkpoint.topic_id_aliases[topic.topic_id] = existing.topic_id;
          processed.add(topic.topic_id);
          delete checkpoint.failures[topic.topic_id];
          continue;
        }
        if (existing && existing.topic_id !== topic.topic_id) record.supersedes_topic_id = existing.topic_id;
        stage = "download_attachments";
        const topicRoot = path.join(topicsRoot, topic.topic_id);
        fs.mkdirSync(topicRoot, { recursive: true });
        let counted=false;
        const recordPath=path.join(topicRoot,'record.json'),existed=fs.existsSync(recordPath);
        const persist=entries=>{writeJsonAtomic(recordPath,{...record,attachments:entries});if(options.control&&!counted){const k=existed?'updatedRecords':'newRecords';options.control.counts[k]=(options.control.counts[k]||0)+1;counted=true;}};
        record.attachments = await (runtime.downloadVisibleFiles || downloadVisibleFiles)(page, record, job, root, {
          ...options,
          onAttachmentProgress: persist,
        });
        stage = "save_record";
        persist(record.attachments);
        writeJsonAtomic(path.join(topicRoot, "assets.json"), { topic_id: topic.topic_id, attachments: record.attachments });
        records.push(record);
        const attachmentsComplete = recordAttachmentsComplete(record,options.mediaPolicy);
        if (signature) knownSignatures.set(signature, { topic_id: topic.topic_id, complete: attachmentsComplete });
        if (attachmentsComplete) {
          processed.add(topic.topic_id);
          delete checkpoint.failures[topic.topic_id];
        } else {
          checkpoint.failures[topic.topic_id] = {
            code: "attachment_incomplete",
            retryable: true,
            attempts: (checkpoint.failures[topic.topic_id]?.attempts||0)+1,
            count: record.attachments.filter((item) => item.status !== "ok").length,
          };
        }
      } catch (error) {
        if(options.control&&isPause(error.code)){delete checkpoint.failures[topic.topic_id];throw error;}
        checkpoint.failures[topic.topic_id] = { code: error.code || "topic_failed", retryable: !["membership_expired", "membership_evidence_conflict", "download_disabled_by_group"].includes(error.code), diagnostic: errorDiagnostic(error) };
        if(options.control)throw error;
        if (error instanceof ZsxqWebError && ["human_login_required", "membership_expired", "membership_evidence_conflict"].includes(error.code)) throw error;
        if (/Target page, context or browser has been closed|Browser closed|crash/i.test(error.message || "")) {
          throw new ZsxqWebError("browser_interrupted", "The browser closed during archive; checkpoint was saved", 13, { cause: errorDiagnostic(error) });
        }
      } finally {
        saveCheckpoint();
      }
      stage = "topic_interval";
      // Pacing must remain independent of a page's lifetime.
      await delay(Number(options.topicIntervalMs ?? 1_500));
    }
  } catch (error) {
    fatalError = !(error instanceof ZsxqWebError)&&/Target page, context or browser has been closed|Browser closed|crash/i.test(error.message||'')
      ?new ZsxqWebError('browser_interrupted','Browser interrupted; checkpoint preserved',13,{cause:errorDiagnostic(error)}):error;
  }
  saveCheckpoint();
  const discoveredProcessed = discovery.topics.filter((topic) => processed.has(topic.topic_id)).length;
  const pendingRetry=options.isolateItemFailures&&discovery.topics.some(t=>!processed.has(t.topic_id)&&(checkpoint.failures[t.topic_id]?.attempts||0)<2);
  const manifest = {
    schema_version: 1,
    job,
    status: fatalError ? "interrupted" : "finished",
    stage,
    current_topic_id: currentTopicId,
    manifest_path: manifestPath,
    checkpoint_path: checkpointPath,
    error: fatalError ? { code: fatalError.code || "unexpected_error", diagnostic: errorDiagnostic(fatalError) } : null,
    finished_at: new Date().toISOString(),
    topics_discovered: discovery.topics.length,
    topics_processed_total: discoveredProcessed,
    checkpoint_topic_ids_total: processed.size,
    records_added_this_run: records.length,
    topics_attempted_this_run: attemptedThisRun,
    failures: checkpoint.failures,
    reached_date_floor: discovery.reached_date_floor,
    oldest_visible_date: discovery.oldest_visible_date,
    link_resolution: discovery.link_resolution,
    feed_pages: discovery.feed_pages || 0,
    discovery_exhausted: Boolean(discovery.discovery_exhausted),
    media_policy: options.mediaPolicy||'all',
    record_refs: [...new Set([...processed,...records.map(r=>r.topic_id),...(currentTopicId&&fs.existsSync(path.join(topicsRoot,currentTopicId,'record.json'))?[currentTopicId]:[])])].map(id=>`zsxq://topic/${id}`),
    attachments_this_run: records.flatMap((record) => record.attachments || []).reduce((acc, item) => {
      if(item.preserved)return acc;
      if (item.reused) acc.reused += 1;
      else if (item.status === "ok") { acc.downloaded += 1; acc.bytes_downloaded += item.size_bytes || 0; }
      else if (item.status === "skipped"||item.status==='deferred') acc.skipped += 1;
      else acc.failed += 1;
      return acc;
    }, { downloaded: 0, reused: 0, failed: 0, skipped: 0, bytes_downloaded: 0 }),
    archive_inventory: archiveInventory(topicsRoot, checkpoint.topic_id_aliases),
    all_discovered_processed: !fatalError && discovery.topics.every((topic) => processed.has(topic.topic_id)),
    all_discovered_attempted: !fatalError && discovery.topics.every(t=>processed.has(t.topic_id)||(checkpoint.failures[t.topic_id]?.attempts||0)>=2),
    run_budget_exhausted: /_budget_exhausted$/.test(fatalError?.code||'') || Boolean(pendingRetry) || discovery.topics.some((topic) => !processed.has(topic.topic_id)) && attemptedThisRun >= maxTopicsPerRun,
    coverage_complete: false,
    coverage_note: "Web infinite-scroll discovery cannot prove source-complete coverage.",
  };
  writeJsonAtomic(manifestPath, manifest);
  if (fatalError) {
    if (!(fatalError instanceof ZsxqWebError)) fatalError = new ZsxqWebError("unexpected_error", "Archive interrupted; see the saved manifest", 1, { diagnostic: errorDiagnostic(fatalError) });
    fatalError.details = { ...fatalError.details, stage, current_topic_id: currentTopicId, manifest_path: manifestPath, checkpoint_path: checkpointPath };
    throw fatalError;
  }
  return manifest;
}

async function runPlan(plan, options = {}, runtime={}) {
  const allJobs = (plan.jobs || []).filter((job) => job.route === "zsxq_web" && job.state === "pending");
  const jobs = allJobs.slice(0, Number(options.maxJobsPerRun || 1));
  if (!jobs.length) throw new ZsxqWebError("no_pending_web_jobs", "The plan contains no pending zsxq_web jobs", 2);
  const root = path.join(path.resolve(plan.archive_root), "zsxq_web");
  const release = acquireLock(root);
  let context;
  try {
    options.control?.check();
    const settings = (runtime.browserOptions||browserOptions)(options, Boolean(options.headed));
    context = await launchContext(settings,runtime);
    const manifests = [];
    options.runBudget = { assets: 0, bytes: objectsDiskTotal(root) };
    for (const job of jobs) manifests.push(await runJob(context, job, root, options,runtime));
    const partial = jobs.length < allJobs.length || manifests.some((manifest) =>
      !(manifest.reached_date_floor||manifest.discovery_exhausted) || !manifest.all_discovered_processed || Object.keys(manifest.failures || {}).length > 0);
    return { status: partial ? "partial" : "completed", archive_root: root, jobs_remaining_after_budget: Math.max(0, allJobs.length - jobs.length), jobs: manifests };
  } finally {
    if (context) await context.close().catch(() => {});
    release();
  }
}

module.exports = { discoverTopics, downloadVisibleFiles, objectsDiskTotal, parseBrowserFeed, parseTopicDate, runJob, runPlan, safeName, topicMetadata };
