import { useLocale } from './ui/locale';
import { useState } from 'react';
import { useRegisterSW } from 'virtual:pwa-register/react';

export function PwaUpdatePrompt() {
  const { tx } = useLocale();
  const { needRefresh: [needRefresh, setNeedRefresh], updateServiceWorker } = useRegisterSW();
  const [updating, setUpdating] = useState(false);
  const [failed, setFailed] = useState(false);

  async function confirmUpdate() {
    setUpdating(true);
    setFailed(false);
    try {
      await updateServiceWorker(true);
    } catch {
      setFailed(true);
    } finally {
      setUpdating(false);
    }
  }

  if (!needRefresh) return null;

  return (
    <aside className="update-notice" role="status">
      <p>{tx("Доступна новая версия приложения.")}</p>
      {failed && <p role="alert">{tx("Не удалось обновить. Проверьте соединение и повторите попытку.")}</p>}
      <button disabled={updating} onClick={() => void confirmUpdate()}>{tx("Обновить приложение")}</button>
      <button disabled={updating} onClick={() => setNeedRefresh(false)}>{tx("Позже")}</button>
    </aside>
  );
}
