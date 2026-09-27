(function(root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.IRDates = api;
})(typeof globalThis === 'object' ? globalThis : this, function() {
  function today(now = new Date()) {
    return new Intl.DateTimeFormat('en-CA', {timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(now);
  }
  function parse(value) {
    const v = String(value || '').trim();
    const iso = /^\d{6}$/.test(v) ? `20${v.slice(0,2)}-${v.slice(2,4)}-${v.slice(4,6)}` : v;
    if (!/^20\d{2}-\d{2}-\d{2}$/.test(iso)) throw new Error('invalid_history_range');
    const d = new Date(`${iso}T00:00:00Z`);
    if (!Number.isFinite(d.getTime()) || d.toISOString().slice(0,10) !== iso) throw new Error('invalid_history_range');
    return iso;
  }
  function compact(iso) { return parse(iso).slice(2).replaceAll('-',''); }
  function defaults(kind, now = new Date()) {
    const end = today(now);
    if (kind === 'incremental') return {start:end,end};
    const [y,m,d] = end.split('-').map(Number);
    const lastDay = new Date(Date.UTC(y,m-1,0)).getUTCDate();
    const start = new Date(Date.UTC(y,m-2,Math.min(d,lastDay))).toISOString().slice(0,10);
    return {start,end:new Date(Date.UTC(y,m-1,d-1)).toISOString().slice(0,10)};
  }
  return {today,parse,compact,defaults};
});
