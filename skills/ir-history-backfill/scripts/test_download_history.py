"""Offline invariants: no provider/network calls; real temporary disk archives."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import download_history as d


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "archive"

    def args(self, *extra):
        return d.parser().parse_args(["--archive-root", str(self.root), "--provider", "zsxq", "--query", "zsxq=宏观", "--collection", "zsxq=123", "--start", "2026-09-24", "--end", "2026-09-24", "--interval", "0", *extra])

    def version(self, text="宏观", **extra):
        return dict(source_ref="zsxq://topic/123/456", title="宏观日报", text=text, text_scope="source_excerpt", published_at="2026-09-23T18:00:00Z", collection_id="123", **extra)

    def result(self, versions=None, cursors=None):
        return {"status": "partial", "complete": False, "items": [{"versions": versions if versions is not None else [self.version()]}], "coverage": [{"provider": "zsxq", "state": "queried", "continuation_cursors": cursors or [], "scans": [{"has_more": True}]}], "diagnostics": [{"code": "bounded_test"}], "gaps": [{"code": "source_scan_incomplete"}]}

    def run_archive(self, args=None, runner=None):
        args = args or self.args()
        return d.execute(args, d.make_jobs(args), runner=runner or (lambda kind, req: self.result()))

    def records(self, day="2026-09-24"):
        path = self.root / "daily" / day / "zsxq/records.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()]

    def test_preview_has_no_io_or_sdk_import(self):
        args = self.args()
        with patch.object(d, "SDKRunner", side_effect=AssertionError("SDK imported")), contextlib.redirect_stdout(io.StringIO()):
            code = d.main(["--archive-root", str(self.root), "--provider", "wisburg", "--query", "wisburg=宏观", "--category", "article"])
        self.assertEqual(code, 0)
        self.assertFalse(self.root.exists())
        self.assertEqual(len(d.make_jobs(args)), 1)

    def test_daily_timezone_and_repeat_dedupe(self):
        first = self.run_archive()
        second = self.run_archive(runner=lambda *args: self.fail("Completed job refetched"))
        self.assertEqual(first["records_total"], 1)
        self.assertEqual(second["sdk_calls"], 0)
        record = self.records()[0]
        self.assertEqual(record["local_date"], "2026-09-24")
        self.assertFalse(first["coverage_complete"])
        self.assertTrue(first["all_jobs_attempted"])
        self.assertEqual(len(list((self.root / "raw").rglob("*.jsonl"))), 1)

    def test_cursor_budget_resumes_without_first_page(self):
        calls = []
        def runner(kind, request):
            calls.append(request["source_cursors"])
            return self.result(cursors=["cursor-one"]) if not request["source_cursors"] else self.result([self.version("changed")])
        args = self.args("--max-pages", "1")
        first = self.run_archive(args, runner)
        second = self.run_archive(args, runner)
        self.assertEqual(first["jobs_remaining"], 1)
        self.assertEqual(second["jobs_remaining"], 0)
        self.assertEqual(calls, [[], ["cursor-one"]])
        self.assertEqual({r["version"] for r in self.records()}, {1, 2})

    def test_raw_replay_after_index_crash(self):
        with patch.object(d.Archive, "add", side_effect=RuntimeError("Bearer secret-value")):
            first = self.run_archive()
        self.assertEqual(first["jobs_failed"], 1)
        second = self.run_archive(runner=lambda *args: self.fail("Raw result refetched"))
        self.assertEqual(second["records_total"], 1)
        self.assertEqual(second["sdk_calls"], 0)
        self.assertNotIn("secret-value", "".join(p.read_text() for p in (self.root / "runs").rglob("*.jsonl")))

    def test_unknown_and_out_of_window(self):
        unknown = self.version()
        unknown.pop("published_at")
        unknown["source_created_at"] = "2026-09-24T00:00:00Z"
        outside = self.version()
        outside.update(source_ref="zsxq://topic/123/789", published_at="2026-09-20T00:00:00Z")
        summary = self.run_archive(runner=lambda *args: self.result([unknown, outside]))
        self.assertEqual(summary["undated_records"], 1)
        self.assertIsNone(self.records("unknown")[0]["local_date"])
        self.assertEqual(summary["records_total"], 1)
        manifest = json.loads((self.root / "daily/2026-09-24/zsxq/manifest.json").read_text())
        self.assertEqual(manifest["record_versions"], 0)
        self.assertFalse(manifest["coverage_complete"])

    def test_detail_budget_resume_and_summary_scope(self):
        calls = []
        def runner(kind, request):
            calls.append(kind)
            if kind == "search":
                return self.result()
            return {"status": "partial", "materials": [{"text": "宏观完整摘要", "text_origin": "provider_summary", "read_details": {"content_origin": "provider_stored_summary"}, "warnings": ["not_original_file"]}]}
        args = self.args("--retrieve-details", "--max-requests", "1")
        first = self.run_archive(args, runner)
        self.assertEqual(first["jobs_remaining"], 1)
        second = self.run_archive(args, runner)
        self.assertEqual(calls, ["search", "retrieve"])
        self.assertTrue(second["all_jobs_attempted"])
        detail = next(r for r in self.records() if r["content_text"] == "宏观完整摘要")
        self.assertEqual(detail["text_scope"], "abstract")

    def test_failed_sdk_response_retried_immutably(self):
        first = self.run_archive(runner=lambda *args: {"status": "unavailable", "diagnostics": [{"code": "entitlement_denied"}]})
        self.assertEqual(first["jobs_failed"], 1)
        self.assertEqual(self.run_archive()["records_total"], 1)
        self.assertEqual(len(list((self.root / "raw").rglob("*.jsonl"))), 2)

    def test_stalled_cursor_does_not_loop(self):
        summary = self.run_archive(runner=lambda *args: self.result(cursors=["same"]))
        self.assertEqual(summary["sdk_calls"], 2)
        self.assertEqual(summary["errors"], 1)
        state = next(iter(json.loads((self.root / "checkpoints/zsxq.json").read_text())["jobs"].values()))
        self.assertEqual(state["stop_reason"], "cursor_stalled")

    def test_literal_scopes_and_no_implicit_providers(self):
        args = d.parser().parse_args(["--archive-root", str(self.root), "--provider", "ima", "--query", "ima=宏观", "--collection", "ima=kb1", "--collection", "ima=kb2", "--start", "2026-09-24", "--end", "2026-09-24"])
        jobs = d.make_jobs(args)
        self.assertEqual(len(jobs), 2)
        requests = [d.request_for(job, []) for job in jobs]
        self.assertEqual([r["ima_knowledge_base_ids"] for r in requests], [["kb1"], ["kb2"]])
        self.assertTrue(all(r["providers"] == ["ima"] and r["ima_include_notes"] is False for r in requests))
        args.collection = []
        args.ima_include_notes = True
        with self.assertRaises(ValueError):
            d.make_jobs(args)

    def test_zsxq_timeline_export_is_explicit_unmatched_and_detail_bounded(self):
        args = d.parser().parse_args(["--archive-root", str(self.root), "--provider", "zsxq",
            "--collection", "zsxq=123", "--zsxq-timeline-export", "--candidates", "5",
            "--text-reads", "5", "--start", "2026-09-24", "--end", "2026-09-24"])
        jobs = d.make_jobs(args)
        self.assertEqual(len(jobs), 1)
        self.assertTrue(jobs[0]["zsxq_timeline_export"])
        request = d.request_for(jobs[0], [])
        self.assertEqual(request["keywords"], [])
        self.assertTrue(request["zsxq_timeline_export"])
        self.assertEqual(request["zsxq_group_ids"], ["123"])
        self.assertEqual(request["candidates_per_source"], request["text_reads_per_source"])
        args.candidates = 6
        with self.assertRaises(ValueError):
            d.make_jobs(args)
        args.candidates = 5
        args.query = ["zsxq=宏观"]
        with self.assertRaises(ValueError):
            d.make_jobs(args)

    def test_secrets_removed_from_public_payload(self):
        value = {"api_key": "secret-A", "text": "Bearer secret-B https://example.com/a?token=secret-C", "nested": {"authorization": "secret-D"}}
        sanitized = d.encoded(d.sanitize(value))
        for secret in ("secret-A", "secret-B", "secret-C", "secret-D"):
            self.assertNotIn(secret, sanitized)

    def test_sdk_runner_uses_public_types(self):
        calls = []
        class FakeResult:
            def to_dict(self):
                return {"status": "partial"}
        class SDK:
            MaterialSearchRequest = staticmethod(lambda **kw: ("search_type", kw))
            MaterialRequest = staticmethod(lambda **kw: ("retrieve_type", kw))
            RequestContext = staticmethod(lambda **kw: kw)
            search_materials = staticmethod(lambda req, **kw: (calls.append((req, kw)) or FakeResult()))
            retrieve = staticmethod(lambda req, **kw: (calls.append((req, kw)) or FakeResult()))
        with patch.object(d.importlib, "import_module", return_value=SDK):
            runner = d.SDKRunner(self.args())
            runner("search", {"providers": ["zsxq"]})
            runner("retrieve", {"urls": ["zsxq://topic/123/456"]})
        self.assertEqual([entry[0][0] for entry in calls], ["search_type", "retrieve_type"])

    def test_detail_merge_drops_stale_offsets_and_keeps_warnings(self):
        version = self.version(warnings=["publication_unverified"], attachments=[{"name": "research.pdf"}], evidence_spans=[{"start_char": 400}], content_hash="old", match={"query": "macro"})
        merged = d.merge_detail(version, {"text": "new", "text_origin": "extracted_text", "warnings": ["text_truncated"], "attachments": []})
        self.assertEqual(merged["text_scope"], "extracted_text")
        self.assertEqual(merged["evidence_spans"], [])
        self.assertNotIn("content_hash", merged)
        self.assertEqual(len(merged["warnings"]), 2)
        self.assertEqual(merged["attachments"], version["attachments"])
        empty = d.merge_detail(version, {"text": "", "text_origin": "extracted_text"})
        self.assertEqual(empty["text"], version["text"])
        self.assertEqual(empty["text_scope"], "source_excerpt")

    def test_provider_failure_stops_later_slices_this_run(self):
        args = self.args("--end", "2026-09-26")
        summary = self.run_archive(args, lambda *args: {"status": "unavailable"})
        self.assertEqual(summary["sdk_calls"], 1)
        self.assertEqual(summary["jobs_remaining"], 3)

    def test_collection_entitlement_failure_does_not_block_another_collection(self):
        args = d.parser().parse_args(["--archive-root", str(self.root), "--provider", "zsxq",
            "--query", "zsxq=宏观", "--collection", "zsxq=123", "--collection", "zsxq=456",
            "--start", "2026-09-24", "--end", "2026-09-24", "--interval", "0"])
        calls = []
        def runner(kind, request):
            calls.append(request["zsxq_group_ids"][0])
            if calls[-1] == "123":
                return {"status":"unavailable","coverage":[{"state":"source_queries_failed"}],
                    "diagnostics":[{"code":"entitlement_denied"}]}
            version = self.version()
            version.update(source_ref="zsxq://topic/456/789", collection_id="456")
            return self.result([version])
        summary = self.run_archive(args, runner)
        self.assertEqual(calls, ["123", "456"])
        self.assertEqual(summary["jobs_failed"], 1)
        self.assertEqual(summary["records_total"], 1)


if __name__ == "__main__":
    unittest.main()
