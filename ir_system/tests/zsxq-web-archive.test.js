const assert = require("node:assert/strict");
const test = require("node:test");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const { parseBrowserFeed, parseTopicDate, runJob, safeName } = require("../adapters/zsxq_web/archive");

const NOW = new Date("2026-09-25T12:00:00Z");

test("topic dates normalize full, short, and relative Chinese dates", () => {
  assert.equal(parseTopicDate("作者 2026/9/23 14:44 标题", NOW), "2026-09-23");
  assert.equal(parseTopicDate("作者 9月24日 02:18", NOW), "2026-09-24");
  assert.equal(parseTopicDate("作者 昨天 09:15", NOW), "2026-09-24");
  assert.equal(parseTopicDate("作者 前天 17:18", NOW), "2026-09-23");
});

test("download filenames cannot escape the archive", () => {
  assert.equal(safeName("../../会议纪要.pdf"), "会议纪要.pdf");
  assert.equal(safeName("a:b?.pdf"), "a_b_.pdf");
});

test("browser feed preserves 17-digit IDs and retains only metadata", () => {
  const raw = '{"succeeded":true,"resp_data":{"topics":[{"topic_id":45548541885442818,"group":{"group_id":51122185284184},"create_time":"2026-09-24T17:18:16.893+0800","talk":{"text":"Title\\nprivate body","files":[{"download_url":"https://files.invalid/?token=secret"}]}}]}}';
  const [topic] = parseBrowserFeed(raw, "51122185284184");
  assert.equal(topic.topic_id, "45548541885442818");
  assert.equal(topic.published_on, "2026-09-24");
  assert.equal(topic.context_text, "Title");
  assert.equal(JSON.stringify(topic).includes("private body"), false);
  assert.equal(JSON.stringify(topic).includes("secret"), false);
});

function fakeContext() {
  const pages = [];
  return {
    pages: () => pages.filter((page) => !page.isClosed()),
    async newPage() {
      let closed = false;
      const page = { isClosed: () => closed, close: async () => { closed = true; } };
      pages.push(page);
      return page;
    },
  };
}

const JOB = { job_id: "test-job", group_id: "123", start: "2025-09-25", end: "2026-09-24", include: { topics: "metadata_only", attachments: true } };
const TOPICS = [{ topic_id: "111", published_on: "2026-09-20" }, { topic_id: "222", published_on: "2026-09-21" }];
const DISCOVERY = { topics: TOPICS, reached_date_floor: true, oldest_visible_date: "2025-09-24", link_resolution: { attempted: 2, succeeded: 2 } };
const record = (topic) => ({ ...topic, title: "Repeated title", content_text: "", detected_attachments: [] });

test("browser interruption saves an honest manifest and resumes past completed topics", async (t) => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "zsxq-lifecycle-test-"));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const seen = [];
  const runtime = {
    discoverTopics: async () => DISCOVERY,
    topicMetadata: async (page, topic) => {
      seen.push(topic.topic_id);
      if (topic.topic_id === "222") {
        await page.close();
        throw new Error("page.goto: Target page, context or browser has been closed");
      }
      return record(topic);
    },
    downloadVisibleFiles: async () => [],
  };
  await assert.rejects(runJob(fakeContext(), JOB, root, { topicIntervalMs: 0 }, runtime), (error) => {
    assert.equal(error.code, "browser_interrupted");
    assert.ok(fs.existsSync(error.details.manifest_path));
    return true;
  });
  const checkpointPath = path.join(root, "jobs", JOB.job_id, "checkpoint.json");
  const manifestPath = path.join(root, "jobs", JOB.job_id, "manifest.json");
  const checkpoint = JSON.parse(fs.readFileSync(checkpointPath));
  const manifest = JSON.parse(fs.readFileSync(manifestPath));
  assert.deepEqual(checkpoint.processed_topic_ids, ["111"]);
  assert.ok(checkpoint.failures["222"].diagnostic.message.includes("closed"));
  assert.equal(manifest.status, "interrupted");
  assert.equal(manifest.all_discovered_processed, false);
  assert.equal(manifest.coverage_complete, false);
  const resumed = [];
  runtime.topicMetadata = async (_page, topic) => { resumed.push(topic.topic_id); return record(topic); };
  const completed = await runJob(fakeContext(), JOB, root, { topicIntervalMs: 0 }, runtime);
  assert.deepEqual(resumed, ["222"]);
  assert.equal(completed.records_added_this_run, 1);
  assert.equal(completed.topics_processed_total, 2);
  assert.deepEqual(completed.failures, {});
});

