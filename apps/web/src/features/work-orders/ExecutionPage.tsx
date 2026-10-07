import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { Link } from 'react-router';
import { ApiError, type ApiClient, type UserView } from '../../lib/api';
import { useQuery } from '../../lib/useQuery';
import { useCommand } from '../../lib/useCommand';
import { events } from '../../lib/events';
import { displayTime } from '../../lib/time';
import { orderAction, priorities, statuses, useShift, type OrderAction, type WorkOrderDetail } from './data';
import { PhotoUpload } from './PhotoUpload';
import { IssuancePhotos } from './IssuancePhotos';
import { NotificationDeliveryPanel } from '../telegram/NotificationDeliveryPanel';
import { SubmissionForm } from './SubmissionForm';
import { SavedSubmission } from './SavedSubmission';
import { ReviewPanel } from './ReviewPanel';

const names = { accept: 'Принять', queue: 'В очередь', reject: 'Отказаться', start: 'Начать работу', pause: 'Приостановить', resume: 'Продолжить', restart: 'Начать доработку' };
type WorkerAction = keyof typeof names;
const photoStatuses = new Set(['ISSUED', 'ACCEPTED', 'QUEUED', 'IN_PROGRESS', 'PAUSED', 'REWORK']);

export function ExecutionPage({ api, user, orderId }: { api: ApiClient; user: UserView; orderId: string }) {
  const detail = useQuery(useCallback((signal: AbortSignal) => api.request<WorkOrderDetail>('/api/v1/work-orders/{order_id}', { params: { order_id: orderId }, signal }), [api, orderId]));
  const [action, setAction] = useState<WorkerAction | null>(null);
  const [reason, setReason] = useState('');
  const [submissionLocked, setSubmissionLocked] = useState(false);
  const command = useCommand(useCallback((body: OrderAction, key: string) => orderAction(api, orderId, body, key), [api, orderId]));
  useEffect(() => { if (command.error instanceof ApiError && command.error.status === 409) detail.reload(); }, [command.error, detail.reload]);
  const order = detail.data;
  const shift = useShift(api, order?.area_id ?? '');
  const timezone = shift.data?.timezone ?? 'Asia/Qostanay';
  const responsible = user.role === 'worker' && !!order && (order.assignee_id ?? order.responsible_id) === user.id;
  const allowed = responsible && !!action && !!order?.allowed_actions?.includes(action);
  const valid = allowed && (action !== 'pause' && action !== 'reject' || !!reason.trim());
  const changed = () => { detail.reload(); events.invalidate(); };
  async function apply(event: FormEvent) {
    event.preventDefault(); if (!order || !action || submissionLocked || (!command.pending && !valid)) return;
    const body: OrderAction | undefined = command.pending ? undefined : { action, expected_version: order.version, ...(action === 'pause' || action === 'reject' ? { reason: reason.trim() } : {}) };
    if (await command.run(body)) { setAction(null); setReason(''); changed(); }
  }
  return <section className="page details-page">
    <Link to="/my-orders">← Мои наряды</Link>
    {detail.loading && <p role="status">Загружаем наряд…</p>}
    {detail.error && <p role="alert">{detail.error.message} <button onClick={detail.reload}>Обновить</button></p>}
    {order && <>
      <div className="page-heading"><h2>Наряд {order.number}</h2><span className={`badge priority-${order.priority}`}>{priorities[order.priority]}</span></div>
      <p className="badge">{statuses[order.status]}{order.is_overdue ? ' · Просрочен' : ''}</p><p id={`problem-${order.id}`} className="full-description">{order.description}</p>
      <p>Срок: {displayTime(order.due_at, timezone)} ({timezone})</p>
      {order.brigade_id && <p>{responsible ? 'Ответственный бригады' : 'Наряд бригады · просмотр'}</p>}
      {responsible && <div className="choices" aria-label="Действия исполнителя">{(Object.keys(names) as WorkerAction[]).filter(name => order.allowed_actions?.includes(name)).map(name => <button key={name} disabled={command.busy || command.pending || submissionLocked} onClick={() => { setAction(name); setReason(''); }}>{names[name]}</button>)}</div>}
      {action && <form className="action-form" onSubmit={apply}><h3>{names[action]}</h3>
        <fieldset className="form-fields" disabled={command.busy || command.pending || !allowed}>{(action === 'reject' || action === 'pause') && <label>Причина<textarea name="reason" required maxLength={4000} value={reason} onChange={event => setReason(event.target.value)} rows={2} /></label>}</fieldset>
        {command.error && <p role="alert">{command.error.message}{command.error instanceof ApiError && command.error.status === 409 ? '. Данные перечитаны; проверьте действие.' : ''}</p>}
        {command.pending && <p role="status">Результат неизвестен. Повтор подтвердит ту же команду.</p>}
        <button className="primary" type="submit" disabled={command.busy || submissionLocked || (!command.pending && !valid)}>{command.busy ? 'Сохраняем…' : command.pending ? 'Повторить действие' : 'Применить'}</button>
        {!command.pending && <button type="button" disabled={command.busy} onClick={() => setAction(null)}>Вернуться</button>}
      </form>}
      {responsible && photoStatuses.has(order.status) && <PhotoUpload api={api} orderId={order.id} type="before" disabled={command.busy || command.pending || submissionLocked} onUploaded={() => {}} />}
      {responsible && <SubmissionForm api={api} order={order} disabled={command.busy || command.pending} reload={detail.reload} onSubmitted={changed} onLockChange={setSubmissionLocked} />}
      {order.submission && <div id={`submission-${order.submission.id}`}><SavedSubmission api={api} submission={order.submission} /></div>}
      <IssuancePhotos photos={order.issuance_photos} />
      <NotificationDeliveryPanel api={api} user={user} orderId={order.id} />
      <ReviewPanel order={order} />
      <section aria-label="История наряда"><h3>История</h3><ol className="history">{order.events?.map(item => <li key={item.id}><strong>{names[item.action as WorkerAction] ?? item.action}</strong><time dateTime={item.occurred_at}>{displayTime(item.occurred_at, timezone)}</time>{item.reason && <p>{item.reason}</p>}</li>)}</ol></section>
    </>}
  </section>;
}
