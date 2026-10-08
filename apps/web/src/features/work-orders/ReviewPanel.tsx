import { useLocale } from '../../ui/locale';
import type { WorkOrderDetail } from './data';
import { StatusBadge } from '../../ui/components';

const reviewStates = { pending: 'Ожидает проверки', running: 'Проверка выполняется', blocked: 'Проверка недоступна. Требуется решение мастера.', discarded: 'Предыдущая проверка устарела', completed: 'Проверка завершена' };

export function ReviewPanel({ order }: { order: WorkOrderDetail }) {
  const { tx } = useLocale();
  const review = order.ai_review;
  const result = review?.result;
  const decision = order.master_decision;
  function evidence(ref: string) {
    const photoId = ref.startsWith('photo:') ? ref.slice(6) : '';
    if (photoId && order.submission?.after_photo_ids?.includes(photoId)) return <a href={`/api/v1/photos/${encodeURIComponent(photoId)}`}>{tx("Фото после работы")}</a>;
    if (ref === 'work_description' && order.submission) return <a href={`#submission-${order.submission.id}`}>{tx("Сохранённый отчёт")}</a>;
    if (ref === 'problem') return <a href={`#problem-${order.id}`}>{tx("Заявка")}</a>;
    return <span>{ref}</span>;
  }
  if (!order.review_status && !review && !decision) return null;
  return <section className="action-form" aria-label={tx("Результат проверки")}>
    <h3>{tx("Проверка отчёта")}</h3>
    {order.review_status && <p role="status">{tx(reviewStates[order.review_status])}</p>}
    {review && result && <>
      {review.is_mock && <p className="badge">{tx("MOCK · демонстрационный результат")}</p>}
      <p><StatusBadge domain="verdict" status={result.verdict} />{result.score != null ? (tx(" · Оценка ") + (result.score) + "/5") : tx(" · Оценка не выставлена")}</p>
      <ul>{result.findings.map((finding, index) => <li key={index}><p className="full-description">{finding.message}</p>{finding.evidence_refs.length > 0 && <ul aria-label={tx("Доказательства")}>{finding.evidence_refs.map((ref, position) => <li key={position}>{evidence(ref)}</li>)}</ul>}</li>)}</ul>
      {!!result.missing_evidence.length && <p>{tx("Недостающие доказательства: ")}{result.missing_evidence.join(', ')}</p>}
      {result.limitations.map((limitation, index) => <p className="full-description" key={index}>{limitation}</p>)}
      <p className="muted">{tx("Модель: ")}{review.model}{tx(" · Версия проверки: ")}{review.prompt_version}</p>
    </>}
    {decision && <div><h4>{decision.decision === 'accept' ? tx("Мастер принял работу") : tx("Мастер вернул на доработку")}</h4>{decision.score != null && <p>{tx("Оценка мастера: ")}{decision.score}/5</p>}{decision.reason && <p className="full-description">{decision.reason}</p>}</div>}
  </section>;
}
