import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { validateRegistry } from './validate.mjs';

const rows = () => readFileSync(new URL('./cases.jsonl', import.meta.url), 'utf8').trim().split('\n').map(JSON.parse);
const manifest = () => JSON.parse(readFileSync(new URL('./split-manifest.json', import.meta.url), 'utf8'));
const check = (mutate) => { const cases = rows(); mutate(cases); return validateRegistry(cases, manifest()); };

test('frozen registry has 50 distinct candidates and five equipment groups', () => {
  const result = validateRegistry(rows(), manifest());
  assert.deepEqual(result.errors, []);
  assert.equal(result.count, 50);
  assert.equal(Object.keys(result.categories).length, 5);
});
test('missing candidate is rejected', () => assert.ok(check(r => r.pop()).errors.some(e => e.includes('count'))));
test('duplicate media cannot masquerade as another defect', () => {
  assert.ok(check(r => { r[1].media_url = r[0].media_url; }).errors.some(e => e.includes('duplicate media')));
});
test('same source family cannot leak between dev and eval', () => {
  assert.ok(check(r => { r[0].split = 'eval'; }).errors.some(e => e.includes('source split leakage')));
});
test('new registry is never a consumed holdout or confirmed master label', () => {
  assert.ok(check(r => { r[0].split = 'holdout'; r[0].master_review.verdict = 'accepted'; }).errors.some(e => e.includes('master review')));
});
test('failed media checks cannot be reported as verified', () => {
  assert.ok(check(r => { r[0].source_check.http_status = 404; }).errors.some(e => e.includes('media not verified')));
});
test('normal and ambiguous controls must remain explicit plans', () => {
  assert.ok(check(r => { r[0].normal_control = ''; }).errors.some(e => e.includes('normal_control')));
});
test('frozen split membership cannot silently change', () => {
  assert.ok(check(r => { r[0].case_id = 'T15-999'; }).errors.some(e => e.includes('frozen membership')));
});
