import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter, Route, Routes } from 'react-router';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ApiClient, type UserView } from '../../lib/api';
import { CreateOrderPage } from './CreateOrderPage';
vi.mock('../../lib/compressPhoto', () => ({ compressPhoto: async (file: File) => file }));

const area = '11111111-1111-4111-8111-111111111111';
const otherArea = '22222222-2222-4222-8222-222222222222';
const workerId = '33333333-3333-4333-8333-333333333333';
const equipment = '44444444-4444-4444-8444-444444444444';
const brigade = '55555555-5555-4555-8555-555555555555';
const master: UserView = { id: '66666666-6666-4666-8666-666666666666', display_name: 'Мастер', role: 'master', specialty: null, grade: null, brigade_id: null, shift_id: null };
const worker: UserView = { ...master, id: workerId, display_name: 'Слесарь', role: 'worker', brigade_id: brigade };
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
let root: Root, container: HTMLDivElement;
let commands: { body: string; key: string }[];
let result: () => Promise<Response>;
let secondArea: boolean;
let photoAttempts: FormData[];
let photoResult: () => Promise<Response>;

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement('div'); document.body.append(container); root = createRoot(container);
  commands = []; secondArea = false;
  photoAttempts = [];
  photoResult = async () => json({ id: `photo-${photoAttempts.length}`, read_url: `/api/v1/photos/${photoAttempts.length}` }, 201);
  result = async () => json({ id: 'created' }, 201);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); });

async function render() {
  const fetcher = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'http://localhost');
    if (url.pathname.endsWith('/csrf')) return json({ csrf_token: 'test-csrf' });
    if (url.pathname.endsWith('/photos')) { photoAttempts.push(init!.body as FormData); return photoResult(); }
    if (init?.method === 'POST') {
      commands.push({ body: String(init.body), key: new Headers(init.headers).get('Idempotency-Key')! });
      return result();
    }
    if (url.pathname.endsWith('/shift')) return json({ timezone: 'Asia/Qostanay', as_of: new Date().toISOString(), items: [master, ...(url.searchParams.get('area_id') === otherArea ? [] : [worker])].map(user => ({ user, start_at: new Date(Date.now() - 3_600_000).toISOString(), end_at: new Date(Date.now() + 3_600_000).toISOString(), availability: user.role === 'worker' ? 'busy' : 'free', queue_count: user.role === 'worker' ? 2 : 0, active_work_order_id: null })) });
    const items = url.pathname.endsWith('/areas') ? [{ id: area, name: 'Первый участок' }, ...(secondArea ? [{ id: otherArea, name: 'Другой участок' }] : [])] : url.pathname.endsWith('/equipment') ? [{ id: equipment, name: 'Насос', area_id: area }, { id: 'other-equipment', name: 'Другой насос', area_id: otherArea }] : [{ id: brigade, name: 'Бригада 1' }];
    return json({ items, total: items.length, offset: 0, limit: 200 });
  });
  const api = new ApiClient(fetcher);
  await act(async () => root.render(<MemoryRouter initialEntries={[`/orders/new?area_id=${area}&assignee_id=${workerId}`]}><Routes>
    <Route path="/orders/new" element={<CreateOrderPage api={api} user={master} />} />
    <Route path="/orders/:id" element={<p>Наряд создан</p>} />
  </Routes></MemoryRouter>));
}
function button(text: string) { return [...container.querySelectorAll<HTMLButtonElement>('button')].find(b => b.textContent === text)!; }
async function choose(text: string) { await act(async () => button(text).click()); }
async function describeWork() {
  const input = container.querySelector<HTMLTextAreaElement>('textarea[name="description"]')!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(input, 'Проверить насос');
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
}
async function select(name: string, value: string) {
  await act(async () => { const field = container.querySelector<HTMLSelectElement>(`select[name="${name}"]`)!; field.value = value; field.dispatchEvent(new Event('change', { bubbles: true })); });
}

it('blocks missing fields and shows the current selected worker occupancy', async () => {
  await render();
  expect(container.querySelector<HTMLButtonElement>('button[type="submit"]')!.disabled).toBe(true);
  expect(container.textContent).toContain('Занят'); expect(container.textContent).toContain('2');
  await choose('Насос'); await describeWork();
  expect(container.querySelector<HTMLButtonElement>('button[type="submit"]')!.disabled).toBe(false);
});

