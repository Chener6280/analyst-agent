"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright-core");
const { ZsxqWebError, defaultChromePath, defaultProfileDir } = require("./core");

function browserOptions(options = {}, headed = false) {
  const executablePath = path.resolve(options.chromePath || defaultChromePath());
  if (!fs.existsSync(executablePath)) {
    throw new ZsxqWebError("chrome_not_found", `Google Chrome was not found at ${executablePath}`, 3);
  }
  const profileDir = path.resolve(options.profileDir || defaultProfileDir());
  fs.mkdirSync(profileDir, { recursive: true, mode: 0o700 });
  return {
    profileDir,
    launch: {
      // Desktop headless uses Playwright's matching headless shell. Full
      // Chrome 153's --headless download path crashes on this macOS host.
      ...(!headed&&options.headless===true&&!options.chromePath&&!process.env.CHROME_EXECUTABLE_PATH?{}:{executablePath}),
      timeout: 30_000,
      // Chrome 153's macOS headless browser process crashed during live archive
      // runs. Keep a normal window by default there; operators can opt in again.
      headless: !headed && (typeof options.headless==='boolean'?options.headless:process.env.ZSXQ_WEB_HEADLESS !== undefined
        ? process.env.ZSXQ_WEB_HEADLESS === "1" : process.platform !== "darwin"),
      acceptDownloads: true,
      viewport: { width: 1440, height: 1000 },
      locale: "zh-CN",
      timezoneId: "Asia/Shanghai",
    },
  };
}

