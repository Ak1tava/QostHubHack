import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { pathToFileURL } from 'node:url';

export const registryHash = rows => createHash('sha256').update(rows.map(r => JSON.stringify(r)).join('\n') + '\n').digest('hex');
const categories = new Set(['conveyors', 'pumps', 'crushers_screens', 'guards', 'drives_bearings']);
const strings = ['case_id', 'component', 'problem', 'observable_sign', 'photo_locator', 'source_group', 'similarity_group', 'normal_control', 'ambiguous_case'];

export function validateRegistry(rows, manifest) {
  const errors = [], counts = {}, splits = {}, groups = new Map(), media = new Set(), ids = new Set();
  const fail = (row, reason) => errors.push(`${row?.case_id ?? 'registry'}: ${reason}`);
  if (!Array.isArray(rows) || rows.length !== 50) fail(null, 'count must be exactly 50');
  for (const row of rows) {
    for (const key of strings) if (typeof row[key] !== 'string' || !row[key].trim()) fail(row, `missing ${key}`);
    if (!/^T15-\d{3}$/.test(row.case_id) || ids.has(row.case_id)) fail(row, 'invalid or duplicate id');
    ids.add(row.case_id);
    if (!categories.has(row.category)) fail(row, 'invalid category');
    counts[row.category] = (counts[row.category] ?? 0) + 1;
    if (!['dev', 'eval'].includes(row.split)) fail(row, 'invalid split');
    splits[row.split] = (splits[row.split] ?? 0) + 1;
    for (const key of ['source_group', 'similarity_group', 'source_url']) {
      const group = `${key}:${row[key]}`;
      if (groups.has(group) && groups.get(group) !== row.split) fail(row, 'source split leakage');
      groups.set(group, row.split);
    }
    for (const key of ['source_url', 'media_url']) {
      try { const url = new URL(row[key]); if (url.protocol !== 'https:' || url.username || url.password) throw Error(); }
      catch { fail(row, `invalid public ${key}`); }
    }
    let canonical = row.media_url;
    try { const url = new URL(row.media_url); canonical = url.origin + url.pathname; } catch {}
    if (media.has(canonical)) fail(row, 'duplicate media');
    media.add(canonical);
    if (row.verified_on !== manifest.frozen_on || row.source_check?.http_status !== 200 ||
        !/^(image\/(jpeg|png|webp)|application\/pdf)/.test(row.source_check?.content_type ?? '') ||
        !Number.isInteger(row.source_check?.bytes) || row.source_check.bytes <= 0) fail(row, 'media not verified');
    if (row.status !== 'candidate_pending_master_review' || row.rights_status !== 'not_reviewed') fail(row, 'candidate/rights status must remain explicit');
    if (!row.master_review || ['reviewer', 'verdict', 'reviewed_on'].some(k => row.master_review[k] !== null)) fail(row, 'master review is not confirmed');
    if (row.dataset !== 't15_new_candidates_v1' || row.used_holdout !== false || row.real_before_after_pair_confirmed !== false) fail(row, 'holdout or unconfirmed pair claimed');
    for (const key of ['required_before_views', 'required_after_views', 'limitations']) {
      if (!Array.isArray(row[key]) || row[key].length < 2 || row[key].some(x => typeof x !== 'string' || !x.trim())) fail(row, `missing ${key}`);
    }
    const membership = manifest.groups?.[row.source_group];
    if (!membership || membership.split !== row.split || !membership.case_ids.includes(row.case_id)) fail(row, 'frozen membership changed');
  }
  if (Object.keys(counts).length !== 5 || !splits.dev || !splits.eval) fail(null, 'coverage must include five groups and both splits');
  if (registryHash(rows) !== manifest.registry_sha256) fail(null, 'frozen registry hash mismatch');
  return { count: rows.length, categories: counts, splits, sources: new Set(rows.map(r => r.source_url)).size,
    source_groups: new Set(rows.map(r => r.source_group)).size, unique_media: media.size, errors };
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    const rows = readFileSync(new URL('./cases.jsonl', import.meta.url), 'utf8').trim().split('\n').map(JSON.parse);
    const manifest = JSON.parse(readFileSync(new URL('./split-manifest.json', import.meta.url), 'utf8'));
    const result = validateRegistry(rows, manifest);
    console.log(JSON.stringify(result, null, 2));
    if (result.errors.length) process.exitCode = 1;
  } catch (error) { console.error(error.message); process.exitCode = 1; }
}
