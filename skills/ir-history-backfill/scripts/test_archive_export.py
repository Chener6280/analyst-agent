"""Offline invariants for archive_export: fake ir_search in sys.modules; real temp disk archives."""
import contextlib
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import archive_export as x
import download_history as d


class FakeSDK:
    """Programmable stand-in for the four public collection-export entry points."""

    class RequestContext:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    def __init__(self):
        self.timeline_pages = {}
        self.comment_pages = {}
        self.assets = {}
        self.timeline_calls = []
        self.comment_calls = []
        self.asset_calls = []

    def export_collection_timeline(self, provider, collection_id, *, published_start,
                                   published_end, cursor=None, include_text=False,
                                   include_notes=True, max_items=500, context=None, registry=None):
        self.timeline_calls.append((collection_id, cursor))
        default = {"items": [], "continuation_cursor": None,
                   "coverage": {"state": "complete", "scanned": 0, "returned": 0, "notes": 0},
                   "diagnostics": [], "status": "ok"}
        return copy.deepcopy(self.timeline_pages.get((collection_id, cursor), default))

    def list_topic_comments(self, provider, ref, *, cursor=None, per_page=30, max_pages=10,
                            context=None, registry=None):
        self.comment_calls.append((ref, cursor))
        default = {"comments": [], "continuation_cursor": None,
                   "coverage": {"state": "complete", "scanned": 0, "returned": 0},
                   "diagnostics": [{"code": "nested_replies_not_provided"}], "status": "ok"}
        return copy.deepcopy(self.comment_pages.get((ref, cursor), default))

    def retrieve_asset(self, asset_ref, *, max_bytes=52428800, context=None, registry=None):
        self.asset_calls.append(asset_ref)
        result = copy.deepcopy(self.assets.get(
            asset_ref, {"status": "failed", "reason": "asset_not_found", "content": None}))
        return result


