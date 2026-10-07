import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { MemoryRouter } from 'react-router';
import { afterEach, expect, it } from 'vitest';
import { ApiClient, type UserView } from '../../lib/api';
import { events } from '../../lib/events';
import { ShiftReportPage } from './ShiftReportPage';
import { RatingPage } from './RatingPage';
import { AnomaliesPage } from './AnomaliesPage';
import type { ShiftReport, Rating, Anomalies } from './data';

const master: UserView = { id: 'master', display_name: 'Мастер', role: 'master', brigade_id: null, shift_id: 'shift-1', specialty: null, grade: null };
const worker: UserView = { ...master, id: 'own-worker', display_name: 'Исполнитель', role: 'worker', brigade_id: 'brigade-1', specialty: 'Слесарь' };
const period = { start_at: '2026-07-07T19:00:00Z', end_at: '2026-10-07T20:00:00Z', as_of: '2026-10-07T20:00:00Z', timezone: 'Asia/Qostanay' };
const shift: ShiftReport = { period, counts: { issued: 11, performed: 7, closed: 5, overdue: 3, rejected: 2 }, workload: { active_seconds: 3661, pause_seconds: 120, review_seconds: 60 }, downtime: { seconds: 0, has_data: false }, summary: 'Закрыто 5 нарядов по данным сервера.', limitations: ['Нет подтверждённых корректировок срока'] };
const rating: Rating = { period, formula_version: 'c6-v1-available', limitations: ['Нормативные часы отсутствуют'], items: [{ worker_id: 'own-worker', display_name: 'Исполнитель', specialty: 'Слесарь', work_type: 'planned', closed_count: 5, score: 83.33, components: { Q: { value: .9, sample_size: 5, reason: null }, T: { value: .7, sample_size: 5, reason: null }, R: { value: null, sample_size: 0, reason: 'Нет подтверждённых повторов' }, V: { value: null, sample_size: 0, reason: 'Нет нормативных часов' } } }] };
const anomalies: Anomalies = { period, limitations: ['Корреляция не доказывает причину'], items: [{ id: 'repeat-1', type: 'repeat_fault', title: 'Повтор неисправности', description: 'Два принятых ремонта одного шифра', equipment_id: 'equipment-1', metrics: { order_count: 2, hours_between: 24 }, evidence_order_ids: ['order-1', 'order-2'], limitations: ['Нужна проверка причины'] }] };
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
let container: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
afterEach(async () => { if (root) await act(async () => root.unmount()); container?.remove(); });

function client(report: unknown, requests: URL[] = [], reportStatus = 200, pending?: (url: URL) => Promise<Response> | undefined) {
  return new ApiClient(async input => {
    const url = new URL(String(input), 'https://test.local'); requests.push(url);
    if (url.pathname === '/api/v1/shift') return json({ as_of: period.as_of, timezone: period.timezone, items: [{ user: worker, availability: 'free', start_at: period.start_at, end_at: period.end_at, queue_count: 0, active_work_order_id: null }] });
    if (url.pathname.includes('/catalog/')) {
      const kind = url.pathname.split('/').at(-1);
      const items = kind === 'areas' ? [{ id: 'area-1', name: 'Цех №1' }] : kind === 'equipment' ? [{ id: 'equipment-1', name: 'Насос', area_id: 'area-1' }] : [{ id: 'brigade-1', name: 'Бригада №1' }];
      return json({ items, total: items.length });
    }
    return pending?.(url) ?? json(report, reportStatus);
  });
}
async function mount(Page: typeof ShiftReportPage, api: ApiClient, user = master, path = '/') {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement('div'); document.body.append(container); root = createRoot(container);
  await act(async () => root.render(<MemoryRouter initialEntries={[path]}><Page api={api} user={user} /></MemoryRouter>));
}
async function choose(name: string, value: string) {
  await act(async () => { const field = container.querySelector<HTMLSelectElement>(`select[name="${name}"]`)!; field.value = value; field.dispatchEvent(new Event('change', { bubbles: true })); });
}

