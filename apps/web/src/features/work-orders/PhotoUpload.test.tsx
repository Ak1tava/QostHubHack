import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, it, vi } from 'vitest';
import { ApiClient } from '../../lib/api';
import { PhotoUpload } from './PhotoUpload';

vi.mock('../../lib/compressPhoto', () => ({ compressPhoto: async () => new File(['jpeg'], 'photo.jpg', { type: 'image/jpeg' }) }));
it('replaces the local preview with the protected uploaded photo without dereferencing a cleared file', async () => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  vi.stubGlobal('URL', class extends URL { static createObjectURL() { return 'blob:test'; } static revokeObjectURL() {} });
  const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
  const requests: RequestInit[] = [];
  const api = new ApiClient(async (input, init) => {
    if (String(input).endsWith('/csrf')) return json({ csrf_token: 'csrf' });
    requests.push(init!); return json({ id: 'photo', type: 'after', work_order_id: 'order', received_at: new Date().toISOString(), read_url: '/api/v1/photos/photo' }, 201);
  });
  const uploaded = vi.fn(); const container = document.createElement('div'); document.body.append(container); const root = createRoot(container);
  try {
    await act(async () => root.render(<PhotoUpload api={api} orderId="order" type="after" disabled={false} onUploaded={uploaded} />));
    const input = container.querySelector<HTMLInputElement>('input[type="file"]')!;
    Object.defineProperty(input, 'files', { value: [new File(['raw'], 'camera.png', { type: 'image/png' })] });
    await act(async () => input.dispatchEvent(new Event('change', { bubbles: true })));
    expect(container.querySelector('img')!.getAttribute('src')).toBe('blob:test');
    await act(async () => container.querySelector<HTMLButtonElement>('button')!.click());
    expect(container.querySelector('img')!.getAttribute('src')).toBe('/api/v1/photos/photo'); expect(uploaded).toHaveBeenCalledOnce();
    expect(requests[0].body).toBeInstanceOf(FormData);
    expect(new Headers(requests[0].headers).get('Content-Type')).toBeNull(); expect(new Headers(requests[0].headers).get('X-CSRF-Token')).toBe('csrf');
    expect((requests[0].body as FormData).get('type')).toBe('after');
  } finally { await act(async () => root.unmount()); container.remove(); vi.unstubAllGlobals(); }
});
