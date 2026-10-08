import { localizedTemplate, useLocale } from '../../ui/locale';
import { displayOrderDescription, displayFaultCode, displayFixtureName } from '../../lib/displayFixture';
import type { WorkOrderTemplate } from './TemplateRequirements';
import type { ApiClient } from '../../lib/api';
import { useExecutionCatalogs, type Submission } from './data';

const evidenceLabels: Record<string, string> = { after_photo: 'Фото после работы', work_description: 'Описание выполненных работ', fault_code_id: 'Шифр неисправности', materials: 'Сведения о материалах', materials_conflict: 'Согласованность списка материалов и отметки об их отсутствии', invalid_photos: 'Допустимые фото этого наряда' };

export function SavedSubmission({ api, submission, template: source }: { api: ApiClient; submission: Submission; template?: WorkOrderTemplate | null }) {
  const { tx, locale } = useLocale();
  const template = source ? localizedTemplate(source, locale) : null;
  const catalogs = useExecutionCatalogs(api);
  const code = catalogs.data?.codes.find(item => item.id === submission.fault_code_id);
  return <section aria-label={tx("Предыдущий отчёт")}><h3>{tx("Передано на приёмку · отчёт ")}{submission.revision}</h3>
    <p className="full-description">{displayOrderDescription(submission.work_description)}</p>
    <p>{tx("Шифр: ")}{code ? `${displayFaultCode(code.code)} · ${displayFixtureName(code.name)}` : catalogs.loading ? tx("Загружаем…") : tx("Недоступен в справочнике")}</p>
    {submission.no_materials_used ? <p>{tx("Материалы не потребовались")}</p> : <ul>{submission.materials?.map(item => {
      const material = catalogs.data?.materials.find(material => material.id === item.material_id);
      return <li key={item.material_id}>{material?.name ?? tx("Материал недоступен")}: {item.quantity}{material ? ` ${material.unit}` : ''}</li>;
    })}</ul>}
    {submission.after_photo_ids?.map(id => <figure className="saved-photo" key={id}><img src={`/api/v1/photos/${encodeURIComponent(id)}`} alt={tx("Фото после работы из сохранённого отчёта")} /></figure>)}
    {template && <section aria-label={tx("Сохранённый чек-лист")}><h4>{tx("Чек-лист · ")}{template.title}</h4><ul>{template.checklist.map(item => {
      const answer = submission.template_answers?.find(answer => answer.id === item.id);
      return <li key={item.id}>{item.label}: {answer?.checked ? tx("Выполнено") : tx("Не подтверждено")}</li>;
    })}</ul></section>}
    {submission.comment && (submission.comment === 'Синтетическая история, не производственные сведения'
      ? <details><summary>{tx('Происхождение отчёта')}</summary><p>{submission.comment}</p></details>
      : <p>{submission.comment}</p>)}
    {!!submission.missing_evidence?.length && <p>{tx("Недостающие доказательства: ")}{submission.missing_evidence.map(item => tx(evidenceLabels[item] ?? "Дополнительное подтверждение")).join(', ')}</p>}
    {catalogs.error && <p role="alert">{tx("Справочники отчёта недоступны. ")}<button type="button" onClick={catalogs.reload}>{tx("Обновить справочники")}</button></p>}
    <p className="muted">{tx("Отчёт сохранён и не редактируется.")}</p>
  </section>;
}
