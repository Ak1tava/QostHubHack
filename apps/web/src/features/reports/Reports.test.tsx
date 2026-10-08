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
import { LanguageSelector, LocaleProvider } from '../../ui/locale';
import type { Locale } from '../../ui/i18n';

const master: UserView = { id: 'master', display_name: 'Мастер', role: 'master', brigade_id: null, shift_id: 'shift-1', specialty: null, grade: null };
const worker: UserView = { ...master, id: 'own-worker', display_name: 'Исполнитель', role: 'worker', brigade_id: 'brigade-1', specialty: 'Слесарь' };
const period = { start_at: '2026-07-07T19:00:00Z', end_at: '2026-10-07T20:00:00Z', as_of: '2026-10-07T20:00:00Z', timezone: 'Asia/Qostanay' };
const shift: ShiftReport = { period, counts: { issued: 11, performed: 7, closed: 5, overdue: 3, rejected: 2 }, workload: { active_seconds: 3661, pause_seconds: 120, review_seconds: 60 }, downtime: { seconds: 0, has_data: false }, summary: 'Закрыто 5 нарядов по данным сервера.', limitations: ['Нет подтверждённых корректировок срока'] };
const rating: Rating = { period, formula_version: 'c6-v1-available', limitations: ['Нормативные часы отсутствуют'], items: [{ worker_id: 'own-worker', display_name: 'Исполнитель', specialty: 'Слесарь', work_type: 'planned', closed_count: 5, score: 83.33, components: { Q: { value: .9, sample_size: 5, reason: null }, T: { value: .7, sample_size: 5, reason: null }, R: { value: null, sample_size: 0, reason: 'Нет подтверждённых повторов' }, V: { value: null, sample_size: 0, reason: 'Нет нормативных часов' } } }] };
const anomalies: Anomalies = { period, limitations: ['Корреляция не доказывает причину'], items: [{ id: 'repeat-1', type: 'repeat_fault', title: 'Повтор неисправности', description: 'Два принятых ремонта одного шифра', equipment_id: 'equipment-1', metrics: { order_count: 2, hours_between: 24 }, evidence_order_ids: ['order-1', 'order-2'], limitations: ['Нужна проверка причины'] }] };
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
let container: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
afterEach(async () => { if (root) await act(async () => root.unmount()); container?.remove(); localStorage.clear(); });

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
async function mount(Page: typeof ShiftReportPage, api: ApiClient, user = master, path = '/', locale?: Locale) {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement('div'); document.body.append(container); root = createRoot(container);
  if (locale) localStorage.setItem('naryadai.locale', locale);
  const content = <MemoryRouter initialEntries={[path]}><Page api={api} user={user} /></MemoryRouter>;
  await act(async () => root.render(locale ? <LocaleProvider><LanguageSelector />{content}</LocaleProvider> : content));
}

it('localizes the canonical shift summary and known limitations and restores original RU text', async () => {
  const report = { ...shift, summary: 'Выдано 11, исполнено 7, закрыто 5. Просроченных за период: 3; отклонённых: 2. Нет данных о простое оборудования.', limitations: [
    'У части нарядов отсутствует журнал: прошлые сроки и назначения восстановлены неполно.',
    'Нет зарегистрированных интервалов простоя за период; это не подтверждает отсутствие простоя.',
    'Уважительность отказов и внешние задержки не структурированы; скрытые штрафы не применяются.',
    'Описание работ',
  ] };
  await mount(ShiftReportPage, client(report), master, '/', 'kk');
  expect(container.querySelector('.report-summary p')!.textContent).toBe('Берілген 11, орындалған 7, жабылған 5. Кезеңде мерзімі өткен: 3; қабылданбаған: 2. Жабдықтың тоқтап тұруы туралы деректер жоқ.');
  expect(container.textContent).toContain('1 сағ 1 мин 1 с');
  expect(container.textContent).toContain('Кейбір нарядтардың журналы жоқ: бұрынғы мерзімдер мен тағайындаулар толық қалпына келтірілмеген.');
  expect(container.textContent).toContain('Кезеңде тоқтап тұру аралықтары тіркелмеген; бұл тоқтап тұру болмағанын растамайды.');
  expect(container.textContent).toContain('Бас тартудың негізділігі мен сыртқы кідірістер құрылымдалмаған; жасырын айыптар қолданылмайды.');
  expect(container.querySelector('.notice li:last-child')!.textContent).toBe('Описание работ');
  await act(async () => [...container.querySelectorAll('button')].find(button => button.textContent === 'RU')!.click());
  expect(container.querySelector('.report-summary p')!.textContent).toBe(report.summary);
  expect(container.querySelector('.notice li')!.textContent).toBe(report.limitations[0]);
});

