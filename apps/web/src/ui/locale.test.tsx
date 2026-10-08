import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, expect, it, vi } from 'vitest';
import { LocaleProvider, useLocale, localizedTemplate, localizeError } from './locale';
import { ApiClient, ApiError, type UserView } from '../lib/api';
import { MemoryRouter } from 'react-router';
import { OrderDetailsPage } from '../features/work-orders/OrderDetailsPage';
import { PhotoUpload } from '../features/work-orders/PhotoUpload';
import { TelegramPage } from '../features/telegram/TelegramPage';
import { NotificationDeliveryPanel } from '../features/telegram/NotificationDeliveryPanel';
import { ReportFilters } from '../features/reports/ReportFilters';
import { useReportContext } from '../features/reports/data';
import { compressPhoto } from '../lib/compressPhoto';
import { SpeechInput } from '../features/speech/SpeechInput';
import { LoginPage } from '../features/auth/LoginPage';
import { leakTemplate } from '../features/work-orders/templateFixture.test-helper';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const container = document.createElement('div');
document.body.append(container);
const root = createRoot(container);
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
const master: UserView = { id: 'master', role: 'master', display_name: 'Мастер', brigade_id: null, shift_id: null, specialty: null, grade: null };
afterEach(async () => { await act(async () => root.render(null)); localStorage.clear(); vi.restoreAllMocks(); });
function Switch() {
  const { locale, setLocale } = useLocale();
  return <button onClick={() => setLocale(locale === 'ru' ? 'kk' : 'ru')}>switch</button>;
}
async function toggle() { await act(async () => container.querySelector('button')!.click()); }

it('defaults to Russian and preserves entered login while switching and after remount', async () => {
  const render = () => <LocaleProvider><Switch /><LoginPage busy={false} error={null} onLogin={async () => {}} /></LocaleProvider>;
  await act(async () => root.render(render()));
  expect(container.textContent).toContain('Вход');
  const login = container.querySelector<HTMLInputElement>('#login')!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(login, 'Мастер-123');
    login.dispatchEvent(new Event('input', { bubbles: true }));
  });
  await toggle();
  expect(container.textContent).toContain('Кіру');
  expect(container.querySelector<HTMLInputElement>('#login')!.value).toBe('Мастер-123');
  expect(document.documentElement.lang).toBe('kk');
  await act(async () => root.render(null));
  await act(async () => root.render(render()));
  expect(container.textContent).toContain('Кіру');
});

it('works when localStorage is denied and ignores unsupported persisted locales', async () => {
  localStorage.setItem('naryadai.locale', 'en');
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new DOMException('denied'); });
  await act(async () => root.render(<LocaleProvider><Switch /><LoginPage busy={false} error={null} onLogin={async () => {}} /></LocaleProvider>));
  expect(container.textContent).toContain('Вход');
  await toggle();
  expect(container.textContent).toContain('Кіру');
});

it('uses UI locale as speech default while preserving an explicit speech language edit', async () => {
  localStorage.setItem('naryadai.locale', 'kk');
  await act(async () => root.render(<LocaleProvider><Switch /><SpeechInput api={new ApiClient()} value="" onChange={() => {}} maxLength={4000} /></LocaleProvider>));
  const select = container.querySelector('select')!;
  expect(select.value).toBe('kk');
  await act(async () => { select.value = 'ru'; select.dispatchEvent(new Event('change', { bubbles: true })); });
  await toggle(); await toggle();
  expect(select.value).toBe('ru');
});

it('localizes known error codes while preserving unknown server error text', async () => {
  localStorage.setItem('naryadai.locale', 'kk');
  await act(async () => root.render(<LocaleProvider><LoginPage busy={false} error={new ApiError(401, 'invalid_credentials', 'server text')} onLogin={async () => {}} /></LocaleProvider>));
  expect(container.textContent).toContain('Логин немесе құпиясөз қате');
  await act(async () => root.render(<LocaleProvider><LoginPage busy={false} error={new ApiError(400, 'unknown_custom_error', 'Текст из документа')} onLogin={async () => {}} /></LocaleProvider>));
  expect(container.textContent).toContain('Текст из документа');
});

it('translates shipped template ID/version/checklist IDs only and preserves descriptions', () => {
  const known = localizedTemplate(leakTemplate, 'kk');
  expect(known.title).toBe('Көрінетін ағуды жою');
  expect(known.checklist[0].label.toLowerCase()).toContain('ағу');
  expect(known.initial_description).toBe(leakTemplate.initial_description);
  expect(localizedTemplate({ ...leakTemplate, version: 2 }, 'kk')).toEqual({ ...leakTemplate, version: 2 });
  expect(localizedTemplate({ ...leakTemplate, id: 'custom' } as unknown as typeof leakTemplate, 'kk')).toEqual({ ...leakTemplate, id: 'custom' });
  const custom = { ...leakTemplate, checklist: [{ id: 'custom', label: 'Непереводимый текст', required: true }] };
  expect(localizedTemplate(custom, 'kk').checklist[0].label).toBe('Непереводимый текст');
});

