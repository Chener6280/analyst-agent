const fs = require("node:fs");
const path = require("node:path");
const { randomUUID } = require("node:crypto");
const { applySeed } = require('./subscriptions');

function atomicJson(file, value) {
  fs.mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 });
  const temporary = `${file}.${randomUUID()}.tmp`;
  const fd = fs.openSync(temporary, "wx", 0o600);
  try { fs.writeFileSync(fd, JSON.stringify(value, null, 2) + "\n"); fs.fsyncSync(fd); }
  finally { fs.closeSync(fd); }
  try { fs.renameSync(temporary, file); }
  finally { if (fs.existsSync(temporary)) fs.unlinkSync(temporary); }
}

const DEFAULTS = {
  schemaVersion: 1, revision: 0,
  settings: { agentMode: "fixed", piCommand: "pi", policies: [],
    budgets: { maxOperations: 60, maxRecords: 100, maxFiles: 20, maxBytesMiB: 100, maxFileMiB: 50, maxParses: 20, maxSeconds: 600 }, overlapDays: 3 },
  jobs: [], grants: {}, watermarks: {}, catalog: null,
  consoleSettings: { runtime: "pi", commands: { pi: "pi", kimi: "kimi", custom: "" } },
};

class SyncStore {
  constructor(directory) {
    this.directory = path.join(directory, "sync-v1");
    this.file = path.join(this.directory, "state.json");
    try { this.state = JSON.parse(fs.readFileSync(this.file, "utf8")); }
    catch (e) { if (e.code !== "ENOENT") throw new Error("sync_state_unreadable"); this.state = structuredClone(DEFAULTS); }
    if (this.state.schemaVersion !== 1) throw new Error("sync_schema_mismatch");
    this.state.consoleSettings ||= { runtime: "pi", commands: { pi: this.state.settings.piCommand || "pi", kimi: "kimi", custom: "" } };
    this.state.subscriptionReview ||= {};
    applySeed(this.state, directory);
    for (const job of this.state.jobs) {
      if (["running", "queued", "agent_starting"].includes(job.status)) {
        job.status = "interrupted"; job.code = "application_interrupted";
      }
    }
    this.save();
  }
  save() { atomicJson(this.file, this.state); }
  jobDirectory(id) {
    if (!/^[a-f0-9-]{36}$/.test(id)) throw new Error("invalid_job_id");
    return path.join(this.directory, "jobs", id);
  }
}
module.exports = { SyncStore, atomicJson };
