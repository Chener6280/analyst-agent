const SOURCES = ["zsxq", "wisburg", "ima"];
const CATEGORIES = ["ib", "company", "am", "archive", "ec", "feed", "market_daily", "article", "mikko"];
const LIMITS = { maxOperations: [1, 1000], maxRecords: [1, 10000], maxFiles: [0, 1000], maxBytesMiB: [1, 20480], maxFileMiB: [1, 200], maxParses: [0, 200], maxSeconds: [30, 3600] };
function exact(object, fields) {
  if (!object || typeof object !== "object" || Array.isArray(object) || Object.keys(object).some(k => !fields.includes(k))) throw new Error("unexpected_fields");
}
function day(value) {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const parsed = new Date(value);
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
}
function today() { return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date()); }
function key(row) { return `${row.provider}:${row.collectionId}`; }
function validateSettings(input) {
  exact(input, ["agentMode", "piCommand", "policies", "budgets", "overlapDays"]);
  if (!["fixed", "pi"].includes(input.agentMode)) throw new Error("unsupported_agent_mode");
  if (typeof input.piCommand !== "string" || !input.piCommand.trim() || input.piCommand.length > 1024 || /[\0\r\n]/.test(input.piCommand)) throw new Error("invalid_pi_command");
  if (!Array.isArray(input.policies) || input.policies.length > 500) throw new Error("invalid_policies");
  const seen = new Set();
  const policies = input.policies.map(row => {
    exact(row, ["provider", "collectionId", "name", "mode", "firstDate"]);
    if (!SOURCES.includes(row.provider) || typeof row.collectionId !== "string" || !/^[A-Za-z0-9_+=.-]{1,512}$/.test(row.collectionId)) throw new Error("invalid_collection_id");
    if (row.provider === "zsxq" && !/^[1-9][0-9]{0,29}$/.test(row.collectionId)) throw new Error("invalid_group_id");
    if (row.provider === "wisburg" && !CATEGORIES.includes(row.collectionId)) throw new Error("invalid_category");
    if (!["once", "incremental", "off", "pending_selection"].includes(row.mode)) throw new Error("invalid_collection_mode");
    if (typeof row.name !== "string" || row.name.length > 2000) throw new Error("invalid_name");
    if (row.firstDate !== "" && !day(row.firstDate)) throw new Error("invalid_first_date");
    if (["once", "incremental"].includes(row.mode) && (!row.firstDate || row.firstDate > today())) throw new Error("first_date_required");
    if (seen.has(key(row))) throw new Error("duplicate_collection");
    seen.add(key(row)); return { ...row };
  });
  exact(input.budgets, Object.keys(LIMITS));
  for (const [field, [min, max]] of Object.entries(LIMITS)) {
    if (!Number.isInteger(input.budgets[field]) || input.budgets[field] < min || input.budgets[field] > max) throw new Error(`invalid_${field}`);
  }
  if (!Number.isInteger(input.overlapDays) || input.overlapDays < 1 || input.overlapDays > 30) throw new Error("invalid_overlap");
  return { agentMode: input.agentMode, piCommand: input.piCommand.trim(), policies, budgets: { ...input.budgets }, overlapDays: input.overlapDays };
}

function validateSelection(input = {}, kind, now = today()) {
  exact(input, ["provider", "providers", "start", "end", "collectionIds", "browserMode"]);
  if(input.providers!==undefined&&(!Array.isArray(input.providers)||!input.providers.length||input.providers.length>SOURCES.length||new Set(input.providers).size!==input.providers.length||input.providers.some(p=>!SOURCES.includes(p))||input.provider||input.collectionIds))throw new Error('unsupported_sync_source');
  if (Object.keys(input).some(k=>k!=='browserMode') && !input.providers && !SOURCES.includes(input.provider)) throw new Error("unsupported_sync_source");
  if(input.browserMode!==undefined&&!['headless','visible'].includes(input.browserMode))throw new Error('invalid_browser_mode');
  const hasDates = Object.hasOwn(input, "start") || Object.hasOwn(input, "end");
  if (hasDates && (!day(input.start) || !day(input.end) || input.start > input.end || input.end > now)) throw new Error("invalid_history_range");
  if(input.collectionIds!==undefined&&(!input.provider||!Array.isArray(input.collectionIds)||!input.collectionIds.length||input.collectionIds.length>500||new Set(input.collectionIds).size!==input.collectionIds.length||input.collectionIds.some(id=>typeof id!=='string'||!/^[A-Za-z0-9_+=.-]{1,512}$/.test(id))))throw new Error('invalid_selected_collections');
  return { ...input };
}

function makePlan(settings, watermarks, kind, root, now = today(), selection = {}) {
  if (!["incremental", "backfill"].includes(kind)) throw new Error("invalid_sync_kind");
  const selected = validateSelection(selection, kind, now);
  const explicitDates = Boolean(selected.start);
  const customHistory = explicitDates && kind === 'backfill';
  const eligible=settings.policies.filter(p => (!selected.provider || p.provider === selected.provider) && (!selected.providers || selected.providers.includes(p.provider)) &&
    (selected.providers ? p.mode==='incremental' : customHistory ? ["once", "incremental"].includes(p.mode) : p.mode === (kind === "backfill" ? "once" : "incremental")));
  if(selected.collectionIds?.some(id=>!eligible.some(row=>row.collectionId===id)))throw new Error('invalid_selected_collections');
  const collections = eligible.filter(row=>!selected.collectionIds||selected.collectionIds.includes(row.collectionId)).flatMap(row => {
    const previous = watermarks[key(row)];
    if (!customHistory && row.mode === "once" && previous?.onceComplete) return [];
    const date = previous?.through ? new Date(`${previous.through}T00:00:00Z`) : null;
    if (date) date.setUTCDate(date.getUTCDate() - settings.overlapDays);
    const start = date && row.provider !== "ima" ? [row.firstDate, date.toISOString().slice(0, 10)].sort().at(-1) : row.firstDate;
    return [{ ...row, start: explicitDates ? selected.start : start, end: explicitDates ? selected.end : now }];
  });
  if (!collections.length) throw new Error("no_selected_collections");
  return { schemaVersion: 1, kind, archiveRoot: root, collections, budgets: structuredClone(settings.budgets), media: "text_non_audio", includeNotes: false };
}
module.exports = { SOURCES, CATEGORIES, LIMITS, exact, day, today, key, validateSettings, validateSelection, makePlan };
