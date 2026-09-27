"""Offline IMA evidence tests: zero source calls, archive or document writes."""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / 'adapters'))
from sync_worker import Worker, Halt
from ima_probe import probe, MAX_SAMPLE_BYTES
from test_sync_worker import fake_sdk, item


def worker(api, **prior):
    return Worker(api, baseline={'sources': [{'provider': 'ima', 'collections': [
        dict(collectionId='kb1', name='fixture', directoryAccess='accessible', accessCode=None, **prior)]}]})


def test_sample_pass_no_content_or_archive_writes(tmp_path):
    api = fake_sdk([item(), item('second')])
    w = worker(api)
    result = probe(w, ['kb1'])
    assert result['status'] == 'completed'
    assert api.downloads == ['ima://media/one']
    assert result['imaProbes'][0]['status'] == 'api_sample_ok'
    assert result['counts']['downloaded'] == result['counts']['parsed'] == 0
    assert result['counts']['samplesPassed'] == 1
    assert not list(tmp_path.iterdir())
    import json
    text = json.dumps(result)
    assert 'Synthetic research' not in text and 'content' not in result['imaProbes'][0]


def test_sample_denial_is_not_whole_library_or_client_proof():
    w = worker(fake_sdk([item()], download_status='failed'))
    result = probe(w, ['kb1'])
    assert result['status'] == 'partial'
    assert result['imaProbes'][0]['status'] == 'sample_denied'
    assert result['imaProbes'][0]['code'] == 'entitlement_denied'


def test_missing_and_changed_scopes_do_not_read_files_or_guess_ids():
    api = fake_sdk([item()])
    result = probe(worker(api, present=False), ['kb1', 'missing'])
    assert [x['status'] for x in result['imaProbes']] == ['review_required', 'not_visible']
    assert api.downloads == []


def test_no_sample_audio_webpage_and_unknown_skipped():
    api = fake_sdk([item('audio', 'a.mp3', 'audio'), item('web', 'w.html', 'webpage'), item('x', 'x.zip', 'document')])
    result = probe(worker(api), ['kb1'])
    assert result['imaProbes'][0]['code'] == 'sample_search_exhausted'
    assert api.downloads == []


def test_folder_walk_is_bounded_and_searches_only_explicit_directory():
    def page(items, following=None): return dict(items=items, has_more=bool(following), next_cursor=following)
    directory = {(None, ''): page([dict(type='folder', folder_id='f')]),
                 ('f', ''): page([item('a', 'a.mp3', 'audio')], 'next'),
                 ('f', 'next'): page([item('ok')])}
    api = fake_sdk(directory=directory)
    result = probe(worker(api), ['kb1'])
    assert result['imaProbes'][0]['pagesChecked'] == 3
    assert api.downloads == ['ima://media/ok']


def test_rate_limit_stops_and_preserves_unprobed_rows():
    api = fake_sdk([item()])
    def denied(ref, *, context, max_bytes, media_policy):
        context.begin_operation()
        return {'status': 'failed', 'reason': 'rate_limit'}
    api.retrieve_asset = denied
    w = worker(api)
    with pytest.raises(Halt) as e: probe(w, ['kb1', 'missing'])
    assert e.value.code == 'rate_limit'
    assert w.result('needs_attention')['imaProbes'][1]['code'] == 'not_tested'


def test_declared_success_with_invalid_bytes_never_passes():
    api = fake_sdk([item()])
    def invalid(ref, *, context, max_bytes, media_policy):
        assert max_bytes == MAX_SAMPLE_BYTES and media_policy == 'text_non_audio'
        return {'status': 'ok', 'content': b'<html>login</html>', 'url': 'secret'}
    api.retrieve_asset = invalid
    result = probe(worker(api), ['kb1'])
    assert result['imaProbes'][0]['code'] == 'pdf_magic_mismatch'
    assert result['counts']['samplesPassed'] == 0
    assert 'secret' not in str(result)


def test_directory_not_found_is_not_a_permission_denial():
    from ir_search.registry import DataAdapterError
    api = fake_sdk()
    def missing(*args, **kwargs): raise DataAdapterError('not_found')
    api.list_collection_directory = missing
    w = worker(api)
    with pytest.raises(Halt): probe(w, ['kb1'])
    result = w.result('needs_attention')
    assert result['imaProbes'][0]['status'] == 'unverified'
    assert result['imaProbes'][0]['code'] == 'not_found'
    assert api.downloads == []


@pytest.mark.parametrize('selection', [[], ['a', 'a'], ['https://example.com'], ['a'] * 26, None])
def test_bad_scope_fails_before_network(selection):
    api = fake_sdk()
    with pytest.raises(ValueError): probe(worker(api), selection)
    assert api.downloads == []


