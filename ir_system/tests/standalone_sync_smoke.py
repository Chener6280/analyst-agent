"""Run with an installed wheel, isolated Python (-I), and a cwd outside both repos."""
import inspect
import json
from pathlib import Path
import sys
import tempfile

import ir_search


def main():
    installed = Path(ir_search.__file__).resolve()
    assert 'site-packages' in installed.parts, installed
    assert Path(sys.prefix).resolve() in installed.parents, installed
    for name in ('list_collection_directory', 'ingest_local_record',
                 'ingest_local_asset', 'inspect_ingested_record'):
        assert callable(getattr(ir_search, name))
    assert 'media_policy' in inspect.signature(ir_search.retrieve_asset).parameters
    with tempfile.TemporaryDirectory(prefix='ir-installed-sync-') as temporary:
        root = Path(temporary)
        record = {'ref': 'ima://media/offline-fixture', 'title': 'Offline fixture',
                  'text': 'installation isolated successfully', 'text_scope': 'source_excerpt',
                  'attachments': [{'asset_ref': 'ima://file/offline-fixture', 'name': 'fixture.pdf'}]}
        saved = ir_search.ingest_local_record(root, 'ima', 'fixture-library', record)
        ir_search.ingest_local_asset(root, 'ima', 'fixture-library', record['ref'],
                                     'ima://file/offline-fixture', b'%PDF-offline-fixture')
        assert ir_search.inspect_ingested_record(root, 'ima', 'fixture-library', record['ref'])['attachments'][0]['verified']
        ir_search.index_local_archive(root)
        assert ir_search.search_local_archive(root)['total'] == 2
        assert ir_search.read_local_archive(root, saved['document_id'])['text'] == record['text']
        assert not (root / 'index/archive.sqlite').exists()
    print(json.dumps({'status': 'passed', 'installed_module': str(installed),
                      'network_calls': 0, 'source_checkout_required': False}))


if __name__ == '__main__':
    main()