it('switches master commands, selected command and known history while preserving raw input and unknown actions', async () => {
  const api = new ApiClient(async input => {
    const path = String(input);
    if (path.endsWith('/notifications')) return json([]);
    if (path.includes('/catalog/')) return json({ items: [], total: 0 });
    if (path.includes('/shift')) return json({ items: [], timezone: 'Asia/Qostanay' });
    return json({ id: 'order', number: 'T17', status: 'ISSUED', priority: 'normal', description: 'Отменить', created_at: '2026-10-08T10:00:00Z', due_at: '2026-10-08T12:00:00Z', allowed_actions: ['cancel', 'reassign', 'reprioritize'],
      events: [{ id: 'known', action: 'create', occurred_at: '2026-10-08T10:00:00Z' }, { id: 'unknown', action: 'Отменить', occurred_at: '2026-10-08T10:00:00Z' }] });
  });
  await act(async () => root.render(<LocaleProvider><Switch /><MemoryRouter><OrderDetailsPage api={api} user={master} orderId="order" /></MemoryRouter></LocaleProvider>));
  await act(async () => [...container.querySelectorAll('button')].find(button => button.textContent === 'Отменить')!.click());
  const reason = container.querySelector<HTMLTextAreaElement>('[name="reason"]')!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(reason, 'Причина без перевода');
    reason.dispatchEvent(new Event('input', { bubbles: true }));
  });
  await toggle();
  const labels = [...container.querySelectorAll('.choices button')].map(button => button.textContent);
  expect(labels).toEqual(['Қайта тағайындау', 'Болдырмау', 'Басымдықты өзгерту']);
  expect(container.querySelector('.action-form h3')!.textContent).toBe('Болдырмау');
  expect(container.querySelector<HTMLTextAreaElement>('[name="reason"]')!.value).toBe('Причина без перевода');
  expect([...container.querySelectorAll('.history strong')].map(element => element.textContent)).toEqual(['Беру', 'Отменить']);
  expect(container.querySelector('.full-description')!.textContent).toBe('Отменить');
});

it('updates already displayed authored Telegram and delivery errors after switching languages', async () => {
  const api = new ApiClient(async input => {
    const path = String(input);
    if (path.endsWith('/csrf')) return json({ csrf_token: 'csrf' });
    if (path.endsWith('/status')) return json({ linked: false });
    return json({ error: { code: 'telegram_not_configured', message: 'private diagnostic', details: [] } }, 503);
  });
  await act(async () => root.render(<LocaleProvider><Switch /><TelegramPage api={api} /><NotificationDeliveryPanel api={api} user={master} orderId="order" /></LocaleProvider>));
  await act(async () => [...container.querySelectorAll('button')].find(button => button.textContent === 'Привязать Telegram')!.click());
  expect([...container.querySelectorAll('[role="alert"]')].map(element => element.textContent)).toEqual(Array(2).fill('Telegram пока не настроен. Обратитесь к мастеру.'));
  await toggle();
  expect([...container.querySelectorAll('[role="alert"]')].map(element => element.textContent)).toEqual(Array(2).fill('Telegram әлі бапталмаған. Шеберге хабарласыңыз.'));
  expect(container.textContent).not.toContain('private diagnostic');
});

it('localizes actual photo helper errors at render and leaves untyped or unknown server errors unchanged', async () => {
  const raw = 'Исходное фото слишком большое или пустое. Выберите фото до 40 МБ.';
  const failure = await compressPhoto(new File([], 'empty.jpg', { type: 'image/jpeg' })).catch(error => error as Error);
  expect(localizeError('ru', failure as Error)).toBe(raw);
  expect(localizeError('kk', failure as Error)).toBe('Бастапқы фото тым үлкен немесе бос. 40 МБ дейінгі фотоны таңдаңыз.');
  expect(localizeError('kk', new Error(raw))).toBe(raw);
  expect(localizeError('kk', new ApiError(422, 'custom_unknown', raw))).toBe(raw);
  await act(async () => root.render(<LocaleProvider><Switch /><PhotoUpload api={new ApiClient()} orderId="order" type="before" disabled={false} onUploaded={() => {}} /></LocaleProvider>));
  const input = container.querySelector<HTMLInputElement>('input[type="file"]')!;
  await act(async () => {
    Object.defineProperty(input, 'files', { value: [new File([], 'empty.jpg', { type: 'image/jpeg' })], configurable: true });
    input.dispatchEvent(new Event('change', { bubbles: true }));
  });
  expect(container.querySelector('[role="alert"]')!.textContent).toBe(raw);
  await toggle();
  expect(container.querySelector('[role="alert"]')!.textContent).toBe('Бастапқы фото тым үлкен немесе бос. 40 МБ дейінгі фотоны таңдаңыз.');
});

it('switches authored period validation while retaining entered dates', async () => {
  const api = new ApiClient(async input => String(input).includes('/shift')
    ? json({ items: [], timezone: 'Asia/Qostanay', as_of: '2026-10-08T12:00:00Z' })
    : json({ items: [], total: 0 }));
  function Period() { const context = useReportContext(api, master); return <ReportFilters context={context} user={master} />; }
  await act(async () => root.render(<LocaleProvider><Switch /><MemoryRouter initialEntries={['/?start=2026-10-08T12:00&end=2026-10-07T12:00']}><Period /></MemoryRouter></LocaleProvider>));
  expect(container.querySelector('[role="alert"]')!.textContent).toBe('Начало периода должно быть раньше окончания');
  await toggle();
  expect(container.querySelector('[role="alert"]')!.textContent).toBe('Кезеңнің басталуы аяқталуынан бұрын болуы керек');
  expect(container.querySelector<HTMLInputElement>('[name="start"]')!.value).toBe('2026-10-08T12:00');
});
