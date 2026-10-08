import { useLocale } from '../../ui/locale';
import type { WorkOrderDetail } from './data';
import { StatusBadge } from '../../ui/components';

const reviewStates = { pending: 'Ожидает проверки', running: 'Проверка выполняется', blocked: 'Проверка недоступна. Требуется решение мастера.', discarded: 'Предыдущая проверка устарела', completed: 'Проверка завершена' };
type ReviewSource = 'provider' | 'rules' | 'prepared' | 'mock' | 'unknown';
const sourceLabels: Record<ReviewSource, string> = { provider: 'Результат ИИ', rules: 'Проверка по правилам', prepared: 'Подготовленный результат', mock: 'Тестовый результат', unknown: 'Источник не подтверждён' };
const preparedOrigin = new Set(['Подготовленный демонстрационный результат', 'MOCK: синтетические рисунки; OpenAI не вызывался.']);
const preparedFindings = new Map([
  ['Описание очистки соответствует заявке; синтетический рисунок после показывает очищенный кожух.', 'Описание очистки соответствует заявке; изображение после показывает очищенный кожух.'],
  ['По синтетическим рисункам нельзя подтвердить полноту очистки кожуха. Видимый результат должен проверить мастер.', 'По изображениям нельзя подтвердить полноту очистки кожуха. Видимый результат должен проверить мастер.'],
]);

export function ReviewPanel({ order }: { order: WorkOrderDetail }) {
  const { tx } = useLocale();
  const review = order.ai_review;
  const result = review?.result;
  const decision = order.master_decision;
  const source = (review as (typeof review & { source?: ReviewSource }))?.source ?? (review?.is_mock ? 'mock' : 'unknown');
  function evidence(ref: string) {
    const photoId = ref.startsWith('photo:') ? ref.slice(6) : '';
    if (photoId && order.submission?.after_photo_ids?.includes(photoId)) return <a href={`/api/v1/photos/${encodeURIComponent(photoId)}`}>{tx("Фото после работы")}</a>;
    if (photoId && order.issuance_photos?.some(photo => photo.id === photoId)) return <a href={`/api/v1/photos/${encodeURIComponent(photoId)}`}>{tx("Фото до работы")}</a>;
    if (ref === 'work_description' && order.submission) return <a href={`#submission-${order.submission.id}`}>{tx("Сохранённый отчёт")}</a>;
    if (ref === 'problem') return <a href={`#problem-${order.id}`}>{tx("Заявка")}</a>;
    return <span>{ref}</span>;
  }
  return <section className="action-form" aria-label={tx("ИИ-проверка работы")}>
    <h3>{tx("ИИ-проверка работы")}</h3>
    {!order.review_status && !review && <p>{tx('Проверка начнётся после отправки отчёта и фото. Решение о приёмке принимает мастер.')}</p>}
    {order.review_status && <p role="status">{tx(reviewStates[order.review_status])}</p>}
    {review && result && <>
      <p className="badge">{tx(sourceLabels[source])}</p>
      <p><StatusBadge domain="verdict" status={result.verdict} />{result.score != null ? (tx(" · Оценка ") + (result.score) + "/5") : tx(" · Оценка не выставлена")}</p>
      <ul>{result.findings.map((finding, index) => <li key={index}><p className="full-description">{source === 'prepared' ? preparedFindings.get(finding.message) ?? finding.message : finding.message}</p>{finding.evidence_refs.length > 0 && <ul aria-label={tx("Доказательства")}>{finding.evidence_refs.map((ref, position) => <li key={position}>{evidence(ref)}</li>)}</ul>}</li>)}</ul>
      {!!result.missing_evidence.length && <p>{tx("Недостающие доказательства: ")}{result.missing_evidence.join(', ')}</p>}
      {source === 'prepared' && <p>{tx('Состояние реального оборудования не подтверждено.')}</p>}
      {result.limitations.filter(limitation => source !== 'prepared' || !preparedOrigin.has(limitation)).map((limitation, index) => <p className="full-description" key={index}>{limitation}</p>)}
      <p><strong>{tx('Следующее действие: ')}</strong>{tx(decision ? 'Решение мастера сохранено.' : result.verdict === 'requires_rework' ? 'Мастеру следует указать причину доработки.' : result.verdict === 'human_review' ? 'Мастеру следует проверить доказательства и принять решение.' : 'Мастеру следует подтвердить приёмку или вернуть работу на доработку.')}</p>
      <details><summary>{tx('Подробности проверки')}</summary>
        <p>{tx(sourceLabels[source])}</p>
        {source === 'prepared' && <><p>{tx('Пример подготовлен заранее; внешний ИИ не вызывался.')}</p><p>{tx('Использованы учебные изображения.')}</p></>}
        <p className="muted">{tx("Модель: ")}{review.model}{tx(" · Версия проверки: ")}{review.prompt_version}</p>
      </details>
    </>}
    {decision && <div><h4>{decision.decision === 'accept' ? tx("Мастер принял работу") : tx("Мастер вернул на доработку")}</h4>{decision.score != null && <p>{tx("Оценка мастера: ")}{decision.score}/5</p>}{decision.reason && <p className="full-description">{decision.reason}</p>}</div>}
  </section>;
}
