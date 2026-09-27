const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");
const { ConfigStore } = require("../src/main/config-store");

test("provider configuration is stored outside the application checkout", () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "ir-system-config-"));
  const store = new ConfigStore(directory);
  store.setProviderConfig({ pythonCommand: "python3", irSearchPath: "/opt/ir_search" });
  store.setActiveProvider("ir_search");
  const config = store.read();
  assert.equal(config.activeProvider, "ir_search");
  assert.equal(config.providers.ir_search.irSearchPath, "/opt/ir_search");
  assert.ok(store.path.startsWith(directory));
});

test("production defaults and old Demo profiles always use ir_search", () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "ir-config-migrate-"));
  const store = new ConfigStore(directory);
  assert.equal(store.read().activeProvider, "ir_search");
  const old = store.read(); old.activeProvider = "demo"; store.write(old);
  assert.equal(store.read().activeProvider, "ir_search");
  assert.throws(() => store.setActiveProvider("demo"), /Unsupported/);
});
