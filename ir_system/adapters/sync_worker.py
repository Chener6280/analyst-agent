#!/usr/bin/env python3
"""Deterministic, resumable sync worker. Public ir_search API only.

This is not a model tool accepting arbitrary commands. The desktop supplies a
validated immutable plan; worker-side validation is independent and fail-closed.
All source text stays local. The JSONL output contains progress, not source text.
"""
from datetime import date, datetime, timezone
import hashlib
import inspect
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager

PROTOCOL = 'ir-system-sync/v1'
AUDIO = {'.mp3', '.m4a', '.wav', '.aac', '.flac', '.ogg', '.opus', '.wma', '.amr'}
VIDEO = {'.mp4', '.mov', '.mkv', '.avi', '.webm'}
DOCUMENTS = {'.pdf', '.doc', '.docx', '.ppt', '.pptx', '.xls', '.xlsx', '.txt', '.html', '.md', '.rtf', '.csv'}
IMAGES = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp'}
ITEM_ERRORS = {'entitlement_denied', 'not_found', 'ima_original_unavailable', 'asset_download_failed',
               'asset_exceeds_authorized_budget', 'asset_exceeds_max_bytes', 'media_type_requires_confirmation',
               'pdf_magic_mismatch', 'invalid_asset_payload', 'no_extracted_text'}
LIMITS = {'maxOperations': (1, 1000), 'maxRecords': (1, 10000), 'maxFiles': (0, 1000),
          'maxBytesMiB': (1, 20480), 'maxFileMiB': (1, 200), 'maxParses': (0, 200), 'maxSeconds': (30, 3600)}


def check_environment(sdk, archive_root):
    """Read-only, no-network preflight. Never create/delete locks or alter jobs."""
    import stat
    from importlib.metadata import version, PackageNotFoundError
    issues = []
    def issue(code, title, detail, action, level='attention'):
        issues.append(dict(code=code, title=title, detail=detail, action=action, level=level))
    required = ('list_material_collections', 'list_collection_directory', 'export_collection_timeline',
                'ingest_local_record', 'ingest_local_asset', 'inspect_ingested_record',
                'index_local_archive', 'search_local_archive', 'read_local_archive', 'parse_local_archive')
    try:
        if any(not callable(getattr(sdk, n, None)) for n in required) or 'media_policy' not in inspect.signature(sdk.retrieve_asset).parameters:
            raise ValueError()
    except (AttributeError, TypeError, ValueError):
        issue('sdk_sync_api_missing', 'ir_search 版本不支持当前下载流程', '公开接口或音频排除参数缺失。', '由维护者更新独立 ir_search 环境，再重新检查；不使用旧混合下载脚本替代。')
    for package in ('PyMuPDF', 'firecrawl-anydoc'):
        try: version(package)
        except PackageNotFoundError:
            issue('parser_missing', '本地解析依赖缺失', package + ' 未安装在当前 Python 环境。', '由维护者核验并配置解析环境，不自动安装。')
    root = Path(archive_root) if archive_root else None
    if not root or not root.is_absolute() or not root.is_dir():
        issue('archive_root_required', '归档目录无效', '未配置有效的本地归档目录。', '在连接设置中配置已有归档目录。')
    else:
        root = root.resolve()
        if not os.access(root, os.R_OK | os.W_OK):
            issue('archive_not_writable', '归档目录不可读写', '当前进程缺少归档目录权限。', '核验本机目录权限后重新检查。')
        # The SDK derived lock is an exclusive-create sentinel; existence blocks.
        derived_lock = root / 'derived/local_archive_v1/.writer.lock'
        if derived_lock.exists() or derived_lock.is_symlink():
            issue('local_archive_locked', '本地解析锁需要核验', '派生资料库存在 .writer.lock，当前 SDK 会拒绝写入。', '由维护者确认实际占用者与进程状态；不自动删除锁。')
        # Legacy archive and desktop sync locks use OS advisory ownership instead.
        for name in ('.writer.lock', '.ir-system-sync.lock'):
            lock = root / name
            if not lock.exists() and not lock.is_symlink(): continue
            if os.name != 'posix':
                issue('lock_check_unavailable', '本机锁状态尚未核验', name + ' 需要平台专用检查。', '请维护者确认，不以锁文件存在或为空判断占用。', 'unknown'); continue
            fd = None
            try:
                import fcntl
                fd = os.open(lock, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | os.O_NONBLOCK)
                if not stat.S_ISREG(os.fstat(fd).st_mode): raise OSError()
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(fd, fcntl.LOCK_UN)
            except BlockingIOError:
                issue('archive_writer_busy', '已有归档写入占用', name + ' 当前有进程持锁。', '等待原任务结束或在其原终端停止；不要删锁或同时启动下载。')
            except OSError:
                issue('lock_check_unavailable', '无法安全核验归档锁', name + ' 不可访问或不是普通文件。', '请维护者检查；不删除、不改写锁文件。', 'unknown')
            finally:
                if fd is not None: os.close(fd)
    return dict(status='ready' if not issues else 'needs_attention', issues=issues,
                checkedAt=datetime.now(timezone.utc).isoformat(), networkCalls=0, filesWritten=0)


