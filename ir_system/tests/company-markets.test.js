const assert = require('node:assert/strict');
const test = require('node:test');
const { NAVIGATION } = require('../src/main/navigation');
const { DemoProvider } = require('../src/main/providers/demo-provider');
const { markets, sections, marketFor, view } = require('../src/shared/company-markets');

test('company tabs are the Companies navigation children', () => {
  const companies = NAVIGATION.find(item => item.id === 'companies');
  assert.deepEqual(companies.children.map(c => [c.id, c.label]), markets.map(m => [m.child, m.label]));
  assert.deepEqual(markets.map(m => m.label), ['A股', '港股', '美股']);
  assert.deepEqual(sections.map(s => s.id), ['search', 'financials', 'filings', 'events', 'research']);
});

test('active market follows the navigation child, then the remembered tab, then A股', () => {
  assert.equal(marketFor('companies-hk', 'US'), 'HK');
  assert.equal(marketFor(null, 'US'), 'US');
  assert.equal(marketFor(null, 'bogus'), 'A_SHARE');
  assert.equal(marketFor('companies-financials', null), 'A_SHARE');
});

test('per-market provider mapping drives tab and section status', () => {
  const data = { status: 'partial', providerDetails: { markets: [
    { id: 'HK', status: 'partial', sections: [{ id: 'filings', status: 'partial', sources: [{ provider: 'hkex', capability: 'announcement' }, null, { capability: 'no provider' }] }] },
  ] } };
  const hk = view(data, 'HK');
  assert.equal(hk.mapped, true);
  assert.equal(hk.status, 'partial');
  assert.deepEqual(hk.sections.find(s => s.id === 'filings').sources.map(s => s.provider), ['hkex']);
  assert.equal(hk.sections.find(s => s.id === 'financials').status, 'unavailable');
  assert.equal(view(data, 'US').status, 'unavailable');
  assert.equal(view(data, 'unknown').market.id, 'A_SHARE');
});

test('without a per-market mapping no market inherits module-level coverage', () => {
  for (const status of ['demo', 'unavailable']) assert.ok(view({ status }, 'US').sections.every(s => s.status === status && s.sources.length === 0));
  const legacy = view({ status: 'partial', providerDetails: { sources: ['sec'] } }, 'US');
  assert.equal(legacy.mapped, false);
  assert.equal(legacy.status, 'planned');
  assert.ok(legacy.sections.every(s => s.status === 'planned'));
});

test('demo provider exposes the market tabs as Companies sections', async () => {
  const data = await new DemoProvider().moduleData('companies');
  assert.deepEqual(data.sections.map(s => s.id), markets.map(m => m.child));
  assert.ok(view(data, 'HK').sections.every(s => s.status === 'demo'));
});
