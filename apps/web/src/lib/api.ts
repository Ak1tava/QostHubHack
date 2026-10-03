import type { components, paths } from '../../../../packages/contracts/api.generated';

export type UserView = components['schemas']['UserView'];
export type LoginRequest = components['schemas']['LoginRequest'];
type AuthResponse = components['schemas']['AuthResponse'];
type ErrorResponse = components['schemas']['ErrorResponse'];
type Details = ErrorResponse['error']['details'];

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
    public readonly details: Details = [],
    public readonly retryAfter: number | null = null,
  ) { super(message); }
}

const unavailable = () => new ApiError(0, 'unavailable', 'Сервер недоступен. Проверьте соединение и повторите попытку.');

export class ApiClient {
  private csrfToken: string | null = null;
  private generation = 0;

  constructor(
    private readonly fetcher: typeof fetch = (...args) => fetch(...args),
    private readonly onUnauthenticated: () => void = () => {},
  ) {}

  private clear() {
    this.csrfToken = null;
    this.generation++;
  }

  async request<T>(path: keyof paths, options: RequestInit = {}): Promise<T> {
    const method = (options.method ?? 'GET').toUpperCase();
    const headers = new Headers(options.headers);
    headers.set('Accept', 'application/json');
    if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
      headers.set('X-CSRF-Token', await this.csrf());
    }
    let response: Response;
    try {
      response = await this.fetcher(path, { ...options, method, headers, credentials: 'same-origin', cache: 'no-store' });
    } catch { throw unavailable(); }
    if (response.status === 401) {
      this.clear();
      this.onUnauthenticated();
    }
    if (response.ok && response.status === 204) return undefined as T;
    if (!response.headers.get('Content-Type')?.includes('application/json')) throw unavailable();
    let body: T & Partial<ErrorResponse>;
    try { body = await response.json(); } catch { throw unavailable(); }
    if (!response.ok) {
      const error = body?.error;
      if (error?.code === 'csrf_failed') this.clear();
      const retry = response.headers.get('Retry-After');
      throw new ApiError(
        response.status, error?.code ?? 'request_failed', error?.message ?? 'Ошибка запроса. Повторите попытку.',
        error?.details ?? [], retry && /^\d+$/.test(retry) ? Number(retry) : null,
      );
    }
    return body;
  }

  private async csrf(): Promise<string> {
    if (!this.csrfToken) {
      const generation = this.generation;
      const response = await this.request<components['schemas']['CsrfResponse']>('/api/v1/auth/csrf');
      if (generation !== this.generation) throw new ApiError(401, 'unauthenticated', 'Сессия истекла. Войдите снова.');
      this.csrfToken = response.csrf_token;
    }
    return this.csrfToken;
  }

  async login(payload: LoginRequest): Promise<AuthResponse> {
    const response = await this.request<AuthResponse>('/api/v1/auth/login', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
    });
    this.csrfToken = response.csrf_token;
    return response;
  }

  async me(): Promise<AuthResponse> {
    const generation = this.generation;
    const response = await this.request<AuthResponse>('/api/v1/auth/me');
    if (generation !== this.generation) throw new ApiError(401, 'unauthenticated', 'Сессия истекла. Войдите снова.');
    this.csrfToken = response.csrf_token;
    return response;
  }

  async logout(): Promise<void> {
    if (!this.csrfToken) await this.me();
    await this.request<void>('/api/v1/auth/logout', { method: 'POST' });
    this.clear();
  }
}
