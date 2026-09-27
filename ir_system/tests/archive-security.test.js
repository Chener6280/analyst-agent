const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");
const { validatedAssetPath } = require("../src/main/archive-security");
const { ConfigStore } = require("../src/main/config-store");
const { ProviderRegistry } = require("../src/main/provider-registry");

test("original reveal accepts only hash objects, rejects arbitrary files and escaping symlinks", (t) => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "ir-archive-path-"));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const sha = "a".repeat(64);
  const object = path.join(root, "objects", "aa", sha);
  fs.mkdirSync(path.dirname(object), { recursive: true });
  fs.writeFileSync(object, "test");
  assert.equal(validatedAssetPath(root, object), fs.realpathSync(object));
  const other = path.join(root, "private.txt");
  fs.writeFileSync(other, "private");
  assert.throws(() => validatedAssetPath(root, other), /允许范围/);
  const link = path.join(root, "objects", "aa", "b".repeat(64));
  fs.symlinkSync(other, link);
  assert.throws(() => validatedAssetPath(root, link), /允许范围/);
});

test("archive root is portable configuration and survives partial updates", (t) => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "ir-archive-config-"));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const store = new ConfigStore(root);
  store.setProviderConfig({ archiveRoot: "/test/archive" });
  store.setProviderConfig({ pythonCommand: "python3" });
  assert.equal(store.read().providers.ir_search.archiveRoot, "/test/archive");
  assert.throws(() => store.setProviderConfig({ archiveRoot: "bad\npath" }));
});

test("archive actions never use demo data or accept arbitrary method names", async () => {
  const registry = new ProviderRegistry({ activeProvider: "demo", providers: { ir_search: { archiveRoot: "/test/archive" } } }, {});
  registry.providers.get("ir_search").request = async (method, params) => ({ method, params });
  assert.deepEqual(await registry.archiveRequest("search", { query: "hello" }), { method: "archive.search", params: { query: "hello" } });
  await assert.rejects(registry.archiveRequest("execute"), /Unknown archive action/);
  registry.config.providers.ir_search.archiveRoot = "";
  await assert.rejects(registry.archiveRequest("status"), /归档目录/);
});
