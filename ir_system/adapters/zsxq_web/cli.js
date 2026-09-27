#!/usr/bin/env node
"use strict";

const fs = require("node:fs");
const path = require("node:path");
const {
  ZsxqWebError,
  buildPlan,
  defaultArchiveRoot,
  defaultChromePath,
  defaultProfileDir,
  readJson,
  resolveCli,
  runZsxqCli,
  scanGroups,
  writeJsonAtomic,
} = require("./core");
const { login, probe } = require("./browser");
const { runPlan } = require("./archive");
const { errorDiagnostic } = require("./diagnostics");

function parseArgs(argv) {
  const command = argv[0];
  const values = {};
  const repeated = new Set(["group-id"]);
  for (let index = 1; index < argv.length; index += 1) {
    const token = argv[index];
    if (!token.startsWith("--")) throw new ZsxqWebError("invalid_argument", `Unexpected argument: ${token}`, 2);
    const key = token.slice(2);
    if (["headed"].includes(key)) {
      values[key] = true;
      continue;
    }
    const value = argv[index + 1];
    if (value === undefined || value.startsWith("--")) throw new ZsxqWebError("missing_argument_value", `--${key} requires a value`, 2);
    index += 1;
    if (repeated.has(key)) {
      values[key] = values[key] || [];
      values[key].push(value);
    } else {
      values[key] = value;
    }
  }
  return { command, values };
}

function required(values, key) {
  if (!values[key]) throw new ZsxqWebError("missing_argument", `--${key} is required`, 2);
  return values[key];
}

function numberValue(values, key, fallback) {
  if (values[key] === undefined) return fallback;
  const value = Number(values[key]);
  if (!Number.isFinite(value) || value < 0) throw new ZsxqWebError("invalid_argument", `--${key} must be a non-negative number`, 2);
  return value;
}

function emit(payload) {
  process.stdout.write(`${JSON.stringify(payload, null, 2)}\n`);
}

function usage() {
  return {
    status: "usage",
    commands: {
      doctor: "Check Chrome, zsxq-cli authentication, and the dedicated browser profile.",
      scan: "Re-scan every joined group and save a sanitized subscription snapshot.",
      plan: "Build deterministic web/archive/delegated/blocked jobs from a fresh scan.",
      prepare: "Run scan and plan in one command; use this before every archive run.",
      backfill: "One-shot full scan, bounded plan, and resumable web archive for weak workers.",
      login: "Open the dedicated Chrome profile for one-time human login.",
      probe: "Verify one group through the dedicated browser profile without saving content.",
      run: "Validate a fresh all-group scan, then execute pending zsxq_web jobs from its plan.",
    },
  };
}

function archiveOptions(values) {
  return {
    headed: Boolean(values.headed),
    profileDir: values["profile-dir"],
    chromePath: values["chrome-path"],
    maxScrolls: numberValue(values, "max-scrolls", 120),
    scrollDelayMs: numberValue(values, "scroll-delay-ms", 900),
    topicIntervalMs: numberValue(values, "topic-interval-ms", 1500),
    maxAssetsPerTopic: numberValue(values, "max-assets-per-topic", 50),
    assetMaxBytes: numberValue(values, "asset-max-bytes", 200 * 1024 * 1024),
    downloadTimeoutMs: numberValue(values, "download-timeout-ms", 15_000),
    maxJobsPerRun: numberValue(values, "max-jobs-per-run", 1),
    maxTopicsPerRun: numberValue(values, "max-topics-per-run", 50),
    maxAssetsPerRun: numberValue(values, "max-assets-per-run", 100),
    sizeGuardBytes: numberValue(values, "size-guard-bytes", 20 * 1024 * 1024 * 1024),
  };
}

function validateFreshPlan(planPayload, values) {
  if (!planPayload.scan_snapshot_path || !planPayload.scan_scanned_at) {
    throw new ZsxqWebError("fresh_scan_required", "Plan does not reference a complete all-group scan; run prepare again", 12);
  }
  const freshScan = readJson(planPayload.scan_snapshot_path);
  const scanAgeMs = Date.now() - Date.parse(planPayload.scan_scanned_at);
  const maxAgeMs = numberValue(values, "max-plan-age-minutes", 15) * 60_000;
  if (freshScan.status !== "complete" || freshScan.scanned_at !== planPayload.scan_scanned_at || !Number.isFinite(scanAgeMs) || scanAgeMs < 0 || scanAgeMs > maxAgeMs) {
    throw new ZsxqWebError("fresh_scan_required", "The plan's all-group scan is stale or incomplete; run prepare again", 12, { max_plan_age_minutes: maxAgeMs / 60_000 });
  }
  const byId = new Map(freshScan.groups.map((group) => [String(group.group_id), group]));
  for (const job of (planPayload.jobs || []).filter((item) => item.route === "zsxq_web" && item.state === "pending")) {
    const current = byId.get(String(job.group_id));
    if (!current || current.scan_status !== "ok") throw new ZsxqWebError("fresh_scan_failed", `Fresh scan failed for group ${job.group_id}`, 12);
    if (!current.membership.active) throw new ZsxqWebError("membership_expired", `Membership expired for group ${job.group_id}`, 20);
    if (current.skill_api !== "not_enabled") throw new ZsxqWebError("route_changed", `Skill route changed for group ${job.group_id}; create a new plan`, 12);
    if (!current.permissions.allow_download) throw new ZsxqWebError("download_disabled_by_group", `Downloads are disabled for group ${job.group_id}`, 21);
  }
  return freshScan;
}

