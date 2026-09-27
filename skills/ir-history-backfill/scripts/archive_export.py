#!/usr/bin/env python3
"""Full-enumeration archival export via the public ir_search collection-export API.

Keyword-free export mode (``mode: "export"``) complements the keyword-scoped
``download_history.py`` jobs. Job = provider x collection x date slice; the job id
is the SHA-256 of the normalized job dict and can never collide with keyword jobs
because the schema field ``mode: "export"`` is part of the digest. Default is a
no-I/O execution preview.

Provider capability boundaries (frozen in ir_archive/capability-matrix.json,
audited 2026-09-25; keep code comments in sync with it):
- zsxq: full enumeration supported; comments paginate but the upstream API never
  embeds nested replies (diagnostic nested_replies_not_provided); attachment bytes
  downloadable via retrieve_asset (zsxq://file/...); original image download is NOT
  provided upstream, so images stay metadata-only (manifest status unsupported).
- ima: keywordless enumeration is NOT supported upstream (empty search_knowledge
  query live-verified to return zero items) and notes require a keyword, so export
  mode archives the knowledge-base directory snapshot plus whatever dated records
  appear, files everything under daily/unknown, marks
  provider_full_export_supported=false and records the gaps. A keyword matrix must
  never be used to pretend full coverage. ima timeline items do not expose
  attachment descriptors; original-file bytes need keyword-search refs.
- wisburg: full enumeration supported; reports are supplier-stored summaries
  (text_scope=abstract, original_document_available=false must be preserved);
  original files and images are not provided upstream (retrieve_asset returns
  unsupported; never faked here).
"""
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

import download_history as base

TZ = base.TZ
PROVIDERS = base.PROVIDERS
CATEGORY_CHOICES = base.CATEGORIES
encoded = base.encoded
digest = base.digest
now = base.now
sanitize = base.sanitize
atomic = base.atomic
publication = base.publication
BudgetReached = base.BudgetReached
Archive = base.Archive

MODE = "export"
SCHEMA = 1
SIZE_GUARD_BYTES = 20 * 1024 * 1024 * 1024  # cumulative objects/ volume guard
PROVIDER_WIDE_CODES = {"authentication_failed", "rate_limit", "timeout", "network",
                       "tls_error", "request_cancelled"}
COLLECTION_SCOPED_CODES = {"entitlement_denied", "not_registered", "disabled",
                           "not_found", "upstream_schema"}
# Deterministic permission facts (ir_search reports e.g. coverage.state
# "upstream_stopped" with an entitlement_denied diagnostic): terminal, never retried.
DENIED_CODES = {"entitlement_denied", "not_registered", "disabled"}
DENIED_STOP_REASONS = {"denied", "entitlement_denied"}
HARD_COVERAGE_STATES = {"upstream_stopped", "stopped"}
# Deterministic asset failure reasons: persisted asset_refs rows with status in
# {failed, unsupported} whose reason is in this set are terminal — later runs skip
# them without an SDK call, mark the manifest already_terminal, count them resolved,
# and never re-count them. Anything else (rate_limit, network, timeout,
# upstream_schema, unknown ...) stays retryable.
TERMINAL_REASONS = {
    "asset_exceeds_max_bytes",
    "unsupported",
    "original_files_unsupported",
    "upstream_does_not_provide_original_files",
    "original_image_download_not_provided_upstream",
    "empty_content",
    "asset_object_missing_after_replay",
    "pdf_magic_mismatch",
    "invalid_asset_ref",
    "not_a_file_ref",
    "unsupported_asset_ref",
    "attachment_not_found_in_topic",
    "notes_do_not_provide_file_bytes",
    "ima_media_type_not_exportable",
    "public_web_original_not_exported_as_bytes",
    "web_content_unsupported",
    "ima_original_unavailable",
    "blocked_url",
}
# capability-matrix.json (2026-09-25): ima keywordless enumeration unsupported.
PROVIDER_FULL_EXPORT_SUPPORTED = {"zsxq": True, "ima": False, "wisburg": True}
ORIGINAL_IMAGE_DOWNLOAD = "original_image_download_not_provided_upstream"
ORIGINAL_FILES_UNSUPPORTED = "upstream_does_not_provide_original_files"
IMA_EXPORT_GAPS = [
    {"code": "keywordless_enumeration_not_supported",
     "detail": "ima search_knowledge with an empty query returns zero items upstream; "
               "export_collection_timeline cannot enumerate knowledge-base contents without keywords."},
    {"code": "notes_enumeration_requires_keyword",
     "detail": "ima search_note requires 1-1000 character content; keywordless notes "
               "enumeration is rejected before network."},
    {"code": "publication_dates_not_provided",
     "detail": "ima records carry no reliable publication dates; records are filed under daily/unknown."},
    {"code": "attachment_refs_not_exposed",
     "detail": "ima timeline items expose no attachment descriptors; original-file bytes "
               "require keyword-search refs (retrieve_asset ima://media/...)."},
]
SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
SHA256_HEX = re.compile(r"[0-9a-f]{64}")


class RateLimitStopped(Exception):
    pass


class CommentsHardFail(Exception):
    pass


class AssetBudgetReached(Exception):
    pass


def safe_name(value, limit=120):
    cleaned = SAFE_NAME.sub("_", str(value)).strip("._")
    return (cleaned or "unnamed")[:limit]


def export_failed(result):
    """A hard-failed export response: kept in raw, never replayed, retried next run."""
    if not isinstance(result, dict):
        return True
    if result.get("required_inputs") or result.get("status") in {"unavailable", "error", "failed"}:
        return True
    if (result.get("coverage") or {}).get("state") in HARD_COVERAGE_STATES:
        return True
    codes = {row.get("code") for row in result.get("diagnostics", []) if isinstance(row, dict)}
    return bool(codes & {"entitlement_denied", "authentication_failed", "invalid_cursor"})


def rate_limited(result):
    codes = {row.get("code") for row in (result or {}).get("diagnostics", []) if isinstance(row, dict)}
    return "rate_limit" in codes or (result.get("coverage") or {}).get("state") in HARD_COVERAGE_STATES


def collection_scoped_failure(result):
    codes = {row.get("code") for row in (result or {}).get("diagnostics", []) if isinstance(row, dict)}
    return bool(codes & COLLECTION_SCOPED_CODES) and not codes & PROVIDER_WIDE_CODES