it('renders separate API counters, exact durations and unavailable downtime', async () => {
  const requests: URL[] = []; await mount(ShiftReportPage, client(shift, requests));
  const metrics = container.querySelector('[aria-label="Показатели отчёта"]')!;
  expect(metrics.textContent).toContain('Выдано11'); expect(metrics.textContent).toContain('Исполнено7'); expect(metrics.textContent).toContain('Закрыто5');
  expect(metrics.textContent).toContain('Просрочено3'); expect(metrics.textContent).toContain('Отклонено2');
  expect(container.textContent).toContain('1 ч 1 мин 1 с'); expect(container.textContent).toContain('Нет данных о простое');
  expect(container.textContent).toContain(shift.summary); expect(container.textContent).toContain(shift.limitations[0]);
  const report = requests.find(url => url.pathname === '/api/v1/reports/shift')!;
  expect(report.searchParams.get('start_at')).toBe('2026-07-07T19:00:00.000Z');
  expect(report.searchParams.get('end_at')).toBe('2026-10-07T20:00:00Z');
});

it('distinguishes known zero downtime from missing data', async () => {
  await mount(ShiftReportPage, client({ ...shift, downtime: { seconds: 0, has_data: true } }));
  expect(container.textContent).toContain('Простой оборудования0 с'); expect(container.textContent).not.toContain('Нет данных о простое');
});

it('uses selected shift alone and carries area equipment worker and brigade filters', async () => {
  const requests: URL[] = []; await mount(ShiftReportPage, client(shift, requests));
  await choose('area_id', 'area-1'); await choose('equipment_id', 'equipment-1'); await choose('assignee_id', 'own-worker'); await choose('brigade_id', 'brigade-1');
  await choose('shift_id', 'shift-1');
  const report = requests.filter(url => url.pathname === '/api/v1/reports/shift').at(-1)!;
  expect(Object.fromEntries(report.searchParams)).toEqual({ shift_id: 'shift-1', area_id: 'area-1', equipment_id: 'equipment-1', assignee_id: 'own-worker', brigade_id: 'brigade-1' });
});

it('renders server rating, component samples and unknown components without inventing values', async () => {
  await mount(RatingPage, client(rating));
  expect(container.textContent).toContain('83,33'); expect(container.textContent).toContain('90%'); expect(container.textContent).toContain('70%');
  expect(container.textContent).toContain('Выборка: 5'); expect(container.textContent).toContain('Нет подтверждённых повторов'); expect(container.textContent).toContain('Нет нормативных часов');
  expect(container.textContent).toContain('0,50'); expect(container.textContent).toContain('0,25'); expect(container.textContent).toContain('0,15'); expect(container.textContent).toContain('0,10'); expect(container.textContent).toContain('нормируются');
});

it('shows an empty rating rather than a fictitious zero', async () => {
  await mount(RatingPage, client({ ...rating, items: [] }));
  expect(container.textContent).toContain('Нет закрытых работ для рейтинга');
});

it('shows anomaly numbers, limitations and links to evidence orders', async () => {
  await mount(AnomaliesPage, client(anomalies));
  expect(container.textContent).toContain('Повтор неисправности'); expect(container.textContent).toContain('Количество нарядов2'); expect(container.textContent).toContain('Интервал, ч24'); expect(container.textContent).toContain('Нужна проверка причины');
  expect([...container.querySelectorAll('a')].map(link => link.getAttribute('href'))).toEqual(expect.arrayContaining(['/orders/order-1', '/orders/order-2']));
});

