import { expect, it, vi } from 'vitest';

const user = { id: '0b67179b-bebe-47cb-891b-461fb4795088', display_name: 'Исполнитель', role: 'worker', specialty: null, grade: null, brigade_id: null, shift_id: null };
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

it('restores auth, clears user/CSRF on any protected 401, and stores no private data', async () => {
  const { AuthStore } = await import('./session');
  const storage = vi.spyOn(Storage.prototype, 'setItem');
  const fetcher = vi.fn()
    .mockResolvedValueOnce(json({ user, csrf_token: 'restored' }))
    .mockResolvedValueOnce(json({ error: { code: 'unauthenticated', message: 'Требуется вход', details: [] } }, 401))
    .mockResolvedValueOnce(json({ csrf_token: 'anonymous' }))
    .mockResolvedValueOnce(json({ user, csrf_token: 'rotated' }));
  const store = new AuthStore(fetcher);
  await store.restore();
  expect(store.getSnapshot().user).toEqual(user);
  await expect(store.api.request('/api/v1/catalog/{kind}')).rejects.toMatchObject({ status: 401 });
  expect(store.getSnapshot().user).toBeNull();
  await store.login({ login: 'worker', password: '0042' });
  expect(fetcher.mock.calls[2][0]).toBe('/api/v1/auth/csrf');
  expect(store.getSnapshot().user).toEqual(user);
  expect(storage).not.toHaveBeenCalled();
});

it('returns to login after logout and does not show an initial 401 as a failure', async () => {
  const { AuthStore } = await import('./session');
  const fetcher = vi.fn()
    .mockResolvedValueOnce(json({ error: { code: 'unauthenticated', message: 'Требуется вход', details: [] } }, 401))
    .mockResolvedValueOnce(json({ csrf_token: 'anonymous' }))
    .mockResolvedValueOnce(json({ user, csrf_token: 'rotated' }))
    .mockResolvedValueOnce(new Response(null, { status: 204 }));
  const store = new AuthStore(fetcher);
  await store.restore();
  expect(store.getSnapshot()).toMatchObject({ user: null, loading: false, error: null });
  await store.login({ login: 'worker', password: '0042' });
  await store.logout();
  expect(store.getSnapshot()).toMatchObject({ user: null, busy: false, error: null });
});
