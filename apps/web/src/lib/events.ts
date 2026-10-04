type Listener = () => void;

function validEvent(value: unknown): boolean {
  if (!value || typeof value !== 'object') return false;
  const event = value as Record<string, unknown>;
  return typeof event.event_id === 'string' && typeof event.type === 'string' && event.type.startsWith('work_order.') &&
    typeof event.work_order_id === 'string' && typeof event.version === 'number' && Number.isInteger(event.version) && event.version > 0 &&
    typeof event.occurred_at === 'string' && Number.isFinite(Date.parse(event.occurred_at));
}

export class EventStream {
  private listeners = new Map<Listener, boolean>();
  private socket: WebSocket | null = null;
  private reconnect: ReturnType<typeof setTimeout> | null = null;
  private fallback: ReturnType<typeof setInterval> | null = null;
  private active = false;
  private retry = 1000;
  private generation = 0;
  private policy: Listener = () => {};

  constructor(private createSocket: (url: string) => WebSocket = url => new WebSocket(url)) {}

  subscribe = (listener: Listener, refreshOnly = false) => { this.listeners.set(listener, refreshOnly); return () => { this.listeners.delete(listener); }; };
  invalidate = (full = false) => { if (!document.hidden) this.listeners.forEach((refreshOnly, listener) => { if (full || !refreshOnly) listener(); }); };

  start(policy: Listener = () => {}) {
    this.stop(); this.active = true; this.policy = policy;
    this.fallback = setInterval(this.invalidate, 3000);
    window.addEventListener('focus', this.resume);
    window.addEventListener('online', this.resume);
    document.addEventListener('visibilitychange', this.resume);
    this.connect();
  }

  private resume = () => {
    if (!this.active || document.hidden) return;
    this.invalidate(true);
    if (!this.socket && !this.reconnect) this.connect();
  };

  private connect() {
    if (!this.active || this.socket) return;
    const generation = this.generation;
    try {
      const url = new URL('/api/v1/events', window.location.href);
      url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
      const socket = this.createSocket(url.href);
      this.socket = socket;
      socket.onopen = () => { if (this.active && generation === this.generation) { this.retry = 1000; this.invalidate(true); } };
      socket.onmessage = event => {
        if (!this.active || generation !== this.generation) return;
        try { if (validEvent(JSON.parse(String(event.data)))) this.invalidate(); } catch { /* Ignore invalid frames. */ }
      };
      socket.onclose = event => {
        if (!this.active || generation !== this.generation) return;
        this.socket = null;
        if (event.code === 1008) this.policy();
        this.scheduleReconnect();
      };
      socket.onerror = () => { /* onclose drives retry; HTTP fallback stays active. */ };
    } catch { this.socket = null; this.scheduleReconnect(); }
  }

  private scheduleReconnect() {
    if (!this.active || this.reconnect) return;
    this.reconnect = setTimeout(() => { this.reconnect = null; this.connect(); }, this.retry);
    this.retry = Math.min(this.retry * 2, 10000);
  }

  stop() {
    this.active = false; this.generation++; this.retry = 1000;
    if (this.reconnect) clearTimeout(this.reconnect);
    if (this.fallback) clearInterval(this.fallback);
    this.reconnect = this.fallback = null;
    window.removeEventListener('focus', this.resume);
    window.removeEventListener('online', this.resume);
    document.removeEventListener('visibilitychange', this.resume);
    if (this.socket) {
      this.socket.onopen = this.socket.onmessage = this.socket.onclose = this.socket.onerror = null;
      this.socket.close(); this.socket = null;
    }
  }
}

export const events = new EventStream();