it('keeps arbitrary or inconsistent shift summaries verbatim and preserves downtime precision', async () => {
  const report = { ...shift, downtime: { has_data: true, seconds: 4500 }, summary: 'Выдано 11, исполнено 7, закрыто 5. Просроченных за период: 3; отклонённых: 2. Простой оборудования: 1.25 ч.' };
  await mount(ShiftReportPage, client(report), master, '/', 'kk');
  expect(container.querySelector('.report-summary p')!.textContent).toContain('Жабдықтың тоқтап тұруы: 1.25 сағ.');
  await act(async () => root.unmount()); container.remove();
  const unknown = 'Описание работ — произвольный текст ИИ';
  await mount(ShiftReportPage, client({ ...report, summary: unknown }), master, '/', 'kk');
  expect(container.querySelector('.report-summary p')!.textContent).toBe(unknown);
  await act(async () => root.unmount()); container.remove();
  const inconsistent = report.summary.replace('Выдано 11', 'Выдано 12');
  await mount(ShiftReportPage, client({ ...report, summary: inconsistent }), master, '/', 'kk');
  expect(container.querySelector('.report-summary p')!.textContent).toBe(inconsistent);
});

it('preserves Python rounded downtime hours and rejects values inconsistent with DTO seconds', async () => {
  const report = { ...shift, downtime: { has_data: true, seconds: 450 }, summary: 'Выдано 11, исполнено 7, закрыто 5. Просроченных за период: 3; отклонённых: 2. Простой оборудования: 0.12 ч.' };
  await mount(ShiftReportPage, client(report), master, '/', 'kk');
  expect(container.querySelector('.report-summary p')!.textContent).toContain('Жабдықтың тоқтап тұруы: 0.12 сағ.');
  await act(async () => root.unmount()); container.remove();
  const inconsistent = report.summary.replace('0.12 ч.', '0.14 ч.');
  await mount(ShiftReportPage, client({ ...report, summary: inconsistent }), master, '/', 'kk');
  expect(container.querySelector('.report-summary p')!.textContent).toBe(inconsistent);
});

it('localizes unavailable rating reasons and limitations while preserving unknown reasons and worker data', async () => {
  const report: Rating = { ...rating, limitations: [
    'Доступные веса нормированы: Q 0.50, T 0.25; R/V неизвестны.',
    'T использует исторический срок: подтверждённые внешние задержки не структурированы.',
    'Оценки ИИ и свободный текст причин не подтверждают качество или вину исполнителя.',
  ], items: [{ ...rating.items[0], display_name: 'Описание работ', components: {
    Q: { value: null, sample_size: 0, reason: 'Нет окончательных оценок мастера.' },
    T: { value: null, sample_size: 0, reason: 'Нет принятых сдач с известным сроком.' },
    R: { value: null, sample_size: 0, reason: 'Окно наблюдения 7 дней не завершено для 5 работ. Нет структурированного подтверждения возврата или повтора по причине качества.' },
    V: { value: null, sample_size: 0, reason: 'Нет нормативных часов работ и исторических доступных часов смен.' },
  } }, { ...rating.items[0], worker_id: 'unknown-reasons', components: { ...rating.items[0].components, R: { value: null, sample_size: 0, reason: 'Описание работ' } } }] };
  await mount(RatingPage, client(report), master, '/', 'kk');
  expect(container.textContent).toContain('Шебердің қорытынды бағалары жоқ.');
  expect(container.textContent).toContain('Мерзімі белгілі қабылданған жұмыстар жоқ.');
  expect(container.textContent).toContain('5 жұмыс үшін 7 күндік бақылау кезеңі аяқталмаған. Сапа себебінен қайтару немесе қайталау туралы құрылымдалған растау жоқ.');
  expect(container.textContent).toContain('Жұмыстардың нормативтік сағаттары мен ауысымдардың тарихи қолжетімді сағаттары жоқ.');
  expect(container.textContent).toContain('Қолжетімді салмақтар нормаланған: Q 0.50, T 0.25; R/V белгісіз.');
  expect(container.textContent).toContain('T тарихи мерзімді пайдаланады: расталған сыртқы кідірістер құрылымдалмаған.');
  expect(container.textContent).toContain('ЖИ бағалары мен себептердің еркін мәтіні сапаны немесе орындаушының кінәсін растамайды.');
  expect(container.querySelector('.rating-person h4')!.textContent).toBe('Описание работ');
  expect(container.querySelectorAll('.rating-components')[1].textContent).toContain('Описание работ');
});

