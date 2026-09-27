const path = require("node:path");
const { spawn } = require("node:child_process");

const PROTOCOL = "ir-system-provider/v1";

class SubprocessProvider {
  constructor(config, runtime) {
    this.id = "ir_search";
    this.label = "ir_search Adapter";
    this.config = config || {};
    this.runtime = runtime;
  }

  adapterPath() {
    if (this.runtime.packaged) {
      return path.join(this.runtime.resourcesPath, "adapters", "ir_search_bridge.py");
    }
    return path.join(this.runtime.appRoot, "adapters", "ir_search_bridge.py");
  }

  async request(method, params = {}) {
    const command = this.config.pythonCommand || "python3";
    const args = [this.adapterPath()];
    // Bundled adapter code is sealed by the macOS application signature.
    // Runtime caches belong outside the bundle, never under Resources.
    const env = { ...process.env, PYTHONDONTWRITEBYTECODE: '1' };
    if (this.config.irSearchPath) env.IR_SEARCH_PATH = this.config.irSearchPath;
    if (this.config.archiveRoot) env.IR_SEARCH_LOCAL_ARCHIVE_ROOT = this.config.archiveRoot;
    else delete env.IR_SEARCH_LOCAL_ARCHIVE_ROOT;
    const timeoutMs = method.startsWith("archive.") ? 120000 : Math.max(1000, Math.min(Number(this.config.timeoutMs) || 12000, 120000));

    return new Promise((resolve, reject) => {
      const child = spawn(command, args, { env, stdio: ["pipe", "pipe", "pipe"], detached: process.platform !== "win32" });
      const stop = () => {
        try {
          if (process.platform === "win32") spawn("taskkill", ["/pid", String(child.pid), "/t", "/f"], { stdio: "ignore" });
          else process.kill(-child.pid, "SIGTERM");
        } catch {}
      };
      let stdout = "";
      let stderr = "";
      let settled = false;
      const timer = setTimeout(() => {
        stop();
        finish(new Error(`Provider timed out after ${timeoutMs}ms`));
      }, timeoutMs);

      function finish(error, value) {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        if (error) reject(error);
        else resolve(value);
      }

      child.stdout.on("data", (chunk) => {
        stdout += chunk.toString("utf8");
        if (stdout.length > 8 * 1024 * 1024) {
          stop();
          finish(new Error("Provider response exceeded 8 MiB"));
        }
      });
      child.stderr.on("data", (chunk) => {
        if (stderr.length < 64 * 1024) stderr += chunk.toString("utf8");
      });
      child.on("error", (error) => finish(error));
      child.stdin.on("error", (error) => finish(error));
      child.on("close", (code) => {
        if (settled) return;
        if (code !== 0) return finish(new Error(stderr.trim() || `Provider exited with code ${code}`));
        try {
          const response = JSON.parse(stdout.trim());
          if (response.protocol !== PROTOCOL) throw new Error("Provider protocol mismatch");
          if (!response.ok) throw new Error(response.error?.message || "Provider request failed");
          finish(null, response.result);
        } catch (error) {
          finish(new Error(`Invalid provider response: ${error.message}`));
        }
      });

      child.stdin.end(`${JSON.stringify({ protocol: PROTOCOL, method, params })}\n`);
    });
  }

  async probe() {
    try {
      return await this.request("system.capabilities");
    } catch (error) {
      return {
        protocol: PROTOCOL,
        provider: this.id,
        label: this.label,
        status: "unavailable",
        mode: "external",
        fetchedAt: new Date().toISOString(),
        modules: [],
        diagnostics: [error.message],
      };
    }
  }

  async bootstrap() {
    const capabilities = await this.probe();
    return {
      schemaVersion: 1,
      generatedAt: new Date().toISOString(),
      dataMode: capabilities.status === "ready" ? "connected" : "unavailable",
      asOf: capabilities.fetchedAt,
      headline: capabilities.status === "ready"
        ? "ir_search connected — widgets activate as compatible datasets are mapped"
        : "ir_search is not available on this computer",
      markets: [],
      pulse: [],
      research: [],
      capabilities,
    };
  }

  async moduleData(moduleId) {
    const capabilities = await this.probe();
    const module = capabilities.modules?.find((item) => item.id === moduleId);
    return {
      schemaVersion: 1,
      moduleId,
      title: module?.label || moduleId.toUpperCase(),
      status: module?.status || "unavailable",
      dataMode: capabilities.status === "ready" ? "connected" : "unavailable",
      asOf: capabilities.fetchedAt,
      summary: module?.summary || "No compatible dataset is currently mapped to this module.",
      sections: [],
      diagnostics: capabilities.diagnostics || [],
      providerDetails: module?.details || {},
    };
  }
}

module.exports = { SubprocessProvider, PROTOCOL };