async function launchContext(settings,runtime={}){
  try{return await (runtime.launch||chromium.launchPersistentContext.bind(chromium))(settings.profileDir,settings.launch);}
  catch(e){
    if(/ProcessSingleton|profile.*in use|SingletonLock/i.test(e.message||''))throw new ZsxqWebError('browser_profile_busy','Dedicated browser profile is already in use',12);
    if(settings.launch.headless&&/Executable doesn't exist|executable.*does not exist/i.test(e.message||''))throw new ZsxqWebError('headless_browser_missing','Install the matching Playwright chromium-headless-shell runtime',3);
    if(settings.launch.headless)throw new ZsxqWebError('headless_browser_failed','Background browser could not start; no visible fallback was opened',13);
    throw e;
  }
}
function observeAbort(context,signal){
  const close=()=>{context.close().catch(()=>{});};
  signal?.addEventListener('abort',close,{once:true});if(signal?.aborted)close();
  return ()=>signal?.removeEventListener('abort',close);
}
// Routine desktop checks are silent. Only a positively identified login page
// may open a visible QR window; crashes, rate limits and unknown pages do not.
async function ensureLogin(options={},runtime={}){
  if(!/^\d{1,30}$/.test(String(options.groupId||'')))throw new ZsxqWebError('invalid_group_id','Invalid login group',2);
  const settings=(runtime.browserOptions||browserOptions)({...options,headless:true},false);
  const context=await launchContext(settings,runtime),unbind=observeAbort(context,options.signal);
  let state;
  try{
    const page=context.pages()[0]||await context.newPage();
    await page.goto(`https://wx.zsxq.com/group/${options.groupId}`,{waitUntil:'domcontentloaded',timeout:45000});
    state=await (runtime.inspectPage||inspectPage)(page);
  }catch(e){
    if(options.signal?.aborted)throw new ZsxqWebError('user_stopped','Login check stopped',13);
    if(/closed|crash/i.test(e.message||''))throw new ZsxqWebError('headless_browser_failed','Background login check was interrupted',13);
    throw e;
  }finally{unbind();await context.close().catch(()=>{});}
  if(options.signal?.aborted)throw new ZsxqWebError('user_stopped','Login check stopped',13);
  if(state.authenticated)return {status:'ready',authenticated:true,browser_mode:'headless',group_id:options.groupId};
  if(!state.login_required)throw new ZsxqWebError('web_login_state_unknown','Page did not establish authentication or a login requirement',13);
  return login(options,runtime);
}

// A renewal reminder is not an expiry notice. Never interpret article prose as
// an account entitlement. Conflicting website/API evidence must stop for review.
function membershipEvidence(text) {
  const explicit = /成员体验已到期|(?:你的|您的)(?:会员|成员资格|订阅)(?:已经|已)到期|(?:你|您)已于\s*20\d{2}[年/.\-]\d{1,2}[月/.\-]\d{1,2}日?[^\n]{0,20}到期/.test(text);
  return { expired: explicit, reminder: /续期提醒|即将到期/.test(text) };
}
function assertMembership(access, job) {
  if (job.membership?.active !== true) throw new ZsxqWebError('membership_expired', 'Fresh subscription scan does not permit this group', 20);
  if (access.renewal_required) throw new ZsxqWebError('membership_evidence_conflict', 'Website expiry notice conflicts with active subscription scan; review this group', 20);
}
async function inspectPage(page) {
  await page.waitForLoadState("domcontentloaded", { timeout: 30_000 }).catch(() => {});
  await page.waitForTimeout(1_200);
  const title = await page.title().catch(() => "");
  const body = await page.locator("body").innerText({ timeout: 10_000 }).catch(() => "");
  const loginRequired = /登录知识星球|微信扫码登录|登录后继续/.test(body) || /login/i.test(page.url());
  const interfaceText = await page.locator('body').evaluate(node => {
    const copy = node.cloneNode(true);
    copy.querySelectorAll('app-topic, app-topic-detail, article, script, style').forEach(n => n.remove());
    return copy.textContent || '';
  });
  const evidence = membershipEvidence(interfaceText);
  const renewalRequired = evidence.expired;
  const memberApp = await page.locator("app-topic, app-topic-detail").count().catch(() => 0);
  const authenticated = !loginRequired && /知识星球/.test(title) && (
    memberApp > 0 || /所有星球|最新动态|加入的星球|可搜索当前星球/.test(body)
  );
  return { title, url: page.url(), authenticated, login_required: loginRequired, renewal_required: renewalRequired, body };
}

async function login(options = {}, runtime={}) {
  const settings = (runtime.browserOptions||browserOptions)(options, true);
  const context = await launchContext(settings,runtime),unbind=observeAbort(context,options.signal);
  try {
  const page = context.pages()[0] || await context.newPage();
  const groupId = options.groupId ? String(options.groupId) : null;
  // Use the known selected page to reach the member app, but inspect account
  // authentication only. A group's renewal banner is not an account logout.
  // Download discovery and topic reads still enforce membership separately.
  await page.goto(groupId ? `https://wx.zsxq.com/group/${groupId}` : 'https://wx.zsxq.com/login', { waitUntil: "domcontentloaded", timeout: 45_000 });
  const inspect=runtime.inspectPage||inspectPage;
  let state = await inspect(page);
  if (!state.authenticated) {
    await page.goto("https://wx.zsxq.com/login", { waitUntil: "domcontentloaded", timeout: 45_000 });
    const checkbox = page.locator('input[type="checkbox"]').first();
    if (await checkbox.count()) await checkbox.check({ force: true }).catch(() => {});
    const qrButton = page.getByText("获取登录二维码", { exact: true });
    if (await qrButton.count()) await qrButton.click().catch(() => {});
    await page.bringToFront?.().catch(() => {});
    state = await inspect(page);
  }
  const deadline = Date.now() + Number(options.waitSeconds || 600) * 1000;
  while (!state.authenticated && Date.now() < deadline) {
    await page.waitForTimeout(1_000);
    state = await inspect(page);
  }
  if (!state.authenticated) {
    throw new ZsxqWebError("human_login_required", "Open browser login did not complete before the timeout", 10, { profile_dir: settings.profileDir });
  }
  return { status: "ready", authenticated: true, profile_dir: settings.profileDir, group_id: groupId };
  } catch(e){if(options.signal?.aborted)throw new ZsxqWebError('user_stopped','Login stopped',13);throw e;}
  finally {unbind();await context.close().catch(()=>{});}
}

async function probe(options = {}) {
  const groupId = String(options.groupId || "");
  if (!/^\d+$/.test(groupId)) throw new ZsxqWebError("invalid_group_id", "group-id must contain digits only", 2);
  const settings = browserOptions(options, Boolean(options.headed));
  const context = await launchContext(settings);
  try {
  const page = context.pages()[0] || await context.newPage();
  await page.goto(`https://wx.zsxq.com/group/${groupId}`, { waitUntil: "domcontentloaded", timeout: 45_000 });
  const state = await inspectPage(page);
  await page.locator("app-topic").first().waitFor({ state: "attached", timeout: 10_000 }).catch(() => {});
  const topicLinkCount = await page.locator('a[href*="/topic/"]').count().catch(() => 0);
  const topicCardCount = await page.locator("app-topic").count().catch(() => 0);
  const fileMarkerCount = await page.locator(".file-name").count().catch(() => 0);
  const imageCount = await page.locator("img").count().catch(() => 0);
  return {
    status: state.authenticated && !state.renewal_required ? "ready" : "blocked",
    group_id: groupId,
    page_title: state.title,
    authenticated: state.authenticated,
    login_required: state.login_required,
    renewal_required: state.renewal_required,
    visible_topic_links: topicLinkCount,
    visible_topic_cards: topicCardCount,
    visible_file_markers: fileMarkerCount,
    visible_images: imageCount,
    profile_dir: settings.profileDir,
  };
  } finally {await context.close().catch(()=>{});}
}

module.exports = { browserOptions, launchContext, ensureLogin, inspectPage, login, probe, membershipEvidence, assertMembership };
