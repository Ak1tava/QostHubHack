import { ApiClient, ApiError, type LoginRequest, type UserView } from '../../lib/api';

type AuthState = { user: UserView | null; loading: boolean; busy: boolean; error: ApiError | null };

export class AuthStore {
  private state: AuthState = { user: null, loading: true, busy: false, error: null };
  private listeners = new Set<() => void>();
  private restoring: Promise<void> | null = null;
  private revision = 0;
  readonly api: ApiClient;

  constructor(fetcher?: typeof fetch) {
    this.api = new ApiClient(fetcher, () => {
      this.revision++;
      this.update({ user: null, loading: false });
    });
  }

  getSnapshot = () => this.state;
  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  };

  private update(patch: Partial<AuthState>) {
    this.state = { ...this.state, ...patch };
    this.listeners.forEach(listener => listener());
  }

  private fail(error: unknown) {
    this.update({ error: error instanceof ApiError ? error : new ApiError(0, 'unavailable', 'Сервер недоступен. Повторите попытку.') });
  }

  restore(): Promise<void> {
    if (this.restoring) return this.restoring;
    const revision = ++this.revision;
    this.restoring = (async () => {
      try {
        const response = await this.api.me();
        if (revision === this.revision) this.update({ user: response.user, error: null });
      } catch (error) {
        if (!(error instanceof ApiError && error.status === 401)) this.fail(error);
      } finally {
        this.update({ loading: false });
        this.restoring = null;
      }
    })();
    return this.restoring;
  }

  async login(payload: LoginRequest) {
    if (this.state.busy) return;
    const revision = ++this.revision;
    this.update({ busy: true, error: null });
    try {
      const response = await this.api.login(payload);
      if (revision === this.revision) this.update({ user: response.user });
    } catch (error) { this.fail(error); }
    finally { this.update({ busy: false, loading: false }); }
  }

  async logout() {
    if (this.state.busy) return;
    this.revision++;
    this.update({ busy: true, error: null });
    try {
      await this.api.logout();
      this.update({ user: null });
    } catch (error) { this.fail(error); }
    finally { this.update({ busy: false }); }
  }
}

export const authStore = new AuthStore();