def collection_denied(result):
    """Terminal permission fact: an entitlement-family diagnostic without any
    provider-wide code. The canonical upstream shape is coverage.state
    "upstream_stopped" plus an entitlement_denied diagnostic; variants such as
    not_registered/disabled mean the same for retry purposes, so they are all
    terminal rather than run errors."""
    codes = {row.get("code") for row in (result or {}).get("diagnostics", []) if isinstance(row, dict)}
    return bool(codes & DENIED_CODES) and not codes & PROVIDER_WIDE_CODES


def export_media_type(attachment, response=None):
    label = (response or {}).get("media_type") or attachment.get("media_type") or ""
    if label == "pdf" or label == "application/pdf":
        return "application/pdf"
    if "/" in str(label):
        return str(label)
    return "application/octet-stream"


def objects_disk_total(root):
    total = 0
    directory = root / "objects"
    if not directory.exists():
        return 0
    for prefix in directory.iterdir():
        if not prefix.is_dir() or len(prefix.name) != 2:
            continue
        for path in prefix.iterdir():
            if path.is_file() and SHA256_HEX.fullmatch(path.name):
                total += path.stat().st_size
    return total


def store_object(root, content, media_type):
    """Content-addressed, atomic: same SHA is stored exactly once."""
    sha = hashlib.sha256(content).hexdigest()
    relative = Path("objects") / sha[:2] / sha
    final = root / relative
    if not final.exists():
        final.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".pending-", dir=final.parent)
        try:
            with os.fdopen(fd, "wb") as out:
                out.write(content)
                out.flush()
                os.fsync(out.fileno())
            os.replace(temporary, final)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return sha, str(relative)