async function executePlan(planPayload, values) {
  validateFreshPlan(planPayload, values);
  return runPlan(planPayload, archiveOptions(values));
}

function doctor(values) {
  const zsxqCli = resolveCli(values["zsxq-cli"]);
  const chromePath = path.resolve(values["chrome-path"] || defaultChromePath());
  let auth = "unavailable";
  try {
    const output = runZsxqCli(zsxqCli, ["auth", "status"]);
    auth = !/not logged in|未登录/i.test(output) && /logged in|已登录/i.test(output) ? "ready" : "required";
  } catch (error) {
    auth = error.code || "unavailable";
  }
  const profileDir = path.resolve(values["profile-dir"] || defaultProfileDir());
  return {
    status: fs.existsSync(chromePath) && auth === "ready" ? "ready" : "attention_required",
    node: process.version,
    chrome: { path: chromePath, available: fs.existsSync(chromePath) },
    zsxq_cli: { command: zsxqCli, auth },
    browser_profile: { path: profileDir, exists: fs.existsSync(profileDir) },
    archive_root: path.resolve(values["archive-root"] || defaultArchiveRoot()),
  };
}

function scan(values) {
  const result = scanGroups({
    zsxqCli: values["zsxq-cli"],
    intervalMs: numberValue(values, "interval-ms", 200),
    timeoutMs: numberValue(values, "timeout-ms", 120_000),
  });
  const requestedOutput = values.out || path.join(path.resolve(values["archive-root"] || defaultArchiveRoot()), "subscriptions", "latest.json");
  const complete = result.summary.scan_errors === 0 && result.summary.skill_probe_errors === 0;
  result.status = complete ? "complete" : "partial";
  const failedName = `scan-${result.scanned_at.replace(/[:.]/g, "-")}.json`;
  const output = complete ? requestedOutput : path.join(path.dirname(requestedOutput), "failed", failedName);
  result.output_path = writeJsonAtomic(output, result);
  return result;
}

function plan(values, scanPayload = null) {
  const source = scanPayload || readJson(required(values, "scan"));
  const result = buildPlan(source, {
    start: required(values, "start"),
    end: required(values, "end"),
    archiveRoot: values["archive-root"],
    groupIds: values["group-id"] || [],
  });
  const defaultName = `plan-${result.date_range.start}-${result.date_range.end}.json`;
  const output = values.out || path.join(result.archive_root, "plans", defaultName);
  result.output_path = writeJsonAtomic(output, result);
  return result;
}

function prepare(values) {
  const archiveRoot = path.resolve(values["archive-root"] || defaultArchiveRoot());
  const scanPayload = scan({ ...values, out: values["scan-out"] || path.join(archiveRoot, "subscriptions", "latest.json") });
  if (scanPayload.status !== "complete") {
    throw new ZsxqWebError("full_scan_incomplete", "The all-group scan was incomplete; no archive plan was created", 12, { scan_path: scanPayload.output_path, summary: scanPayload.summary });
  }
  return {
    status: "prepared",
    scan: { output_path: scanPayload.output_path, summary: scanPayload.summary },
    plan: plan({ ...values, out: values.out || path.join(archiveRoot, "plans", `plan-${required(values, "start")}-${required(values, "end")}.json`) }, scanPayload),
  };
}

async function main() {
  const { command, values } = parseArgs(process.argv.slice(2));
  if (!command || command === "help" || command === "--help") return emit(usage());
  if (command === "doctor") return emit(doctor(values));
  if (command === "scan") return emit(scan(values));
  if (command === "plan") return emit(plan(values));
  if (command === "prepare") return emit(prepare(values));
  if (command === "login") return emit(await login({
    groupId: values["group-id"]?.[0],
    waitSeconds: numberValue(values, "wait-seconds", 600),
    profileDir: values["profile-dir"],
    chromePath: values["chrome-path"],
  }));
  if (command === "probe") return emit(await probe({
    groupId: required(values, "group-id")[0],
    headed: Boolean(values.headed),
    profileDir: values["profile-dir"],
    chromePath: values["chrome-path"],
  }));
  if (command === "backfill") {
    if (!(values["group-id"] || []).length) throw new ZsxqWebError("missing_argument", "backfill requires at least one --group-id", 2);
    const prepared = prepare(values);
    if (prepared.plan.summary.pending_web === 0) {
      const status = prepared.plan.summary.delegated_ir_search > 0 ? "delegated_ir_search" : "blocked";
      return emit({
        status,
        scan: prepared.scan,
        plan: { output_path: prepared.plan.output_path, summary: prepared.plan.summary, jobs: prepared.plan.jobs },
      });
    }
    const archive = await executePlan(prepared.plan, values);
    return emit({
      status: archive.status,
      scan: prepared.scan,
      plan: { output_path: prepared.plan.output_path, summary: prepared.plan.summary },
      archive,
    });
  }
  if (command === "run") {
    const planPayload = readJson(required(values, "plan"));
    return emit(await executePlan(planPayload, values));
  }
  throw new ZsxqWebError("unknown_command", `Unknown command: ${command}`, 2);
}

main().catch((error) => {
  const known = error instanceof ZsxqWebError;
  const payload = {
    status: "error",
    error: {
      code: known ? error.code : "unexpected_error",
      message: known ? error.message : "Unexpected zsxq_web failure",
      details: { diagnostic: errorDiagnostic(error), ...(known ? error.details : {}) },
    },
  };
  process.stderr.write(`${JSON.stringify(payload, null, 2)}\n`);
  process.exitCode = known ? error.exitCode : 1;
});
