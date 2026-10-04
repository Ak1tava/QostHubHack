import { expect, it } from 'vitest';
import { localDateTime, utcDateTime } from './time';

it('round trips a deadline in the enterprise timezone instead of the device timezone', () => {
  expect(localDateTime('2026-10-04T07:30:00Z', 'Asia/Qostanay')).toBe('2026-10-04T12:30');
  expect(utcDateTime('2026-10-04T12:30', 'Asia/Qostanay')).toBe('2026-10-04T07:30:00.000Z');
});

it('rejects impossible local times rather than silently changing the deadline', () => {
  expect(() => utcDateTime('2026-03-08T02:30', 'America/New_York')).toThrow();
  expect(() => utcDateTime('', 'Asia/Qostanay')).toThrow();
});
