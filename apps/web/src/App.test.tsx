import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { MemoryRouter } from 'react-router';
import { expect, it, vi } from 'vitest';
import { App } from './App';

vi.mock('./PwaUpdatePrompt', () => ({ PwaUpdatePrompt: () => null }));
vi.mock('./features/auth/session', () => {
  const state = { user: { id: 'master', display_name: 'Мастер', role: 'master' }, loading: false, busy: false, error: null };
  return { authStore: { getSnapshot: () => state, subscribe: () => () => {}, restore: vi.fn(),
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
