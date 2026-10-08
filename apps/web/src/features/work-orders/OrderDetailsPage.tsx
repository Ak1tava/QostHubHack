import { TemplateRequirements } from './TemplateRequirements';
import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { Link } from 'react-router';
import { ApiClient, ApiError, type UserView } from '../../lib/api';
import { useQuery } from '../../lib/useQuery';
import { useCommand } from '../../lib/useCommand';
import { displayTime } from '../../lib/time';
import { events } from '../../lib/events';
import { availability, orderAction, priorities, statuses, useCatalogs, useShift, type OrderAction, type WorkOrderDetail } from './data';
import { SavedSubmission } from './SavedSubmission';
import { ReviewPanel } from './ReviewPanel';
import { MasterDecisionForm } from './MasterDecisionForm';
import { IssuancePhotos } from './IssuancePhotos';
import { NotificationDeliveryPanel } from '../telegram/NotificationDeliveryPanel';

type MasterAction = 'reassign' | 'cancel' | 'reprioritize';
const actionNames: Record<MasterAction, string> = { reassign: 'Переназначить', cancel: 'Отменить', reprioritize: 'Изменить приоритет' };
const historyNames: Record<string, string> = { create: 'Выдача', accept: 'Принятие', queue: 'Очередь', reject: 'Отказ', reassign: 'Переназначение', start: 'Начало работы', pause: 'Пауза', resume: 'Продолжение', restart: 'Доработка', submit: 'Отправка на приёмку', begin_review: 'Проверка', request_rework: 'Возврат на доработку', close: 'Закрытие', override_close: 'Решение мастера', cancel: 'Отмена', reprioritize: 'Изменение приоритета' };

