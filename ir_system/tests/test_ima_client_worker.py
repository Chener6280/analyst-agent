"""Native client routing tests use synthetic UI fixtures and real local ingest."""
from datetime import date
from pathlib import Path
import json
import pytest
from test_sync_worker import Worker, Halt, fake_sdk, plan, item
import ima_client_worker as client


class FakeNative:
    def __init__(self, w, pages=None):
        self.w=w; self.calls=[]; self.position=0
        self.pages=pages or [[{'title':'fixture.pdf','displayDate':'2026/09/25'}]]
        self.total=sum(len(page) for page in self.pages)

    def call(self, command, **args):
        self.w.check(); self.calls.append((command,args)); self.w.counts['operations']+=1
        if command=='open_library': return {'libraryId':'123456'}
        if command=='list': return {'items':self.pages[self.position], 'totalLabel':f'内容({self.total})'}
        if command=='scroll':
            self.position=0 if args.get('direction')=='top' else min(self.position+1,len(self.pages)-1)
        if command=='open_file': return {'mediaId':'fixture_pdf','downloadAvailable':True,'closeAfter':True}
        if command=='download':
            import fitz
            doc=fitz.open(); doc.new_page().insert_text((40,40),'Official UI synthetic research 567.89')
            Path(args['destination']).write_bytes(doc.tobytes());doc.close()
        return {'status':'ok'}


def install(monkeypatch, pages=None):
    natives=[]
    def factory(w):
        n=FakeNative(w,pages);natives.append(n);return n
    monkeypatch.setattr(client,'available',lambda:True)
    monkeypatch.setattr(client,'Native',factory)
    return natives


def test_beijing_display_dates_keep_filename_out_of_filter():
    today=date(2026,9,27)
    assert client.display_day('WORD 9/27',today)=='2026-09-27'
    assert client.display_day('PDF 16:29',today)=='2026-09-27'
    assert client.display_day('笔记 9/17更新',today)=='2026-09-17'
    assert client.display_day('25:29',today) is None
    assert client.display_day('昨天',today)=='2026-09-26'
    assert client.display_day('2025/12/31',today)=='2025-12-31'
    assert client.display_day('12/31',today)=='2025-12-31'
    assert client.display_day('report_20260927.pdf',today) is None
    assert client.display_day('2/30',today) is None


def test_permission_granted_during_prompt_continues_without_rethrow(tmp_path, monkeypatch):
    original = FakeNative.call
    checked = []
    def grant(self, command, **args):
        if command == 'check':
            checked.append(command)
            if len(checked) == 1: raise Halt('needs_attention', 'ima_accessibility_required')
        return original(self, command, **args)
    monkeypatch.setattr(FakeNative, 'call', grant)
    install(monkeypatch)
    w = Worker(fake_sdk()); w.ima_client_collections = ['kb1']
    result = w.run(plan(tmp_path), tmp_path/'job')
    assert result['status'] == 'completed'
    assert result['counts']['downloaded'] == 1
    assert len(checked) == 2


@pytest.mark.parametrize('phase',['preflight','enumeration'])
def test_quota_routes_to_native_same_scope_and_public_ingest(tmp_path,monkeypatch,phase):
    from ir_search.registry import DataAdapterError
    api=fake_sdk(); listing=api.list_collection_directory
    calls=[]
    def quota(*args,**kwargs):
        calls.append(kwargs['limit'])
        if phase=='preflight' or kwargs['limit']!=1: raise DataAdapterError('ima_daily_quota_exhausted')
        return listing(*args,**kwargs)
    api.list_collection_directory=quota
    natives=install(monkeypatch)
    w=Worker(api); result=w.run(plan(tmp_path),tmp_path/'job')
    assert result['status']=='completed'
    assert result['counts']['downloaded']==result['counts']['parsed']==1
    assert w.state['imaApiUnavailable'] is True
    assert not api.downloads
    assert [a['name'] for c,a in natives[0].calls if c=='open_library']==['fixture']
    assert w.state['collections']['ima:kb1']['route']=='ima_client'
    assert w.state['collections']['ima:kb1']['apiCheckpoint'] is not None
    # Same checkpoint does not re-open or re-download the client record.
    again=Worker(api).run(plan(tmp_path),tmp_path/'job')
    assert again['counts']['downloaded']==0
    assert len(calls)==(1 if phase=='preflight' else 2)


def test_client_selection_does_not_fake_api_permission(tmp_path,monkeypatch):
    api=fake_sdk();api.list_collection_directory=lambda *a,**k:pytest.fail('client route must not probe API')
    install(monkeypatch)
    w=Worker(api);w.ima_client_collections=['kb1']
    result=w.run(plan(tmp_path),tmp_path/'job')
    assert result['status']=='completed'
    assert 'directoryAccess' not in w.catalog['sources'][0]['collections'][0]


def test_native_scan_date_audio_and_inventory_gaps_not_claimed_complete(tmp_path,monkeypatch):
    pages=[[{'title':'outside_20260925.pdf','displayDate':'2025/01/01'},
            {'title':'voice.mp3','displayDate':'2026/09/25'},
            {'title':'unknown.pdf','displayDate':''}]]
    natives=install(monkeypatch,pages)
    w=Worker(fake_sdk());w.ima_client_collections=['kb1']
    result=w.run(plan(tmp_path),tmp_path/'job')
    assert result['status']=='partial' and result['coverageComplete'] is False
    assert result['counts']['audioDeferred']==1
    assert not any(c=='open_file' for c,a in natives[0].calls)
    assert w.state['collections']['ima:kb1']['failures']


def test_stalled_inventory_is_partial_and_cannot_advance_watermark(tmp_path,monkeypatch):
    install(monkeypatch)
    original=client.Native
    def factory(w):
        n=original(w);n.total=5;return n
    monkeypatch.setattr(client,'Native',factory)
    w=Worker(fake_sdk());w.ima_client_collections=['kb1']
    result=w.run(plan(tmp_path),tmp_path/'job')
    assert result['status']=='partial'
    assert result['issues'][0]['code']=='ima_client_inventory_incomplete'
    assert w.state['collections']['ima:kb1']['done'] is False


def test_failed_item_does_not_block_good_sibling_and_retry_is_bounded(tmp_path):
    api=fake_sdk([item('bad','unknown.bin','unknown'),item('good')])
    w=Worker(api);result=w.run(plan(tmp_path),tmp_path/'job')
    assert result['status']=='partial'
    assert result['counts']['downloaded']==result['counts']['parsed']==1
    pending=list(w.state['retryItems'].values())
    assert len(pending)==1 and pending[0]['attempts']==2
    assert api.downloads==['ima://media/good']


def test_parse_failure_keeps_going_and_is_durable(tmp_path):
    api=fake_sdk([item('one'),item('two')]);parse=api.parse_local_archive
    attempts=[]
    def mixed(*a,**k):
        attempts.append(k['document_ids'][0])
        if len(attempts)==1: return {'status':'partial','attempted':1,'results':[{'status':'needs_ocr'}]}
        return parse(*a,**k)
    api.parse_local_archive=mixed
    result=Worker(api).run(plan(tmp_path),tmp_path/'job')
    assert len(attempts)==2 and result['counts']['parsed']==1
    assert result['status']=='partial' and result['issues'][0]['code']=='needs_ocr'
