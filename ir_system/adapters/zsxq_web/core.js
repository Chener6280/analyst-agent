"use strict";

const { spawnSync } = require("node:child_process");
const crypto = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const SCHEMA_VERSION = 1;
const DEFAULT_CLI_TIMEOUT_MS = 120_000;

class ZsxqWebError extends Error {
  constructor(code, message, exitCode = 1, details = {}) {
    super(message);
    this.name = "ZsxqWebError";
    this.code = code;
    this.exitCode = exitCode;
    this.details = details;
  }
}

function isoNow() {
  return new Date().toISOString();
}

function defaultArchiveRoot() {
  if (process.env.IR_ARCHIVE_ROOT) return path.resolve(process.env.IR_ARCHIVE_ROOT);
  return path.join(os.homedir(), "Documents", "ir_archive");
}

function defaultProfileDir() {
  if (process.env.ZSXQ_WEB_PROFILE_DIR) return path.resolve(process.env.ZSXQ_WEB_PROFILE_DIR);
  if (process.platform === "darwin") {
    return path.join(os.homedir(), "Library", "Application Support", "IR System", "zsxq-web-profile");
  }
  if (process.platform === "win32") {
    return path.join(process.env.APPDATA || path.join(os.homedir(), "AppData", "Roaming"), "IR System", "zsxq-web-profile");
  }
  return path.join(process.env.XDG_DATA_HOME || path.join(os.homedir(), ".local", "share"), "ir-system", "zsxq-web-profile");
}

function defaultChromePath() {
  if (process.env.CHROME_EXECUTABLE_PATH) return path.resolve(process.env.CHROME_EXECUTABLE_PATH);
  // Prefer the runtime pinned to this Playwright installation. The normal
  // desktop Chrome auto-updates independently and can introduce native crashes.
  try {
    const candidate = require("playwright-core").chromium.executablePath();
    if (fs.existsSync(candidate)) return candidate;
  } catch {}
  if (process.platform === "darwin") {
    return "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
  }
  if (process.platform === "win32") {
    const roots = [process.env.PROGRAMFILES, process.env["PROGRAMFILES(X86)"], process.env.LOCALAPPDATA].filter(Boolean);
    for (const root of roots) {
      const candidate = path.join(root, "Google", "Chrome", "Application", "chrome.exe");
      if (fs.existsSync(candidate)) return candidate;
    }
    return "chrome.exe";
  }
  for (const candidate of ["/usr/bin/google-chrome", "/usr/bin/google-chrome-stable", "/usr/bin/chromium", "/usr/bin/chromium-browser"]) {
    if (fs.existsSync(candidate)) return candidate;
  }
  return "google-chrome";
}

function resolveCli(explicit) {
  const configured = explicit || process.env.ZSXQ_CLI_COMMAND;
  if (configured) return path.resolve(configured);
  const legacy = path.join(os.homedir(), ".hermes", "node", "bin", "zsxq-cli");
  if (fs.existsSync(legacy)) return legacy;
  return "zsxq-cli";
}

function redactMessage(value) {
  const text = String(value || "").replace(/https?:\/\/\S+/g, "[url]");
  if (/rate.?limit|too many requests|429/i.test(text)) return "Knowledge Planet rate limit";
  if (/not logged in|authentication|token|401/i.test(text)) return "Knowledge Planet authentication is required";
  if (/entitlement|permission|forbidden|403|未开通|无权限/i.test(text)) return "Knowledge Planet permission denied";
  if (/timeout|timed out/i.test(text)) return "Knowledge Planet request timed out";
  return "Knowledge Planet CLI request failed";
}

// Finder-launched apps do not inherit a shell's Node PATH. Run npm's JS
// launcher with our own runtime (Electron in Node mode in the desktop app).
// Native CLI binaries still run directly. No shell, profile or credentials read.
function cliInvocation(executable, args, env = process.env) {
  let entry = executable;
  if (!path.isAbsolute(entry)) {
    entry = (env.PATH || '').split(path.delimiter).map(dir => path.join(dir, executable))
      .find(candidate => { try { return fs.statSync(candidate).isFile(); } catch { return false; } }) || executable;
  }
  try {
    entry = fs.realpathSync(entry);
    const fd = fs.openSync(entry, 'r'), header = Buffer.alloc(256);
    let length;
    try { length = fs.readSync(fd, header, 0, header.length, 0); } finally { fs.closeSync(fd); }
    if (/\.[cm]?js$/i.test(entry) || /^#![^\r\n]*\bnode(?:\s|$)/.test(header.subarray(0, length).toString())) {
      return { command: process.execPath, args: [entry, ...args], env: { ...env, ELECTRON_RUN_AS_NODE: '1' } };
    }
  } catch { /* Preserve normal ENOENT / EACCES handling below. */ }
  return { command: executable, args, env };
}

