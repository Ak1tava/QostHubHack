import { displayFixtureName, displayOrderNumber, displayOrderDescription } from '../../lib/displayFixture';
import { useLocale } from '../../ui/locale';
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
  const { tx, errorText } = useLocale();
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
    <Link to="/shift">{tx("← Панель смены")}</Link>
    {detail.loading && <p role="status">{tx("Загружаем наряд…")}</p>}
    {detail.error && <p role="alert">{errorText(detail.error)} <button onClick={detail.reload}>{tx("Обновить")}</button></p>}
    {order && <>
      <div className="page-heading"><h2>{tx("Наряд ")}{displayOrderNumber(order.number)}</h2><span className={`badge priority-${order.priority}`}>{tx(priorities[order.priority])}</span></div>
      <p className="badge">{tx(statuses[order.status])}{order.is_overdue ? tx(" · Просрочен") : ''}</p>
      <ReviewPanel order={order} />
      <MasterDecisionForm key={`${order.id}:${user.id}`} api={api} user={user} order={order} reload={detail.reload} onDecided={() => { detail.reload(); events.invalidate(); }} />
      {order.template_snapshot && <TemplateRequirements template={order.template_snapshot} />}
      <p id={`problem-${order.id}`} className="full-description">{displayOrderDescription(order.description)}</p>
      <dl className="order-info">
        <dt>{tx("Участок")}</dt><dd>{displayFixtureName(catalogs.data?.areas.find(area => area.id === order.area_id)?.name ?? tx("Загружаем…"))}</dd>
        <dt>{tx("Оборудование")}</dt><dd><Link to={`/equipment/${order.equipment_id}`}>{displayFixtureName(catalogs.data?.equipment.find(item => item.id === order.equipment_id)?.name ?? tx("Карточка оборудования"))}</Link></dd>
        <dt>{tx("Исполнитель")}</dt><dd>{displayFixtureName(shift.data?.items.find(member => member.user.id === (order.assignee_id ?? order.responsible_id))?.user.display_name ?? tx("Назначенный исполнитель"))}{order.brigade_id ? (" · " + displayFixtureName(catalogs.data?.brigades.find(brigade => brigade.id === order.brigade_id)?.name ?? tx('бригада'))) : ''}</dd>
        <dt>{tx("Тип")}</dt><dd>{order.work_type === 'emergency' ? tx("Аварийный") : tx("Плановый")}</dd>
        <dt>{tx("Срок")}</dt><dd>{displayTime(order.due_at, timezone)} ({timezone})</dd>
        <dt>{tx("Выдан")}</dt><dd>{displayTime(order.created_at, timezone)}</dd>
        {order.queue_position != null && <><dt>{tx("Очередь")}</dt><dd>{tx("Позиция ")}{order.queue_position}</dd></>}
      </dl>
      {user.role === 'master' && <div className="choices" aria-label={tx("Действия мастера")}>{(Object.keys(actionNames) as MasterAction[]).filter(name => order.allowed_actions?.includes(name)).map(name => <button key={name} disabled={command.pending || command.busy} onClick={() => chooseAction(name)}>{tx(actionNames[name])}</button>)}</div>}
      {action && <form className="action-form" onSubmit={submit}>
        <h3>{tx(actionNames[action])}</h3>
        <fieldset disabled={command.pending || command.busy || !allowed} className="form-fields">
          {action === 'reprioritize' ? <label>{tx("Приоритет")}<select name="priority" value={priority} onChange={event => setPriority(event.target.value as typeof priority)}>{Object.entries(priorities).map(([value, label]) => <option key={value} value={value}>{tx(label)}</option>)}</select></label> : <label>{tx("Причина")}<textarea name="reason" value={reason} onChange={event => setReason(event.target.value)} maxLength={4000} required rows={2} /></label>}
          {action === 'reassign' && <>
            <label>{tx("Назначить")}<select value={mode} onChange={event => { setMode(event.target.value as typeof mode); setResponsible(''); }}><option value="worker">{tx("Исполнителю")}</option><option value="brigade">{tx("Бригаде")}</option></select></label>
            {mode === 'worker' ? <label>{tx("Исполнитель")}<select value={assignee} onChange={event => setAssignee(event.target.value)} required><option value="">{tx("Выберите")}</option>{workers.map(member => <option key={member.user.id} value={member.user.id}>{displayFixtureName(member.user.display_name)} · {tx(availability[member.availability])}</option>)}</select></label> : <>
              <label>{tx("Бригада")}<select value={brigade} onChange={event => { setBrigade(event.target.value); setResponsible(''); }} required><option value="">{tx("Выберите")}</option>{catalogs.data?.brigades.filter(brigade => workers.some(member => member.user.brigade_id === brigade.id)).map(brigade => <option key={brigade.id} value={brigade.id}>{displayFixtureName(brigade.name)}</option>)}</select></label>
              <label>{tx("Ответственный")}<select value={responsible} onChange={event => setResponsible(event.target.value)} required><option value="">{tx("Выберите")}</option>{workers.filter(member => member.user.brigade_id === brigade).map(member => <option key={member.user.id} value={member.user.id}>{displayFixtureName(member.user.display_name)}</option>)}</select></label>
            </>}
            {selected && <p role="status">{tx(availability[selected.availability])}{tx(" · в очереди: ")}{selected.queue_count}</p>}
            {shift.error && <p role="alert">{errorText(shift.error)}</p>}
          </>}
        </fieldset>
        {command.error && <p role="alert">{errorText(command.error)}{command.error instanceof ApiError && command.error.status === 409 ? tx(". Данные обновлены; проверьте действие и отправьте снова.") : ''}</p>}
        {command.pending && <p role="status">{tx("Результат неизвестен. Повтор подтвердит ту же команду.")}</p>}
        <button className="primary" type="submit" disabled={command.busy || (!command.pending && !valid)}>{command.busy ? tx("Сохраняем…") : command.pending ? tx("Повторить действие") : tx("Применить")}</button>
        {!command.pending && <button type="button" disabled={command.busy} onClick={() => setAction(null)}>{tx("Вернуться")}</button>}
      </form>}
      <section aria-label={tx("История наряда")}><h3>{tx("История")}</h3><ol className="history">{order.events?.map(event => <li key={event.id}>
        <strong>{Object.hasOwn(historyNames, event.action) ? tx(historyNames[event.action]) : event.action}</strong><time dateTime={event.occurred_at}>{displayTime(event.occurred_at, timezone)}</time>
        <span>{event.actor_id ? displayFixtureName(shift.data?.items.find(member => member.user.id === event.actor_id)?.user.display_name ?? tx("Сотрудник")) : tx("Система")}</span>
        {event.reason && <p>{event.reason}</p>}
      </li>)}</ol></section>
      {order.submission && <div id={`submission-${order.submission.id}`}><SavedSubmission api={api} submission={order.submission} template={order.template_snapshot} /></div>}
      <IssuancePhotos photos={order.issuance_photos} />
      <NotificationDeliveryPanel api={api} user={user} orderId={order.id} />
    </>}
  </section>;
}