export function OrderDetailsPage({ api, user, orderId }: { api: ApiClient; user: UserView; orderId: string }) {
  const detail = useQuery(useCallback((signal: AbortSignal) => api.request<WorkOrderDetail>('/api/v1/work-orders/{order_id}', { params: { order_id: orderId }, signal }), [api, orderId]));
  const catalogs = useCatalogs(api);
  const shift = useShift(api, detail.data?.area_id ?? '');
  const [action, setAction] = useState<MasterAction | null>(null);
  const [reason, setReason] = useState('');
  const [priority, setPriority] = useState<NonNullable<OrderAction['priority']>>('normal');
  const [mode, setMode] = useState<'worker' | 'brigade'>('worker');
  const [assignee, setAssignee] = useState('');
  const [brigade, setBrigade] = useState('');
  const [responsible, setResponsible] = useState('');
  const command = useCommand(useCallback((body: OrderAction, key: string) => orderAction(api, orderId, body, key), [api, orderId]));
  useEffect(() => {
    if (command.error instanceof ApiError && command.error.status === 409) { detail.reload(); shift.reload(); }
  }, [command.error, detail.reload, shift.reload]);
  const order = detail.data;
  const timezone = shift.data?.timezone ?? 'Asia/Qostanay';
  const workers = shift.data?.items.filter(member => member.user.role === 'worker') ?? [];
  const selected = workers.find(member => member.user.id === (mode === 'worker' ? assignee : responsible));
  const assignment = mode === 'worker' ? workers.some(member => member.user.id === assignee) : workers.some(member => member.user.id === responsible && member.user.brigade_id === brigade);
  const allowed = !!(order && action && user.role === 'master' && order.allowed_actions?.includes(action));
  const valid = allowed && (action === 'reprioritize' ? !!priority : !!reason.trim() && (action === 'cancel' || assignment));
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!order || !action) return;
    let body: OrderAction | undefined;
    if (!command.pending) {
      if (!valid) return;
      body = { action, expected_version: order.version };
      if (action === 'reprioritize') body.priority = priority;
      else body.reason = reason.trim();
      if (action === 'reassign') Object.assign(body, { assignee_id: mode === 'worker' ? assignee : null, brigade_id: mode === 'brigade' ? brigade : null, responsible_id: mode === 'brigade' ? responsible : null });
    }
    const changed = await command.run(body);
    if (changed) { setAction(null); setReason(''); detail.reload(); events.invalidate(); }
  }
  function chooseAction(next: MasterAction) {
    setAction(next); setReason(''); setPriority(order?.priority ?? 'normal'); setAssignee(''); setBrigade(''); setResponsible('');
  }

  return <section className="page details-page">
    <Link to="/shift">← Панель смены</Link>
    {detail.loading && <p role="status">Загружаем наряд…</p>}
    {detail.error && <p role="alert">{detail.error.message} <button onClick={detail.reload}>Обновить</button></p>}
    {order && <>
      <div className="page-heading"><h2>Наряд {order.number}</h2><span className={`badge priority-${order.priority}`}>{priorities[order.priority]}</span></div>
      <p className="badge">{statuses[order.status]}{order.is_overdue ? ' · Просрочен' : ''}</p>
      {order.template_snapshot && <TemplateRequirements template={order.template_snapshot} />}
      <p id={`problem-${order.id}`} className="full-description">{order.description}</p>
      <dl className="order-info">
        <dt>Участок</dt><dd>{catalogs.data?.areas.find(area => area.id === order.area_id)?.name ?? 'Загружаем…'}</dd>
        <dt>Оборудование</dt><dd><Link to={`/equipment/${order.equipment_id}`}>{catalogs.data?.equipment.find(item => item.id === order.equipment_id)?.name ?? 'Карточка оборудования'}</Link></dd>
        <dt>Исполнитель</dt><dd>{shift.data?.items.find(member => member.user.id === (order.assignee_id ?? order.responsible_id))?.user.display_name ?? 'Назначенный исполнитель'}{order.brigade_id ? ` · ${catalogs.data?.brigades.find(brigade => brigade.id === order.brigade_id)?.name ?? 'бригада'}` : ''}</dd>
        <dt>Тип</dt><dd>{order.work_type === 'emergency' ? 'Аварийный' : 'Плановый'}</dd>
        <dt>Срок</dt><dd>{displayTime(order.due_at, timezone)} ({timezone})</dd>
        <dt>Выдан</dt><dd>{displayTime(order.created_at, timezone)}</dd>
        {order.queue_position != null && <><dt>Очередь</dt><dd>Позиция {order.queue_position}</dd></>}
      </dl>
      {user.role === 'master' && <div className="choices" aria-label="Действия мастера">{(Object.keys(actionNames) as MasterAction[]).filter(name => order.allowed_actions?.includes(name)).map(name => <button key={name} disabled={command.pending || command.busy} onClick={() => chooseAction(name)}>{actionNames[name]}</button>)}</div>}
      {action && <form className="action-form" onSubmit={submit}>
        <h3>{actionNames[action]}</h3>
        <fieldset disabled={command.pending || command.busy || !allowed} className="form-fields">
          {action === 'reprioritize' ? <label>Приоритет<select name="priority" value={priority} onChange={event => setPriority(event.target.value as typeof priority)}>{Object.entries(priorities).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label> : <label>Причина<textarea name="reason" value={reason} onChange={event => setReason(event.target.value)} maxLength={4000} required rows={2} /></label>}
          {action === 'reassign' && <>
            <label>Назначить<select value={mode} onChange={event => { setMode(event.target.value as typeof mode); setResponsible(''); }}><option value="worker">Исполнителю</option><option value="brigade">Бригаде</option></select></label>
            {mode === 'worker' ? <label>Исполнитель<select value={assignee} onChange={event => setAssignee(event.target.value)} required><option value="">Выберите</option>{workers.map(member => <option key={member.user.id} value={member.user.id}>{member.user.display_name} · {availability[member.availability]}</option>)}</select></label> : <>
              <label>Бригада<select value={brigade} onChange={event => { setBrigade(event.target.value); setResponsible(''); }} required><option value="">Выберите</option>{catalogs.data?.brigades.filter(brigade => workers.some(member => member.user.brigade_id === brigade.id)).map(brigade => <option key={brigade.id} value={brigade.id}>{brigade.name}</option>)}</select></label>
              <label>Ответственный<select value={responsible} onChange={event => setResponsible(event.target.value)} required><option value="">Выберите</option>{workers.filter(member => member.user.brigade_id === brigade).map(member => <option key={member.user.id} value={member.user.id}>{member.user.display_name}</option>)}</select></label>
            </>}
            {selected && <p role="status">{availability[selected.availability]} · в очереди: {selected.queue_count}</p>}
            {shift.error && <p role="alert">{shift.error.message}</p>}
          </>}
        </fieldset>
        {command.error && <p role="alert">{command.error.message}{command.error instanceof ApiError && command.error.status === 409 ? '. Данные обновлены; проверьте действие и отправьте снова.' : ''}</p>}
        {command.pending && <p role="status">Результат неизвестен. Повтор подтвердит ту же команду.</p>}
        <button className="primary" type="submit" disabled={command.busy || (!command.pending && !valid)}>{command.busy ? 'Сохраняем…' : command.pending ? 'Повторить действие' : 'Применить'}</button>
        {!command.pending && <button type="button" disabled={command.busy} onClick={() => setAction(null)}>Вернуться</button>}
      </form>}
      <section aria-label="История наряда"><h3>История</h3><ol className="history">{order.events?.map(event => <li key={event.id}>
        <strong>{historyNames[event.action] ?? 'Изменение'}</strong><time dateTime={event.occurred_at}>{displayTime(event.occurred_at, timezone)}</time>
        <span>{event.actor_id ? shift.data?.items.find(member => member.user.id === event.actor_id)?.user.display_name ?? 'Сотрудник' : 'Система'}</span>
        {event.reason && <p>{event.reason}</p>}
      </li>)}</ol></section>
      {order.submission && <div id={`submission-${order.submission.id}`}><SavedSubmission api={api} submission={order.submission} template={order.template_snapshot} /></div>}
      <IssuancePhotos photos={order.issuance_photos} />
      <NotificationDeliveryPanel api={api} user={user} orderId={order.id} />
      <ReviewPanel order={order} />
      <MasterDecisionForm key={`${order.id}:${user.id}`} api={api} user={user} order={order} reload={detail.reload} onDecided={() => { detail.reload(); events.invalidate(); }} />
    </>}
  </section>;
}
