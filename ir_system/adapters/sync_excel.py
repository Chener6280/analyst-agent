#!/usr/bin/env python3
"""Read-only, dependency-free import preview for the user's IMA selection sheet.

Never evaluates formulas, follows links, writes XLSX, or treats cell text as
instructions. Only named columns are read; IDs remain strings. Binding names to
account IDs happens separately against a scanned directory and user selection.
"""
from collections import Counter
import json
from pathlib import Path
import posixpath
import re
import sys
from xml.etree import ElementTree as ET
from zipfile import ZipFile

NS = {'x': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
REL = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'
MARKS = {'需要下载': 'once', '优先下载': 'incremental', '暂不下载': 'off', '待确认': 'pending_selection', '': 'pending_selection'}


def xml(data):
    if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper(): raise ValueError('xlsx_external_entities_forbidden')
    return ET.fromstring(data)


def interpret(rows, sheet):
    header = None; result = []; issues = []
    for row_number, cells in rows:
        if header is None:
            reverse = {v: k for k, v in cells.items() if isinstance(v, str)}
            if '知识库名称' in reverse and '你的标记' in reverse:
                header = {'name': reverse['知识库名称'], 'mark': reverse['你的标记'], 'remark': reverse.get('你的备注'),
                          'id': reverse.get('知识库ID') or reverse.get('知识库 ID') or reverse.get('kb_id')}
            continue
        name = cells.get(header['name'], '')
        if not name: continue
        if not isinstance(name, str) or name.startswith('=') or len(name) > 2000:
            issues.append({'sheet': sheet, 'row': row_number, 'code': 'invalid_library_name'}); continue
        mark = cells.get(header['mark'], '')
        if mark not in MARKS:
            issues.append({'sheet': sheet, 'row': row_number, 'code': 'unknown_mark'}); continue
        identifier = cells.get(header['id'], '') if header['id'] else ''
        if identifier and not re.fullmatch('[A-Za-z0-9_+=.-]{1,512}', identifier):
            issues.append({'sheet': sheet, 'row': row_number, 'code': 'invalid_collection_id'}); identifier = ''
        result.append({'provider': 'ima', 'name': name.strip(), 'mode': MARKS[mark], 'collectionId': identifier,
                       'remark': str(cells.get(header['remark'], '') if header['remark'] else '')[:2000],
                       'sheet': sheet, 'row': row_number})
    return result, issues


def preview(filename):
    path = Path(filename)
    if path.suffix.lower() != '.xlsx' or path.stat().st_size > 8 * 1024 * 1024: raise ValueError('invalid_xlsx_file')
    with ZipFile(path) as book:
        entries = book.infolist()
        if len(entries) > 2000 or sum(e.file_size for e in entries) > 20 * 1024 * 1024: raise ValueError('xlsx_size_limit')
        shared = []
        if 'xl/sharedStrings.xml' in book.namelist():
            shared = [''.join(si.itertext()) for si in xml(book.read('xl/sharedStrings.xml')).findall('x:si', NS)]
        relations = {r.attrib['Id']: r.attrib['Target'] for r in xml(book.read('xl/_rels/workbook.xml.rels'))
                     if r.attrib.get('TargetMode') != 'External'}
        rows, issues = [], []
        for sheet in xml(book.read('xl/workbook.xml')).findall('x:sheets/x:sheet', NS):
            target = relations.get(sheet.attrib[REL], '')
            if not target: continue
            member = posixpath.normpath(target.lstrip('/') if target.startswith('/') else 'xl/' + target)
            if not member.startswith('xl/worksheets/') or not member.endswith('.xml'): continue
            parsed_rows = []
            for r in xml(book.read(member)).findall('x:sheetData/x:row', NS):
                if len(parsed_rows) >= 2000: raise ValueError('xlsx_row_limit')
                cells = {}
                for cell in r.findall('x:c', NS):
                    address = cell.get('r', '')
                    col = re.sub(r'\d', '', address)
                    if cell.find('x:f', NS) is not None: value = '=FORMULA_NOT_EVALUATED'
                    elif cell.get('t') == 'inlineStr': value = ''.join(cell.find('x:is', NS).itertext())
                    elif cell.get('t') == 's': value = shared[int(cell.findtext('x:v', '0', NS))]
                    else: value = cell.findtext('x:v', '', NS)
                    cells[col] = value.strip() if isinstance(value, str) else value
                parsed_rows.append((int(r.get('r', '0')), cells))
            selected, errors = interpret(parsed_rows, sheet.get('name', ''))
            rows.extend(selected); issues.extend(errors)
        if len(rows) > 500: raise ValueError('xlsx_collection_limit')
        counts = Counter(r['name'] for r in rows)
        for r in rows:
            r['ambiguous'] = counts[r['name']] > 1
        return {'schemaVersion': 1, 'rows': rows, 'issues': issues, 'counts': dict(Counter(r['mode'] for r in rows)),
                'readOnly': True, 'requiresBinding': sum(not r['collectionId'] for r in rows), 'formulasEvaluated': False}


if __name__ == '__main__':
    try: print(json.dumps(preview(sys.argv[1]), ensure_ascii=False))
    except Exception as exc:
        safe = str(exc)
        print(json.dumps({'error': safe if re.fullmatch('[a-z_]{1,80}', safe) else 'xlsx_preview_failed'}))
        sys.exit(2)
