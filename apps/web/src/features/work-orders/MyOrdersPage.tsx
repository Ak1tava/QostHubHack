import { useCallback } from 'react';
import { Link } from 'react-router';
import type { ApiClient, UserView } from '../../lib/api';
import { useQuery } from '../../lib/useQuery';
import { statuses, priorities, type WorkOrder, type WorkOrderList } from './data';

export function MyOrdersPage({ api, user }: { api: ApiClient; user: UserView }) {
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
  if (user.role !== 'worker') return <p role="alert">Экран доступен исполнителю.</p>;
  return <section className="page details-page"><h2>Мои наряды</h2>
    {orders.loading && <p role="status">Загружаем наряды…</p>}
    {orders.error && <p role="alert">{orders.error.message} <button onClick={orders.reload}>Обновить</button></p>}
    {orders.data?.length === 0 && <p>Назначенных нарядов нет.</p>}
    {orders.data?.map(order => <Link className={`order-card ${order.is_overdue ? 'overdue' : ''}`} key={order.id} to={`/orders/${order.id}/execute`}>
      <strong>Наряд {order.number}</strong><span>{order.description}</span>
      <span className={`badge priority-${order.priority}`}>{priorities[order.priority]}</span><span>{statuses[order.status]}{order.is_overdue ? ' · Просрочен' : ''}</span>
      {order.queue_position != null && <span>Очередь: {order.queue_position}</span>}
      {order.brigade_id && <span>{order.responsible_id === user.id ? 'Ответственный бригады' : 'Наряд бригады · просмотр'}</span>}
    </Link>)}
  </section>;
}
