import { describe, expect, it, vi } from 'vitest';

const user = { id: '0b67179b-bebe-47cb-891b-461fb4795088', display_name: 'Исполнитель', role: 'worker', specialty: null, grade: null, brigade_id: null, shift_id: null };
const json = (body: unknown, status = 200, headers = {}) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json', ...headers } });
const error = (code: string) => ({ error: { code, message: 'Ошибка входа', details: [] } });

describe('C1.2 API client', () => {
  it('performs csrf → login → me → logout → 401 with string PIN and same-origin cookies', async () => {
    const { ApiClient } = await import('./api');
    const fetcher = vi.fn()
      .mockResolvedValueOnce(json({ csrf_token: 'anonymous' }))
      .mockResolvedValueOnce(json({ user, csrf_token: 'rotated' }))
      .mockResolvedValueOnce(json({ user, csrf_token: 'rotated' }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockResolvedValueOnce(json(error('unauthenticated'), 401));
    const invalidated = vi.fn();
    const client = new ApiClient(fetcher, invalidated);
    await client.login({ login: 'worker', password: '0042' });
    await client.me();
    await client.logout();
    await expect(client.me()).rejects.toMatchObject({ status: 401 });
    expect(fetcher.mock.calls.map(call => call[0])).toEqual(['/api/v1/auth/csrf', '/api/v1/auth/login', '/api/v1/auth/me', '/api/v1/auth/logout', '/api/v1/auth/me']);
    for (const [, options] of fetcher.mock.calls) {
      expect(options).toMatchObject({ credentials: 'same-origin', cache: 'no-store' });
    }
    expect(JSON.parse(fetcher.mock.calls[1][1].body)).toEqual({ login: 'worker', password: '0042' });
    expect(new Headers(fetcher.mock.calls[1][1].headers).get('X-CSRF-Token')).toBe('anonymous');
    expect(new Headers(fetcher.mock.calls[3][1].headers).get('X-CSRF-Token')).toBe('rotated');
    expect(invalidated).toHaveBeenCalledOnce();
  });

  it('restores CSRF through me on reload and uses it for logout', async () => {
    const { ApiClient } = await import('./api');
    const fetcher = vi.fn().mockResolvedValueOnce(json({ user, csrf_token: 'restored' })).mockResolvedValueOnce(new Response(null, { status: 204 }));
    const client = new ApiClient(fetcher);
    await client.me();
    await client.logout();
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(new Headers(fetcher.mock.calls[1][1].headers).get('X-CSRF-Token')).toBe('restored');
  });

  it.each([[401, 'invalid_credentials'], [403, 'csrf_failed']])('discards invalid CSRF after %s before another login', async (status, code) => {
    const { ApiClient } = await import('./api');
    const fetcher = vi.fn()
      .mockResolvedValueOnce(json({ csrf_token: 'old' }))
      .mockResolvedValueOnce(json(error(code), status))
      .mockResolvedValueOnce(json({ csrf_token: 'fresh' }))
      .mockResolvedValueOnce(json({ user, csrf_token: 'new' }));
    const client = new ApiClient(fetcher);
    await expect(client.login({ login: 'worker', password: 'bad' })).rejects.toMatchObject({ status, code });
    await client.login({ login: 'worker', password: '0042' });
    expect(fetcher.mock.calls[2][0]).toBe('/api/v1/auth/csrf');
    expect(new Headers(fetcher.mock.calls[3][1].headers).get('X-CSRF-Token')).toBe('fresh');
  });

  it.each([[422, 'validation_error', null], [429, 'rate_limited', 12]])('keeps structured %s errors and Retry-After', async (status, code, retryAfter) => {
    const { ApiClient } = await import('./api');
    const fetcher = vi.fn().mockResolvedValue(json(error(code), status, retryAfter ? { 'Retry-After': String(retryAfter) } : {}));
    await expect(new ApiClient(fetcher).request('/api/v1/auth/me')).rejects.toMatchObject({ status, code, retryAfter });
  });

  it.each(['network', 'html'])('handles unavailable server (%s) without exposing HTML', async kind => {
    const { ApiClient } = await import('./api');
    const fetcher = kind === 'network' ? vi.fn().mockRejectedValue(new TypeError('offline')) : vi.fn().mockResolvedValue(new Response('<html>gateway error</html>', { status: 502 }));
    await expect(new ApiClient(fetcher).me()).rejects.toMatchObject({ code: 'unavailable' });
  });
});
