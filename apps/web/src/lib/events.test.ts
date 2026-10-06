import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { EventStream } from './events';

class FakeSocket {
  readyState = 0;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;
  onerror: (() => void) | null = null;
  close = vi.fn(() => { this.readyState = 3; });
}
let stream: EventStream, sockets: FakeSocket[], create: (url: string) => WebSocket;
beforeEach(() => {
  vi.useFakeTimers(); vi.spyOn(document, 'hidden', 'get').mockReturnValue(false);
  sockets = []; create = vi.fn(() => { const ws = new FakeSocket(); sockets.push(ws); return ws as unknown as WebSocket; });
  stream = new EventStream(create);
});
afterEach(() => { stream.stop(); vi.useRealTimers(); });

it('refreshes on open, a valid event and fallback, then removes timers and callbacks on stop', () => {
  const refresh = vi.fn(); stream.subscribe(refresh); stream.start();
  sockets[0].readyState = 1; sockets[0].onopen!();
  const count = refresh.mock.calls.length;
  sockets[0].onmessage!({ data: JSON.stringify({ event_id: 'event', type: 'work_order.create', work_order_id: 'order', version: 1, occurred_at: '2026-10-04T12:00:00Z' }) });
  expect(refresh.mock.calls.length).toBeGreaterThan(count);
  vi.advanceTimersByTime(3000); expect(refresh.mock.calls.length).toBeGreaterThan(count + 1);
  stream.stop(); const stopped = refresh.mock.calls.length;
  vi.advanceTimersByTime(30000); expect(refresh).toHaveBeenCalledTimes(stopped);
  expect(sockets[0].close).toHaveBeenCalled(); expect(create).toHaveBeenCalledTimes(1);
});

it('reconnects and refreshes while rejecting malformed events', () => {
  const refresh = vi.fn(); stream.subscribe(refresh); stream.start();
  sockets[0].onmessage!({ data: 'not json' }); sockets[0].onmessage!({ data: JSON.stringify({ type: 'untrusted' }) });
  expect(refresh).not.toHaveBeenCalled();
  sockets[0].readyState = 3; sockets[0].onclose!({ code: 1006 });
  vi.advanceTimersByTime(1000); expect(create).toHaveBeenCalledTimes(2);
  sockets[1].readyState = 1; sockets[1].onopen!(); expect(refresh).toHaveBeenCalled();
});

it('checks authentication when the server revokes the socket', () => {
  const policy = vi.fn(); stream.start(policy); sockets[0].onclose!({ code: 1008 });
  expect(policy).toHaveBeenCalledOnce();
});

it('refreshes catalogs on reconnect and focus without polling them on every order change', () => {
  const catalogs = vi.fn(); stream.subscribe(catalogs, true); stream.start();
  sockets[0].readyState = 1; sockets[0].onopen!(); expect(catalogs).toHaveBeenCalledTimes(1);
  sockets[0].onmessage!({ data: JSON.stringify({ event_id: 'event', type: 'work_order.create', work_order_id: 'order', version: 1, occurred_at: '2026-10-04T12:00:00Z' }) });
  vi.advanceTimersByTime(3000); expect(catalogs).toHaveBeenCalledTimes(1);
  window.dispatchEvent(new Event('focus')); expect(catalogs).toHaveBeenCalledTimes(2);
});
