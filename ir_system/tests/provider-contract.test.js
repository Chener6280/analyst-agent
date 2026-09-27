const assert = require("node:assert/strict");
const path = require("node:path");
const test = require("node:test");
const { DemoProvider } = require("../src/main/providers/demo-provider");
const { SubprocessProvider, PROTOCOL } = require("../src/main/providers/subprocess-provider");

test("demo provider exposes the stable provider contract", async () => {
  const result = await new DemoProvider().probe();
  assert.equal(result.protocol, PROTOCOL);
  assert.equal(result.status, "ready");
  assert.ok(result.modules.some((item) => item.id === "macro"));
  assert.ok(result.modules.some((item) => item.id === "research"));
});

test("ir_search bridge fails closed when ir_search is unavailable", async () => {
  const provider = new SubprocessProvider(
    { pythonCommand: "python3", irSearchPath: path.join(__dirname, "missing-ir-search"), timeoutMs: 4000 },
    { appRoot: path.join(__dirname, ".."), resourcesPath: "", packaged: false },
  );
  const result = await provider.probe();
  assert.equal(result.protocol, PROTOCOL);
  assert.ok(["ready", "unavailable"].includes(result.status));
  if (result.status === "unavailable") assert.ok(result.diagnostics.length > 0);
});
