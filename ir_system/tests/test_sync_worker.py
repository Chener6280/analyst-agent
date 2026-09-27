"""Synthetic end-to-end worker checks; no online requests or production writes."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
import ir_search

spec = importlib.util.spec_from_file_location('sync_worker', Path(__file__).parents[1] / 'adapters/sync_worker.py')
worker_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker_module)
Worker, Halt = worker_module.Worker, worker_module.Halt


def plan(root, **budgets):
    return {'schemaVersion': 1, 'kind': 'incremental', 'archiveRoot': str(root),
            'collections': [{'provider': 'ima', 'collectionId': 'kb1', 'name': 'fixture', 'mode': 'incremental',
                             'firstDate': '2026-01-01', 'start': '2026-01-01', 'end': '2026-09-26'}],
            'budgets': dict(maxOperations=30, maxRecords=100, maxFiles=20, maxBytesMiB=10, maxFileMiB=5, maxParses=20, maxSeconds=60, **{}) | budgets,
            'media': 'text_non_audio', 'includeNotes': False}


def fake_sdk(items=None, directory=None, download_status='ok'):
    api = SimpleNamespace(**{n: getattr(ir_search, n) for n in ir_search.__all__ if hasattr(ir_search, n)})
    api.downloads = []
    def collections(provider, *, context):
        context.begin_operation()
        return {'collections': [{'collection_id': 'kb1', 'name': 'fixture'}], 'exhaustive': True}
    def listing(provider, collection, *, folder_id, cursor, limit, context):
        context.begin_operation()
        result = directory.get((folder_id, cursor)) if directory else {'items': items or [], 'next_cursor': None, 'has_more': False}
        return result
    def download(ref, *, max_bytes, context, media_policy):
        assert media_policy == 'text_non_audio'
        context.begin_operation(); api.downloads.append(ref)
        import fitz
        doc = fitz.open(); page = doc.new_page(); page.insert_text((40, 40), 'Synthetic research 123.45')
        raw = doc.tobytes(); doc.close()
        return {'status': download_status, 'content': raw, 'reason': 'entitlement_denied'}
    api.list_material_collections = collections; api.list_collection_directory = listing; api.retrieve_asset = download
    return api


def item(identifier='one', name='report.pdf', media='pdf'):
    return {'ref': 'ima://media/' + identifier, 'title': name, 'type': media,
            'attachments': [{'asset_ref': 'ima://media/' + identifier, 'name': name, 'media_type': media}]}


def test_real_ingest_parse_index_replay_and_text_first(tmp_path):
    pytest.importorskip('fitz')
    api = fake_sdk([item(), item('audio', 'audio.mp3', 'audio')])
    job = tmp_path / 'job'
    first = Worker(api).run(plan(tmp_path), job)
    assert first['status'] == 'completed'
    assert first['counts']['downloaded'] == first['counts']['parsed'] == 1
    assert first['counts']['audioDeferred'] == 1
    assert first['counts']['audioDownloads'] == first['counts']['asrCalls'] == 0
    assert ir_search.search_local_archive(tmp_path, query='123.45')['total'] == 1
    again = Worker(api).run(plan(tmp_path), tmp_path / 'job2')
    assert again['counts']['downloaded'] == 0 and again['counts']['reused'] == 1
    assert len(api.downloads) == 1


def test_folder_recursion_pagination_and_record_budget_resume(tmp_path):
    folder = {'ref': 'ima://media/f1', 'title': 'nested', 'type': 'folder', 'folder_id': 'f1'}
    pages = {(None, ''): {'items': [folder, item('a'), item('b')], 'next_cursor': None, 'has_more': False},
             ('f1', ''): {'items': [item('c')], 'next_cursor': None, 'has_more': False}}
    api = fake_sdk(directory=pages)
    p = plan(tmp_path, maxRecords=1)
    job = tmp_path / 'job'
    for _ in range(2):
        with pytest.raises(Halt) as exc: Worker(api).run(p, job)
        assert exc.value.code == 'record_budget_exhausted'
    result = Worker(api).run(p, job)
    assert result['status'] == 'completed'
    assert sorted(api.downloads) == ['ima://media/a', 'ima://media/b', 'ima://media/c']


def test_stop_errors_scope_and_unknown_media_fail_closed(tmp_path):
    api = fake_sdk([item(name='mystery.bin', media='unknown')])
    result = Worker(api).run(plan(tmp_path), tmp_path / 'job')
    assert result['status'] == 'partial' and not api.downloads
    assert any(i['code'] == 'media_type_requires_confirmation' for i in result['issues'])
    with pytest.raises(ValueError): Worker(api).run(plan(tmp_path, maxFiles=-1), tmp_path / 'invalid')
    worker = Worker(api); worker.stop()
    with pytest.raises(Halt) as exc: worker.run(plan(tmp_path), tmp_path / 'stopped')
    assert exc.value.status == 'stopped'
    with worker_module.root_lock(tmp_path): pass  # Persistent lock file is unlocked, not deleted.


def test_old_sdk_rejected_before_scanning_or_writing(tmp_path):
    api = fake_sdk([])
    api.retrieve_asset = lambda ref, max_bytes, context: None
    api.list_material_collections = lambda *args, **kwargs: pytest.fail('must fail before network')
    with pytest.raises(ValueError, match='sdk_sync_api_missing'):
        Worker(api).run(plan(tmp_path), tmp_path / 'job')
    assert list(tmp_path.iterdir()) == []


def test_ima_daily_quota_preserves_permission_evidence_and_safe_diagnostic(tmp_path):
    from ir_search.registry import DataAdapterError
    api = fake_sdk()
    def limited(*args, **kwargs):
        error = DataAdapterError('ima_daily_quota_exhausted')
        error.diagnostics = {'operation': 'get_knowledge_list', 'providerCode': 220021,
                             'httpStatus': 200, 'raw': 'never expose'}
        raise error
    api.list_collection_directory = limited
    w = Worker(api)
    with pytest.raises(Halt) as error:
        w.run(plan(tmp_path), tmp_path / 'job')
    assert error.value.code == 'ima_daily_quota_exhausted'
    report = w.result(error.value.status, error.value.code)
    assert report['diagnostic']['providerCode'] == 220021
    assert 'raw' not in report['diagnostic']
    assert 'directoryAccess' not in w.catalog['sources'][0]['collections'][0]
    assert not api.downloads


def test_browser_failure_not_misattributed_to_successful_indexing(tmp_path):
    w = Worker(fake_sdk())
    w.root = tmp_path; w.checkpoint_path = tmp_path / 'checkpoint.json'
    w.state = {'collections': {}, 'parseIds': [], 'hasRecords': False}
    w.checkpoint = lambda: None
    w.web_request = lambda request: {'status': 'interrupted', 'code': 'browser_interrupted',
                                    'manifest': {'record_refs': ['zsxq://topic/123']}}
    w.queue_web_parses = lambda *args: w.update('indexing')
    with pytest.raises(Halt):
        w.enumerate_web({'provider': 'zsxq', 'collectionId': '123', 'start': '2026-09-27', 'end': '2026-09-27'})
    assert w.stage == 'web_downloading'
    assert not w.state['collections']['zsxq:123']['done']


def test_custom_history_before_incremental_origin_keeps_public_plan_valid(tmp_path):
    p = plan(tmp_path)
    p['kind'] = 'backfill'
    p['collections'][0].update(start='2025-01-01', end='2025-01-31')
    assert worker_module.validate(p) == tmp_path.resolve()
    p['kind'] = 'incremental'
    assert worker_module.validate(p) == tmp_path.resolve()


def test_changed_subscription_stops_before_content_download(tmp_path):
    api = fake_sdk([item()])
    baseline = {'sources': [{'provider': 'ima', 'collections': [
        {'collectionId': 'kb1', 'name': 'fixture', 'directoryAccess': 'unavailable', 'accessCode': 'entitlement_denied'}]}]}
    result = Worker(api, baseline=baseline).run(plan(tmp_path), tmp_path / 'changed')
    assert result['status'] == 'partial' and result['issues'][0]['code'] == 'subscription_status_changed'
    assert not api.downloads


def test_membership_and_web_route_gates_run_before_downloading(tmp_path):
    api = fake_sdk([item()])
    p = plan(tmp_path)
    p['collections'][0].update(provider='zsxq', collectionId='123')
    row = {'collectionId': '123', 'name': 'fixture', 'membership': {'active': False},
           'skill_api': 'accessible', 'permissions': {'allow_download': True}}
    catalog = {'sources': [{'provider': 'zsxq', 'complete': True, 'collections': [row]}]}
    result = Worker(api, zsxq_catalog=catalog).run(p, tmp_path / 'expired')
    assert result['status'] == 'partial'
    assert result['issues'][0]['code'] == 'membership_expired'
    assert result['issues'][0]['collectionId'] == '123'
    row['membership']['active'] = True
    row['skill_api'] = 'not_enabled'
    with pytest.raises(Halt) as exc:
        Worker(api, zsxq_catalog=catalog).run(p, tmp_path / 'web')
    assert exc.value.code == 'web_runtime_missing'
    assert not api.downloads


def test_failed_download_and_incomplete_scan_never_advance(tmp_path):
    api = fake_sdk([item()], download_status='failed')
    result = Worker(api).run(plan(tmp_path), tmp_path / 'job')
    assert result['status'] == 'partial'
    assert any(i['code'] == 'entitlement_denied' for i in result['issues'])
    assert len(api.downloads) == 2  # Initial attempt + one bounded item retry.
    api.list_material_collections = lambda *a, **k: {'collections': [], 'exhaustive': False}
    with pytest.raises(Halt) as exc: Worker(api).run(plan(tmp_path), tmp_path / 'scan')
    assert exc.value.code == 'subscription_scan_incomplete'


def test_inventory_discovery_never_probes_or_hides_a_new_library():
    api = fake_sdk()
    def broken_directory(*args, **kwargs):
        pytest.fail('inventory must not probe content')
    api.list_collection_directory = broken_directory
    worker = Worker(api)
    worker.limits['maxOperations'] = 1
    result = worker.scan(['ima'])
    assert result['complete'] is True
    assert result['sources'][0]['inventoryOnly'] is True
    assert result['sources'][0]['collections'][0]['collectionId'] == 'kb1'


def test_local_check_is_read_only_and_advisory_lock_file_is_not_ownership(tmp_path):
    lock = tmp_path / '.writer.lock'
    lock.write_bytes(b'')
    before = sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob('*'))
    result = worker_module.check_environment(fake_sdk(), str(tmp_path))
    assert result['status'] == 'ready'
    assert result['networkCalls'] == result['filesWritten'] == 0
    assert lock.read_bytes() == b''
    assert before == sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob('*'))


def test_local_check_reports_real_advisory_ownership_and_derived_sentinel(tmp_path):
    fcntl = pytest.importorskip('fcntl')
    lock = tmp_path / '.writer.lock'
    with lock.open('w') as fd:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = worker_module.check_environment(fake_sdk(), str(tmp_path))
        assert any(r['code'] == 'archive_writer_busy' for r in result['issues'])
    derived = tmp_path / 'derived/local_archive_v1/.writer.lock'
    derived.parent.mkdir(parents=True); derived.write_text('123')
    result = worker_module.check_environment(fake_sdk(), str(tmp_path))
    assert any(r['code'] == 'local_archive_locked' for r in result['issues'])
    assert derived.read_text() == '123'


def test_local_check_rejects_old_media_api_without_downloading(tmp_path):
    api = fake_sdk(); api.retrieve_asset = lambda ref, max_bytes, context: None
    result = worker_module.check_environment(api, str(tmp_path))
    assert any(r['code'] == 'sdk_sync_api_missing' for r in result['issues'])
    assert not api.downloads and list(tmp_path.iterdir()) == []


def test_parse_failure_is_preserved_on_resume_no_silent_skip(tmp_path):
    api = fake_sdk([item()])
    api.parse_local_archive = lambda *a, **k: {'status': 'partial', 'attempted': 1}
    for _ in range(2):
        result = Worker(api).run(plan(tmp_path), tmp_path / 'job')
        assert result['status'] == 'partial'
        assert any(i['code'] == 'parse_requires_review' for i in result['issues'])
    assert len(api.downloads) == 1


def test_cycle_and_page_mutation_stop(tmp_path):
    api = fake_sdk(directory={(None, ''): {'items': [item('a'), item('b')], 'next_cursor': None, 'has_more': False}})
    with pytest.raises(Halt): Worker(api).run(plan(tmp_path, maxRecords=1), tmp_path / 'job')
    changed = fake_sdk([item('different'), item('b')])
    with pytest.raises(Halt) as exc: Worker(changed).run(plan(tmp_path, maxRecords=10), tmp_path / 'job')
    assert exc.value.code == 'material_cursor_stale'
    assert not changed.downloads


@pytest.mark.parametrize('provider,collection', [('zsxq', '100'), ('wisburg', 'archive')])
def test_other_sources_use_public_timeline_and_preserve_summary_scope(tmp_path, provider, collection):
    api = fake_sdk()
    def directory(p, *, context):
        context.begin_operation()
        return {'exhaustive': True, 'collections': [{'collection_id': collection}]}
    def timeline(p, coll, *, published_start, published_end, cursor, include_text, include_notes, max_items, context):
        context.begin_operation()
        assert (p, coll) == (provider, collection) and include_text and not include_notes
        assert published_start == '2026-01-01' and published_end == '2026-09-26'
        return {'coverage': {'state': 'complete'}, 'items': [{'ref': provider + '://article/1',
            'title': 'fixture', 'summary': 'Abstract, not original', 'text_scope': 'abstract', 'attachments': []}]}
    api.list_material_collections = directory; api.export_collection_timeline = timeline
    p = plan(tmp_path); p['collections'][0].update(provider=provider, collectionId=collection)
    catalog = {'sources': [{'provider': 'zsxq', 'complete': True, 'collections': [
        {'collectionId': collection, 'membership': {'active': True}, 'permissions': {'allow_download': True}, 'skill_api': 'accessible'}]}]} if provider == 'zsxq' else None
    result = Worker(api, zsxq_catalog=catalog).run(p, tmp_path / 'job')
    assert result['status'] == 'completed'
    assert ir_search.search_local_archive(tmp_path)['items'][0]['text_scope'] == 'abstract'


def test_root_lock_is_exclusive_and_released_without_file_deletion(tmp_path):
    with worker_module.root_lock(tmp_path):
        with pytest.raises(ValueError, match='locked'):
            with worker_module.root_lock(tmp_path): pass
    with worker_module.root_lock(tmp_path): pass


@pytest.mark.parametrize('kind', ['backfill', 'incremental'])
def test_web_route_indexes_and_parses_only_current_non_audio_records(tmp_path, kind):
    import hashlib
    import json
    import fitz
    api = fake_sdk()
    api.export_collection_timeline = lambda *a, **k: pytest.fail('web group must not call timeline API')
    p = plan(tmp_path); p['kind'] = kind; p['collections'][0].update(provider='zsxq', collectionId='123')
    catalog = {'complete': True, 'scannedAt': '2026-09-27T00:00:00Z', 'sources': [{'provider': 'zsxq', 'complete': True, 'collections': [
        {'collectionId': '123', 'group_id': '123', 'scan_status': 'ok', 'name': 'fixture', 'membership': {'active': True},
         'skill_api': 'not_enabled', 'permissions': {'allow_download': True, 'allow_copy': False}}]}]}
    requests = []
    class WebWorker(Worker):
        def web_request(self, request):
            requests.append(request)
            assert request['row']['start'] == '2026-01-01'
            assert request['limits']['maxFiles'] == p['budgets']['maxFiles']
            pdf = fitz.open(); page = pdf.new_page(); page.insert_text((40, 40), 'Web route synthetic 567.89'); raw = pdf.tobytes(); pdf.close()
            sha = hashlib.sha256(raw).hexdigest(); obj = 'objects/' + sha[:2] + '/' + sha
            target = tmp_path / 'zsxq_web' / obj; target.parent.mkdir(parents=True); target.write_bytes(raw)
            record = tmp_path / 'zsxq_web/groups/123/topics/111/record.json'; record.parent.mkdir(parents=True)
            record.write_text(json.dumps({'source_item_id': 'zsxq://topic/111', 'source_collection': '123', 'title': 'Fixture',
                'published_on': '2026-09-20', 'text_scope': 'metadata_only_group_copy_disabled', 'content_text': '',
                'attachments': [{'original_filename': 'fixture.pdf', 'status': 'ok', 'sha256': sha, 'size_bytes': len(raw), 'object_path': obj},
                                {'original_filename': 'later.mp3', 'status': 'deferred', 'reason': 'audio_deferred'}]}))
            return {'status': 'completed', 'counts': {'operations': 4, 'recordsAttempted': 1, 'newRecords': 1, 'downloaded': 1, 'bytes': len(raw), 'audioDeferred': 1},
                    'manifest': {'record_refs': ['zsxq://topic/111'], 'reached_date_floor': True, 'manifest_path': 'zsxq_web/jobs/test/manifest.json'}}
    result = WebWorker(api, zsxq_catalog=catalog).run(p, tmp_path / 'job')
    assert result['status'] == 'completed' and result['coverageComplete'] is False
    assert result['counts']['parsed'] == result['counts']['downloaded'] == 1
    assert result['counts']['audioDeferred'] == 1 and result['counts']['asrCalls'] == result['counts']['audioDownloads'] == 0
    assert ir_search.search_local_archive(tmp_path, query='567.89')['total'] == 1
    # Resume the same task after parsing, without re-entering the browser.
    again = WebWorker(api, zsxq_catalog=catalog).run(p, tmp_path / 'job')
    assert again['status'] == 'completed' and len(requests) == 1


def test_web_failure_preserves_parent_checkpoint_and_never_marks_collection_done(tmp_path):
    api = fake_sdk(); p = plan(tmp_path); p['collections'][0].update(provider='zsxq', collectionId='123')
    catalog = {'sources': [{'provider': 'zsxq', 'complete': True, 'collections': [
        {'collectionId': '123', 'membership': {'active': True}, 'skill_api': 'not_enabled', 'permissions': {'allow_download': True}}]}]}
    class Paused(Worker):
        def web_request(self, request): return {'status': 'budget_paused', 'code': 'operation_budget_exhausted', 'counts': {'operations': 30}}
    worker = Paused(api, zsxq_catalog=catalog)
    with pytest.raises(Halt) as exc: worker.run(p, tmp_path / 'job')
    assert exc.value.status == 'budget_paused'
    assert worker.state['collections']['zsxq:123']['done'] is False
    assert not api.downloads


def test_api_and_web_groups_share_remaining_budget_in_one_task(tmp_path):
    api = fake_sdk()
    def timeline(*args, **kw):
        kw['context'].begin_operation()
        return {'coverage': {'state': 'complete'}, 'items': [{'ref': 'zsxq://topic/1', 'title': 'API fixture', 'attachments': []}]}
    api.export_collection_timeline = timeline
    p = plan(tmp_path, maxRecords=2); base = p['collections'][0]; base.update(provider='zsxq', collectionId='123')
    p['collections'].append(dict(base, collectionId='456'))
    catalog = {'sources': [{'provider': 'zsxq', 'complete': True, 'collections': [
        {'collectionId': identifier, 'membership': {'active': True}, 'skill_api': route, 'permissions': {'allow_download': True}}
        for identifier, route in [('123', 'accessible'), ('456', 'not_enabled')]]}]}
    class Mixed(Worker):
        def web_request(self, request):
            assert request['row']['collectionId'] == '456'
            assert request['limits']['maxRecords'] == 1
            assert request['limits']['maxOperations'] == p['budgets']['maxOperations'] - 1
            return {'status': 'completed', 'counts': {'operations': 2, 'recordsAttempted': 1}, 'manifest': {'record_refs': []}}
    result = Mixed(api, zsxq_catalog=catalog).run(p, tmp_path / 'job')
    assert result['status'] == 'completed' and result['counts']['operations'] == 3 and result['counts']['recordsAttempted'] == 2


@pytest.mark.parametrize('code', ['membership_evidence_conflict', 'membership_expired', 'download_disabled_by_group'])
def test_group_local_failure_continues_healthy_sibling_and_does_not_retry_blocked(tmp_path, code):
    api = fake_sdk()
    p = plan(tmp_path)
    p['collections'][0].update(provider='zsxq', collectionId='123')
    p['collections'].append(dict(p['collections'][0], collectionId='456'))
    catalog = {'sources': [{'provider': 'zsxq', 'complete': True, 'collections': [
        {'collectionId': identifier, 'membership': {'active': True}, 'skill_api': 'not_enabled', 'permissions': {'allow_download': True}}
        for identifier in ['123', '456']]}]}
    seen = []
    class Mixed(Worker):
        def web_request(self, request):
            identifier = request['row']['collectionId']; seen.append(identifier)
            return {'status': 'needs_attention' if identifier == '123' else 'completed',
                    'code': code if identifier == '123' else None, 'counts': {}, 'manifest': {'record_refs': []}}
    first = Mixed(api, zsxq_catalog=catalog).run(p, tmp_path / 'job')
    assert seen == ['123', '456']
    assert first['status'] == 'partial' and first['stage'] == 'finished'
    assert first['issues'][0]['collectionId'] == '123'
    second = Mixed(api, zsxq_catalog=catalog).run(p, tmp_path / 'job')
    assert seen == ['123', '456'] and second['status'] == 'partial'


@pytest.mark.parametrize('code', ['rate_limited', 'human_login_required', 'web_worker_failed'])
def test_global_web_faults_still_stop_all_groups(tmp_path, code):
    api = fake_sdk(); p = plan(tmp_path)
    p['collections'][0].update(provider='zsxq', collectionId='123')
    catalog = {'sources': [{'provider': 'zsxq', 'complete': True, 'collections': [
        {'collectionId': '123', 'membership': {'active': True}, 'skill_api': 'not_enabled', 'permissions': {'allow_download': True}}]}]}
    class Broken(Worker):
        def web_request(self, request):
            return {'status': 'needs_attention', 'code': code, 'counts': {}, 'manifest': {'record_refs': []}}
    with pytest.raises(Halt) as error: Broken(api, zsxq_catalog=catalog).run(p, tmp_path / 'job')
    assert error.value.code == code


def test_superseded_subset_is_not_requested_and_original_checkpoint_hash_is_retained(tmp_path):
    api = fake_sdk(); p = plan(tmp_path)
    p['collections'].append(dict(p['collections'][0], collectionId='kb2'))
    def collections(provider, *, context):
        return {'collections': [{'collection_id': 'kb1', 'name': 'fixture'}, {'collection_id': 'kb2', 'name': 'fixture'}], 'exhaustive': True}
    api.list_material_collections = collections
    queried = []
    def directory(provider, collection, **kw):
        queried.append(collection)
        return {'items': [], 'next_cursor': None, 'has_more': False}
    api.list_collection_directory = directory
    worker = Worker(api); result = worker.run(p, tmp_path / 'job', ['ima:kb1'])
    assert result['status'] == 'completed' and set(queried) == {'kb2'}
    assert worker.state['planHash'] == worker_module.fingerprint({k: v for k, v in p.items() if k != 'budgets'})
    with pytest.raises(ValueError, match='sync_excluded_scope_invalid'):
        Worker(api).run(p, tmp_path / 'wrong', ['ima:outsider'])
