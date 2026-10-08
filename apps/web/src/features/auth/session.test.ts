import { expect, it, vi } from 'vitest';

it('clears the former workspace before switching judge profile and rotates its session', async () => {
  const { AuthStore } = await import('./session');
  const fetcher = vi.fn()
    .mockResolvedValueOnce(json({ user, csrf_token: 'old' }))
    .mockResolvedValueOnce(new Response(null, { status: 204 }))
    .mockResolvedValueOnce(json({ csrf_token: 'anonymous' }))
    .mockResolvedValueOnce(json({ user: { ...user, id: 'worker-2' }, csrf_token: 'new' }));
  const store = new AuthStore(fetcher); await store.restore();
  const snapshots: unknown[] = []; store.subscribe(() => snapshots.push(store.getSnapshot().user));
  await store.judgeLogin('worker-2');
  expect(snapshots).toContain(null);
  expect(store.getSnapshot().user?.id).toBe('worker-2');
  expect(fetcher.mock.calls.map(call => call[0])).toEqual(['/api/v1/auth/me', '/api/v1/auth/logout', '/api/v1/auth/csrf', '/api/v1/auth/judge-login']);
  expect(JSON.parse(fetcher.mock.calls[3][1].body)).toEqual({ profile: 'worker-2' });
});

it('leaves password login available when judge mode is disabled', async () => {
  const { AuthStore } = await import('./session');
  const store = new AuthStore(vi.fn().mockResolvedValue(json({ error: { code: 'not_found', message: 'Not found' } }, 404)));
  await store.loadJudgeProfiles();
  expect(store.getSnapshot()).toMatchObject({ judgeProfiles: [], error: null });
});

it('ignores an old protected 401 after a successful judge profile login', async () => {
  const { AuthStore } = await import('./session');
  let finishOld!: (response: Response) => void;
  const fetcher = vi.fn()
    .mockImplementationOnce(() => new Promise<Response>(resolve => { finishOld = resolve; }))
    .mockResolvedValueOnce(json({ csrf_token: 'anonymous' }))
    .mockResolvedValueOnce(json({ user: { ...user, id: 'worker-2' }, csrf_token: 'new' }));
  const store = new AuthStore(fetcher);
  const pending = store.api.request('/api/v1/shift').catch(error => error);
  await store.judgeLogin('worker-2');
  finishOld(json({ error: { code: 'unauthenticated', message: 'Expired' } }, 401));
  await pending;
  expect(store.getSnapshot().user?.id).toBe('worker-2');
});

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