it('clears incompatible equipment and assignment on an area change', async () => {
  secondArea = true; await render(); await choose('Насос'); await describeWork();
  await choose('Другой участок');
  expect(container.querySelector<HTMLSelectElement>('select[name="assignee_id"]')!.value).toBe('');
  expect(container.querySelector<HTMLButtonElement>('button[type="submit"]')!.disabled).toBe(true);
  expect(button('Насос')).toBeUndefined();
});

it('requires and sends a responsible worker for a brigade', async () => {
  await render(); await choose('Насос'); await describeWork(); await choose('Бригада');
  await select('brigade_id', brigade);
  expect(container.querySelector<HTMLButtonElement>('button[type="submit"]')!.disabled).toBe(true);
  await select('responsible_id', workerId);
  await act(async () => container.querySelector<HTMLButtonElement>('button[type="submit"]')!.click());
  expect(JSON.parse(commands[0].body)).toMatchObject({ brigade_id: brigade, responsible_id: workerId, assignee_id: null });
});

it('preserves input and repeats the identical command after an unknown network outcome', async () => {
  await render(); await choose('Насос'); await describeWork();
  result = async () => { throw new TypeError('offline'); };
  await act(async () => container.querySelector<HTMLButtonElement>('button[type="submit"]')!.click());
  expect(container.querySelector<HTMLTextAreaElement>('textarea')!.value).toBe('Проверить насос');
  expect(container.querySelector<HTMLTextAreaElement>('textarea')!.matches(':disabled')).toBe(true);
  result = async () => json({ id: 'created' }, 201);
  await act(async () => button('Повторить выдачу').click());
  expect(commands).toHaveLength(2); expect(commands[1]).toEqual(commands[0]);
  expect(container.textContent).toContain('Наряд создан');
});

it('does not send a second command while the first request is pending', async () => {
  await render(); await choose('Насос'); await describeWork();
  let resolve!: (response: Response) => void;
  result = () => new Promise<Response>(done => { resolve = done; });
  const submit = container.querySelector<HTMLButtonElement>('button[type="submit"]')!;
  await act(async () => { submit.click(); submit.click(); });
  expect(commands).toHaveLength(1);
  await act(async () => resolve(json({ id: 'created' }, 201)));
});

it('leaves a manually cleared deadline empty instead of silently restoring the initial default', async () => {
  await render(); await choose('Насос'); await describeWork();
  const field = container.querySelector<HTMLInputElement>('input[type="datetime-local"]')!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(field, '');
    field.dispatchEvent(new Event('input', { bubbles: true }));
  });
  expect(field.value).toBe('');
  expect(container.querySelector<HTMLButtonElement>('button[type="submit"]')!.disabled).toBe(true);
});

it('retains the issued order and successful photos when a later upload fails and retries only remaining photos', async () => {
  await render(); await choose('Насос'); await describeWork();
  const input = container.querySelector<HTMLInputElement>('input[type="file"]');
  expect(input).not.toBeNull();
  Object.defineProperty(input!, 'files', { value: [new File(['first'], 'first.jpg', { type: 'image/jpeg' }), new File(['second'], 'second.jpg', { type: 'image/jpeg' })] });
  await act(async () => input!.dispatchEvent(new Event('change', { bubbles: true })));
  result = async () => json({ id: 'created', version: 1, assignment_version: 1 }, 201);
  photoResult = async () => { if (photoAttempts.length === 2) throw new TypeError('offline'); return json({ id: 'photo-1', read_url: '/api/v1/photos/one' }, 201); };
  await act(async () => container.querySelector<HTMLButtonElement>('button[type="submit"]')!.click());
  expect(commands).toHaveLength(1); expect(photoAttempts).toHaveLength(2);
  expect(container.textContent).toContain('Загружено фото: 1 из 2');
  expect(container.querySelector('img')!.getAttribute('src')).toBe('/api/v1/photos/one');
  photoResult = async () => json({ id: 'photo-2', read_url: '/api/v1/photos/two' }, 201);
  await act(async () => button('Повторить загрузку фото').click());
  expect(commands).toHaveLength(1); expect(photoAttempts).toHaveLength(3);
  expect((photoAttempts[2].get('file') as File).name).toBe('second.jpg');
  expect(photoAttempts[2].get('expected_version')).toBe('1');
  expect(photoAttempts[2].get('assignment_version')).toBe('1');
  expect(container.textContent).toContain('Наряд создан');
});
