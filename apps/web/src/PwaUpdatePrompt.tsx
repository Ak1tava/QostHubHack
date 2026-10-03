import { useState } from 'react';
import { useRegisterSW } from 'virtual:pwa-register/react';

export function PwaUpdatePrompt() {
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
      <p>Доступна новая версия приложения.</p>
      {failed && <p role="alert">Не удалось обновить. Проверьте соединение и повторите попытку.</p>}
      <button disabled={updating} onClick={() => void confirmUpdate()}>Обновить приложение</button>
      <button disabled={updating} onClick={() => setNeedRefresh(false)}>Позже</button>
    </aside>
  );
}
