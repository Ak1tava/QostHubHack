import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router';
import { expect, it, vi } from 'vitest';

vi.mock('./PwaUpdatePrompt', () => ({ PwaUpdatePrompt: () => null }));
vi.mock('./features/auth/session', async importOriginal => {
  const original = await importOriginal<typeof import('./features/auth/session')>();
  const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
  return { ...original, authStore: new original.AuthStore(async input => {
    const path = String(input);
    if (path.endsWith('/me')) return json({ error: { code: 'unauthenticated' } }, 401);
    if (path.endsWith('/judge-profiles')) return json({ error: { code: 'not_found' } }, 404);
    if (path.endsWith('/csrf')) return json({ csrf_token: 'anonymous' });
    if (path.endsWith('/login') || path.endsWith('/judge-login')) return json({ user: { id: 'worker', role: 'worker', display_name: 'Рабочий 1' }, csrf_token: 'signed-in' });
    if (path.endsWith('/logout')) return new Response(null, { status: 204 });
    if (path.includes('/equipment/')) return json({ id: 'equipment', name: 'Насос', area: { name: 'Участок' }, area_id: 'area', public_url: null, recent_work_orders: [], timezone: 'Asia/Qostanay' });
    return json({ items: [], total: 0, timezone: 'Asia/Qostanay' });
  }) };
});

it.each([['/', 'Мои наряды', '/my-orders'], ['/equipment/equipment', 'Насос', '/equipment/equipment']])('renders the password-login destination at %s without racing redirects', async (start, heading, destination) => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  const { App } = await import('./App');
  const { authStore } = await import('./features/auth/session');
  await authStore.logout();
  window.history.replaceState(null, '', start);
  const container = document.createElement('div'); const root = createRoot(container);
  try {
    await act(async () => root.render(<BrowserRouter><App /></BrowserRouter>));
    await act(async () => {
      for (const [name, value] of [['login', 'worker'], ['password', '0042']]) {
        const input = container.querySelector<HTMLInputElement>(`input[name="${name}"]`)!;
        Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, value);
        input.dispatchEvent(new Event('input', { bubbles: true }));
      }
    });
    await act(async () => container.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })));
    expect(container.querySelector('main')?.textContent).toContain(heading);
    expect(window.location.pathname).toBe(destination);
    if (start !== '/') {
      await act(async () => authStore.judgeLogin('worker-2'));
      expect(window.location.pathname).toBe('/my-orders');
      expect(container.querySelector('main')?.textContent).toContain('Мои наряды');
    }
  } finally { await act(async () => root.unmount()); window.history.replaceState(null, '', '/'); }
});