function cliFailure(result) {
  if (result.error?.code === 'ENOENT') return 'zsxq_cli_not_found';
  if (result.error?.code === 'ETIMEDOUT') return 'zsxq_cli_timeout';
  const message = `${result.stderr || ''}\n${result.stdout || ''}`;
  if (/env:.*node.*(?:No such file|not found)/i.test(message)) return 'zsxq_node_runtime_missing';
  if (/not logged in|authentication|token|401/i.test(message)) return 'zsxq_auth_required';
  if (/rate.?limit|too many requests|429/i.test(message)) return 'zsxq_rate_limited';
  return 'zsxq_cli_failed';
}

function runZsxqCli(executable, args, options = {}) {
  const invocation = cliInvocation(executable, args);
  const result = spawnSync(invocation.command, invocation.args, {
    encoding: "utf8",
    maxBuffer: 32 * 1024 * 1024,
    timeout: options.timeoutMs || DEFAULT_CLI_TIMEOUT_MS,
    env: invocation.env,
  });
  if (result.error) {
    const code = cliFailure(result);
    throw new ZsxqWebError(code, redactMessage(result.error.message), code === "zsxq_cli_not_found" ? 3 : 4);
  }
  if (result.status !== 0) {
    throw new ZsxqWebError(cliFailure(result), redactMessage(result.stderr || result.stdout), 4, { status: result.status });
  }
  return String(result.stdout || "");
}

function probeSkillApi(executable, groupId, options = {}) {
  const invocation = cliInvocation(executable, [
    "api", "raw", "--method", "GET", "--path", `/v2/groups/${groupId}/topics`,
    "--query", JSON.stringify({ scope: "all", count: 1 }),
  ]);
  const result = spawnSync(invocation.command, invocation.args, {
    encoding: "utf8",
    maxBuffer: 8 * 1024 * 1024,
    timeout: options.timeoutMs || DEFAULT_CLI_TIMEOUT_MS,
    env: invocation.env,
  });
  const combined = `${result.stdout || ""}\n${result.stderr || ""}`;
  if (result.error) return { state: result.error.code === "ETIMEDOUT" ? "timeout" : "error" };
  if (result.status !== 0) {
    if (/暂未开通\s*Skill\s*权限|permission denied|entitlement/i.test(combined)) return { state: "not_enabled" };
    if (/rate.?limit|too many requests|429/i.test(combined)) return { state: "rate_limited" };
    if (/not logged in|authentication|token|401/i.test(combined)) return { state: "authentication_required" };
    return { state: "error" };
  }
  let payload;
  try {
    payload = JSON.parse(String(result.stdout || ""));
  } catch {
    return { state: "error" };
  }
  const body = payload?.body || payload;
  if (body?.succeeded === true || payload?.succeeded === true) return { state: "accessible" };
  const message = String(body?.error || body?.info || payload?.error?.message || "");
  if (body?.code === 14210 || /体验已到期|会员.*到期|成员.*到期/.test(message)) return { state: "membership_expired" };
  if (/暂未开通\s*Skill\s*权限/.test(message)) return { state: "not_enabled" };
  return { state: "error" };
}

function parseJsonOutput(raw, code = "invalid_zsxq_response") {
  try {
    return JSON.parse(raw);
  } catch {
    throw new ZsxqWebError(code, "Knowledge Planet CLI returned invalid JSON", 4);
  }
}

function unwrapGroupDetail(payload) {
  const group = payload?.body?.resp_data?.group || payload?.resp_data?.group || payload?.group;
  const succeeded = payload?.success !== false && payload?.body?.succeeded !== false;
  if (!succeeded || !group) {
    const hint = JSON.stringify(payload?.error || payload?.body?.resp_data?.error || {});
    throw new ZsxqWebError("group_detail_failed", redactMessage(hint), 4);
  }
  return group;
}

function dateOnly(value) {
  if (!value || typeof value !== "string") return null;
  const match = value.match(/^(\d{4}-\d{2}-\d{2})/);
  return match ? match[1] : null;
}