def use_sdk(fake):
    return patch.dict(sys.modules, {"ir_search": fake})


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "archive"
        self.sdk = FakeSDK()

    def args(self, *extra):
        return x.parser().parse_args([
            "--archive-root", str(self.root), "--provider", "zsxq",
            "--collection", "123", "--start", "2026-09-20", "--end", "2026-09-20",
            "--interval", "0", *extra])

    def run_export(self, *extra, sdk=None):
        if extra and hasattr(extra[0], "archive_root"):
            args = extra[0]
        else:
            args = self.args(*extra)
        planned = x.make_jobs(args)
        with use_sdk(sdk or self.sdk):
            return x.execute(args, planned)

    def item(self, ref="zsxq://topic/123/456", day="2026-09-20", **extra):
        base = {"ref": ref, "title": "宏观日报", "type": "talk", "collection_id": "123",
                "published_at": f"{day}T18:00:00+08:00", "updated_at": None, "author": "作者",
                "authors": ["作者"], "labels": ["宏观"], "like_count": 3, "comments_count": 2,
                "attachments": [], "images": [], "text": "正文内容", "text_scope": "source_excerpt",
                "summary": None, "has_summary": None, "original_document_available": True,
                "category": None, "original_url": None, "warnings": [], "created_at": None,
                "modified_at": None}
        base.update(extra)
        return base

    def page(self, items=None, cursor=None, state="complete", diagnostics=None):
        items = items or []
        return {"items": items, "continuation_cursor": cursor,
                "coverage": {"state": state, "scanned": len(items), "returned": len(items), "notes": 0},
                "diagnostics": diagnostics or [], "status": "ok" if state == "complete" else "partial"}

    def records(self, day="2026-09-20", provider="zsxq"):
        path = self.root / "daily" / day / provider / "records.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()]

    def record_for(self, ref):
        return next(r for r in self.records("2026-09-20") if r["source_item_id"] == ref)

    def pdf_asset(self, ref, content=b"%PDF-1.4 fake report bytes", reason=None, status="ok"):
        entry = {"status": status, "ref": ref, "filename": "report.pdf",
                 "media_type": "application/pdf", "size_bytes": len(content),
                 "content_sha256": x.hashlib.sha256(content).hexdigest(),
                 "warnings": [], "content": content}
        if reason:
            entry["reason"] = reason
            entry["content"] = None
        self.sdk.assets[ref] = entry

    def attachment(self, ref="zsxq://file/123/456/789", name="report.pdf", size=45):
        return {"source_ref": ref, "name": name, "media_type": "pdf",
                "size_bytes": size, "status": "metadata_only"}

    def test_preview_has_no_io_or_sdk_import(self):
        with patch.object(x, "ExportSDKRunner", side_effect=AssertionError("SDK imported")), \
                contextlib.redirect_stdout(io.StringIO()):
            code = x.main(["--archive-root", str(self.root), "--provider", "zsxq",
                           "--collection", "123", "--start", "2026-09-20", "--end", "2026-09-20"])
        self.assertEqual(code, 0)
        self.assertFalse(self.root.exists())

    def test_enumeration_writes_export_records_with_day_attribution(self):
        self.sdk.timeline_pages[("123", None)] = self.page([self.item(), self.item(
            ref="zsxq://topic/123/457", day="2026-09-21")])
        summary = self.run_export(self.args("--end", "2026-09-21"))
        self.assertEqual(summary["records_total"], 2)
        self.assertEqual(summary["sdk_calls"], 1)
        self.assertTrue(summary["all_jobs_attempted"])
        self.assertTrue(summary["coverage_complete"] is False)  # run-level stays False
        first = self.record_for("zsxq://topic/123/456")
        self.assertEqual(first["local_date"], "2026-09-20")
        self.assertEqual(first["record_type"], "talk")
        self.assertEqual(first["labels"], ["宏观"])
        self.assertEqual(first["like_count"], 3)
        self.assertEqual(first["comments_count"], 2)
        self.assertIs(first["original_document_available"], True)
        self.assertEqual(first["content_text"], "正文内容")
        self.assertEqual(first["text_scope"], "source_excerpt")
        self.assertFalse(first["comments_fetched"])
        second = next(r for r in self.records("2026-09-21")
                      if r["source_item_id"] == "zsxq://topic/123/457")
        self.assertEqual(second["local_date"], "2026-09-21")
        job = json.loads((self.root / "checkpoints/zsxq.json").read_text())["jobs"]
        self.assertTrue(next(iter(job.values()))["coverage_complete"])
        manifest = json.loads((self.root / "daily/2026-09-20/zsxq/manifest.json").read_text())
        self.assertTrue(manifest["coverage_complete"])
        self.assertEqual(manifest["record_versions"], 1)
        manifest_21 = json.loads((self.root / "daily/2026-09-21/zsxq/manifest.json").read_text())
        self.assertTrue(manifest_21["coverage_complete"])

    def test_rate_limit_stops_provider_then_replays_cached_pages_on_resume(self):
        first_item = self.item()
        second_item = self.item(ref="zsxq://topic/123/457")
        self.sdk.timeline_pages[("123", None)] = self.page([first_item], cursor="cursor-one",
                                                           state="budget_exhausted")
        self.sdk.timeline_pages[("123", "cursor-one")] = self.page(
            [second_item], cursor="cursor-two", state="upstream_stopped",
            diagnostics=[{"code": "rate_limit"}])
        first = self.run_export()
        self.assertEqual(first["sdk_calls"], 2)
        self.assertEqual(first["jobs_remaining"], 1)
        self.assertIn("rate_limit_stopped", {row["code"] for row in first["diagnostics"]})
        state = next(iter(json.loads((self.root / "checkpoints/zsxq.json").read_text())["jobs"].values()))
        self.assertEqual(state["state"], "pending")
        self.assertEqual(state["cursor"], "cursor-two")
        self.assertEqual(state["stop_reason"], "rate_limit_stopped")
        # Second run: the cached first page replays without an SDK call; the walk
        # resumes from the cursor saved off the rate-limited page, so nothing that
        # page already returned is re-requested.
        self.sdk.timeline_pages[("123", "cursor-two")] = self.page([])
        second = self.run_export()
        self.assertEqual(second["sdk_calls"], 1)
        self.assertEqual(self.sdk.timeline_calls, [("123", None), ("123", "cursor-one"),
                                                   ("123", "cursor-two")])
        self.assertTrue(second["all_jobs_attempted"])
        self.assertEqual(second["records_total"], 2)
        self.assertEqual(len(list((self.root / "raw").rglob("*.jsonl"))), 3)

    def test_budget_exhausted_saves_cursor_and_resumes_without_refetch(self):
        self.sdk.timeline_pages[("123", None)] = self.page([self.item()], cursor="cursor-one",
                                                           state="budget_exhausted")
        self.sdk.timeline_pages[("123", "cursor-one")] = self.page(
            [self.item(ref="zsxq://topic/123/457")])
        first = self.run_export("--max-calls", "1")
        self.assertEqual(first["sdk_calls"], 1)
        self.assertEqual(first["jobs_remaining"], 1)
        second = self.run_export("--max-calls", "1")
        self.assertEqual(second["sdk_calls"], 1)
        self.assertTrue(second["all_jobs_attempted"])
        self.assertEqual(self.sdk.timeline_calls, [("123", None), ("123", "cursor-one")])
        self.assertEqual(second["records_total"], 2)
        self.assertEqual(len(list((self.root / "raw").rglob("*.jsonl"))), 2)

    def test_ima_undated_unknown_day_snapshot_gaps_and_never_full_coverage(self):
        args = x.parser().parse_args([
            "--archive-root", str(self.root), "--provider", "ima", "--collection", "kb1",
            "--start", "2026-09-20", "--end", "2026-09-20", "--interval", "0"])
        ima_item = {"ref": "ima://media/kb1/abc", "title": "策略研究", "type": "pdf",
                    "collection_id": "kb1", "published_at": None, "updated_at": None,
                    "author": None, "authors": [], "labels": [], "like_count": None,
                    "comments_count": None, "attachments": [], "images": [],
                    "text": "正文", "text_scope": "extracted_text", "summary": None,
                    "has_summary": None, "created_at": "2026-09-01T10:00:00+08:00",
                    "modified_at": None, "original_document_available": True,
                    "category": None, "original_url": None, "warnings": []}
        self.sdk.timeline_pages[("kb1", None)] = self.page([ima_item])
        summary = self.run_export(args)
        self.assertEqual(summary["undated_records"], 1)
        self.assertFalse(summary["provider_full_export_supported"])
        self.assertIn("keywordless_enumeration_not_supported",
                      {gap["code"] for gap in summary["gaps"]})
        self.assertTrue(summary["all_jobs_attempted"])
        record = self.records("unknown", provider="ima")[0]
        self.assertIsNone(record["local_date"])
        self.assertEqual(record["content_text"], "正文")
        snapshot = json.loads((self.root / "daily/unknown/ima/knowledge_bases.json").read_text())
        self.assertFalse(snapshot["provider_full_export_supported"])
        self.assertEqual(snapshot["knowledge_bases"], [{"collection_id": "kb1", "name": None}])
        state = next(iter(json.loads((self.root / "checkpoints/ima.json").read_text())["jobs"].values()))
        self.assertFalse(state["coverage_complete"])  # honest: full export unsupported upstream

    def test_comments_pagination_written_to_file_and_record(self):
        topic = self.item()
        self.sdk.timeline_pages[("123", None)] = self.page([topic])
        comment = lambda cid: {"ref": "zsxq://comment/123/456/" + cid, "comment_id": cid,
                               "author": None, "role": None, "created_at": None, "text": "评论" + cid,
                               "reply_to": None, "like_count": None, "replies": [], "warnings": []}
        self.sdk.comment_pages[("zsxq://topic/123/456", None)] = {
            "comments": [comment("1")], "continuation_cursor": "cc-1",
            "coverage": {"state": "budget_exhausted", "scanned": 1, "returned": 1},
            "diagnostics": [{"code": "nested_replies_not_provided"}], "status": "partial"}
        self.sdk.comment_pages[("zsxq://topic/123/456", "cc-1")] = {
            "comments": [comment("2")], "continuation_cursor": None,
            "coverage": {"state": "complete", "scanned": 1, "returned": 1},
            "diagnostics": [{"code": "nested_replies_not_provided"}], "status": "ok"}
        summary = self.run_export(self.args("--comments"))
        self.assertTrue(summary["all_jobs_attempted"])
        path = self.root / "daily/2026-09-20/zsxq/comments/zsxq_topic_123_456.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        self.assertEqual([row["comment_id"] for row in rows], ["1", "2"])
        record = self.record_for("zsxq://topic/123/456")
        self.assertEqual(record["comments_fetched"], 2)
        self.assertEqual(record["comments_nested"], "not_provided_upstream")
        self.assertEqual(self.sdk.comment_calls, [("zsxq://topic/123/456", None),
                                                  ("zsxq://topic/123/456", "cc-1")])
        kinds = {json.loads(p.read_text())["kind"] for p in (self.root / "raw").rglob("*.jsonl")}
        self.assertEqual(kinds, {"timeline", "comments"})

    def test_comments_resume_without_duplicates_after_budget_stop(self):
        topic = self.item()
        self.sdk.timeline_pages[("123", None)] = self.page([topic])
        comment = lambda cid: {"ref": "zsxq://comment/123/456/" + cid, "comment_id": cid,
                               "author": None, "role": None, "created_at": None, "text": "t" + cid,
                               "reply_to": None, "like_count": None, "replies": [], "warnings": []}
        self.sdk.comment_pages[("zsxq://topic/123/456", None)] = {
            "comments": [comment("1")], "continuation_cursor": "cc-1",
            "coverage": {"state": "budget_exhausted", "scanned": 1, "returned": 1},
            "diagnostics": [], "status": "partial"}
        self.sdk.comment_pages[("zsxq://topic/123/456", "cc-1")] = {
            "comments": [comment("2")], "continuation_cursor": None,
            "coverage": {"state": "complete", "scanned": 1, "returned": 1},
            "diagnostics": [], "status": "ok"}
        args = self.args("--comments", "--max-calls", "2")
        first = self.run_export(args)
        self.assertEqual(first["jobs_remaining"], 1)
        self.assertEqual(self.sdk.comment_calls, [("zsxq://topic/123/456", None)])
        second = self.run_export(args)
        self.assertTrue(second["all_jobs_attempted"])
        self.assertEqual(second["sdk_calls"], 1)  # only the second comments page costs a call
        path = self.root / "daily/2026-09-20/zsxq/comments/zsxq_topic_123_456.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        self.assertEqual([row["comment_id"] for row in rows], ["1", "2"])

    def test_assets_download_object_manifest_record_and_rerun_dedupe(self):
        topic = self.item(attachments=[self.attachment()])
        self.sdk.timeline_pages[("123", None)] = self.page([topic])
        self.pdf_asset("zsxq://file/123/456/789")
        args = self.args("--assets")
        summary = self.run_export(args)
        self.assertEqual(summary["assets_downloaded"], 1)
        sha = x.hashlib.sha256(b"%PDF-1.4 fake report bytes").hexdigest()
        self.assertEqual((self.root / "objects" / sha[:2] / sha).read_bytes(), b"%PDF-1.4 fake report bytes")
        manifest_path = self.root / "assets/zsxq/123/zsxq_topic_123_456/manifest.json"
        entries = json.loads(manifest_path.read_text())
        self.assertEqual(entries[0]["status"], "ok")
        self.assertEqual(entries[0]["sha256"], sha)
        self.assertEqual(entries[0]["object_path"], f"objects/{sha[:2]}/{sha}")
        self.assertEqual(entries[0]["original_filename"], "report.pdf")
        self.assertEqual(entries[0]["asset_ref"], "zsxq://file/123/456/789")
        record = self.record_for("zsxq://topic/123/456")
        self.assertEqual(record["attachments"][0]["status"], "ok")
        self.assertEqual(record["asset_manifest"], "assets/zsxq/123/zsxq_topic_123_456/manifest.json")
        # Re-run: the completed job is skipped, so no new download happens and the
        # manifest keeps its ok entry (the asset_refs index is the dedupe authority).
        rerun = self.run_export(args)
        self.assertEqual(self.sdk.asset_calls, ["zsxq://file/123/456/789"])
        self.assertEqual(rerun["assets_downloaded"], 0)
        entries = json.loads((self.root / "assets/zsxq/123/zsxq_topic_123_456/manifest.json").read_text())
        self.assertEqual(entries[0]["status"], "ok")
        self.assertEqual(entries[0]["sha256"], sha)
        # When the job does run again (missing manifest), rows short-circuit to skipped.
        entries[0]["status"] = "ok"
        (self.root / "assets/zsxq/123/zsxq_topic_123_456/manifest.json").write_text("[]")
        with use_sdk(self.sdk):
            archive = x.ExportArchive(self.root)
            state = archive.state(x.make_jobs(self.args())["jobs"][0])
            state["assets"]["zsxq://topic/123/456"]["resolved"] = 0
            archive.save_state(x.make_jobs(self.args())["jobs"][0], state)
            archive.db.close()
        self.run_export(args)
        entries = json.loads((self.root / "assets/zsxq/123/zsxq_topic_123_456/manifest.json").read_text())
        self.assertEqual(self.sdk.asset_calls, ["zsxq://file/123/456/789"])
        self.assertEqual(entries[0]["status"], "skipped")
        self.assertEqual(entries[0]["reason"], "already_archived")

    def test_assets_same_sha_stored_once(self):
        first = self.item(attachments=[self.attachment(ref="zsxq://file/123/456/1")])
        second = self.item(ref="zsxq://topic/123/457",
                           attachments=[self.attachment(ref="zsxq://file/123/456/2")])
        self.sdk.timeline_pages[("123", None)] = self.page([first, second])
        self.pdf_asset("zsxq://file/123/456/1")
        self.pdf_asset("zsxq://file/123/456/2")
        self.run_export(self.args("--assets"))
        objects = [p for p in (self.root / "objects").rglob("*") if p.is_file()]
        self.assertEqual(len(objects), 1)
        self.assertEqual(self.sdk.asset_calls, ["zsxq://file/123/456/1", "zsxq://file/123/456/2"])
        manifest = json.loads((self.root / "assets/zsxq/123/zsxq_topic_123_457/manifest.json").read_text())
        self.assertEqual(manifest[0]["object_path"], f"objects/{objects[0].name[:2]}/{objects[0].name}")

    def test_asset_failure_reason_recorded_in_manifest_and_index(self):
        topic = self.item(attachments=[self.attachment(size=99999999)])
        self.sdk.timeline_pages[("123", None)] = self.page([topic])
        self.pdf_asset("zsxq://file/123/456/789", content=b"too big", status="failed",
                       reason="asset_exceeds_max_bytes")
        summary = self.run_export(self.args("--assets"))
        self.assertEqual(summary["assets_failed"], 1)
        manifest = json.loads((self.root / "assets/zsxq/123/zsxq_topic_123_456/manifest.json").read_text())
        self.assertEqual(manifest[0]["status"], "failed")
        self.assertEqual(manifest[0]["reason"], "asset_exceeds_max_bytes")
        self.assertIsNone(manifest[0]["object_path"])
        self.assertFalse((self.root / "objects").exists())
        with use_sdk(self.sdk):
            archive = x.ExportArchive(self.root)
            row = archive.asset_ref_row("zsxq", "zsxq://topic/123/456", "zsxq://file/123/456/789")
            self.assertEqual(row["status"], "failed")
            archive.db.close()

    def test_size_guard_trips_and_stops_assets(self):
        topic = self.item(attachments=[self.attachment(ref="zsxq://file/123/456/1", size=100),
                                       self.attachment(ref="zsxq://file/123/456/2", size=100)])
        self.sdk.timeline_pages[("123", None)] = self.page([topic])
        self.pdf_asset("zsxq://file/123/456/1", content=b"%PDF-1.4 " + b"a" * 92)
        self.pdf_asset("zsxq://file/123/456/2", content=b"%PDF-1.4 " + b"b" * 92)
        args = self.args("--assets", "--size-guard-bytes", "150")
        summary = self.run_export(args)
        self.assertTrue(summary["size_guard_tripped"])
        self.assertIn("size_guard_tripped", {row["code"] for row in summary["diagnostics"]})
        self.assertEqual(self.sdk.asset_calls, ["zsxq://file/123/456/1"])
        manifest = json.loads((self.root / "assets/zsxq/123/zsxq_topic_123_456/manifest.json").read_text())
        self.assertEqual([entry["status"] for entry in manifest], ["ok", "skipped"])
        self.assertEqual(manifest[1]["reason"], "size_guard_tripped")
        self.assertFalse(list((self.root / "objects").rglob(".pending-*")))
        self.assertFalse(summary["all_jobs_attempted"])  # assets unresolved, resumable

    def test_max_assets_budget_stops_job_and_resumes_next_run(self):
        topic = self.item(attachments=[self.attachment(ref="zsxq://file/123/456/1"),
                                       self.attachment(ref="zsxq://file/123/456/2")])
        self.sdk.timeline_pages[("123", None)] = self.page([topic])
        self.pdf_asset("zsxq://file/123/456/1", content=b"%PDF-1.4 first")
        self.pdf_asset("zsxq://file/123/456/2", content=b"%PDF-1.4 second")
        args = self.args("--assets", "--max-assets", "1")
        first = self.run_export(args)
        self.assertFalse(first["all_jobs_attempted"])
        self.assertEqual(first["assets_downloaded"], 1)
        self.assertEqual(self.sdk.asset_calls, ["zsxq://file/123/456/1"])
        state = next(iter(json.loads((self.root / "checkpoints/zsxq.json").read_text())["jobs"].values()))
        self.assertEqual(state["state"], "pending")
        self.assertEqual(state["stop_reason"], "asset_budget")
        second = self.run_export(self.args("--assets", "--max-assets", "5"))
        self.assertTrue(second["all_jobs_attempted"])
        self.assertEqual(self.sdk.asset_calls, ["zsxq://file/123/456/1", "zsxq://file/123/456/2"])
        manifest = json.loads((self.root / "assets/zsxq/123/zsxq_topic_123_456/manifest.json").read_text())
        self.assertEqual([entry["status"] for entry in manifest], ["skipped", "ok"])
        self.assertEqual(manifest[0]["reason"], "already_archived")

    def test_declared_oversize_persisted_without_call_and_advances(self):
        topic = self.item(attachments=[self.attachment(size=1000)])
        self.sdk.timeline_pages[("123", None)] = self.page([topic])
        args = self.args("--assets", "--asset-max-bytes", "500")
        first = self.run_export(args)
        self.assertTrue(first["all_jobs_attempted"])  # deterministic failure = resolved
        self.assertEqual(first["assets_failed"], 1)
        self.assertEqual(self.sdk.asset_calls, [])  # precheck: zero SDK download calls
        manifest = json.loads((self.root / "assets/zsxq/123/zsxq_topic_123_456/manifest.json").read_text())
        self.assertEqual(manifest[0]["status"], "failed")
        self.assertEqual(manifest[0]["reason"], "asset_exceeds_max_bytes")
        self.assertEqual(manifest[0]["declared_size"], 1000)
        with use_sdk(self.sdk):
            archive = x.ExportArchive(self.root)
            row = archive.asset_ref_row("zsxq", "zsxq://topic/123/456", "zsxq://file/123/456/789")
            self.assertEqual(row["status"], "failed")
            self.assertEqual(row["reason"], "asset_exceeds_max_bytes")
            archive.db.close()
        # Second run: the completed job is skipped; nothing is re-counted or re-called.
        second = self.run_export(args)
        self.assertEqual(second["sdk_calls"], 0)
        self.assertEqual(second["assets_failed"], 0)
        self.assertEqual(self.sdk.asset_calls, [])
        # Force the job to re-enter (crash-style): the persisted failure still does
        # not double-count and still costs no SDK call.
        with use_sdk(self.sdk):
            archive = x.ExportArchive(self.root)
            job = x.make_jobs(self.args())["jobs"][0]
            state = archive.state(job)
            state["assets"]["zsxq://topic/123/456"]["resolved"] = 0
            archive.save_state(job, state)
            archive.db.close()
        third = self.run_export(args)
        self.assertEqual(third["assets_failed"], 0)
        self.assertEqual(self.sdk.asset_calls, [])
        # Raising the byte cap makes the deterministic failure retryable again.
        self.pdf_asset("zsxq://file/123/456/789")
        raised = self.run_export(self.args("--assets"))
        self.assertEqual(raised["assets_downloaded"], 1)
        self.assertEqual(self.sdk.asset_calls, ["zsxq://file/123/456/789"])

    def test_path_traversal_filenames_sanitized(self):
        topic = self.item(attachments=[self.attachment(name="../../etc/evil.pdf"),
                                       self.attachment(ref="zsxq://file/123/456/2",
                                                       name="..\\..\\win.dll")])
        self.sdk.timeline_pages[("123", None)] = self.page([topic])
        self.pdf_asset("zsxq://file/123/456/789")
        self.pdf_asset("zsxq://file/123/456/2", content=b"%PDF-1.4 other bytes")
        self.run_export(self.args("--assets"))
        manifest = json.loads((self.root / "assets/zsxq/123/zsxq_topic_123_456/manifest.json").read_text())
        for entry in manifest:
            self.assertIsNotNone(entry["safe_filename"])
            self.assertNotIn("/", entry["safe_filename"])
            self.assertNotIn("\\", entry["safe_filename"])
            self.assertNotIn("..", entry["safe_filename"])
            self.assertRegex(entry["safe_filename"], r"^[A-Za-z0-9._-]{1,120}$")
        self.assertEqual(manifest[0]["safe_filename"], "evil.pdf")

    def test_collections_missing_reported_from_sqlite_jobs(self):
        subscriptions = self.root / "subscriptions" / "latest.json"
        subscriptions.parent.mkdir(parents=True)
        subscriptions.write_text(json.dumps({"zsxq": {"groups": [
            {"group_id": "111", "name": "A"}, {"group_id": "222", "name": "B"}]}}))
        args = x.parser().parse_args([
            "--archive-root", str(self.root), "--provider", "zsxq",
            "--start", "2026-09-20", "--end", "2026-09-20", "--interval", "0"])
        self.sdk.timeline_pages[("111", None)] = self.page([self.item(collection_id="111")])
        self.sdk.timeline_pages[("222", None)] = self.page([self.item(collection_id="222",
                                                                      ref="zsxq://topic/222/1")])
        first = self.run_export(args)
        self.assertEqual(first["jobs_selected"], 2)
        subscriptions.write_text(json.dumps({"zsxq": {"groups": [{"group_id": "111", "name": "A"}]}}))
        second = self.run_export(args)
        self.assertEqual(second["collections_missing"], ["222"])
        self.assertEqual(second["jobs_selected"], 1)
        self.assertEqual(second["sdk_calls"], 0)  # collection 111 already attempted

    def test_export_coexists_with_keyword_jobs_without_id_collision(self):
        old_args = d.parser().parse_args([
            "--archive-root", str(self.root), "--provider", "zsxq", "--query", "zsxq=宏观",
            "--collection", "zsxq=123", "--start", "2026-09-20", "--end", "2026-09-20",
            "--interval", "0"])
        old_result = {"status": "partial", "complete": True,
                      "items": [{"versions": [{"source_ref": "zsxq://topic/123/456", "title": "旧记录",
                                              "text": "旧正文", "text_scope": "source_excerpt",
                                              "published_at": "2026-09-20T10:00:00+08:00",
                                              "collection_id": "123"}]}],
                      "coverage": [{"provider": "zsxq", "state": "queried", "continuation_cursors": []}],
                      "diagnostics": [], "gaps": []}
        old_summary = d.execute(old_args, d.make_jobs(old_args), runner=lambda kind, req: old_result)
        self.assertEqual(old_summary["records_total"], 1)
        self.sdk.timeline_pages[("123", None)] = self.page([self.item()])
        export_summary = self.run_export()
        self.assertEqual(export_summary["records_total"], 2)
        planned = x.make_jobs(self.args())
        old_jobs = d.make_jobs(old_args)
        self.assertNotIn(planned["jobs"][0]["id"], {job["id"] for job in old_jobs})
        checkpoint = json.loads((self.root / "checkpoints/zsxq.json").read_text())
        self.assertEqual(len(checkpoint["jobs"]), 2)
        states = {state["job"]["mode"] if "mode" in state["job"] else "keyword" for state in checkpoint["jobs"].values()}
        self.assertEqual(states, {"export", "keyword"})
        kinds = {json.loads(p.read_text())["kind"] for p in (self.root / "raw").rglob("*.jsonl")}
        self.assertEqual(kinds, {"search", "timeline"})

    def test_wisburg_report_abstract_preserved_and_assets_unsupported(self):
        args = x.parser().parse_args([
            "--archive-root", str(self.root), "--provider", "wisburg", "--collection", "article",
            "--start", "2026-09-20", "--end", "2026-09-20", "--interval", "0", "--assets"])
        report = self.item(ref="wisburg://report/article/9", type="report", collection_id="article",
                           published_at="2026-09-20T08:00:00+08:00", text=None, text_scope=None,
                           summary="供应商摘要", has_summary=True, labels=[], like_count=None,
                           comments_count=None, original_document_available=False,
                           attachments=[{"source_ref": "wisburg://file/9", "name": "orig.pdf",
                                         "media_type": "pdf", "size_bytes": 10,
                                         "status": "metadata_only"}])
        self.sdk.timeline_pages[("article", None)] = self.page([report])
        summary = self.run_export(args)
        self.assertTrue(summary["all_jobs_attempted"])
        record = self.records(provider="wisburg")[0]
        self.assertEqual(record["content_text"], "供应商摘要")
        self.assertEqual(record["text_scope"], "abstract")
        self.assertIs(record["original_document_available"], False)
        manifest = json.loads((self.root / "assets/wisburg/article/wisburg_report_article_9/manifest.json").read_text())
        self.assertEqual(manifest[0]["status"], "unsupported")
        self.assertEqual(manifest[0]["reason"], "upstream_does_not_provide_original_files")
        self.assertEqual(self.sdk.asset_calls, [])  # short-circuited, no SDK download call

    def test_images_stay_metadata_only_and_are_never_downloaded(self):
        topic = self.item(images=[{"index": 0, "image_id": "999"}])
        self.sdk.timeline_pages[("123", None)] = self.page([topic])
        summary = self.run_export(self.args("--assets"))
        self.assertTrue(summary["all_jobs_attempted"])
        record = self.record_for("zsxq://topic/123/456")
        self.assertEqual(record["images"], [{"index": 0, "image_id": "999"}])
        manifest = json.loads((self.root / "assets/zsxq/123/zsxq_topic_123_456/manifest.json").read_text())
        self.assertEqual(manifest[0]["kind"], "image")
        self.assertEqual(manifest[0]["status"], "unsupported")
        self.assertEqual(manifest[0]["reason"], "original_image_download_not_provided_upstream")
        self.assertEqual(self.sdk.asset_calls, [])

    def test_entitlement_denied_is_terminal_and_does_not_block_other_collection(self):
        args = x.parser().parse_args([
            "--archive-root", str(self.root), "--provider", "zsxq",
            "--collection", "123", "--collection", "456",
            "--start", "2026-09-20", "--end", "2026-09-20", "--interval", "0"])
        self.sdk.timeline_pages[("123", None)] = self.page(
            state="upstream_stopped", diagnostics=[{"code": "entitlement_denied"}])
        self.sdk.timeline_pages[("456", None)] = self.page(
            [self.item(collection_id="456", ref="zsxq://topic/456/1")])
        summary = self.run_export(args)
        self.assertEqual(summary["jobs_failed"], 0)
        self.assertEqual(summary["errors"], 0)
        self.assertEqual(summary["jobs_denied"], 1)
        self.assertEqual(summary["collections_denied"], ["123"])
        self.assertTrue(summary["all_jobs_attempted"])  # denied counts as resolved
        self.assertEqual(summary["jobs_remaining"], 0)
        self.assertEqual(summary["records_total"], 1)
        self.assertEqual(self.sdk.timeline_calls, [("123", None), ("456", None)])
        checkpoint = json.loads((self.root / "checkpoints/zsxq.json").read_text())["jobs"]
        by_collection = {state["job"]["collection"]: state for state in checkpoint.values()}
        self.assertEqual(by_collection["123"]["state"], "denied")
        self.assertEqual(by_collection["123"]["stop_reason"], "denied")
        self.assertEqual(by_collection["456"]["state"], "attempted")
        manifest = json.loads((self.root / "daily/2026-09-20/zsxq/manifest.json").read_text())
        states = {entry["job_id"]: entry["state"] for entry in manifest["jobs"]}
        self.assertIn("denied", states.values())
        # Terminal: re-running never re-probes the denied collection.
        second = self.run_export(args)
        self.assertEqual(self.sdk.timeline_calls, [("123", None), ("456", None)])
        self.assertEqual(second["sdk_calls"], 0)
        self.assertEqual(second["jobs_denied"], 1)
        self.assertTrue(second["all_jobs_attempted"])

    def test_denied_variants_not_registered_and_disabled(self):
        args = x.parser().parse_args([
            "--archive-root", str(self.root), "--provider", "zsxq",
            "--collection", "123", "--collection", "456",
            "--start", "2026-09-20", "--end", "2026-09-20", "--interval", "0"])
        self.sdk.timeline_pages[("123", None)] = self.page(
            state="upstream_stopped", diagnostics=[{"code": "not_registered"}])
        self.sdk.timeline_pages[("456", None)] = self.page(
            state="upstream_stopped", diagnostics=[{"code": "disabled"}])
        summary = self.run_export(args)
        self.assertEqual(summary["jobs_denied"], 2)
        self.assertEqual(summary["jobs_failed"], 0)
        self.assertEqual(summary["errors"], 0)
        self.assertTrue(summary["all_jobs_attempted"])

    def test_rate_limit_with_entitlement_code_stays_retryable_failure(self):
        # A provider-wide code (rate_limit) alongside an entitlement diagnostic is
        # NOT a deterministic permission fact: it keeps the retryable semantics.
        self.sdk.timeline_pages[("123", None)] = self.page(
            state="upstream_stopped",
            diagnostics=[{"code": "entitlement_denied"}, {"code": "rate_limit"}])
        first = self.run_export()
        self.assertEqual(first["jobs_denied"], 0)
        self.assertEqual(first["jobs_failed"], 0)  # rate-limit stop is pending, not denied
        self.assertEqual(first["jobs_remaining"], 1)
        self.assertEqual(first["errors"], 1)
        self.sdk.timeline_pages[("123", None)] = self.page([self.item()])
        second = self.run_export()
        self.assertTrue(second["all_jobs_attempted"])
        self.assertEqual(second["records_total"], 1)

    def test_old_failed_entitlement_checkpoint_migrates_to_denied(self):
        args = self.args()
        planned = x.make_jobs(args)
        state = x.ExportArchive(self.root).state(planned["jobs"][0])
        state.update(state="failed", stop_reason="entitlement_denied", pages=1)
        archive = x.ExportArchive(self.root)
        archive.save_state(planned["jobs"][0], state)
        archive.db.close()
        summary = self.run_export(args)
        self.assertEqual(self.sdk.timeline_calls, [])  # migrated without an SDK call
        self.assertEqual(summary["jobs_denied"], 1)
        self.assertEqual(summary["jobs_failed"], 0)
        self.assertTrue(summary["all_jobs_attempted"])
        checkpoint = json.loads((self.root / "checkpoints/zsxq.json").read_text())["jobs"]
        self.assertEqual(next(iter(checkpoint.values()))["state"], "denied")
    def test_stage_comments_resumes_completed_timeline_without_timeline_calls(self):
        topic = self.item()
        self.sdk.timeline_pages[("123", None)] = self.page([topic])
        first = self.run_export()  # enumeration only; job ends attempted
        self.assertTrue(first["all_jobs_attempted"])
        self.assertEqual(self.sdk.timeline_calls, [("123", None)])
        self.assertEqual(first["records_total"], 1)
        comment = lambda cid: {"ref": "zsxq://comment/123/456/" + cid, "comment_id": cid,
                               "author": None, "role": None, "created_at": None, "text": "t" + cid,
                               "reply_to": None, "like_count": None, "replies": [], "warnings": []}
        self.sdk.comment_pages[("zsxq://topic/123/456", None)] = {
            "comments": [comment("1"), comment("2")], "continuation_cursor": None,
            "coverage": {"state": "complete", "scanned": 2, "returned": 2},
            "diagnostics": [{"code": "nested_replies_not_provided"}], "status": "ok"}
        second = self.run_export(self.args("--stage", "comments"))
        self.assertEqual(self.sdk.timeline_calls, [("123", None)])  # zero new timeline calls
        self.assertEqual(self.sdk.comment_calls, [("zsxq://topic/123/456", None)])
        self.assertEqual(second["records_total"], 1)  # no duplicated records
        self.assertEqual(len(list((self.root / "raw").rglob("*.jsonl"))), 2)
        path = self.root / "daily/2026-09-20/zsxq/comments/zsxq_topic_123_456.jsonl"
        self.assertEqual(len(path.read_text().splitlines()), 2)
        record = self.record_for("zsxq://topic/123/456")
        self.assertEqual(record["comments_fetched"], 2)
        checkpoint = json.loads((self.root / "checkpoints/zsxq.json").read_text())["jobs"]
        state = next(iter(checkpoint.values()))
        self.assertEqual(state["state"], "attempted")  # back to attempted, not degraded
        self.assertTrue(state["coverage_complete"])
        with self.assertRaises(ValueError):
            x.make_jobs(self.args("--stage", "comments", "--comments"))

    def test_stage_assets_rebuilds_manifest_without_timeline_calls(self):
        topic = self.item(attachments=[self.attachment()])
        self.sdk.timeline_pages[("123", None)] = self.page([topic])
        self.pdf_asset("zsxq://file/123/456/789")
        first = self.run_export(self.args("--assets"))
        self.assertTrue(first["all_jobs_attempted"])
        self.assertEqual(first["assets_downloaded"], 1)
        # Crash simulation: object + asset_refs row survive, manifest is lost.
        (self.root / "assets/zsxq/123/zsxq_topic_123_456/manifest.json").unlink()
        second = self.run_export(self.args("--stage", "assets"))
        self.assertEqual(self.sdk.timeline_calls, [("123", None)])  # zero new timeline calls
        self.assertEqual(self.sdk.asset_calls, ["zsxq://file/123/456/789"])  # no re-download
        self.assertTrue(second["all_jobs_attempted"])
        manifest = json.loads((self.root / "assets/zsxq/123/zsxq_topic_123_456/manifest.json").read_text())
        self.assertEqual(manifest[0]["status"], "skipped")
        self.assertEqual(manifest[0]["reason"], "already_archived")

    def test_legacy_transport_limit_failure_is_reopened(self):
        nine_mib = 9 * 1024 * 1024
        topic = self.item(attachments=[self.attachment(size=nine_mib)])
        self.sdk.timeline_pages[("123", None)] = self.page([topic])
        args = self.args("--assets")
        self.sdk.assets["zsxq://file/123/456/789"] = {
            "status": "failed", "reason": "exceeds_official_transport_limit",
            "ref": "zsxq://file/123/456/789", "filename": "big.pdf",
            "media_type": "application/pdf", "size_bytes": nine_mib,
            "content_sha256": None, "warnings": [], "content": None}
        first = self.run_export(args)
        self.assertTrue(first["all_jobs_attempted"])
        self.assertEqual(first["assets_failed"], 1)
        self.assertEqual(self.sdk.asset_calls, ["zsxq://file/123/456/789"])
        manifest = json.loads((self.root / "assets/zsxq/123/zsxq_topic_123_456/manifest.json").read_text())
        self.assertEqual(manifest[0]["reason"], "exceeds_official_transport_limit")
        self.pdf_asset("zsxq://file/123/456/789", content=b"%PDF-1.4 recovered")
        second = self.run_export(args)
        self.assertEqual(second["assets_downloaded"], 1)
        self.assertEqual(self.sdk.asset_calls,
                         ["zsxq://file/123/456/789", "zsxq://file/123/456/789"])
        manifest = json.loads((self.root / "assets/zsxq/123/zsxq_topic_123_456/manifest.json").read_text())
        self.assertEqual(manifest[0]["status"], "ok")

    def test_batch_of_declared_oversize_does_not_block_other_assets(self):
        big = [self.attachment(ref=f"zsxq://file/123/456/big{i}", size=60 * 1024 * 1024)
               for i in range(25)]
        topic_a = self.item(ref="zsxq://topic/123/456", attachments=big + [self.attachment()])
        topic_b = self.item(ref="zsxq://topic/123/789", collection_id="456",
                            attachments=[self.attachment(ref="zsxq://file/456/789/1")])
        args = x.parser().parse_args([
            "--archive-root", str(self.root), "--provider", "zsxq",
            "--collection", "123", "--collection", "456",
            "--start", "2026-09-20", "--end", "2026-09-20", "--interval", "0", "--assets"])
        self.sdk.timeline_pages[("123", None)] = self.page([topic_a])
        self.sdk.timeline_pages[("456", None)] = self.page([topic_b])
        self.pdf_asset("zsxq://file/123/456/789")
        self.pdf_asset("zsxq://file/456/789/1", content=b"%PDF-1.4 other bytes")
        first = self.run_export(args)
        self.assertTrue(first["all_jobs_attempted"])
        self.assertEqual(first["assets_failed"], 25)
        self.assertEqual(first["assets_downloaded"], 2)  # both normal assets still fetched
        self.assertEqual(self.sdk.asset_calls, ["zsxq://file/123/456/789", "zsxq://file/456/789/1"])
        second = self.run_export(args)
        self.assertEqual(second["sdk_calls"], 0)
        self.assertEqual(second["assets_failed"], 0)
        self.assertEqual(second["assets_downloaded"], 0)
        self.assertEqual(self.sdk.asset_calls, ["zsxq://file/123/456/789", "zsxq://file/456/789/1"])

    def test_persisted_response_too_large_is_retried(self):
        topic = self.item(attachments=[self.attachment(size=None)])
        self.sdk.timeline_pages[("123", None)] = self.page([topic])
        self.sdk.assets["zsxq://file/123/456/789"] = {
            "status": "failed", "reason": "response_too_large", "ref": "zsxq://file/123/456/789",
            "filename": "big.pdf", "media_type": "application/pdf", "size_bytes": 15 * 1024 * 1024,
            "content_sha256": None, "warnings": [], "content": None}
        args = self.args("--assets")
        first = self.run_export(args)
        self.assertEqual(first["assets_failed"], 1)
        self.assertEqual(self.sdk.asset_calls, ["zsxq://file/123/456/789"])
        self.pdf_asset("zsxq://file/123/456/789", content=b"%PDF-1.4 recovered")
        second = self.run_export(args)
        self.assertEqual(second["assets_downloaded"], 1)
        self.assertEqual(self.sdk.asset_calls,
                         ["zsxq://file/123/456/789", "zsxq://file/123/456/789"])
        self.assertTrue(second["all_jobs_attempted"])
        manifest = json.loads((self.root / "assets/zsxq/123/zsxq_topic_123_456/manifest.json").read_text())
        self.assertEqual(manifest[0]["status"], "ok")

    def test_asset_terminal_failure_does_not_block_next_collection(self):
        topic_a = self.item(ref="zsxq://topic/123/456",
                            attachments=[self.attachment(size=9 * 1024 * 1024)])
        topic_b = self.item(ref="zsxq://topic/456/1", collection_id="456",
                            attachments=[self.attachment(ref="zsxq://file/456/1/1")])
        args = x.parser().parse_args([
            "--archive-root", str(self.root), "--provider", "zsxq",
            "--collection", "123", "--collection", "456",
            "--start", "2026-09-20", "--end", "2026-09-20", "--interval", "0", "--assets"])
        self.sdk.timeline_pages[("123", None)] = self.page([topic_a])
        self.sdk.timeline_pages[("456", None)] = self.page([topic_b])
        self.pdf_asset("zsxq://file/456/1/1", content=b"%PDF-1.4 healthy")
        summary = self.run_export(args)
        self.assertTrue(summary["all_jobs_attempted"])
        self.assertEqual(summary["assets_failed"], 1)
        self.assertEqual(self.sdk.asset_calls,
                         ["zsxq://file/123/456/789", "zsxq://file/456/1/1"])
        self.assertEqual(self.sdk.timeline_calls, [("123", None), ("456", None)])

    def test_asset_rate_limit_saves_breakpoint_and_resumes(self):
        topic_a = self.item(ref="zsxq://topic/123/456",
                            attachments=[self.attachment(ref="zsxq://file/123/456/1"),
                                         self.attachment(ref="zsxq://file/123/456/2")])
        topic_b = self.item(ref="zsxq://topic/456/1", collection_id="456",
                            attachments=[self.attachment(ref="zsxq://file/456/1/1")])
        args = x.parser().parse_args([
            "--archive-root", str(self.root), "--provider", "zsxq",
            "--collection", "123", "--collection", "456",
            "--start", "2026-09-20", "--end", "2026-09-20", "--interval", "0", "--assets"])
        self.sdk.timeline_pages[("123", None)] = self.page([topic_a])
        self.sdk.timeline_pages[("456", None)] = self.page([topic_b])
        self.sdk.assets["zsxq://file/123/456/1"] = {
            "status": "metadata_only", "reason": "rate_limit", "ref": "zsxq://file/123/456/1",
            "filename": "a.pdf", "media_type": "application/pdf", "size_bytes": None,
            "content_sha256": None, "warnings": [], "content": None}
        first = self.run_export(args)
        self.assertEqual(first["assets_failed"], 0)  # rate-limit stop is not a failure count
        self.assertIn("rate_limit_stopped", {row["code"] for row in first["diagnostics"]})
        checkpoint = json.loads((self.root / "checkpoints/zsxq.json").read_text())["jobs"]
        by_collection = {state_["job"]["collection"]: state_ for state_ in checkpoint.values()}
        self.assertEqual(by_collection["123"]["state"], "pending")
        self.assertEqual(by_collection["123"]["stop_reason"], "rate_limit_stopped")
        self.assertEqual(self.sdk.asset_calls, ["zsxq://file/123/456/1"])  # provider stopped mid-asset
        with use_sdk(self.sdk):
            archive = x.ExportArchive(self.root)
            row = archive.asset_ref_row("zsxq", "zsxq://topic/123/456", "zsxq://file/123/456/1")
            self.assertEqual((row["status"], row["reason"]), ("failed", "rate_limit"))
            archive.db.close()
        # Second run retries the rate-limited asset (NOT terminal) and completes the rest.
        self.pdf_asset("zsxq://file/123/456/1", content=b"%PDF-1.4 one")
        self.pdf_asset("zsxq://file/123/456/2", content=b"%PDF-1.4 two")
        self.pdf_asset("zsxq://file/456/1/1", content=b"%PDF-1.4 three")
        second = self.run_export(args)
        self.assertTrue(second["all_jobs_attempted"])
        self.assertEqual(second["assets_downloaded"], 3)
        self.assertEqual(self.sdk.asset_calls, ["zsxq://file/123/456/1", "zsxq://file/123/456/1",
                                                "zsxq://file/123/456/2", "zsxq://file/456/1/1"])

    def test_stage_assets_skips_denied_collection_without_requests(self):
        args = x.parser().parse_args([
            "--archive-root", str(self.root), "--provider", "zsxq",
            "--collection", "123", "--collection", "456",
            "--start", "2026-09-20", "--end", "2026-09-20", "--interval", "0"])
        self.sdk.timeline_pages[("123", None)] = self.page(
            state="upstream_stopped", diagnostics=[{"code": "entitlement_denied"}])
        self.sdk.timeline_pages[("456", None)] = self.page(
            [self.item(collection_id="456", ref="zsxq://topic/456/1")])
        first = self.run_export(args)
        self.assertEqual(first["jobs_denied"], 1)
        self.assertEqual(self.sdk.timeline_calls, [("123", None), ("456", None)])
        stage_args = x.parser().parse_args([
            "--archive-root", str(self.root), "--provider", "zsxq",
            "--collection", "123", "--collection", "456",
            "--start", "2026-09-20", "--end", "2026-09-20", "--interval", "0",
            "--stage", "assets"])
        second = self.run_export(stage_args)
        self.assertEqual(self.sdk.timeline_calls, [("123", None), ("456", None)])
        self.assertEqual(self.sdk.asset_calls, [])
        self.assertEqual(second["jobs_denied"], 1)
        checkpoint = json.loads((self.root / "checkpoints/zsxq.json").read_text())["jobs"]
        by_collection = {state["job"]["collection"]: state for state in checkpoint.values()}
        self.assertEqual(by_collection["123"]["state"], "denied")  # not reset
        self.assertEqual(by_collection["456"]["state"], "attempted")


if __name__ == "__main__":
    unittest.main()
