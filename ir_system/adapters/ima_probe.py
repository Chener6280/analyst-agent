"""Bounded permission evidence, using only the public ir_search SDK.

Sample bytes live in memory only: no archive, parse, model or transcript writes.
Directory visibility and one sample's permission are deliberately separate.
"""
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re
from ima_probe_state import checkpoint, position, clean_title, diagnostics, MAX_POSITIONS, MAX_CHECKPOINT_BYTES
import json


DENIED = {'entitlement_denied', 'permission_denied', 'blocked_by_policy'}
FATAL = {'rate_limit', 'authentication_required', 'authentication_failed', 'unauthorized',
         'invalid_credentials', 'credential_missing', 'operation_budget_exhausted',
         'deadline_exceeded', 'cancelled'}
INCONCLUSIVE = {'asset_exceeds_max_bytes', 'media_excluded_by_policy', 'ima_original_unavailable',
                'ima_media_type_not_exportable', 'web_content_unsupported', 'notes_do_not_provide_file_bytes',
                'public_web_original_not_exported_as_bytes'}
TYPES = {'pdf', 'docx', 'pptx', 'xlsx', 'txt', 'html'}
EXTENSIONS = {'.pdf', '.docx', '.pptx', '.xlsx', '.txt', '.md', '.html', '.csv'}
MAX_LIBRARIES = 25
MAX_SAMPLE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 32 * 1024 * 1024