function classifyMembership(group, now = new Date()) {
  const membership = group?.user_specific?.membership || {};
  const validity = group?.user_specific?.validity || {};
  const endTime = membership.end_time || validity.end_time || null;
  const end = endTime ? new Date(endTime) : null;
  if (group?.type === "free" && !endTime) {
    return { state: "active_free", active: true, end_time: null, end_date: null };
  }
  if (end && Number.isFinite(end.getTime()) && end.getTime() > now.getTime()) {
    return { state: "active_paid", active: true, end_time: endTime, end_date: dateOnly(endTime) };
  }
  return { state: "expired", active: false, end_time: endTime, end_date: dateOnly(endTime) };
}

function normalizeGroup(group, now = new Date(), skillApi = null) {
  const policies = group.policies || {};
  const membership = classifyMembership(group, now);
  return {
    group_id: String(group.group_id),
    name: String(group.name || ""),
    group_type: group.type || "unknown",
    membership,
    skill_setting: policies.enable_ai_openapi ? "enabled" : "disabled",
    skill_api: skillApi?.state || "not_probed",
    permissions: {
      allow_download: Boolean(policies.allow_download),
      allow_copy: Boolean(policies.allow_copy),
      allow_screen_capture_recording: Boolean(policies.allow_screen_capture_recording),
    },
    statistics: {
      files_count: Number(group?.statistics?.files?.count || 0),
      topics_count: Number(group?.statistics?.topics?.topics_count || 0),
    },
    scan_status: "ok",
  };
}

function summarizeGroups(groups) {
  const summary = {
    total: groups.length,
    active_paid: 0,
    active_free: 0,
    expired: 0,
    skill_accessible: 0,
    skill_not_enabled: 0,
    skill_membership_expired: 0,
    skill_probe_errors: 0,
    web_download_eligible: 0,
    blocked_by_download_policy: 0,
    scan_errors: 0,
  };
  for (const group of groups) {
    if (group.scan_status !== "ok") {
      summary.scan_errors += 1;
      continue;
    }
    summary[group.membership.state] += 1;
    if (group.skill_api === "accessible") summary.skill_accessible += 1;
    else if (group.skill_api === "not_enabled") summary.skill_not_enabled += 1;
    else if (group.skill_api === "membership_expired") summary.skill_membership_expired += 1;
    else summary.skill_probe_errors += 1;
    if (group.membership.active && group.skill_api === "not_enabled") {
      if (group.permissions.allow_download) summary.web_download_eligible += 1;
      else summary.blocked_by_download_policy += 1;
    }
  }
  return summary;
}

function sleep(ms) {
  if (!ms) return;
  const shared = new Int32Array(new SharedArrayBuffer(4));
  Atomics.wait(shared, 0, 0, ms);
}

function scanGroups(options = {}) {
  const executable = resolveCli(options.zsxqCli);
  const list = parseJsonOutput(runZsxqCli(executable, ["group", "+list", "--limit", "200", "--scope", "all", "--json"], options));
  const listed = Array.isArray(list.groups) ? list.groups : [];
  const groups = [];
  for (let index = 0; index < listed.length; index += 1) {
    const row = listed[index];
    const groupId = String(row.group_id || "");
    if (!/^\d+$/.test(groupId)) continue;
    try {
      const detail = parseJsonOutput(runZsxqCli(executable, ["api", "raw", "--method", "GET", "--path", `/v2/groups/${groupId}`], options));
      const normalized = normalizeGroup(unwrapGroupDetail(detail), options.now || new Date());
      if (options.probeSkill !== false) {
        const skillApi = probeSkillApi(executable, groupId, options);
        normalized.skill_api = skillApi.state;
      }
      groups.push(normalized);
      if (["rate_limited", "authentication_required", "timeout", "error"].includes(normalized.skill_api)) break;
    } catch (error) {
      groups.push({
        group_id: groupId,
        name: String(row.name || ""),
        scan_status: "error",
        error_code: error.code || "group_detail_failed",
      });
      if (error.code === "zsxq_cli_not_found") throw error;
      // A failed CLI call can represent rate limiting or authentication. Do not
      // keep probing other subscriptions after an unresolved transport failure.
      break;
    }
    if (index + 1 < listed.length) sleep(options.intervalMs ?? 200);
  }
  groups.sort((left, right) => left.group_id.localeCompare(right.group_id));
  return {
    schema_version: SCHEMA_VERSION,
    provider: "zsxq",
    scanned_at: isoNow(),
    account_scope: "current_authenticated_account",
    groups,
    summary: summarizeGroups(groups),
  };
}

