"""Official IMA client fallback, deterministic macOS accessibility only.

Keep raw display dates as evidence. Unknown dates are not silently discarded.
No private client endpoints, cookies, signed URL fetches, or model calls.
"""
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
import zipfile


def available():
    return os.environ.get('IR_SYSTEM_IMA_CLIENT_ENABLED') == '1' and bridge_path().is_file()


def bridge_path():
    return Path(__file__).parent / 'ima_client/ima-accessibility'


def display_day(raw, today=None):
    """Client list update day, not document publication or filename date."""
    today = today or datetime.now(ZoneInfo('Asia/Shanghai')).date()
    raw = re.sub(r'^(PDF|WORD|PPT|EXCEL|TXT|MARKDOWN|笔记)\s*', '', raw).removesuffix('更新').strip()
    if raw in {'今天', '昨天'}: return (today - timedelta(days=raw == '昨天')).isoformat()
    if re.fullmatch(r'([01]?\d|2[0-3]):[0-5]\d', raw): return today.isoformat()
    try:
        if re.fullmatch(r'\d{4}/\d{1,2}/\d{1,2}', raw): return date(*map(int, raw.split('/'))).isoformat()
        if re.fullmatch(r'\d{1,2}/\d{1,2}', raw):
            month, day = map(int, raw.split('/')); result = date(today.year, month, day)
            # IMA's short display omits the year. Resolve only the most recent
            # occurrence, keep raw date and this inference in the checkpoint.
            if result > today: result = date(today.year - 1, month, day)
            return result.isoformat()
    except ValueError: pass
    return None


class Native:
    def __init__(self, worker): self.w = worker

    def call(self, command, **args):
        w = self.w; Halt = w.halt_type; w.check()
        if w.counts['operations'] >= w.limits['maxOperations']: raise Halt('budget_paused', 'operation_budget_exhausted')
        w.counts['operations'] += 1
        proc = subprocess.Popen([str(bridge_path())], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, text=True)
        w.client_process = proc
        proc.stdin.write(json.dumps(dict(command=command, **args)) + '\n'); proc.stdin.close(); proc.stdin = None
        deadline = time.monotonic() + 90
        try:
            while True:
                try: raw, _ = proc.communicate(timeout=.25); break
                except subprocess.TimeoutExpired:
                    if w.stopped or time.monotonic() > deadline:
                        proc.terminate(); proc.communicate(timeout=5)
                        raise Halt('stopped' if w.stopped else 'interrupted', 'user_stopped' if w.stopped else 'ima_client_timeout')
            if w.stopped: raise Halt('stopped', 'user_stopped')
            if len(raw) > 2*1024*1024: raise Halt('needs_attention', 'ima_client_output_limit')
            try: result = json.loads(raw)
            except ValueError: raise Halt('needs_attention', 'ima_client_invalid_response') from None
            if result.get('status') not in {'ok', 'ready'}:
                code = result.get('code', 'ima_client_failed')
                error = Halt('needs_attention', code if re.fullmatch(r'ima_[a-z_]{1,80}', code) else 'ima_client_failed')
                error.client_command = command
                raise error
            return result
        finally:
            if proc.poll() is None: proc.terminate(); proc.wait(timeout=5)
            w.client_process = None


