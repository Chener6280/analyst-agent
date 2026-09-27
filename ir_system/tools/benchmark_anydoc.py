"""Read-only, bounded local archive benchmark. Never opts into hosted OCR."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import time


def assets(root):
    found = {}
    db = root / 'index/archive.sqlite'
    if db.exists():
        with sqlite3.connect(db.as_uri() + '?mode=ro', uri=True) as con:
            for payload, in con.execute('SELECT payload FROM records ORDER BY rowid'):
                r = json.loads(payload)
                for a in r.get('attachments', []):
                    if a.get('status') == 'ok' and a.get('object_path') and a.get('sha256'):
                        found[a['sha256']] = {**a, 'path': str(root / a['object_path'])}
    for p in (root / 'zsxq_web/groups').glob('*/topics/*/record.json'):
        r = json.loads(p.read_text())
        for a in r.get('attachments', []):
            if a.get('status') == 'ok' and a.get('object_path') and a.get('sha256'):
                found[a['sha256']] = {**a, 'path': str(root / 'zsxq_web' / a['object_path'])}
    return list(found.values())


def worker(path):
    import socket
    def denied(*args, **kwargs):
        raise RuntimeError('network_disabled_for_local_parse')
    socket.socket.connect = denied
    socket.create_connection = denied
    import anydoc
    import fitz
    from importlib.metadata import version
    raw = Path(path).read_bytes()
    result = {'sha256': hashlib.sha256(raw).hexdigest(), 'size_bytes': len(raw),
              'parser_version': version('firecrawl-anydoc')}
    before = time.monotonic()
    try:
        md = anydoc.to_markdown_bytes(raw)
        result.update(status='parsed' if md.strip() else 'empty', chars=len(md),
                      markdown_tables=md.count('|'), chinese_chars=len(re.findall(r'[\u4e00-\u9fff]', md)))
    except Exception as e:
        md = ''
        result.update(status=type(e).__name__, chars=0)
    result['conversion_ms'] = round((time.monotonic() - before) * 1000, 2)
    if raw.startswith(b'%PDF-'):
        with fitz.open(stream=raw, filetype='pdf') as pdf:
            pages = [page.get_text() for page in pdf]
            text = '\n'.join(pages)
            numbers = set(re.findall(r'\d+(?:[.,]\d+)*', text))
            actual = set(re.findall(r'\d+(?:[.,]\d+)*', md))
            result.update(pages=len(pages), baseline_chars=len(text),
                          baseline_empty_pages=[n+1 for n, s in enumerate(pages) if not s.strip()],
                          numeric_token_recall=round(len(numbers & actual)/len(numbers), 4) if numbers else None)
    print(json.dumps(result))


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--archive-root', type=Path)
    p.add_argument('--output', type=Path)
    p.add_argument('--worker')
    args = p.parse_args()
    if args.worker:
        worker(args.worker)
        return
    root = args.archive_root.resolve(strict=True)
    rows = assets(root)
    groups = defaultdict(list)
    supported = {'.pdf', '.doc', '.docx', '.ppt', '.pptx', '.xls', '.xlsx', '.rtf', '.epub', '.odt', '.ods', '.odp'}
    for a in sorted(rows, key=lambda x: x['sha256']):
        ext = Path(a.get('original_filename') or '').suffix.lower()
        if ext in supported:
            groups[ext].append(a)
    selected = []
    while len(selected) < 20 and any(groups.values()):
        for ext in sorted(groups):
            if groups[ext] and len(selected) < 20:
                selected.append(groups[ext].pop(0))
    results = []
    for a in selected:
        path = Path(a['path']).resolve(strict=True)
        if not path.is_relative_to(root):
            raise ValueError('object outside archive')
        try:
            r = subprocess.run([sys.executable, __file__, '--worker', str(path)],
                               capture_output=True, text=True, timeout=45)
            metric = json.loads(r.stdout) if r.returncode == 0 else {'status': 'worker_failed', 'exit_code': r.returncode}
        except subprocess.TimeoutExpired:
            metric = {'status': 'timeout'}
        metric.update(name=a.get('original_filename'), object_path=str(path.relative_to(root)), expected_sha256=a['sha256'])
        metric['checksum_verified'] = metric.get('sha256') == a['sha256']
        results.append(metric)
        print(json.dumps({'sample': len(results), 'status': metric['status']}, ensure_ascii=False), flush=True)
    report = {'network': 'disabled_no_hosted_ocr', 'method': 'stratified_by_available_extension_sha256_sorted',
              'eligible_downloaded_objects': len(rows), 'sample_count': len(results),
              'available_extensions': dict(Counter(Path(a.get('original_filename') or '').suffix.lower() for a in rows)),
              'sample_extensions': dict(Counter(Path(r.get('name') or '').suffix.lower() for r in results)),
              'status_counts': dict(Counter(r['status'] for r in results)), 'samples': results,
              'quality_note': 'Token recall is a diagnostic, not table/meaning fidelity or OCR verification.'}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    args.output.chmod(0o600)


if __name__ == '__main__':
    main()
