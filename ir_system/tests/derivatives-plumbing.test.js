const assert = require("node:assert/strict");
const path = require("node:path");
const test = require("node:test");
const { ProviderRegistry } = require("../src/main/provider-registry");
const { SubprocessProvider } = require("../src/main/providers/subprocess-provider");

function registry(runtime = { appRoot: path.join(__dirname, ".."), resourcesPath: "", packaged: false, userData: "/tmp/ir-test-userdata" }) {
  return new ProviderRegistry({ activeProvider: "ir_search", providers: { ir_search: { pythonCommand: "python3" } } }, runtime);
}

test("derivatives allowlist rejects unknown actions", async () => {
  const reg = registry();
  await assert.rejects(() => reg.derivatives("eval", {}), /Unknown derivatives action/);
  await assert.rejects(() => reg.derivatives("basis;rm", {}), /Unknown derivatives action/);
});

test("derivatives routes to the ir_search provider with the versioned method", async () => {
  const reg = registry();
  const seen = [];
  reg.providers.set("ir_search", { request: (method, params) => { seen.push([method, params]); return Promise.resolve({ ok: true }); } });
  await reg.derivatives("options_surface", { exchange: "DCE", product: "M.DCE", rate: 0.015 });
  assert.deepEqual(seen, [["derivatives.options_surface", { exchange: "DCE", product: "M.DCE", rate: 0.015 }]]);
});

test("derivatives cache directory comes from userData, never from persisted config", () => {
  const reg = new ProviderRegistry(
    { activeProvider: "ir_search", providers: { ir_search: { pythonCommand: "python3", cacheDir: "/etc/poison" } } },
    { appRoot: path.join(__dirname, ".."), resourcesPath: "", packaged: false, userData: "/tmp/ir-test-userdata" },
  );
  const provider = reg.providers.get("ir_search");
  assert.equal(provider.config.cacheDir, path.join("/tmp/ir-test-userdata", "derivatives-cache"));
});

test("derivatives methods get the long subprocess timeout", async () => {
  const provider = new SubprocessProvider(
    { pythonCommand: process.execPath, timeoutMs: 1000 },
    { appRoot: path.join(__dirname, ".."), resourcesPath: "", packaged: false },
  );
  provider.adapterPath = () => path.join(__dirname, "fixtures", "slow-adapter.js");
  const result = await provider.request("derivatives.basis", {});
  assert.equal(result.slow, true);
  await assert.rejects(() => provider.request("system.capabilities"), /timed out/);
});
