import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { MemoryRouter } from 'react-router';
import { beforeEach, expect, it, vi } from 'vitest';
import { App } from './App';

vi.mock('./PwaUpdatePrompt', () => ({ PwaUpdatePrompt: () => null }));
const { state } = vi.hoisted(() => ({ state: { user: { id: 'master', display_name: 'Мастер', role: 'master' as 'master' | 'worker' | 'manager' }, loading: false, busy: false, error: null, judgeProfiles: [] as { code: string }[] } }));
beforeEach(() => { state.user.role = 'master'; state.user.id = 'master'; state.judgeProfiles = []; });
vi.mock('./features/auth/session', () => {
  return { authStore: { getSnapshot: () => state, subscribe: () => () => {}, restore: vi.fn(), loadJudgeProfiles: vi.fn(),
    api: { request: vi.fn().mockResolvedValue({ items: [], total: 0, offset: 0, limit: 50, as_of: new Date().toISOString(), timezone: 'Asia/Qostanay' }) } } };
});

it('opens the shift dashboard after a foreman signs in', async () => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  await act(async () => root.render(<MemoryRouter initialEntries={['/']}><App /></MemoryRouter>));
  expect(container.textContent).toContain('Панель смены');
  await act(async () => root.unmount());
  container.remove();
});

it('lets a signed-in foreman reach reports and Telegram settings', async () => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  await act(async () => root.render(<MemoryRouter initialEntries={['/shift']}><App /></MemoryRouter>));
  const destinations = Array.from(container.querySelectorAll('nav a'), link => link.getAttribute('href'));
  expect(destinations).toContain('/reports/shift');
  expect(destinations).toContain('/telegram');
  expect(destinations).not.toContain('/reports/rating');
  expect(destinations).not.toContain('/analytics/anomalies');
  await act(async () => root.unmount());
  container.remove();
});

it.each(['worker', 'manager'] as const)('opens the role workspace directly for %s', async role => {
  state.user.role = role; state.user.id = role;
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  const container = document.createElement('div'); document.body.append(container); const root = createRoot(container);
  try {
    await act(async () => root.render(<MemoryRouter initialEntries={['/']}><App /></MemoryRouter>));
    const nav = container.querySelector('nav[aria-label="Разделы приложения"]')!;
    expect(nav.querySelector('[aria-current="page"]')?.getAttribute('href')).toBe(role === 'worker' ? '/my-orders' : '/shift');
    expect(container.textContent).not.toContain('Вы вошли');
    if (role === 'worker') expect(nav.textContent).not.toContain('Панель смены');
  } finally { await act(async () => root.unmount()); container.remove(); }
});

it('resets a worker away from the former master shift route', async () => {
  state.user.role = 'worker'; state.user.id = 'worker-2';
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  const container = document.createElement('div'); const root = createRoot(container);
  try {
    await act(async () => root.render(<MemoryRouter initialEntries={['/shift']}><App /></MemoryRouter>));
    expect(container.querySelector('nav [aria-current="page"]')?.getAttribute('href')).toBe('/my-orders');
    expect(container.textContent).not.toContain('Панель доступна мастеру.');
  } finally { await act(async () => root.unmount()); }
});

it('shows a separate fictional five-worker ranking only for a judge foreman', async () => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  const container = document.createElement('div'); const root = createRoot(container);
  try {
    await act(async () => root.render(<MemoryRouter><App /></MemoryRouter>));
    expect(container.querySelector('[aria-label="Пример бригады"]')).toBeNull();
    state.judgeProfiles = [{ code: 'master' }];
    await act(async () => root.render(<MemoryRouter><App /></MemoryRouter>));
    const example = container.querySelector('[aria-label="Пример бригады"]')!;
    expect(example).not.toBeNull();
    expect(example.querySelectorAll('article')).toHaveLength(5);
    const availability = Array.from(example.querySelectorAll('.ui-badge'), node => node.textContent);
    expect(availability.filter(text => text === 'Занят')).toHaveLength(4);
    expect(availability.filter(text => text === 'Свободен')).toHaveLength(1);
  } finally { await act(async () => root.unmount()); }
});
