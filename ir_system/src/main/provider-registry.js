const path = require("node:path");
const { DemoProvider } = require("./providers/demo-provider");
const { SubprocessProvider } = require("./providers/subprocess-provider");
const { NAVIGATION } = require("./navigation");

class ProviderRegistry {
  constructor(config, runtime) {
    this.runtime = runtime;
    this.reload(config);
  }

  reload(config) {
    this.config = config;
    const irSearchConfig = { ...(config.providers?.ir_search || {}) };
    if (this.runtime?.userData) irSearchConfig.cacheDir = path.join(this.runtime.userData, "derivatives-cache");
    this.providers = new Map([
      ["demo", new DemoProvider()],
      ["ir_search", new SubprocessProvider(irSearchConfig, this.runtime)],
    ]);
  }

  active() {
    return this.providers.get(this.config.activeProvider) || this.providers.get("ir_search");
  }

  async probe(providerId) {
    const provider = this.providers.get(providerId);
    if (!provider) throw new Error("Unknown provider");
    return provider.probe();
  }

  async bootstrap() {
    const active = this.active();
    const [dashboard, demoStatus, irSearchStatus] = await Promise.all([
      active.bootstrap(),
      this.providers.get("demo").probe(),
      this.providers.get("ir_search").probe(),
    ]);
    return {
      schemaVersion: 1,
      app: { name: "ir_system", displayName: "IR System", version: "0.1.0" },
      activeProvider: active.id,
      providers: [demoStatus, irSearchStatus],
      providerConfig: {
        pythonCommand: this.config.providers?.ir_search?.pythonCommand || "python3",
        irSearchPath: this.config.providers?.ir_search?.irSearchPath || "",
        archiveRoot: this.config.providers?.ir_search?.archiveRoot || "",
      },
      navigation: NAVIGATION,
      dashboard,
    };
  }

  async moduleData(moduleId) {
    if (!NAVIGATION.some((item) => item.id === moduleId)) throw new Error("Unknown module");
    return this.active().moduleData(moduleId);
  }

  async archiveRequest(action, params = {}) {
    if (!["status", "index", "search", "read", "parse", "asset", "audio_list"].includes(action)) throw new Error("Unknown archive action");
    if (!this.config.providers?.ir_search?.archiveRoot) throw new Error("请先在 Data Center 设置本地归档目录");
    return this.providers.get("ir_search").request(`archive.${action}`, params);
  }

  async derivatives(action, params = {}) {
    if (!["basis", "options_catalog", "options_surface", "options_vix"].includes(action)) throw new Error("Unknown derivatives action");
    return this.providers.get("ir_search").request(`derivatives.${action}`, params);
  }
}

module.exports = { ProviderRegistry };