def run_library(w, row, native=None):
    Halt = w.halt_type
    AUDIO, VIDEO, DOCUMENTS = w.media_types
    native = native or Native(w)
    key = 'ima:' + row['collectionId']
    previous = w.state['collections'].get(key, {})
    if previous.get('done') and previous.get('route') == 'ima_client': return
    if previous.get('route') != 'ima_client':
        # Preserve the untouched API cursor, instead of rewriting its meaning.
        previous = {'route': 'ima_client', 'apiCheckpoint': previous, 'done': False, 'seen': {}, 'failures': {}}
        w.state['collections'][key] = previous; w.checkpoint()
    state = previous
    w.update('client_downloading')
    try:
        native.call('check')
    except Halt as exc:
        if exc.code == 'ima_accessibility_required':
            # Prompt only; the user, never the program, grants this OS permission.
            native.call('authorize')
            native.call('check')
        elif exc.code == 'ima_client_not_running':
            subprocess.run(['/usr/bin/open', '-b', 'com.tencent.imamac'], check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
            time.sleep(1)
            native.call('check')
        else: raise
    opened = native.call('open_library', name=row['name'], libraryId=state.get('libraryId'))
    library = opened.get('libraryId')
    if not isinstance(library, str) or not library.isdigit(): raise Halt('needs_attention', 'ima_client_library_unverified')
    if state.get('libraryId') and state['libraryId'] != library: raise Halt('needs_attention', 'ima_client_scope_changed')
    state['libraryId'] = library
    state['dateBasis'] = 'client_list_update_day_year_inferred_not_publication'
    state.setdefault('seen', {}); state.setdefault('failures', {})
    state['scanIncomplete'] = False
    # Each new process starts at the top. Durable per-row identities make this
    # safe after a crash or a user scrolling the client between batches.
    initial = native.call('list', libraryId=library)
    viewport = lambda items: hashlib.sha256(json.dumps(items,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    if not opened.get('reusedView') or viewport(initial.get('items', [])) != state.get('viewport'):
        native.call('scroll', libraryId=library, direction='top')
    last = None; stalled = 0
    while True:
        page = native.call('list', libraryId=library)
        items = page.get('items', [])
        declared = re.search(r'^内容\s*[（(]?(\d+)', page.get('totalLabel', '').replace(',', ''))
        total = int(declared[1]) if declared else None
        state['displayedTotal'] = total
        state['viewport'] = viewport(items); w.checkpoint()
        for item in items:
            title, raw_date = item.get('title', ''), item.get('displayDate', '')
            if not isinstance(title, str) or len(title) > 2000: raise Halt('needs_attention', 'ima_client_invalid_response')
            identity = hashlib.sha256((title+'\n'+raw_date).encode()).hexdigest()
            if identity in state['seen']: continue
            suffix = Path(title).suffix.lower()
            stamp = display_day(raw_date)
            info = dict(title=title, rawDate=raw_date, updateDay=stamp)
            # Unknown-date rows remain visible gaps rather than fabricated dates.
            if stamp and not row['start'] <= stamp <= row['end']:
                state['seen'][identity] = dict(info, status='outside_window'); w.checkpoint(); continue
            if suffix in AUDIO | VIDEO:
                w.counts['audioDeferred' if suffix in AUDIO else 'videoDeferred'] += 1
                state['seen'][identity] = dict(info, status='audio_video_deferred'); w.checkpoint(); continue
            if not stamp or suffix not in DOCUMENTS:
                state['seen'][identity] = dict(info, status='date_or_format_review')
                state['failures'][identity] = 'ima_client_date_or_format_review'; w.checkpoint(); continue
            if w.counts['recordsAttempted'] >= w.limits['maxRecords']: raise Halt('budget_paused', 'record_budget_exhausted')
            # Reserve enough operations to finish one file before another batch.
            if w.limits['maxOperations'] - w.counts['operations'] < 4: raise Halt('budget_paused', 'operation_budget_exhausted')
            if w.counts['downloaded'] >= w.limits['maxFiles']: raise Halt('budget_paused', 'file_budget_exhausted')
            w.counts['recordsAttempted'] += 1
            opened_doc = native.call('open_file', libraryId=library, title=title)
            media = opened_doc.get('mediaId', '')
            if not re.fullmatch(r'[A-Za-z0-9_+=.-]{1,512}', media): raise Halt('needs_attention', 'ima_client_invalid_response')
            ref = 'ima://media/' + media
            try:
                if not opened_doc.get('downloadAvailable'):
                    state['failures'][identity] = 'ima_client_download_unavailable'
                    state['seen'][identity] = dict(info, status='download_unavailable'); continue
                full_title = opened_doc.get('title') or title
                if not isinstance(full_title, str) or len(full_title)>2000 or Path(full_title).suffix.lower()!=suffix:
                    raise Halt('needs_attention', 'ima_client_document_changed')
                result = w.sdk.ingest_local_record(w.root, 'ima', row['collectionId'], {
                    'ref': ref, 'title': full_title, 'published_at': None, 'text_scope': 'metadata',
                    'attachments': [{'asset_ref': ref, 'name': full_title, 'media_type': suffix.lstrip('.')} ]})
                w.counts[{'new':'newRecords','updated':'updatedRecords','unchanged':'unchangedRecords'}[result['change']]] += 1
                w.state['hasRecords'] = True
                saved = w.sdk.inspect_ingested_record(w.root, 'ima', row['collectionId'], ref)
                prior = next(a for a in saved['attachments'] if a['asset_ref'] == ref)
                if prior.get('verified'):
                    w.counts['reused'] += 1; document_id = prior['document_id']
                else:
                    remaining = w.limits['maxBytesMiB']*1024*1024 - w.counts['bytes']
                    if remaining <= 0: raise Halt('budget_paused', 'byte_budget_exhausted')
                    # Official UI has no declared size. Stage under a job-owned
                    # directory, enforce local acceptance cap, never overwrite originals.
                    staging = w.checkpoint_path.parent / 'client-staging'
                    staging.mkdir(exist_ok=True, mode=0o700)
                    with tempfile.TemporaryDirectory(prefix='file-', dir=staging) as folder:
                        output = Path(folder) / ('original' + suffix)
                        native.call('download', mediaId=media, destination=str(output))
                        size = output.stat().st_size
                        if size <= 0 or size > min(remaining, w.limits['maxFileMiB']*1024*1024):
                            state['failures'][identity] = 'asset_exceeds_authorized_budget'
                            state['seen'][identity] = dict(info, status='size_review'); continue
                        raw = output.read_bytes()
                        if suffix == '.pdf' and not raw.startswith(b'%PDF-'): raise Halt('needs_attention','pdf_magic_mismatch')
                        if suffix in {'.docx','.xlsx','.pptx'}:
                            with zipfile.ZipFile(output) as z:
                                if len(z.infolist())>10000 or sum(i.file_size for i in z.infolist())>512*1024*1024:
                                    raise Halt('needs_attention','invalid_asset_payload')
                                if z.testzip() is not None: raise Halt('needs_attention','invalid_asset_payload')
                        committed = w.sdk.ingest_local_asset(w.root,'ima',row['collectionId'],ref,ref,raw)
                        document_id = committed['document_id']; w.counts['downloaded'] += 1; w.counts['bytes'] += size
                if document_id not in w.state['parseIds']: w.state['parseIds'].append(document_id)
                state['seen'][identity] = dict(info,status='downloaded',mediaId=media)
            except zipfile.BadZipFile:
                state['failures'][identity] = 'ima_client_file_validation_failed'
                state['seen'][identity] = dict(info, status='validation_failed')
            except Halt as exc:
                if exc.code not in {'pdf_magic_mismatch', 'invalid_asset_payload', 'ima_client_download_unavailable'}: raise
                state['failures'][identity] = exc.code
                state['seen'][identity] = dict(info, status='file_failed')
            finally:
                if opened_doc.get('closeAfter') and not w.stopped:
                    native.call('close_document',mediaId=media)
                w.checkpoint()
        signature = hashlib.sha256(json.dumps(items,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        stalled = stalled + 1 if signature == last else 0; last = signature
        state['seenCount'] = len(state['seen']); w.checkpoint()
        w.update('client_downloading')
        if total is not None and len(state['seen']) == total:
            state['done'] = True; break
        if stalled >= 3:
            state['scanIncomplete'] = True; break
        native.call('scroll', libraryId=library)
    if state.get('scanIncomplete') or state['failures']:
        issue = dict(provider='ima',collectionId=row['collectionId'],name=row['name'],
                     code='ima_client_items_pending' if state['failures'] else 'ima_client_inventory_incomplete',
                     count=len(state['failures']))
        if issue not in w.issues: w.issues.append(issue)


def run_scoped(w, row):
    """A missing library layout cannot block independent sibling libraries."""
    try: run_library(w, row)
    except w.halt_type as exc:
        scoped = exc.code in {'ima_client_library_ambiguous', 'ima_client_library_unverified', 'ima_client_scroll_unavailable'}
        scoped = scoped or (exc.code == 'ima_client_ui_timeout' and getattr(exc, 'client_command', None) == 'list')
        if not scoped: raise
        w.block_collection(row, exc.code)
    w.checkpoint()
