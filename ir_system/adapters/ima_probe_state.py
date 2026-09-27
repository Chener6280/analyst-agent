"""Bounded local continuation and allowlisted diagnostics; never file contents."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import re

ID = r'[A-Za-z0-9_+=.-]{1,512}'
REF = r'ima://media/' + ID
MAX_POSITIONS = 4096
MAX_CHECKPOINT_BYTES = 48 * 1024
OPERATIONS = {'search_knowledge_base', 'get_knowledge_base', 'get_knowledge_list', 'get_media_info'}


def clean_title(value):
    return re.sub(r'[\x00-\x1f\x7f]', ' ', value if isinstance(value, str) else '')[:300]


def position(folder, cursor):
    return hashlib.sha256(((folder or '') + '\0' + cursor).encode()).hexdigest()


def checkpoint(value=None):
    if value is None:
        return dict(version=1, queue=[[None, '']], visited=[], sample=None, pagesTotal=0, skippedTotal=0)
    try:
        def require(ok):
            if not ok: raise ValueError('ima_probe_checkpoint_invalid')
        require(isinstance(value, dict) and set(value) == {'version', 'queue', 'visited', 'sample', 'pagesTotal', 'skippedTotal'})
        require(value['version'] == 1)
        require(isinstance(value['queue'], list) and len(value['queue']) <= MAX_POSITIONS)
        require(isinstance(value['visited'], list) and len(value['visited']) <= MAX_POSITIONS)
        for pair in value['queue']:
            require(isinstance(pair, list) and len(pair) == 2)
            folder, cursor = pair
            require(folder is None or isinstance(folder, str) and re.fullmatch(ID, folder))
            require(isinstance(cursor, str) and len(cursor) <= 512 and not re.search(r'[\x00-\x1f]', cursor))
        require(all(isinstance(v, str) and re.fullmatch(r'[a-f0-9]{64}', v) for v in value['visited']))
        for key in ('pagesTotal', 'skippedTotal'):
            require(type(value[key]) is int and 0 <= value[key] <= MAX_POSITIONS * 20)
        sample = value['sample']
        if sample is not None:
            require(isinstance(sample, dict) and set(sample) == {'ref', 'suffix', 'title', 'folderId'})
            require(isinstance(sample['ref'], str) and re.fullmatch(REF, sample['ref']))
            require(sample['suffix'] in {'.pdf', '.docx', '.pptx', '.xlsx', '.txt', '.md', '.html', '.csv'})
            require(isinstance(sample['title'], str) and clean_title(sample['title']) == sample['title'])
            require(sample['folderId'] is None or isinstance(sample['folderId'], str) and re.fullmatch(ID, sample['folderId']))
        require(len(json.dumps(value).encode()) <= MAX_CHECKPOINT_BYTES)
        return deepcopy(value)
    except (ValueError, TypeError, KeyError):
        raise ValueError('ima_probe_checkpoint_invalid') from None


def diagnostics(value=None, *, phase, code):
    source = value if isinstance(value, dict) else getattr(value, 'diagnostics', {})
    source = source if isinstance(source, dict) else {}
    result = dict(phase=phase, code=code, observedAt=datetime.now(timezone.utc).isoformat())
    if source.get('operation') in OPERATIONS:
        result['operation'] = source['operation']
    for key, low, high in [('httpStatus', 100, 599), ('providerCode', -2147483648, 2147483647)]:
        if type(source.get(key)) is int and low <= source[key] <= high:
            result[key] = source[key]
    return result