test("discovery failure still writes a manifest and preserves an existing checkpoint", async (t) => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "zsxq-discovery-test-"));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const checkpointPath = path.join(root, "jobs", JOB.job_id, "checkpoint.json");
  fs.mkdirSync(path.dirname(checkpointPath), { recursive: true });
  fs.writeFileSync(checkpointPath, JSON.stringify({ schema_version: 1, job_id: JOB.job_id, processed_topic_ids: ["111"], failures: {} }));
  const runtime = { discoverTopics: async () => { throw new TypeError("fixture discovery failed"); } };
  await assert.rejects(runJob(fakeContext(), JOB, root, {}, runtime), (error) => {
    assert.equal(error.details.stage, "discover_topics");
    const manifest = JSON.parse(fs.readFileSync(error.details.manifest_path));
    assert.equal(manifest.status, "interrupted");
    assert.equal(manifest.all_discovered_processed, false);
    assert.equal(manifest.error.diagnostic.name, "TypeError");
    return true;
  });
  assert.deepEqual(JSON.parse(fs.readFileSync(checkpointPath)).processed_topic_ids, ["111"]);
});

test("attachment progress survives a later file failure and retry reuses verified objects", async (t) => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "zsxq-attachment-test-"));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const topic = TOPICS[0];
  const recordPath = path.join(root, "groups", JOB.group_id, "topics", topic.topic_id, "record.json");
  let saved = 0;
  function downloadContext(failSecond) {
    const pages = [];
    return {
      pages: () => pages.filter((page) => !page.isClosed()),
      async newPage() {
        let closed = false;
        const control = { count: async () => 1, click: async () => {}, waitFor: async () => {} };
        control.first = control.last = control.filter = () => control;
        const page = {
          isClosed: () => closed,
          close: async () => { closed = true; },
          locator: () => control,
          getByText: () => control,
          goto: async () => {
            const partial = JSON.parse(fs.readFileSync(recordPath));
            assert.equal(partial.attachments[0].status, "ok");
            if (failSecond) throw new Error("fixture navigation failed on second attachment");
          },
          waitForEvent: async () => ({
            saveAs: async (target) => { saved += 1; fs.writeFileSync(target, `%PDF-test-${saved}`); },
            suggestedFilename: () => "fixture.pdf",
          }),
        };
        pages.push(page);
        return page;
      },
    };
  }
  const runtime = {
    discoverTopics: async () => ({ ...DISCOVERY, topics: [topic] }),
    topicMetadata: async () => ({ ...record(topic), source_url: "https://wx.zsxq.com/group/123/topic/111", detected_attachments: ["first.pdf", "second.pdf"] }),
  };
  const first = await runJob(downloadContext(true), JOB, root, { topicIntervalMs: 0 }, runtime);
  assert.equal(first.attachments_this_run.downloaded, 1);
  assert.equal(first.attachments_this_run.failed, 1);
  assert.equal(first.all_discovered_processed, false);
  const partial = JSON.parse(fs.readFileSync(recordPath));
  assert.equal(partial.attachments[1].stage, "open_attachment");
  const resumed = await runJob(downloadContext(false), JOB, root, { topicIntervalMs: 0 }, runtime);
  assert.equal(saved, 2);
  assert.equal(resumed.attachments_this_run.reused, 1);
  assert.equal(resumed.attachments_this_run.downloaded, 1);
  assert.equal(resumed.attachments_this_run.failed, 0);
  assert.equal(resumed.all_discovered_processed, true);
  assert.deepEqual(resumed.failures, {});
});
