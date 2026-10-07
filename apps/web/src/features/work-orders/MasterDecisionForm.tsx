import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { ApiError, type ApiClient, type UserView } from '../../lib/api';
import { useCommand } from '../../lib/useCommand';
import { decideOrder, type MasterDecision, type WorkOrderDetail } from './data';

export function MasterDecisionForm({ api, user, order, reload, onDecided }: { api: ApiClient; user: UserView; order: WorkOrderDetail; reload: () => void; onDecided: () => void }) {
  const result = order.ai_review?.result;
  const [decision, setDecision] = useState<MasterDecision['decision'] | ''>('');
  const [score, setScore] = useState(result?.score == null ? '' : String(result.score));
  const [reason, setReason] = useState('');
  const [conflictOrder, setConflictOrder] = useState<WorkOrderDetail | null>(null);
  const command = useCommand(useCallback((body: MasterDecision, key: string) => decideOrder(api, order.id, body, key), [api, order.id]));
  useEffect(() => {
    setDecision(''); setReason(''); setScore(result?.score == null ? '' : String(result.score));
  }, [order.id, order.version, order.assignment_version, order.submission?.id, order.ai_review?.id]);
  useEffect(() => {
    if (command.error instanceof ApiError && command.error.status === 409) { setConflictOrder(order); setDecision(''); setReason(''); reload(); }
  }, [command.error, reload]);
  useEffect(() => {
    if (conflictOrder && conflictOrder !== order) { setConflictOrder(null); setDecision(''); setReason(''); }
  }, [order, conflictOrder]);
  const choices = (order.allowed_decisions ?? []).filter(value => value !== 'accept' || !order.submission?.missing_evidence?.length);
  const selectedScore = score ? Number(score) : null;
  const acceptedByAI = result?.verdict === 'accepted' || result?.verdict === 'accepted_with_notes';
  const needsReason = decision === 'rework' || decision === 'accept' && (!acceptedByAI || order.status === 'REWORK') || !!result && selectedScore !== result.score;
  const allowed = user.role === 'master' && !!order.submission && (choices.length > 0 || command.pending);
  const valid = allowed && !conflictOrder && !!decision && choices.includes(decision) && (!needsReason || !!reason.trim());
  async function submit(event: FormEvent) {
    event.preventDefault(); if (!allowed || command.busy || (!command.pending && !valid)) return;
    const body: MasterDecision | undefined = command.pending ? undefined : { decision: decision as MasterDecision['decision'], submission_id: order.submission!.id, expected_version: order.version, assignment_version: order.assignment_version, score: selectedScore, reason: reason.trim() || null };
    if (await command.run(body)) { setDecision(''); setReason(''); onDecided(); }
  }
  if (!allowed) return null;
  return <form className="action-form" onSubmit={submit} aria-label="Приёмка мастером">
    <h3>Решение мастера</h3>
    <p>Решение относится к сохранённому отчёту {order.submission!.revision}. ИИ не закрывает наряд.</p>
    <fieldset className="form-fields" disabled={command.busy || command.pending || !!conflictOrder}>
      <label>Решение<select name="decision" value={decision} onChange={event => setDecision(event.target.value as typeof decision)} required><option value="">Выберите решение</option>{choices.map(value => <option key={value} value={value}>{value === 'accept' ? 'Принять и закрыть' : 'Вернуть на доработку'}</option>)}</select></label>
      <label>Оценка<select name="score" value={score} onChange={event => setScore(event.target.value)}><option value="">Без оценки</option>{[1, 2, 3, 4, 5].map(value => <option key={value} value={value}>{value}</option>)}</select></label>
      <label>Объяснение{needsReason ? ' (обязательно)' : ''}<textarea name="decision_reason" value={reason} onChange={event => setReason(event.target.value)} required={needsReason} rows={3} maxLength={4000} /></label>
    </fieldset>
    {command.error && <p role="alert">{command.error.message}{command.error instanceof ApiError && command.error.status === 409 ? '. Дождитесь обновления данных. Выберите решение заново для актуального отчёта.' : ''}</p>}
    {command.pending && <p role="status">Результат неизвестен. Повтор отправит то же решение.</p>}
    <button type="submit" className="primary" disabled={command.busy || (!command.pending && !valid)}>{command.busy ? 'Сохраняем…' : command.pending ? 'Повторить решение' : 'Сохранить решение'}</button>
  </form>;
}
