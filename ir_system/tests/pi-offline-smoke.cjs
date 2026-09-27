// No model prompt: exercise the real installed Pi extension loader in RPC mode.
const path = require("node:path");
const { spawn } = require("node:child_process");
const assert = require("node:assert/strict");
const { TOOLS } = require("../src/main/sync/pi-agent");
const child = spawn(process.env.PI_COMMAND || "pi", ["--mode", "rpc", "--no-session", "--no-extensions", "--no-skills",
  "--no-context-files", "--no-prompt-templates", "--no-themes", "--no-approve", "--offline", "--tools", TOOLS.join(","),
  "--extension", path.resolve(__dirname, "../adapters/pi-sync.ts")],
  { cwd: require("node:os").tmpdir(), env: { ...process.env, PI_OFFLINE: "1", PI_TELEMETRY: "0", IR_SYSTEM_SYNC_SELFTEST: "1" }, stdio: ["pipe", "pipe", "pipe"] });
let buffer = "", passed = false, errors = "";
const timer = setTimeout(() => { child.kill(); process.exitCode = 1; console.error("Pi offline extension probe timed out"); }, 15000);
child.stdout.on("data", chunk => {
  buffer += chunk;
  let n;
  while ((n = buffer.indexOf("\n")) >= 0) {
    const line = buffer.slice(0, n); buffer = buffer.slice(n + 1);
    try {
      const event = JSON.parse(line);
      if (event.type === "extension_ui_request" && event.method === "notify") {
        const data = JSON.parse(event.message);
        if (data.irSyncSelfTest) {
          assert.deepEqual([...data.irSyncSelfTest].sort(), [...TOOLS].sort());
          passed = true; console.log("Pi offline PASS: exactly four sync tools; no model request sent."); child.kill();
        }
      }
    } catch { /* No raw session/model data is printed. */ }
  }
});
child.stderr.on("data", chunk => { errors += chunk; });
child.on("error", () => { clearTimeout(timer); console.error("Pi process unavailable"); process.exitCode = 1; });
child.on("close", () => { clearTimeout(timer); if (!passed) { console.error("Pi extension loader failed:", errors.replace(/https?:\/\/\S+/g, "[url]").slice(0, 1500)); process.exitCode = 1; } });
