import { useCallback } from 'react';
import type { components } from '../../../../../packages/contracts/api.generated';
import type { ApiClient, UserView } from '../../lib/api';
import { useQuery } from '../../lib/useQuery';
import { telegramError } from './TelegramPage';

type Delivery = components['schemas']['DeliveryStatus'];
const statuses: Record<string, string> = { PENDING: 'Ожидает отправки', LEASED: 'Отправляется', RETRY: 'Повторная попытка', BLOCKED: 'Доставка заблокирована', SENT: 'Отправлено', FAILED: 'Не доставлено', CANCELLED: 'Уведомление отменено' };
const kinds: Record<string, string> = { new: 'Новый наряд', reminder: 'Напоминание о сроке', unaccepted: 'Наряд не принят', overdue: 'Просрочка', emergency_queued: 'Аварийный наряд в очереди' };

export function NotificationDeliveryPanel({ api, user, orderId }: { api: ApiClient; user: UserView; orderId: string }) {
  const deliveries = useQuery(useCallback((signal: AbortSignal) => api.request<Delivery[]>('/api/v1/work-orders/{order_id}/notifications', { params: { order_id: orderId }, signal }), [api, orderId]), 'refresh');
  const rows = deliveries.data?.filter(row => user.role !== 'worker' || row.recipient_id === user.id);
  return <section aria-label="Доставка Telegram"><h3>Доставка Telegram</h3>
    {deliveries.loading && <p role="status">Проверяем доставку…</p>}
    {deliveries.error && <p role="alert">{telegramError(deliveries.error)}</p>}
    {rows?.length === 0 && <p>Уведомлений пока нет.</p>}
    {rows?.map(row => <p key={row.id}>{kinds[row.kind] ?? 'Уведомление'}: <strong>{statuses[row.status] ?? 'Статус недоступен'}</strong> · попыток: {row.attempts}{row.status === 'BLOCKED' && ' · Проверьте привязку Telegram.'}</p>)}
    <button type="button" disabled={deliveries.loading} onClick={deliveries.reload}>Обновить доставку</button>
  </section>;
}
