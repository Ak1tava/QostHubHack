import type { components } from '../../../../../packages/contracts/api.generated';
import type { paths } from '../../../../../packages/contracts/api.generated';
import { useCallback, useRef } from 'react';
import { useSearchParams } from 'react-router';
import type { ApiClient, UserView } from '../../lib/api';
import { localDateTime, utcDateTime } from '../../lib/time';
import { useQuery } from '../../lib/useQuery';
import { useCatalogs, useShift } from '../work-orders/data';

export type ShiftReport = components['schemas']['ShiftReportResponse'];
export type Rating = components['schemas']['RatingResponse'];
export type Anomalies = components['schemas']['AnomaliesResponse'];

export function defaultPeriod(now: string, timezone: string): { start: string; end: string } {
  const end = localDateTime(now, timezone);
  const [year, month, day] = end.slice(0, 10).split('-').map(Number);
  const target = new Date(Date.UTC(year, month - 4, 1));
  const lastDay = new Date(Date.UTC(target.getUTCFullYear(), target.getUTCMonth() + 1, 0)).getUTCDate();
  target.setUTCDate(Math.min(day, lastDay));
  return { start: `${target.toISOString().slice(0, 10)}T00:00`, end };
}

export function useReportContext(api: ApiClient, user: UserView, allowShift = false) {
  const [params, setParams] = useSearchParams();
  const areaId = params.get('area_id') ?? '';
  const catalogs = useCatalogs(api);
  const shift = useShift(api, areaId);
  const timezone = shift.data?.timezone;
  const bootstrap = useRef<{ api: ApiClient; userId: string; timezone: string; asOf: string; defaults: ReturnType<typeof defaultPeriod> } | null>(null);
  if (bootstrap.current && (bootstrap.current.api !== api || bootstrap.current.userId !== user.id)) bootstrap.current = null;
  // Live composition updates advance as_of; keep the report's initial server-derived period stable.
  if (shift.data && (!bootstrap.current || bootstrap.current.timezone !== timezone)) {
    bootstrap.current = { api, userId: user.id, timezone: shift.data.timezone, asOf: shift.data.as_of, defaults: defaultPeriod(shift.data.as_of, shift.data.timezone) };
  }
  const defaults = bootstrap.current?.defaults ?? { start: '', end: '' };
  let start = params.get('start') ?? defaults.start;
  let end = params.get('end') ?? defaults.end;
  const shiftId = allowShift ? params.get('shift_id') ?? '' : '';
  let query: Record<string, string | undefined> | null = null;
  let validationError: string | null = null;
  if (timezone && shift.data) {
    try {
      if (!params.has('start') && params.has('start_at')) start = localDateTime(params.get('start_at')!, timezone);
      if (!params.has('end') && params.has('end_at')) end = localDateTime(params.get('end_at')!, timezone);
      const period = shiftId ? { shift_id: shiftId } : {
        start_at: params.has('start') ? utcDateTime(start, timezone) : params.get('start_at') ?? utcDateTime(start, timezone),
        end_at: params.has('end') ? utcDateTime(end, timezone) : params.get('end_at') ?? bootstrap.current!.asOf,
      };
      if (!shiftId && (!Number.isFinite(Date.parse(period.start_at!)) || !Number.isFinite(Date.parse(period.end_at!)))) throw new Error('Проверьте границы периода');
      if (!shiftId && Date.parse(period.start_at!) >= Date.parse(period.end_at!)) throw new Error('Начало периода должно быть раньше окончания');
      query = { ...period, area_id: areaId || undefined, equipment_id: params.get('equipment_id') || undefined,
        assignee_id: user.role === 'worker' ? user.id : params.get('assignee_id') || undefined,
        brigade_id: user.role === 'worker' ? undefined : params.get('brigade_id') || undefined };
    } catch (error) { validationError = error instanceof Error ? error.message : 'Проверьте период'; }
  }
  function filter(name: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(name, value); else next.delete(name);
    if (name === 'area_id') { next.delete('equipment_id'); next.delete('assignee_id'); next.delete('shift_id'); }
    if (name === 'start' || name === 'end') {
      next.delete('shift_id'); next.delete('start_at'); next.delete('end_at');
      next.set('start', name === 'start' ? value : start); next.set('end', name === 'end' ? value : end);
    }
    setParams(next, { replace: true });
  }
  function preset(days: 7 | 30 | 90) {
    if (!shift.data) return;
    const asOf = shift.data.as_of;
    const next = new URLSearchParams(params);
    for (const name of ['start', 'end', 'shift_id']) next.delete(name);
    next.set('start_at', days === 90 ? utcDateTime(defaultPeriod(asOf, shift.data.timezone).start, shift.data.timezone) : new Date(Date.parse(asOf) - days * 86400000).toISOString());
    next.set('end_at', asOf); setParams(next, { replace: true });
  }
  const shifts = [...new Set([user.shift_id, ...(shift.data?.items.map(member => member.user.shift_id) ?? [])].filter((id): id is string => Boolean(id)))];
  return { params, catalogs, shift, timezone, start, end, shiftId, shifts, query, validationError, filter, preset, areaId };
}

export function useReport<T>(api: ApiClient, path: keyof paths, query: Record<string, string | undefined> | null) {
  const key = query ? JSON.stringify(query) : '';
  return useQuery(useCallback((signal: AbortSignal) => key
    ? api.request<T>(path, { query: JSON.parse(key) as Record<string, string>, signal })
    : Promise.resolve(null), [api, path, key]), 'refresh');
}

export function duration(seconds: number): string {
  if (seconds > 0 && seconds < 1) return seconds < .01 ? '< 0,01 с' : `${number(seconds)} с`;
  const total = Math.max(0, Math.round(seconds));
  const hours = Math.floor(total / 3600), minutes = Math.floor(total % 3600 / 60), remainder = total % 60;
  return [hours ? `${hours} ч` : '', minutes ? `${minutes} мин` : '', remainder || !total ? `${remainder} с` : ''].filter(Boolean).join(' ');
}

export const number = (value: number) => new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 }).format(value);
