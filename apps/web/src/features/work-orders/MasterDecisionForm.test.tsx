import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, expect, it, vi } from 'vitest';
import { ApiClient, type UserView } from '../../lib/api';
import type { WorkOrderDetail } from './data';
import { MasterDecisionForm } from './MasterDecisionForm';

const master = { id: 'master', role: 'master' } as UserView;
const order = { id: 'order', version: 4, assignment_version: 2, allowed_decisions: ['accept', 'rework'], submission: { id: 'submission', missing_evidence: [] }, ai_review: { result: { verdict: 'accepted', score: 4 } } } as unknown as WorkOrderDetail;
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
let root: ReturnType<typeof createRoot>;
let container: HTMLDivElement;
afterEach(async () => { if (root) await act(async () => root.unmount()); container?.remove(); });
async function mount(api: ApiClient, detail = order, user = master, reload = vi.fn()) {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement('div'); document.body.append(container); root = createRoot(container);
  await act(async () => root.render(<MasterDecisionForm api={api} order={detail} user={user} reload={reload} onDecided={vi.fn()} />));
}
const submit = () => container.querySelector<HTMLButtonElement>('button[type="submit"]')!;
async function choose(value: string) { await act(async () => { const field = container.querySelector<HTMLSelectElement>('select[name="decision"]')!; field.value = value; field.dispatchEvent(new Event('change', { bubbles: true })); }); }
async function reason(value: string) { await act(async () => { const field = container.querySelector<HTMLTextAreaElement>('textarea')!; Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(field, value); field.dispatchEvent(new Event('input', { bubbles: true })); }); }

it('requires explicit selection and reasons for rework, changed score and acceptance without AI', async () => {
  await mount(new ApiClient()); expect(submit().disabled).toBe(true);
  await choose('rework'); expect(submit().disabled).toBe(true);
  await reason('Нужно устранить течь'); expect(submit().disabled).toBe(false);
  await choose('accept'); expect(submit().disabled).toBe(false);
  await act(async () => { const field = container.querySelector<HTMLSelectElement>('select[name="score"]')!; field.value = '5'; field.dispatchEvent(new Event('change', { bubbles: true })); });
  await reason(''); expect(submit().disabled).toBe(true);
  await act(async () => root.render(<MasterDecisionForm api={new ApiClient()} order={{ ...order, ai_review: null }} user={master} reload={vi.fn()} onDecided={vi.fn()} />));
  await choose('accept'); expect(submit().disabled).toBe(true);
});

it('does not permit acceptance with missing evidence and renders no worker decision controls', async () => {
  await mount(new ApiClient(), { ...order, submission: { ...order.submission!, missing_evidence: ['after_photo'] } });
  expect(container.querySelector('option[value="accept"]')).toBeNull();
  await act(async () => root.render(<MasterDecisionForm api={new ApiClient()} order={order} user={{ ...master, role: 'worker' }} reload={vi.fn()} onDecided={vi.fn()} />));
  expect(container.querySelector('form')).toBeNull();
});

it('retries the frozen payload and idempotency key after a network failure', async () => {
  const requests: { body: string; key: string | null }[] = [];
  const api = new ApiClient(async (input, init) => {
    if (String(input).endsWith('/csrf')) return json({ csrf_token: 'test' });
    requests.push({ body: String(init?.body), key: new Headers(init?.headers).get('Idempotency-Key') });
    if (requests.length === 1) throw new TypeError('offline');
    return json({ id: 'order' });
  });
  await mount(api); await choose('accept');
  await act(async () => { submit().click(); submit().click(); });
  expect(requests).toHaveLength(1); expect(container.querySelector('fieldset')!.disabled).toBe(true);
  await act(async () => root.render(<MasterDecisionForm api={api} order={{ ...order, status: 'CLOSED', allowed_decisions: [], version: 5 }} user={master} reload={vi.fn()} onDecided={vi.fn()} />));
  expect(container.querySelector('form')).not.toBeNull();
  await act(async () => submit().click()); expect(requests).toHaveLength(2); expect(requests[1]).toEqual(requests[0]);
  expect(JSON.parse(requests[0].body)).toMatchObject({ decision: 'accept', submission_id: 'submission', expected_version: 4, assignment_version: 2, score: 4 });
});

it('reloads a conflict and requires a new explicit selection', async () => {
  const reload = vi.fn();
  const api = new ApiClient(async (input) => String(input).endsWith('/csrf') ? json({ csrf_token: 'test' }) : json({ error: { code: 'version_conflict', message: 'Наряд изменён', details: [] } }, 409));
  await mount(api, order, master, reload); await choose('accept'); await act(async () => submit().click());
  expect(reload).toHaveBeenCalledOnce(); expect(submit().disabled).toBe(true);
  expect(container.textContent).toContain('Выберите решение заново');
  await choose('accept'); expect(submit().disabled).toBe(true);
  await act(async () => root.render(<MasterDecisionForm api={api} order={{ ...order, version: 5 }} user={master} reload={reload} onDecided={vi.fn()} />));
  expect(submit().disabled).toBe(true); await choose('accept'); expect(submit().disabled).toBe(false);
});

it('requires explanation for overriding the AI verdict and resets selection on a new revision', async () => {
  const api = new ApiClient();
  const detail = { ...order, ai_review: { ...order.ai_review!, result: { ...order.ai_review!.result, verdict: 'requires_rework' as const } } };
  await mount(api, detail); await choose('accept'); expect(submit().disabled).toBe(true);
  await reason('Подтверждено осмотром на месте'); expect(submit().disabled).toBe(false);
  await act(async () => root.render(<MasterDecisionForm api={api} order={{ ...detail, version: 5, submission: { ...detail.submission!, id: 'new-submission', revision: 2 } }} user={master} reload={vi.fn()} onDecided={vi.fn()} />));
  expect(submit().disabled).toBe(true); expect(container.querySelector<HTMLSelectElement>('select[name="decision"]')!.value).toBe('');
});

it('uses only server permissions and hides the form when current access is revoked', async () => {
  await mount(new ApiClient(), { ...order, allowed_decisions: ['rework'] });
  expect(container.querySelector('option[value="accept"]')).toBeNull();
  await choose('rework'); await reason('Доработка');
  await act(async () => root.render(<MasterDecisionForm api={new ApiClient()} order={{ ...order, allowed_decisions: [] }} user={master} reload={vi.fn()} onDecided={vi.fn()} />));
  expect(container.querySelector('form')).toBeNull();
});
