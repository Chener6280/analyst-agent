#!/usr/bin/env python3
"""Bounded public ir_search archival; default is a no-I/O execution preview."""
from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import time
import uuid
from urllib.parse import urlsplit, urlunsplit, parse_qsl
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Shanghai")
PROVIDERS = ("zsxq", "ima", "wisburg")
CATEGORIES = ("ib", "company", "am", "archive", "ec", "feed", "market_daily", "article", "mikko")
SECRET = re.compile(r"^(authorization|cookie|set-cookie|password|secret|token|key|api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?(secret|id)|signature|x-amz-signature)$", re.I)


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sanitize(value):
    if isinstance(value, dict):
        return {k: "[REDACTED]" if SECRET.match(k) else sanitize(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [sanitize(v) for v in value]
    if isinstance(value, str):
        value = re.sub(r"(?i)\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+", r"\1 [REDACTED]", value)

        def clean_url(match):
            try:
                url = urlsplit(match.group())
            except ValueError:
                return "[URL_REDACTED_UNPARSEABLE]"
            if url.username or any(SECRET.match(k) or k.lower() in {"token", "key", "x-oss-signature", "q-signature"} for k, _ in parse_qsl(url.query)):
                return urlunsplit((url.scheme, url.hostname or "", url.path, "", ""))
            return match.group()

        return re.sub(r"https?://[^\s<>\"']+", clean_url, value)
    return value


def atomic(path, value, *, immutable=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            out.write(value)
            out.flush()
            os.fsync(out.fileno())
        if immutable:
            os.link(temporary, path)
        else:
            os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--archive-root", required=True, type=Path)
    p.add_argument("--provider", action="append", choices=PROVIDERS, required=True)
    p.add_argument("--query", action="append", default=[], help="PROVIDER=literal query; repeatable")
    p.add_argument("--collection", action="append", default=[], help="zsxq=ID or ima=ID; repeatable")
    p.add_argument("--category", action="append", choices=CATEGORIES, default=[])
    p.add_argument("--ima-include-notes", action="store_true")
    p.add_argument("--zsxq-timeline-export", action="store_true",
                   help="Archive every bounded ZSXQ timeline record; requires explicit ZSXQ collections")
    p.add_argument("--start", type=dt.date.fromisoformat)
    p.add_argument("--end", type=dt.date.fromisoformat)
    p.add_argument("--slice-days", type=int, default=1)
    p.add_argument("--candidates", type=int, default=50)
    p.add_argument("--text-reads", type=int, default=10)
    p.add_argument("--max-chars", type=int, default=50000)
    p.add_argument("--max-pages", type=int, default=3, help="Per job per invocation")
    p.add_argument("--max-jobs", type=int, default=30)
    p.add_argument("--max-requests", type=int, default=100, help="SDK calls, not upstream HTTP calls")
    p.add_argument("--timeout", type=float, default=60)
    p.add_argument("--operations", type=int, default=100)
    p.add_argument("--interval", type=float, default=1)
    p.add_argument("--retrieve-details", action="store_true")
    p.add_argument("--execute", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    return p


def make_jobs(args):
    if bool(args.start) != bool(args.end):
        raise ValueError("Provide both --start and --end")
    end = args.end or dt.datetime.now(TZ).date() - dt.timedelta(days=1)
    start = args.start or end - dt.timedelta(days=364)
    if start > end or end == dt.date.max:
        raise ValueError("Invalid date range")
    for name, lo, hi in (("slice_days", 1, 367), ("candidates", 1, 50), ("text_reads", 0, 10), ("max_chars", 1, 50000), ("max_pages", 1, 1000), ("max_jobs", 1, 100000), ("max_requests", 1, 100000), ("operations", 1, 100)):
        if not lo <= getattr(args, name) <= hi:
            raise ValueError("Invalid " + name)
    if not 0 < args.timeout <= 300 or not 0 <= args.interval <= 60:
        raise ValueError("Invalid timeout or interval")
    selected = list(dict.fromkeys(args.provider))
    queries = {p: [] for p in selected}
    collections = {p: [] for p in selected}
    for entries, destination in ((args.query, queries), (args.collection, collections)):
        for entry in entries:
            provider, sep, value = entry.partition("=")
            if not sep or provider not in selected or not value.strip():
                raise ValueError("Scope requires selected PROVIDER=value")
            if value not in destination[provider]:
                destination[provider].append(value)
    if args.category and "wisburg" not in selected or args.ima_include_notes and "ima" not in selected:
        raise ValueError("Options refer to an unselected provider")
    if args.zsxq_timeline_export and "zsxq" not in selected:
        raise ValueError("ZSXQ timeline export requires provider zsxq")
    if args.zsxq_timeline_export and queries.get("zsxq"):
        raise ValueError("Do not combine ZSXQ timeline export with a ZSXQ query")
    if args.zsxq_timeline_export and (not args.text_reads or args.candidates > args.text_reads):
        raise ValueError("ZSXQ timeline export requires 1 <= candidates <= text-reads for per-record detail reads")
    if collections.get("wisburg"):
        raise ValueError("Use --category for wisburg")
    jobs = []
    for provider in selected:
        if provider == "zsxq" and args.zsxq_timeline_export:
            queries[provider] = ["知识星球时间线归档"]
        if not queries[provider] or any(len(q) > 100 for q in queries[provider]):
            raise ValueError("Each provider needs literal queries of at most 100 characters")
        scopes = list(dict.fromkeys(args.category)) if provider == "wisburg" else collections[provider][:]
        if not scopes:
            raise ValueError("Explicit collections/categories required for " + provider)
        for scope in scopes:
            if provider == "zsxq" and not re.fullmatch(r"[1-9][0-9]{0,29}", scope):
                raise ValueError("Invalid star ID")
            if provider == "ima" and scope is not None and not re.fullmatch(r"[A-Za-z0-9_+=.-]{1,512}", scope):
                raise ValueError("Invalid IMA knowledge-base ID")
            for query in queries[provider]:
                current = start
                while current <= end:
                    finish = min(end, current + dt.timedelta(days=args.slice_days - 1))
                    job = {"provider": provider, "query": query, "scope": scope, "start": current.isoformat(), "end": finish.isoformat(), "candidates": args.candidates, "text_reads": args.text_reads, "max_chars": args.max_chars, "retrieve_details": args.retrieve_details, "ima_include_notes": provider == "ima" and args.ima_include_notes, "zsxq_timeline_export": provider == "zsxq" and args.zsxq_timeline_export, "schema": 1}
                    jobs.append(dict(job, id=digest(job)))
                    current = finish + dt.timedelta(days=1)
    return jobs


def request_for(job, cursors):
    timeline = job.get("zsxq_timeline_export", False)
    request = dict(question=job["query"], keywords=[] if timeline else [job["query"]], providers=[job["provider"]], published_start=job["start"], published_end=job["end"], limit=job["candidates"], candidates_per_source=job["candidates"], text_reads_per_source=job["text_reads"], max_chars=job["max_chars"], source_cursors=cursors)
    if job["provider"] == "zsxq":
        request["zsxq_group_ids"] = [job["scope"]]
        request["zsxq_timeline_export"] = timeline
    elif job["provider"] == "wisburg":
        request["wisburg_categories"] = [job["scope"]]
    else:
        request.update(ima_knowledge_base_ids=[job["scope"]], ima_include_notes=job["ima_include_notes"])
    return request


class SDKRunner:
    def __init__(self, args):
        self.sdk = importlib.import_module("ir_search")
        self.args = args

    def __call__(self, kind, request):
        cls = self.sdk.MaterialSearchRequest if kind == "search" else self.sdk.MaterialRequest
        context = self.sdk.RequestContext(timeout_seconds=self.args.timeout, max_operations=self.args.operations)
        function = self.sdk.search_materials if kind == "search" else self.sdk.retrieve
        return function(cls(**request), context=context).to_dict()


class BudgetReached(Exception):
    pass


def failed(result):
    if result.get("required_inputs") or result.get("status") in {"unavailable", "error", "failed"}:
        return True
    return any(row.get("state") in {"source_queries_failed", "not_registered", "disabled", "failed"} for row in result.get("coverage", []))


def collection_scoped_failure(result):
    """Allow another explicit collection after a failure known to be collection-local."""
    codes = {row.get("code") for row in result.get("diagnostics", [])}
    provider_wide = {"authentication_failed", "rate_limit", "timeout", "network", "tls_error", "request_cancelled"}
    return bool(codes & {"entitlement_denied", "not_found", "upstream_schema"}) and not codes & provider_wide


def publication(version):
    instant = version.get("published_at")
    warnings = []
    if instant:
        try:
            timestamp = dt.datetime.fromisoformat(instant.replace("Z", "+00:00"))
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=TZ)
                warnings.append("publication_timezone_assumed_asia_shanghai")
            return timestamp.astimezone(TZ).date().isoformat(), warnings
        except (TypeError, ValueError):
            warnings.append("invalid_publication_timestamp")
    if version.get("published_on"):
        try:
            return dt.date.fromisoformat(version["published_on"]).isoformat(), warnings
        except (TypeError, ValueError):
            warnings.append("invalid_publication_date")
    return None, warnings + ["publication_date_unknown"]


def merge_detail(version, material):
    """Preserve search identity and never apply old evidence offsets to new text."""
    merged = dict(version)
    merged["detail_result"] = material
    merged["warnings"] = list(dict.fromkeys(version.get("warnings", []) + material.get("warnings", [])))
    if not material.get("text"):
        merged["warnings"].append("detail_returned_no_text")
        return merged
    for key in ("text", "sections", "read_details", "text_provider", "provenance", "evidence_spans"):
        if material.get(key) is not None:
            merged[key] = material[key]
    # An empty attachment array in generic retrieval does not mean none existed.
    if material.get("attachments"):
        merged["attachments"] = material["attachments"]
    merged["evidence_spans"] = material.get("evidence_spans", [])
    for key in ("content_hash", "version_id", "match"):
        merged.pop(key, None)
    origin = material.get("text_origin")
    scope = material.get("read_details", {}).get("text_scope")
    if scope in {"metadata", "abstract", "search_snippet", "source_excerpt", "extracted_text"}:
        merged["text_scope"] = scope
    elif origin in {"abstract", "provider_summary"}:
        merged["text_scope"] = "abstract"
    elif origin in {"extracted_text", "search_snippet", "source_excerpt"}:
        merged["text_scope"] = origin
    else:
        merged["text_scope"] = "source_excerpt"
        merged["warnings"].append("detail_text_scope_unverified")
    if not merged.get("published_at") and material.get("published_at"):
        merged["published_at"] = material["published_at"]
    return merged


class Archive:
    def __init__(self, root):
        self.root = root
        (root / "index").mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(root / "index/archive.sqlite")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS metadata(version INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, provider TEXT, state TEXT, payload TEXT);
        CREATE TABLE IF NOT EXISTS records(provider TEXT, ref TEXT, hash TEXT, day TEXT, payload TEXT,
          PRIMARY KEY(provider, ref, hash));
        """)
        versions = self.db.execute("SELECT version FROM metadata").fetchall()
        if not versions:
            self.db.execute("INSERT INTO metadata VALUES(1)")
        elif versions != [(1,)]:
            raise ValueError("Unsupported archive schema")
        self.db.commit()

    def state(self, job):
        row = self.db.execute("SELECT payload FROM jobs WHERE id=?", (job["id"],)).fetchone()
        return json.loads(row[0]) if row else {"job": job, "cursors": [], "seen": [], "state": "pending", "pages": 0, "coverage_complete": False}

    def save_state(self, job, state):
        self.db.execute("INSERT OR REPLACE INTO jobs VALUES(?,?,?,?)", (job["id"], job["provider"], state["state"], encoded(state)))
        self.db.commit()

    def add(self, job, version, raw_path, fetched_at):
        ref = version.get("source_ref")
        if not isinstance(ref, str) or not ref.startswith(job["provider"] + "://"):
            raise ValueError("Missing or mismatched stable source reference")
        day, warnings = publication(version)
        if day is not None and not job["start"] <= day <= job["end"]:
            return False
        semantic = {k: version.get(k) for k in ("title", "authors", "published_at", "published_on", "text", "text_scope", "attachments", "collection_id", "source_created_at", "source_updated_at")}
        sha = digest(semantic)
        count = self.db.execute("SELECT COUNT(*) FROM records WHERE provider=? AND ref=?", (job["provider"], ref)).fetchone()[0]
        record = {"source": job["provider"], "source_item_id": ref, "source_collection": version.get("collection_id"), "title": version.get("title"), "authors": version.get("authors", []), "published_at": version.get("published_at"), "published_on": version.get("published_on"), "local_date": day, "fetched_at": fetched_at, "content_text": version.get("text", ""), "text_scope": version.get("text_scope", "metadata"), "content_sha256": sha, "version": count + 1, "raw_path": raw_path, "attachments": version.get("attachments", []), "attachment_paths": [], "warnings": warnings, "source_metadata": version}
        changed = self.db.execute("INSERT OR IGNORE INTO records VALUES(?,?,?,?,?)", (job["provider"], ref, sha, day or "unknown", encoded(record))).rowcount
        self.db.commit()
        return bool(changed)

    def views(self):
        for day, provider in self.db.execute("SELECT DISTINCT day,provider FROM records"):
            rows = self.db.execute("SELECT payload FROM records WHERE day=? AND provider=? ORDER BY ref,hash", (day, provider)).fetchall()
            atomic(self.root / "daily" / day / provider / "records.jsonl", "".join(row[0] + "\n" for row in rows))
        for provider, in self.db.execute("SELECT DISTINCT provider FROM jobs"):
            states = {row[0]: json.loads(row[1]) for row in self.db.execute("SELECT id,payload FROM jobs WHERE provider=? ORDER BY id", (provider,))}
            atomic(self.root / "checkpoints" / (provider + ".json"), encoded({"schema_version": 1, "coverage_complete": False, "jobs": states}) + "\n")
        daily_jobs = {}
        for provider, payload in self.db.execute("SELECT provider,payload FROM jobs"):
            state = json.loads(payload)
            job = state["job"]
            day = dt.date.fromisoformat(job["start"])
            end = dt.date.fromisoformat(job["end"])
            while day <= end:
                key = (day.isoformat(), provider)
                daily_jobs.setdefault(key, []).append({"job_id": job["id"], "state": state["state"], "stop_reason": state.get("stop_reason"), "coverage_complete": False})
                day += dt.timedelta(days=1)
        for (day, provider), jobs in daily_jobs.items():
            count = self.db.execute("SELECT COUNT(*) FROM records WHERE day=? AND provider=?", (day, provider)).fetchone()[0]
            atomic(self.root / "daily" / day / provider / "manifest.json", encoded({"date": day, "provider": provider, "record_versions": count, "coverage_complete": False, "jobs": jobs}) + "\n")


def execute(args, jobs, runner=None):
    root = args.archive_root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (root / ".writer.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        archive = Archive(root)
        for job in jobs:
            state = archive.state(job)
            archive.db.execute("INSERT OR IGNORE INTO jobs VALUES(?,?,?,?)", (job["id"], job["provider"], state["state"], encoded(state)))
        archive.db.commit()
        run_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
        run_dir = root / "runs" / run_id
        run_dir.mkdir(parents=True)
        timeline = any(job.get("zsxq_timeline_export") for job in jobs)
        summary = {"schema_version": 1, "run_id": run_id, "started_at": now(), "coverage_complete": False, "coverage_basis": "bounded_zsxq_timeline" if timeline else "bounded_literal_query_search", "sdk_calls": 0, "records_added": 0, "errors": 0, "jobs_selected": len(jobs)}
        atomic(run_dir / "manifest.json", encoded(summary) + "\n")
        errors = (run_dir / "errors.jsonl").open("a", encoding="utf-8")
        remaining = [args.max_requests]
        last_call = [None]
        client = [runner]

        def error(job, code):
            summary["errors"] += 1
            errors.write(encoded({"time": now(), "provider": job["provider"], "job_id": job["id"], "code": code}) + "\n")
            errors.flush()

        def call(job, kind, request):
            signature = digest({"kind": kind, "request": request})
            base = root / "raw" / job["provider"] / job["start"] / job["id"]
            attempts = sorted(base.glob(signature + "-*.jsonl")) if base.exists() else []
            for path in attempts:
                envelope = json.loads(path.read_text(encoding="utf-8"))
                if not failed(envelope["response"]) and (kind != "retrieve" or envelope["response"].get("materials")):
                    return envelope, str(path.relative_to(root))
            if remaining[0] <= 0:
                raise BudgetReached()
            if client[0] is None:
                client[0] = SDKRunner(args)
            if last_call[0] is not None:
                time.sleep(max(0, args.interval - (time.monotonic() - last_call[0])))
            remaining[0] -= 1
            summary["sdk_calls"] += 1
            try:
                result = sanitize(client[0](kind, request))
            finally:
                last_call[0] = time.monotonic()
            envelope = {"schema_version": 1, "kind": kind, "request": sanitize(request), "fetched_at": now(), "response": result}
            path = base / (signature + "-" + uuid.uuid4().hex + ".jsonl")
            atomic(path, encoded(envelope) + "\n", immutable=True)
            return envelope, str(path.relative_to(root))

        try:
            attempted = 0
            failed_providers = set()
            for job in jobs:
                state = archive.state(job)
                if state["state"] == "attempted" or job["provider"] in failed_providers:
                    continue
                if attempted >= args.max_jobs:
                    break
                attempted += 1
                try:
                    for _ in range(args.max_pages):
                        response, raw_path = call(job, "search", request_for(job, state["cursors"]))
                        result = response["response"]
                        state["coverage"] = result.get("coverage", [])
                        state["diagnostics"] = result.get("diagnostics", [])
                        state["gaps"] = result.get("gaps", [])
                        if failed(result):
                            state["state"] = "failed"
                            if not collection_scoped_failure(result):
                                failed_providers.add(job["provider"])
                            error(job, "search_failed_see_raw_diagnostics")
                            archive.save_state(job, state)
                            break
                        detail_failed = False
                        for item in result.get("items", []):
                            for version in item.get("versions", []):
                                summary["records_added"] += archive.add(job, version, raw_path, response["fetched_at"])
                                if not job["retrieve_details"]:
                                    continue
                                detail, detail_path = call(job, "retrieve", {"question": job["query"], "urls": [version["source_ref"]], "max_chars": job["max_chars"]})
                                materials = detail["response"].get("materials", [])
                                if failed(detail["response"]) or not materials:
                                    error(job, "detail_failed_see_raw_diagnostics")
                                    detail_failed = True
                                    continue
                                for material in materials:
                                    merged = merge_detail(version, material)
                                    summary["records_added"] += archive.add(job, merged, detail_path, detail["fetched_at"])
                        if detail_failed:
                            state["state"] = "failed"
                            failed_providers.add(job["provider"])
                            archive.save_state(job, state)
                            break
                        tokens = list(dict.fromkeys(token for row in result.get("coverage", []) for token in row.get("continuation_cursors", [])))
                        signature = digest(tokens)
                        state["pages"] += 1
                        if tokens and (tokens == state["cursors"] or signature in state["seen"]):
                            state.update(state="attempted", stop_reason="cursor_stalled")
                            error(job, "cursor_stalled")
                        elif tokens:
                            state["cursors"] = tokens
                            state["seen"].append(signature)
                            state.update(state="pending", stop_reason="page_budget")
                        else:
                            state.update(state="attempted", stop_reason="no_public_continuation")
                        state["coverage_complete"] = False
                        archive.save_state(job, state)
                        if state["state"] == "attempted":
                            break
                except BudgetReached:
                    break
                except Exception as exc:
                    state.update(state="failed", exception_type=type(exc).__name__)
                    failed_providers.add(job["provider"])
                    error(job, "exception_" + type(exc).__name__)
                    archive.save_state(job, state)
            summary["jobs_attempted_this_run"] = attempted
        finally:
            archive.views()
            states = [archive.state(job)["state"] for job in jobs]
            summary.update(finished_at=now(), jobs_attempted=states.count("attempted"), jobs_failed=states.count("failed"), jobs_remaining=len(states) - states.count("attempted"), all_jobs_attempted=all(s == "attempted" for s in states), records_total=archive.db.execute("SELECT COUNT(*) FROM records").fetchone()[0], undated_records=archive.db.execute("SELECT COUNT(*) FROM records WHERE day='unknown'").fetchone()[0])
            atomic(run_dir / "manifest.json", encoded(summary) + "\n")
            errors.close()
            archive.db.close()
        return dict(summary, manifest=str(run_dir / "manifest.json"))


def main(argv=None):
    p = parser()
    args = p.parse_args(argv)
    try:
        jobs = make_jobs(args)
        if args.dry_run or not args.execute:
            scope = "Bounded ZSXQ timeline archive" if args.zsxq_timeline_export else "Query-scoped archive"
            print(encoded({"mode": "dry_run", "archive_root": str(args.archive_root), "jobs": len(jobs), "first_job": jobs[0], "last_job": jobs[-1], "providers": list(dict.fromkeys(args.provider)), "max_sdk_calls": args.max_requests, "coverage_complete": False, "notes": scope + "; no network or filesystem writes."}))
            return 0
        result = execute(args, jobs)
        print(encoded(result))
        return 0 if result["all_jobs_attempted"] and not result["errors"] else 2
    except (ValueError, OSError, ImportError) as exc:
        print(encoded({"error": type(exc).__name__, "message": "Invalid scope, missing SDK, busy archive, or local I/O failure; check inputs and environment."}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
