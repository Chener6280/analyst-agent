const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const SOURCES = ['wechat', 'bilibili', 'announcements', 'web', 'news', 'xiaoyuzhou', 'xiaoe'];
const empty = () => ({version: 1, revision: 0, sources: Object.fromEntries(SOURCES.map(id => [id, []]))});
function entry(value) {
  if (!value || typeof value.name !== 'string' || !value.name.trim() || value.name.length > 300 || /[\x00-\x1f]/.test(value.name)) throw Error('invalid_name');
  const result = {name: value.name.trim()};
  if (value.ghid !== undefined) {
    if (typeof value.ghid !== 'string' || !/^gh_[a-zA-Z0-9_]+$/.test(value.ghid)) throw Error('invalid_ghid');
    result.ghid = value.ghid;
  }
  return result;
}
function validate(data) {
  if (data?.version !== 1 || !Number.isSafeInteger(data.revision) || data.revision < 0 || !data.sources || Object.keys(data.sources).some(id => !SOURCES.includes(id))) throw Error('invalid_source_lists');
  // Additive compatibility for existing six-source files; reading never writes
  // or resets the user's lists. Explicitly malformed values still fail closed.
  if (!Object.hasOwn(data.sources, 'xiaoe')) data.sources.xiaoe = [];
  for (const id of SOURCES) {
    const rows = data.sources[id];
    if (!Array.isArray(rows) || rows.length > 10000) throw Error('invalid_source_lists');
    const names = new Set(), ids = new Set();
    for (const row of rows) {
      const clean = entry(row);
      if (names.has(clean.name) || clean.ghid && ids.has(clean.ghid)) throw Error('duplicate_entry');
      names.add(clean.name); if (clean.ghid) ids.add(clean.ghid);
    }
  }
  return data;
}
class SourceLists {
  constructor(dir) { if (!path.isAbsolute(dir)) throw Error('absolute_data_dir_required'); this.file = path.join(dir, 'source-lists.v1.json'); }
  read() {
    try { if (fs.statSync(this.file).size > 8 * 1024 * 1024) throw Error('source_lists_too_large'); return validate(JSON.parse(fs.readFileSync(this.file, 'utf8'))); }
    catch (e) { if (e.code === 'ENOENT') return empty(); throw e; }
  }
  view() { try { return {status: 'ready', ...this.read(), file: this.file}; } catch (e) { return {status: 'error', error: e.message, file: this.file}; } }
  change(source, expectedRevision, edit) {
    if (!SOURCES.includes(source)) throw Error('unsupported_list_source');
    if (!Number.isSafeInteger(expectedRevision)) throw Error('revision_required');
    fs.mkdirSync(path.dirname(this.file), {recursive: true});
    const lock = this.file + '.lock'; let fd;
    try { fd = fs.openSync(lock, 'wx', 0o600); } catch (e) { if (e.code === 'EEXIST') throw Error('source_lists_busy_do_not_remove_lock'); throw e; }
    const temp = this.file + '.' + crypto.randomUUID() + '.tmp';
    try {
      const data = this.read();
      if (data.revision !== expectedRevision) throw Error('source_lists_changed_read_again');
      data.sources[source] = edit(structuredClone(data.sources[source])).map(entry);
      data.revision++; validate(data);
      if (fs.existsSync(this.file)) {
        const backupDir = path.join(path.dirname(this.file), 'source-list-backups');
        fs.mkdirSync(backupDir, {recursive: true});
        fs.copyFileSync(this.file, path.join(backupDir, `${Date.now()}-${crypto.randomUUID()}.json`), fs.constants.COPYFILE_EXCL);
      }
      const out = fs.openSync(temp, 'wx', 0o600);
      try { fs.writeFileSync(out, JSON.stringify(data, null, 2) + '\n'); fs.fsyncSync(out); } finally { fs.closeSync(out); }
      fs.renameSync(temp, this.file);
      return data;
    } finally { if (fs.existsSync(temp)) fs.unlinkSync(temp); fs.closeSync(fd); fs.unlinkSync(lock); }
  }
}
module.exports = {SourceLists, SOURCES, entry};
