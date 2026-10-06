import { Link } from 'react-router';
import { availability, type ShiftMember } from '../work-orders/data';

export function WorkerList({ members, areaId, canCreate }: { members: ShiftMember[]; areaId: string; canCreate: boolean }) {
  const workers = members.filter(member => member.user.role === 'worker');
  return <section aria-label="Исполнители смены">
    <h3>Исполнители <span className="muted">{workers.length}</span></h3>
    <div className="worker-grid">{workers.map(member => <article className="worker-card" key={member.user.id}>
      <strong>{member.user.display_name}</strong>
      <span className={`badge availability-${member.availability}`}>{availability[member.availability]}</span>
      <span>{member.user.specialty ?? 'Исполнитель'}{member.user.grade ? ` · ${member.user.grade} разряд` : ''}</span>
      <span>В очереди: {member.queue_count}</span>
      {member.active_work_order_id && <Link to={`/orders/${member.active_work_order_id}`}>Активный наряд</Link>}
      {canCreate && <Link className="button" to={`/orders/new?${new URLSearchParams({ assignee_id: member.user.id, ...(areaId ? { area_id: areaId } : {}) })}`}>Выдать</Link>}
    </article>)}</div>
    {!workers.length && <p className="muted">На выбранном участке нет доступных исполнителей.</p>}
  </section>;
}
