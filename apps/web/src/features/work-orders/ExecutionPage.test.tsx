import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, expect, it } from 'vitest';
import { ApiClient, type UserView } from '../../lib/api';
import { events } from '../../lib/events';
import { ExecutionPage } from './ExecutionPage';
import { MyOrdersPage } from './MyOrdersPage';

const user: UserView = { id: 'worker', display_name: 'Слесарь', role: 'worker', brigade_id: 'brigade', grade: null, specialty: null, shift_id: null };
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
let root: Root, container: HTMLDivElement, version: number, allowed: string[], timezone: string, requests: { body: string; key: string }[], outcome: () => Promise<Response>;
const order = () => ({ id: 'order', number: 'N-5', description: 'Насос', status: 'IN_PROGRESS', version, assignment_version: 2, assignee_id: null, brigade_id: 'brigade', responsible_id: user.id, priority: 'normal', due_at: '2026-10-04T12:00:00Z', created_at: '2026-10-04T10:00:00Z', is_overdue: false, allowed_actions: allowed, events: [], submission: null, issuance_photos: [{ id: 'initial-photo', read_url: '/api/v1/photos/initial-photo' }] });
beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement('div'); document.body.append(container); root = createRoot(container);
  version = 3; allowed = ['pause', 'submit']; timezone = 'Asia/Qostanay'; requests = []; outcome = async () => json({ revision: 1 }, 201);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); });
function api() {
  return new ApiClient(async (input, init) => {
    const url = new URL(String(input), 'http://localhost');
    if (url.pathname.endsWith('/csrf')) return json({ csrf_token: 'csrf' });
    if (url.pathname.endsWith('/notifications')) return json([]);
    if (url.pathname.endsWith('/shift')) return json({ timezone, items: [], as_of: '2026-10-04T10:00:00Z' });
    if (init?.method === 'POST') { requests.push({ body: String(init.body), key: new Headers(init.headers).get('Idempotency-Key')! }); return outcome(); }
    if (url.pathname.endsWith('/work-codes')) return json({ items: [{ id: 'code', code: '01', name: 'Течь' }], total: 1 });
    if (url.pathname.endsWith('/materials')) return json({ items: [{ id: 'material', name: 'Масло', unit: 'л' }], total: 1 });
    return json(order());
  });
}
async function render() { await act(async () => root.render(<MemoryRouter><ExecutionPage api={api()} user={user} orderId="order" /></MemoryRouter>)); }
function button(text: string) { return [...container.querySelectorAll<HTMLButtonElement>('button')].find(item => item.textContent === text)!; }
async function fill(name: string, value: string) {
  await act(async () => { const field = container.querySelector<HTMLInputElement | HTMLTextAreaElement>(`[name="${name}"]`)!; expect(field).not.toBeNull(); const proto = field instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype; Object.getOwnPropertyDescriptor(proto, 'value')!.set!.call(field, value); field.dispatchEvent(new Event('input', { bubbles: true })); });
}
async function select(name: string, value: string) { await act(async () => { const field = container.querySelector<HTMLSelectElement>(`[name="${name}"]`)!; field.value = value; field.dispatchEvent(new Event('change', { bubbles: true })); }); }
async function report() { await fill('work_description', 'Устранена течь'); await select('fault_code_id', 'code'); await act(async () => container.querySelector<HTMLInputElement>('[name="no_materials_used"]')!.click()); }

it('shows only allowed worker actions and requires a pause reason', async () => {
  await render(); expect(button('Принять')).toBeUndefined();
  expect(button('Приостановить')).toBeDefined(); await act(async () => button('Приостановить').click());
  expect(button('Применить').disabled).toBe(true);
  await fill('reason', 'Ждём материал'); await act(async () => button('Применить').click());
  expect(JSON.parse(requests[0].body)).toEqual({ action: 'pause', expected_version: 3, reason: 'Ждём материал' });
});

