#!/usr/bin/env node
// Local list maintenance only. No downloads, subscriptions, credentials or models.
const fs = require('node:fs');
const {SourceLists, SOURCES, entry} = require('./store');
function main(args) {
  const command = args.shift(), flags = {};
  while (args.length) {
    const key = args.shift(), value = args.shift();
    if (!['--data-dir', '--source', '--name', '--ghid', '--file', '--revision'].includes(key) || value === undefined || key in flags) throw Error('invalid_arguments');
    flags[key] = value;
  }
  if (!['list', 'add', 'remove', 'import-wechat'].includes(command)) throw Error('usage: list|add|remove|import-wechat --data-dir ABSOLUTE_PATH --source SOURCE; writes require --revision N');
  const store = new SourceLists(flags['--data-dir'] || ''), source = flags['--source'];
  if (source && !SOURCES.includes(source)) throw Error('unsupported_list_source');
  if (command === 'list') { const data = store.read(); return {status: 'ok', revision: data.revision, file: store.file, ...(source ? {source, entries: data.sources[source]} : {sources: data.sources})}; }
  if (!/^\d+$/.test(flags['--revision'] || '')) throw Error('revision_required_read_list_first');
  const revision = Number(flags['--revision']);
  if (command === 'import-wechat') {
    if (source !== 'wechat' || !flags['--file']) throw Error('wechat_import_requires_file');
    if (fs.statSync(flags['--file']).size > 8 * 1024 * 1024) throw Error('import_too_large');
    const input = JSON.parse(fs.readFileSync(flags['--file'], 'utf8'));
    if (!Array.isArray(input)) throw Error('invalid_import');
    const incoming = input.map(entry);
    const data = store.change(source, revision, rows => {
      for (const row of incoming) {
        const old = rows.find(r => r.name === row.name);
        if (old) { if (row.ghid && old.ghid !== row.ghid) throw Error('conflicting_ghid'); }
        else rows.push(row);
      }
      return rows;
    });
    return {status: 'ok', revision: data.revision, source, count: data.sources[source].length};
  }
  const row = entry({name: flags['--name'], ...(flags['--ghid'] ? {ghid: flags['--ghid']} : {})});
  const data = store.change(source, revision, rows => {
    if (command === 'add') { if (rows.some(r => r.name === row.name)) throw Error('name_already_exists'); return [...rows, row]; }
    if (!rows.some(r => r.name === row.name)) throw Error('name_not_found');
    return rows.filter(r => r.name !== row.name);
  });
  return {status: 'ok', revision: data.revision, source, count: data.sources[source].length};
}
if (require.main === module) { try { console.log(JSON.stringify(main(process.argv.slice(2)))); } catch (e) { console.log(JSON.stringify({status: 'error', code: e.message})); process.exitCode = 1; } }
module.exports = {main};