it('localizes only known anomaly system copy and retains arbitrary text and evidence IDs', async () => {
  const limitation = 'Совпадение во времени — сигнал для проверки причины, а не доказательство вины исполнителя.';
  const report: Anomalies = { ...anomalies, limitations: [
    'Повтор шифра и расход анализируются только по окончательно принятым отчётам.',
    'Без сопоставимой нормы превышение расхода не определяется.', limitation,
  ], items: [{ ...anomalies.items[0], title: 'Повтор одного шифра на оборудовании', description: 'Два принятых ремонта одного оборудования с одинаковым окончательным шифром за 7 дней.', limitations: [limitation] },
    { ...anomalies.items[0], id: 'unknown', title: 'Описание работ', description: 'Текст пользователя без перевода', limitations: ['Описание работ'] }] };
  await mount(AnomaliesPage, client(report), master, '/', 'kk');
  expect(container.textContent).toContain('Жабдықта бір кодтың қайталануы');
  expect(container.textContent).toContain('7 күн ішінде бір жабдықтың бірдей қорытынды кодпен қабылданған екі жөндеуі.');
  expect(container.textContent).toContain('Уақыт бойынша сәйкес келу — себепті тексеру сигналы, орындаушы кінәсінің дәлелі емес.');
  expect(container.textContent).toContain('Кодтың қайталануы мен шығын тек түпкілікті қабылданған есептер бойынша талданады.');
  expect(container.textContent).toContain('Салыстыруға болатын норма болмаса, артық шығын анықталмайды.');
  expect(container.querySelectorAll('.insight-card > h3')[1].textContent).toBe('Описание работ');
  expect(container.textContent).toContain('Текст пользователя без перевода');
  expect(container.querySelectorAll('.insight-card .notice li')[1].textContent).toBe('Описание работ');
  expect([...container.querySelectorAll('.insight-evidence a')].map(link => link.getAttribute('href'))).toContain('/orders/order-1');
});
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
  expect(Object.fromEntries(ratingLink.searchParams)).toEqual({ start_at: period.start_at, end_at: period.end_at, area_id: 'area-1', equipment_id: 'equipment-1', assignee_id: 'own-worker', brigade_id: 'brigade-1' });
  const reportLink = new URL(links.find(link => link.textContent === 'Обзор')!.href);
  expect(reportLink.searchParams.get('shift_id')).toBe('shift-1');
});

it('carries the exact effective API period when navigating from a selected shift', async () => {
  const overnight = { ...period, start_at: '2026-10-06T15:00:00Z', end_at: '2026-10-07T03:00:13Z' };
  await mount(ShiftReportPage, client({ ...shift, period: overnight }), master, '/?shift_id=shift-1&start=2026-09-01T00:00&end=2026-10-01T00:00&area_id=area-1');
  const link = [...container.querySelectorAll<HTMLAnchorElement>('nav a')].find(item => item.textContent === 'Рейтинг')!;
  const params = new URL(link.href).searchParams;
  expect(params.get('start_at')).toBe(overnight.start_at); expect(params.get('end_at')).toBe(overnight.end_at);
  expect(params.has('shift_id')).toBe(false); expect(params.has('start')).toBe(false); expect(params.get('area_id')).toBe('area-1');
});

it('keeps exact UTC bounds from report navigation while displaying enterprise time', async () => {
  const requests: URL[] = [];
  await mount(RatingPage, client(rating, requests), master, '/?start_at=2026-10-06T15:00:00Z&end_at=2026-10-07T03:00:13Z');
  const request = requests.find(url => url.pathname === '/api/v1/reports/rating')!;
  expect(request.searchParams.get('end_at')).toBe('2026-10-07T03:00:13Z');
  expect(container.querySelector<HTMLInputElement>('input[name="end"]')!.value).toBe('2026-10-07T08:00');
});

it('shows missing rating components without meters and explains their effective weights', async () => {
  await mount(RatingPage, client(rating));
  expect(container.querySelectorAll('meter')).toHaveLength(3);
  expect(container.textContent).toContain('66,67%'); expect(container.textContent).toContain('33,33%');
});

it('uses server time for quick periods and preserves the permitted area filter', async () => {
  const requests: URL[] = [];
  await mount(ShiftReportPage, client(shift, requests), master, '/?area_id=area-1&shift_id=shift-1');
  const week = [...container.querySelectorAll('button')].find(button => button.textContent === '7 дней')!;
  expect(week).toBeDefined();
  await act(async () => week.click());
  const request = requests.filter(url => url.pathname === '/api/v1/reports/shift').at(-1)!;
  expect(request.searchParams.get('start_at')).toBe('2026-09-30T20:00:00.000Z');
  expect(request.searchParams.get('end_at')).toBe(period.as_of);
  expect(request.searchParams.has('shift_id')).toBe(false); expect(request.searchParams.get('area_id')).toBe('area-1');
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
