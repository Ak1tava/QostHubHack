import { useLocale } from '../../ui/locale';
import { useCallback, useEffect, useRef, useState } from 'react';
import type { components } from '../../../../../packages/contracts/api.generated';
import { ApiClient, ApiError } from '../../lib/api';
import { useQuery } from '../../lib/useQuery';

type LinkStatus = components['schemas']['LinkStatus'];
type LinkToken = components['schemas']['LinkTokenResponse'];

export function telegramError(error: unknown): string {
  if (error instanceof ApiError && error.code === 'telegram_not_configured') return 'Telegram пока не настроен. Обратитесь к мастеру.';
  if (error instanceof ApiError && error.status === 429) return 'Слишком частые попытки. Повторите позже.';
  if (error instanceof ApiError && error.status === 401) return 'Войдите в приложение повторно.';
  if (error instanceof ApiError && error.status === 403) return 'Действие недоступно. Обновите страницу.';
  return 'Не удалось проверить Telegram. Проверьте соединение и повторите попытку.';
}

export function TelegramPage({ api }: { api: ApiClient }) {
  const { tx } = useLocale();
  const status = useQuery(useCallback((signal: AbortSignal) => api.request<LinkStatus>('/api/v1/telegram/status', { signal }), [api]), 'refresh');
  const [link, setLink] = useState<LinkToken | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const running = useRef(false);
  useEffect(() => { if (status.data?.linked) setLink(null); }, [status.data?.linked]);
  useEffect(() => {
    if (!link) return;
    const remaining = Date.parse(link.expires_at) - Date.now();
    if (!Number.isFinite(remaining) || remaining <= 0) { setLink(null); return; }
    const timer = setTimeout(() => setLink(null), remaining);
    return () => clearTimeout(timer);
  }, [link]);
  async function change(action: 'link-token' | 'unlink') {
    if (running.current) return;
    running.current = true; setBusy(true); setError('');
    try {
      if (action === 'link-token') {
        const issued = await api.request<LinkToken>('/api/v1/telegram/link-token', { method: 'POST' });
        const url = new URL(issued.url);
        if (url.protocol !== 'https:' || url.hostname !== 't.me') throw new Error('Invalid Telegram URL');
        setLink(issued);
      } else {
        await api.request<LinkStatus>('/api/v1/telegram/unlink', { method: 'POST' });
        setLink(null); status.reload();
      }
    } catch (failure) { setError(telegramError(failure)); }
    finally { running.current = false; setBusy(false); }
  }
  return <section className="page form-page">
    <h2>Telegram</h2><p>{tx("Уведомления приходят в Telegram. Принятие и закрытие наряда выполняются в приложении.")}</p>
    {status.loading && <p role="status">{tx("Проверяем привязку…")}</p>}
    {status.data && <p role="status">{status.data.linked ? tx("Привязан") : tx("Не привязан")}</p>}
    {(error || status.error) && <p role="alert">{error || telegramError(status.error)}</p>}
    <div className="choices">
      {status.data && <button type="button" disabled={busy} onClick={() => void change(status.data!.linked ? 'unlink' : 'link-token')}>{status.data.linked ? tx("Отвязать Telegram") : link ? tx("Получить новую ссылку") : tx("Привязать Telegram")}</button>}
      <button type="button" disabled={busy || status.loading} onClick={status.reload}>{tx("Проверить привязку")}</button>
    </div>
    {link && !status.data?.linked && <p><a className="button primary" href={link.url} target="_blank" rel="noreferrer">{tx("Открыть бота")}</a>{tx(" Нажмите «Запустить» в Telegram, затем проверьте привязку здесь. Ссылка одноразовая, действует 10 минут.")}</p>}
  </section>;
}
