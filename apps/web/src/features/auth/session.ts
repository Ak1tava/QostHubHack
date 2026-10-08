import { ApiClient, ApiError, type JudgeProfile, type JudgeProfileCode, type LoginRequest, type UserView } from '../../lib/api';
import { events } from '../../lib/events';

type AuthState = { user: UserView | null; loading: boolean; busy: boolean; error: ApiError | null; judgeProfiles: JudgeProfile[]; workspaceRevision: number };

export class AuthStore {
  private state: AuthState = { user: null, loading: true, busy: false, error: null, judgeProfiles: [], workspaceRevision: 0 };
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
        if (revision === this.revision && !(error instanceof ApiError && error.status === 401)) this.fail(error);
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
      if (revision === this.revision) this.update({ user: response.user, workspaceRevision: this.state.workspaceRevision + 1 });
    } catch (error) { this.fail(error); }
    finally { this.update({ busy: false, loading: false }); }
  }

  async logout() {
    if (this.state.busy) return;
    this.revision++;
    this.update({ busy: true, error: null });
    try {
      await this.api.logout();
      events.stop();
      this.update({ user: null, workspaceRevision: this.state.workspaceRevision + 1 });
    } catch (error) { this.fail(error); }
    finally { this.update({ busy: false }); }
  }

  async loadJudgeProfiles() {
    try { this.update({ judgeProfiles: (await this.api.judgeProfiles()).profiles }); }
    catch (error) { if (!(error instanceof ApiError && error.status === 404)) this.fail(error); }
  }

  async judgeLogin(profile: JudgeProfileCode) {
    if (this.state.busy) return;
    const revision = ++this.revision;
    const wasSignedIn = !!this.state.user;
    events.stop();
    this.update({ user: null, busy: true, error: null });
    try {
      if (wasSignedIn) await this.api.logout();
      const response = await this.api.judgeLogin(profile);
      if (revision === this.revision) this.update({ user: response.user, workspaceRevision: this.state.workspaceRevision + 1 });
    } catch (error) { this.fail(error); }
    finally { this.update({ busy: false, loading: false }); }
  }
}

export const authStore = new AuthStore();