@contextmanager
def root_lock(root):
    """OS-owned advisory lock: crash releases ownership, no stale PID deletion."""
    path = root / '.ir-system-sync.lock'
    if path.is_symlink(): raise ValueError('sync_root_locked')
    fd = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    locked = False
    try:
        try:
            if os.name == 'nt':
                import msvcrt
                if os.fstat(fd).st_size == 0: os.write(fd, b'0')
                os.lseek(fd, 0, os.SEEK_SET); msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except OSError: raise ValueError('sync_root_locked') from None
        yield
    finally:
        if locked:
            if os.name == 'nt':
                os.lseek(fd, 0, os.SEEK_SET); msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else: fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


class Halt(Exception):
    def __init__(self, status, code):
        self.status, self.code = status, code


def atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix='.pending-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            json.dump(value, out, ensure_ascii=False)
            out.flush(); os.fsync(out.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def emit(kind, value):
    print(json.dumps({'protocol': PROTOCOL, 'type': kind, kind: value}, ensure_ascii=False), flush=True)


def safe_code(exc):
    code = getattr(exc, 'code', None)
    if isinstance(code, str) and re.fullmatch('[a-z][a-z0-9_]{0,90}', code): return code
    # Never return arbitrary upstream exception messages, tracebacks, paths or keys.
    text = str(exc)
    local = {'local_archive_locked', 'local_archive_record_budget_exceeded', 'ingest_object_checksum_mismatch',
             'invalid_collection_mode', 'first_date_required', 'archive_root_required', 'sync_plan_invalid',
             'sync_checkpoint_mismatch', 'sync_checkpoint_unreadable', 'sync_root_locked', 'sdk_sync_api_missing',
             'ima_probe_checkpoint_invalid'}
    return text if text in local else 'unexpected_worker_error'


def validate(plan):
    if (not isinstance(plan, dict) or plan.get('schemaVersion') != 1 or plan.get('media') != 'text_non_audio'
            or plan.get('includeNotes') is not False or plan.get('kind') not in {'incremental', 'backfill'}):
        raise ValueError('sync_plan_invalid')
    if set(plan) != {'schemaVersion', 'kind', 'archiveRoot', 'collections', 'budgets', 'media', 'includeNotes'}:
        raise ValueError('sync_plan_invalid')
    root = Path(plan['archiveRoot'])
    if not root.is_absolute() or not root.is_dir(): raise ValueError('archive_root_required')
    if set(plan['budgets']) != set(LIMITS): raise ValueError('sync_plan_invalid')
    for k, (minimum, maximum) in LIMITS.items():
        v = plan['budgets'][k]
        if type(v) is not int or not minimum <= v <= maximum: raise ValueError('sync_plan_invalid')
    rows = plan['collections']
    if not isinstance(rows, list) or not 1 <= len(rows) <= 500: raise ValueError('sync_plan_invalid')
    seen = set()
    for r in rows:
        if set(r) != {'provider', 'collectionId', 'name', 'mode', 'firstDate', 'start', 'end'}: raise ValueError('sync_plan_invalid')
        if r['provider'] not in {'zsxq', 'wisburg', 'ima'} or not re.fullmatch('[A-Za-z0-9_+=.-]{1,512}', r['collectionId']): raise ValueError('sync_plan_invalid')
        if r['mode'] not in ({'once', 'incremental'} if plan['kind'] == 'backfill' else {'incremental'}): raise ValueError('sync_plan_invalid')
        first, start, end = (date.fromisoformat(r[k]) for k in ('firstDate', 'start', 'end'))
        if start > end: raise ValueError('sync_plan_invalid')
        key = (r['provider'], r['collectionId'])
        if key in seen: raise ValueError('sync_plan_invalid')
        seen.add(key)
    return root.resolve()


class Worker:
    halt_type = Halt
    media_types = (AUDIO, VIDEO, DOCUMENTS)
    def __init__(self, sdk, *, progress=lambda _: None, zsxq_catalog=None, baseline=None):
        self.sdk, self.progress = sdk, progress
        self.zsxq_catalog, self.baseline = zsxq_catalog, baseline
        self.stopped = False; self.context = None; self.web_process = None; self.started = time.monotonic()
        self.counts = dict(operations=0, recordsAttempted=0, newRecords=0, updatedRecords=0,
                           unchangedRecords=0, downloaded=0, reused=0, bytes=0, parsed=0,
                           audioDeferred=0, videoDeferred=0, imagesDeferred=0, metadataOnly=0, unknownDates=0,
                           audioDownloads=0, asrCalls=0, hostedOcrCalls=0)
        self.stage = 'preflight'; self.issues = []; self.catalog = None
        self.limits = {k: maximum for k, (_, maximum) in LIMITS.items()}
        self.limits.update(maxOperations=100, maxSeconds=300)

    def stop(self, *_):
        self.stopped = True
        if self.context: self.context.cancel()
        if self.web_process and self.web_process.poll() is None: self.web_process.terminate()
        if getattr(self, 'client_process', None) and self.client_process.poll() is None: self.client_process.terminate()

    def check(self):
        if self.stopped: raise Halt('stopped', 'user_stopped')
        if time.monotonic() - self.started > self.limits['maxSeconds']: raise Halt('budget_paused', 'time_budget_exhausted')

    def update(self, stage):
        self.stage = stage
        event = {'stage': stage, 'counts': dict(self.counts)}
        if getattr(self, 'probe_active', None):
            event.update(imaProbeSearch={self.probe_active: self.probe_search[self.probe_active]},
                         imaProbes=[r for r in self.probes if r['collectionId'] == self.probe_active])
        self.progress(event)

    def call(self, function, *args, **kwargs):
        self.check()
        remaining = self.limits['maxOperations'] - self.counts['operations']
        if remaining <= 0: raise Halt('budget_paused', 'operation_budget_exhausted')
        timeout = max(0.1, min(60, self.limits['maxSeconds'] - (time.monotonic() - self.started)))
        self.context = self.sdk.RequestContext(timeout_seconds=timeout, max_operations=min(100, remaining))
        try: return function(*args, **kwargs, context=self.context)
        finally:
            self.counts['operations'] += self.context.operations
            self.context = None

    def scan(self, providers):
        if not isinstance(providers, list) or not providers or set(providers) - {'zsxq', 'ima', 'wisburg'}:
            raise ValueError('sync_plan_invalid')
        self.update('scanning')
        catalogs = []
        for provider in dict.fromkeys(providers):
            self.check()
            if provider == 'zsxq' and self.zsxq_catalog:
                catalogs.extend(self.zsxq_catalog['sources'])
                continue
            result = self.call(self.sdk.list_material_collections, provider)
            catalogs.append({'provider': provider, 'complete': result.get('exhaustive') is True,
                             'membershipVerification': 'not_verified_by_api_directory' if provider == 'zsxq' else 'not_applicable',
                             'kind': 'static_categories' if provider == 'wisburg' else 'account_directory',
                             'collections': [{'collectionId': r['collection_id'], 'name': r.get('name') or r['collection_id']}
                                             for r in result.get('collections', [])]})
            if result.get('exhaustive') is not True:
                self.catalog = {'scannedAt': datetime.now(timezone.utc).isoformat(), 'sources': catalogs, 'complete': False}
                raise Halt('needs_attention', 'subscription_scan_incomplete')
            # Discovery is independent of content/download permissions. A failure
            # inside one library must never hide a newly joined library. Selected
            # content is checked by the probe or actual export, not this inventory.
            if provider == 'ima': catalogs[-1]['inventoryOnly'] = True
        self.catalog = {'scannedAt': datetime.now(timezone.utc).isoformat(), 'sources': catalogs, 'complete': True}
        return self.catalog

    def checkpoint(self):
        atomic(self.checkpoint_path, self.state)

    def defer_item(self, row, item, code):
        pending = self.state.setdefault('retryItems', {})
        identifier = fingerprint([row['provider'], row['collectionId'], item['ref']])
        prior = pending.get(identifier, {})
        pending[identifier] = {'row': row, 'item': item, 'code': code, 'attempts': prior.get('attempts', 0) + 1}
        self.checkpoint()

    def process(self, row, item):
        self.check()
        if self.counts['recordsAttempted'] >= self.limits['maxRecords']: raise Halt('budget_paused', 'record_budget_exhausted')
        self.counts['recordsAttempted'] += 1
        provider, coll = row['provider'], row['collectionId']
        result = self.sdk.ingest_local_record(self.root, provider, coll, item)
        self.counts[{'new': 'newRecords', 'updated': 'updatedRecords', 'unchanged': 'unchangedRecords'}[result['change']]] += 1
        record = result['record']
        if not record.get('published_at'): self.counts['unknownDates'] += 1
        if record.get('images_discovered'):
            self.issues.append({'code': 'images_metadata_only', 'count': record['images_discovered']})
        if item.get('type') in {'webpage', 'wechat', 'note', 'unknown', 'document', 'conversation'} and not record.get('content_text'):
            self.counts['metadataOnly'] += 1
            self.issues.append({'code': 'ima_content_route_not_connected'})
        for a in record['attachments']:
            self.check()
            suffix = Path(a['original_filename'].strip()).suffix.lower()
            media = a['media_type'].lower()
            if suffix in AUDIO or media == 'audio' or media.startswith('audio/'):
                self.counts['audioDeferred'] += 1; continue
            if suffix in VIDEO or media == 'video' or media.startswith('video/'):
                self.counts['videoDeferred'] += 1; continue
            if suffix not in DOCUMENTS | IMAGES and media not in {'pdf', 'docx', 'pptx', 'xlsx', 'txt', 'html', 'image'}:
                raise Halt('needs_attention', 'media_type_requires_confirmation')
            saved = self.sdk.inspect_ingested_record(self.root, provider, coll, item['ref'])
            prior = next(x for x in saved['attachments'] if x['asset_ref'] == a['asset_ref'])
            if prior.get('verified'):
                self.counts['reused'] += 1
                document_id = prior['document_id']
            else:
                if self.counts['downloaded'] >= self.limits['maxFiles']: raise Halt('budget_paused', 'file_budget_exhausted')
                remaining = self.limits['maxBytesMiB'] * 1024 * 1024 - self.counts['bytes']
                maximum = min(remaining, self.limits['maxFileMiB'] * 1024 * 1024)
                if maximum <= 0: raise Halt('budget_paused', 'byte_budget_exhausted')
                if a.get('declared_size') and a['declared_size'] > maximum: raise Halt('needs_attention', 'asset_exceeds_authorized_budget')
                self.update('downloading')
                asset = self.call(self.sdk.retrieve_asset, a['asset_ref'], max_bytes=maximum, media_policy='text_non_audio')
                if asset.get('status') != 'ok':
                    code = asset.get('reason') or 'asset_download_failed'
                    raise Halt('needs_attention', code if re.fullmatch('[a-z_]{1,90}', code) else 'asset_download_failed')
                raw = asset.get('content')
                if not isinstance(raw, bytes) or len(raw) > maximum or not raw: raise Halt('failed', 'invalid_asset_payload')
                if suffix == '.pdf' and not raw.startswith(b'%PDF-'): raise Halt('needs_attention', 'pdf_magic_mismatch')
                committed = self.sdk.ingest_local_asset(self.root, provider, coll, item['ref'], a['asset_ref'], raw)
                self.counts['downloaded'] += 1; self.counts['bytes'] += len(raw)
                document_id = committed['document_id']
            if document_id not in self.state['parseIds']:
                self.state['parseIds'].append(document_id)
            self.state['hasRecords'] = True
            self.checkpoint()
        self.state['hasRecords'] = True

    def enumerate(self, row):
        p, coll = row['provider'], row['collectionId']
        key = p + ':' + coll
        s = self.state['collections'].setdefault(key, {'queue': [[None, '']], 'visited': [], 'folders': [], 'done': False})
        if s['done']: return
        while s['queue']:
            self.check(); self.update('enumerating')
            folder, cursor = s['queue'][0]
            pair = [folder, cursor]
            if pair in s['visited']: raise Halt('needs_attention', 'pagination_cycle')
            if p == 'ima':
                page = self.call(self.sdk.list_collection_directory, p, coll, folder_id=folder, cursor=cursor, limit=20)
                items, next_cursor = page['items'], page['next_cursor']
                more = page['has_more']
            else:
                page = self.call(self.sdk.export_collection_timeline, p, coll, published_start=row['start'],
                                 published_end=row['end'], cursor=cursor or None, include_text=True, include_notes=False, max_items=20)
                coverage = page.get('coverage', {}).get('state')
                if coverage not in {'complete', 'budget_exhausted'}: raise Halt('needs_attention', 'source_enumeration_incomplete')
                # Known diagnostics denote omitted records/uncertain ordering, not a complete page.
                critical = {'invalid_community_record', 'invalid_ima_record', 'ima_pagination_unknown', 'ima_pagination_stalled'}
                if any(d.get('code') in critical for d in page.get('diagnostics', [])):
                    raise Halt('needs_attention', 'source_record_gap')
                items = page['items']; more = coverage == 'budget_exhausted'; next_cursor = page.get('continuation_cursor')
            page_hash = fingerprint(items)
            if s.get('pageHash') and s['pageHash'] != page_hash:
                raise Halt('needs_attention', 'material_cursor_stale')
            s['pageHash'] = page_hash
            children = s.setdefault('children', [])
            self.checkpoint()
            for position, item in enumerate(items):
                if position < s.get('position', 0): continue
                if item.get('type') == 'folder':
                    if item['folder_id'] not in s['folders']:
                        children.append([item['folder_id'], ''])
                else:
                    try:
                        self.process(row, item)
                    except Halt as exc:
                        if exc.code not in ITEM_ERRORS: raise
                        self.defer_item(row, item, exc.code)
                s['position'] = position + 1
                self.checkpoint()
            if more and (not next_cursor or next_cursor == cursor): raise Halt('needs_attention', 'pagination_stalled')
            s['visited'].append(pair); s['queue'].pop(0)
            for child in children:
                if child[0] not in s['folders']:
                    s['folders'].append(child[0]); s['queue'].append(child)
            if more: s['queue'].insert(0, [folder, next_cursor])
            s.update(position=0, pageHash=None, children=[])
            if len(s['folders']) > 10000 or len(s['visited']) > 100000: raise Halt('needs_attention', 'directory_safety_limit')
            if not s['queue']: s['done'] = True
            self.state['issues'] = self.issues
            self.checkpoint()

    def web_request(self, request):
        executable = os.environ.get('IR_SYSTEM_NODE_EXECUTABLE')
        if not executable or not Path(executable).is_file(): raise Halt('needs_attention', 'web_runtime_missing')
        env = dict(os.environ, ELECTRON_RUN_AS_NODE='1')
        child = subprocess.Popen([executable, str(Path(__file__).parent / 'zsxq_web/desktop.js')],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env)
        self.web_process = child
        deadline = time.monotonic() + request['limits']['maxSeconds'] + 55
        try:
            child.stdin.write((json.dumps(request) + '\n').encode()); child.stdin.close(); child.stdin = None
            while True:
                try: raw, _ = child.communicate(timeout=0.5); break
                except subprocess.TimeoutExpired:
                    if time.monotonic() > deadline:
                        child.kill(); child.communicate(); raise Halt('interrupted', 'web_worker_interrupted')
            if len(raw) > 4*1024*1024: raise Halt('needs_attention', 'web_output_limit')
            payload = json.loads(raw)
            if payload.get('protocol') != PROTOCOL or payload.get('type') != 'result': raise ValueError()
            return payload['result']
        except (ValueError, KeyError): raise Halt('interrupted', 'invalid_web_response') from None
        finally:
            if child.poll() is None: child.terminate(); child.wait(timeout=5)
            self.web_process = None

    def queue_web_parses(self, row, refs):
        if not refs: return
        self.check()
        self.update('indexing'); self.sdk.index_local_archive(self.root)
        offset = 0
        while True:
            page = self.sdk.search_local_archive(self.root, source='zsxq_web', collection_id=row['collectionId'],
                                                 kind='attachment', start=row['start'], end=row['end'], include_unknown_dates=True, limit=100, offset=offset)
            for doc in page['items']:
                if doc.get('parent_ref') not in refs or doc.get('download_status') != 'ok': continue
                if Path(doc.get('title', '')).suffix.lower() in AUDIO | VIDEO or doc.get('media_kind') == 'audio': continue
                if doc['id'] not in self.state['parseIds']: self.state['parseIds'].append(doc['id'])
            offset += len(page['items'])
            if not page['has_more']: break
            if not page['items'] or offset > 200000: raise Halt('needs_attention', 'web_index_limit')
        self.checkpoint()

    def enumerate_web(self, row):
        key = row['provider'] + ':' + row['collectionId']
        current = self.state['collections'].setdefault(key, {'route': 'zsxq_web', 'done': False, 'refs': []})
        if current.get('route') != 'zsxq_web': raise Halt('needs_attention', 'route_changed')
        if current['done']: return
        self.check(); self.update('web_downloading')
        limits = dict(maxOperations=max(0, self.limits['maxOperations']-self.counts['operations']),
                      maxRecords=max(0, self.limits['maxRecords']-self.counts['recordsAttempted']),
                      maxFiles=max(0, self.limits['maxFiles']-self.counts['downloaded']),
                      maxBytes=max(0, self.limits['maxBytesMiB']*1024*1024-self.counts['bytes']),
                      maxFileBytes=self.limits['maxFileMiB']*1024*1024,
                      maxSeconds=max(0, int(self.limits['maxSeconds']-(time.monotonic()-self.started))))
        request = dict(command='run', archiveRoot=str(self.root), row=row, catalog=self.zsxq_catalog,
                       scopeKey=fingerprint(str(self.checkpoint_path)), limits=limits)
        result = self.web_request(request)
        for name, count in result.get('counts', {}).items():
            if name in self.counts and type(count) is int and count >= 0: self.counts[name] += count
        if result.get('counts', {}).get('imagesDeferred'):
            self.issues.append({'code': 'web_images_metadata_only', 'count': result['counts']['imagesDeferred']})
        manifest = result.get('manifest') or {}
        for ref in manifest.get('record_refs', []):
            if not re.fullmatch(r'zsxq://topic/\d{1,30}', ref): raise Halt('needs_attention', 'invalid_web_response')
            if ref not in current['refs']: current['refs'].append(ref)
        current['manifest'] = manifest.get('manifest_path')
        current['reachedDateFloor'] = manifest.get('reached_date_floor', False)
        current['coverageComplete'] = False
        self.state['hasRecords'] = self.state['hasRecords'] or bool(current['refs'])
        self.checkpoint()
        # Even a bounded pause exposes already committed files in the local index.
        self.queue_web_parses(row, set(current['refs']))
        if result.get('status') == 'partial' and result.get('code') == 'web_items_pending':
            current['done'] = True
            current['fileFailures'] = manifest.get('failures', {})
            self.issues.append(dict(code='web_items_pending', provider=row['provider'],
                                    collectionId=row['collectionId'], name=row['name'], count=len(current['fileFailures'])))
            self.checkpoint(); return
        if result.get('status') != 'completed':
            # Indexing committed files must not disguise the actual failure as
            # an index error. The browser stopped during source download.
            self.update('web_downloading')
            code = result.get('code') or 'web_discovery_incomplete'
            if not re.fullmatch('[a-z][a-z0-9_]{0,90}', code): code = 'web_worker_failed'
            status = result.get('status')
            raise Halt(status if status in {'stopped', 'interrupted', 'budget_paused'} else 'needs_attention', code)
        current['done'] = True; self.checkpoint()

    def block_collection(self, row, code):
        key = row['provider'] + ':' + row['collectionId']
        entry = self.state['collections'].setdefault(key, {'done': False})
        entry['blockedCode'] = code
        issue = dict(code=code, provider=row['provider'], collectionId=row['collectionId'], name=row['name'])
        if issue not in self.issues: self.issues.append(issue)
        self.state['issues'] = self.issues
        self.checkpoint()

    def run(self, plan, job_directory, excluded_collections=None):
        self.root = validate(plan); self.limits = plan['budgets']
        excluded = excluded_collections or []
        known = {r['provider'] + ':' + r['collectionId'] for r in plan['collections']}
        if not isinstance(excluded, list) or any(not isinstance(k, str) or k not in known for k in excluded):
            raise ValueError('sync_excluded_scope_invalid')
        rows = [r for r in plan['collections'] if r['provider'] + ':' + r['collectionId'] not in excluded]
        if not rows: raise ValueError('sync_empty_scope')
        for name in ('list_collection_directory', 'ingest_local_record', 'ingest_local_asset', 'inspect_ingested_record', 'search_local_archive'):
            if not callable(getattr(self.sdk, name, None)): raise ValueError('sdk_sync_api_missing')
        try:
            if 'media_policy' not in inspect.signature(self.sdk.retrieve_asset).parameters:
                raise ValueError('sdk_sync_api_missing')
        except (AttributeError, TypeError):
            raise ValueError('sdk_sync_api_missing') from None
        directory = Path(job_directory).resolve()
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.checkpoint_path = directory / 'checkpoint.json'
        if self.checkpoint_path.is_symlink(): raise ValueError('sync_checkpoint_unreadable')
        digest = fingerprint({k: v for k, v in plan.items() if k != 'budgets'})
        if self.checkpoint_path.exists():
            self.state = json.loads(self.checkpoint_path.read_text())
            if self.state.get('planHash') != digest: raise ValueError('sync_checkpoint_mismatch')
        else:
            self.state = {'planHash': digest, 'collections': {}, 'parseIds': [], 'hasRecords': False, 'issues': []}
        self.issues = self.state.get('issues', [])
        lock = root_lock(self.root)
        lock.__enter__()
        try:
            self.scan(list(dict.fromkeys(r['provider'] for r in rows)))
            visible = {(s['provider'], c['collectionId']) for s in self.catalog['sources'] for c in s['collections']}
            before = {(s['provider'], c['collectionId']): c for s in (self.baseline or {}).get('sources', []) for c in s['collections']}
            current = {(s['provider'], c['collectionId']): c for s in self.catalog['sources'] for c in s['collections']}
            for row in rows:
                if (row['provider'], row['collectionId']) not in visible:
                    self.block_collection(row, 'selected_collection_not_visible'); continue
                k = (row['provider'], row['collectionId'])
                c, prior = current[k], before.get(k)
                if row['provider'] == 'ima':
                    from ima_client_worker import available as client_available
                    use_client = client_available() and (self.state.get('imaApiUnavailable') or row['collectionId'] in self.state.get('imaClientRoutes', []) or
                        row['collectionId'] in getattr(self, 'ima_client_collections', []))
                    # Check only the explicitly authorized scope before writing
                    # any content. Off-scope libraries cannot block this run.
                    try:
                        if not use_client:
                            self.call(self.sdk.list_collection_directory, 'ima', row['collectionId'], folder_id=None, cursor='', limit=1)
                            c.update(directoryAccess='accessible', accessCode=None)
                        else:
                            c.update(clientRoute='execution_check')
                    except Exception as exc:
                        if isinstance(exc, Halt): raise
                        code = safe_code(exc)
                        from ima_probe_state import diagnostics
                        self.failure_diagnostic = diagnostics(exc, phase='directory_page', code=code)
                        if code in {'ima_daily_quota_exhausted','entitlement_denied','ima_original_unavailable'} and client_available():
                            if c.get('name') != row['name']:
                                self.block_collection(row, 'subscription_status_changed'); continue
                            if code == 'ima_daily_quota_exhausted': self.state['imaApiUnavailable'] = True
                            elif row['collectionId'] not in self.state.setdefault('imaClientRoutes', []):
                                self.state['imaClientRoutes'].append(row['collectionId'])
                            self.checkpoint()
                            c.update(clientRoute='execution_check')
                            continue
                        # A transient quota is not a changed subscription or a
                        # permanent denial. Preserve earlier permission evidence.
                        if code not in {'ima_daily_quota_exhausted', 'quota', 'rate_limit', 'network', 'timeout'}:
                            c.update(directoryAccess='unavailable', accessCode=code)
                        raise Halt('needs_attention', code) from None
                fields = ('name', 'membership', 'skill_api', 'permissions') if row['provider'] == 'zsxq' else (('name',) if c.get('clientRoute') else ('name', 'directoryAccess', 'accessCode'))
                if prior and any(f in prior and prior.get(f) != c.get(f) for f in fields):
                    self.block_collection(row, 'subscription_status_changed'); continue
                if row['provider'] == 'zsxq' and self.zsxq_catalog:
                    if not c.get('membership', {}).get('active'):
                        self.block_collection(row, 'membership_expired'); continue
                    if not c.get('permissions', {}).get('allow_download'):
                        self.block_collection(row, 'download_disabled_by_group'); continue
                    if c.get('skill_api') not in {'accessible', 'not_enabled'}: raise Halt('needs_attention', 'skill_route_unavailable')
                elif row['provider'] == 'zsxq': raise Halt('needs_attention', 'fresh_scan_required')
                if c.get('directoryAccess') == 'unavailable': raise Halt('needs_attention', 'collection_access_denied')
            self.checkpoint()
            for row in rows:
                if self.state['collections'].get(row['provider']+':'+row['collectionId'], {}).get('blockedCode'): continue
                c = current[(row['provider'], row['collectionId'])]
                if row['provider'] == 'ima':
                    from ima_client_worker import available as client_available, run_scoped
                    if client_available() and (self.state.get('imaApiUnavailable') or row['collectionId'] in self.state.get('imaClientRoutes', []) or row['collectionId'] in getattr(self, 'ima_client_collections', [])):
                        run_scoped(self, row); continue
                if row['provider'] == 'zsxq' and c.get('skill_api') == 'not_enabled':
                    try:
                        self.enumerate_web(row)
                    except Halt as exc:
                        # Only group-local entitlement outcomes are isolated.
                        # Login, rate limits, locks, and unexpected errors still stop globally.
                        if exc.code not in {'membership_expired', 'membership_evidence_conflict', 'download_disabled_by_group'}: raise
                        self.block_collection(row, exc.code)
                else:
                    prior_route = self.state['collections'].get(row['provider']+':'+row['collectionId'], {}).get('route')
                    if prior_route == 'zsxq_web': raise Halt('needs_attention', 'route_changed')
                    try:
                        self.enumerate(row)
                    except Exception as exc:
                        code = exc.code if isinstance(exc, Halt) else safe_code(exc)
                        if row['provider'] != 'ima' or code != 'ima_daily_quota_exhausted' or not client_available(): raise
                        self.state['imaApiUnavailable'] = True; self.checkpoint()
                        run_scoped(self, row)
            # Finish healthy documents before bounded retry of isolated failures.
            for identifier, pending in list(self.state.get('retryItems', {}).items()):
                if pending['row']['provider'] + ':' + pending['row']['collectionId'] in excluded: continue
                if pending.get('attempts', 0) >= 2: continue
                try:
                    self.process(pending['row'], pending['item'])
                except Halt as exc:
                    if exc.code not in ITEM_ERRORS: raise
                    self.defer_item(pending['row'], pending['item'], exc.code)
                else:
                    del self.state['retryItems'][identifier]; self.checkpoint()
            if self.state.get('retryItems'):
                for identifier, pending in self.state['retryItems'].items():
                    issue = {'code': pending['code'], 'retryId': identifier,
                             'collectionId': pending['row']['collectionId'], 'provider': pending['row']['provider']}
                    if issue not in self.issues: self.issues.append(issue)
            if self.state['hasRecords']:
                self.check(); self.update('indexing'); self.sdk.index_local_archive(self.root)
            while self.state['parseIds']:
                self.check()
                if self.counts.get('parseAttempts', 0) >= self.limits['maxParses']: raise Halt('budget_paused', 'parse_budget_exhausted')
                identifier = self.state['parseIds'][0]
                # Inspect this exact document, including a prior terminal failure; do not skip it silently.
                doc = self.sdk.read_local_archive(self.root, identifier, max_chars=1)
                if doc['parse_status'] == 'parsed':
                    self.state['parseIds'].pop(0); self.checkpoint(); continue
                if doc['parse_status'] not in {'pending', 'parser_missing'}:
                    self.issues.append({'code': doc['parse_status'], 'documentId': identifier})
                    self.state['parseIds'].pop(0); self.checkpoint(); continue
                self.update('parsing')
                self.counts['parseAttempts'] = self.counts.get('parseAttempts', 0) + 1
                result = self.sdk.parse_local_archive(self.root, limit=1, document_ids=[identifier])
                if result.get('status') != 'ok' or result.get('attempted') != 1:
                    self.issues.append({'code': (result.get('results') or [{}])[0].get('status', 'parse_requires_review'), 'documentId': identifier})
                    self.state['parseIds'].pop(0); self.checkpoint(); continue
                self.counts['parsed'] += 1; self.state['parseIds'].pop(0); self.checkpoint()
            self.update('finished')
            return self.result('partial' if self.issues else 'completed', 'coverage_gaps' if self.issues else None)
        finally:
            self.state['issues'] = self.issues
            try: self.checkpoint()
            finally: lock.__exit__(None, None, None)

    def result(self, status, code=None):
        return {'status': status, 'code': code, 'stage': self.stage, 'counts': self.counts,
                'diagnostic': getattr(self, 'failure_diagnostic', None),
                'imaProbes': getattr(self, 'probes', []),
                'imaProbeSearch': getattr(self, 'probe_search', {}),
                'imaProbeDiagnostic': getattr(self, 'probe_diagnostic', None),
                'issues': self.issues, 'catalog': self.catalog, 'coverageComplete': False,
                'webManifests': [c['manifest'] for c in getattr(self, 'state', {}).get('collections', {}).values() if c.get('manifest')],
                'elapsedSeconds': round(time.monotonic() - self.started, 3)}


def main():
    os.umask(0o077)
    configured = os.environ.get('IR_SEARCH_PATH')
    if configured: sys.path.insert(0, str(Path(configured).expanduser().resolve()))
    worker = None
    try:
        import ir_search
        request = json.loads(sys.stdin.readline(2 * 1024 * 1024))
        worker = Worker(ir_search, progress=lambda p: emit('progress', p), zsxq_catalog=request.get('zsxqCatalog'), baseline=request.get('subscriptionBaseline'))
        worker.ima_client_collections = request.get('imaClientCollections', [])
        signal.signal(signal.SIGTERM, worker.stop); signal.signal(signal.SIGINT, worker.stop)
        if request.get('command') == 'check':
            result = {'status': 'completed', 'localCheck': check_environment(ir_search, request.get('archiveRoot'))}
        elif request.get('command') == 'scan':
            worker.scan(request.get('providers'))
            result = worker.result('completed')
        elif request.get('command') == 'ima-probe':
            # Alias the running module so Halt has one identity in CLI and tests.
            sys.modules['sync_worker'] = sys.modules[__name__]
            from ima_probe import probe
            result = probe(worker, request.get('selected'), request.get('probeCheckpoints'))
        elif request.get('command') == 'run': result = worker.run(request['plan'], request['jobDirectory'], request.get('excludedCollections'))
        else: raise ValueError('sync_plan_invalid')
    except Halt as exc:
        result = worker.result(exc.status, exc.code)
    except Exception as exc:
        code = safe_code(exc)
        status = 'stopped' if worker and worker.stopped else 'budget_paused' if code == 'operation_budget_exhausted' else 'needs_attention'
        result = worker.result(status, code) if worker else {'status': 'failed', 'code': code}
    emit('result', result)


if __name__ == '__main__': main()
