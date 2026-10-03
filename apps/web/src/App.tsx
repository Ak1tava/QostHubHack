import { useEffect, useSyncExternalStore } from 'react';
import { authStore } from './features/auth/session';
import { LoginPage } from './features/auth/LoginPage';
import { PwaUpdatePrompt } from './PwaUpdatePrompt';

export function App() {
  const { user, loading, busy, error } = useSyncExternalStore(authStore.subscribe, authStore.getSnapshot);
  useEffect(() => { void authStore.restore(); }, []);
  return <main>
    <h1>НарядAI</h1>
    <p>Система ремонтных нарядов</p>
    {loading ? <p role="status">Проверяем вход…</p> : user ? <section className="auth-card">
      <h2>Вы вошли</h2>
      <p>{user.display_name}</p>
      {error && <p role="alert">{error.message}</p>}
      <button onClick={() => void authStore.logout()} disabled={busy}>{busy ? 'Выходим…' : 'Выйти'}</button>
    </section> : <LoginPage busy={busy} error={error} onLogin={payload => authStore.login(payload)} />}
    <PwaUpdatePrompt />
  </main>;
}