function parseDate(value, label) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(String(value || ""))) {
    throw new ZsxqWebError("invalid_date", `${label} must use YYYY-MM-DD`, 2);
  }
  const date = new Date(`${value}T00:00:00+08:00`);
  if (!Number.isFinite(date.getTime())) throw new ZsxqWebError("invalid_date", `${label} is invalid`, 2);
  return String(value);
}

function buildPlan(scan, options = {}) {
  const start = parseDate(options.start, "start");
  const end = parseDate(options.end, "end");
  if (start > end) throw new ZsxqWebError("invalid_date_range", "start must not be after end", 2);
  const selected = new Set((options.groupIds || []).map(String));
  const includeAll = selected.size === 0;
  const jobs = [];
  for (const group of scan.groups || []) {
    if (!includeAll && !selected.has(String(group.group_id))) continue;
    let route = "blocked";
    let state = "blocked";
    let reason = "scan_failed";
    if (group.scan_status === "ok") {
      if (!group.membership.active) reason = "membership_expired";
      else if (group.skill_api === "accessible") {
        route = "ir_search";
        state = "delegated";
        reason = "skill_api_enabled";
      } else if (group.skill_api !== "not_enabled") {
        reason = `skill_probe_${group.skill_api || "unknown"}`;
      } else if (!group.permissions.allow_download) {
        reason = "download_disabled_by_group";
      } else {
        route = "zsxq_web";
        state = "pending";
        reason = null;
      }
    }
    jobs.push({
      job_id: crypto.createHash("sha256").update(JSON.stringify({ group_id: group.group_id, start, end, route })).digest("hex").slice(0, 24),
      group_id: String(group.group_id),
      group_name: group.name || "",
      start,
      end,
      route,
      state,
      reason,
      include: {
        topics: group.permissions?.allow_copy ? "full_text" : "metadata_only",
        attachments: Boolean(group.permissions?.allow_download),
        images: group.permissions?.allow_screen_capture_recording ? "visible_original_when_available" : "explicit_download_only",
      },
      permissions: group.permissions || null,
      membership: group.membership || null,
    });
  }
  const requestedMissing = [...selected].filter((id) => !(scan.groups || []).some((group) => String(group.group_id) === id));
  if (requestedMissing.length) {
    throw new ZsxqWebError("group_not_found", "One or more selected group IDs were not found in the fresh scan", 2, { group_ids: requestedMissing });
  }
  const counts = jobs.reduce((acc, job) => {
    acc[job.state] = (acc[job.state] || 0) + 1;
    return acc;
  }, {});
  return {
    schema_version: SCHEMA_VERSION,
    plan_type: "zsxq_web_archive",
    created_at: isoNow(),
    scan_scanned_at: scan.scanned_at || null,
    scan_snapshot_path: scan.output_path || null,
    archive_root: path.resolve(options.archiveRoot || defaultArchiveRoot()),
    date_range: { start, end, timezone: "Asia/Shanghai", inclusive: true },
    jobs,
    summary: { total: jobs.length, pending_web: counts.pending || 0, delegated_ir_search: counts.delegated || 0, blocked: counts.blocked || 0 },
  };
}

function writeJsonAtomic(target, payload) {
  const absolute = path.resolve(target);
  fs.mkdirSync(path.dirname(absolute), { recursive: true });
  const temporary = `${absolute}.tmp-${process.pid}-${crypto.randomBytes(4).toString("hex")}`;
  fs.writeFileSync(temporary, `${JSON.stringify(payload, null, 2)}\n`, { encoding: "utf8", mode: 0o600 });
  fs.renameSync(temporary, absolute);
  return absolute;
}

function readJson(target) {
  try {
    return JSON.parse(fs.readFileSync(path.resolve(target), "utf8"));
  } catch (error) {
    throw new ZsxqWebError("invalid_json_file", `Cannot read JSON file: ${path.resolve(target)}`, 2, { cause: error.code || "parse_error" });
  }
}

module.exports = {
  SCHEMA_VERSION,
  ZsxqWebError,
  buildPlan,
  classifyMembership,
  cliInvocation,
  defaultArchiveRoot,
  defaultChromePath,
  defaultProfileDir,
  normalizeGroup,
  probeSkillApi,
  readJson,
  resolveCli,
  runZsxqCli,
  scanGroups,
  summarizeGroups,
  writeJsonAtomic,
};
