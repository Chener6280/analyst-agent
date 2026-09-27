const path = require("node:path");
const { spawn } = require("node:child_process");

function previewExcel(file, provider, runtime) {
  return new Promise((resolve, reject) => {
    const script = path.join(runtime.packaged ? runtime.resourcesPath : runtime.appRoot, "adapters", "sync_excel.py");
    const child = spawn(provider.pythonCommand || "python3", [script, file], { stdio: ["ignore", "pipe", "ignore"] });
    let output = "";
    const timer = setTimeout(() => { child.kill(); reject(new Error("xlsx_preview_timeout")); }, 10000);
    child.stdout.on("data", chunk => { output += chunk; if (output.length > 2 * 1024 * 1024) { child.kill(); reject(new Error("xlsx_preview_too_large")); } });
    child.on("error", () => { clearTimeout(timer); reject(new Error("xlsx_reader_unavailable")); });
    child.on("close", code => {
      clearTimeout(timer);
      try { const result = JSON.parse(output); if (code || result.error) throw new Error(result.error || "xlsx_preview_failed"); resolve(result); }
      catch (e) { reject(new Error(/^[a-z_]{1,80}$/.test(e.message) ? e.message : "xlsx_preview_failed")); }
    });
  });
}
module.exports = { previewExcel };
