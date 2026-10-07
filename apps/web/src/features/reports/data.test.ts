import { expect, it } from 'vitest';
import { defaultPeriod, duration } from './data';

it('uses enterprise calendar date across a UTC midnight boundary', () => {
  expect(defaultPeriod('2026-10-07T20:00:00Z', 'Asia/Qostanay')).toEqual({ start: '2026-07-08T00:00', end: '2026-10-08T01:00' });
});

it('keeps a positive subsecond duration distinct from a known zero', () => {
  expect(duration(.3)).toBe('0,3 с');
  expect(duration(.001)).toBe('< 0,01 с');
  expect(duration(0)).toBe('0 с');
});

it('clamps the start day to the last day of the target month', () => {
  expect(defaultPeriod('2026-05-31T12:00:00Z', 'UTC')).toEqual({ start: '2026-02-28T00:00', end: '2026-05-31T12:00' });
});

it('uses the configured timezone rather than browser timezone', () => {
  expect(defaultPeriod('2026-01-01T01:00:00Z', 'Pacific/Honolulu')).toEqual({ start: '2025-09-30T00:00', end: '2025-12-31T15:00' });
});