class ExportArchive(Archive):
    """Extends the keyword-archive schema with objects/asset_refs tables and
    export-flavored records; jobs/records semantics for old keyword jobs are
    untouched (new tables only, CREATE TABLE IF NOT EXISTS)."""

    def __init__(self, root):
        super().__init__(root)
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS objects(sha TEXT PRIMARY KEY, path TEXT, size INTEGER,
          media_type TEXT, first_seen TEXT);
        CREATE TABLE IF NOT EXISTS asset_refs(provider TEXT, collection_id TEXT, item_ref TEXT,
          asset_ref TEXT, sha TEXT, status TEXT, reason TEXT,
          PRIMARY KEY(provider, item_ref, asset_ref));
        """)
        self.db.commit()

    def state(self, job):
        row = self.db.execute("SELECT payload FROM jobs WHERE id=?", (job["id"],)).fetchone()
        if row:
            return json.loads(row[0])
        return {"job": job, "state": "pending", "cursor": None, "seen": [], "pages": 0,
                "enum_state": "pending", "coverage": None, "diagnostics": [], "gaps": [],
                "topic_refs": [], "topic_days": {}, "comments": {}, "assets": {},
                "stop_reason": None, "coverage_complete": False}

    def export_collections(self, provider):
        found = set()
        for payload, in self.db.execute("SELECT payload FROM jobs WHERE provider=?", (provider,)):
            try:
                job = json.loads(payload).get("job") or {}
            except json.JSONDecodeError:
                continue
            if job.get("mode") == MODE and job.get("collection"):
                found.add(job["collection"])
        return found

    def add_export(self, job, item, raw_path, fetched_at, day, warnings):
        provider = job["provider"]
        ref = item.get("ref")
        if not isinstance(ref, str) or not ref.startswith(provider + "://"):
            raise ValueError("Missing or mismatched stable source reference")
        if day is not None and not job["start"] <= day <= job["end"]:
            return False
        semantic = {k: item.get(k) for k in ("title", "authors", "published_at", "published_on",
                                             "text", "text_scope", "attachments", "collection_id")}
        semantic.update(published_on=None, source_created_at=item.get("created_at"),
                        source_updated_at=item.get("modified_at") or item.get("updated_at"))
        sha = digest(semantic)
        count = self.db.execute("SELECT COUNT(*) FROM records WHERE provider=? AND ref=?",
                                (provider, ref)).fetchone()[0]
        attachments = []
        for attachment in item.get("attachments") or []:
            attachments.append({"asset_ref": attachment.get("source_ref"),
                                "original_filename": attachment.get("name"),
                                "media_type": export_media_type(attachment),
                                "size_bytes": attachment.get("size_bytes"),
                                "status": "metadata_only"})
        text = item.get("text")
        summary_text = item.get("summary")
        scope = item.get("text_scope")
        if not text and summary_text:
            text, scope = summary_text, (scope or "abstract")
        record = {"source": provider, "source_item_id": ref,
                  "source_collection": item.get("collection_id"), "title": item.get("title"),
                  "authors": item.get("authors") or [], "published_at": item.get("published_at"),
                  "published_on": None, "local_date": day, "fetched_at": fetched_at,
                  "content_text": text or "", "text_scope": scope or "metadata",
                  "content_sha256": sha, "version": count + 1, "raw_path": raw_path,
                  "attachments": attachments, "attachment_paths": [],
                  "warnings": list(warnings) + list(item.get("warnings") or []),
                  "source_metadata": item,
                  "record_type": item.get("type"), "labels": list(item.get("labels") or []),
                  "like_count": item.get("like_count"),
                  "comments_count": item.get("comments_count"),
                  "original_document_available": item.get("original_document_available"),
                  "images": list(item.get("images") or []), "comments_fetched": False,
                  "comments_nested": None, "coverage_complete": False,
                  "asset_manifest": None}
        changed = self.db.execute("INSERT OR IGNORE INTO records VALUES(?,?,?,?,?)",
                                  (provider, ref, sha, day or "unknown", encoded(record))).rowcount
        self.db.commit()
        return bool(changed)

    def update_export_records(self, provider, ref, mutator):
        rows = self.db.execute("SELECT hash,payload FROM records WHERE provider=? AND ref=?",
                               (provider, ref)).fetchall()
        for sha, payload in rows:
            record = json.loads(payload)
            if "record_type" not in record:
                continue
            mutator(record)
            self.db.execute("UPDATE records SET payload=? WHERE provider=? AND ref=? AND hash=?",
                            (encoded(record), provider, ref, sha))
        self.db.commit()

    def latest_export_record(self, provider, ref):
        rows = self.db.execute("SELECT payload FROM records WHERE provider=? AND ref=?",
                               (provider, ref)).fetchall()
        records = [json.loads(payload) for payload, in rows]
        export_records = [record for record in records if "record_type" in record]
        return max(export_records, key=lambda record: record.get("version", 0), default=None)

    def asset_ref_row(self, provider, item_ref, asset_ref):
        row = self.db.execute(
            "SELECT sha,status,reason FROM asset_refs WHERE provider=? AND item_ref=? AND asset_ref=?",
            (provider, item_ref, asset_ref)).fetchone()
        return {"sha": row[0], "status": row[1], "reason": row[2]} if row else None

    def upsert_asset_ref(self, provider, collection_id, item_ref, asset_ref, sha, status, reason):
        self.db.execute("INSERT OR REPLACE INTO asset_refs VALUES(?,?,?,?,?,?,?)",
                        (provider, collection_id, item_ref, asset_ref, sha, status, reason))
        self.db.commit()

    def add_object(self, sha, path, size, media_type):
        self.db.execute("INSERT OR IGNORE INTO objects VALUES(?,?,?,?,?)",
                        (sha, path, size, media_type, now()))
        self.db.commit()

    def views(self):
        for day, provider in self.db.execute("SELECT DISTINCT day,provider FROM records"):
            rows = self.db.execute("SELECT payload FROM records WHERE day=? AND provider=? ORDER BY ref,hash",
                                   (day, provider)).fetchall()
            atomic(self.root / "daily" / day / provider / "records.jsonl",
                   "".join(row[0] + "\n" for row in rows))
        for provider, in self.db.execute("SELECT DISTINCT provider FROM jobs"):
            states = {row[0]: json.loads(row[1]) for row in
                      self.db.execute("SELECT id,payload FROM jobs WHERE provider=? ORDER BY id", (provider,))}
            atomic(self.root / "checkpoints" / (provider + ".json"),
                   encoded({"schema_version": 1, "coverage_complete": False, "jobs": states}) + "\n")
        daily_jobs = {}
        for provider, payload in self.db.execute("SELECT provider,payload FROM jobs"):
            state = json.loads(payload)
            job = state["job"]
            day = dt.date.fromisoformat(job["start"])
            end = dt.date.fromisoformat(job["end"])
            complete = bool(state.get("coverage_complete"))
            while day <= end:
                key = (day.isoformat(), provider)
                daily_jobs.setdefault(key, []).append({"job_id": job["id"], "state": state["state"],
                                                       "stop_reason": state.get("stop_reason"),
                                                       "coverage_complete": complete})
                day += dt.timedelta(days=1)
        for (day, provider), jobs in daily_jobs.items():
            count = self.db.execute("SELECT COUNT(*) FROM records WHERE day=? AND provider=?",
                                    (day, provider)).fetchone()[0]
            complete = bool(jobs) and all(job["coverage_complete"] for job in jobs)
            atomic(self.root / "daily" / day / provider / "manifest.json",
                   encoded({"date": day, "provider": provider, "record_versions": count,
                            "coverage_complete": complete, "jobs": jobs}) + "\n")


def parser():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--archive-root", required=True, type=Path)
    p.add_argument("--provider", required=True, choices=PROVIDERS)
    p.add_argument("--collections-from", type=Path,
                   help="subscription scan JSON; default <archive-root>/subscriptions/latest.json")
    p.add_argument("--collection", action="append", default=[], help="collection ID; repeatable, overrides the subscription scan")
    p.add_argument("--start", type=dt.date.fromisoformat)
    p.add_argument("--end", type=dt.date.fromisoformat)
    p.add_argument("--slice-days", type=int, default=3)
    p.add_argument("--max-items-per-call", type=int, default=100)
    p.add_argument("--max-topic-comments", type=int, default=200)
    p.add_argument("--max-assets", type=int, default=50, help="fresh asset downloads per job per invocation")
    p.add_argument("--max-comment-pages", type=int, default=5, help="comment pages per SDK call")
    p.add_argument("--asset-max-bytes", type=int, default=52428800)
    p.add_argument("--size-guard-bytes", type=int, default=SIZE_GUARD_BYTES,
                   help="cumulative objects/ byte budget; positive integer with no fixed upper ceiling")
    p.add_argument("--max-calls", type=int, default=20, help="SDK calls per invocation, not upstream HTTP calls")
    p.add_argument("--interval", type=float, default=3)
    p.add_argument("--timeout", type=float, default=60)
    p.add_argument("--operations", type=int, default=50)
    p.add_argument("--comments", action="store_true", help="fetch zsxq topic comments (default: off)")
    p.add_argument("--assets", action="store_true", help="download attachment bytes into objects/ (default: off)")
    p.add_argument("--stage", choices=("comments", "assets"),
                   help="run only this sub-task stage on existing jobs (replays completed "
                        "timelines from raw envelopes with zero timeline SDK calls); "
                        "cannot be combined with --comments/--assets")
    p.add_argument("--execute", action="store_true")
    return p


def validate_collection(provider, collection):
    if provider == "zsxq" and not re.fullmatch(r"[1-9][0-9]{0,29}", collection):
        raise ValueError("Invalid star ID")
    if provider == "ima" and not re.fullmatch(r"[A-Za-z0-9_+=.-]{1,512}", collection):
        raise ValueError("Invalid IMA knowledge-base ID")
    if provider == "wisburg" and collection not in CATEGORY_CHOICES:
        raise ValueError("Invalid Wisburg category")


def load_collections(args):
    explicit = list(dict.fromkeys(args.collection))
    if explicit:
        for collection in explicit:
            validate_collection(args.provider, collection)
        return explicit, None, {}
    path = (args.collections_from or (args.archive_root / "subscriptions" / "latest.json")).expanduser()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read subscription scan {path}: {exc}") from None
    section = data.get(args.provider) or {}
    key, id_key = {"zsxq": ("groups", "group_id"), "ima": ("knowledge_bases", "collection_id"),
                   "wisburg": ("categories", "category")}[args.provider]
    collections, names = [], {}
    for row in section.get(key) or []:
        if not isinstance(row, dict):
            continue
        collection = row.get(id_key)
        if not collection:
            continue
        collection = str(collection)
        validate_collection(args.provider, collection)
        if collection not in collections:
            collections.append(collection)
            names[collection] = row.get("name")
    return collections, str(path), names


def make_jobs(args):
    if args.stage and (args.comments or args.assets):
        raise ValueError("--stage cannot be combined with --comments/--assets")
    if bool(args.start) != bool(args.end):
        raise ValueError("Provide both --start and --end")
    end = args.end or dt.datetime.now(TZ).date() - dt.timedelta(days=1)
    start = args.start or end - dt.timedelta(days=364)
    if start > end or end == dt.date.max:
        raise ValueError("Invalid date range")
    for name, lo, hi in (("slice_days", 1, 367), ("max_items_per_call", 1, 1000),
                         ("max_topic_comments", 1, 5000), ("max_assets", 1, 10000),
                         ("max_comment_pages", 1, 50),
                         ("max_calls", 1, 100000), ("operations", 1, 100)):
        if not lo <= getattr(args, name) <= hi:
            raise ValueError("Invalid " + name)
    for name in ("asset_max_bytes", "size_guard_bytes"):
        if type(getattr(args, name)) is not int or getattr(args, name) < 1:
            raise ValueError("Invalid " + name)
    if not 0 < args.timeout <= 300 or not 0 <= args.interval <= 60:
        raise ValueError("Invalid timeout or interval")
    collections, source, names = load_collections(args)
    if not collections:
        raise ValueError("No collections resolved; check the subscription scan or pass --collection")
    jobs = []
    for collection in collections:
        current = start
        while current <= end:
            finish = min(end, current + dt.timedelta(days=args.slice_days - 1))
            job = {"provider": args.provider, "mode": MODE, "collection": collection,
                   "start": current.isoformat(), "end": finish.isoformat(), "schema": SCHEMA}
            jobs.append(dict(job, id=digest(job)))
            current = finish + dt.timedelta(days=1)
    return {"provider": args.provider, "jobs": jobs, "collections": collections,
            "collections_from": source, "collection_names": names}


class ExportSDKRunner:
    """Thin injectable wrapper around the four public collection-export entry points."""

    def __init__(self, args):
        self.sdk = importlib.import_module("ir_search")
        self.args = args

    def __call__(self, kind, request):
        context = self.sdk.RequestContext(timeout_seconds=self.args.timeout,
                                          max_operations=self.args.operations)
        parameters = {k: v for k, v in request.items() if k != "kind"}
        if kind == "timeline":
            return self.sdk.export_collection_timeline(context=context, **parameters)
        if kind == "comments":
            return self.sdk.list_topic_comments(context=context, **parameters)
        if kind == "asset":
            return self.sdk.retrieve_asset(context=context, **parameters)
        raise ValueError("Unknown export call kind: " + kind)


def timeline_request(job, cursor, args):
    return {"kind": "timeline", "provider": job["provider"], "collection_id": job["collection"],
            "published_start": job["start"], "published_end": job["end"], "cursor": cursor,
            "include_text": True, "include_notes": False, "max_items": args.max_items_per_call}


def comments_request(ref, cursor, args):
    return {"kind": "comments", "provider": "zsxq", "ref": ref, "cursor": cursor,
            "per_page": 30, "max_pages": args.max_comment_pages}


def asset_request(asset_ref, args):
    return {"kind": "asset", "asset_ref": asset_ref, "max_bytes": args.asset_max_bytes}


def execute(args, planned, runner=None):
    root = args.archive_root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (root / ".writer.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        archive = ExportArchive(root)
        jobs = planned["jobs"]
        provider = planned["provider"]
        for job in jobs:
            state = archive.state(job)
            archive.db.execute("INSERT OR IGNORE INTO jobs VALUES(?,?,?,?)",
                               (job["id"], job["provider"], state["state"], encoded(state)))
        archive.db.commit()
        run_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
        run_dir = root / "runs" / run_id
        run_dir.mkdir(parents=True)
        summary = {"schema_version": 1, "run_id": run_id, "started_at": now(), "mode": MODE,
                   "provider": provider, "coverage_complete": False,
                   "coverage_basis": "ima_directory_snapshot_not_full_export" if provider == "ima"
                                     else "full_enumeration_collection_export",
                   "sdk_calls": 0, "records_added": 0, "errors": 0, "jobs_selected": len(jobs),
                   "collections": planned["collections"],
                   "collections_from": planned.get("collections_from"),
                   "collections_missing": sorted(archive.export_collections(provider) -
                                                 set(planned["collections"])),
                   "provider_full_export_supported": PROVIDER_FULL_EXPORT_SUPPORTED[provider],
                   "assets_downloaded": 0, "assets_failed": 0, "assets_bytes": 0,
                   "comments_topics_done": 0, "comments_fetched": 0, "diagnostics": []}
        if args.stage:
            # Effective sub-task flags: a stage run performs only that stage
            # (enumeration still completes first for pending jobs; jobs whose
            # timeline is already attempted replay zero timeline SDK calls).
            args.comments = args.stage == "comments"
            args.assets = args.stage == "assets"
            summary["stage"] = args.stage
        if provider == "ima":
            summary["gaps"] = IMA_EXPORT_GAPS
            summary["diagnostics"].extend(dict(code=gap["code"], provider=provider) for gap in IMA_EXPORT_GAPS)
            snapshot = {"provider": "ima", "written_at": now(),
                        "collections_from": planned.get("collections_from"),
                        "provider_full_export_supported": False, "gaps": IMA_EXPORT_GAPS,
                        "knowledge_bases": [{"collection_id": collection,
                                             "name": (planned["collection_names"] or {}).get(collection)}
                                            for collection in planned["collections"]]}
            atomic(root / "daily" / "unknown" / "ima" / "knowledge_bases.json", encoded(snapshot) + "\n")
        atomic(run_dir / "manifest.json", encoded(summary) + "\n")
        errors = (run_dir / "errors.jsonl").open("a", encoding="utf-8")
        remaining = [args.max_calls]
        last_call = [None]
        client = [runner]
        fresh_content = {}
        objects_total = [objects_disk_total(root)]
        size_guard = [False]
        assets_used = [0]
        attempted = [0]
        failed_providers = set()
        noted_unsupported_comments = set()

        def error(job, code):
            summary["errors"] += 1
            errors.write(encoded({"time": now(), "provider": job["provider"],
                                  "job_id": job["id"], "code": code}) + "\n")
            errors.flush()

        def trip_size_guard():
            if not size_guard[0]:
                size_guard[0] = True
                summary["size_guard_tripped"] = True
                summary["diagnostics"].append({"code": "size_guard_tripped", "provider": provider})

        def call(job, kind, request):
            signature = digest({"kind": kind, "request": request})
            base_dir = root / "raw" / job["provider"] / job["start"] / job["id"]
            attempts = sorted(base_dir.glob(signature + "-*.jsonl")) if base_dir.exists() else []
            for path in attempts:
                envelope = json.loads(path.read_text(encoding="utf-8"))
                response = envelope["response"]
                # Asset envelopes replay only when the bytes actually arrived; a
                # failed/metadata_only/unsupported asset response (e.g. rate_limit,
                # response_too_large) must be re-requested, never silently replayed.
                if not export_failed(response) and (envelope.get("kind") != "asset"
                                                    or response.get("status") == "ok"):
                    return envelope, str(path.relative_to(root)), signature
            if remaining[0] <= 0:
                raise BudgetReached()
            if client[0] is None:
                client[0] = ExportSDKRunner(args)
            if last_call[0] is not None:
                time.sleep(max(0, args.interval - (time.monotonic() - last_call[0])))
            remaining[0] -= 1
            summary["sdk_calls"] += 1
            try:
                result = sanitize(client[0](kind, request))
            finally:
                last_call[0] = time.monotonic()
            if kind == "asset" and isinstance(result, dict):
                fresh_content[signature] = result.get("content")
                result = {k: v for k, v in result.items() if k != "content"}
            envelope = {"schema_version": 1, "kind": kind, "request": sanitize(request),
                        "fetched_at": now(), "response": result}
            path = base_dir / (signature + "-" + uuid.uuid4().hex + ".jsonl")
            atomic(path, encoded(envelope) + "\n", immutable=True)
            return envelope, str(path.relative_to(root)), signature

        def asset_entry(*, kind, asset_ref, status, source_record_ref, original_filename=None,
                        media_type=None, size_bytes=None, sha256=None, reason=None,
                        object_path=None, downloaded_at=None):
            return {"kind": kind, "asset_ref": asset_ref,
                    "original_filename": original_filename,
                    "safe_filename": safe_name(os.path.basename(str(original_filename)))
                                    if original_filename else None,
                    "media_type": media_type, "size_bytes": size_bytes, "sha256": sha256,
                    "source_record_ref": source_record_ref, "downloaded_at": downloaded_at,
                    "status": status, "reason": reason, "object_path": object_path}

        def fetch_comments(job, state, ref):
            cstate = state["comments"].setdefault(
                ref, {"state": "pending", "cursor": None, "pages": 0, "count": 0})
            if cstate["state"] == "done":
                return
            day = state["topic_days"].get(ref) or "unknown"
            path = root / "daily" / day / "zsxq" / "comments" / (safe_name(ref) + ".jsonl")
            comments = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
                        if line.strip()] if path.exists() else []
            seen_ids = {comment.get("comment_id") for comment in comments}
            nested = "not_observed"

            def persist():
                atomic(path, "".join(encoded(comment) + "\n" for comment in comments))
                cstate["count"] = len(comments)
                archive.update_export_records(
                    provider, ref,
                    lambda record: record.update(comments_fetched=len(comments),
                                                 comments_nested=nested))
                archive.save_state(job, state)

            while True:
                if len(comments) >= args.max_topic_comments:
                    cstate.update(state="done", stop_reason="comment_cap_reached")
                    summary["diagnostics"].append({"code": "comment_cap_reached", "ref": ref})
                    break
                request = comments_request(ref, cstate["cursor"], args)
                envelope, _, _ = call(job, "comments", request)
                result = envelope["response"]
                codes = {row.get("code") for row in result.get("diagnostics", []) if isinstance(row, dict)}
                if "nested_replies_not_provided" in codes:
                    nested = "not_provided_upstream"
                elif any(comment.get("replies") for comment in result.get("comments") or []):
                    nested = "provided"
                coverage_state = (result.get("coverage") or {}).get("state")
                if "rate_limit" in codes or coverage_state in HARD_COVERAGE_STATES:
                    cstate["cursor"] = result.get("continuation_cursor") or cstate["cursor"]
                    persist()
                    raise RateLimitStopped()
                if export_failed(result):
                    error(job, "comments_failed_see_raw_diagnostics")
                    archive.save_state(job, state)
                    raise CommentsHardFail()
                for comment in result.get("comments") or []:
                    marker = comment.get("comment_id")
                    if marker in seen_ids:
                        continue
                    seen_ids.add(marker)
                    comments.append(comment)
                cstate["pages"] += 1
                cursor = result.get("continuation_cursor")
                if coverage_state == "complete":
                    cstate.update(state="done", cursor=None)
                    persist()
                    break
                if coverage_state == "budget_exhausted" and cursor:
                    # SDK-side page budget for this call: keep paginating with the
                    # saved index; our own --max-calls budget bounds the loop.
                    if cursor != cstate["cursor"]:
                        cstate["cursor"] = cursor
                        persist()
                        continue
                    cstate.update(state="done", stop_reason="comments_continuation_missing")
                    summary["diagnostics"].append({"code": "comments_continuation_missing", "ref": ref})
                    persist()
                    break
                if cursor and cursor != cstate["cursor"]:
                    cstate["cursor"] = cursor
                    persist()
                    continue
                cstate.update(state="done", stop_reason="comments_continuation_missing")
                summary["diagnostics"].append({"code": "comments_continuation_missing", "ref": ref})
                persist()
                break
            if cstate["state"] != "done":
                persist()

        def fetch_assets(job, state, ref):
            record = archive.latest_export_record(provider, ref)
            metadata = (record or {}).get("source_metadata") or {}
            attachments = metadata.get("attachments") or []
            images = metadata.get("images") or []
            if not attachments and not images:
                return
            progress = state["assets"].setdefault(
                ref, {"total": len(attachments) + len(images), "resolved": 0})
            collection = job["collection"]
            manifest_rel = Path("assets") / provider / safe_name(collection) / safe_name(ref) / "manifest.json"
            manifest_path = root / manifest_rel
            entries, order = {}, []

            def put(key, entry):
                if key not in entries:
                    order.append(key)
                entries[key] = entry

            for attachment in attachments:
                asset_ref = attachment.get("source_ref")
                declared = attachment.get("size_bytes")
                if provider == "wisburg":
                    # capability-matrix: wisburg originals do not exist upstream
                    # (retrieve_asset would return unsupported without a call).
                    put(asset_ref, asset_entry(kind="attachment", asset_ref=asset_ref,
                                               status="unsupported", reason=ORIGINAL_FILES_UNSUPPORTED,
                                               source_record_ref=ref,
                                               original_filename=attachment.get("name"),
                                               media_type=export_media_type(attachment),
                                               size_bytes=declared))
                    archive.upsert_asset_ref(provider, collection, ref, asset_ref, None,
                                             "unsupported", ORIGINAL_FILES_UNSUPPORTED)
                    continue
                row = archive.asset_ref_row(provider, ref, asset_ref)
                if row and row["status"] == "ok":
                    put(asset_ref, asset_entry(
                        kind="attachment", asset_ref=asset_ref, status="skipped",
                        reason="already_archived", source_record_ref=ref,
                        original_filename=attachment.get("name"),
                        media_type=export_media_type(attachment), sha256=row["sha"],
                        object_path=str(Path("objects") / row["sha"][:2] / row["sha"])))
                    continue
                # Deterministic local precheck, zero SDK calls. This is the caller's
                # explicit per-file budget, not a provider or transport ceiling.
                if type(declared) is int and declared > args.asset_max_bytes:
                    precheck_reason = "asset_exceeds_max_bytes"
                else:
                    precheck_reason = None
                if precheck_reason:
                    # Persistence rule: the INSERT OR REPLACE below must run on every
                    # path that counts a fresh failure; when an identical failed row
                    # already exists the entry is restated as already_terminal and
                    # assets_failed is NOT incremented again.
                    prior = archive.asset_ref_row(provider, ref, asset_ref)
                    if prior and prior["status"] == "failed" and prior["reason"] == precheck_reason:
                        entry = asset_entry(kind="attachment", asset_ref=asset_ref,
                                            status="failed", reason="already_terminal",
                                            source_record_ref=ref,
                                            original_filename=attachment.get("name"),
                                            media_type=export_media_type(attachment),
                                            size_bytes=declared)
                        entry["declared_size"] = declared
                        entry["terminal_reason"] = precheck_reason
                        put(asset_ref, entry)
                        continue
                    archive.upsert_asset_ref(provider, collection, ref, asset_ref,
                                             None, "failed", precheck_reason)
                    summary["assets_failed"] += 1
                    entry = asset_entry(kind="attachment", asset_ref=asset_ref,
                                        status="failed", reason=precheck_reason,
                                        source_record_ref=ref,
                                        original_filename=attachment.get("name"),
                                        media_type=export_media_type(attachment),
                                        size_bytes=declared)
                    entry["declared_size"] = declared
                    put(asset_ref, entry)
                    continue
                # Persisted terminal rows are skipped forever (already_terminal,
                # resolved, no re-count, no call). Exception: a row recorded under
                # an earlier, lower --asset-max-bytes becomes retryable once the
                # declared size fits within the current cap.
                if row and row["status"] in {"failed", "unsupported"} \
                        and row["reason"] in TERMINAL_REASONS:
                    fits_now = (row["reason"] == "asset_exceeds_max_bytes"
                                and type(declared) is int
                                and declared <= args.asset_max_bytes)
                    if not fits_now:
                        entry = asset_entry(kind="attachment", asset_ref=asset_ref,
                                            status="failed", reason="already_terminal",
                                            source_record_ref=ref,
                                            original_filename=attachment.get("name"),
                                            media_type=export_media_type(attachment),
                                            size_bytes=declared)
                        if type(declared) is int:
                            entry["declared_size"] = declared
                        entry["terminal_reason"] = row["reason"]
                        put(asset_ref, entry)
                        continue
                if size_guard[0]:
                    put(asset_ref, asset_entry(kind="attachment", asset_ref=asset_ref, status="skipped",
                                               reason="size_guard_tripped", source_record_ref=ref,
                                               original_filename=attachment.get("name")))
                    continue
                if type(declared) is int and objects_total[0] + declared > args.size_guard_bytes:
                    trip_size_guard()
                    put(asset_ref, asset_entry(kind="attachment", asset_ref=asset_ref, status="skipped",
                                               reason="size_guard_tripped", source_record_ref=ref,
                                               original_filename=attachment.get("name")))
                    continue
                if assets_used[0] >= args.max_assets:
                    archive.save_state(job, state)
                    raise AssetBudgetReached()
                request = asset_request(asset_ref, args)
                envelope, _, signature = call(job, "asset", request)
                assets_used[0] += 1
                result = envelope["response"]
                content = fresh_content.pop(signature, None)
                media_type = export_media_type(attachment, result)
                codes = {row_.get("code") for row_ in result.get("diagnostics", []) if isinstance(row_, dict)}
                if "rate_limit" in codes or result.get("reason") == "rate_limit":
                    # Save the breakpoint, stop the provider, stay retryable:
                    # rate_limit is deliberately NOT in TERMINAL_REASONS.
                    archive.upsert_asset_ref(provider, collection, ref, asset_ref,
                                             None, "failed", "rate_limit")
                    archive.save_state(job, state)
                    raise RateLimitStopped()
                if result.get("status") == "ok":
                    put(asset_ref, handle_ok_asset(job, state, ref, attachment, result, content,
                                                   media_type, asset_ref))
                else:
                    status = result.get("status") if result.get("status") in {"failed", "unsupported"} else "failed"
                    reason = result.get("reason") or status
                    put(asset_ref, asset_entry(kind="attachment", asset_ref=asset_ref, status=status,
                                               reason=reason, source_record_ref=ref,
                                               original_filename=attachment.get("name"),
                                               media_type=media_type,
                                               size_bytes=result.get("size_bytes"),
                                               downloaded_at=envelope["fetched_at"]))
                    archive.upsert_asset_ref(provider, collection, ref, asset_ref, None, status, reason)
                    summary["assets_failed"] += 1
            for image in images:
                image_id = image.get("image_id")
                key = "image:" + (str(image_id) if image_id is not None else "index-" + str(image.get("index")))
                put(key, {"kind": "image", "asset_ref": image_id if image_id is not None else key,
                          "index": image.get("index"), "original_filename": None, "safe_filename": None,
                          "media_type": "image/unknown", "size_bytes": None, "sha256": None,
                          "source_record_ref": ref, "downloaded_at": None,
                          "status": "unsupported", "reason": ORIGINAL_IMAGE_DOWNLOAD,
                          "object_path": None})
            manifest_list = [entries[key] for key in order if key in entries]
            atomic(manifest_path, encoded(manifest_list) + "\n")
            # size_guard_tripped skips are not terminal: the job stays pending so a
            # later invocation retries them once there is headroom under the guard.
            progress["resolved"] = sum(
                1 for entry in manifest_list
                if entry["status"] != "skipped" or entry["reason"] == "already_archived")
            archive.update_export_records(
                provider, ref,
                lambda record: record.update(
                    attachments=[entry for entry in manifest_list if entry["kind"] == "attachment"],
                    images=images or record.get("images") or [],
                    asset_manifest=str(manifest_rel)))
            archive.save_state(job, state)

        def handle_ok_asset(job, state, ref, attachment, result, content, media_type, asset_ref):
            collection = job["collection"]
            if content is None:
                sha = result.get("content_sha256")
                if sha and SHA256_HEX.fullmatch(sha) and (root / "objects" / sha[:2] / sha).exists():
                    archive.upsert_asset_ref(provider, collection, ref, asset_ref, sha, "ok", None)
                    return asset_entry(kind="attachment", asset_ref=asset_ref, status="ok",
                                       reason="replayed_from_raw", source_record_ref=ref,
                                       original_filename=attachment.get("name"), media_type=media_type,
                                       size_bytes=result.get("size_bytes"), sha256=sha,
                                       object_path=str(Path("objects") / sha[:2] / sha))
                summary["assets_failed"] += 1
                archive.upsert_asset_ref(provider, collection, ref, asset_ref, None, "failed",
                                         "asset_object_missing_after_replay")
                return asset_entry(kind="attachment", asset_ref=asset_ref, status="failed",
                                   reason="asset_object_missing_after_replay", source_record_ref=ref,
                                   original_filename=attachment.get("name"), media_type=media_type)
            size = len(content)
            if size <= 0:
                reason = "empty_content"
            elif size > args.asset_max_bytes:
                reason = "asset_exceeds_max_bytes"
            elif media_type == "application/pdf" and content[:5] != b"%PDF-":
                reason = "pdf_magic_mismatch"
            elif objects_total[0] + size > args.size_guard_bytes:
                trip_size_guard()
                return asset_entry(kind="attachment", asset_ref=asset_ref, status="skipped",
                                   reason="size_guard_tripped", source_record_ref=ref,
                                   original_filename=attachment.get("name"), media_type=media_type,
                                   size_bytes=size)
            else:
                reason = None
            if reason:
                summary["assets_failed"] += 1
                archive.upsert_asset_ref(provider, collection, ref, asset_ref, None, "failed", reason)
                return asset_entry(kind="attachment", asset_ref=asset_ref, status="failed", reason=reason,
                                   source_record_ref=ref, original_filename=attachment.get("name"),
                                   media_type=media_type, size_bytes=size)
            sha, relative = store_object(root, content, media_type)
            objects_total[0] += size
            archive.add_object(sha, relative, size, media_type)
            archive.upsert_asset_ref(provider, collection, ref, asset_ref, sha, "ok", None)
            summary["assets_downloaded"] += 1
            summary["assets_bytes"] += size
            return asset_entry(kind="attachment", asset_ref=asset_ref, status="ok", reason=None,
                               source_record_ref=ref, original_filename=attachment.get("name"),
                               media_type=media_type, size_bytes=size, sha256=sha,
                               object_path=relative)

        def run_job(job):
            state = archive.state(job)
            if state["state"] == "failed" and state.get("stop_reason") in DENIED_STOP_REASONS:
                # Pre-denied-semantics checkpoints recorded entitlement failures as
                # failed; upgrade the deterministic permission fact once, no SDK call.
                state.update(state="denied", stop_reason="denied")
                archive.save_state(job, state)
                return
            if provider == "ima" and not state.get("gaps"):
                state["gaps"] = IMA_EXPORT_GAPS
            try:
                while state["enum_state"] != "complete":
                    request = timeline_request(job, state["cursor"], args)
                    envelope, raw_path, _ = call(job, "timeline", request)
                    result = envelope["response"]
                    state["pages"] += 1
                    state["coverage"] = result.get("coverage")
                    state["diagnostics"] = result.get("diagnostics", [])
                    if collection_denied(result):
                        # Terminal permission fact, not a run error: recorded once,
                        # skipped forever after, and excluded from jobs_failed/errors
                        # so batch budgets are not burned re-probing dead collections.
                        state.update(state="denied", stop_reason="denied")
                        archive.save_state(job, state)
                        return
                    codes = {row.get("code") for row in state["diagnostics"] if isinstance(row, dict)}
                    if export_failed(result) and "rate_limit" not in codes:
                        state.update(state="failed", stop_reason="export_failed")
                        if not collection_scoped_failure(result):
                            failed_providers.add(provider)
                        error(job, "export_failed_see_raw_diagnostics")
                        archive.save_state(job, state)
                        return
                    for item in result.get("items") or []:
                        day, warnings = publication(item)
                        if item.get("ref") not in state["topic_refs"]:
                            state["topic_refs"].append(item.get("ref"))
                            state["topic_days"][item["ref"]] = day
                        summary["records_added"] += archive.add_export(
                            job, item, raw_path, envelope["fetched_at"], day, warnings)
                    cursor = result.get("continuation_cursor")
                    coverage_state = (result.get("coverage") or {}).get("state")
                    if rate_limited(result):
                        state["cursor"] = cursor or state["cursor"]
                        state.update(state="pending", stop_reason="rate_limit_stopped")
                        archive.save_state(job, state)
                        failed_providers.add(provider)
                        error(job, "rate_limit_stopped")
                        summary["diagnostics"].append({"code": "rate_limit_stopped",
                                                       "provider": provider, "job_id": job["id"]})
                        return
                    if coverage_state == "complete":
                        state["cursor"] = None
                        state["enum_state"] = "complete"
                        break
                    if coverage_state == "budget_exhausted" and cursor:
                        # SDK-side page budget: keep walking with the saved cursor;
                        # our own --max-calls budget bounds the loop per invocation.
                        if cursor == state["cursor"] or digest(cursor) in state["seen"]:
                            state.update(state="attempted", stop_reason="cursor_stalled")
                            error(job, "cursor_stalled")
                            archive.save_state(job, state)
                            return
                        state["seen"].append(digest(cursor))
                        state["cursor"] = cursor
                        state.update(state="pending", stop_reason="page_budget")
                        archive.save_state(job, state)
                        continue
                    if cursor and cursor != state["cursor"]:
                        marker = digest(cursor)
                        if marker in state["seen"]:
                            state.update(state="attempted", stop_reason="cursor_stalled")
                            error(job, "cursor_stalled")
                            archive.save_state(job, state)
                            return
                        state["seen"].append(marker)
                        state["cursor"] = cursor
                        archive.save_state(job, state)
                        continue
                    state.update(state="attempted", stop_reason="continuation_missing")
                    archive.save_state(job, state)
                    return
                if args.comments:
                    if provider == "zsxq":
                        for ref in list(state["topic_refs"]):
                            fetch_comments(job, state, ref)
                    elif provider not in noted_unsupported_comments:
                        noted_unsupported_comments.add(provider)
                        summary["diagnostics"].append(
                            {"code": "comments_not_supported_for_provider", "provider": provider})
                if args.assets:
                    for ref in list(state["topic_refs"]):
                        fetch_assets(job, state, ref)
                # Sub-tasks unresolved (e.g. SDK-side comment budget) keep the job
                # pending so a later invocation resumes from the saved cursors.
                if args.comments and provider == "zsxq" and any(
                        row.get("state") != "done" for row in state["comments"].values()):
                    state.update(state="pending", stop_reason="comments_budget")
                    archive.save_state(job, state)
                    return
                if args.assets and any(row.get("resolved", 0) < row.get("total", 0)
                                       for row in state["assets"].values()):
                    state.update(state="pending", stop_reason="assets_budget")
                    archive.save_state(job, state)
                    return
                complete = state["enum_state"] == "complete" and PROVIDER_FULL_EXPORT_SUPPORTED[provider]
                state["coverage_complete"] = bool(complete)
                state.update(state="attempted", stop_reason=None)
                archive.save_state(job, state)
                for ref in state["topic_refs"]:
                    archive.update_export_records(
                        provider, ref,
                        lambda record: record.update(coverage_complete=state["coverage_complete"]))
            except BudgetReached:
                state.update(state="pending", stop_reason="call_budget")
                archive.save_state(job, state)
            except AssetBudgetReached:
                state.update(state="pending", stop_reason="asset_budget")
                archive.save_state(job, state)
            except RateLimitStopped:
                state.update(state="pending", stop_reason="rate_limit_stopped")
                failed_providers.add(provider)
                error(job, "rate_limit_stopped")
                summary["diagnostics"].append({"code": "rate_limit_stopped",
                                               "provider": provider, "job_id": job["id"]})
                archive.save_state(job, state)
            except CommentsHardFail:
                state.update(state="failed", stop_reason="comments_failed")
                failed_providers.add(provider)
                archive.save_state(job, state)
            except Exception as exc:
                state.update(state="failed", exception_type=type(exc).__name__)
                failed_providers.add(provider)
                error(job, "exception_" + type(exc).__name__)
                archive.save_state(job, state)

        def assets_unresolved(state, job):
            if not args.assets:
                return False
            for ref in state.get("topic_refs", []):
                progress = state.get("assets", {}).get(ref)
                if progress is None:
                    return True
                if progress.get("resolved", 0) < progress.get("total", 0):
                    return True
                manifest_path = (root / "assets" / provider / safe_name(job["collection"]) /
                                 safe_name(ref) / "manifest.json")
                if progress.get("total", 0) > 0 and not manifest_path.exists():
                    return True
                # A persisted policy-cap failure becomes retryable once it fits the
                # current budget. Legacy hidden-8-MiB failures are always reopened:
                # current ir_search forwards the caller's max_bytes to the transport.
                if manifest_path.exists():
                    try:
                        entries = json.loads(manifest_path.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        return True
                    for entry in entries:
                        if entry.get("kind") != "attachment" or entry.get("status") != "failed":
                            continue
                        original = entry.get("terminal_reason") or entry.get("reason")
                        recorded = entry.get("declared_size") or entry.get("size_bytes") or 0
                        if original == "asset_exceeds_max_bytes" and type(recorded) is int \
                                and recorded <= args.asset_max_bytes:
                            return True
                        if original in {"response_too_large", "exceeds_official_transport_limit"}:
                            return True
            return False

        try:
            for job in jobs:
                state = archive.state(job)
                topic_refs = state.get("topic_refs", [])
                comment_rows = state.get("comments", {})
                comments_pending = (args.comments and provider == "zsxq" and
                                    (len(comment_rows) < len(topic_refs) or
                                     any(row.get("state") != "done"
                                         for row in comment_rows.values())))
                if state["state"] in {"attempted", "denied"} and not (comments_pending or assets_unresolved(state, job)):
                    continue
                if provider in failed_providers:
                    continue
                attempted[0] += 1
                run_job(job)
            summary["jobs_attempted_this_run"] = attempted[0]
            states = [archive.state(job)["state"] for job in jobs]
            summary["comments_topics_done"] = sum(
                1 for job in jobs for row in archive.state(job).get("comments", {}).values()
                if row.get("state") == "done")
            summary["comments_fetched"] = sum(
                row.get("count", 0) for job in jobs
                for row in archive.state(job).get("comments", {}).values())
        finally:
            archive.views()
            states = [archive.state(job)["state"] for job in jobs]
            summary.update(finished_at=now(), jobs_attempted=states.count("attempted"),
                           jobs_denied=states.count("denied"),
                           collections_denied=sorted({archive.state(job)["job"]["collection"]
                                                      for job in jobs
                                                      if archive.state(job)["state"] == "denied"}),
                           jobs_failed=states.count("failed"),
                           jobs_remaining=states.count("pending") + states.count("failed"),
                           all_jobs_attempted=all(s in {"attempted", "denied"} for s in states),
                           records_total=archive.db.execute("SELECT COUNT(*) FROM records").fetchone()[0],
                           undated_records=archive.db.execute(
                               "SELECT COUNT(*) FROM records WHERE day='unknown'").fetchone()[0])
            atomic(run_dir / "manifest.json", encoded(summary) + "\n")
            errors.close()
            archive.db.close()
        return dict(summary, manifest=str(run_dir / "manifest.json"))


def main(argv=None):
    p = parser()
    args = p.parse_args(argv)
    try:
        planned = make_jobs(args)
        if not args.execute:
            print(encoded({"mode": "dry_run", "archive_root": str(args.archive_root),
                           "provider": args.provider, "collections": planned["collections"],
                           "collections_from": planned["collections_from"],
                           "jobs": len(planned["jobs"]), "first_job": planned["jobs"][0],
                           "last_job": planned["jobs"][-1], "max_sdk_calls": args.max_calls,
                           "coverage_complete": False,
                           "notes": "Full-enumeration export archive; no network or filesystem writes."}))
            return 0
        result = execute(args, planned)
        print(encoded(result))
        return 0 if result["all_jobs_attempted"] and not result["errors"] else 2
    except (ValueError, OSError, ImportError, sqlite3.Error) as exc:
        print(encoded({"error": type(exc).__name__,
                       "message": "Invalid scope, missing SDK, busy archive, or local I/O failure; "
                                  "check inputs and environment."}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