def probe(worker, selected, checkpoints=None):
    # No caller-supplied URLs, dates, sample refs, budgets or executable names.
    if (not isinstance(selected, list) or not 1 <= len(selected) <= MAX_LIBRARIES
            or any(not isinstance(x, str) or not re.fullmatch(r'[A-Za-z0-9_+=.-]{1,512}', x) for x in selected)
            or len(set(selected)) != len(selected)):
        raise ValueError('sync_plan_invalid')
    if checkpoints is not None and (not isinstance(checkpoints, dict) or set(checkpoints) - set(selected)):
        raise ValueError('sync_plan_invalid')
    worker.probe_search = {cid: checkpoint((checkpoints or {}).get(cid)) for cid in selected}
    worker.limits.update(maxOperations=100, maxSeconds=180)
    worker.probes = [dict(collectionId=x, status='unverified', code='not_tested') for x in selected]
    worker.counts.update(samplesAttempted=0, samplesPassed=0, sampleBytes=0)
    # Fresh full subscription scan before every probe, including new subscriptions.
    try:
        worker.scan(['ima'])
    except Exception as exc:
        from sync_worker import safe_code
        worker.probe_diagnostic = diagnostics(exc, phase='subscription_scan', code=safe_code(exc))
        raise
    source = worker.catalog['sources'][0]
    current = {x['collectionId']: x for x in source['collections']}
    prior = {x['collectionId']: x for s in (worker.baseline or {}).get('sources', [])
             if s['provider'] == 'ima' for x in s['collections']}
    from sync_worker import Halt, safe_code

    def finish(row, status, code, **extra):
        if status != 'api_sample_ok' and 'diagnostic' not in extra:
            extra['diagnostic'] = diagnostics(phase='sample_read' if row.get('sampleRef') else 'directory_page', code=code)
        row.update(status=status, code=code, checkedAt=datetime.now(timezone.utc).isoformat(), **extra)
        worker.update('probing_permissions')

    for row in worker.probes:
        worker.probe_active = None
        worker.check()
        cid = row['collectionId']
        entry = current.get(cid)
        if entry is None:
            finish(row, 'not_visible', 'selected_collection_not_visible'); continue
        before = prior.get(cid)
        fields = ('name',)
        if not before or before.get('present') is False or any(before.get(k) != entry.get(k) for k in fields):
            finish(row, 'review_required', 'subscription_status_changed'); continue
        state = worker.probe_search[cid]
        worker.probe_active = cid
        sample, pages, skipped, phase = state['sample'], 0, 0, 'directory_page'
        row.update(pagesChecked=0, pagesTotal=state['pagesTotal'], skippedMedia=0)
        worker.update('probing_permissions')
        try:
            # Save only after a complete page; an interrupted page stays at the head.
            while state['queue'] and pages < 3 and sample is None:
                folder, cursor = state['queue'][0]
                mark = position(folder, cursor)
                if mark in state['visited']:
                    finish(row, 'unverified', 'pagination_cycle'); break
                page = worker.call(worker.sdk.list_collection_directory, 'ima', cid,
                                   folder_id=folder, cursor=cursor, limit=20)
                pending = state['queue'][1:]
                for item in page['items']:
                    if item.get('type') == 'folder':
                        pair = [item['folder_id'], '']
                        if position(*pair) not in state['visited'] and pair not in pending:
                            pending.append(pair)
                        continue
                    if item.get('type') not in TYPES:
                        skipped += 1; continue
                    for asset in item.get('attachments', []):
                        suffix = Path(asset.get('name', '').strip()).suffix.lower()
                        ref = asset.get('asset_ref', '')
                        # A trusted SDK document type can supply a missing extension,
                        # but never override an explicit conflicting/audio extension.
                        if not suffix: suffix = '.' + item['type']
                        if sample is None and suffix in EXTENSIONS and re.fullmatch(r'ima://media/[A-Za-z0-9_+=.-]{1,512}', ref):
                            sample = dict(ref=ref, suffix=suffix, title=clean_title(item.get('title') or asset.get('name')), folderId=folder)
                if page.get('has_more'):
                    following = page.get('next_cursor')
                    if not following or following == cursor:
                        finish(row, 'unverified', 'pagination_stalled'); break
                    pending.append([folder, following])
                if len(pending) > MAX_POSITIONS or len(state['visited']) >= MAX_POSITIONS:
                    finish(row, 'unverified', 'probe_checkpoint_budget_exhausted'); break
                updated = dict(state, queue=pending, visited=state['visited'] + [mark], sample=sample,
                               pagesTotal=state['pagesTotal'] + 1, skippedTotal=state['skippedTotal'] + skipped - row['skippedMedia'])
                if len(json.dumps(updated).encode()) > MAX_CHECKPOINT_BYTES:
                    finish(row, 'unverified', 'probe_checkpoint_budget_exhausted'); break
                state.update(updated)
                pages += 1
                row.update(pagesChecked=pages, pagesTotal=state['pagesTotal'], skippedMedia=skipped)
                worker.update('probing_permissions')
            if row['code'] in {'pagination_cycle', 'pagination_stalled', 'probe_checkpoint_budget_exhausted'}: continue
            if not sample:
                finish(row, 'unverified', 'sample_not_found_in_budget' if state['queue'] else 'sample_search_exhausted'); continue
            remaining = MAX_TOTAL_BYTES - worker.counts['sampleBytes']
            if remaining <= 0: raise Halt('budget_paused', 'sample_byte_budget_exhausted')
            row.update(sampleRef=sample['ref'], sampleTitle=sample['title'], sampleFolderId=sample['folderId'])
            phase = 'sample_read'
            worker.counts['samplesAttempted'] += 1
            reply = worker.call(worker.sdk.retrieve_asset, sample['ref'], max_bytes=min(remaining, MAX_SAMPLE_BYTES),
                                media_policy='text_non_audio')
            if reply.get('status') != 'ok':
                reason = reply.get('reason', '')
                reason = reason if isinstance(reason, str) and re.fullmatch(r'[a-z][a-z0-9_]{0,90}', reason) else 'sample_read_failed'
                finish(row, 'sample_denied' if reason in DENIED else 'unverified', reason,
                       diagnostic=diagnostics(reply.get('diagnostics'), phase=phase, code=reason))
                if reason in FATAL or reason not in DENIED | INCONCLUSIVE: raise Halt('needs_attention', reason)
                continue
            raw = reply.get('content')
            if not isinstance(raw, bytes) or not raw or len(raw) > min(remaining, MAX_SAMPLE_BYTES):
                finish(row, 'unverified', 'invalid_sample_payload'); continue
            worker.counts['sampleBytes'] += len(raw)
            if sample['suffix'] == '.pdf' and not raw.startswith(b'%PDF-'):
                finish(row, 'unverified', 'pdf_magic_mismatch'); continue
            worker.counts['samplesPassed'] += 1
            finish(row, 'api_sample_ok', 'sample_read_ok', bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
            # Keep only the sample title/reference, never body, headers or temporary URLs.
            del raw, reply
        except Halt as exc:
            if row['code'] == 'not_tested':
                finish(row, 'unverified', exc.code, diagnostic=diagnostics(exc, phase=phase, code=exc.code))
            raise
        except Exception as exc:
            code = safe_code(exc)
            finish(row, 'sample_denied' if code in DENIED else 'unverified', code,
                   diagnostic=diagnostics(exc, phase=phase, code=code))
            # No blind retries after unknown failures; permission denials are per sample.
            if code not in DENIED: raise Halt('needs_attention', code) from None
    worker.update('finished')
    passed = all(x['status'] == 'api_sample_ok' for x in worker.probes)
    return worker.result('completed' if passed else 'partial', None if passed else 'permission_probe_gaps')