it('shows the actual protected issuance photo to its assigned worker', async () => {
  await render();
  expect(container.querySelector('img[alt="Фото мастера при выдаче"]')?.getAttribute('src')).toBe('/api/v1/photos/initial-photo');
});
it('shows deadlines in the server-configured enterprise timezone', async () => {
  timezone = 'UTC'; await render(); expect(container.textContent).toContain('04.10, 12:00 (UTC)');
});
it.each([
  ['accept', 'Принять'], ['queue', 'В очередь'], ['start', 'Начать работу'], ['resume', 'Продолжить'], ['restart', 'Начать доработку'],
])('sends the server-allowed %s worker action', async (action, label) => {
  allowed = [action]; await render(); await act(async () => button(label).click()); await act(async () => button('Применить').click());
  expect(JSON.parse(requests[0].body)).toEqual({ action, expected_version: 3 });
});
it('requires the explicit rejection reason', async () => {
  allowed = ['reject']; await render(); await act(async () => button('Отказаться').click()); expect(button('Применить').disabled).toBe(true);
  await fill('reason', 'Не моя специальность'); await act(async () => button('Применить').click());
  expect(JSON.parse(requests[0].body)).toEqual({ action: 'reject', expected_version: 3, reason: 'Не моя специальность' });
});
it('preserves report through reconciliation and retries identical body/key after a lost response', async () => {
  await render(); await report(); outcome = async () => { throw new TypeError('offline'); };
  await act(async () => button('Передать на проверку').click());
  version = 4; await act(async () => events.invalidate());
  expect(container.querySelector<HTMLTextAreaElement>('[name="work_description"]')!.value).toBe('Устранена течь');
  outcome = async () => json({ revision: 1 }, 201); await act(async () => button('Повторить отправку').click());
  expect(requests).toHaveLength(2); expect(requests[1]).toEqual(requests[0]);
  expect(JSON.parse(requests[0].body)).toMatchObject({ expected_version: 3, assignment_version: 2, no_materials_used: true, materials: [], after_photo_ids: [] });
});
it('requires explicit no-materials declaration and sends positive decimal quantities as strings', async () => {
  await render(); await fill('work_description', 'Заменено масло'); await select('fault_code_id', 'code');
  expect(button('Передать на проверку').disabled).toBe(true);
  await act(async () => button('Добавить материал').click()); await select('material_id-0', 'material');
  await fill('quantity-0', '-1'); expect(button('Передать на проверку').disabled).toBe(true);
  await fill('quantity-0', '1.25'); await act(async () => button('Передать на проверку').click());
  expect(JSON.parse(requests[0].body).materials).toEqual([{ material_id: 'material', quantity: '1.25' }]);
});
it('refreshes a conflict without automatic resubmission and keeps edited report', async () => {
  await render(); await report(); outcome = async () => { version++; return json({ error: { code: 'version_conflict', message: 'Наряд изменён', details: [] } }, 409); };
  await act(async () => button('Передать на проверку').click());
  expect(requests).toHaveLength(1); expect(container.querySelector<HTMLTextAreaElement>('[name="work_description"]')!.value).toBe('Устранена течь');
  await act(async () => button('Передать на проверку').click()); expect(JSON.parse(requests[1].body).expected_version).toBe(4);
});
it('does not duplicate submission during an in-flight request', async () => {
  await render(); await report(); let done!: (response: Response) => void; outcome = () => new Promise(resolve => { done = resolve; });
  await act(async () => { button('Передать на проверку').click(); button('Передать на проверку').click(); });
  expect(requests).toHaveLength(1); await act(async () => done(json({ revision: 1 }, 201)));
});
it('loads every list page and includes brigade orders for the responsible worker', async () => {
  const offsets: string[] = [];
  const client = new ApiClient(async input => { const url = new URL(String(input), 'http://localhost'); offsets.push(url.searchParams.get('offset')!); const offset = Number(url.searchParams.get('offset')); return json({ items: Array.from({ length: offset ? 1 : 50 }, (_, index) => ({ ...order(), id: String(offset + index), number: `N-${offset + index}`, queue_position: offset + index + 1 })), offset, limit: 50, total: 51 }); });
  await act(async () => root.render(<MemoryRouter><MyOrdersPage api={client} user={user} /></MemoryRouter>));
  expect(offsets).toEqual(['0', '50']); expect(container.querySelectorAll('a.order-card')).toHaveLength(51); expect(container.textContent).toContain('Ответственный бригады');
});