def test_search_resumes_on_fourth_page_and_accepts_typed_document_without_extension():
    pages = {(None, ''): dict(items=[item('a', 'a.mp3', 'audio')], has_more=True, next_cursor='p2'),
             (None, 'p2'): dict(items=[], has_more=True, next_cursor='p3'),
             (None, 'p3'): dict(items=[], has_more=True, next_cursor='p4'),
             (None, 'p4'): dict(items=[item('found', '产业链研究', 'pdf')], has_more=False, next_cursor=None)}
    api = fake_sdk(directory=pages)
    calls, original = [], api.list_collection_directory
    def listing(*args, **kw):
        if kw['limit'] == 20: calls.append(kw['cursor'])
        return original(*args, **kw)
    api.list_collection_directory = listing
    first = probe(worker(api), ['kb1'])
    assert first['imaProbes'][0]['code'] == 'sample_not_found_in_budget'
    assert first['imaProbeSearch']['kb1']['queue'] == [[None, 'p4']]
    second = probe(worker(api), ['kb1'], first['imaProbeSearch'])
    assert calls == ['', 'p2', 'p3', 'p4']
    assert second['status'] == 'completed'
    assert second['imaProbes'][0]['sampleTitle'] == '产业链研究'
    assert second['imaProbes'][0]['pagesChecked'] == 1
    assert second['imaProbes'][0]['pagesTotal'] == 4


def test_failed_directory_page_is_not_consumed_and_diagnostics_are_redacted():
    from ir_search.registry import DataAdapterError
    api = fake_sdk([item()])
    original = api.list_collection_directory
    def failed(*args, **kw):
        if kw['limit'] == 20:
            exc = DataAdapterError('ima_upstream_rejected')
            exc.diagnostics = {'operation': 'get_knowledge_list', 'httpStatus': 200, 'providerCode': 765432,
                               'message': 'secret', 'headers': {'Cookie': 'secret'}, 'url': 'https://secret'}
            raise exc
        return original(*args, **kw)
    api.list_collection_directory = failed
    w = worker(api)
    with pytest.raises(Halt): probe(w, ['kb1'])
    result = w.result('needs_attention')
    assert result['imaProbeSearch']['kb1']['queue'] == [[None, '']]
    assert result['imaProbeSearch']['kb1']['visited'] == []
    d = result['imaProbes'][0]['diagnostic']
    assert d['phase'] == 'directory_page' and d['providerCode'] == 765432
    assert 'secret' not in str(result)
    api.list_collection_directory = original
    assert probe(worker(api), ['kb1'], result['imaProbeSearch'])['status'] == 'completed'


def test_denied_sample_is_rechecked_without_rewalking_and_retains_title():
    api = fake_sdk([item('denied', '<script>not instructions</script>.pdf')], download_status='failed')
    first = probe(worker(api), ['kb1'])
    original = api.list_collection_directory
    def only_scan(*args, **kw):
        assert kw['limit'] == 1
        return original(*args, **kw)
    api.list_collection_directory = only_scan
    second = probe(worker(api), ['kb1'], first['imaProbeSearch'])
    assert api.downloads == ['ima://media/denied'] * 2
    assert second['imaProbes'][0]['pagesChecked'] == 0
    assert second['imaProbes'][0]['sampleTitle'] == '<script>not instructions</script>.pdf'


def test_known_document_type_does_not_override_audio_extension_or_unknown_type():
    api = fake_sdk([item('a', 'a.mp3', 'pdf'), item('b', 'title', 'unknown')])
    assert probe(worker(api), ['kb1'])['imaProbes'][0]['code'] == 'sample_search_exhausted'
    assert not api.downloads


def test_directory_error_keeps_library_diagnostic_and_inventory_complete():
    from ir_search.registry import DataAdapterError
    api = fake_sdk()
    def fail(*args, **kw):
        exc = DataAdapterError('ima_upstream_rejected')
        exc.diagnostics = {'operation': 'get_knowledge_list', 'providerCode': 987654, 'httpStatus': 200}
        raise exc
    api.list_collection_directory = fail
    w = worker(api)
    with pytest.raises(Halt): probe(w, ['kb1'])
    result = w.result('needs_attention')
    assert result['catalog']['complete'] is True
    assert result['imaProbes'][0]['diagnostic']['providerCode'] == 987654
    assert result['imaProbes'][0]['diagnostic']['phase'] == 'directory_page'
    assert result['imaProbes'][0]['code'] == 'ima_upstream_rejected'


def test_checkpoint_validation_and_exhaustion_never_guess_a_new_start():
    from ima_probe_state import checkpoint
    api = fake_sdk()
    with pytest.raises(ValueError, match='checkpoint_invalid'):
        probe(worker(api), ['kb1'], {'kb1': {'queue': [['secret', 'url']]}})
    exhausted = checkpoint(); exhausted['queue'] = []
    result = probe(worker(api), ['kb1'], {'kb1': exhausted})
    assert result['imaProbes'][0]['pagesChecked'] == 0
    assert result['imaProbes'][0]['code'] == 'sample_search_exhausted'
    assert not api.downloads


def test_progress_emits_completed_page_before_next_call():
    from copy import deepcopy
    api = fake_sdk(directory={(None, ''): dict(items=[], has_more=True, next_cursor='next'),
                              (None, 'next'): dict(items=[item()], has_more=False, next_cursor=None)})
    events = []
    w = worker(api); w.progress = lambda event: events.append(deepcopy(event))
    probe(w, ['kb1'])
    assert any(e.get('imaProbeSearch', {}).get('kb1', {}).get('queue') == [[None, 'next']] for e in events)