it('blocks worker anomalies before requests and hides other workers despite manipulated URL', async () => {
  const requests: URL[] = []; await mount(AnomaliesPage, client(anomalies, requests), worker);
  expect(container.querySelector('[role="alert"]')?.textContent).toContain('недоступен исполнителю'); expect(requests).toHaveLength(0);
  await act(async () => root.unmount()); container.remove();
  const other = { ...rating.items[0], worker_id: 'other', display_name: 'Чужая оценка' };
  await mount(RatingPage, client({ ...rating, items: [...rating.items, other] }, requests), worker, '/?assignee_id=other&brigade_id=other-brigade');
  expect(container.textContent).not.toContain('Чужая оценка'); expect(container.querySelector('select[name="assignee_id"]')).toBeNull(); expect(container.querySelector('select[name="brigade_id"]')).toBeNull();
  const report = requests.find(url => url.pathname === '/api/v1/reports/rating')!;
  expect(report.searchParams.get('assignee_id')).toBe('own-worker'); expect(report.searchParams.has('brigade_id')).toBe(false);
});

it('renders API errors with retry instead of empty results', async () => {
  await mount(RatingPage, client({ error: { code: 'forbidden', message: 'Участок недоступен', details: [] } }, [], 403));
  expect(container.querySelector('[role="alert"]')?.textContent).toContain('Участок недоступен'); expect(container.textContent).not.toContain('Нет закрытых работ для рейтинга');
  expect([...container.querySelectorAll('button')].some(button => button.textContent === 'Повторить запрос')).toBe(true);
});

it('rejects reversed periods before calling the report API', async () => {
  const requests: URL[] = []; await mount(RatingPage, client(rating, requests), master, '/?start=2026-10-09T00:00&end=2026-10-08T00:00');
  expect(container.querySelector('[role="alert"]')?.textContent).toContain('Начало периода должно быть раньше окончания');
  expect(requests.some(url => url.pathname === '/api/v1/reports/rating')).toBe(false);
});

it('renders null scores without assigning zero', async () => {
  const empty = { ...rating.items[0], closed_count: 0, score: null, components: Object.fromEntries(['Q', 'T', 'R', 'V'].map(key => [key, { value: null, sample_size: 0, reason: 'Нет закрытых работ' }])) };
  await mount(RatingPage, client({ ...rating, items: [empty] }));
  expect(container.querySelector('[aria-label="Итоговый рейтинг"]')?.textContent).toBe('Нет данных');
  expect(container.textContent).toContain('Выборка: 0');
});

it('does not display a late response from previous filters', async () => {
  let finishOld: (value: Response) => void = () => {}; let finishNew: (value: Response) => void = () => {};
  const api = client(shift, [], 200, url => new Promise<Response>(resolve => { if (url.searchParams.has('area_id')) finishNew = resolve; else finishOld = resolve; }));
  await mount(ShiftReportPage, api); expect(container.querySelector('[role="status"]')).not.toBeNull();
  await choose('area_id', 'area-1');
  await act(async () => finishNew(json({ ...shift, summary: 'Актуальный участок' })));
  await act(async () => finishOld(json({ ...shift, summary: 'Старый участок' })));
  expect(container.textContent).toContain('Актуальный участок'); expect(container.textContent).not.toContain('Старый участок');
});

it('preserves common filters across report navigation and scopes shift selection to shift reports', async () => {
  await mount(ShiftReportPage, client(shift), master, '/?start=2026-09-01T00:00&end=2026-10-01T00:00&area_id=area-1&equipment_id=equipment-1&assignee_id=own-worker&brigade_id=brigade-1&shift_id=shift-1');
  const links = [...container.querySelectorAll<HTMLAnchorElement>('nav a')];
  const ratingLink = new URL(links.find(link => link.textContent === 'Рейтинг')!.href);
  expect(Object.fromEntries(ratingLink.searchParams)).toEqual({ start: '2026-09-01T00:00', end: '2026-10-01T00:00', area_id: 'area-1', equipment_id: 'equipment-1', assignee_id: 'own-worker', brigade_id: 'brigade-1' });
  const reportLink = new URL(links.find(link => link.textContent === 'Отчёт')!.href);
  expect(reportLink.searchParams.get('shift_id')).toBe('shift-1');
});

