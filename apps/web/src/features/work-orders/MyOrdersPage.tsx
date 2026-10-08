import { useLocale } from '../../ui/locale';
import { useCallback } from 'react';
import { Link } from 'react-router';
import type { ApiClient, UserView } from '../../lib/api';
import { useQuery } from '../../lib/useQuery';
import { statuses, priorities, type WorkOrder, type WorkOrderList } from './data';

export function MyOrdersPage({ api, user }: { api: ApiClient; user: UserView }) {
  const { tx, errorText } = useLocale();
  const orders = useQuery(useCallback(async (signal: AbortSignal) => {
    const all: WorkOrder[] = [];
    let offset = 0;
    while (true) {
      // Object access is enforced by the server; omitting assignee_id preserves brigade assignments.
      const page = await api.request<WorkOrderList>('/api/v1/work-orders', { query: { offset, limit: 50 }, signal });
      all.push(...page.items); offset += page.items.length;
      if (!page.items.length || offset >= page.total) break;
    }
    return all.filter(order => order.assignee_id === user.id || order.responsible_id === user.id || (order.brigade_id && order.brigade_id === user.brigade_id))
      .sort((a, b) => (a.queue_position ?? Number.MAX_SAFE_INTEGER) - (b.queue_position ?? Number.MAX_SAFE_INTEGER));
  }, [api, user.id, user.brigade_id]));
  if (user.role !== 'worker') return <p role="alert">{tx("Экран доступен исполнителю.")}</p>;
  return <section className="page details-page"><h2>{tx("Мои наряды")}</h2>
    {orders.loading && <p role="status">{tx("Загружаем наряды…")}</p>}
    {orders.error && <p role="alert">{errorText(orders.error)} <button onClick={orders.reload}>{tx("Обновить")}</button></p>}
    {orders.data?.length === 0 && <p>{tx("Назначенных нарядов нет.")}</p>}
    {orders.data?.map(order => <Link className={`order-card ${order.is_overdue ? 'overdue' : ''}`} key={order.id} to={`/orders/${order.id}/execute`}>
      <strong>{tx("Наряд ")}{order.number}</strong><span>{order.description}</span>
      <span className={`badge priority-${order.priority}`}>{tx(priorities[order.priority])}</span><span>{tx(statuses[order.status])}{order.is_overdue ? tx(" · Просрочен") : ''}</span>
      {order.queue_position != null && <span>{tx("Очередь: ")}{order.queue_position}</span>}
      {order.brigade_id && <span>{order.responsible_id === user.id ? tx("Ответственный бригады") : tx("Наряд бригады · просмотр")}</span>}
    </Link>)}
  </section>;
}
