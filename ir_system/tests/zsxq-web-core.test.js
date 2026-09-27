const assert = require("node:assert/strict");
const test = require("node:test");

const { buildPlan, classifyMembership, normalizeGroup, summarizeGroups } = require("../adapters/zsxq_web/core");

const NOW = new Date("2026-09-25T12:00:00Z");

function group(overrides = {}) {
  return {
    group_id: "51122185284184",
    name: "韭菜空间站",
    type: "pay",
    policies: {
      allow_download: true,
      allow_copy: false,
      allow_screen_capture_recording: false,
      enable_ai_openapi: false,
    },
    statistics: { files: { count: 4208 }, topics: { topics_count: 9000 } },
    user_specific: { membership: { end_time: "2027-03-12T22:31:58.678+0800" } },
    ...overrides,
  };
}

test("membership is based on the real expiry timestamp, not list presence", () => {
  assert.equal(classifyMembership(group(), NOW).state, "active_paid");
  assert.equal(classifyMembership(group({ user_specific: { membership: { end_time: "2026-04-02T18:01:40.070+0800" } } }), NOW).state, "expired");
  assert.equal(classifyMembership(group({ type: "free", user_specific: {} }), NOW).state, "active_free");
});

test("normalization removes signed URLs and keeps only fields needed by workers", () => {
  const normalized = normalizeGroup({ ...group(), background_url: "https://example.invalid/?token=secret" }, NOW);
  assert.equal(normalized.name, "韭菜空间站");
  assert.equal(normalized.permissions.allow_download, true);
  assert.equal(normalized.statistics.files_count, 4208);
  assert.equal(JSON.stringify(normalized).includes("secret"), false);
});

test("plan routes deterministic jobs without asking the worker to infer permissions", () => {
  const web = normalizeGroup(group(), NOW, { state: "not_enabled" });
  const skill = normalizeGroup(group({ group_id: "1", name: "Skill enabled", policies: { ...group().policies, enable_ai_openapi: true } }), NOW, { state: "accessible" });
  const blocked = normalizeGroup(group({ group_id: "2", name: "No downloads", policies: { ...group().policies, allow_download: false } }), NOW, { state: "not_enabled" });
  const scan = { scanned_at: NOW.toISOString(), groups: [web, skill, blocked], summary: summarizeGroups([web, skill, blocked]) };
  const plan = buildPlan(scan, { start: "2026-09-18", end: "2026-09-24", archiveRoot: "/tmp/archive" });
  assert.deepEqual(plan.summary, { total: 3, pending_web: 1, delegated_ir_search: 1, blocked: 1 });
  assert.equal(plan.jobs.find((job) => job.group_id === web.group_id).route, "zsxq_web");
  assert.equal(plan.jobs.find((job) => job.group_id === web.group_id).include.topics, "metadata_only");
  assert.equal(plan.jobs.find((job) => job.group_id === "1").route, "ir_search");
  assert.equal(plan.jobs.find((job) => job.group_id === "2").reason, "download_disabled_by_group");
});
