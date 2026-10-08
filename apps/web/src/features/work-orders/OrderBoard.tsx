import { useLocale } from '../../ui/locale';
import { useCallback, useState } from 'react';
import { Link } from 'react-router';
import { ApiClient } from '../../lib/api';
import { displayTime } from '../../lib/time';
import { useQuery } from '../../lib/useQuery';
import { PriorityChip } from '../../ui/components';
import { priorities, statuses, type Equipment, type Named, type ShiftMember, type WorkOrder, type WorkOrderList } from './data';

type Props = { api: ApiClient; catalogs: { areas: Named[]; equipment: Equipment[]; brigades: Named[] }; members: ShiftMember[]; timezone: string;
  query: URLSearchParams; filter: (name: string, value: string) => void; setQuery: (query: URLSearchParams) => void };

export function OrderBoard({ api, catalogs, members, timezone, query, filter, setQuery }: Props) {
  const { tx, errorText } = useLocale();
  const raw = Number(query.get('offset') ?? 0);
  const offset = Number.isSafeInteger(raw) && raw >= 0 ? Math.floor(raw / 50) * 50 : 0;
  const [column, setColumn] = useState<WorkOrder['status']>('ISSUED');
  const area = query.get('area_id') ?? '', equipment = query.get('equipment_id') ?? '', assignee = query.get('assignee_id') ?? '', priority = query.get('priority') ?? '', status = query.get('status') ?? '';
  const orders = useQuery(useCallback((signal: AbortSignal) => api.request<WorkOrderList>('/api/v1/work-orders', {
    query: { area_id: area, equipment_id: equipment, assignee_id: assignee, priority, status, offset, limit: 50 }, signal,
  }), [api, area, equipment, assignee, priority, status, offset]));
  const names = new Map(members.map(member => [member.user.id, member.user.display_name]));
  const equipmentNames = new Map(catalogs.equipment.map(item => [item.id, item.name]));
  const areaNames = new Map(catalogs.areas.map(item => [item.id, item.name]));
  function page(nextOffset: number) { const next = new URLSearchParams(query); next.set('offset', String(nextOffset)); setQuery(next); }
  return <section aria-label={tx("Наряды смены")}>
    <h3>{tx("Наряды")}</h3>
    <div className="filters">
      <label>{tx("Оборудование")}<select value={equipment} onChange={event => filter('equipment_id', event.target.value)}><option value="">{tx("Все")}</option>{catalogs.equipment.filter(item => !area || item.area_id === area).map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
      <label>{tx("Исполнитель")}<select value={assignee} onChange={event => filter('assignee_id', event.target.value)}><option value="">{tx("Все")}</option>{members.filter(member => member.user.role === 'worker').map(member => <option key={member.user.id} value={member.user.id}>{member.user.display_name}</option>)}</select></label>
      <label>{tx("Приоритет")}<select value={priority} onChange={event => filter('priority', event.target.value)}><option value="">{tx("Все")}</option>{Object.entries(priorities).map(([value, label]) => <option key={value} value={value}>{tx(label)}</option>)}</select></label>
      <label>{tx("Статус")}<select value={status} onChange={event => filter('status', event.target.value)}><option value="">{tx("Все")}</option>{Object.entries(statuses).map(([value, label]) => <option key={value} value={value}>{tx(label)}</option>)}</select></label>
    </div>
    {orders.error && <p role="alert">{errorText(orders.error)} <button onClick={orders.reload}>{tx("Обновить наряды")}</button></p>}
    {orders.loading && <p role="status">{tx("Загружаем наряды…")}</p>}
    <label className="mobile-column">{tx("Колонка")}<select value={status || column} onChange={event => setColumn(event.target.value as WorkOrder['status'])} disabled={!!status}>{Object.entries(statuses).map(([value, label]) => <option key={value} value={value}>{tx(label)} ({orders.data?.items.filter(order => order.status === value).length ?? 0})</option>)}</select></label>
    <div className="order-board">{Object.entries(statuses).filter(([value]) => !status || value === status).map(([value, label]) => <section className={`order-column ${(status || column) === value ? 'is-selected' : ''}`} key={value} aria-label={tx(label)}>
      <h4>{tx(label)} <span className="muted">{orders.data?.items.filter(order => order.status === value).length ?? 0}</span></h4>
      {orders.data?.items.filter(order => order.status === value).map(order => <Link className={`order-card ${order.is_overdue ? 'overdue' : ''}`} to={`/orders/${order.id}`} key={order.id}>
        <strong>{order.number}</strong><PriorityChip priority={order.priority} />
        <span className="order-description">{order.description}</span><span>{areaNames.get(order.area_id)} · {equipmentNames.get(order.equipment_id)}</span>
        <span>{names.get(order.assignee_id ?? order.responsible_id ?? '') ?? tx("Назначенный исполнитель")}{order.brigade_id ? tx(" · бригада") : ''}</span>
        <span>{tx("До ")}{displayTime(order.due_at, timezone)}{order.is_overdue ? tx(" · Просрочен") : ''}</span>
        {order.queue_position != null && <span>{tx("Позиция в очереди: ")}{order.queue_position}</span>}
      </Link>)}
      {!orders.data?.items.some(order => order.status === value) && <p className="muted">{tx("На этой странице нет нарядов.")}</p>}
    </section>)}</div>
    {orders.data && <nav className="pagination" aria-label={tx("Страницы нарядов")}>
      <button disabled={offset === 0} onClick={() => page(Math.max(0, offset - 50))}>{tx("Назад")}</button>
      <span>{orders.data.items.length ? `${offset + 1}–${offset + orders.data.items.length}` : '0'}{tx(" из ")}{orders.data.total}</span>
      <button disabled={offset + 50 >= orders.data.total} onClick={() => page(offset + 50)}>{tx("Далее")}</button>
    </nav>}
  </section>;
}
