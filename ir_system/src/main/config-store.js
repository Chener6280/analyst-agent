const fs = require("node:fs");
const path = require("node:path");

const DEFAULT_CONFIG = Object.freeze({
  schemaVersion: 1,
  activeProvider: "ir_search",
  providers: {
    ir_search: {
      pythonCommand: "python3",
      irSearchPath: "",
      timeoutMs: 12000,
      archiveRoot: "",
    },
  },
});

function cloneDefaults() {
  return JSON.parse(JSON.stringify(DEFAULT_CONFIG));
}

class ConfigStore {
  constructor(userDataDir) {
    this.path = path.join(userDataDir, "ir-system-config.json");
  }

  read() {
    const config = cloneDefaults();
    try {
      const stored = JSON.parse(fs.readFileSync(this.path, "utf8"));
      if (stored && stored.schemaVersion === 1) {
        // Demo is a developer fixture, never a persisted production fallback.
        config.activeProvider = "ir_search";
        config.providers.ir_search = {
          ...config.providers.ir_search,
          ...(stored.providers?.ir_search || {}),
        };
      }
    } catch (error) {
      if (error.code !== "ENOENT") console.warn("Unable to read IR System config", error.message);
    }

    config.activeProvider = process.env.IR_SYSTEM_DEVELOPMENT_DEMO === "1" && process.env.IR_SYSTEM_PROVIDER === "demo" ? "demo" : "ir_search";
    config.providers.ir_search.pythonCommand = process.env.IR_SYSTEM_PYTHON || config.providers.ir_search.pythonCommand;
    config.providers.ir_search.irSearchPath = process.env.IR_SYSTEM_IR_SEARCH_PATH || config.providers.ir_search.irSearchPath;
    config.providers.ir_search.archiveRoot = process.env.IR_SYSTEM_ARCHIVE_ROOT || config.providers.ir_search.archiveRoot;
    return config;
  }

  write(config) {
    fs.mkdirSync(path.dirname(this.path), { recursive: true });
    const temporaryPath = `${this.path}.tmp`;
    fs.writeFileSync(temporaryPath, `${JSON.stringify(config, null, 2)}\n`, { mode: 0o600 });
    fs.renameSync(temporaryPath, this.path);
    return config;
  }

  setActiveProvider(providerId) {
    if (providerId !== "ir_search" && !(providerId === "demo" && process.env.IR_SYSTEM_DEVELOPMENT_DEMO === "1")) throw new Error("Unsupported provider");
    const config = this.read();
    config.activeProvider = providerId;
    return this.write(config);
  }

  setProviderConfig(input = {}) {
    const config = this.read();
    const pythonCommand = String(input.pythonCommand || "python3").trim();
    const irSearchPath = String(input.irSearchPath || "").trim();
    const archiveRoot = String(input.archiveRoot ?? config.providers.ir_search.archiveRoot ?? "").trim();
    if (!pythonCommand || pythonCommand.length > 512 || irSearchPath.length > 2048 || archiveRoot.length > 2048 || /[\r\n\0]/.test(archiveRoot)) {
      throw new Error("Invalid provider configuration");
    }
    config.providers.ir_search = {
      ...config.providers.ir_search,
      pythonCommand,
      irSearchPath,
      archiveRoot,
    };
    return this.write(config);
  }
}

module.exports = { ConfigStore, DEFAULT_CONFIG };
