import { useLocale } from '../../ui/locale';
import { useEffect, useState, type FormEvent } from 'react';
import { ApiError, type LoginRequest } from '../../lib/api';

type Props = { busy: boolean; error: ApiError | null; onLogin: (payload: LoginRequest) => Promise<void> };

export function LoginPage({ busy, error, onLogin }: Props) {
  const { tx, errorText } = useLocale();
  const [login, setLogin] = useState('');
  const [password, setPassword] = useState('');
  const [retryIn, setRetryIn] = useState(0);
  useEffect(() => {
    const seconds = error?.retryAfter ?? 0;
    setRetryIn(seconds);
    if (!seconds) return;
    const deadline = Date.now() + seconds * 1000;
    const timer = window.setInterval(() => setRetryIn(Math.max(0, Math.ceil((deadline - Date.now()) / 1000))), 1000);
    return () => window.clearInterval(timer);
  }, [error]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || retryIn) return;
    await onLogin({ login: login.trim(), password });
    setPassword('');
  }

  return <section className="auth-card" aria-labelledby="login-title">
    <h2 id="login-title">{tx("Вход")}</h2>
    <p>{tx("Введите логин и пароль или ПИН.")}</p>
    <form onSubmit={submit}>
      <label htmlFor="login">{tx("Логин")}</label>
      <input id="login" name="login" autoComplete="username" autoCapitalize="none" value={login} onChange={event => setLogin(event.target.value)} required maxLength={128} disabled={busy} />
      <label htmlFor="password">{tx("Пароль или ПИН")}</label>
      <input id="password" name="password" type="password" autoComplete="current-password" value={password} onChange={event => setPassword(event.target.value)} required maxLength={128} disabled={busy} />
      {error && <div role="alert">
        <p>{errorText(error)}</p>
        {error.details?.map((detail, index) => <p key={`${detail.field}-${index}`}>{detail.field}: {detail.message}</p>)}
        {retryIn > 0 && <p>{tx("Повторите через ")}{retryIn}{tx(" с.")}</p>}
      </div>}
      <button type="submit" disabled={busy || retryIn > 0}>{busy ? tx("Входим…") : tx("Войти")}</button>
    </form>
  </section>;
}