it.each(['/', '/?start=2026-09-01T00:00'])('keeps a delayed report and server-derived default end stable across shift refreshes at %s', async path => {
  let shiftRequests = 0;
  const reports: { url: URL; signal: AbortSignal; finish: (value: Response) => void }[] = [];
  const api = new ApiClient(async (input, init) => {
    const url = new URL(String(input), 'https://test.local');
    if (url.pathname === '/api/v1/shift') {
      const as_of = new Date(Date.parse(period.as_of) + shiftRequests++ * 3000).toISOString();
      return json({ as_of, timezone: period.timezone, items: [] });
    }
    if (url.pathname.includes('/catalog/')) return json({ items: [], total: 0 });
    return new Promise<Response>(finish => reports.push({ url, signal: init!.signal as AbortSignal, finish }));
  });
  await mount(ShiftReportPage, api, master, path);
  const firstStart = container.querySelector<HTMLInputElement>('input[name="start"]')!.value;
  const firstEnd = container.querySelector<HTMLInputElement>('input[name="end"]')!.value;
  await act(async () => events.invalidate());
  await act(async () => events.invalidate());
  expect(shiftRequests).toBe(3);
  expect(reports).toHaveLength(1);
  expect(reports[0].signal.aborted).toBe(false);
  expect(reports[0].url.searchParams.get('end_at')).toBe('2026-10-07T20:00:00.000Z');
  expect(container.querySelector<HTMLInputElement>('input[name="start"]')!.value).toBe(firstStart);
  expect(container.querySelector<HTMLInputElement>('input[name="end"]')!.value).toBe(firstEnd);
  await act(async () => reports[0].finish(json({ ...shift, summary: 'Медленный отчёт завершён' })));
  expect(container.textContent).toContain('Медленный отчёт завершён');
  expect(container.querySelector('[role="status"]')).toBeNull();
});

it('recomputes the server-derived period if the enterprise timezone changes', async () => {
  let shiftRequests = 0;
  const reports: URL[] = [];
  const api = new ApiClient(async input => {
    const url = new URL(String(input), 'https://test.local');
    if (url.pathname === '/api/v1/shift') return json({ as_of: period.as_of, timezone: shiftRequests++ === 0 ? period.timezone : 'Asia/Tokyo', items: [] });
    if (url.pathname.includes('/catalog/')) return json({ items: [], total: 0 });
    reports.push(url); return json(shift);
  });
  await mount(ShiftReportPage, api);
  await act(async () => events.invalidate());
  expect(reports).toHaveLength(2);
  expect(reports[0].searchParams.get('start_at')).toBe('2026-07-07T19:00:00.000Z');
  expect(reports[1].searchParams.get('start_at')).toBe('2026-07-07T15:00:00.000Z');
  expect(container.querySelector<HTMLInputElement>('input[name="end"]')!.value).toBe('2026-10-08T05:00');
});

it('starts a new server-derived snapshot when the report user changes', async () => {
  let shiftRequests = 0;
  const reports: URL[] = [];
  const api = new ApiClient(async input => {
    const url = new URL(String(input), 'https://test.local');
    if (url.pathname === '/api/v1/shift') return json({ as_of: new Date(Date.parse(period.as_of) + shiftRequests++ * 3000).toISOString(), timezone: period.timezone, items: [] });
    if (url.pathname.includes('/catalog/')) return json({ items: [], total: 0 });
    reports.push(url); return json(shift);
  });
  await mount(ShiftReportPage, api);
  await act(async () => events.invalidate());
  await act(async () => root.render(<MemoryRouter><ShiftReportPage api={api} user={worker} /></MemoryRouter>));
  expect(reports).toHaveLength(2);
  expect(reports[1].searchParams.get('assignee_id')).toBe('own-worker');
  expect(reports[1].searchParams.get('end_at')).toBe('2026-10-07T20:00:03.000Z');
});
