import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { MemoryRouter } from 'react-router';
import { expect, it } from 'vitest';
import { ApiClient, type UserView } from '../../lib/api';
import { OrderDetailsPage } from './OrderDetailsPage';
import { leakTemplate } from './templateFixture.test-helper';

const user: UserView = { id: 'master', display_name: 'Мастер', role: 'master', specialty: null, grade: null, brigade_id: null, shift_id: null };
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

it('refreshes a conflict and requires a new explicit command with the current version', async () => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  let version = 1;
  const commands: { expected_version: number }[] = [];
  const api = new ApiClient(async (input, init) => {
    const path = String(input);
    if (path.endsWith('/csrf')) return json({ csrf_token: 'test' });
    if (path.endsWith('/notifications')) return json([]);
    if (init?.method === 'POST') {
      commands.push(JSON.parse(String(init.body))); version++;
      return json({ error: { code: 'version_conflict', message: 'Наряд изменён', details: [] } }, 409);
    }
    if (path.includes('/catalog/')) return json({ items: [], total: 0, offset: 0, limit: 200 });
    if (path.startsWith('/api/v1/shift')) return json({ items: [], as_of: new Date().toISOString(), timezone: 'Asia/Qostanay' });
    return json({ id: 'order', number: 'N-1', description: 'Насос', area_id: 'area', equipment_id: 'equipment', assignee_id: 'worker', master_id: user.id, brigade_id: null,
      responsible_id: null, work_type: 'planned', priority: 'normal', status: 'ISSUED', version, assignment_version: 1, queue_position: null, due_at: '2026-10-04T12:00:00Z',
      created_at: '2026-10-04T10:00:00Z', is_overdue: false, allowed_actions: ['reprioritize'], events: [], submission: null });
  });
  const container = document.createElement('div'); document.body.append(container);
  const root = createRoot(container);
  try {
    await act(async () => root.render(<MemoryRouter><OrderDetailsPage api={api} user={user} orderId="order" /></MemoryRouter>));
    await act(async () => [...container.querySelectorAll('button')].find(button => button.textContent === 'Изменить приоритет')!.click());
    await act(async () => { const field = container.querySelector<HTMLSelectElement>('select[name="priority"]')!; field.value = 'high'; field.dispatchEvent(new Event('change', { bubbles: true })); });
    await act(async () => container.querySelector<HTMLButtonElement>('button[type="submit"]')!.click());
    expect(commands).toEqual([{ action: 'reprioritize', expected_version: 1, priority: 'high' }]);
    expect(container.textContent).toContain('Наряд изменён');
    await act(async () => container.querySelector<HTMLButtonElement>('button[type="submit"]')!.click());
    expect(commands[1].expected_version).toBe(2);
  } finally { await act(async () => root.unmount()); container.remove(); }
});

it('shows the issued template and persisted checklist to the master', async () => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  const api = new ApiClient(async input => {
    const path = String(input);
    if (path.endsWith('/notifications')) return json([]);
    if (path.includes('/catalog/')) return json({ items: [], total: 0 });
    if (path.includes('/shift')) return json({ items: [], timezone: 'Asia/Qostanay' });
    return json({ id: 'order', number: 'N-template', description: 'Течь', created_at: '2026-10-08T10:00:00Z', priority: 'normal', status: 'AI_REVIEW', master_id: user.id, due_at: '2026-10-08T12:00:00Z', allowed_actions: [], template_snapshot: leakTemplate,
      submission: { id: 'report', revision: 1, work_description: 'Видимый участок восстановлен', no_materials_used: true, template_answers: leakTemplate.checklist.map(item => ({ id: item.id, checked: true })) } });
  });
  const container = document.createElement('div'); const root = createRoot(container);
  try {
    await act(async () => root.render(<MemoryRouter><OrderDetailsPage api={api} user={user} orderId="order" /></MemoryRouter>));
    expect(container.textContent).toContain('Устранение видимой течи · версия 1');
    expect(container.textContent).toContain('Место течи указано: Выполнено');
  } finally { await act(async () => root.unmount()); }
});
